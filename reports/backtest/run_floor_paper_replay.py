"""Compara el floor stop/ORB >= 0.25 sobre el replay paper de 56 operaciones.

Fuente: reports/backtest/profile_filter_replay.json y preset_card_8766.db.
No re-simula señales ni toca la configuración activa. Usa las entradas, qty y
salidas originales del replay paper como punto de partida y solo recalcula el
recorrido de cada operación con el stop ampliado.

Reglas:
  - floor_original: stop 0.25*ORB y target original del replay.
  - floor_recalc:   stop 0.25*ORB y target 3R del stop ampliado.
  - El tope max_sl_ticks=200 se aplica solo a las señales que el floor amplía.
    Las 44 operaciones de alto ratio no se tocan: el replay paper ya las aceptó
    con sus stops originales, muchos >200 ticks.
  - Sin filtro por ratio: las 10 señales de bajo ratio que no superan el tope
    entran en la rama floor; las 2 que lo superan quedan fuera.
  - qty fijo del replay; no se recalcula por equity. Esto separa el efecto del
    stop/target del efecto de tamaño de posición.

Holdout no usado: el replay termina el 2026-06-30.
"""

from __future__ import annotations

import json
import math
import sqlite3
import statistics
import sys
from bisect import bisect_left
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "reports" / "backtest"
if str(REPORTS) not in sys.path:
    sys.path.insert(0, str(REPORTS))

from run_breakeven_1r_experiment import (  # noqa: E402
    COMMISSION_SIDE,
    POINT,
    SLIP,
    TICK,
    load_bars,
    pnl_for,
    round_tick,
    stop_price,
    target_price,
)

PAPER = REPORTS / "profile_filter_replay.json"
DB = REPORTS / "preset_card_8766.db"
OUT = REPORTS / "floor_paper_replay.json"
MD = REPORTS / "FLOOR_PAPER_REPLAY.md"
FILTER_RATIO = 0.25
MAX_SL = 200
INITIAL_CAPITAL = 25_000.0
ET = ZoneInfo("America/New_York")


def et(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, ET)


def load_trades() -> list[dict]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = []
    for row in con.execute("select * from trades order by entry_ts"):
        meta = json.loads(row["meta"])
        rows.append(
            {
                "signal_id": row["signal_id"],
                "direction": row["direction"],
                "qty": int(row["qty"]),
                "entry_ts": int(row["entry_ts"]),
                "entry_price": float(row["entry_price"]),
                "exit_ts": int(row["exit_ts"]),
                "exit_price": float(row["exit_price"]),
                "exit_reason": row["exit_reason"],
                "pnl": float(row["pnl"]),
                "r_multiple": float(row["r_multiple"]),
                "stop": float(row["stop"]),
                "target": float(row["target"]),
                "meta": meta,
            }
        )
    con.close()
    return rows


def simulate(
    trade: dict,
    stop: float,
    target: float,
    bars: dict[int, dict],
    stamps: list[int],
    session_last: dict[str, int],
) -> dict:
    entry = float(trade["entry_price"])
    direction = 1 if trade["direction"] == "long" else -1
    qty = int(trade["qty"])
    start = int(trade["entry_ts"])
    session_end = session_last[et(start).date().isoformat()]
    exit_ts = None
    exit_price = None
    exit_reason = None

    index = bisect_left(stamps, start)
    for ts in stamps[index:]:
        if ts > session_end:
            break
        bar = bars[ts]
        if direction == 1:
            hit_stop = bar["low"] <= stop
            hit_target = bar["high"] >= target
            gap_stop = bar["open"] < stop
            gap_target = bar["open"] > target
        else:
            hit_stop = bar["high"] >= stop
            hit_target = bar["low"] <= target
            gap_stop = bar["open"] > stop
            gap_target = bar["open"] < target

        if hit_stop:
            exit_price = stop_price(trade, stop, gap_stop, bar)
            exit_reason = "stop_loss"
            exit_ts = ts
            break
        if hit_target:
            exit_price = target_price(trade, target, gap_target, bar)
            exit_reason = "take_profit"
            exit_ts = ts
            break
        if ts >= session_end:
            exit_price = round_tick(bar["close"])
            exit_reason = "session_close"
            exit_ts = ts
            break

    if exit_price is None:
        bar = bars[session_end]
        exit_price = round_tick(bar["close"])
        exit_reason = "session_close"
        exit_ts = session_end

    pnl = pnl_for(trade, exit_price)
    risk_original = abs(entry - float(trade["stop"]))
    risk_floor = abs(entry - stop)
    move = (exit_price - entry) * direction
    return {
        "signal_id": trade["signal_id"],
        "direction": trade["direction"],
        "qty": qty,
        "entry_ts": start,
        "exit_ts": exit_ts,
        "exit_reason": exit_reason,
        "exit_price": round(exit_price, 2),
        "stop": round(stop, 2),
        "target": round(target, 2),
        "pnl": pnl,
        "r_original": round(move / risk_original, 4) if risk_original else 0.0,
        "r_floor": round(move / risk_floor, 4) if risk_floor else 0.0,
        "target_r_floor": round(abs(target - entry) / risk_floor, 3)
        if risk_floor
        else None,
        "original_pnl": trade["pnl"],
        "original_exit_reason": trade["exit_reason"],
    }


