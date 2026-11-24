"""Filtro stop/ORB 0.25 sobre las ablaciones orb, orb_smt y orb_retest.

Mismas seis ventanas y mismo lock que el protocolo v1.2. El holdout no se
carga ni se ejecuta. Cada ventana se simula por separado, igual que en el
protocolo, para que el sizing no se contamine entre bloques.
"""

from __future__ import annotations

import json
import statistics
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import server.backtest as bt
from _windows import WINDOW_IDS, WINDOWS
from server.config import Settings, apply_settings
from server.stats import compute_stats

LOCK_PATH = ROOT / "docs/protocolo_backtest.lock.json"
OUT_DIR = ROOT / "reports/backtest"
OUT_PATH = OUT_DIR / "stop_or_ratio_ablations.json"
HOLDOUT_START = date(2026, 7, 1)
FILTER_RATIO = 0.25
TICK_SIZE = 0.25
GROUPS = (("W1", "W2"), ("W3",), ("W4",), ("W5", "W6"))
VARIANTS = ("orb", "orb_smt", "orb_retest")


def _load_lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _summary(trades: list[dict[str, Any]], initial_capital: float) -> dict[str, Any]:
    stats = compute_stats(trades, initial_capital)
    return {
        key: stats.get(key)
        for key in (
            "trades",
            "wins",
            "losses",
            "win_rate",
            "profit_factor",
            "expectancy",
            "net_profit",
            "gross_profit",
            "gross_loss",
            "avg_r",
            "max_drawdown",
            "max_drawdown_pct",
            "worst_loss_streak",
            "best_trade",
            "worst_trade",
        )
    }


def _orb_width_ticks(trade: dict[str, Any]) -> float | None:
    meta = trade.get("meta") or {}
    high = meta.get("orb_high")
    low = meta.get("orb_low")
    if high is None or low is None:
        return None
    return (float(high) - float(low)) / TICK_SIZE


def _ratio(trade: dict[str, Any]) -> float | None:
    width = _orb_width_ticks(trade)
    stop = (trade.get("meta") or {}).get("stop_ticks")
    if width is None or stop is None or width <= 0:
        return None
    return float(stop) / width


def _trade_diagnostic(trade: dict[str, Any]) -> dict[str, Any]:
    meta = trade.get("meta") or {}
    width = _orb_width_ticks(trade)
    ratio = _ratio(trade)
    high = meta.get("orb_high")
    low = meta.get("orb_low")
    entry = trade.get("entry_price")
    stop = meta.get("stop_ticks")
    mid = (float(high) + float(low)) / 2 if high is not None and low is not None else None
    side = 1 if trade.get("direction") == "long" else -1
    entry_to_mid = (float(entry) - mid) * side if entry is not None and mid is not None else None
    stop_to_mid = (
        (float(entry) - side * float(stop) * TICK_SIZE - mid) * side
        if entry is not None and stop is not None and mid is not None
        else None
    )
    return {
        "signal_id": meta.get("signal_id"),
        "window": trade.get("window"),
        "direction": trade.get("direction"),
        "qty": trade.get("qty"),
        "pnl": trade.get("pnl"),
        "ratio": ratio,
        "stop_ticks": stop,
        "orb_width_ticks": width,
        "half_orb_width_ticks": width / 2 if width is not None else None,
        "entry_to_mid_ticks": entry_to_mid / TICK_SIZE if entry_to_mid is not None else None,
        "stop_to_mid_ticks": stop_to_mid / TICK_SIZE if stop_to_mid is not None else None,
    }


def _stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"trades": 0}
    ratios = [row["ratio"] for row in rows if row["ratio"] is not None]
    widths = [row["orb_width_ticks"] for row in rows if row["orb_width_ticks"] is not None]
    stops = [row["stop_ticks"] for row in rows if row["stop_ticks"] is not None]
    entries = [row["entry_to_mid_ticks"] for row in rows if row["entry_to_mid_ticks"] is not None]
    stops_mid = [row["stop_to_mid_ticks"] for row in rows if row["stop_to_mid_ticks"] is not None]
    return {
        "trades": len(rows),
        "below_025": sum(1 for ratio in ratios if ratio < FILTER_RATIO - 1e-9),
        "all_below_025": bool(ratios) and all(
            ratio < FILTER_RATIO - 1e-9 for ratio in ratios
        ),
        "ratio_min": round(min(ratios), 6) if ratios else None,
        "ratio_median": round(statistics.median(ratios), 6) if ratios else None,
        "ratio_max": round(max(ratios), 6) if ratios else None,
        "orb_width_median_ticks": round(statistics.median(widths), 1) if widths else None,
        "orb_width_min_ticks": round(min(widths), 1) if widths else None,
        "half_orb_width_median_ticks": round(statistics.median(widths) / 2, 1) if widths else None,
        "stop_median_ticks": round(statistics.median(stops), 1) if stops else None,
        "stop_max_ticks": round(max(stops), 1) if stops else None,
        "entry_to_mid_median_ticks": round(statistics.median(entries), 1) if entries else None,
        "stop_to_mid_median_ticks": round(statistics.median(stops_mid), 1) if stops_mid else None,
    }


