"""Experimento aislado: break-even y trailing a +1R sobre el replay filtrado.

Fuente: reports/backtest/preset_card_8766.db (56 operaciones paper).
Filtro: stop/ORB >= 0.25 (44 operaciones).
No toca el motor ni la configuración de producción.

Políticas, aplicadas desde la vela siguiente a la primera que alcanza +1R:
  - be_1r:    stop a la entrada (break-even).
  - lock_1r:  stop a +1R (bloquea 1R).
  - trail_1r: stop a 1R por debajo del máximo favorable (trailing 1R).

Supuestos:
  - Entradas fijas: no se re-simulan señales nuevas por salir antes.
  - El stop se mueve después de cerrar la vela que alcanza +1R; no se asume
    un camino intrabar favorable dentro de esa misma vela.
  - Si en una vela se tocan stop y target, se aplica stop primero (igual que
    ExecutionEngine).
  - Slippage adverso de 1 tick en stops/targets; comisión 0.62 USD por lado.
"""

from __future__ import annotations

import csv
import json
import math
import sqlite3
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reports" / "backtest" / "preset_card_8766.db"
OFFICIAL = ROOT / "reports" / "backtest" / "min_stop_or_ratio_protocol.json"
CSV = ROOT / "data" / "real" / "bars_mnq_nq_es_1m.csv"
OUT = ROOT / "reports" / "backtest" / "breakeven_1r_experiment.json"

ET = ZoneInfo("America/New_York")
TICK = 0.25
POINT = 2.0
SLIP = 0.25
COMMISSION_SIDE = 0.62
INITIAL_CAPITAL = 25_000.0
FILTER_RATIO = 0.25
POLICIES = ("original", "be_1r", "lock_1r", "trail_1r")


def et(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, ET)


def round_tick(x: float) -> float:
    return math.floor(x / TICK + 0.5) * TICK


def load_bars() -> tuple[dict[int, dict], list[int], dict[str, int]]:
    bars: dict[int, dict] = {}
    with CSV.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["symbol"] != "MNQ":
                continue
            ts = int(datetime.fromisoformat(row["timestamp"]).timestamp())
            bars[ts] = {
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
            }
    stamps = sorted(bars)
    by_day: dict[str, list[int]] = defaultdict(list)
    for ts in stamps:
        by_day[et(ts).date().isoformat()].append(ts)
    # Cierre de sesión: primera vela a las 15:55 ET o posterior; en sesiones
    # acortadas, la última vela disponible.
    session_last: dict[str, int] = {}
    for day, day_stamps in by_day.items():
        closes = [ts for ts in day_stamps if et(ts).strftime("%H:%M") >= "15:55"]
        session_last[day] = closes[0] if closes else day_stamps[-1]
    return bars, stamps, session_last


def load_trades(con: sqlite3.Connection) -> list[sqlite3.Row]:
    out = []
    for r in con.execute("select * from trades order by entry_ts"):
        meta = json.loads(r["meta"])
        width = (meta["orb_high"] - meta["orb_low"]) / TICK
        ratio = meta["stop_ticks"] / width if width else 0.0
        if ratio >= FILTER_RATIO:
            out.append(r)
    return out


def load_official_filter() -> list[dict]:
    """14 operaciones del protocolo oficial con min_stop_or_ratio=0.25."""
    data = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    out = []
    for t in data["filter"]["trades"]:
        direction = 1 if t["direction"] == "long" else -1
        stop = round_tick(t["entry_price"] - direction * t["stop_ticks"] * TICK)
        target = round_tick(t["entry_price"] + direction * 3.0 * t["stop_ticks"] * TICK)
        out.append(
            {
                **t,
                "stop": stop,
                "target": target,
                "mfe_r": 0.0,
            }
        )
    return out


def pnl_for_qty(trade, exit_price: float, qty: int) -> float:
    direction = 1 if trade["direction"] == "long" else -1
    gross = (exit_price - trade["entry_price"]) * direction * POINT * qty
    return round(gross - COMMISSION_SIDE * 2 * qty, 2)


