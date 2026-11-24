"""Panel de observación de solo lectura del forward.

Lee exclusivamente artefactos (`window.json`, ledgers, sesiones selladas y
exports). No importa el motor, no abre la SQLite de ningún brazo y no tiene
rutas de escritura: cualquier método distinto de GET/HEAD responde 405.
"""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any

import uvicorn

from .identity import GENESIS, now_utc
from .ledger import LedgerError, canonical_bytes, derive_status, read_records, verify_chain
from .paths import FORWARD_ROOT, PANEL_PORT, arm_dir, window_dir

READ_ONLY = True


def _hash(value: Any) -> str:
    import hashlib

    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _file_sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _session_hash(record: dict[str, Any]) -> str:
    payload = {key: value for key, value in record.items() if key != "session_sha256"}
    return _hash(payload)


def _safe_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None
    return value if isinstance(value, dict) else None


def _arm_summary(window_id: str, arm: str, initial: float) -> dict[str, Any]:
    base = arm_dir(window_id, arm)
    snapshot = _safe_json(base / "profile" / "snapshot.json") or {}
    chain_problems: list[str] = []
    try:
        records = read_records(base / "ledger.jsonl")
        chain_problems = verify_chain(records)
    except LedgerError as exc:
        records = []
        chain_problems = [str(exc)]

    sessions: list[dict[str, Any]] = []
    hash_problems: list[str] = []
    folder = base / "sessions"
    for path in sorted(folder.glob("*.json")) if folder.exists() else []:
        record = _safe_json(path)
        if record is None:
            hash_problems.append(f"{path.name}: JSON inválido")
            continue
        if record.get("session_sha256") != _session_hash(record):
            hash_problems.append(f"{path.name}: session_sha256 no coincide")
        if record.get("valid"):
            for key, name in (
                ("trades_sha256", "trades.jsonl"),
                ("equity_sha256", "equity.csv"),
                ("signals_sha256", "signals.jsonl"),
            ):
                artifact = folder / path.stem / name
                if not artifact.exists():
                    hash_problems.append(f"{path.stem}/{name}: ausente")
                elif record.get("artifacts", {}).get(key) != _file_sha256(artifact):
                    hash_problems.append(f"{path.stem}/{name}: sha256 no coincide")
        sessions.append(record)

    valid_sessions = [item for item in sessions if item.get("valid")]
    last = valid_sessions[-1] if valid_sessions else None
    trades_total = sum(int(item.get("trades", {}).get("count") or 0) for item in valid_sessions)
    net_total = round(
        sum(float(item.get("trades", {}).get("net_pnl") or 0.0) for item in valid_sessions), 2
    )
    signals_total = sum(int(item.get("signals", {}).get("count") or 0) for item in valid_sessions)
    equity = float((last or {}).get("cumulative", {}).get("equity") or initial)
    max_dd = max(
        [float(item.get("cumulative", {}).get("max_drawdown") or 0.0) for item in valid_sessions]
        or [0.0]
    )

    super_records: list[dict[str, Any]] = []
    super_problems: list[str] = []
    try:
        super_records = read_records(base / "supervisor.jsonl")
        super_problems = verify_chain(super_records)
    except LedgerError as exc:
        super_problems = [str(exc)]

    violations = [
        {"seq": item.get("seq"), "ts": item.get("ts"), "detail": item.get("detail")}
        for item in records
        if item.get("event") == "VIOLATION"
    ]
    integrity_failures = [
        {"seq": item.get("seq"), "ts": item.get("ts"), "detail": item.get("detail")}
        for item in records
        if item.get("event") == "INTEGRITY_FAIL"
    ]
    restarts = [
        item for item in super_records if item.get("event") == "ARM_RESTART"
    ]
    status = derive_status(records)
    if chain_problems:
        status = "NO_VALIDA"
    config_path = base / "profile" / "config.json"
    current_config = _file_sha256(config_path) if config_path.exists() else None
    config_ok = current_config == snapshot.get("config_file_sha256")

    return {
        "arm": arm,
        "status": status,
        "chain_ok": not chain_problems and not super_problems,
        "chain_problems": chain_problems + super_problems,
        "hash_ok": not hash_problems and not chain_problems and config_ok,
        "hash_problems": hash_problems,
        "config_ok": config_ok,
        "config_file_sha256_current": current_config,
        "sessions_sealed": len(sessions),
        "sessions_valid": len(valid_sessions),
        "last_session": (last or {}).get("session"),
        "signals_total": signals_total,
        "trades_total": trades_total,
        "net_pnl": net_total,
        "equity": round(equity, 2),
        "max_drawdown": round(max_dd, 2),
        "config_file_sha256": snapshot.get("config_file_sha256"),
        "code_sha256": snapshot.get("code_sha256"),
        "events": len(records),
        "last_event": (
            {"event": records[-1].get("event"), "seq": records[-1].get("seq"),
             "ts": records[-1].get("ts")}
            if records
            else None
        ),
        "violations": violations,
        "integrity_failures": integrity_failures,
        "supervisor": {
            "events": len(super_records),
            "restarts": len(restarts),
            "last_event": (super_records[-1].get("event") if super_records else None),
        },
    }


def summarize_window(root: Path) -> dict[str, Any]:
    window = _safe_json(root / "window.json")
    if window is None:
        return {"window_id": root.name, "status": "NO_VALIDA", "error": "window.json inválido"}
    arms: dict[str, Any] = {}
    for arm in (window.get("arms") or {}):
        initial = 25000.0
        snapshot = _safe_json(arm_dir(root.name, arm) / "profile" / "snapshot.json")
        if snapshot and snapshot.get("initial_capital"):
            initial = float(snapshot["initial_capital"])
        arms[arm] = _arm_summary(root.name, arm, initial)
    statuses = [item["status"] for item in arms.values()]
    if "NO_VALIDA" in statuses:
        status = "NO_VALIDA"
    elif "DETENIDA" in statuses:
        status = "DETENIDA"
    elif "ACTIVA" in statuses:
        status = "ACTIVA"
    else:
        status = "INICIADA"
    return {
        "window": window,
        "window_id": window.get("window_id"),
        "status": status,
        "arms": arms,
        "generated_at": now_utc(),
        "read_only": READ_ONLY,
    }


