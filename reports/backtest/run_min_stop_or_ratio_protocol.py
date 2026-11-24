"""Ejecuta W1-W6 del protocolo v1.2 con y sin el filtro stop/ORB.

Solo desarrollo: las seis ventanas del lock suman 362 sesiones evaluadas y
terminan el 2026-06-30. El holdout (desde 2026-07-01) no se carga ni se usa.

Brazo baseline: lock tal cual (min_stop_or_ratio = 0.0).
Brazo filtro: mismo lock con min_stop_or_ratio = 0.25.

Guarda un JSON compacto con bloques, agregados, DD, concentración, mensual y
las comprobaciones de integridad. No modifica data/config.json ni el perfil.
"""

from __future__ import annotations

import json
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
from server.timeutil import et_date

LOCK_PATH = ROOT / "docs/protocolo_backtest.lock.json"
OUT_DIR = ROOT / "reports/backtest"
OUT_PATH = OUT_DIR / "min_stop_or_ratio_protocol.json"
HOLDOUT_START = date(2026, 7, 1)
DEVELOPMENT_END = WINDOWS[-1][2]
FILTER_RATIO = 0.25
TICK_SIZE = 0.25
GROUPS = (("W1", "W2"), ("W3",), ("W4",), ("W5", "W6"))
ARMS = (("baseline", 0.0), ("filter", FILTER_RATIO))


def _load_lock() -> dict[str, Any]:
    return json.loads(LOCK_PATH.read_text(encoding="utf-8"))


def _window_dataset(
    dataset: dict[str, Any], sessions: list[tuple[date, dict[str, list[Any]]]]
) -> dict[str, Any]:
    """Copia la procedencia del grupo limitada a las sesiones de una ventana."""
    window = dict(dataset)
    contracts = dataset.get("contracts") or {}
    selected_contracts = {
        symbol: sorted(contracts.get(symbol, [])) for symbol in bt.REQUIRED_SYMBOLS
    }
    hash_meta: dict[str, Any] = {
        "kind": "csv-selected",
        "contracts": selected_contracts,
    }
    if (
        dataset.get("contracts_declared")
        or dataset.get("series_mode") != "adjusted"
        or dataset.get("roll_sessions")
        or dataset.get("excluded_sessions")
    ):
        hash_meta.update(
            {
                "series_id": dataset.get("series_id"),
                "series_mode": dataset.get("series_mode"),
                "roll_sessions": dataset.get("roll_sessions") or [],
                "excluded_sessions": dataset.get("excluded_sessions") or [],
            }
        )
    window["selected_id"] = bt._hash_sessions(sessions, hash_meta)
    window["selected_range"] = bt._session_range(sessions)
    window["sessions"] = {
        "count": len(sessions),
        "available": len(dataset.get("all_sessions") or []),
        "excluded": len(dataset.get("excluded_sessions") or []),
        "dates": [day.isoformat() for day, _ in sessions],
    }
    window["requested_start"] = sessions[0][0].isoformat()
    window["selection"] = "start_date"
    return window


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


def _trade_signature(trade: dict[str, Any]) -> tuple:
    meta = trade.get("meta") or {}
    return (
        meta.get("signal_id"),
        trade.get("entry_ts"),
        trade.get("exit_ts"),
        trade.get("direction"),
        trade.get("qty"),
        trade.get("exit_reason"),
        round(float(trade.get("pnl") or 0.0), 6),
    )


def _orb_metrics(meta: dict[str, Any]) -> tuple[float | None, float | None]:
    high = meta.get("orb_high")
    low = meta.get("orb_low")
    if high is None or low is None:
        return None, None
    width = (float(high) - float(low)) / TICK_SIZE
    stop = meta.get("stop_ticks")
    ratio = (
        round(float(stop) / width, 6)
        if stop is not None and width > 0
        else None
    )
    return round(width, 3), ratio