def pnl_for(trade: sqlite3.Row, exit_price: float) -> float:
    return pnl_for_qty(trade, exit_price, int(trade["qty"]))


def r_for(trade: sqlite3.Row, exit_price: float) -> float:
    direction = 1 if trade["direction"] == "long" else -1
    risk = abs(trade["entry_price"] - trade["stop"])
    return round((exit_price - trade["entry_price"]) * direction / risk, 2) if risk else 0.0


def stop_price(trade: sqlite3.Row, base: float, gap: bool, bar: dict) -> float:
    direction = 1 if trade["direction"] == "long" else -1
    raw = bar["open"] if gap else base
    return round_tick(raw - direction * SLIP)


def target_price(trade: sqlite3.Row, base: float, gap: bool, bar: dict) -> float:
    direction = 1 if trade["direction"] == "long" else -1
    if gap:
        return round_tick(bar["open"])
    return round_tick(base - direction * SLIP)


def simulate(
    trade: sqlite3.Row,
    bars: dict[int, dict],
    stamps: list[int],
    session_last: dict[str, int],
    policy: str,
) -> dict:
    entry = float(trade["entry_price"])
    initial_stop = float(trade["stop"])
    target = float(trade["target"])
    direction = 1 if trade["direction"] == "long" else -1
    risk = abs(entry - initial_stop)
    qty = int(trade["qty"])
    start = int(trade["entry_ts"])
    session_end = session_last[et(start).date().isoformat()]
    stop = initial_stop
    mfe = 0.0
    moved = False
    exit_ts = None
    exit_price = None
    exit_reason = None

    for ts in stamps:
        if ts < start:
            continue
        if ts > session_end:
            break
        bar = bars[ts]
        # Gestión con el stop vigente al abrir la vela.
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

        if hit_stop and hit_target:
            exit_price = stop_price(trade, stop, gap_stop, bar)
            exit_reason = "stop_loss"
            exit_ts = ts
            break
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

        # Cierre de sesión: primera vela a las 15:55 ET o última de la sesión.
        if ts >= session_end:
            exit_price = round_tick(bar["close"])
            exit_reason = "session_close"
            exit_ts = ts
            break

        # Actualización de excursión favorable para la siguiente vela.
        favorable = (bar["high"] - entry) if direction == 1 else (entry - bar["low"])
        mfe = max(mfe, favorable / risk if risk else 0.0)
        if policy != "original" and mfe >= 1.0:
            if policy == "be_1r":
                if not moved:
                    moved = True
                    new_stop = entry
                else:
                    continue
            elif policy == "lock_1r":
                if not moved:
                    moved = True
                    new_stop = entry + direction * risk
                else:
                    continue
            elif policy == "trail_1r":
                moved = True
                new_stop = entry + direction * (mfe - 1.0) * risk
            else:
                raise ValueError(policy)
            if direction == 1:
                stop = max(stop, new_stop)
            else:
                stop = min(stop, new_stop)

    if exit_price is None:
        # Fallback: última vela disponible de la sesión.
        bar = bars[session_end]
        exit_price = round_tick(bar["close"])
        exit_reason = "session_close"
        exit_ts = session_end

    pnl = pnl_for(trade, exit_price)
    return {
        "policy": policy,
        "signal_id": trade["signal_id"],
        "direction": trade["direction"],
        "qty": qty,
        "entry_ts": start,
        "exit_ts": exit_ts,
        "exit_reason": exit_reason,
        "exit_price": round(exit_price, 2),
        "pnl": pnl,
        "r_multiple": r_for(trade, exit_price),
        "mfe_1r_reached": mfe >= 1.0,
        "mfe_r": round(mfe, 2),
        "original_exit_reason": trade["exit_reason"],
        "original_exit_price": trade["exit_price"],
        "original_pnl": trade["pnl"],
        "original_r": trade["r_multiple"],
        "original_mfe_r": trade["mfe_r"],
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


def summarize(rows: list[dict]) -> dict:
    ordered = sorted(rows, key=lambda x: x["exit_ts"])
    pnls = [x["pnl"] for x in ordered]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gp = sum(wins)
    gl = sum(losses)
    dd, dd_pct = max_drawdown(pnls)
    streak = worst = 0
    for p in pnls:
        if p < 0:
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
        "avg_r": round(statistics.fmean(x["r_multiple"] for x in ordered), 2) if ordered else 0.0,
        "total_r": round(sum(x["r_multiple"] for x in ordered), 2),
        "max_drawdown": dd,
        "max_drawdown_pct": dd_pct,
        "worst_loss_streak": worst,
    }


