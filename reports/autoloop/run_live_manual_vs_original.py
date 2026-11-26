"""Compara la configuración viva del 8765 con la referencia original versionada.

Usa exactamente las ventanas de reports/backtest/_windows.py y el dataset real
data/bars.csv. Congela una copia del perfil servido para que un cambio externo
durante la corrida no mezcle configuraciones.

No escribe configuraciones, DB, holdout ni reports/autoloop/resultados_original.jsonl.
Solo escribe la copia de trabajo en logs/ y el JSON de resultados en reports/autoloop/.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "reports" / "backtest"
for path in (ROOT, BT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _manual_common import (  # noqa: E402
    INITIAL_CAPITAL,
    ORIGINAL_FREQUENCY_PATCH,
    ORIGINAL_PATH,
    aggregate,
    load,
    load_original,
    run_windows,
    settings_diff,
)
from _windows import WINDOWS  # noqa: E402

SRC = ROOT / "profiles/live_8765/config.json"
REFERENCE = ROOT / "reports/autoloop/resultados_original.jsonl"
OUT = ROOT / "reports/autoloop/live_manual_vs_original_20261126.json"
API_CONFIG = ROOT / "logs/8765_config_live_20261126.json"
API_STATUS = ROOT / "logs/8765_status_live_20261126.json"
API_STATS = ROOT / "logs/8765_stats_live_20261126.json"
BARS = ROOT / "data/bars.csv"

INITIAL = 25_000.0
NAMES = ["original", "manual_live", "manual_next_open", "p1_5_200_210_24"]


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def close(a: float, b: float, tol: float = 0.05) -> bool:
    return abs(float(a) - float(b)) <= tol


def same_pf(a, b) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= 0.01


def metrics_for(metrics: dict) -> dict:
    net = round(float(metrics.get("net_profit") or 0.0), 2)
    return {
        "trades": int(metrics.get("trades") or 0),
        "net_pnl": net,
        "return_pct": round(net / INITIAL * 100.0, 4),
        "max_drawdown": round(float(metrics.get("max_drawdown") or 0.0), 2),
        "profit_factor": metrics.get("profit_factor"),
        "win_rate": metrics.get("win_rate"),
        "fees": round(float(metrics.get("fees") or 0.0), 2),
    }


def main() -> int:
    started = time.perf_counter()
    src_before = sha256(SRC)
    ref_before = sha256(REFERENCE)
    snapshot = ROOT / "logs" / f"live_manual_profile_{src_before[:12]}.json"
    snapshot.write_bytes(SRC.read_bytes())
    snap_hash = sha256(snapshot)
    if snap_hash != src_before:
        raise RuntimeError("La copia del perfil vivo no coincide con el config servido")

    current = load(snapshot)
    original = load_original()
    diff = settings_diff(current, original)

    variants = {
        "original": (ORIGINAL_PATH, ORIGINAL_FREQUENCY_PATCH),
        "manual_live": (snapshot, {}),
        "manual_next_open": (snapshot, {"execution": {"fill_model": "next_open"}}),
        # P1: 5/200/210/24, TP3, or_mid/close, next_open; el perfil original
        # ya tiene 5/200 y TP3, solo se fija la frecuencia 210/24.
        "p1_5_200_210_24": (
            ORIGINAL_PATH,
            {"strategy": {"setup_validity_minutes": 210, "retest_tolerance_ticks": 24}},
        ),
    }
    ordered = run_windows(variants, dataset_base=snapshot, workers=6)
    agg = aggregate(ordered, NAMES)

    reference = read_json(REFERENCE)
    fixed = {
        "trades": int(reference["trades"]),
        "net": float(reference["net"]),
        "max_drawdown": float(reference["dd"]),
        "profit_factor": reference["pf"],
    }
    obtained = agg["original"]["stats"]
    if obtained["trades"] != fixed["trades"]:
        raise AssertionError(f"original trades {obtained['trades']} != {fixed['trades']}")
    if not close(obtained["net_profit"], fixed["net"]):
        raise AssertionError(f"original net {obtained['net_profit']} != {fixed['net']}")
    if not close(obtained["max_drawdown"], fixed["max_drawdown"], 1.0):
        raise AssertionError(
            f"original DD {obtained['max_drawdown']} != {fixed['max_drawdown']}"
        )
    if not same_pf(obtained["profit_factor"], fixed["profit_factor"]):
        raise AssertionError(
            f"original PF {obtained['profit_factor']} != {fixed['profit_factor']}"
        )

    for block in ordered:
        window = block["window"]
        expected = reference["windows"][window]
        got = block["variants"]["original"]["metrics"]
        if int(got["trades"]) != int(expected["trades"]):
            raise AssertionError(f"{window} original trades mismatch")
        if not close(got["net_profit"], expected["net"]):
            raise AssertionError(f"{window} original net mismatch")
        if not close(got["max_drawdown"], expected["dd"], 1.0):
            raise AssertionError(f"{window} original DD mismatch")
        if not same_pf(got["profit_factor"], expected["pf"]):
            raise AssertionError(f"{window} original PF mismatch")

    windows = []
    for block in ordered:
        windows.append(
            {
                "window": block["window"],
                "sessions": block["sessions"],
                "first": block["first"],
                "last": block["last"],
                "variants": {
                    name: metrics_for(block["variants"][name]["metrics"])
                    for name in NAMES
                },
            }
        )

    aggregate_out = {}
    for name in NAMES:
        stats = agg[name]["stats"]
        net = round(float(stats["net_profit"]), 2)
        aggregate_out[name] = {
            "trades": int(stats["trades"]),
            "net_pnl": net,
            "return_pct": round(net / INITIAL * 100.0, 4),
            "max_drawdown": round(float(stats["max_drawdown"]), 2),
            "max_drawdown_pct": stats["max_drawdown_pct"],
            "profit_factor": stats["profit_factor"],
            "win_rate": stats["win_rate"],
            "expectancy": stats["expectancy"],
            "fees": stats["fees"],
            "avg_r": stats["avg_r"],
            "max_qty": agg[name]["max_qty"],
            "net_by_window": agg[name]["net_by_window"],
        }

    status = read_json(API_STATUS)
    api_config = read_json(API_CONFIG)
    live_stats = read_json(API_STATS)
    session = status.get("session") or {}
    risk = status.get("risk") or {}
    live_state = {
        "captured_server_time": status.get("server_time"),
        "status": status.get("status"),
        "mode": status.get("mode"),
        "instrument": status.get("instrument"),
        "session_date": session.get("date"),
        "equity": risk.get("equity"),
        "initial_capital": (api_config.get("settings", {}).get("risk", {}) or {}).get(
            "initial_capital"
        ),
        "trades": live_stats.get("trades"),
        "net_profit": live_stats.get("net_profit"),
        "max_drawdown": live_stats.get("max_drawdown"),
        "max_drawdown_pct": live_stats.get("max_drawdown_pct"),
        "open_position": status.get("position") is not None,
        "trades_today": risk.get("trades_today"),
        "daily_pnl": risk.get("daily_pnl"),
    }

    src_after = sha256(SRC)
    ref_after = sha256(REFERENCE)
    if src_after != src_before:
        raise RuntimeError("El perfil vivo cambió durante la corrida")
    if ref_after != ref_before:
        raise RuntimeError("resultados_original.jsonl cambió durante la corrida")

    payload = {
        "schema": "live-manual-vs-original-20261126-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_profile": str(SRC.relative_to(ROOT)),
        "source_profile_sha256_before": src_before,
        "source_profile_sha256_after": src_after,
        "snapshot": str(snapshot.relative_to(ROOT)),
        "snapshot_sha256": snap_hash,
        "scope": {
            "windows": [spec[0] for spec in WINDOWS],
            "sessions": sum(block["sessions"] for block in ordered),
            "start": ordered[0]["first"],
            "last": ordered[-1]["last"],
            "dataset": "data/bars.csv",
            "dataset_sha256": sha256(BARS),
            "initial_capital": INITIAL,
            "holdout_used": False,
        },
        "reference": {
            "path": "reports/autoloop/resultados_original.jsonl",
            "sha256_before": ref_before,
            "sha256_after": ref_after,
            "fixed": fixed,
            "matched_by_harness": True,
        },
        "live_state": {
            "api_config_path": str(API_CONFIG.relative_to(ROOT)),
            "api_config_sha256": sha256(API_CONFIG),
            "api_status_path": str(API_STATUS.relative_to(ROOT)),
            "api_status_sha256": sha256(API_STATUS),
            "api_stats_path": str(API_STATS.relative_to(ROOT)),
            "api_stats_sha256": sha256(API_STATS),
            "state": live_state,
            "settings": api_config.get("settings", {}),
        },
        "config_diff_manual_live_vs_original": diff,
        "variants": {
            "original": "ORIGINAL_PATH + ORIGINAL_FREQUENCY_PATCH (150/12)",
            "manual_live": "profiles/live_8765/config.json, fill_model=signal_price",
            "manual_next_open": "same live config, fill_model=next_open for fair fill",
            "p1_5_200_210_24": "5/200/210/24, TP3, or_mid/close, next_open (P1)",
        },
        "windows": windows,
        "aggregate": aggregate_out,
        "constraints": {
            "config_written": False,
            "db_written": False,
            "holdout_accessed": False,
            "original_results_written": False,
            "process_touched": False,
            "reprice_rerun": False,
            "tracked_artifacts_written": False,
        },
        "seconds": round(time.perf_counter() - started, 1),
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        json.dumps(
            {
                "out": str(OUT.relative_to(ROOT)),
                "source_sha256": src_before,
                "reference_sha256": ref_before,
                "fixed": fixed,
                "live_state": live_state,
                "aggregate": aggregate_out,
                "seconds": payload["seconds"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
