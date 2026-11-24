"""Utilidades compartidas por los análisis de la configuración manual/P2.

Ventanas canónicas, carga de perfiles, ejecución en memoria y agregación de
trades. No toca la configuración viva, la DB ni el holdout.

Convención de agregación: cada ventana se simula con capital inicial 25.000 y
se concatenan sus trades para calcular métricas de trade (neto, PF, expectancy,
R). El ``max_drawdown`` resultante es el de la curva de trades concatenados con
capital 25.000, no el de una curva continua con sizing arrastrado. Es la misma
convención de ``development_aggregate.json`` y de los informes W1-W6.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from _windows import WINDOW_FIRST, WINDOWS  # noqa: E402
from server.backtest import _simulate, prepare_dataset  # noqa: E402
from server.config import Settings, apply_settings  # noqa: E402
from server.stats import compute_stats  # noqa: E402

ORIGINAL_PATH = ROOT / "profiles/backtest_real/config.json"
MANUAL_PATH = ROOT / "data/config.json"
P2_PATH = ROOT / "profiles/p2_freq/config.json"
INITIAL_CAPITAL = 25_000.0
FILTER_THRESHOLD = 0.25

# El perfil original canónico del protocolo. El archivo actual contiene 210/24;
# se fija la frecuencia en memoria para no tocar la configuración.
ORIGINAL_FREQUENCY_PATCH = {
    "strategy": {"setup_validity_minutes": 150, "retest_tolerance_ticks": 12}
}

# name -> (perfil base, patch parcial)
VariantMap = dict[str, tuple[Path, dict[str, Any]]]


def load(path: Path) -> Settings:
    return Settings.model_validate_json(path.read_text(encoding="utf-8"))


def load_original() -> Settings:
    """Original canónico 150/12, independiente del archivo contaminado."""
    return apply_settings(load(ORIGINAL_PATH), ORIGINAL_FREQUENCY_PATCH)


def _flatten(value, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(value, dict):
        for key, item in value.items():
            out.update(_flatten(item, f"{prefix}.{key}" if prefix else key))
    else:
        out[prefix] = value
    return out


def settings_diff(a: Settings, b: Settings) -> dict[str, list[Any]]:
    """Diff plano entre dos Settings, para las confirmaciones."""
    fa, fb = _flatten(a.model_dump()), _flatten(b.model_dump())
    keys = sorted(set(fa) | set(fb))
    return {key: [fa.get(key), fb.get(key)] for key in keys if fa.get(key) != fb.get(key)}


def _validate_block(block: dict[str, Any], spec: tuple[str, str, str, int]) -> None:
    key, start, end, days = spec
    if block["sessions"] != days:
        raise RuntimeError(
            f"{key}: {block['sessions']} sesiones, se esperaban {days}"
        )
    first = block.get("first") or ""
    expected_first = WINDOW_FIRST.get(key)
    if expected_first and not first.startswith(expected_first):
        raise RuntimeError(
            f"{key}: primera sesión {first!r}, se esperaba {expected_first}"
        )
    last = block.get("last") or ""
    if not last.startswith(end):
        raise RuntimeError(f"{key}: última sesión {last!r}, se esperaba {end}")


def _run_window(
    spec: tuple[str, str, str, int],
    variants: VariantMap,
    dataset_base: Path,
) -> dict[str, Any]:
    key, start_s, _end_s, days = spec
    sessions, source, dataset = prepare_dataset(
        load(dataset_base), days=days, start=date.fromisoformat(start_s)
    )
    out: dict[str, Any] = {
        "window": key,
        "start": start_s,
        "sessions": len(sessions),
        "first": dataset.get("selected_range", {}).get("first_et"),
        "last": dataset.get("selected_range", {}).get("last_et"),
        "variants": {},
    }
    _validate_block(out, spec)

    cache: dict[Path, Settings] = {}
    for name, (base_path, patch) in variants.items():
        base = cache.get(base_path)
        if base is None:
            base = load(base_path)
            cache[base_path] = base
        settings = apply_settings(base, patch) if patch else base
        result = _simulate(settings, sessions, source, name, dataset)
        out["variants"][name] = {
            "trades": result["trades"],
            "metrics": result["metrics"],
        }
    return out


def run_windows(
    variants: VariantMap,
    dataset_base: Path = MANUAL_PATH,
    *,
    workers: int | None = None,
) -> list[dict[str, Any]]:
    """Ejecuta todas las ventanas en procesos separados y devuelve W1..W6."""
    if not variants:
        raise ValueError("No hay variantes que ejecutar")
    started = time.perf_counter()
    by_window: dict[str, dict[str, Any]] = {}
    with ProcessPoolExecutor(max_workers=workers or len(WINDOWS)) as pool:
        futures = {
            pool.submit(_run_window, spec, variants, dataset_base): spec
            for spec in WINDOWS
        }
        for future in as_completed(futures):
            data = future.result()
            by_window[data["window"]] = data
            print(f"[{data['window']}] {data['first']}..{data['last']}", flush=True)
    ordered = [by_window[spec[0]] for spec in WINDOWS]
    print(f"Ejecucion: {time.perf_counter() - started:.1f}s")
    return ordered


def aggregate(ordered: list[dict[str, Any]], names: list[str]) -> dict[str, dict]:
    """Concatena trades por variante y calcula métricas y contadores."""
    aggregate_out: dict[str, dict] = {}
    for name in names:
        trades: list[dict] = []
        stop_caps = 0
        qty_zero = 0
        net_by_window = 0.0
        for block in ordered:
            variant = block["variants"][name]
            trades.extend(variant["trades"])
            stop_caps += variant["metrics"].get("stop_cap_sessions", 0)
            qty_zero += variant["metrics"].get("qty_zero_sessions", 0)
            net_by_window += float(variant["metrics"].get("net_profit", 0.0))
        stats = compute_stats(trades, INITIAL_CAPITAL)
        if stats["trades"] != len(trades):
            raise RuntimeError(f"{name}: trades {stats['trades']} != {len(trades)}")
        if abs(stats["net_profit"] - net_by_window) > 0.05:
            raise RuntimeError(
                f"{name}: neto agregado {stats['net_profit']} != suma ventanas "
                f"{net_by_window}"
            )
        aggregate_out[name] = {
            "stats": stats,
            "max_qty": max((int(t["qty"]) for t in trades), default=0),
            "ops_over_5": sum(1 for t in trades if int(t["qty"]) > 5),
            "stop_caps": stop_caps,
            "qty_zero": qty_zero,
            "net_by_window": round(net_by_window, 2),
        }
    return aggregate_out


def fmt(value, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def print_windows(ordered: list[dict[str, Any]], names: list[str]) -> None:
    print("\nNETO POR VENTANA")
    print("ventana " + " ".join(f"{name:>24}" for name in names))
    for block in ordered:
        cells = [
            f"{block['variants'][name]['metrics']['net_profit']:>24.2f}"
            for name in names
        ]
        print(f"{block['window']:>7} " + " ".join(cells))


def print_aggregate(aggregate_out: dict[str, dict], names: list[str]) -> None:
    print("\nAGREGADO W1-W6")
    print(
        "variante,trades,net,pf,expectancy,win_rate,max_dd,max_dd_pct,"
        "avg_r,total_r,max_qty,ops>5,stop_caps,qty0"
    )
    for name in names:
        item = aggregate_out[name]
        s = item["stats"]
        print(
            f"{name},{s['trades']},{s['net_profit']:.2f},"
            f"{fmt(s['profit_factor'])},{s['expectancy']:.2f},"
            f"{fmt(s['win_rate'], 1)},{s['max_drawdown']:.2f},"
            f"{s['max_drawdown_pct']:.2f},{fmt(s['avg_r'])},"
            f"{fmt(s['total_r'])},{item['max_qty']},{item['ops_over_5']},"
            f"{item['stop_caps']},{item['qty_zero']}"
        )


def assert_metrics(
    name: str,
    stats: dict,
    *,
    trades: int,
    net: float,
    pf: float,
    dd: float,
) -> None:
    if stats["trades"] != trades:
        raise AssertionError(f"{name}: trades {stats['trades']} != {trades}")
    if abs(float(stats["net_profit"]) - net) > 0.05:
        raise AssertionError(f"{name}: net {stats['net_profit']} != {net}")
    if stats["profit_factor"] is None or abs(
        float(stats["profit_factor"]) - pf
    ) > 0.01:
        raise AssertionError(f"{name}: PF {stats['profit_factor']} != {pf}")
    if abs(float(stats["max_drawdown"]) - dd) > 1.0:
        raise AssertionError(f"{name}: DD {stats['max_drawdown']} != {dd}")
