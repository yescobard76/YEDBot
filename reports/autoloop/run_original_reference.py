"""Genera la fila de referencia original 5/200/150/12 en W1-W6.

Se ejecuta una sola vez sobre el mismo dataset que `manual_base`, con el mismo
runner `_simulate` y las mismas ventanas. No toca configuraciones, DB ni el
proceso 8765. La fila original se escribe en un JSONL aparte para no alterar
el ranking del autoloop; `manual_base` solo se enriquece con las fechas de sus
ventanas, sin cambiar sus métricas.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BT = ROOT / "reports" / "backtest"
for path in (ROOT, BT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from _manual_common import (  # noqa: E402
    MANUAL_PATH,
    ORIGINAL_FREQUENCY_PATCH,
    ORIGINAL_PATH,
    aggregate,
    run_windows,
)
from _windows import WINDOWS  # noqa: E402

OUT = ROOT / "reports/autoloop"
RESULTS = OUT / "resultados.jsonl"
ORIGINAL_RESULTS = OUT / "resultados_original.jsonl"
WINDOW_END = {key: end for key, _start, end, _days in WINDOWS}
VARIANTS = {
    "manual_base": (MANUAL_PATH, {}),
    "original_5_200_150_12": (ORIGINAL_PATH, ORIGINAL_FREQUENCY_PATCH),
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def row_for(name: str, ordered: list[dict], agg: dict) -> dict:
    stats = agg[name]["stats"]
    windows = {}
    for block in ordered:
        metrics = block["variants"][name]["metrics"]
        windows[block["window"]] = {
            "start": block["start"],
            "end": WINDOW_END[block["window"]],
            "first": block["first"],
            "last": block["last"],
            "sessions": block["sessions"],
            "trades": metrics.get("trades"),
            "net": metrics.get("net_profit"),
            "pf": metrics.get("profit_factor"),
            "dd": metrics.get("max_drawdown"),
        }
    net = float(stats.get("net_profit") or 0.0)
    dd = float(stats.get("max_drawdown") or 0.0)
    record = {
        "ts": now(),
        "id": name,
        "role": "live" if name == "manual_base" else "original",
        "run_id": f"{name}__w1_w6__same-dataset",
        "config_label": "10/300/210/24" if name == "manual_base" else "5/200/150/12",
        "profile": str((MANUAL_PATH if name == "manual_base" else ORIGINAL_PATH).relative_to(ROOT)),
        "dataset": "data/bars.csv",
        "why": (
            "control: configuración viva 10/300/210/24"
            if name == "manual_base"
            else "referencia original 5/200/150/12; no es una variante de la viva"
        ),
        "patch": {} if name == "manual_base" else {
            "risk": {"max_contracts": 5, "max_sl_ticks": 200},
            "strategy": {"setup_validity_minutes": 150, "retest_tolerance_ticks": 12},
        },
        "trades": stats.get("trades"),
        "net": net,
        "pf": stats.get("profit_factor"),
        "dd": dd,
        "dd_pct": stats.get("max_drawdown_pct"),
        "avg_r": stats.get("avg_r"),
        "win_rate": stats.get("win_rate"),
        "rdd": round(net / max(dd, 1.0), 4),
        "windows": windows,
    }
    return record


def main() -> int:
    existing = read_rows(RESULTS)
    manual_old = next((r for r in existing if r.get("id") == "manual_base"), None)
    if manual_old is None:
        raise RuntimeError("No existe manual_base en resultados.jsonl")

    ordered = run_windows(VARIANTS, dataset_base=MANUAL_PATH)
    agg = aggregate(ordered, list(VARIANTS))
    manual = row_for("manual_base", ordered, agg)
    original = row_for("original_5_200_150_12", ordered, agg)

    for key in ("trades", "net", "pf", "dd"):
        if key == "pf":
            if abs(float(manual["pf"] or 0) - float(manual_old["pf"] or 0)) > 0.01:
                raise RuntimeError(f"manual_base cambió pf: {manual['pf']} vs {manual_old['pf']}")
        elif abs(float(manual[key]) - float(manual_old[key])) > 0.05:
            raise RuntimeError(f"manual_base cambió {key}: {manual[key]} vs {manual_old[key]}")

    # Conserva la identidad y el ts originales de manual_base, pero añade las
    # fechas de ventana que faltaban para poder verificar la ventana común.
    manual["ts"] = manual_old.get("ts", manual["ts"])
    manual["source"] = "reports/autoloop/run_original_reference.py"
    existing = [manual if r.get("id") == "manual_base" else r for r in existing]
    RESULTS.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in existing) + "\n",
        encoding="utf-8",
    )
    original["source"] = "reports/autoloop/run_original_reference.py"
    ORIGINAL_RESULTS.write_text(
        json.dumps(original, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    print("manual_base", manual["trades"], manual["net"], manual["dd"], manual["rdd"])
    print("original  ", original["trades"], original["net"], original["dd"], original["rdd"])
    print("ventanas", [(w, manual["windows"][w]["first"], manual["windows"][w]["last"],
                       original["windows"][w]["first"], original["windows"][w]["last"])
                      for w in manual["windows"]])
    print("escrito", RESULTS.relative_to(ROOT), ORIGINAL_RESULTS.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