def _run_group(task: tuple[str, tuple[str, ...]]) -> tuple[str, dict[str, Any]]:
    variant, keys = task
    lock = _load_lock()
    base = Settings.model_validate(lock["settings"])
    _, patch = bt.VARIANTS[variant]
    config = apply_settings(
        base, {**patch, "risk": {"min_stop_or_ratio": FILTER_RATIO}}
    )
    if config.risk.min_stop_or_ratio != FILTER_RATIO:
        raise RuntimeError(f"{variant}: filtro no activo")
    windows_by_id = {window["id"]: window for window in lock["windows"]}
    group_windows = [windows_by_id[key] for key in keys]
    start = date.fromisoformat(group_windows[0]["start"])
    days = sum(int(window["sessions"]) for window in group_windows)

    started = time.perf_counter()
    sessions, source, dataset = bt.prepare_dataset(
        base, days, start, allow_holdout=False
    )
    if source != "csv":
        raise RuntimeError(f"{variant}: se esperaba CSV, recibido {source!r}")
    if sessions[-1][0] >= HOLDOUT_START:
        raise RuntimeError(f"{variant}: el dataset toca el holdout")
    print(
        f"[{variant} {keys[0]}..{keys[-1]}] {len(sessions)} sesiones en "
        f"{time.perf_counter() - started:.1f}s",
        flush=True,
    )

    output: dict[str, Any] = {}
    for window in group_windows:
        window_start = date.fromisoformat(window["start"])
        window_end = date.fromisoformat(window["end"])
        window_sessions = [
            (day, data)
            for day, data in sessions
            if window_start <= day <= window_end
        ]
        if len(window_sessions) != int(window["sessions"]):
            raise RuntimeError(
                f"{variant} {window['id']}: {len(window_sessions)} sesiones, "
                f"se esperaban {window['sessions']}"
            )
        result = bt._simulate(
            config,
            window_sessions,
            source,
            f"{variant}-{window['id']}-filter",
            dataset,
        )
        trades = [dict(trade, window=window["id"]) for trade in result["trades"]]
        bad = [
            trade
            for trade in trades
            if (_ratio(trade) is not None and _ratio(trade) < FILTER_RATIO - 1e-9)
        ]
        if bad:
            raise RuntimeError(f"{variant} {window['id']}: {len(bad)} ops bajo el filtro")
        output[window["id"]] = {
            "sessions": len(window_sessions),
            "metrics": _summary(trades, config.risk.initial_capital),
            "trades": trades,
        }
        print(
            f"  {variant} {window['id']}: {len(trades)} ops, "
            f"neto {result['metrics']['net_profit']}, "
            f"DD {result['metrics']['max_drawdown']}",
            flush=True,
        )
    return variant, output


def _load_variant_window(variant: str, window_id: str) -> dict[str, Any]:
    data = json.loads(
        (OUT_DIR / f"{window_id}.json").read_text(encoding="utf-8")
    )
    return next(item for item in data if item["variant"] == variant)