def effect(original: list[dict], changed: list[dict]) -> dict:
    o = {x["signal_id"]: x for x in original}
    win_cut = []
    loss_saved = []
    for x in changed:
        before = o[x["signal_id"]]
        before_pnl = before["pnl"]  # P&L de la simulación original, no el de la DB.
        if before_pnl > 0 and x["pnl"] <= 0:
            win_cut.append(
                {
                    "signal_id": x["signal_id"],
                    "original_pnl": before_pnl,
                    "new_pnl": x["pnl"],
                    "original_r": before["r_multiple"],
                    "new_r": x["r_multiple"],
                }
            )
        if before_pnl < 0 and x["pnl"] > before_pnl:
            loss_saved.append(
                {
                    "signal_id": x["signal_id"],
                    "original_pnl": before_pnl,
                    "new_pnl": x["pnl"],
                    "delta": round(x["pnl"] - before_pnl, 2),
                }
            )
    return {
        "winners_cut": len(win_cut),
        "winner_pnl_lost": round(
            sum(o[x["signal_id"]]["pnl"] - x["pnl"] for x in changed
                if o[x["signal_id"]]["pnl"] > 0 and x["pnl"] < o[x["signal_id"]]["pnl"]),
            2,
        ),
        "winners_below_original": sum(
            1 for x in changed
            if o[x["signal_id"]]["pnl"] > 0 and x["pnl"] < o[x["signal_id"]]["pnl"]
        ),
        "losses_improved": len(loss_saved),
        "losses_saved_usd": round(sum(y["delta"] for y in loss_saved), 2),
        "win_cut_detail": win_cut,
        "loss_saved_detail": loss_saved,
    }


