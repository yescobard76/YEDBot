"""Backtest aislado: config viva (10/300/210/24 + replay 8x) con y sin filtro 0,25.

Dos brazos, ambos sobre ``data/config.json``:
- live: config viva sin cambios (min_stop_or_ratio=0,00, SL 300).
- live_filter025: mismo perfil con el único override
  ``risk.min_stop_or_ratio=0,25``; el SL sigue en 300.

No escribe en la DB, no modifica perfiles ni abre el holdout. Solo ejecuta
W1-W6 sobre el CSV adjusted y escribe este JSON de resultados en
``reports/backtest/_live_filter025_w1_w6.json``.

El ``max_drawdown`` agregado es el de la curva de trades concatenados desde
25.000, no una curva continua con sizing arrastrado.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from _manual_common import (  # noqa: E402
    FILTER_THRESHOLD,
    INITIAL_CAPITAL,
    MANUAL_PATH,
    WINDOWS,
    aggregate,
    assert_metrics,
    fmt,
    load,
    print_aggregate,
    print_windows,
    run_windows,
    settings_diff,
)
from server.config import apply_settings  # noqa: E402
from server.stats import compute_stats  # noqa: E402

OUT_JSON = ROOT / "reports/backtest/_live_filter025_w1_w6.json"
HOLDOUT_START = "2026-07-01"

VARIANTS = {
    "live": (MANUAL_PATH, {}),
    "live_filter025": (
        MANUAL_PATH,
        {"risk": {"min_stop_or_ratio": FILTER_THRESHOLD}},
    ),
}

BASELINE_EXPECTED = {"trades": 72, "net": 2022.94, "pf": 1.22, "dd": 2891.66}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signal_id(trade: dict[str, Any]) -> str:
    return str((trade.get("meta") or {}).get("signal_id") or trade.get("id"))


def trades_for(ordered: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [t for block in ordered for t in block["variants"][name]["trades"]]


def delta(a: dict[str, Any], b: dict[str, Any], key: str) -> float | None:
    av, bv = a.get(key), b.get(key)
    if av is None or bv is None:
        return None
    return round(float(av) - float(bv), 4)


def main() -> int:
    started = time.perf_counter()
    live = load(MANUAL_PATH)
    filtered = apply_settings(live, VARIANTS["live_filter025"][1])

    if live.risk.max_sl_ticks != 300:
        raise AssertionError("La config viva no tiene SL 300")
    if live.risk.max_contracts != 10:
        raise AssertionError("La config viva no tiene max_contracts 10")
    if (
        live.strategy.setup_validity_minutes != 210
        or live.strategy.retest_tolerance_ticks != 24
    ):
        raise AssertionError("La config viva no es 210/24")
    if abs(live.feed.replay_speed - 8.0) > 1e-9:
        raise AssertionError("La config viva no tiene replay_speed 8")
    if live.risk.min_stop_or_ratio != 0.0:
        raise AssertionError("La config viva no parte de min_stop_or_ratio 0")

    diff = settings_diff(live, filtered)
    expected_diff = {"risk.min_stop_or_ratio": [0.0, FILTER_THRESHOLD]}
    if diff != expected_diff:
        raise AssertionError(f"El override no es único: {diff}")
    if filtered.risk.max_sl_ticks != 300:
        raise AssertionError("El override cambió max_sl_ticks")

    hash_paths = {
        "data_config": MANUAL_PATH,
        "live_profile": ROOT / "profiles/live_8765/config.json",
        "bars_csv": ROOT / live.feed.csv_path,
    }
    before_hashes = {key: sha256_file(path) for key, path in hash_paths.items()}

    names = list(VARIANTS)
    ordered = run_windows(VARIANTS, MANUAL_PATH)
    if ordered[-1]["last"][:10] >= HOLDOUT_START:
        raise AssertionError("La última sesión alcanza el holdout")
    print_windows(ordered, names)
    agg = aggregate(ordered, names)
    print_aggregate(agg, names)

    assert_metrics("live", agg["live"]["stats"], **BASELINE_EXPECTED)

    after_hashes = {key: sha256_file(path) for key, path in hash_paths.items()}
    if before_hashes != after_hashes:
        raise AssertionError("Un archivo de entrada cambió durante la ejecución")

    live_stats = agg["live"]["stats"]
    filtered_stats = agg["live_filter025"]["stats"]
    live_trades = trades_for(ordered, "live")
    filtered_trades = trades_for(ordered, "live_filter025")
    live_ids = {signal_id(t) for t in live_trades}
    filtered_ids = {signal_id(t) for t in filtered_trades}
    if not filtered_ids <= live_ids:
        raise AssertionError("El filtro generó señales que no están en la viva")
    rejected = [t for t in live_trades if signal_id(t) not in filtered_ids]
    rejected_stats = compute_stats(rejected, INITIAL_CAPITAL)

    delta_stats = {
        key: delta(filtered_stats, live_stats, key)
        for key in (
            "trades",
            "net_profit",
            "avg_r",
            "profit_factor",
            "max_drawdown",
            "max_drawdown_pct",
            "expectancy",
            "win_rate",
            "total_r",
        )
    }

    out = {
        "schema": "live-filter025-w1-w6-v1",
        "base_profile": "data/config.json",
        "filter_threshold": FILTER_THRESHOLD,
        "only_change": "risk.min_stop_or_ratio 0.00 -> 0.25; max_sl_ticks stays 300",
        "settings": {
            "max_contracts": live.risk.max_contracts,
            "max_sl_ticks": live.risk.max_sl_ticks,
            "setup_validity_minutes": live.strategy.setup_validity_minutes,
            "retest_tolerance_ticks": live.strategy.retest_tolerance_ticks,
            "replay_speed": live.feed.replay_speed,
            "min_stop_or_ratio_base": live.risk.min_stop_or_ratio,
            "min_stop_or_ratio_filter": filtered.risk.min_stop_or_ratio,
        },
        "scope": {
            "windows": [spec[0] for spec in WINDOWS],
            "sessions": sum(spec[3] for spec in WINDOWS),
            "start": ordered[0]["first"],
            "last": ordered[-1]["last"],
            "data": live.feed.csv_path,
            "series_mode": live.feed.series_mode,
            "initial_capital": INITIAL_CAPITAL,
            "holdout_used": False,
            "year_2024_used": False,
        },
        "variants": {
            name: {
                "base": str(base.relative_to(ROOT)),
                "patch": patch,
            }
            for name, (base, patch) in VARIANTS.items()
        },
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
        "delta_filter_vs_live": delta_stats,
        "rejected": {
            "count": len(rejected),
            "net_profit": rejected_stats["net_profit"],
            "avg_r": rejected_stats["avg_r"],
            "profit_factor": rejected_stats["profit_factor"],
            "win_rate": rejected_stats["win_rate"],
        },
        "windows": [
            {
                "window": block["window"],
                "sessions": block["sessions"],
                "net": {
                    name: block["variants"][name]["metrics"]["net_profit"]
                    for name in names
                },
                "trades": {
                    name: block["variants"][name]["metrics"]["trades"]
                    for name in names
                },
                "avg_r": {
                    name: block["variants"][name]["metrics"]["avg_r"]
                    for name in names
                },
                "profit_factor": {
                    name: block["variants"][name]["metrics"]["profit_factor"]
                    for name in names
                },
                "max_drawdown": {
                    name: block["variants"][name]["metrics"]["max_drawdown"]
                    for name in names
                },
            }
            for block in ordered
        ],
        "hashes": {
            "before": before_hashes,
            "after": after_hashes,
            "unchanged": before_hashes == after_hashes,
        },
        "constraints": {
            "configs_modified": False,
            "db_written": False,
            "holdout_accessed": False,
            "year_2024_accessed": False,
            "backtests_run": True,
            "capture_started": False,
        },
    }
    OUT_JSON.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    print("\nCOMPARACION LIVE vs LIVE + FILTRO 0,25")
    print("brazo,trades,net,expectancy_r,pf,dd,dd_pct,win_rate,total_r")
    for name in names:
        s = agg[name]["stats"]
        print(
            f"{name},{s['trades']},{s['net_profit']:.2f},{fmt(s['avg_r'], 3)},"
            f"{fmt(s['profit_factor'])},{s['max_drawdown']:.2f},"
            f"{s['max_drawdown_pct']:.2f},{s['win_rate']:.1f},"
            f"{fmt(s['total_r'])}"
        )
    print("\nDELTA FILTRO - LIVE")
    print(
        f"neto={delta_stats['net_profit']:+.2f} USD; "
        f"expectancy_r={delta_stats['avg_r']:+.3f}; "
        f"pf={delta_stats['profit_factor']:+.2f}; "
        f"dd={delta_stats['max_drawdown']:+.2f} USD; "
        f"trades={int(delta_stats['trades']):+d}"
    )
    print(
        f"rechazados={len(rejected)}; neto_rechazados={rejected_stats['net_profit']:+.2f} USD; "
        f"avg_r_rechazados={rejected_stats['avg_r']:+.3f}; "
        f"pf_rechazados={fmt(rejected_stats['profit_factor'])}"
    )
    print(f"\nJSON: {OUT_JSON}")
    print(f"Tiempo: {time.perf_counter() - started:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