def _compact_trade(trade: dict[str, Any]) -> dict[str, Any]:
    meta = trade.get("meta") or {}
    orb_width_ticks, stop_or_ratio = _orb_metrics(meta)
    return {
        "signal_id": meta.get("signal_id"),
        "window": trade.get("window"),
        "direction": trade.get("direction"),
        "qty": trade.get("qty"),
        "entry_ts": trade.get("entry_ts"),
        "exit_ts": trade.get("exit_ts"),
        "entry_price": trade.get("entry_price"),
        "exit_price": trade.get("exit_price"),
        "exit_reason": trade.get("exit_reason"),
        "pnl": trade.get("pnl"),
        "r_multiple": trade.get("r_multiple"),
        "stop_ticks": meta.get("stop_ticks"),
        "orb_width_ticks": orb_width_ticks,
        "stop_or_ratio": stop_or_ratio,
    }


def _run_group(keys: tuple[str, ...]) -> dict[tuple[str, str], dict[str, Any]]:
    lock = _load_lock()
    base = Settings.model_validate(lock["settings"])
    arm_configs = {
        label: apply_settings(base, {"risk": {"min_stop_or_ratio": ratio}})
        for label, ratio in ARMS
    }
    windows_by_id = {window["id"]: window for window in lock["windows"]}
    group_windows = [windows_by_id[key] for key in keys]
    start = date.fromisoformat(group_windows[0]["start"])
    days = sum(int(window["sessions"]) for window in group_windows)

    started = time.perf_counter()
    sessions, source, dataset = bt.prepare_dataset(
        base, days, start, allow_holdout=False
    )
    if source != "csv":
        raise RuntimeError(f"Se esperaba el CSV real; recibido {source!r}")
    if sessions[-1][0] >= HOLDOUT_START:
        raise RuntimeError(f"El dataset alcanza el holdout: {sessions[-1][0]}")
    print(
        f"[{keys[0]}..{keys[-1]}] {len(sessions)} sesiones cargadas en "
        f"{time.perf_counter() - started:.1f}s",
        flush=True,
    )

    output: dict[tuple[str, str], dict[str, Any]] = {}
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
                f"{window['id']}: {len(window_sessions)} sesiones, "
                f"se esperaban {window['sessions']}"
            )
        if window_sessions[-1][0] >= HOLDOUT_START:
            raise RuntimeError(f"{window['id']} toca el holdout")

        window_dataset = _window_dataset(dataset, window_sessions)
        for label, config in arm_configs.items():
            simulation_started = time.perf_counter()
            result = bt._simulate(
                config,
                window_sessions,
                source,
                f"{window['id']}-{label}",
                window_dataset,
            )
            trades = [
                dict(trade, window=window["id"]) for trade in result["trades"]
            ]
            if label == "filter":
                low = [
                    trade
                    for trade in trades
                    if (_compact_trade(trade)["stop_or_ratio"] or 0.0)
                    < FILTER_RATIO - 1e-9
                ]
                if low:
                    raise RuntimeError(
                        f"{window['id']}: {len(low)} operaciones con ratio < "
                        f"{FILTER_RATIO}"
                    )
            output[(window["id"], label)] = {
                "window": window,
                "selected_range": window_dataset["selected_range"],
                "sessions": len(window_sessions),
                "metrics": _summary(trades, config.risk.initial_capital),
                "trades": trades,
                "dataset": {
                    "file_hash": window_dataset.get("file_hash"),
                    "dataset_id": window_dataset.get("id"),
                    "series_id": window_dataset.get("series_id"),
                    "selected_id": window_dataset.get("selected_id"),
                },
                "experiment": {
                    "config_sha256": result["experiment"]["config_sha256"],
                    "dataset_sha256": result["experiment"]["dataset_sha256"],
                    "selected_id": result["experiment"].get("selected_id"),
                },
            }
            print(
                f"  {window['id']} {label}: {len(trades)} ops, "
                f"neto {result['metrics']['net_profit']}, "
                f"DD {result['metrics']['max_drawdown']} en "
                f"{time.perf_counter() - simulation_started:.1f}s",
                flush=True,
            )
    return output


