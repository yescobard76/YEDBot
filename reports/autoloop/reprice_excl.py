"""Reprecía `excl_1130_1330` contra la base con los costes exactos del bot.

Usa el mismo runner y dataset que `manual_base`, conserva la configuración de
ejecución de `data/config.json` y no toca el 8765, la DB ni el holdout.
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "reports/backtest"
for path in (ROOT, BT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _manual_common import MANUAL_PATH, aggregate, load, run_windows  # noqa: E402
from server.config import apply_settings  # noqa: E402

OUT = ROOT / "reports/autoloop"
RESULTS = OUT / "reprecio_excl_1130_1330.jsonl"
EXCLUSION = {
    "risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "13:30"}
}
VARIANTS = {
    "manual_base": (MANUAL_PATH, {}),
    "excl_1130_1330": (MANUAL_PATH, EXCLUSION),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stats_metrics(stats: dict) -> dict:
    net = float(stats.get("net_profit") or 0.0)
    dd = float(stats.get("max_drawdown") or 0.0)
    return {
        "trades": stats.get("trades"),
        "net": net,
        "pf": stats.get("profit_factor"),
        "dd": dd,
        "dd_pct": stats.get("max_drawdown_pct"),
        "avg_r": stats.get("avg_r"),
        "rdd": round(net / max(dd, 1.0), 4),
    }


def main() -> int:
    def metrics(row: dict) -> dict:
        return stats_metrics(row["stats"])

    base_settings = load(MANUAL_PATH)
    variant_settings = apply_settings(base_settings, EXCLUSION)
    if base_settings.execution.model_dump() != variant_settings.execution.model_dump():
        raise RuntimeError("La variante cambió la configuración de ejecución")

    ordered = run_windows(VARIANTS, dataset_base=MANUAL_PATH)
    agg = aggregate(ordered, list(VARIANTS))
    windows = {}
    for block in ordered:
        windows[block["window"]] = {
            "first": block["first"],
            "last": block["last"],
            "sessions": block["sessions"],
            "base": stats_metrics(block["variants"]["manual_base"]["metrics"]),
            "variant": stats_metrics(block["variants"]["excl_1130_1330"]["metrics"]),
        }
    base = metrics(agg["manual_base"])
    variant = metrics(agg["excl_1130_1330"])
    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "id": "reprecio_excl_1130_1330",
        "role": "reprice",
        "run_id": "reprecio_excl_1130_1330__w1_w6__exact-execution",
        "dataset": "data/bars.csv",
        "dataset_sha256": sha256(ROOT / "data/bars.csv"),
        "config_sha256": sha256(MANUAL_PATH),
        "execution": base_settings.execution.model_dump(),
        "exclusion": EXCLUSION,
        "windows": windows,
        "base": base,
        "variant": variant,
        "delta": {
            "trades": int(variant["trades"]) - int(base["trades"]),
            "net": round(variant["net"] - base["net"], 2),
            "dd": round(variant["dd"] - base["dd"], 2),
            "rdd": round(variant["rdd"] - base["rdd"], 4),
        },
    }
    RESULTS.write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
