"""Audita W2/W3 del lock contra el código actual, sin tocar los JSON originales."""

from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server.backtest as bt  # noqa: E402
from _windows import WINDOWS  # noqa: E402
from server.confirmatory import compute_code_hash  # noqa: E402
from server.config import Settings  # noqa: E402

LOCK = ROOT / "docs/protocolo_backtest.lock.json"
OUT = ROOT / "reports/backtest/_audit_w2_w3"
TASKS = tuple(
    {"window": key, "start": start, "end": end, "sessions": days}
    for key, start, end, days in WINDOWS
    if key in {"W2", "W3"}
)
MODE = os.environ.get("AUDIT_MODE", "raw").strip().lower()
if MODE not in {"raw", "adjusted"}:
    raise SystemExit(f"AUDIT_MODE inválido: {MODE}")


def run_one(task: dict) -> dict:
    started = time.perf_counter()
    lock = json.loads(LOCK.read_text(encoding="utf-8"))
    settings = Settings.model_validate(lock["settings"]).model_copy(deep=True)
    settings.feed.provider = "csv"
    settings.feed.csv_path = (
        "data/real/bars_mnq_nq_es_1m.csv"
        if MODE == "raw"
        else "data/real/bars_mnq_nq_es_1m_roll_adjusted.csv"
    )
    settings.feed.series_mode = MODE
    result = bt.run_backtest(
        settings,
        days=task["sessions"],
        start=date.fromisoformat(task["start"]),
        label=f"audit-{task['window']}",
        allow_holdout=False,
    )
    full = result
    selected = full["dataset"]["selected_range"]
    first = selected["first_et"][:10]
    last = selected["last_et"][:10]
    if full["dataset"]["sessions"]["count"] != task["sessions"]:
        raise RuntimeError(f"{task['window']}: sesiones inesperadas")
    if not (task["start"] <= first <= last <= task["end"]):
        raise RuntimeError(f"{task['window']}: rango inesperado {first}..{last}")
    payload = {
        "window": task["window"],
        "mode": MODE,
        "start": task["start"],
        "end": task["end"],
        "settings": settings.model_dump(mode="json"),
        "result": full,
        "elapsed_s": round(time.perf_counter() - started, 1),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{MODE}_{task['window']}.json").write_text(
        json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    metrics = full["metrics"]
    print(
        f"{task['window']}: {metrics['trades']} ops, neto {metrics['net_profit']}, "
        f"PF {metrics['profit_factor']}, DD {metrics['max_drawdown']} ({payload['elapsed_s']}s)",
        flush=True,
    )
    return {
        "window": task["window"],
        "metrics": metrics,
        "trades": full["trades"],
        "dataset": {
            "series_mode": full["dataset"].get("series_mode"),
            "selected_range": selected,
            "sessions": full["dataset"].get("sessions", {}).get("count"),
            "code": full["dataset"].get("code"),
            "config_sha256": (full.get("experiment") or {}).get("config_sha256"),
        },
        "elapsed_s": payload["elapsed_s"],
    }


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    code = compute_code_hash(ROOT)
    print("code", code, flush=True)
    rows = []
    with ProcessPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(run_one, task): task for task in TASKS}
        for future in as_completed(futures):
            rows.append(future.result())
    rows.sort(key=lambda row: row["window"])
    summary = {
        "code": code,
        "mode": MODE,
        "lock": str(LOCK.relative_to(ROOT)).replace("\\", "/"),
        "rows": rows,
    }
    (OUT / f"summary_{MODE}.json").write_text(
        json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8"
    )
    print(json.dumps(summary, indent=1, ensure_ascii=False)[:12000])


if __name__ == "__main__":
    main()