def summarize_all(root: Path = FORWARD_ROOT) -> list[dict[str, Any]]:
    if not root.exists():
        return []
    return [
        summarize_window(path)
        for path in sorted(root.iterdir())
        if path.is_dir() and (path / "window.json").exists()
    ]


def _html(summaries: list[dict[str, Any]]) -> str:
    blocks: list[str] = []
    for summary in summaries:
        window = summary.get("window") or {}
        rows = []
        for arm, info in (summary.get("arms") or {}).items():
            bad = " class='bad'" if info["status"] == "NO_VALIDA" else ""
            rows.append(
                "<tr>"
                f"<td>{html.escape(arm)}</td>"
                f"<td{bad}>{html.escape(info['status'])}</td>"
                f"<td>{info['sessions_valid']}/{info['sessions_sealed']}</td>"
                f"<td>{info['signals_total']}</td>"
                f"<td>{info['trades_total']}</td>"
                f"<td>{info['net_pnl']:.2f}</td>"
                f"<td>{info['equity']:.2f}</td>"
                f"<td>{info['max_drawdown']:.2f}</td>"
                f"<td>{'OK' if info['chain_ok'] else 'ROTO'}</td>"
                f"<td>{'OK' if info['hash_ok'] else 'ROTO'}</td>"
                f"<td>{len(info['violations'])}</td>"
                f"<td>{len(info['integrity_failures'])}</td>"
                "</tr>"
            )
        events = []
        for arm, info in (summary.get("arms") or {}).items():
            for violation in info["violations"]:
                events.append(
                    f"<li><b>{html.escape(arm)}</b> VIOLATION seq {violation['seq']} "
                    f"· {html.escape(json.dumps(violation['detail'], ensure_ascii=False))}</li>"
                )
            for failure in info["integrity_failures"]:
                events.append(
                    f"<li><b>{html.escape(arm)}</b> INTEGRITY_FAIL seq {failure['seq']} "
                    f"· {html.escape(json.dumps(failure['detail'], ensure_ascii=False))}</li>"
                )
        blocks.append(
            f"<section><h2>{html.escape(str(window.get('window_id')))} "
            f"<span class='bad'>{html.escape(summary['status'])}</span></h2>"
            f"<p class='meta'>kind={html.escape(str(window.get('kind')))} · "
            f"inicio={html.escape(str(window.get('start_date')))} · "
            f"{html.escape(str(window.get('note') or ''))}</p>"
            "<table><thead><tr><th>Brazo</th><th>Estado</th><th>Sesiones</th>"
            "<th>Señales</th><th>Trades</th><th>Neto</th><th>Equity</th><th>DD</th>"
            "<th>Cadena</th><th>Hashes</th><th>Violaciones</th><th>Integridad</th>"
            "</tr></thead><tbody>"
            + "".join(rows)
            + "</tbody></table><ul class='events'>"
            + ("".join(events) or "<li>Sin incidentes registrados</li>")
            + "</ul></section>"
        )
    return (
        "<!doctype html><html lang='es'><head><meta charset='utf-8'>"
        "<title>Forward · solo lectura</title><style>"
        "body{background:#0b0e13;color:#e6ebf2;font-family:system-ui;padding:24px}"
        "h1{font-size:20px}section{border:1px solid #1e2735;border-radius:10px;"
        "padding:16px;margin:16px 0;background:#111722}"
        "table{width:100%;border-collapse:collapse;font-size:13px}"
        "th,td{padding:6px 8px;border-bottom:1px solid #1e2735;text-align:right}"
        "th:first-child,td:first-child{text-align:left}"
        ".bad{color:#ff6b6b}.meta{color:#8a97a8;font-size:12px}"
        ".events{font-size:12px;color:#ffb3b3;line-height:1.7}"
        ".readonly{display:inline-block;padding:2px 8px;border-radius:999px;"
        "background:#17301f;color:#3ddc97;font-size:11px}"
        "</style></head><body><h1>Forward · panel de solo lectura "
        "<span class='readonly'>sin escritura</span></h1>"
        "<p class='meta'>Lee artefactos sellados. No habla con el motor.</p>"
        + ("".join(blocks) or "<p>No hay ventanas forward.</p>")
        + "</body></html>"
    )


def build_app(root: Path = FORWARD_ROOT):
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, JSONResponse

    app = FastAPI(
        title="YED forward panel (read-only)",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.middleware("http")
    async def read_only(request: Request, call_next):
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return JSONResponse(
                status_code=405,
                content={"detail": "panel de solo lectura: método no permitido"},
            )
        return await call_next(request)

    @app.get("/api/forward/summary")
    def summary() -> dict[str, Any]:
        return {"read_only": READ_ONLY, "windows": summarize_all(root)}

    @app.get("/api/forward/windows/{window_id}")
    def one(window_id: str) -> Any:
        path = window_dir(window_id)
        if not (path / "window.json").exists():
            return JSONResponse(status_code=404, content={"detail": "ventana no encontrada"})
        return summarize_window(path)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return _html(summarize_all(root))

    return app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Panel forward de solo lectura.")
    parser.add_argument("--port", type=int, default=PANEL_PORT)
    parser.add_argument("--host", default="127.0.0.1")
    args = parser.parse_args(argv)
    uvicorn.run(build_app(), host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