def _official_full(window_id: str) -> dict[str, Any]:
    data = json.loads((OUT_DIR / f"{window_id}.json").read_text(encoding="utf-8"))
    return next(item for item in data if item["variant"] == "full")


def _months() -> list[str]:
    out: list[str] = []
    year, month = 2025, 1
    while (year, month) <= (2026, 6):
        out.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return out


def _monthly(trades: list[dict[str, Any]], initial_capital: float) -> list[dict[str, Any]]:
    stats = compute_stats(trades, initial_capital)
    by_key = {item["key"]: item for item in stats["monthly"]}
    out = []
    for key in _months():
        item = by_key.get(key) or {}
        out.append(
            {
                "key": key,
                "trades": int(item.get("trades") or 0),
                "pnl": round(float(item.get("pnl") or 0.0), 2),
                "wins": int(item.get("wins") or 0),
                "win_rate": item.get("win_rate", 0.0),
            }
        )
    return out


def _concentration(
    trades: list[dict[str, Any]],
    monthly: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    pnls = [float(t["pnl"]) for t in trades]
    positive_pnls = [p for p in pnls if p > 0]
    gross_profit = sum(positive_pnls)
    top5 = sorted(positive_pnls, reverse=True)[:5]
    top5_total = sum(top5)
    net = sum(pnls)
    best_month = max(monthly, key=lambda item: item["pnl"]) if monthly else None
    w4 = next((block for block in blocks if block["id"] == "W4"), None)
    positive_blocks = sum(max(float(block["metrics"]["net_profit"]), 0.0) for block in blocks)
    top_dates: dict[str, float] = {}
    for trade in trades:
        key = et_date(int(trade["exit_ts"])).isoformat()
        top_dates[key] = top_dates.get(key, 0.0) + float(trade["pnl"])
    top_dates_sorted = sorted(top_dates.items(), key=lambda item: item[1], reverse=True)[:3]
    sorted_trades = sorted(
        trades, key=lambda trade: float(trade["pnl"]), reverse=True
    )
    best_trade = sorted_trades[0] if sorted_trades else None

    return {
        "gross_profit": round(gross_profit, 2),
        "net_profit": round(net, 2),
        "top5_gross_profit": round(top5_total, 2),
        "top5_share_gross_profit_pct": (
            round(top5_total / gross_profit * 100, 2) if gross_profit > 0 else None
        ),
        "top5_share_net_pct": (
            round(top5_total / net * 100, 2) if net > 0 else None
        ),
        "best_month": best_month,
        "best_month_share_net_pct": (
            round(best_month["pnl"] / net * 100, 2)
            if best_month is not None and net > 0
            else None
        ),
        "w4_net_profit": round(float(w4["metrics"]["net_profit"]), 2) if w4 else None,
        "w4_share_net_pct": (
            round(float(w4["metrics"]["net_profit"]) / net * 100, 2)
            if w4 and net > 0
            else None
        ),
        "w4_share_positive_blocks_pct": (
            round(float(w4["metrics"]["net_profit"]) / positive_blocks * 100, 2)
            if w4 and positive_blocks > 0
            else None
        ),
        "positive_windows": sum(
            1 for block in blocks if float(block["metrics"]["net_profit"]) > 0
        ),
        "best_trade": (
            {
                "signal_id": (best_trade.get("meta") or {}).get("signal_id"),
                "date": et_date(int(best_trade["exit_ts"])).isoformat(),
                "pnl": round(float(best_trade["pnl"]), 2),
            }
            if best_trade
            else None
        ),
        "top_dates": [
            {"date": key, "pnl": round(value, 2)} for key, value in top_dates_sorted
        ],
        "top_trades": [
            {
                "signal_id": (trade.get("meta") or {}).get("signal_id"),
                "window": trade.get("window"),
                "date": et_date(int(trade["exit_ts"])).isoformat(),
                "pnl": round(float(trade["pnl"]), 2),
            }
            for trade in sorted_trades[:5]
        ],
    }


def _aggregate(
    output: dict[tuple[str, str], dict[str, Any]],
    label: str,
    initial_capital: float,
) -> dict[str, Any]:
    all_trades = [
        trade
        for window_id in WINDOW_IDS
        for trade in output[(window_id, label)]["trades"]
    ]
    ex_w4_trades = [trade for trade in all_trades if trade["window"] != "W4"]
    blocks = []
    for window_id in WINDOW_IDS:
        item = output[(window_id, label)]
        blocks.append(
            {
                "id": window_id,
                "start": item["window"]["start"],
                "end": item["window"]["end"],
                "sessions": item["sessions"],
                "first_et": item["selected_range"]["first_et"],
                "last_et": item["selected_range"]["last_et"],
                "metrics": item["metrics"],
            }
        )
    total = _summary(all_trades, initial_capital)
    ex_w4 = _summary(ex_w4_trades, initial_capital)
    monthly = _monthly(all_trades, initial_capital)
    concentration = _concentration(all_trades, monthly, blocks)
    return {
        "total": total,
        "ex_w4": ex_w4,
        "blocks": blocks,
        "monthly": monthly,
        "concentration": concentration,
        "trades": [_compact_trade(trade) for trade in all_trades],
    }


def _signal_ids(
    results: dict[tuple[str, str], dict[str, Any]], label: str
) -> set[Any]:
    return {
        (trade.get("meta") or {}).get("signal_id")
        for window_id in WINDOW_IDS
        for trade in results[(window_id, label)]["trades"]
    }


def _delta(left: dict[str, Any], right: dict[str, Any], key: str) -> float | None:
    a = left.get(key)
    b = right.get(key)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(float(b) - float(a), 2)
    return None


def _delta_metrics(
    baseline: dict[str, Any], filtered: dict[str, Any]
) -> dict[str, Any]:
    keys = (
        "trades",
        "win_rate",
        "profit_factor",
        "expectancy",
        "net_profit",
        "avg_r",
        "max_drawdown",
        "max_drawdown_pct",
        "worst_loss_streak",
    )
    return {key: _delta(baseline, filtered, key) for key in keys}


def main() -> int:
    lock = _load_lock()
    base = Settings.model_validate(lock["settings"])
    windows_by_id = {window["id"]: window for window in lock["windows"]}
    if sum(int(window["sessions"]) for window in lock["windows"]) != 362:
        raise RuntimeError("Las ventanas del lock no suman 362 sesiones")
    if lock["holdout"]["start"] != HOLDOUT_START.isoformat():
        raise RuntimeError("El inicio del holdout no coincide con el esperado")
    if base.risk.min_stop_or_ratio != 0.0:
        raise RuntimeError("El baseline del lock no está inactivo")

    results: dict[tuple[str, str], dict[str, Any]] = {}
    started = time.perf_counter()
    with ProcessPoolExecutor(max_workers=len(GROUPS)) as pool:
        futures = {pool.submit(_run_group, group): group for group in GROUPS}
        for future in as_completed(futures):
            group = futures[future]
            try:
                results.update(future.result())
            except Exception as exc:  # noqa: BLE001 - el informe debe fallar entero
                print(f"FALLO el grupo {group}: {exc}", flush=True)
                raise
    print(f"Simulaciones terminadas en {time.perf_counter() - started:.1f}s", flush=True)

    verification: dict[str, Any] = {
        "session_counts": {},
        "same_dataset_between_arms": {},
        "config_changed_between_arms": {},
        "baseline_matches_official": {},
        "filter_above_ratio": {},
        "holdout_used": False,
        "last_session": None,
    }
    for window_id in WINDOW_IDS:
        baseline = results[(window_id, "baseline")]
        filtered = results[(window_id, "filter")]
        expected = int(windows_by_id[window_id]["sessions"])
        verification["session_counts"][window_id] = {
            "baseline": baseline["sessions"],
            "filter": filtered["sessions"],
            "expected": expected,
        }
        if baseline["sessions"] != expected or filtered["sessions"] != expected:
            raise RuntimeError(f"{window_id}: conteo de sesiones inesperado")
        if baseline["dataset"]["selected_id"] != filtered["dataset"]["selected_id"]:
            raise RuntimeError(f"{window_id}: la muestra cambió entre brazos")
        if baseline["experiment"]["dataset_sha256"] != filtered["experiment"]["dataset_sha256"]:
            raise RuntimeError(f"{window_id}: cambió el dataset entre brazos")
        if baseline["experiment"]["config_sha256"] == filtered["experiment"]["config_sha256"]:
            raise RuntimeError(f"{window_id}: la configuración no cambió")
        verification["same_dataset_between_arms"][window_id] = True
        verification["config_changed_between_arms"][window_id] = True

        official = _official_full(window_id)
        baseline_sig = [_trade_signature(trade) for trade in baseline["trades"]]
        official_sig = [_trade_signature(trade) for trade in official["trades"]]
        matches = baseline_sig == official_sig
        verification["baseline_matches_official"][window_id] = {
            "matches": matches,
            "baseline_trades": len(baseline_sig),
            "official_trades": len(official_sig),
        }
        if not matches:
            raise RuntimeError(f"{window_id}: el baseline no coincide con W1-W6 oficial")

        ratios = [
            item["stop_or_ratio"]
            for item in map(_compact_trade, filtered["trades"])
            if item["stop_or_ratio"] is not None
        ]
        min_ratio = min(ratios) if ratios else None
        verification["filter_above_ratio"][window_id] = {
            "min_ratio": min_ratio,
            "trades": len(filtered["trades"]),
        }
        if min_ratio is not None and min_ratio < FILTER_RATIO - 1e-9:
            raise RuntimeError(f"{window_id}: el filtro dejó pasar {min_ratio}")
        last_et = filtered["selected_range"]["last_et"]
        last_date = str(last_et)[:10]
        verification["last_session"] = max(
            verification["last_session"] or "", last_date
        )

    if verification["last_session"] > DEVELOPMENT_END:
        raise RuntimeError("Se tocó el holdout")
    if sum(
        verification["session_counts"][window_id]["filter"]
        for window_id in WINDOW_IDS
    ) != 362:
        raise RuntimeError("El brazo filtrado no suma 362 sesiones")

    baseline_agg = _aggregate(results, "baseline", base.risk.initial_capital)
    filter_agg = _aggregate(results, "filter", base.risk.initial_capital)
    baseline_ids = _signal_ids(results, "baseline")
    filter_ids = _signal_ids(results, "filter")
    removed_ids = sorted(baseline_ids - filter_ids)
    new_ids = sorted(filter_ids - baseline_ids)

    monthly_comparison = []
    for base_month, filter_month in zip(baseline_agg["monthly"], filter_agg["monthly"]):
        monthly_comparison.append(
            {
                "key": base_month["key"],
                "baseline_pnl": base_month["pnl"],
                "filter_pnl": filter_month["pnl"],
                "delta_pnl": round(filter_month["pnl"] - base_month["pnl"], 2),
                "baseline_trades": base_month["trades"],
                "filter_trades": filter_month["trades"],
            }
        )

    report = {
        "schema": "min-stop-or-ratio-protocol-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "path": "docs/PROTOCOLO_BACKTEST.md",
            "version": lock["protocol_version"],
            "lock": "docs/protocolo_backtest.lock.json",
            "endpoint": "full",
            "windows": WINDOW_IDS,
            "sessions": sum(spec[3] for spec in WINDOWS),
            "development_end": DEVELOPMENT_END,
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_executed": False,
        },
        "filter_config": {
            "field": "risk.min_stop_or_ratio",
            "baseline": 0.0,
            "active": FILTER_RATIO,
        },
        "dataset": {
            "path": base.feed.csv_path,
            "series_mode": base.feed.series_mode,
            "exclude_roll_sessions": base.feed.exclude_roll_sessions,
            "file_hash": results[("W1", "baseline")]["dataset"]["file_hash"],
            "dataset_id": results[("W1", "baseline")]["dataset"]["dataset_id"],
        },
        "baseline": baseline_agg,
        "filter": filter_agg,
        "comparison": {
            "delta_total": _delta_metrics(baseline_agg["total"], filter_agg["total"]),
            "delta_ex_w4": _delta_metrics(baseline_agg["ex_w4"], filter_agg["ex_w4"]),
            "delta_by_window": {
                window_id: _delta_metrics(
                    results[(window_id, "baseline")]["metrics"],
                    results[(window_id, "filter")]["metrics"],
                )
                for window_id in WINDOW_IDS
            },
            "monthly": monthly_comparison,
            "removed_signal_ids": removed_ids,
            "new_signal_ids": new_ids,
            "removed_count": len(removed_ids),
            "new_count": len(new_ids),
            "dd_ex_w4_delta": round(
                baseline_agg["total"]["max_drawdown"]
                - baseline_agg["ex_w4"]["max_drawdown"],
                2,
            ),
            "filter_dd_ex_w4_delta": round(
                filter_agg["total"]["max_drawdown"]
                - filter_agg["ex_w4"]["max_drawdown"],
                2,
            ),
        },
        "verification": verification,
    }
    OUT_PATH.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    def fmt(value: Any, digits: int = 2) -> str:
        if value is None:
            return "n/d"
        if isinstance(value, float):
            return f"{value:,.{digits}f}"
        return f"{value:,}"

    print()
    print("Protocolo v1.2 - endpoint full - 362 sesiones - holdout no usado")
    print()
    print("BLOQUE  BRAZO      OPS      NETO       PF      DD $    DD %")
    for window_id in WINDOW_IDS:
        for label in ("baseline", "filter"):
            metrics = results[(window_id, label)]["metrics"]
            print(
                f"{window_id:<6} {label:<9} {metrics['trades']:>3} "
                f"{fmt(metrics['net_profit']):>10} "
                f"{fmt(metrics['profit_factor']):>7} "
                f"{fmt(metrics['max_drawdown']):>9} "
                f"{fmt(metrics['max_drawdown_pct']):>6}"
            )
    print()
    for label, data in (("BASELINE", baseline_agg), ("FILTER", filter_agg)):
        print(label)
        for key in ("total", "ex_w4"):
            metrics = data[key]
            print(
                f"  {key:<6} ops {metrics['trades']:>3} | "
                f"neto {fmt(metrics['net_profit']):>10} | "
                f"PF {fmt(metrics['profit_factor']):>5} | "
                f"DD {fmt(metrics['max_drawdown']):>9} "
                f"({fmt(metrics['max_drawdown_pct'])}%) | "
                f"peor racha {metrics['worst_loss_streak']}"
            )
        conc = data["concentration"]
        print(
            f"  concentracion: top5 {fmt(conc['top5_share_gross_profit_pct'])}% "
            f"del bruto | mejor mes {fmt(conc['best_month_share_net_pct'])}% "
            f"del neto | W4 {fmt(conc['w4_share_net_pct'])}% del neto"
        )
    print()
    print("Comparacion mensual (filtro - baseline):")
    for item in monthly_comparison:
        print(
            f"  {item['key']}  {fmt(item['baseline_pnl']):>10} -> "
            f"{fmt(item['filter_pnl']):>10}  delta {fmt(item['delta_pnl']):>10}"
        )
    print()
    print(f"Informe guardado en {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