def main() -> None:
    bars, stamps, session_last = load_bars()
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    trades = load_trades(con)
    con.close()

    results = {p: [simulate(t, bars, stamps, session_last, p) for t in trades] for p in POLICIES}
    by_id = {p: {x["signal_id"]: x for x in results[p]} for p in POLICIES}

    # Validación del original contra la DB.
    validation = []
    for t in trades:
        x = by_id["original"][t["signal_id"]]
        validation.append(
            {
                "signal_id": t["signal_id"],
                "same_reason": x["exit_reason"] == t["exit_reason"],
                "same_pnl": abs(x["pnl"] - t["pnl"]) <= 0.02,
                "db_reason": t["exit_reason"],
                "sim_reason": x["exit_reason"],
                "db_pnl": t["pnl"],
                "sim_pnl": x["pnl"],
            }
        )

    # En este replay las 8 salidas de la hora 11:00 son las que salen entre
    # 11:00 y 11:59, no solo exactamente a las 11:00.
    hour11_ids = [
        t["signal_id"] for t in trades if et(t["exit_ts"]).hour == 11
    ]
    high_mfe_loss_ids = [
        t["signal_id"] for t in trades if t["pnl"] < 0 and t["mfe_r"] >= 1.0
    ]

    subsets = {
        "all_filtered": [t["signal_id"] for t in trades],
        "hour11_exits": hour11_ids,
        "losses_mfe_ge_1r": high_mfe_loss_ids,
    }

    official_trades = load_official_filter()
    official_results = {
        p: [simulate(t, bars, stamps, session_last, p) for t in official_trades]
        for p in POLICIES
    }
    official = {"trades": len(official_trades), "summary": {}, "effect": {}, "rows": official_results}
    for p in POLICIES:
        official["summary"][p] = summarize(official_results[p])
        official["effect"][p] = effect(official_results["original"], official_results[p]) if p != "original" else None

    report = {
        "schema": "breakeven-1r-experiment-v1",
        "source": str(DB.relative_to(ROOT)),
        "official_source": str(OFFICIAL.relative_to(ROOT)),
        "bars": str(CSV.relative_to(ROOT)),
        "filter": f"stop_or_ratio >= {FILTER_RATIO}",
        "policies": {
            "original": "sin cambios",
            "be_1r": "stop a entrada tras MFE >= 1R",
            "lock_1r": "stop a +1R tras MFE >= 1R",
            "trail_1r": "stop a maximo favorable - 1R tras MFE >= 1R",
        },
        "assumptions": [
            "entradas fijas; no se generan señales nuevas",
            "el stop se mueve desde la vela siguiente a la que alcanza +1R",
            "si stop y target coinciden en una vela, stop primero",
            "slippage 1 tick en stop/target; comision 0.62/lado",
        ],
        "dataset": {
            "trades": len(trades),
            "hour11_exits": len(hour11_ids),
            "losses_mfe_ge_1r": len(high_mfe_loss_ids),
            "wins": sum(1 for t in trades if t["pnl"] > 0),
            "losses": sum(1 for t in trades if t["pnl"] < 0),
        },
        "validation": {
            "same_reason": sum(1 for v in validation if v["same_reason"]),
            "same_pnl": sum(1 for v in validation if v["same_pnl"]),
            "total": len(validation),
            "mismatches": [v for v in validation if not (v["same_reason"] and v["same_pnl"])],
        },
        "subsets": {},
        "official_filter": official,
    }

    for name, ids in subsets.items():
        subset = {
            p: [by_id[p][i] for i in ids] for p in POLICIES
        }
        block = {"trades": len(ids), "summary": {}, "effect": {}}
        for p in POLICIES:
            block["summary"][p] = summarize(subset[p])
            block["effect"][p] = effect(subset["original"], subset[p]) if p != "original" else None
        block["rows"] = subset
        report["subsets"][name] = block

    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("=" * 78)
    print("BREAK-EVEN / TRAILING 1R - REPLAY FILTRADO")
    print("=" * 78)
    print(f"Operaciones filtradas: {len(trades)}")
    print(f"Validacion original: {report['validation']['same_reason']}/{len(trades)} mismo motivo, "
          f"{report['validation']['same_pnl']}/{len(trades)} mismo P&L")
    for name in subsets:
        block = report["subsets"][name]
        print(f"\n--- {name} ({block['trades']} ops) ---")
        for p in POLICIES:
            s = block["summary"][p]
            e = block["effect"][p]
            extra = ""
            if e:
                extra = (f" | ganadores cortados {e['winners_cut']} "
                         f"(-{e['winner_pnl_lost']:.2f} USD) | perdidas mejoradas "
                         f"{e['losses_improved']} (+{e['losses_saved_usd']:.2f} USD)")
            print(f"{p:9s} neto {s['net_profit']:+9.2f} | PF {str(s['profit_factor']):>5s} | "
                  f"R {s['total_r']:+6.2f} | DD {s['max_drawdown']:7.2f} | "
                  f"W/L {s['wins']}/{s['losses']}{extra}")
    print("\n--- official_filter (14 ops, protocolo 362 sesiones) ---")
    for p in POLICIES:
        s = report["official_filter"]["summary"][p]
        e = report["official_filter"]["effect"][p]
        extra = ""
        if e:
            extra = (f" | ganadores cortados {e['winners_cut']} "
                     f"(-{e['winner_pnl_lost']:.2f} USD) | perdidas mejoradas "
                     f"{e['losses_improved']} (+{e['losses_saved_usd']:.2f} USD)")
        print(f"{p:9s} neto {s['net_profit']:+9.2f} | PF {str(s['profit_factor']):>5s} | "
              f"R {s['total_r']:+6.2f} | DD {s['max_drawdown']:7.2f} | "
              f"W/L {s['wins']}/{s['losses']}{extra}")
    print(f"\nJSON: {OUT}")


if __name__ == "__main__":
    main()