def _baseline_trades(variant: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trades: list[dict[str, Any]] = []
    blocks: dict[str, Any] = {}
    for window_id in WINDOW_IDS:
        item = _load_variant_window(variant, window_id)
        window_trades = [
            dict(trade, window=window_id) for trade in item.get("trades", [])
        ]
        trades.extend(window_trades)
        blocks[window_id] = {
            "trades": len(window_trades),
            "metrics": item["metrics"],
        }
    return trades, blocks


def main() -> int:
    lock = _load_lock()
    base = Settings.model_validate(lock["settings"])
    windows_by_id = {window["id"]: window for window in lock["windows"]}
    if sum(int(window["sessions"]) for window in lock["windows"]) != 362:
        raise RuntimeError("Las ventanas del lock no suman 362 sesiones")
    if lock["holdout"]["start"] != HOLDOUT_START.isoformat():
        raise RuntimeError("El holdout del lock no coincide")
    if base.risk.min_stop_or_ratio != 0.0:
        raise RuntimeError("El baseline del lock no está inactivo")

    started = time.perf_counter()
    results: dict[str, dict[str, Any]] = {variant: {} for variant in VARIANTS}
    tasks = [(variant, group) for variant in VARIANTS for group in GROUPS]
    with ProcessPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(_run_group, task): task for task in tasks}
        for future in as_completed(futures):
            variant, output = future.result()
            results[variant].update(output)
    print(f"Simulaciones terminadas en {time.perf_counter() - started:.1f}s", flush=True)

    report: dict[str, Any] = {
        "schema": "stop-or-ratio-ablations-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "version": lock["protocol_version"],
            "windows": WINDOW_IDS,
            "sessions": sum(spec[3] for spec in WINDOWS),
            "development_end": WINDOWS[-1][2],
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_executed": False,
        },
        "filter": {
            "field": "risk.min_stop_or_ratio",
            "baseline": 0.0,
            "active": FILTER_RATIO,
        },
        "variants": {},
        "diagnosis_2026": {},
        "verification": {
            "session_counts": {},
            "holdout_used": False,
            "all_filter_trades_above_ratio": True,
        },
    }

    for variant in VARIANTS:
        baseline_trades, baseline_blocks = _baseline_trades(variant)
        filter_trades = [
            trade
            for window_id in WINDOW_IDS
            for trade in results[variant][window_id]["trades"]
        ]
        filter_blocks = {
            window_id: results[variant][window_id]["metrics"]
            for window_id in WINDOW_IDS
        }
        baseline_ids = {
            (trade.get("meta") or {}).get("signal_id") for trade in baseline_trades
        }
        filter_ids = {
            (trade.get("meta") or {}).get("signal_id") for trade in filter_trades
        }
        removed = sorted(baseline_ids - filter_ids)
        added = sorted(filter_ids - baseline_ids)
        if added:
            raise RuntimeError(f"{variant}: el filtro creó {len(added)} señales")
        baseline_rows = [_trade_diagnostic(trade) for trade in baseline_trades]
        filter_rows = [_trade_diagnostic(trade) for trade in filter_trades]
        baseline_2025 = [row for row in baseline_rows if row["window"] in ("W1", "W2", "W3", "W4")]
        baseline_2026 = [row for row in baseline_rows if row["window"] in ("W5", "W6")]
        filter_2026 = [row for row in filter_rows if row["window"] in ("W5", "W6")]

        report["variants"][variant] = {
            "label": bt.VARIANTS[variant][0],
            "baseline": {
                "total": _summary(baseline_trades, base.risk.initial_capital),
                "blocks": baseline_blocks,
            },
            "filter": {
                "total": _summary(filter_trades, base.risk.initial_capital),
                "blocks": filter_blocks,
            },
            "comparison": {
                "removed_count": len(removed),
                "new_count": len(added),
                "removed_signal_ids": removed,
                "new_signal_ids": added,
                "removed_2026": sum(
                    1 for row in baseline_2026 if row["signal_id"] in set(removed)
                ),
                "filter_2026_trades": len(filter_2026),
            },
            "diagnosis": {
                "baseline_2025": _stats(baseline_2025),
                "baseline_2026": _stats(baseline_2026),
                "filter_2026": _stats(filter_2026),
                "baseline_2026_rows": baseline_2026,
            },
        }

        for window_id in WINDOW_IDS:
            item = results[variant][window_id]
            expected = int(windows_by_id[window_id]["sessions"])
            report["verification"]["session_counts"][f"{variant}-{window_id}"] = {
                "sessions": item["sessions"],
                "expected": expected,
            }
            if item["sessions"] != expected:
                raise RuntimeError(f"{variant} {window_id}: sesiones inesperadas")
        if any(
            row["ratio"] is not None and row["ratio"] < FILTER_RATIO - 1e-9
            for row in filter_rows
        ):
            report["verification"]["all_filter_trades_above_ratio"] = False
            raise RuntimeError(f"{variant}: el filtro dejó pasar una operación")

    retest_2026 = report["variants"]["orb_retest"]["diagnosis"]["baseline_2026"]
    report["diagnosis_2026"] = {
        "orb_2026_trades": report["variants"]["orb"]["diagnosis"]["baseline_2026"]["trades"],
        "orb_smt_2026_trades": report["variants"]["orb_smt"]["diagnosis"]["baseline_2026"]["trades"],
        "retest_2026_trades": retest_2026["trades"],
        "retest_2026_all_below_025": retest_2026.get("all_below_025"),
        "retest_2026_ratio_range": [
            retest_2026.get("ratio_min"),
            retest_2026.get("ratio_max"),
        ],
        "retest_2026_ratio_median": retest_2026.get("ratio_median"),
        "retest_2026_orb_width_min_ticks": retest_2026.get("orb_width_min_ticks"),
        "retest_2026_orb_width_median_ticks": retest_2026.get(
            "orb_width_median_ticks"
        ),
        "retest_2026_half_orb_width_median_ticks": retest_2026.get(
            "half_orb_width_median_ticks"
        ),
        "max_sl_ticks": base.risk.max_sl_ticks,
        "retest_2026_stop_median_ticks": retest_2026.get("stop_median_ticks"),
        "retest_2026_stop_max_ticks": retest_2026.get("stop_max_ticks"),
    }

    OUT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    print()
    print(f"{'VARIANTE':<12} {'BASE':>5} {'FILTRO':>6} {'NETO':>10} {'PF':>5} {'DD':>8} {'2026':>5}")
    for variant in VARIANTS:
        data = report["variants"][variant]
        base_metrics = data["baseline"]["total"]
        filter_metrics = data["filter"]["total"]
        print(
            f"{variant:<12} {base_metrics['trades']:>5} {filter_metrics['trades']:>6} "
            f"{filter_metrics['net_profit']:>10,.2f} {filter_metrics['profit_factor']:>5.2f} "
            f"{filter_metrics['max_drawdown']:>8,.2f} {data['comparison']['filter_2026_trades']:>5}"
        )
    print()
    print(f"Informe guardado en {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