def max_drawdown(pnls: list[float]) -> tuple[float, float]:
    equity = INITIAL_CAPITAL
    peak = equity
    worst = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 2), round(worst / INITIAL_CAPITAL * 100, 3)


def summarize(rows: list[dict], r_key: str = "r_original") -> dict:
    ordered = sorted(rows, key=lambda item: item["exit_ts"])
    pnls = [float(item["pnl"]) for item in ordered]
    wins = [pnl for pnl in pnls if pnl > 0]
    losses = [pnl for pnl in pnls if pnl < 0]
    gp = sum(wins)
    gl = sum(losses)
    dd, dd_pct = max_drawdown(pnls)
    r_values = [float(item[r_key]) for item in ordered]
    r_gross_profit = sum(value for value in r_values if value > 0)
    r_gross_loss = sum(value for value in r_values if value < 0)
    streak = worst = 0
    for pnl in pnls:
        if pnl < 0:
            streak += 1
            worst = max(worst, streak)
        else:
            streak = 0
    return {
        "trades": len(pnls),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(len(wins) / len(pnls) * 100, 2) if pnls else 0.0,
        "gross_profit": round(gp, 2),
        "gross_loss": round(gl, 2),
        "net_profit": round(sum(pnls), 2),
        "profit_factor": round(gp / abs(gl), 2) if gl else None,
        "avg_r": round(statistics.fmean(item[r_key] for item in ordered), 2)
        if ordered
        else 0.0,
        "total_r": round(sum(item[r_key] for item in ordered), 2),
        "gross_profit_r": round(r_gross_profit, 2),
        "gross_loss_r": round(r_gross_loss, 2),
        "r_profit_factor": round(r_gross_profit / abs(r_gross_loss), 2)
        if r_gross_loss < 0
        else None,
        "max_drawdown": dd,
        "max_drawdown_pct": dd_pct,
        "worst_loss_streak": worst,
    }


def summarize_json(trades: list[dict]) -> dict:
    rows = [
        {
            "pnl": float(trade["pnl"]),
            "r_original": float(trade["r_multiple"]),
            "exit_ts": int(trade["exit_ts"]),
        }
        for trade in trades
    ]
    return summarize(rows)


