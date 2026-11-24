"""Cierre de sesión forward: verificación de integridad y export sellado.

El cierre es idempotente por fecha: una sesión ya sellada no se reescribe. Si
la identidad T0 no coincide, la sesión se escribe como inválida y el ledger
registra `INTEGRITY_FAIL`; la ventana queda NO_VÁLIDA.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any

from .identity import GENESIS, now_utc, read_snapshot, verify_snapshot
from .ledger import Ledger, canonical_bytes, derive_status, read_records, verify_chain
from .loader import ForwardIntegrityError, load_strict
from .paths import (
    arm_dir,
    ledger_path,
    profile_dir,
    sessions_dir,
    validate_arm,
    validate_window_id,
)
from server.timeutil import et_date_str

SESSION_SCHEMA = "forward-session-v1"
TRACE_FIELDS = (
    "id, mode, signal_id, direction, qty, entry_ts, exit_ts, pnl, "
    "r_multiple, exit_reason"
)


def _read_trades(db_path: Path) -> list[dict[str, Any]]:
    if not db_path.exists():
        return []
    uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                f"SELECT {TRACE_FIELDS} FROM trades WHERE mode = 'paper' ORDER BY exit_ts"
            ).fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return []
    return [dict(row) for row in rows]


def _trade_day(trade: dict[str, Any]) -> str:
    try:
        return et_date_str(int(trade.get("exit_ts") or 0))
    except Exception:  # noqa: BLE001
        return ""


def _curve(trades: list[dict[str, Any]], initial: float) -> tuple[list[dict[str, Any]], float]:
    equity = float(initial)
    peak = equity
    max_dd = 0.0
    rows = [{"seq": 0, "ts": "", "equity": equity, "peak": peak, "drawdown": 0.0}]
    for index, trade in enumerate(trades, start=1):
        equity += float(trade.get("pnl") or 0.0)
        peak = max(peak, equity)
        drawdown = peak - equity
        max_dd = max(max_dd, drawdown)
        rows.append(
            {
                "seq": index,
                "ts": int(trade.get("exit_ts") or 0),
                "equity": equity,
                "peak": peak,
                "drawdown": drawdown,
            }
        )
    return rows, max_dd


def _profit_factor(pnls: list[float]) -> float | None:
    gross_win = sum(value for value in pnls if value > 0)
    gross_loss = abs(sum(value for value in pnls if value < 0))
    if gross_loss == 0:
        return None
    return round(gross_win / gross_loss, 4)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False) + "\n")


def _write_curve(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=["seq", "ts", "equity", "peak", "drawdown"], lineterminator="\n"
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    path.write_text(buffer.getvalue(), encoding="utf-8", newline="\n")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _session_hash(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "session_sha256"}
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def _previous_session_hash(folder: Path, current: str) -> str:
    entries = sorted(path for path in folder.glob("*.json") if path.stem < current)
    if not entries:
        return GENESIS
    try:
        value = json.loads(entries[-1].read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return GENESIS
    return str(value.get("session_sha256") or GENESIS)


def _signals_for(arm_path: Path, session_date: str) -> list[dict[str, Any]]:
    path = arm_path / "signals.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and str(value.get("session") or "") == session_date:
            rows.append(value)
    return rows


def close_session(
    *,
    window_id: str,
    arm: str,
    session_date: str,
    note: str = "",
) -> dict[str, Any]:
    window_id = validate_window_id(window_id)
    arm = validate_arm(arm)
    profile = profile_dir(window_id, arm)
    arm_path = arm_dir(window_id, arm)
    snapshot = read_snapshot(profile)
    ledger = Ledger(ledger_path(window_id, arm), window_id, arm)

    folder = sessions_dir(window_id, arm)
    folder.mkdir(parents=True, exist_ok=True)
    session_file = folder / f"{session_date}.json"
    if session_file.exists():
        return {
            "ok": False,
            "reason": f"la sesión {session_date} ya está sellada",
            "session_file": str(session_file),
        }

    problems = verify_snapshot(profile, snapshot)
    if not problems:
        try:
            load_strict(profile, snapshot)
        except ForwardIntegrityError as exc:
            problems = list(exc.problems)

    previous = _previous_session_hash(folder, session_date)
    if problems:
        record: dict[str, Any] = {
            "schema": SESSION_SCHEMA,
            "window_id": window_id,
            "arm": arm,
            "session": session_date,
            "closed_at": now_utc(),
            "valid": False,
            "reason": "integridad T0",
            "integrity_problems": problems,
            "note": note,
            "artifacts": {},
            "config_file_sha256": str(snapshot.get("config_file_sha256") or ""),
            "code_sha256": str(snapshot.get("code_sha256") or ""),
            "prev_session_sha256": previous,
        }
        record["session_sha256"] = _session_hash(record)
        _write_json(session_file, record)
        ledger.append(
            "INTEGRITY_FAIL",
            {
                "stage": "session_close",
                "session": session_date,
                "problems": problems,
                "session_file": str(session_file),
            },
        )
        ledger.append(
            "SESSION_CLOSED",
            {
                "session": session_date,
                "valid": False,
                "session_sha256": record["session_sha256"],
            },
        )
        status = derive_status(read_records(ledger.path))
        return {
            "ok": True,
            "valid": False,
            "window_status": status,
            "session_file": str(session_file),
            "problems": problems,
        }

    initial = float(snapshot.get("initial_capital") or 25000.0)
    trades = _read_trades(profile / "yedbot.db")
    day_trades = [trade for trade in trades if _trade_day(trade) == session_date]
    up_to = [trade for trade in trades if _trade_day(trade) <= session_date]
    curve, max_dd = _curve(up_to, initial)
    day_pnls = [float(trade.get("pnl") or 0.0) for trade in day_trades]
    up_to_pnls = [float(trade.get("pnl") or 0.0) for trade in up_to]
    signals = _signals_for(arm_path, session_date)

    artifact_dir = folder / session_date
    artifact_dir.mkdir(parents=True, exist_ok=True)
    trades_path = artifact_dir / "trades.jsonl"
    equity_path = artifact_dir / "equity.csv"
    signals_path = artifact_dir / "signals.jsonl"
    _write_jsonl(trades_path, day_trades)
    _write_curve(equity_path, curve)
    _write_jsonl(signals_path, signals)

    record = {
        "schema": SESSION_SCHEMA,
        "window_id": window_id,
        "arm": arm,
        "session": session_date,
        "closed_at": now_utc(),
        "valid": True,
        "reason": "",
        "note": note,
        "trades": {
            "count": len(day_trades),
            "net_pnl": round(sum(day_pnls), 2),
            "wins": sum(1 for value in day_pnls if value > 0),
            "losses": sum(1 for value in day_pnls if value < 0),
            "profit_factor": _profit_factor(day_pnls),
        },
        "cumulative": {
            "trades": len(up_to),
            "net_pnl": round(sum(up_to_pnls), 2),
            "expected_equity": round(initial + sum(up_to_pnls), 2),
            "equity": round(float(curve[-1]["equity"]), 2),
            "peak": round(float(curve[-1]["peak"]), 2),
            "max_drawdown": round(max_dd, 2),
        },
        "signals": {"count": len(signals)},
        "artifacts": {
            "trades_sha256": _file_hash(trades_path),
            "equity_sha256": _file_hash(equity_path),
            "signals_sha256": _file_hash(signals_path),
        },
        "config_file_sha256": str(snapshot.get("config_file_sha256") or ""),
        "code_sha256": str(snapshot.get("code_sha256") or ""),
        "prev_session_sha256": previous,
    }
    record["session_sha256"] = _session_hash(record)
    _write_json(session_file, record)
    ledger.append(
        "SESSION_CLOSED",
        {
            "session": session_date,
            "valid": True,
            "session_sha256": record["session_sha256"],
            "trades": record["trades"]["count"],
            "net_pnl": record["trades"]["net_pnl"],
            "equity": record["cumulative"]["equity"],
            "max_drawdown": record["cumulative"]["max_drawdown"],
        },
    )
    status = derive_status(read_records(ledger.path))
    return {
        "ok": True,
        "valid": True,
        "window_status": status,
        "session_file": str(session_file),
        "record": record,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sella una sesión forward.")
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument(
        "--date",
        default=et_date_str(int(__import__("time").time())),
        help="Fecha de sesión en ET (YYYY-MM-DD).",
    )
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)
    try:
        result = close_session(
            window_id=args.window_id,
            arm=args.arm,
            session_date=args.date,
            note=args.note,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"FORWARD_SESSION_FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
