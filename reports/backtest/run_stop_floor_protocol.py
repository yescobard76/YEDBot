"""Compara rechazo stop/ORB < 0.25 contra stop mínimo 0.25*ORB.

Rama de rechazo: ya calculada en min_stop_or_ratio_protocol.json.
Rama de stop mínimo: no rechaza por ratio; si el stop es más estrecho que
0.25*ORB, lo amplía hasta ese mínimo. El tope max_sl_ticks sigue activo: las
señales cuyo stop ampliado supera 200 ticks se rechazan por ese tope, no por
el ratio.

La política de target se selecciona con FLOOR_TARGET_POLICY:

- ``widened`` (default): recalcula el target a ``tp_rr * stop_ampliado``;
- ``original``: conserva el target que calculó la estrategia con el stop
  original. Sirve para separar el efecto del stop del efecto del target.

Solo desarrollo (W1-W6, 362 sesiones). El holdout no se carga ni se usa.
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
REPORTS = ROOT / "reports/backtest"
if str(REPORTS) not in sys.path:
    sys.path.insert(0, str(REPORTS))

import server.backtest as bt
from server.config import Settings, apply_settings
from server.risk import RiskManager
from server.stats import compute_stats
from server.timeutil import et_date

from run_min_stop_or_ratio_protocol import (  # noqa: E402
    DEVELOPMENT_END,
    FILTER_RATIO,
    GROUPS,
    HOLDOUT_START,
    WINDOW_IDS,
    _compact_trade,
    _load_lock,
    _monthly,
    _summary,
    _window_dataset,
)

BASE_REPORT = REPORTS / "min_stop_or_ratio_protocol.json"
MAX_SL = int(os.environ.get("FLOOR_MAX_SL", "200"))
TARGET_POLICY = os.environ.get("FLOOR_TARGET_POLICY", "widened").strip().lower()
if TARGET_POLICY not in {"widened", "original"}:
    raise SystemExit(
        "FLOOR_TARGET_POLICY debe ser 'widened' u 'original'; "
        f"recibido {TARGET_POLICY!r}"
    )
if TARGET_POLICY == "widened":
    OUT_PATH = REPORTS / (
        "stop_floor_protocol.json"
        if MAX_SL == 200
        else f"stop_floor_protocol_cap{MAX_SL}.json"
    )
else:
    OUT_PATH = REPORTS / (
        "stop_floor_protocol_original_target.json"
        if MAX_SL == 200
        else f"stop_floor_protocol_cap{MAX_SL}_original_target.json"
    )


def _signal_id(trade: dict[str, Any]) -> str | None:
    if trade.get("signal_id"):
        return str(trade["signal_id"])
    meta = trade.get("meta") or {}
    return str(meta.get("signal_id")) if meta.get("signal_id") else None


def _apply_floor(
    manager: RiskManager, signal: Any, target_policy: str
) -> dict[str, Any] | None:
    """Amplía el stop si su ratio inicial es menor que FILTER_RATIO.

    ``target_policy`` decide si el target se recalcula sobre el stop ampliado
    (``widened``) o se conserva el target original (``original``).
    Devuelve el evento de ampliación, o None si la señal no necesita el floor.
    """
    meta = signal.meta if isinstance(signal.meta, dict) else {}
    try:
        orb_high = float(meta["orb_high"])
        orb_low = float(meta["orb_low"])
    except (KeyError, TypeError, ValueError):
        return None
    tick = manager.settings.execution.tick_size
    width_ticks = (orb_high - orb_low) / tick
    if not math.isfinite(width_ticks) or width_ticks <= 0:
        return None
    original_ticks = abs(float(signal.entry_price) - float(signal.stop)) / tick
    floor_ticks = FILTER_RATIO * width_ticks
    if original_ticks >= floor_ticks - 1e-9:
        return None
    distance = floor_ticks * tick
    original_stop = float(signal.stop)
    original_target = float(signal.target)
    if signal.direction == "long":
        signal.stop = float(signal.entry_price) - distance
        signal.target = (
            float(signal.entry_price)
            + manager.settings.strategy.tp_rr * distance
            if target_policy == "widened"
            else original_target
        )
    else:
        signal.stop = float(signal.entry_price) + distance
        signal.target = (
            float(signal.entry_price)
            - manager.settings.strategy.tp_rr * distance
            if target_policy == "widened"
            else original_target
        )
    applied_target = float(signal.target)
    target_distance = abs(applied_target - float(signal.entry_price))
    target_r_multiple = target_distance / distance if distance > 0 else None
    meta["stop_floor_applied"] = True
    meta["stop_floor_target_policy"] = target_policy
    meta["stop_floor_original_ticks"] = round(original_ticks, 3)
    meta["stop_floor_original_stop"] = original_stop
    meta["stop_floor_original_target"] = original_target
    meta["stop_floor_applied_target"] = applied_target
    meta["stop_floor_target_r_multiple"] = (
        round(target_r_multiple, 3) if target_r_multiple is not None else None
    )
    meta["stop_floor_orb_width_ticks"] = round(width_ticks, 3)
    meta["stop_ticks"] = round(floor_ticks, 3)
    return {
        "signal_id": signal.id,
        "date": et_date(int(signal.ts)).isoformat(),
        "direction": signal.direction,
        "original_ticks": round(original_ticks, 3),
        "floor_ticks": round(floor_ticks, 3),
        "orb_width_ticks": round(width_ticks, 3),
        "target_policy": target_policy,
        "original_target": original_target,
        "applied_target": applied_target,
        "target_r_multiple": (
            round(target_r_multiple, 3) if target_r_multiple is not None else None
        ),
        "widened": True,
    }


def _run_group(keys: tuple[str, ...]) -> dict[str, Any]:
    lock = _load_lock()
    base = Settings.model_validate(lock["settings"])
    windows_by_id = {window["id"]: window for window in lock["windows"]}
    group_windows = [windows_by_id[key] for key in keys]
    start = date.fromisoformat(group_windows[0]["start"])
    days = sum(int(window["sessions"]) for window in group_windows)

    started = time.perf_counter()
    sessions, source, dataset = bt.prepare_dataset(
        base, days, start, allow_holdout=False
    )
    if source != "csv":
        raise RuntimeError(f"Se esperaba CSV; recibido {source!r}")
    if sessions[-1][0] >= HOLDOUT_START:
        raise RuntimeError(f"El dataset alcanza el holdout: {sessions[-1][0]}")
    print(
        f"[{keys[0]}..{keys[-1]}] {len(sessions)} sesiones cargadas en "
        f"{time.perf_counter() - started:.1f}s",
        flush=True,
    )

    output: dict[tuple[str, str], dict[str, Any]] = {}
    events: dict[str, dict[str, Any]] = {}
    original_evaluate = RiskManager.evaluate

    def evaluate_with_floor(self, signal, **kwargs):
        event = _apply_floor(self, signal, TARGET_POLICY)
        decision = original_evaluate(self, signal, **kwargs)
        if event is not None:
            event["ok"] = bool(decision.ok)
            event["reason"] = decision.reason
            event["decision_stop_ticks"] = round(float(decision.stop_ticks), 3)
            events.setdefault(event["signal_id"], event)
        return decision

    RiskManager.evaluate = evaluate_with_floor
    try:
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
            config = apply_settings(
                base,
                {
                    "risk": {
                        "min_stop_or_ratio": 0.0,
                        "max_sl_ticks": MAX_SL,
                    }
                },
            )
            assert config.risk.min_stop_or_ratio == 0.0
            assert config.risk.max_sl_ticks == MAX_SL
            simulation_started = time.perf_counter()
            result = bt._simulate(
                config,
                window_sessions,
                source,
                f"{window['id']}-stop-floor",
                window_dataset,
            )
            trades = [
                dict(trade, window=window["id"]) for trade in result["trades"]
            ]
            floor_trades = [
                trade
                for trade in trades
                if (trade.get("meta") or {}).get("stop_floor_applied")
            ]
            low_after = [
                trade
                for trade in floor_trades
                if (_compact_trade(trade)["stop_or_ratio"] or 0.0)
                < FILTER_RATIO - 1e-9
            ]
            if low_after:
                raise RuntimeError(
                    f"{window['id']}: {len(low_after)} stops ampliados siguen "
                    f"por debajo de {FILTER_RATIO}"
                )
            output[(window["id"], "floor")] = {
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
                "elapsed_sec": round(time.perf_counter() - simulation_started, 1),
            }
            print(
                f"  {window['id']} stop-floor: {len(trades)} ops, "
                f"neto {result['metrics']['net_profit']}, "
                f"DD {result['metrics']['max_drawdown']} en "
                f"{time.perf_counter() - simulation_started:.1f}s",
                flush=True,
            )
    finally:
        RiskManager.evaluate = original_evaluate

    return {"output": output, "events": list(events.values())}


def _concentration(
    trades: list[dict[str, Any]],
    monthly: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    pnls = [float(t["pnl"]) for t in trades]
    gross_profit = sum(p for p in pnls if p > 0)
    top5 = sorted((p for p in pnls if p > 0), reverse=True)[:5]
    net = sum(pnls)
    best_month = max(monthly, key=lambda item: item["pnl"]) if monthly else None
    w4 = next((block for block in blocks if block["id"] == "W4"), None)
    positive_blocks = sum(
        max(float(block["metrics"]["net_profit"]), 0.0) for block in blocks
    )
    top_dates: dict[str, float] = {}
    for trade in trades:
        key = et_date(int(trade["exit_ts"])).isoformat()
        top_dates[key] = top_dates.get(key, 0.0) + float(trade["pnl"])
    top_dates_sorted = sorted(top_dates.items(), key=lambda item: item[1], reverse=True)[:3]
    best_trade = max(trades, key=lambda trade: float(trade["pnl"]), default=None)
    return {
        "gross_profit": round(gross_profit, 2),
        "net_profit": round(net, 2),
        "top5_gross_profit": round(sum(top5), 2),
        "top5_share_gross_profit_pct": (
            round(sum(top5) / gross_profit * 100, 2) if gross_profit > 0 else None
        ),
        "top5_share_net_pct": round(sum(top5) / net * 100, 2) if net > 0 else None,
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
                "signal_id": _signal_id(best_trade),
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
                "signal_id": _signal_id(trade),
                "window": trade.get("window"),
                "date": et_date(int(trade["exit_ts"])).isoformat(),
                "pnl": round(float(trade["pnl"]), 2),
            }
            for trade in sorted(
                trades, key=lambda item: float(item["pnl"]), reverse=True
            )[:5]
        ],
    }


def _aggregate(
    trades: list[dict[str, Any]],
    blocks: list[dict[str, Any]],
) -> dict[str, Any]:
    total = _summary(trades, 25_000)
    ex_w4 = _summary([trade for trade in trades if trade["window"] != "W4"], 25_000)
    monthly = _monthly(trades, 25_000)
    return {
        "total": total,
        "ex_w4": ex_w4,
        "blocks": blocks,
        "monthly": monthly,
        "concentration": _concentration(trades, monthly, blocks),
        "trades": trades,
    }


def _blocks_from_output(
    output: dict[tuple[str, str], dict[str, Any]], label: str
) -> list[dict[str, Any]]:
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
    return blocks


def _delta(left: dict[str, Any], right: dict[str, Any], key: str) -> float | None:
    a = left.get(key)
    b = right.get(key)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return round(float(b) - float(a), 2)
    return None


def _delta_metrics(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _delta(left, right, key)
        for key in (
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
    }


def main() -> int:
    if not BASE_REPORT.exists():
        raise FileNotFoundError(f"Falta el informe base {BASE_REPORT}")
    base_report = json.loads(BASE_REPORT.read_text(encoding="utf-8"))
    if base_report["protocol"]["holdout_executed"]:
        raise RuntimeError("El informe base indica holdout ejecutado")
    if not all(
        item["matches"]
        for item in base_report["verification"]["baseline_matches_official"].values()
    ):
        raise RuntimeError("El baseline base no coincide con W1-W6")
    lock = _load_lock()
    if sum(int(window["sessions"]) for window in lock["windows"]) != 362:
        raise RuntimeError("Las ventanas no suman 362 sesiones")

    started = time.perf_counter()
    results: dict[tuple[str, str], dict[str, Any]] = {}
    events: list[dict[str, Any]] = []
    with ProcessPoolExecutor(max_workers=len(GROUPS)) as pool:
        futures = {pool.submit(_run_group, group): group for group in GROUPS}
        for future in as_completed(futures):
            group = futures[future]
            try:
                payload = future.result()
            except Exception as exc:  # noqa: BLE001
                print(f"FALLO el grupo {group}: {exc}", flush=True)
                raise
            results.update(payload["output"])
            events.extend(payload["events"])
    print(f"Simulaciones terminadas en {time.perf_counter() - started:.1f}s", flush=True)

    missing = [
        (window_id, "floor")
        for window_id in WINDOW_IDS
        if (window_id, "floor") not in results
    ]
    if missing:
        raise RuntimeError(f"Faltan resultados: {missing}")

    session_counts = {
        window_id: results[(window_id, "floor")]["sessions"]
        for window_id in WINDOW_IDS
    }
    if sum(session_counts.values()) != 362:
        raise RuntimeError(f"El floor no suma 362 sesiones: {session_counts}")
    last_session = max(
        results[(window_id, "floor")]["selected_range"]["last_et"][:10]
        for window_id in WINDOW_IDS
    )
    if last_session > DEVELOPMENT_END:
        raise RuntimeError(f"Se tocó el holdout: {last_session}")

    floor_trades = [
        _compact_trade(trade)
        for window_id in WINDOW_IDS
        for trade in results[(window_id, "floor")]["trades"]
    ]
    floor_blocks = _blocks_from_output(results, "floor")
    floor_agg = _aggregate(floor_trades, floor_blocks)
    floor_low = [
        trade
        for trade in floor_trades
        if trade["stop_or_ratio"] is not None
        and trade["stop_or_ratio"] < FILTER_RATIO - 1e-9
    ]
    if floor_low:
        raise RuntimeError(
            f"El floor dejó {len(floor_low)} operaciones por debajo de {FILTER_RATIO}"
        )
    baseline_agg = {
        key: base_report["baseline"][key]
        for key in ("total", "ex_w4", "blocks", "monthly", "concentration")
    }
    baseline_agg["trades"] = base_report["baseline"]["trades"]
    filter_agg = {
        key: base_report["filter"][key]
        for key in ("total", "ex_w4", "blocks", "monthly", "concentration")
    }
    filter_agg["trades"] = base_report["filter"]["trades"]

    baseline_ids = {_signal_id(trade) for trade in baseline_agg["trades"]}
    filter_ids = {_signal_id(trade) for trade in filter_agg["trades"]}
    floor_ids = {_signal_id(trade) for trade in floor_agg["trades"]}
    low_ratio_base = [
        trade
        for trade in baseline_agg["trades"]
        if (trade.get("stop_or_ratio") or 1.0) < FILTER_RATIO - 1e-9
    ]
    low_ratio_winners = [
        trade
        for trade in low_ratio_base
        if float(trade["pnl"]) > 0
    ]
    winner_outcomes = []
    floor_by_id = {_signal_id(trade): trade for trade in floor_agg["trades"]}
    floor_full_by_id = {
        _signal_id(trade): trade
        for window_id in WINDOW_IDS
        for trade in results[(window_id, "floor")]["trades"]
    }
    for trade in sorted(low_ratio_winners, key=lambda item: float(item["pnl"]), reverse=True):
        sid = _signal_id(trade)
        floor_trade = floor_by_id.get(sid)
        floor_full = floor_full_by_id.get(sid)
        floor_meta = (floor_full or {}).get("meta") or {}
        winner_outcomes.append(
            {
                "signal_id": sid,
                "baseline_pnl": round(float(trade["pnl"]), 2),
                "baseline_stop_ticks": trade.get("stop_ticks"),
                "floor_stop_ticks": (
                    floor_meta.get("stop_ticks")
                    if floor_meta
                    else (floor_trade.get("stop_ticks") if floor_trade else None)
                ),
                "floor_pnl": (
                    round(float(floor_trade["pnl"]), 2) if floor_trade else None
                ),
                "floor_exit_reason": (
                    floor_trade.get("exit_reason") if floor_trade else None
                ),
                "floor_target": floor_meta.get("stop_floor_applied_target"),
                "floor_target_r_multiple": floor_meta.get(
                    "stop_floor_target_r_multiple"
                ),
                "floor_original_target": floor_meta.get(
                    "stop_floor_original_target"
                ),
                "floor_target_policy": floor_meta.get("stop_floor_target_policy"),
                "still_profitable": bool(
                    floor_trade and float(floor_trade["pnl"]) > 0
                ),
                "preserved": floor_trade is not None,
            }
        )

    event_summary = {
        "low_ratio_signals": len(events),
        "widened": sum(1 for event in events if event.get("widened")),
        "accepted": sum(1 for event in events if event.get("ok")),
        "rejected": sum(1 for event in events if not event.get("ok")),
        "rejected_by_max_sl": sum(
            1
            for event in events
            if not event.get("ok")
            and "excede el máximo" in str(event.get("reason", "")).lower()
        ),
        "rejected_other": sum(
            1
            for event in events
            if not event.get("ok")
            and "excede el máximo" not in str(event.get("reason", "")).lower()
        ),
        "reasons": {},
    }
    for event in events:
        if not event.get("ok"):
            reason = str(event.get("reason") or "sin motivo")
            event_summary["reasons"][reason] = event_summary["reasons"].get(reason, 0) + 1

    monthly_comparison = []
    for base_month, filter_month, floor_month in zip(
        baseline_agg["monthly"], filter_agg["monthly"], floor_agg["monthly"]
    ):
        monthly_comparison.append(
            {
                "key": base_month["key"],
                "baseline_pnl": base_month["pnl"],
                "filter_pnl": filter_month["pnl"],
                "floor_pnl": floor_month["pnl"],
                "floor_minus_baseline": round(
                    floor_month["pnl"] - base_month["pnl"], 2
                ),
                "floor_minus_filter": round(
                    floor_month["pnl"] - filter_month["pnl"], 2
                ),
                "baseline_trades": base_month["trades"],
                "filter_trades": filter_month["trades"],
                "floor_trades": floor_month["trades"],
            }
        )

    report = {
        "schema": "stop-floor-protocol-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "path": "docs/PROTOCOLO_BACKTEST.md",
            "version": lock["protocol_version"],
            "endpoint": "full",
            "windows": WINDOW_IDS,
            "sessions": 362,
            "development_end": DEVELOPMENT_END,
            "holdout_start": HOLDOUT_START.isoformat(),
            "holdout_executed": False,
        },
        "arms": {
            "baseline": {
                "description": "lock v1.2 sin filtro",
                "min_stop_or_ratio": 0.0,
            },
            "reject": {
                "description": "rechaza si stop/ORB < 0.25",
                "min_stop_or_ratio": FILTER_RATIO,
            },
            "stop_floor": {
                "description": (
                    "amplía el stop a 0.25*ORB; target original o recalculado; "
                    "no rechaza por ratio"
                ),
                "min_stop_or_ratio": 0.0,
                "floor_ratio": FILTER_RATIO,
                "max_sl_ticks": MAX_SL,
                "target_policy_id": TARGET_POLICY,
                "target_policy": (
                    "tp_rr * stop_ampliado"
                    if TARGET_POLICY == "widened"
                    else "target_original_sin_recalcular"
                ),
            },
        },
        "baseline": baseline_agg,
        "reject": filter_agg,
        "stop_floor": floor_agg,
        "comparison": {
            "floor_vs_baseline_total": _delta_metrics(
                baseline_agg["total"], floor_agg["total"]
            ),
            "floor_vs_baseline_ex_w4": _delta_metrics(
                baseline_agg["ex_w4"], floor_agg["ex_w4"]
            ),
            "floor_vs_filter_total": _delta_metrics(
                filter_agg["total"], floor_agg["total"]
            ),
            "floor_vs_filter_ex_w4": _delta_metrics(
                filter_agg["ex_w4"], floor_agg["ex_w4"]
            ),
            "monthly": monthly_comparison,
            "events": event_summary,
            "target_policy": TARGET_POLICY,
            "low_ratio_winners": winner_outcomes,
            "preserved_winners": sum(1 for item in winner_outcomes if item["preserved"]),
            "winners_still_profitable": sum(
                1 for item in winner_outcomes if item["still_profitable"]
            ),
            "winners_still_profitable_pnl": round(
                sum(
                    float(item["floor_pnl"])
                    for item in winner_outcomes
                    if item["still_profitable"]
                ),
                2,
            ),
            "low_ratio_winners_count": len(winner_outcomes),
            "new_floor_signals_vs_baseline": sorted(floor_ids - baseline_ids),
            "removed_floor_signals_vs_baseline": sorted(baseline_ids - floor_ids),
            "filter_new_signals_vs_baseline": sorted(filter_ids - baseline_ids),
            "floor_new_count": len(floor_ids - baseline_ids),
            "floor_removed_count": len(baseline_ids - floor_ids),
            "baseline_matches_official": base_report["verification"][
                "baseline_matches_official"
            ],
        },
        "verification": {
            "session_counts": session_counts,
            "sessions_total": sum(session_counts.values()),
            "last_session": last_session,
            "holdout_used": False,
            "target_policy": TARGET_POLICY,
            "floor_trades": len(floor_trades),
            "floor_all_widened_above_ratio": not floor_low,
            "floor_min_ratio": min(
                (
                    trade["stop_or_ratio"]
                    for trade in floor_trades
                    if trade["stop_or_ratio"] is not None
                ),
                default=None,
            ),
        },
        "events": events,
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
    print(
        f"Protocolo v1.2 - endpoint full - 362 sesiones - holdout no usado "
        f"- max_sl {MAX_SL} - target {TARGET_POLICY}"
    )
    print()
    print("BLOQUE  BASELINE ops/net/DD       RECHAZO ops/net/DD       FLOOR ops/net/DD")
    for window_id in WINDOW_IDS:
        for label, data in (
            ("baseline", baseline_agg),
            ("reject", filter_agg),
            ("floor", floor_agg),
        ):
            block = next(item for item in data["blocks"] if item["id"] == window_id)
            metrics = block["metrics"]
            print(
                f"{window_id:<6} {label:<9} {metrics['trades']:>3} "
                f"{fmt(metrics['net_profit']):>10} {fmt(metrics['max_drawdown']):>9}"
            )
    print()
    for label, data in (
        ("BASELINE", baseline_agg),
        ("RECHAZO", filter_agg),
        ("STOP FLOOR", floor_agg),
    ):
        print(label)
        for key in ("total", "ex_w4"):
            metrics = data[key]
            print(
                f"  {key:<6} ops {metrics['trades']:>3} | "
                f"neto {fmt(metrics['net_profit']):>10} | "
                f"PF {fmt(metrics['profit_factor']):>5} | "
                f"DD {fmt(metrics['max_drawdown']):>9} "
                f"({fmt(metrics['max_drawdown_pct'])}%) | "
                f"racha {metrics['worst_loss_streak']}"
            )
        conc = data["concentration"]
        print(
            f"  top5 {fmt(conc['top5_share_gross_profit_pct'])}% | "
            f"mejor mes {fmt(conc['best_month_share_net_pct'])}% | "
            f"W4 {fmt(conc['w4_share_net_pct'])}%"
        )
    print()
    print("Eventos del floor:", json.dumps(event_summary, ensure_ascii=True))
    print()
    print("Ganadores de bajo ratio:")
    for item in winner_outcomes:
        print(
            f"  {item['signal_id']} base {fmt(item['baseline_pnl'])} -> "
            f"floor {fmt(item['floor_pnl'])} ({item['floor_exit_reason']}, "
            f"target {fmt(item.get('floor_target_r_multiple'), 2)}R, "
            f"rentable={item['still_profitable']})"
        )
    print()
    print("Mensual:")
    for item in monthly_comparison:
        print(
            f"  {item['key']} base {fmt(item['baseline_pnl']):>9} | "
            f"rechazo {fmt(item['filter_pnl']):>9} | "
            f"floor {fmt(item['floor_pnl']):>9}"
        )
    print()
    print(f"Informe guardado en {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