def main() -> None:
    paper = json.loads(PAPER.read_text(encoding="utf-8"))
    baseline_trades = paper["arms"]["baseline"]["trades"]
    filter_trades = paper["arms"]["filter"]["trades"]
    baseline_by_id = {trade["signal_id"]: trade for trade in baseline_trades}
    filter_by_id = {trade["signal_id"]: trade for trade in filter_trades}

    db_trades = load_trades()
    db_by_id = {trade["signal_id"]: trade for trade in db_trades}
    if set(db_by_id) != set(baseline_by_id):
        raise RuntimeError("El replay paper y preset_card_8766.db no tienen los mismos IDs")
    last_exit = max(et(trade["exit_ts"]).date() for trade in db_trades)
    if last_exit >= date(2026, 7, 1):
        raise RuntimeError(f"El replay toca el holdout: última salida {last_exit}")

    bars, stamps, session_last = load_bars()

    prepared = []
    for trade in db_trades:
        meta = trade["meta"]
        width_ticks = (float(meta["orb_high"]) - float(meta["orb_low"])) / TICK
        original_ticks = abs(trade["entry_price"] - trade["stop"]) / TICK
        ratio = original_ticks / width_ticks if width_ticks else None
        floor_needed = ratio is not None and ratio < FILTER_RATIO - 1e-9
        floor_ticks = (
            max(original_ticks, FILTER_RATIO * width_ticks)
            if floor_needed
            else original_ticks
        )
        cap_hit = bool(floor_needed and floor_ticks > MAX_SL + 1e-9)
        direction = 1 if trade["direction"] == "long" else -1
        floor_stop = (
            round_tick(trade["entry_price"] - direction * floor_ticks * TICK)
            if floor_needed
            else trade["stop"]
        )
        recalc_target = (
            round_tick(trade["entry_price"] + direction * 3.0 * floor_ticks * TICK)
            if floor_needed
            else trade["target"]
        )
        prepared.append(
            {
                **trade,
                "ratio": round(ratio, 6) if ratio is not None else None,
                "original_ticks": round(original_ticks, 3),
                "floor_ticks": round(floor_ticks, 3),
                "floor_needed": floor_needed,
                "cap_hit": cap_hit,
                "floor_stop": floor_stop,
                "original_target": trade["target"],
                "recalc_target": recalc_target,
            }
        )

    control = [
        simulate(trade, trade["stop"], trade["target"], bars, stamps, session_last)
        for trade in prepared
    ]
    floor_original = [
        simulate(trade, trade["floor_stop"], trade["original_target"], bars, stamps, session_last)
        for trade in prepared
        if not trade["cap_hit"]
    ]
    floor_recalc = [
        simulate(trade, trade["floor_stop"], trade["recalc_target"], bars, stamps, session_last)
        for trade in prepared
        if not trade["cap_hit"]
    ]

    control_by_id = {trade["signal_id"]: trade for trade in control}
    orig_by_id = {trade["signal_id"]: trade for trade in floor_original}
    recalc_by_id = {trade["signal_id"]: trade for trade in floor_recalc}

    validation = []
    for trade in baseline_trades:
        sim = control_by_id[trade["signal_id"]]
        validation.append(
            {
                "signal_id": trade["signal_id"],
                "paper_pnl": trade["pnl"],
                "sim_pnl": sim["pnl"],
                "delta": round(sim["pnl"] - float(trade["pnl"]), 2),
                "paper_exit": trade["exit_reason"],
                "sim_exit": sim["exit_reason"],
            }
        )
    mismatches = [item for item in validation if abs(item["delta"]) > 0.01]

    removed_ids = paper["comparison"]["removed_signal_ids"]
    capped_ids = [trade["signal_id"] for trade in prepared if trade["cap_hit"]]
    eligible_low_ids = [
        trade["signal_id"]
        for trade in prepared
        if trade["floor_needed"] and not trade["cap_hit"]
    ]
    if set(capped_ids) - set(removed_ids):
        raise RuntimeError("Hay una señal cap fuera de las 12 eliminadas")
    if set(eligible_low_ids) - set(removed_ids):
        raise RuntimeError("Hay una señal floor fuera de las 12 eliminadas")

    def removed_row(signal_id: str) -> dict:
        base = baseline_by_id[signal_id]
        item = {
            "signal_id": signal_id,
            "ratio": db_by_id[signal_id]["meta"]["stop_ticks"]
            / ((db_by_id[signal_id]["meta"]["orb_high"] - db_by_id[signal_id]["meta"]["orb_low"]) / TICK),
            "baseline_pnl": float(base["pnl"]),
            "baseline_exit": base["exit_reason"],
            "capped": signal_id in capped_ids,
            "floor_original_pnl": None,
            "floor_original_exit": None,
            "floor_recalc_pnl": None,
            "floor_recalc_exit": None,
        }
        if signal_id in orig_by_id:
            item["floor_original_pnl"] = orig_by_id[signal_id]["pnl"]
            item["floor_original_exit"] = orig_by_id[signal_id]["exit_reason"]
            item["floor_recalc_pnl"] = recalc_by_id[signal_id]["pnl"]
            item["floor_recalc_exit"] = recalc_by_id[signal_id]["exit_reason"]
        return item

    removed = [removed_row(signal_id) for signal_id in removed_ids]
    removed_baseline_winners = [item for item in removed if item["baseline_pnl"] > 0]
    removed_original_winners = [
        item for item in removed if (item["floor_original_pnl"] or 0.0) > 0
    ]
    removed_recalc_winners = [
        item for item in removed if (item["floor_recalc_pnl"] or 0.0) > 0
    ]
    recovered_original = [
        item
        for item in removed
        if item["floor_original_pnl"] is not None and item["baseline_pnl"] <= 0 and item["floor_original_pnl"] > 0
    ]
    recovered_recalc = [
        item
        for item in removed
        if item["floor_recalc_pnl"] is not None and item["baseline_pnl"] <= 0 and item["floor_recalc_pnl"] > 0
    ]
    lost_original = [
        item
        for item in removed
        if item["floor_original_pnl"] is not None and item["baseline_pnl"] > 0 and item["floor_original_pnl"] <= 0
    ]
    lost_recalc = [
        item
        for item in removed
        if item["floor_recalc_pnl"] is not None and item["baseline_pnl"] > 0 and item["floor_recalc_pnl"] <= 0
    ]

    filter_static_rows = [
        {
            "pnl": float(db_by_id[signal_id]["pnl"]),
            "r_original": float(db_by_id[signal_id]["r_multiple"]),
            "exit_ts": int(db_by_id[signal_id]["exit_ts"]),
        }
        for signal_id in sorted(filter_by_id)
    ]
    filter_static_metrics = summarize(filter_static_rows)
    baseline_static_54_rows = [
        {
            "pnl": float(db_by_id[trade["signal_id"]]["pnl"]),
            "r_original": float(db_by_id[trade["signal_id"]]["r_multiple"]),
            "exit_ts": int(db_by_id[trade["signal_id"]]["exit_ts"]),
        }
        for trade in prepared
        if not trade["cap_hit"]
    ]
    baseline_static_54_metrics = summarize(baseline_static_54_rows)

    kept_validation = []
    for signal_id in sorted(filter_by_id):
        base = db_by_id[signal_id]
        sim = orig_by_id[signal_id]
        kept_validation.append(
            {
                "signal_id": signal_id,
                "paper_pnl": base["pnl"],
                "sim_pnl": sim["pnl"],
                "delta": round(sim["pnl"] - float(base["pnl"]), 2),
            }
        )
    kept_mismatches = [item for item in kept_validation if abs(item["delta"]) > 0.01]

    low_baseline_pnl = round(
        sum(float(baseline_by_id[signal_id]["pnl"]) for signal_id in removed_ids), 2
    )
    capped_baseline_pnl = round(
        sum(float(baseline_by_id[signal_id]["pnl"]) for signal_id in capped_ids), 2
    )
    eligible_baseline_pnl = round(low_baseline_pnl - capped_baseline_pnl, 2)
    floor_original_low_pnl = round(
        sum(orig_by_id[signal_id]["pnl"] for signal_id in eligible_low_ids), 2
    )
    floor_recalc_low_pnl = round(
        sum(recalc_by_id[signal_id]["pnl"] for signal_id in eligible_low_ids), 2
    )
    low_baseline_r = round(
        sum(float(db_by_id[signal_id]["r_multiple"]) for signal_id in eligible_low_ids), 3
    )
    low_floor_original_r = round(
        sum(orig_by_id[signal_id]["r_original"] for signal_id in eligible_low_ids), 3
    )
    low_floor_recalc_r = round(
        sum(recalc_by_id[signal_id]["r_original"] for signal_id in eligible_low_ids), 3
    )

    filter_metrics = summarize_json(filter_trades)
    baseline_metrics = summarize_json(baseline_trades)
    floor_original_metrics = summarize(floor_original)
    floor_recalc_metrics = summarize(floor_recalc)
    floor_original_r_floor = summarize(floor_original, r_key="r_floor")
    floor_recalc_r_floor = summarize(floor_recalc, r_key="r_floor")

    # Si se conservaran las 2 señales cap con su resultado baseline, para
    # separar el efecto de excluirlas del efecto del stop/target.
    capped_rows = [
        {
            "pnl": float(baseline_by_id[signal_id]["pnl"]),
            "r_original": float(baseline_by_id[signal_id]["r_multiple"]),
            "exit_ts": int(baseline_by_id[signal_id]["exit_ts"]),
        }
        for signal_id in capped_ids
    ]
    floor_original_plus_capped = floor_original + capped_rows
    floor_recalc_plus_capped = floor_recalc + capped_rows

    output = {
        "schema": "floor-paper-replay-v1",
        "scope": "Replay paper de 56 operaciones, 2025-01-10 a 2026-06-30; holdout no usado",
        "selection": {
            "start": min(et(trade["entry_ts"]).date() for trade in db_trades).isoformat(),
            "last_exit": last_exit.isoformat(),
            "holdout_start": "2026-07-01",
            "holdout_used": False,
        },
        "source": {
            "paper": str(PAPER.relative_to(ROOT)),
            "paper_sha256": __import__("hashlib").sha256(PAPER.read_bytes()).hexdigest(),
            "db": str(DB.relative_to(ROOT)),
            "db_sha256": __import__("hashlib").sha256(DB.read_bytes()).hexdigest(),
        },
        "rules": {
            "filter_ratio": FILTER_RATIO,
            "max_sl_ticks": MAX_SL,
            "max_sl_applies_to": "solo señales ampliadas por el floor",
            "target_original": "target del replay paper, calculado con el stop original",
            "target_recalc": "3R del stop ampliado",
            "qty": "fijo del replay; no se recalcula por equity",
        },
        "validation": {
            "ids_match": True,
            "control_sim_mismatches": len(mismatches),
            "control_sim_mismatch_detail": mismatches,
            "control_sim_net": summarize(control)["net_profit"],
            "paper_baseline_net": baseline_metrics["net_profit"],
            "filter_official_net": filter_metrics["net_profit"],
            "filter_static_qty_net": filter_static_metrics["net_profit"],
            "kept_44_changed": len(kept_mismatches),
            "kept_44_mismatch_detail": kept_mismatches,
        },
        "arms": {
            "baseline_paper_56": baseline_metrics,
            "filter_paper_44": filter_metrics,
            "filter_static_qty_44": filter_static_metrics,
            "baseline_static_qty_54": baseline_static_54_metrics,
            "floor_original_54": floor_original_metrics,
            "floor_recalc_54": floor_recalc_metrics,
            "floor_original_plus_capped_56": summarize(floor_original_plus_capped),
            "floor_recalc_plus_capped_56": summarize(floor_recalc_plus_capped),
        },
        "r_metrics": {
            "baseline_paper_56": {
                "total_r": baseline_metrics["total_r"],
                "avg_r": baseline_metrics["avg_r"],
                "r_profit_factor": baseline_metrics["r_profit_factor"],
            },
            "filter_paper_44": {
                "total_r": filter_metrics["total_r"],
                "avg_r": filter_metrics["avg_r"],
                "r_profit_factor": filter_metrics["r_profit_factor"],
            },
            "filter_static_qty_44": {
                "total_r": filter_static_metrics["total_r"],
                "avg_r": filter_static_metrics["avg_r"],
                "r_profit_factor": filter_static_metrics["r_profit_factor"],
            },
            "floor_original_54": {
                "r_original_total": floor_original_metrics["total_r"],
                "r_original_mean": floor_original_metrics["avg_r"],
                "r_original_profit_factor": floor_original_metrics["r_profit_factor"],
                "r_floor_total": floor_original_r_floor["total_r"],
                "r_floor_mean": floor_original_r_floor["avg_r"],
                "r_floor_profit_factor": floor_original_r_floor["r_profit_factor"],
            },
            "floor_recalc_54": {
                "r_original_total": floor_recalc_metrics["total_r"],
                "r_original_mean": floor_recalc_metrics["avg_r"],
                "r_original_profit_factor": floor_recalc_metrics["r_profit_factor"],
                "r_floor_total": floor_recalc_r_floor["total_r"],
                "r_floor_mean": floor_recalc_r_floor["avg_r"],
                "r_floor_profit_factor": floor_recalc_r_floor["r_profit_factor"],
            },
            "low_ratio_10": {
                "baseline_total_r": low_baseline_r,
                "floor_original_total_r": low_floor_original_r,
                "floor_recalc_total_r": low_floor_recalc_r,
            },
        },
        "counts": {
            "baseline_56": len(baseline_trades),
            "filter_44": len(filter_trades),
            "removed_12": len(removed_ids),
            "removed_baseline_winners": len(removed_baseline_winners),
            "removed_floor_original_winners": len(removed_original_winners),
            "removed_floor_recalc_winners": len(removed_recalc_winners),
            "capped_2": len(capped_ids),
            "capped_ids": capped_ids,
            "eligible_low_10": len(eligible_low_ids),
            "eligible_low_ids": eligible_low_ids,
            "floor_original_54": len(floor_original),
            "floor_recalc_54": len(floor_recalc),
        },
        "decomposition": {
            "filter_official_44_net": filter_metrics["net_profit"],
            "filter_static_qty_44_net": filter_static_metrics["net_profit"],
            "removed_12_baseline_net": low_baseline_pnl,
            "capped_2_baseline_net": capped_baseline_pnl,
            "eligible_low_10_baseline_net": eligible_baseline_pnl,
            "eligible_low_10_floor_original_net": floor_original_low_pnl,
            "eligible_low_10_floor_recalc_net": floor_recalc_low_pnl,
            "baseline_static_qty_54_net": baseline_static_54_metrics["net_profit"],
            "floor_original_minus_filter_official": round(
                floor_original_metrics["net_profit"] - filter_metrics["net_profit"], 2
            ),
            "floor_recalc_minus_filter_official": round(
                floor_recalc_metrics["net_profit"] - filter_metrics["net_profit"], 2
            ),
            "floor_original_minus_filter_static": round(
                floor_original_metrics["net_profit"] - filter_static_metrics["net_profit"], 2
            ),
            "floor_recalc_minus_filter_static": round(
                floor_recalc_metrics["net_profit"] - filter_static_metrics["net_profit"], 2
            ),
            "floor_original_minus_baseline_54": round(
                floor_original_metrics["net_profit"] - baseline_static_54_metrics["net_profit"], 2
            ),
            "floor_recalc_minus_baseline_54": round(
                floor_recalc_metrics["net_profit"] - baseline_static_54_metrics["net_profit"], 2
            ),
            "floor_original_minus_baseline_56": round(
                floor_original_metrics["net_profit"] - baseline_metrics["net_profit"], 2
            ),
            "floor_recalc_minus_baseline_56": round(
                floor_recalc_metrics["net_profit"] - baseline_metrics["net_profit"], 2
            ),
        },
        "removed": removed,
        "recovered_original": recovered_original,
        "recovered_recalc": recovered_recalc,
        "lost_original": lost_original,
        "lost_recalc": lost_recalc,
        "kept_validation": kept_validation,
        "trades": {
            "floor_original_54": floor_original,
            "floor_recalc_54": floor_recalc,
        },
    }
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")

    def money(value: float | None) -> str:
        return "—" if value is None else f"{value:+,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    lines = [
        "# Floor sobre el replay paper de 56 operaciones",
        "",
        "**Alcance:** 2025-01-10 a 2026-06-30, 56 operaciones paper. Holdout no usado.  ",
        "**Naturaleza:** comparación descriptiva in-sample; no es validación forward.  ",
        "**Fuente:** `reports/backtest/profile_filter_replay.json` + `preset_card_8766.db`  ",
        "**Resultado estructurado:** `reports/backtest/floor_paper_replay.json`",
        "",
        "## 1. Reglas",
        "",
        "El replay paper tiene 56 operaciones; el rechazo `stop/ORB >= 0,25` deja 44 y elimina 12. El floor amplía el stop a `0,25 × ORB` sin rechazar por ratio. Se comparan las dos políticas de target ya usadas en W1–W6:",
        "",
        "| Política | Stop | Target |",
        "|---|---|---|",
        "| `floor_original` | `0,25 × ORB` | target original del replay |",
        "| `floor_recalc` | `0,25 × ORB` | `3R` del stop ampliado |",
        "",
        "El tope `max_sl_ticks=200` se aplica **solo a las 12 señales de bajo ratio que el floor amplía**. Las 44 de alto ratio se dejan intactas: el replay paper ya las aceptó con sus stops originales, muchos >200 ticks. Imponer 200 a todas habría eliminado 29 operaciones de alto ratio y habría convertido esto en otro experimento.",
        "",
        f"De las 12 eliminadas, **{len(capped_ids)}** superan el tope al ampliarse ({', '.join(f'`{x}`' for x in capped_ids)}); quedan **{len(eligible_low_ids)}** señales de bajo ratio para el floor. La qty es la del replay y no se recalcula por equity.",
        "",
        "## 2. Resultado agregado",
        "",
        "| Brazo | Ops | Neto USD | PF | R medio (riesgo original) | DD USD | DD % | Peor racha |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key, label in (
        ("baseline_paper_56", "Baseline paper"),
        ("filter_paper_44", "Rechazo ratio oficial (44)"),
        ("filter_static_qty_44", "Rechazo ratio, misma qty (44)"),
        ("floor_original_54", "Floor + target original"),
        ("floor_recalc_54", "Floor + target 3R"),
    ):
        metrics = output["arms"][key]
        lines.append(
            f"| {label} | {metrics['trades']} | {money(metrics['net_profit'])} | "
            f"{metrics['profit_factor']} | {metrics['avg_r']:.2f} | "
            f"{money(metrics['max_drawdown']).lstrip('+')} | {metrics['max_drawdown_pct']:.2f}% | "
            f"{metrics['worst_loss_streak']} |"
        )
    lines += [
        "",
        f"El rechazo oficial deja **{money(filter_metrics['net_profit'])}** con 44 operaciones; con la misma qty del replay, **{money(filter_static_metrics['net_profit'])}**. La diferencia de {money(filter_static_metrics['net_profit'] - filter_metrics['net_profit'])} viene de una sola operación (`2025-09-19`), que el rechazo ejecuta con qty 3 y el baseline con qty 2. El floor original deja **{money(floor_original_metrics['net_profit'])}** y el floor 3R **{money(floor_recalc_metrics['net_profit'])}**. ",
        f"Frente al rechazo oficial, el floor original queda **{money(output['decomposition']['floor_original_minus_filter_official'])}** y el 3R **{money(output['decomposition']['floor_recalc_minus_filter_official'])}**. Frente al rechazo con la misma qty, quedan **{money(output['decomposition']['floor_original_minus_filter_static'])}** y **{money(output['decomposition']['floor_recalc_minus_filter_static'])}**.",
        "",
        "El DD no debe leerse como una mejora del floor: el rechazo oficial usa otra qty. Con la misma qty, el rechazo también marca 2.128,28. El PF sí es comparable y favorece al rechazo: 1,96 oficial / 2,00 misma qty frente a 1,62 del floor 3R. El floor 3R genera más beneficio bruto, pero también más pérdida bruta; su neto casi empata, su perfil es de mayor varianza.",
        "",
        "## 2b. La lectura en R",
        "",
        "El P&L en USD usa la qty fija del replay. Al ampliar el stop, una pérdida cuesta más dólares aunque el R —normalizado por el riesgo original— no empeore. Por eso conviene mirar las dos métricas:",
        "",
        "| Cohorte | Baseline R | Floor original R | Floor 3R R |",
        "|---|---:|---:|---:|",
        f"| 54 ops (riesgo original) | {baseline_static_54_metrics['total_r']:.2f} | {floor_original_metrics['total_r']:.2f} | {floor_recalc_metrics['total_r']:.2f} |",
        f"| 10 de bajo ratio | {low_baseline_r:.2f} | {low_floor_original_r:.2f} | {low_floor_recalc_r:.2f} |",
        "",
        f"El rechazo suma {filter_static_metrics['total_r']:.2f}R. El floor 3R suma {floor_recalc_metrics['total_r']:.2f}R, por encima del rechazo, y el floor original {floor_original_metrics['total_r']:.2f}R, por debajo. Pero el R-PF sigue favoreciendo al rechazo: {filter_static_metrics['r_profit_factor']:.2f} vs {floor_recalc_metrics['r_profit_factor']:.2f} del 3R y {floor_original_metrics['r_profit_factor']:.2f} del original. En USD, en cambio, el 3R queda 65,82 por debajo del rechazo oficial y 159,06 por debajo con la misma qty. La divergencia es el efecto de la qty fija: el 3R gana más R en las 10 de bajo ratio (+0,75R) pero pierde 159,06 USD por el mayor tamaño en dólares de los stops ampliados. El floor original pierde frente al rechazo en ambas lecturas; el 3R gana en R total pero no en calidad del R.",
        "",
        "## 3. Las 12 eliminadas y los ganadores",
        "",
        f"En el baseline paper hay **{len(removed_baseline_winners)} ganadores** entre las 12 eliminadas: `2025-03-21` (+501,30) y `2026-05-22` (+318,80). El dato de **tres ganadores** corresponde al floor original, no al rechazo: al ampliar el stop se suma `2025-01-15`, que pasa de -168,70 a +516,30. El target 3R conserva dos ganadores en el grupo (`2025-01-15` y `2025-03-21`) pero pierde `2026-05-22`.",
        "",
        "| Señal | Ratio | Baseline | Floor original | Floor 3R |",
        "|---|---:|---:|---:|---:|",
    ]
    for item in removed:
        original_cell = "cap" if item["capped"] else money(item["floor_original_pnl"])
        recalc_cell = "cap" if item["capped"] else money(item["floor_recalc_pnl"])
        lines.append(
            f"| `{item['signal_id']}` | {item['ratio']:.3f} | {money(item['baseline_pnl'])} | "
            f"{original_cell} | {recalc_cell} |"
        )
    lines += [
        "",
        f"**Recuperadas por el floor original:** {len(recovered_original)}. "
        f"**Ganadores perdidos:** {len(lost_original)}. "
        f"**Recuperadas por el 3R:** {len(recovered_recalc)}; **ganadores perdidos:** {len(lost_recalc)}.",
        "",
        "## 4. Descomposición",
        "",
        "| Componente | Neto USD | Lectura |",
        "|---|---:|---|",
        f"| Rechazo oficial 44 | {money(filter_metrics['net_profit'])} | Las 44 de alto ratio, sin tocar |",
        f"| Rechazo misma qty 44 | {money(filter_static_metrics['net_profit'])} | Control con la qty del replay |",
        f"| Baseline 54 misma qty | {money(baseline_static_54_metrics['net_profit'])} | 56 menos las 2 cap |",
        f"| 12 eliminadas, baseline | {money(low_baseline_pnl)} | 2 ganadoras y 10 perdedoras |",
        f"| 2 eliminadas por cap | {money(capped_baseline_pnl)} | Se quedan fuera del floor |",
        f"| 10 de bajo ratio, baseline | {money(eligible_baseline_pnl)} | Mismo subconjunto que el floor |",
        f"| 10 de bajo ratio, floor original | {money(floor_original_low_pnl)} | {money(floor_original_low_pnl - eligible_baseline_pnl)} vs baseline |",
        f"| 10 de bajo ratio, floor 3R | {money(floor_recalc_low_pnl)} | {money(floor_recalc_low_pnl - eligible_baseline_pnl)} vs baseline |",
        "",
        f"El floor original mejora al baseline de las 54 en **{money(output['decomposition']['floor_original_minus_baseline_54'])}** y el 3R en **{money(output['decomposition']['floor_recalc_minus_baseline_54'])}**. Frente al rechazo con la misma qty, el original queda **{money(output['decomposition']['floor_original_minus_filter_static'])}** y el 3R **{money(output['decomposition']['floor_recalc_minus_filter_static'])}**; frente al oficial, **{money(output['decomposition']['floor_original_minus_filter_official'])}** y **{money(output['decomposition']['floor_recalc_minus_filter_official'])}**. Con la misma qty, la diferencia con el rechazo es exactamente el resultado de las 10 señales de bajo ratio que el floor añade.",
        "",
        f"Si se conservan las 2 cap con su resultado baseline, el floor original de 56 queda en **{money(summarize(floor_original_plus_capped)['net_profit'])}** ({money(summarize(floor_original_plus_capped)['net_profit'] - baseline_metrics['net_profit'])} vs baseline 56) y el 3R en **{money(summarize(floor_recalc_plus_capped)['net_profit'])}** ({money(summarize(floor_recalc_plus_capped)['net_profit'] - baseline_metrics['net_profit'])}). Excluir las 2 cap aporta **{money(abs(capped_baseline_pnl))}**, una parte relevante de la mejora aparente.",
        "",
        "## 5. ¿Cambia respecto a W1–W6?",
        "",
        "| Dato | W1–W6 | Replay paper |",
        "|---|---:|---:|",
        "| Ops baseline / rechazo | 38 / 14 | 56 / 44 |",
        "| Rechazo: neto / PF / DD | +3.026,88 / 3,57 / 839,90 | +4.450,38 / 1,96 / 2.220,02 |",
        "| Ops floor / cap | 34 / 4 | 54 / 2 |",
        "| Floor original: neto / PF / DD | +1.363,20 / 1,34 / 1.440,00 | " + f"{money(floor_original_metrics['net_profit'])} / {floor_original_metrics['profit_factor']} / {money(floor_original_metrics['max_drawdown']).lstrip('+')}" + " |",
        "| Floor 3R: neto / PF / DD | +1.724,96 / 1,39 / 1.534,04 | " + f"{money(floor_recalc_metrics['net_profit'])} / {floor_recalc_metrics['profit_factor']} / {money(floor_recalc_metrics['max_drawdown']).lstrip('+')}" + " |",
        "| Gap rechazo − floor 3R | +1.301,92 USD | +65,82 oficial / +159,06 misma qty |",
        "| R rechazo vs floor 3R | 14,53 vs 5,79 | 24,04 vs 24,77 |",
        "",
        "El resultado **sí cambia**: en W1–W6 el rechazo superaba al floor 3R por 1.301,92 USD y por 8,74R; en el paper la ventaja en USD se reduce a 65,82 (o 159,06 con la misma qty), y en R el floor 3R supera al rechazo (24,77 vs 24,04). La razón principal es que el paper solo añade 10 operaciones de bajo ratio, 2 quedan fuera por el tope, la qty es fija y `2025-01-15` se recupera con fuerza. La muestra es pequeña y el replay ya contiene las 44 de alto ratio; no es una validación forward.",
        "",
        "## 6. Conclusión",
        "",
        f"- El floor original conserva **los 2 ganadores originales de las eliminadas** y recupera **1 perdedora** (`2025-01-15`); el grupo pasa a 3 ganadores. El 3R conserva **{len([x for x in removed if x['floor_recalc_pnl'] is not None and x['baseline_pnl'] > 0 and x['floor_recalc_pnl'] > 0])}** de los 2 originales y pierde **{len(lost_recalc)}** (`2026-05-22`).",
        f"- En USD, el floor original queda **{money(output['decomposition']['floor_original_minus_filter_official'])}** por debajo del rechazo oficial; el 3R queda **{money(output['decomposition']['floor_recalc_minus_filter_official'])}** (o **{money(output['decomposition']['floor_recalc_minus_filter_static'])}** con la misma qty). En R, el 3R **supera** al rechazo (24,77 vs 24,04); el original queda por debajo (23,72).",
        "- Por tanto, el resultado **sí cambia respecto a W1–W6**: el rechazo deja de ser claramente superior en neto y en R total. Sigue ganando en USD por un margen estrecho y conserva mejor PF (1,96/2,00 vs 1,62) y mejor R-PF (2,09 vs 1,70), pero pierde en R total frente al target 3R (24,04 vs 24,77); su DD oficial no es comparable por la qty. El floor original sigue por debajo en ambas lecturas.",
        "- La causa hay que buscarla en la composición: solo 10 operaciones de bajo ratio, 2 cap, qty fija y una muestra paper pequeña. No es una validación forward ni autoriza promoción.",
        "- El holdout sigue sin usarse.",
        "",
        "## 7. Verificación",
        "",
        f"- IDs del replay y DB: coinciden (56).",
        f"- Simulación de control contra el baseline paper: {len(mismatches)} discrepancia > 0,01 USD; neto control {money(output['validation']['control_sim_net'])} vs paper {money(output['validation']['paper_baseline_net'])}. La única diferencia es `2025-11-28` (+1,50 USD por redondeo de sesión).",
        f"- Las 44 de alto ratio no cambian con el floor: {len(kept_mismatches)} discrepancias > 0,01 USD.",
        f"- Rechazo oficial 44: {money(filter_metrics['net_profit'])}; misma qty: {money(filter_static_metrics['net_profit'])}; diferencia {money(filter_static_metrics['net_profit'] - filter_metrics['net_profit'])} por `2025-09-19`.",
        f"- 12 eliminadas = 2 cap + 10 floor; 56 - 2 = 54 operaciones floor; 44 + 10 = 54.",
        "",
        f"JSON: `{OUT.relative_to(ROOT)}`  ",
        f"Markdown: `{MD.relative_to(ROOT)}`",
    ]
    MD.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "baseline": baseline_metrics,
        "filter": filter_metrics,
        "floor_original": floor_original_metrics,
        "floor_recalc": floor_recalc_metrics,
        "counts": output["counts"],
        "decomposition": output["decomposition"],
        "validation": output["validation"],
    }, ensure_ascii=False, indent=2))
    print(f"Escrito {OUT}")
    print(f"Escrito {MD}")


if __name__ == "__main__":
    main()
