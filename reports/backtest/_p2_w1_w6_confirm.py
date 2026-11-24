"""Confirma el backtest W1-W6 del perfil P2.

P2 = copia de data/config.json con max_sl_ticks=200; max_contracts=10,
setup_validity_minutes=210 y retest_tolerance_ticks=24.

Usa la definición única de ventanas de ``_windows.py`` y el helper común de
carga/agregación. El original se fija en memoria a la frecuencia canónica
150/12: ``profiles/backtest_real/config.json`` puede contener 210/24 y este
script no lo modifica.

No escribe en la DB, no modifica data/config.json, P2 ni el holdout.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from _manual_common import (  # noqa: E402
    MANUAL_PATH,
    ORIGINAL_FREQUENCY_PATCH,
    ORIGINAL_PATH,
    P2_PATH,
    WINDOWS,
    aggregate,
    assert_metrics,
    load,
    load_original,
    print_aggregate,
    print_windows,
    run_windows,
    settings_diff,
)
from server.config import apply_settings  # noqa: E402

OUT_PATH = ROOT / "reports/backtest/p2_w1_w6_confirm.json"

VARIANTS = {
    "original": (ORIGINAL_PATH, ORIGINAL_FREQUENCY_PATCH),
    "p2": (P2_PATH, {}),
}

# Definición efectiva expuesta para la verificación de equivalencia.
EFFECTIVE_WINDOWS = WINDOWS

EXPECTED = {
    "original": {"trades": 38, "net": 661.44, "pf": 1.13, "dd": 1967.82},
    "p2": {"trades": 46, "net": 2471.78, "pf": 1.39, "dd": 2304.46},
}


def _validate_settings() -> None:
    original = load_original()
    p2 = load(P2_PATH)
    manual = load(MANUAL_PATH)

    if original.risk.max_contracts != 5 or original.risk.max_sl_ticks != 200:
        raise AssertionError("El original canónico no es 5 contratos / SL 200")
    if (
        original.strategy.setup_validity_minutes != 150
        or original.strategy.retest_tolerance_ticks != 12
    ):
        raise AssertionError("El original canónico no tiene validez 150 / tolerancia 12")

    if p2.risk.max_sl_ticks != 200 or p2.risk.max_contracts != 10:
        raise AssertionError("P2 no es 10 contratos / SL 200")
    if (
        p2.strategy.setup_validity_minutes != 210
        or p2.strategy.retest_tolerance_ticks != 24
    ):
        raise AssertionError("P2 no tiene validez 210 / tolerancia 24")
    if p2.risk.min_stop_or_ratio != 0.0:
        raise AssertionError("P2 no parte de min_stop_or_ratio 0")
    if p2.live.live_enabled is not False:
        raise AssertionError("P2 no debe tener live habilitado")
    if manual.risk.max_sl_ticks != 300:
        raise AssertionError("data/config.json no es el perfil manual con SL 300")

    expected_p2 = apply_settings(manual, {"risk": {"max_sl_ticks": 200}})
    if p2.model_dump() != expected_p2.model_dump():
        raise AssertionError("profiles/p2_freq/config.json no es manual con SL 200")

    print("P2:", P2_PATH)
    print("VS ORIGINAL CANONICO (150/12):")
    for key, (old, new) in settings_diff(original, p2).items():
        print(f"  {key}: {old!r} -> {new!r}")
    print("VS DATA CONFIG:")
    for key, (old, new) in settings_diff(manual, p2).items():
        print(f"  {key}: {old!r} -> {new!r}")


def main() -> int:
    started = time.perf_counter()
    _validate_settings()
    names = list(VARIANTS)
    ordered = run_windows(VARIANTS, P2_PATH)
    print_windows(ordered, names)
    agg = aggregate(ordered, names)
    print_aggregate(agg, names)

    for name, expected in EXPECTED.items():
        assert_metrics(name, agg[name]["stats"], **expected)

    print("\nCONFIRMACION: OK (original y P2 reproducen los valores esperados)")
    out = {
        "profile": str(P2_PATH.relative_to(ROOT)).replace("\\", "/"),
        "original_baseline": "canonical 150/12 pinned in memory",
        "windows": ordered,
        "aggregate": {
            name: {
                "stats": agg[name]["stats"],
                "max_qty": agg[name]["max_qty"],
                "ops_over_5": agg[name]["ops_over_5"],
            }
            for name in names
        },
        "expected": EXPECTED,
        "problems": [],
    }
    OUT_PATH.write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nJSON: {OUT_PATH}")
    print(f"Tiempo: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
