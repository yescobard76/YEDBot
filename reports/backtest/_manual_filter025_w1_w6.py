"""Backtest aislado: perfil P2 + filtro min_stop_or_ratio=0,25 en W1-W6.

Dos brazos:
- filter025_max10: P2 (10 contratos, SL 200) + filtro 0,25.
- filter025_max5: P2 con 5 contratos + filtro 0,25.

Los dos brazos deben dar el mismo resultado porque todas las entradas
aceptadas tienen qty <= 5. El segundo brazo es una comprobación de invariancia,
no una estrategia alternativa.

No escribe en la DB ni modifica la configuracion viva. Ejecutar desde la raiz.
El ``max_drawdown`` agregado es el de la curva de trades concatenados desde
25.000, no una curva continua con sizing arrastrado.
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
    FILTER_THRESHOLD,
    P2_PATH,
    WINDOWS,
    aggregate,
    assert_metrics,
    load,
    print_aggregate,
    print_windows,
    run_windows,
)

VARIANTS = {
    "filter025_max10": (
        P2_PATH,
        {"risk": {"min_stop_or_ratio": FILTER_THRESHOLD}},
    ),
    "filter025_max5": (
        P2_PATH,
        {
            "risk": {
                "max_contracts": 5,
                "min_stop_or_ratio": FILTER_THRESHOLD,
            }
        },
    ),
}

# Definición efectiva expuesta para la verificación de equivalencia.
EFFECTIVE_WINDOWS = WINDOWS

EXPECTED = {"trades": 17, "net": 4202.20, "pf": 4.25, "dd": 946.38}


def _trades(ordered: list[dict], name: str) -> list[dict]:
    return [
        trade
        for block in ordered
        for trade in block["variants"][name]["trades"]
    ]


def _signature(trade: dict) -> tuple:
    """Identidad económica del trade; el id es un UUID distinto en cada corrida."""
    return (
        (trade.get("meta") or {}).get("signal_id"),
        trade["entry_ts"],
        trade["exit_ts"],
        trade["direction"],
        int(trade["qty"]),
        round(float(trade["entry_price"]), 4),
        round(float(trade["exit_price"]), 4),
        round(float(trade["pnl"]), 2),
        trade["exit_reason"],
    )


def _assert_same_result(ordered: list[dict], names: list[str]) -> None:
    a = [_signature(t) for t in _trades(ordered, names[0])]
    b = [_signature(t) for t in _trades(ordered, names[1])]
    if a != b:
        raise AssertionError("Los brazos no tienen la misma secuencia económica")


def main() -> int:
    started = time.perf_counter()
    p2 = load(P2_PATH)
    if p2.risk.min_stop_or_ratio != 0.0:
        raise AssertionError("P2 no parte de min_stop_or_ratio 0")

    names = list(VARIANTS)
    ordered = run_windows(VARIANTS, P2_PATH)
    print_windows(ordered, names)
    agg = aggregate(ordered, names)
    print_aggregate(agg, names)

    for name in names:
        assert_metrics(name, agg[name]["stats"], **EXPECTED)
    _assert_same_result(ordered, names)

    out = {
        "profile": "profiles/p2_freq/config.json",
        "filter_threshold": FILTER_THRESHOLD,
        "variants": {
            name: {
                "base": str(base.relative_to(ROOT)),
                "patch": patch,
            }
            for name, (base, patch) in VARIANTS.items()
        },
        "windows": ordered,
        "aggregate": {
            name: {
                **agg[name]["stats"],
                "max_qty": agg[name]["max_qty"],
                "ops_over_5": agg[name]["ops_over_5"],
                "stop_caps": agg[name]["stop_caps"],
                "qty_zero": agg[name]["qty_zero"],
            }
            for name in names
        },
        "invariant_max10_eq_max5": True,
    }
    (ROOT / "reports/backtest/_manual_filter025_w1_w6.json").write_text(
        json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print(f"\nTiempo: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
