"""Comprueba que `full` sigue produciendo las 38 operaciones archivadas.

No escribe resultados ni toca el holdout: solo reejecuta W1-W6 con el lock
congelado y compara ids, precios, cantidades y P&L contra los JSON existentes.
"""

from __future__ import annotations

import json
import math
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.backtest import run_backtest
from server.config import Settings, apply_settings
FIELDS = (
    "direction",
    "qty",
    "entry_ts",
    "exit_ts",
    "entry_price",
    "exit_price",
    "stop",
    "target",
    "pnl",
    "gross_pnl",
    "fees",
    "r_multiple",
    "risk_amount",
    "signal_type",
    "exit_reason",
    "duration_sec",
)


def _same(left, right) -> bool:
    if isinstance(left, float) or isinstance(right, float):
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-9)
    return left == right


def main() -> int:
    lock = json.loads((ROOT / "docs/protocolo_backtest.lock.json").read_text(encoding="utf-8"))
    base = Settings.model_validate(lock["settings"])
    full = apply_settings(base, {"strategy": {"use_smt": True, "entry_reference": "or_mid"}})
    expected_total = actual_total = 0
    mismatches: list[str] = []

    for window in lock["windows"]:
        archived = json.loads(
            (ROOT / "reports/backtest" / f"{window['id']}.json").read_text(encoding="utf-8")
        )
        expected = next(item for item in archived if item["variant"] == "full")
        result = run_backtest(
            full,
            window["sessions"],
            None,
            window["id"],
            date.fromisoformat(window["start"]),
        )
        actual = result["trades"]
        wanted = expected["trades"]
        expected_total += len(wanted)
        actual_total += len(actual)
        if len(wanted) != len(actual):
            mismatches.append(f"{window['id']}: {len(actual)} ops, esperadas {len(wanted)}")
        for index, (left, right) in enumerate(zip(wanted, actual)):
            if left.get("meta", {}).get("signal_id") != right.get("meta", {}).get("signal_id"):
                mismatches.append(f"{window['id']}[{index}]: signal_id")
            for key in FIELDS:
                if not _same(left.get(key), right.get(key)):
                    mismatches.append(
                        f"{window['id']}[{index}].{key}: {right.get(key)!r} != {left.get(key)!r}"
                    )
        print(
            f"{window['id']}: {len(actual)} ops, "
            f"net {result['metrics']['net_profit']:.2f}, "
            f"PF {result['metrics']['profit_factor']}",
            flush=True,
        )

    print(f"TOTAL: {actual_total} ops (archivadas {expected_total})", flush=True)
    if mismatches:
        print("MISMATCHES:", flush=True)
        for mismatch in mismatches[:40]:
            print(f"  {mismatch}", flush=True)
        return 1
    print("REGRESSION OK: ids, precios, cantidades y P&L idénticos", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
