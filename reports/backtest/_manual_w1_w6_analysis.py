"""Compara la config manual de 8765 con la original y P1/P2 en W1-W6.

No escribe en la DB ni modifica configuracion: reutiliza el motor de backtest
en memoria y solo imprime resultados. Ejecutar desde la raiz del proyecto.

Variantes:
- original: perfil backtest_real con la frecuencia canónica 150/12
  (max_contracts 5, max_sl_ticks 200). El patch de frecuencia se aplica
  explícitamente porque el archivo actual contiene 210/24; no se modifica.
- manual: data/config.json (max_contracts 10, max_sl_ticks 300,
  validez 210, tolerancia 24).
- p2: profiles/p2_freq/config.json (manual con max_sl_ticks 200).
- p1: P2 con max_contracts 5.
- manual_freq_original: manual con validez/tolerancia originales (150/12).

El ``max_drawdown`` agregado es el de la curva de trades concatenados desde
25.000, no el de una curva continua con sizing arrastrado.
"""

from __future__ import annotations

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
    fmt,
    load,
    load_original,
    print_aggregate,
    print_windows,
    run_windows,
)
from server.config import apply_settings  # noqa: E402

VARIANTS = {
    "original": (ORIGINAL_PATH, ORIGINAL_FREQUENCY_PATCH),
    "manual": (MANUAL_PATH, {}),
    "p2": (P2_PATH, {}),
    "p1": (P2_PATH, {"risk": {"max_contracts": 5}}),
    "manual_freq_original": (
        MANUAL_PATH,
        {"strategy": {"setup_validity_minutes": 150, "retest_tolerance_ticks": 12}},
    ),
}

# Definición efectiva expuesta para la verificación de equivalencia.
EFFECTIVE_WINDOWS = WINDOWS

EXPECTED = {
    "original": {"trades": 38, "net": 661.44, "pf": 1.13, "dd": 1967.82},
    "manual": {"trades": 72, "net": 2022.94, "pf": 1.22, "dd": 2891.66},
    "p2": {"trades": 46, "net": 2471.78, "pf": 1.39, "dd": 2304.46},
    "p1": {"trades": 46, "net": 1992.26, "pf": 1.37, "dd": 1947.82},
    "manual_freq_original": {
        "trades": 60,
        "net": -608.06,
        "pf": 0.93,
        "dd": 2870.66,
    },
}


def _validate_settings() -> None:
    original_file = load(ORIGINAL_PATH)
    original = load_original()
    manual = load(MANUAL_PATH)
    p2 = load(P2_PATH)

    if original.risk.max_contracts != 5 or original.risk.max_sl_ticks != 200:
        raise AssertionError("El perfil original no es 5 contratos / SL 200")
    if (
        original.strategy.setup_validity_minutes != 150
        or original.strategy.retest_tolerance_ticks != 12
    ):
        raise AssertionError("El original canónico no tiene validez 150 / tolerancia 12")
    if (
        original_file.strategy.setup_validity_minutes != 150
        or original_file.strategy.retest_tolerance_ticks != 12
    ):
        print(
            "AVISO: profiles/backtest_real/config.json contiene "
            f"{original_file.strategy.setup_validity_minutes}/"
            f"{original_file.strategy.retest_tolerance_ticks}; el baseline se fija "
            "a 150/12 (protocolo) sin modificar el archivo.",
            flush=True,
        )

    if manual.risk.max_contracts != 10 or manual.risk.max_sl_ticks != 300:
        raise AssertionError("La config manual no es 10 contratos / SL 300")
    if (
        manual.strategy.setup_validity_minutes != 210
        or manual.strategy.retest_tolerance_ticks != 24
    ):
        raise AssertionError("La config manual no tiene validez 210 / tolerancia 24")
    if manual.risk.min_stop_or_ratio != 0.0:
        raise AssertionError("La config manual no parte de min_stop_or_ratio 0")

    if p2.risk.max_contracts != 10 or p2.risk.max_sl_ticks != 200:
        raise AssertionError("P2 no es 10 contratos / SL 200")
    if (
        p2.strategy.setup_validity_minutes != 210
        or p2.strategy.retest_tolerance_ticks != 24
    ):
        raise AssertionError("P2 no tiene validez 210 / tolerancia 24")
    if p2.risk.min_stop_or_ratio != 0.0:
        raise AssertionError("P2 no parte de min_stop_or_ratio 0")

    expected_p2 = apply_settings(manual, {"risk": {"max_sl_ticks": 200}})
    if p2.model_dump() != expected_p2.model_dump():
        raise AssertionError("profiles/p2_freq/config.json no es manual con SL 200")


def _print_attribution(agg: dict[str, dict]) -> None:
    print("\nATRIBUCION (delta frente a la columna base)")
    print("cambio,base,net_variante,delta_net,delta_dd,delta_pf")
    rows = (
        ("frecuencia 210/24 (riesgo original)", "p1", "original"),
        ("max_contracts 10 (con SL 200)", "p2", "p1"),
        ("max_sl_ticks 300 (con max10)", "manual", "p2"),
        ("paquete agresivo (manual vs P1)", "manual", "p1"),
        (
            "riesgo agresivo sin frecuencia",
            "manual_freq_original",
            "original",
        ),
    )
    for label, variant, base in rows:
        a = agg[variant]["stats"]
        b = agg[base]["stats"]
        print(
            f"{label},{base},{a['net_profit']:.2f},"
            f"{a['net_profit'] - b['net_profit']:+.2f},"
            f"{a['max_drawdown'] - b['max_drawdown']:+.2f},"
            f"{fmt(a['profit_factor'])} vs {fmt(b['profit_factor'])}"
        )

    freq = agg["p1"]["stats"]["net_profit"] - agg["original"]["stats"]["net_profit"]
    max10 = agg["p2"]["stats"]["net_profit"] - agg["p1"]["stats"]["net_profit"]
    sl300 = (
        agg["manual"]["stats"]["net_profit"] - agg["p2"]["stats"]["net_profit"]
    )
    residual = (
        agg["manual"]["stats"]["net_profit"]
        - agg["original"]["stats"]["net_profit"]
        - (freq + max10 + sl300)
    )
    print(f"residual descomposicion: {residual:+.2f}")
    if abs(residual) > 0.05:
        raise AssertionError(f"La atribucion no cierra: residual {residual}")


def main() -> int:
    started = time.perf_counter()
    _validate_settings()
    names = list(VARIANTS)
    ordered = run_windows(VARIANTS, MANUAL_PATH)
    print_windows(ordered, names)
    agg = aggregate(ordered, names)
    print_aggregate(agg, names)

    for name, expected in EXPECTED.items():
        assert_metrics(name, agg[name]["stats"], **expected)

    _print_attribution(agg)
    print(f"\nTiempo: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
