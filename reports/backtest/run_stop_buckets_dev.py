"""Diagnóstico de stops profundos sobre W1-W6.

Compara el baseline (cap 200) con el control de cap 600 y la entrada directa
con cap 600. No toca la configuración activa ni el holdout.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.backtest import run_presets  # noqa: E402
from server.config import Settings  # noqa: E402
from server.confirmatory import compute_code_hash, settings_sha256, sha256_file  # noqa: E402

OUT = ROOT / "reports/backtest/stop_buckets_dev.json"
CSV_OUT = ROOT / "reports/backtest/stop_buckets_dev.csv"
LOCK_PATH = ROOT / "docs/protocolo_backtest.lock.json"
DATASET_PATH = ROOT / "data/real/bars_mnq_nq_es_1m.csv"
PRESETS = ("sl_cap_600", "direct_sl_cap_600")
HOLDOUT_PATHS = (
    ROOT / "reports/backtest/holdout.json",
    ROOT / "reports/backtest/holdout.seal.json",
    ROOT / "reports/backtest/holdout.ledger.jsonl",
    ROOT / "reports/backtest/holdout.receipt.json",
)
STOP_RE = re.compile(r"Stop de ([0-9]+(?:\.[0-9]+)?) ticks")


def _lock() -> dict:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _holdout_snapshot() -> dict:
    return {
        str(path.relative_to(ROOT)).replace("\\", "/"): (
            sha256_file(path) if path.exists() else None
        )
        for path in HOLDOUT_PATHS
    }


def _bucket(ticks: float | None) -> str:
    if ticks is None:
        return "desconocido"
    if ticks <= 200:
        return "0-200"
    if ticks <= 500:
        return "201-500"
    if ticks <= 600:
        return "501-600"
    return ">600"


def _stop_ticks(record: dict) -> tuple[float | None, str]:
    signal = record.get("signal") or {}
    value = signal.get("stop_ticks")
    if isinstance(value, (int, float)):
        return float(value), "signal"
    risk = record.get("risk") or {}
    value = risk.get("stop_ticks")
    if isinstance(value, (int, float)) and value > 0:
        return float(value), "risk"
    if record.get("reject_code") == "stop_cap":
        match = STOP_RE.search(record.get("reject_detail") or "")
        if match:
            return float(match.group(1)), "stop_cap"
    return None, "unknown"


def _outcome(record: dict, ticks: float | None) -> tuple[str, str]:
    if record.get("traded"):
        return "trade", ""
    if record.get("reject_code") == "stop_cap":
        return "stop_cap", record.get("reject_detail") or ""
    risk = record.get("risk") or {}
    if risk and risk.get("ok") is False:
        if int(risk.get("qty") or 0) < 1 and ticks is not None and ticks > 0:
            return "qty_zero", risk.get("reason") or ""
        return "other_risk", risk.get("reason") or ""
    if record.get("signal"):
        return "not_executed", ""
    return "no_signal", ""


def _run_window(window: dict) -> dict:
    settings = Settings.model_validate(_lock()["settings"])
    started = time.perf_counter()
    payload = run_presets(
        settings,
        days=window["sessions"],
        presets=list(PRESETS),
        start=date.fromisoformat(window["start"]),
        allow_holdout=False,
    )
    full_runs = {}
    for result in payload["results"]:
        key = result["preset"]
        full = result
        if full["dataset"]["sessions"]["count"] != window["sessions"]:
            raise RuntimeError(
                f"{window['id']}/{key}: {full['dataset']['sessions']['count']} sesiones"
            )
        last = (full["dataset"]["selected_range"].get("last_et") or "")[:10]
        if last > "2026-06-30" or last > _lock()["holdout"]["start"]:
            raise RuntimeError(f"{window['id']}/{key}: fin {last} toca el holdout")
        rows = []
        for record in full.get("funnel", {}).get("sessions", []):
            ticks, source = _stop_ticks(record)
            outcome, reason = _outcome(record, ticks)
            signal = record.get("signal") or {}
            rows.append(
                {
                    "window": window["id"],
                    "preset": key,
                    "date": record.get("date"),
                    "direction": (record.get("breakout") or {}).get("direction"),
                    "stop_ticks": None if ticks is None else round(ticks, 1),
                    "stop_source": source,
                    "bucket": _bucket(ticks),
                    "signal_created": bool(signal),
                    "traded": bool(record.get("traded")),
                    "qty": (record.get("risk") or {}).get("qty"),
                    "risk_ok": (record.get("risk") or {}).get("ok"),
                    "outcome": outcome,
                    "reason": reason,
                    "reject_code": record.get("reject_code"),
                }
            )
        full_runs[key] = {
            "preset": key,
            "label": full.get("preset_label"),
            "description": full.get("preset_description"),
            "trades": full["metrics"]["trades"],
            "signals": full["metrics"].get("signals", 0),
            "stop_cap_sessions": full["metrics"].get("stop_cap_sessions", 0),
            "qty_zero_sessions": full["metrics"].get("qty_zero_sessions", 0),
            "avg_stop_ticks": full["metrics"].get("avg_stop_ticks"),
            "rows": rows,
        }
    return {
        "window": window["id"],
        "start": window["start"],
        "end": window["end"],
        "sessions": payload["sessions"],
        "code": payload["results"][0]["dataset"]["code"],
        "dataset_id": payload["dataset_id"],
        "elapsed_s": round(time.perf_counter() - started, 1),
        "presets": full_runs,
    }


def _counts(rows: list[dict]) -> dict:
    buckets = {}
    for bucket in ("0-200", "201-500", "501-600", ">600", "desconocido"):
        selected = [row for row in rows if row["bucket"] == bucket]
        if not selected and bucket == "desconocido":
            continue
        buckets[bucket] = {
            "candidates": len(selected),
            "signals": sum(1 for row in selected if row["signal_created"]),
            "stop_cap_candidates": sum(1 for row in selected if row["outcome"] == "stop_cap"),
            "trade": sum(1 for row in selected if row["outcome"] == "trade"),
            "qty_zero": sum(1 for row in selected if row["outcome"] == "qty_zero"),
            "stop_cap": sum(1 for row in selected if row["outcome"] == "stop_cap"),
            "other_risk": sum(1 for row in selected if row["outcome"] == "other_risk"),
            "not_executed": sum(1 for row in selected if row["outcome"] == "not_executed"),
            "no_signal": sum(1 for row in selected if row["outcome"] == "no_signal"),
        }
    return buckets


def main() -> int:
    lock = _lock()
    settings = Settings.model_validate(lock["settings"])
    expected = json.loads(json.dumps(lock["settings"]))
    if expected["strategy"].get("or_retracement_pct") is None:
        expected["strategy"]["or_retracement_pct"] = settings.strategy.or_retracement_pct
    assert settings.model_dump() == expected, "Configuración distinta del lock"
    assert settings.risk.max_sl_ticks == 200
    assert settings.feed.series_mode == "raw"
    assert settings.feed.csv_path.endswith("bars_mnq_nq_es_1m.csv")
    dataset_before = sha256_file(DATASET_PATH)
    holdout_before = _holdout_snapshot()
    code_hash, code_files = compute_code_hash(ROOT, [ROOT / "server", ROOT / "tests"])
    print(f"Código {code_hash} ({code_files} archivos)", flush=True)
    print(f"Dataset {dataset_before}", flush=True)
    print(f"Holdout antes: {holdout_before}", flush=True)

    started = time.perf_counter()
    windows = []
    with ProcessPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(_run_window, window): window for window in lock["windows"]}
        for future in as_completed(futures):
            window = futures[future]
            try:
                result = future.result()
            except Exception:
                print(f"[{window['id']}] FALLÓ", flush=True)
                traceback.print_exc()
                return 1
            windows.append(result)
            print(f"[{window['id']}] {result['elapsed_s']}s", flush=True)

    windows.sort(key=lambda item: item["id"])
    dataset_after = sha256_file(DATASET_PATH)
    holdout_after = _holdout_snapshot()
    if dataset_before != dataset_after:
        raise RuntimeError("El dataset cambió durante el diagnóstico")
    if holdout_before != holdout_after or any(path.exists() for path in HOLDOUT_PATHS):
        raise RuntimeError("Se tocó o creó un artefacto de holdout")

    presets = {}
    for key in ("baseline", *PRESETS):
        all_rows = [
            row
            for window in windows
            for row in window["presets"][key]["rows"]
        ]
        by_window = {
            window["id"]: _counts(window["presets"][key]["rows"]) for window in windows
        }
        presets[key] = {
            "label": windows[0]["presets"][key]["label"],
            "description": windows[0]["presets"][key]["description"],
            "trades": sum(window["presets"][key]["trades"] for window in windows),
            "signals": sum(window["presets"][key]["signals"] for window in windows),
            "stop_cap_sessions": sum(
                window["presets"][key]["stop_cap_sessions"] for window in windows
            ),
            "qty_zero_sessions": sum(
                window["presets"][key]["qty_zero_sessions"] for window in windows
            ),
            "buckets": _counts(all_rows),
            "by_window": by_window,
            "rows": all_rows,
        }

    payload = {
        "schema": "stop-buckets-dev-v1",
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": "development",
        "code_sha256": code_hash,
        "code_files": code_files,
        "dataset_sha256": dataset_before,
        "settings_sha256": settings_sha256(lock["settings"]),
        "lock_sha256": sha256_file(LOCK_PATH),
        "holdout": {
            "status": "sealed",
            "inspected": False,
            "before": holdout_before,
            "after": holdout_after,
        },
        "config": {
            "initial_capital": settings.risk.initial_capital,
            "risk_per_trade_pct": settings.risk.risk_per_trade_pct,
            "tick_value": settings.execution.tick_value,
            "max_contracts": settings.risk.max_contracts,
            "max_sl_ticks": settings.risk.max_sl_ticks,
            "cap_control": 600,
            "budget_ticks_at_initial_capital": round(
                settings.risk.initial_capital
                * settings.risk.risk_per_trade_pct
                / 100
                / settings.execution.tick_value,
                2,
            ),
        },
        "presets": presets,
        "windows": [
            {
                "window": window["window"],
                "start": window["start"],
                "end": window["end"],
                "sessions": window["sessions"],
                "elapsed_s": window["elapsed_s"],
            }
            for window in windows
        ],
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    fields = [
        "window", "preset", "date", "direction", "stop_ticks", "stop_source",
        "bucket", "signal_created", "traded", "qty", "risk_ok", "outcome",
        "reason", "reject_code",
    ]
    with CSV_OUT.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for key in ("baseline", *PRESETS):
            for row in presets[key]["rows"]:
                writer.writerow({field: row.get(field) for field in fields})

    for key in ("baseline", *PRESETS):
        print(f"\n{key} ({presets[key]['label']})", flush=True)
        print(
            f"trades={presets[key]['trades']} signals={presets[key]['signals']} "
            f"stop_cap_sessions={presets[key]['stop_cap_sessions']} "
            f"qty_zero_sessions={presets[key]['qty_zero_sessions']}",
            flush=True,
        )
        for bucket, counts in presets[key]["buckets"].items():
            print(f"  {bucket}: {counts}", flush=True)

    print(f"\nEscrito {OUT} y {CSV_OUT} en {payload['elapsed_s']}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
