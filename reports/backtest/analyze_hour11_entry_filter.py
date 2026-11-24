"""Filtros de entrada para las 8 pérdidas que salen en la hora 11:00.

Fuente: replay paper de 56 operaciones (`preset_card_8766.db`), 44 tras el
filtro stop/ORB >= 0,25. Las 8 pérdidas son las que tienen `exit_ts` entre
11:00 y 11:59 ET y no alcanzan +1R; la gestión BE/trailing no las puede ayudar.

El análisis es de entradas fijas: cada filtro solo elimina operaciones. No
re-simula señales ni modifica el motor, la configuración activa o el holdout.

Features calculadas con barras MNQ de 1 minuto hasta la vela de entrada
inclusive (el fill ocurre al cierre de esa vela):

  ret3_dir   retorno de 3 velas / ancho ORB, firmado por dirección
  ret20_dir  retorno de 20 velas / ancho ORB, firmado por dirección
  vwap_dir   (entry - VWAP de sesión) / ancho ORB, firmado por dirección
  entry_min  minutos desde las 09:30 ET

Reglas evaluadas:

  core      ret3_dir <= -0,05 y ret20_dir <= -0,40
  extended  core o (10:50 <= entry_min < 11:05 y vwap_dir <= 0)
  wide      core o (10:45 <= entry_min < 11:15 y vwap_dir <= 0)
  time_only (10:50 <= entry_min < 11:05 y vwap_dir <= 0)

Salidas: `hour11_entry_filter.json` y `HOUR11_ENTRY_FILTER.md`.
"""

from __future__ import annotations

import csv
import json
import sqlite3
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.stats import compute_stats  # noqa: E402

DB = ROOT / "reports" / "backtest" / "preset_card_8766.db"
CSV = ROOT / "data" / "real" / "bars_mnq_nq_es_1m.csv"
BE_REPORT = ROOT / "reports" / "backtest" / "breakeven_1r_experiment.json"
OFFICIAL = ROOT / "reports" / "backtest" / "breakeven_1r_protocol_all.json"
OUT_JSON = ROOT / "reports" / "backtest" / "hour11_entry_filter.json"
OUT_MD = ROOT / "reports" / "backtest" / "HOUR11_ENTRY_FILTER.md"
ET = ZoneInfo("America/New_York")
TICK = 0.25
FILTER_RATIO = 0.25
INITIAL_CAPITAL = 25_000.0


def et_dt(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, ET)


def load_bars() -> tuple[dict[str, dict[int, dict[str, float]]], dict[str, dict[Any, list[int]]]]:
    bars: dict[str, dict[int, dict[str, float]]] = {s: {} for s in ("MNQ", "NQ", "ES")}
    with CSV.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            symbol = row["symbol"]
            if symbol not in bars:
                continue
            ts = int(datetime.fromisoformat(row["timestamp"]).timestamp())
            bars[symbol][ts] = {
                key: float(row[key]) for key in ("open", "high", "low", "close", "volume")
            }
    by_day: dict[str, dict[Any, list[int]]] = {s: defaultdict(list) for s in bars}
    for symbol, series in bars.items():
        for ts in series:
            by_day[symbol][et_dt(ts).date()].append(ts)
    for symbol in by_day:
        for day in by_day[symbol]:
            by_day[symbol][day].sort()
    return bars, by_day


def features(
    entry_ts: int,
    meta: dict[str, Any],
    direction: str,
    entry_price: float,
    bars: dict[str, dict[int, dict[str, float]]],
    by_day: dict[str, dict[Any, list[int]]],
) -> dict[str, float] | None:
    day = et_dt(entry_ts).date()
    start_ts = int(
        datetime.combine(day, datetime.min.time(), ET)
        .replace(hour=9, minute=30)
        .timestamp()
    )
    stamps = [ts for ts in by_day["MNQ"].get(day, []) if start_ts <= ts <= entry_ts]
    if len(stamps) < 21:
        return None
    width = float(meta["orb_high"]) - float(meta["orb_low"])
    if width <= 0:
        return None
    sign = 1 if direction == "long" else -1

    vwap_num = 0.0
    vwap_den = 0.0
    vwaps: list[float] = []
    for ts in stamps:
        bar = bars["MNQ"][ts]
        typical = (bar["high"] + bar["low"] + bar["close"]) / 3.0
        vwap_num += typical * bar["volume"]
        vwap_den += bar["volume"]
        vwaps.append(vwap_num / vwap_den if vwap_den else entry_price)
    vwap = vwaps[-1]

    entry_bar = bars["MNQ"][stamps[-1]]
    c3 = bars["MNQ"][stamps[-4]]["close"]
    c20 = bars["MNQ"][stamps[-21]]["close"]
    closes = [bars["MNQ"][ts]["close"] for ts in stamps]
    vols = [bars["MNQ"][ts]["volume"] for ts in stamps]
    true_ranges = []
    for i in range(1, len(stamps)):
        bar = bars["MNQ"][stamps[i]]
        prev_close = bars["MNQ"][stamps[i - 1]]["close"]
        true_ranges.append(
            max(
                bar["high"] - bar["low"],
                abs(bar["high"] - prev_close),
                abs(bar["low"] - prev_close),
            )
        )

    return {
        "entry_min": round((entry_ts - start_ts) / 60.0, 2),
        "ret3_dir": round(((entry_bar["close"] - c3) / width) * sign, 6),
        "ret20_dir": round(((entry_bar["close"] - c20) / width) * sign, 6),
        "vwap_dir": round(((entry_price - vwap) / width) * sign, 6),
        "stop_ticks": round(float(meta["stop_ticks"]), 2),
        "orb_width_ticks": round(width / TICK, 2),
        "stop_or_ratio": round(float(meta["stop_ticks"]) / (width / TICK), 6),
        "entry_delay_min": round(float(meta["entry_delay_min"]), 2),
        "retest_ticks": round(float(meta["retest_distance_ticks"]), 2),
        "direct_stop_ticks": round(float(meta["direct_stop_ticks"]), 2),
        "atr14_orb": round(statistics.fmean(true_ranges[-14:]) / width, 6)
        if true_ranges
        else 0.0,
        "vol5_20": round(
            statistics.fmean(vols[-5:]) / statistics.fmean(vols[-25:-5]), 6
        )
        if len(vols) >= 25 and statistics.fmean(vols[-25:-5])
        else 0.0,
        "entry_bar_range_orb": round(
            (entry_bar["high"] - entry_bar["low"]) / width, 6
        ),
        "entry_bar_body_orb": round(
            abs(entry_bar["close"] - entry_bar["open"]) / width, 6
        ),
        "last_close": round(closes[-1], 2),
    }


def load_paper(
    bars: dict[str, dict[int, dict[str, float]]],
    by_day: dict[str, dict[Any, list[int]]],
) -> list[dict[str, Any]]:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows: list[dict[str, Any]] = []
    for raw in con.execute("select * from trades order by entry_ts"):
        meta = json.loads(raw["meta"])
        width = (meta["orb_high"] - meta["orb_low"]) / TICK
        ratio = meta["stop_ticks"] / width if width else 0.0
        if ratio < FILTER_RATIO:
            continue
        trade = dict(raw)
        trade["meta"] = meta
        extra = features(
            int(trade["entry_ts"]),
            meta,
            str(trade["direction"]),
            float(trade["entry_price"]),
            bars,
            by_day,
        )
        if extra is None:
            continue
        trade.update(extra)
        trade["entry_et"] = et_dt(int(trade["entry_ts"])).strftime("%Y-%m-%d %H:%M")
        trade["exit_et"] = et_dt(int(trade["exit_ts"])).strftime("%Y-%m-%d %H:%M")
        trade["hour11_loss"] = bool(
            et_dt(int(trade["exit_ts"])).hour == 11 and float(trade["pnl"]) < 0
        )
        rows.append(trade)
    con.close()
    return rows


def load_official(
    bars: dict[str, dict[int, dict[str, float]]],
    by_day: dict[str, dict[Any, list[int]]],
) -> list[dict[str, Any]]:
    report = json.loads(OFFICIAL.read_text(encoding="utf-8"))
    rows = []
    for trade in report["arms"]["filter"]["trades"]:
        extra = features(
            int(trade["entry_ts"]),
            trade["meta"],
            str(trade["direction"]),
            float(trade["entry_price"]),
            bars,
            by_day,
        )
        if extra is None:
            continue
        rows.append(
            {
                "signal_id": trade["meta"]["signal_id"],
                "pnl": float(trade["pnl"]),
                "win": float(trade["pnl"]) > 0,
                **extra,
            }
        )
    return rows


def core(trade: dict[str, Any]) -> bool:
    return trade["ret3_dir"] <= -0.05 and trade["ret20_dir"] <= -0.40


def extended(trade: dict[str, Any]) -> bool:
    return core(trade) or (
        80 <= trade["entry_min"] < 95 and trade["vwap_dir"] <= 0
    )


def wide(trade: dict[str, Any]) -> bool:
    return core(trade) or (
        75 <= trade["entry_min"] < 105 and trade["vwap_dir"] <= 0
    )


def time_only(trade: dict[str, Any]) -> bool:
    return 80 <= trade["entry_min"] < 95 and trade["vwap_dir"] <= 0


RULES: dict[str, Callable[[dict[str, Any]], bool]] = {
    "core": core,
    "extended": extended,
    "wide": wide,
    "time_only": time_only,
}


def metrics(trades: list[dict[str, Any]]) -> dict[str, Any]:
    stats = compute_stats(trades, INITIAL_CAPITAL)
    keys = (
        "trades",
        "wins",
        "losses",
        "win_rate",
        "net_profit",
        "profit_factor",
        "max_drawdown",
        "max_drawdown_pct",
        "worst_loss_streak",
        "avg_r",
        "gross_profit",
        "gross_loss",
    )
    return {key: stats.get(key) for key in keys}


def detail(trade: dict[str, Any], pnl: float) -> dict[str, Any]:
    return {
        "signal_id": trade["signal_id"],
        "entry_et": trade["entry_et"],
        "exit_et": trade["exit_et"],
        "direction": trade["direction"],
        "pnl": round(float(pnl), 2),
        "mfe_r": round(float(trade.get("mfe_r") or 0.0), 2),
        "ret3_dir": round(float(trade["ret3_dir"]), 3),
        "ret20_dir": round(float(trade["ret20_dir"]), 3),
        "vwap_dir": round(float(trade["vwap_dir"]), 3),
        "entry_min": round(float(trade["entry_min"]), 1),
    }


def evaluate(
    label: str,
    rule: Callable[[dict[str, Any]], bool],
    rows: list[dict[str, Any]],
    be_pnl: dict[str, float],
) -> dict[str, Any]:
    removed = [trade for trade in rows if rule(trade)]
    kept = [trade for trade in rows if not rule(trade)]
    removed_ids = {trade["signal_id"] for trade in removed}
    h11 = [trade for trade in removed if trade["hour11_loss"]]
    winners = [trade for trade in removed if float(trade["pnl"]) > 0]
    other_losses = [
        trade
        for trade in removed
        if not trade["hour11_loss"] and float(trade["pnl"]) <= 0
    ]
    base_all = metrics(rows)
    base_kept = metrics(kept)
    be_kept = [
        dict(trade, pnl=be_pnl[trade["signal_id"]])
        for trade in kept
        if trade["signal_id"] in be_pnl
    ]
    be_all = [
        dict(trade, pnl=be_pnl[trade["signal_id"]])
        for trade in rows
        if trade["signal_id"] in be_pnl
    ]
    be_kept_metrics = metrics(be_kept)
    be_all_metrics = metrics(be_all)
    removed_base = round(sum(float(trade["pnl"]) for trade in removed), 2)
    removed_be = round(
        sum(be_pnl[trade["signal_id"]] for trade in removed if trade["signal_id"] in be_pnl),
        2,
    )
    by_period = {}
    for name, start, end in (
        ("2025", "2025-01-01", "2026-01-01"),
        ("2026", "2026-01-01", "2027-01-01"),
    ):
        period = [trade for trade in rows if start <= trade["entry_et"][:10] < end]
        p_removed = [trade for trade in period if rule(trade)]
        p_kept = [trade for trade in period if not rule(trade)]
        by_period[name] = {
            "all": {
                "trades": len(period),
                "hour11_losses": sum(1 for trade in period if trade["hour11_loss"]),
                "net_profit": round(sum(float(trade["pnl"]) for trade in period), 2),
            },
            "removed": {
                "trades": len(p_removed),
                "hour11_losses": sum(1 for trade in p_removed if trade["hour11_loss"]),
                "winners": sum(1 for trade in p_removed if float(trade["pnl"]) > 0),
                "pnl": round(sum(float(trade["pnl"]) for trade in p_removed), 2),
            },
            "kept": {
                "trades": len(p_kept),
                "hour11_losses": sum(1 for trade in p_kept if trade["hour11_loss"]),
                "net_profit": round(sum(float(trade["pnl"]) for trade in p_kept), 2),
            },
        }
    return {
        "rule": label,
        "removed_trades": len(removed),
        "kept_trades": len(kept),
        "hour11_losses_total": sum(1 for trade in rows if trade["hour11_loss"]),
        "hour11_losses_avoided": len(h11),
        "hour11_loss_usd_avoided": round(sum(-float(trade["pnl"]) for trade in h11), 2),
        "winners_removed": len(winners),
        "winner_pnl_removed": round(sum(float(trade["pnl"]) for trade in winners), 2),
        "other_losses_removed": len(other_losses),
        "other_loss_usd_avoided": round(
            sum(-float(trade["pnl"]) for trade in other_losses), 2
        ),
        "net_delta_base": round(-removed_base, 2),
        "net_delta_be": round(-removed_be, 2),
        "removed": {
            "hour11": [detail(trade, trade["pnl"]) for trade in h11],
            "winners": [detail(trade, trade["pnl"]) for trade in winners],
            "other_losses": [detail(trade, trade["pnl"]) for trade in other_losses],
        },
        "remaining_hour11": [
            detail(trade, trade["pnl"]) for trade in kept if trade["hour11_loss"]
        ],
        "base_before": base_all,
        "base_after": base_kept,
        "be_before": be_all_metrics,
        "be_after": be_kept_metrics,
        "by_period": by_period,
        "removed_ids": sorted(removed_ids),
    }


def official_check(
    rows: list[dict[str, Any]], rule: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    removed = [trade for trade in rows if rule(trade)]
    return {
        "trades": len(rows),
        "removed": len(removed),
        "winners_removed": sum(1 for trade in removed if trade["win"]),
        "winner_pnl_removed": round(
            sum(float(trade["pnl"]) for trade in removed if trade["win"]), 2
        ),
        "losses_removed": sum(1 for trade in removed if float(trade["pnl"]) < 0),
        "net_saved": round(sum(-float(trade["pnl"]) for trade in removed), 2),
        "detail": [
            {
                "signal_id": trade["signal_id"],
                "pnl": round(float(trade["pnl"]), 2),
                "ret3_dir": round(float(trade["ret3_dir"]), 3),
                "ret20_dir": round(float(trade["ret20_dir"]), 3),
                "vwap_dir": round(float(trade["vwap_dir"]), 3),
                "entry_min": round(float(trade["entry_min"]), 1),
            }
            for trade in removed
        ],
    }


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        text = f"{value:,.{digits}f}"
        return text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return f"{value:,}".replace(",", ".")


def main() -> int:
    bars, by_day = load_bars()
    rows = load_paper(bars, by_day)
    if len(rows) != 44:
        raise RuntimeError(f"Se esperaban 44 operaciones filtradas; hay {len(rows)}")
    h11 = [trade for trade in rows if trade["hour11_loss"]]
    if len(h11) != 8:
        raise RuntimeError(f"Se esperaban 8 pérdidas de hora 11; hay {len(h11)}")
    be_report = json.loads(BE_REPORT.read_text(encoding="utf-8"))
    be_pnl = {
        row["signal_id"]: float(row["pnl"])
        for row in be_report["subsets"]["all_filtered"]["rows"]["be_1r"]
    }
    if len(be_pnl) != len(rows):
        raise RuntimeError("El BE de referencia no cubre las 44 operaciones")

    results = {
        name: evaluate(name, rule, rows, be_pnl) for name, rule in RULES.items()
    }
    official_rows = load_official(bars, by_day)
    official = {
        name: official_check(official_rows, rule) for name, rule in RULES.items()
    }
    payload = {
        "schema": "hour11-entry-filter-v1",
        "source": {
            "paper_db": str(DB.relative_to(ROOT)),
            "bars": str(CSV.relative_to(ROOT)),
            "be_reference": str(BE_REPORT.relative_to(ROOT)),
            "filtered_trades": len(rows),
            "hour11_losses": len(h11),
            "hour11_loss_usd": round(sum(float(trade["pnl"]) for trade in h11), 2),
            "winners": sum(1 for trade in rows if float(trade["pnl"]) > 0),
            "losses": sum(1 for trade in rows if float(trade["pnl"]) < 0),
            "holdout_used": False,
        },
        "definitions": {
            "ret3_dir": "retorno 3 velas / ancho ORB, firmado por dirección",
            "ret20_dir": "retorno 20 velas / ancho ORB, firmado por dirección",
            "vwap_dir": "(entry - VWAP sesión) / ancho ORB, firmado por dirección",
            "entry_min": "minutos desde 09:30 ET",
            "core": "ret3_dir <= -0,05 y ret20_dir <= -0,40",
            "extended": "core o (10:50 <= entry_min < 11:05 y vwap_dir <= 0)",
            "wide": "core o (10:45 <= entry_min < 11:15 y vwap_dir <= 0)",
            "time_only": "(10:50 <= entry_min < 11:05 y vwap_dir <= 0)",
        },
        "hour11_losses": [detail(trade, trade["pnl"]) for trade in h11],
        "rules": results,
        "official_14_cross_check": official,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# Filtro de entrada para las pérdidas que salen en la hora 11:00",
        "",
        "**Fuente:** replay paper de 56 operaciones, 44 tras el filtro `stop/ORB >= 0,25`.  ",
        "**Pérdidas objetivo:** 8 operaciones con salida entre 11:00 y 11:59 ET, todas con MFE < 1R.  ",
        "**Naturaleza:** medición sobre entradas fijas; no re-simula señales ni toca el holdout.",
        "",
        "## Las 8 pérdidas",
        "",
        "| Señal | Entrada | Salida | Dir | P&L | MFE R | ret3/ORB | ret20/ORB | VWAP/ORB |",
        "|---|---:|---:|---|---:|---:|---:|---:|---:|",
    ]
    for trade in h11:
        lines.append(
            f"| `{trade['signal_id']}` | {trade['entry_et'][11:]} | "
            f"{trade['exit_et'][11:]} | {trade['direction']} | "
            f"{fmt(float(trade['pnl']))} | {fmt(float(trade['mfe_r']))} | "
            f"{fmt(float(trade['ret3_dir']), 3)} | {fmt(float(trade['ret20_dir']), 3)} | "
            f"{fmt(float(trade['vwap_dir']), 3)} |"
        )
    lines += [
        "",
        "Las 8 son `stop_loss`, con MFE entre 0,00R y 0,53R. No llegan a +1R: BE, lock o trailing no pueden mejorarlas.",
        "",
        "## Reglas y resultado",
        "",
        "| Regla | Ops quitadas | H11 evitadas | Ganadoras quitadas | Otras pérdidas | Neto delta | DD después | PF después | Racha |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("core", "extended", "wide", "time_only"):
        result = results[name]
        after = result["base_after"]
        lines.append(
            f"| `{name}` | {result['removed_trades']} | "
            f"{result['hour11_losses_avoided']}/8 | {result['winners_removed']} | "
            f"{result['other_losses_removed']} | {fmt(result['net_delta_base'])} | "
            f"{fmt(after['max_drawdown'])} | {fmt(after['profit_factor'])} | "
            f"{after['worst_loss_streak']} |"
        )
    lines += [
        "",
        "## Comparación contra el BE 1R",
        "",
        "| Regla | Neto base | Neto BE | DD base | DD BE | Ganadoras base | Ganadoras BE |",
        "|---|---:|---:|---:|---:|---:|---:|",
        "| original | 4.543,62 | 3.670,12 | 2.128,28 | 1.501,44 | 22 | 16 |",
    ]
    for name in ("core", "extended"):
        result = results[name]
        lines.append(
            f"| `{name}` | {fmt(result['base_after']['net_profit'])} | "
            f"{fmt(result['be_after']['net_profit'])} | "
            f"{fmt(result['base_after']['max_drawdown'])} | "
            f"{fmt(result['be_after']['max_drawdown'])} | "
            f"{result['base_after']['wins']} | {result['be_after']['wins']} |"
        )
    lines += [
        "",
        "## Detalle",
        "",
        "### Core (recomendado como base robusta)",
        "",
        f"- Evita **{results['core']['hour11_losses_avoided']}/8** pérdidas H11 y **{results['core']['other_losses_removed']}** pérdidas adicionales; **0 ganadoras**.",
        f"- Neto: **+{fmt(results['core']['net_delta_base'])}**; DD: 2.128,28 → **{fmt(results['core']['base_after']['max_drawdown'])}**; PF: 2,00 → **{fmt(results['core']['base_after']['profit_factor'])}**.",
        "- No atrapa las 4 H11 restantes: 07-23, 09-04, 11-20 y 04-09.",
        "",
        "### Extended (más agresivo, 10:50–11:05 + VWAP)",
        "",
        f"- Evita **{results['extended']['hour11_losses_avoided']}/8** pérdidas H11 y **{results['extended']['other_losses_removed']}** adicionales; **0 ganadoras**.",
        f"- Neto: **+{fmt(results['extended']['net_delta_base'])}**; DD: 2.128,28 → **{fmt(results['extended']['base_after']['max_drawdown'])}**; PF: 2,00 → **{fmt(results['extended']['base_after']['profit_factor'])}**.",
        "- Solo queda `2025-09-04-short-1756994400` (−176,48), que entra con momento positivo y no lo atrapa ninguna regla estudiada.",
        "- La rama 10:50–11:05 es una ventana de 15 minutos elegida in-sample; es la parte frágil.",
        "",
        "### Wide (atrapar las 8)",
        "",
        f"- Evita **8/8** H11, pero quita **{results['wide']['winners_removed']} ganadoras** por **{fmt(results['wide']['winner_pnl_removed'])}** USD.",
        f"- Neto: +{fmt(results['wide']['net_delta_base'])}; DD {fmt(results['wide']['base_after']['max_drawdown'])}. No cumple “sin quitar ganadores”.",
        "",
        "## Split temporal",
        "",
        "| Regla | 2025 quitadas | H11 2025 | Ganadoras 2025 | 2026 quitadas | H11 2026 | Ganadoras 2026 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("core", "extended", "wide"):
        p = results[name]["by_period"]
        lines.append(
            f"| `{name}` | {p['2025']['removed']['trades']} | "
            f"{p['2025']['removed']['hour11_losses']} | {p['2025']['removed']['winners']} | "
            f"{p['2026']['removed']['trades']} | {p['2026']['removed']['hour11_losses']} | "
            f"{p['2026']['removed']['winners']} |"
        )
    lines += [
        "",
        "El filtro conserva 0 ganadoras quitadas en ambos períodos para `core` y `extended`; no es una validación fuera de muestra porque los umbrales se eligieron mirando la muestra completa.",
        "",
        "## Cross-check en el protocolo oficial de 14 operaciones",
        "",
        "| Regla | Ops quitadas | Ganadoras quitadas | Pérdidas quitadas | Neto ahorrado |",
        "|---|---:|---:|---:|---:|",
    ]
    for name in ("core", "extended", "wide"):
        item = official[name]
        lines.append(
            f"| `{name}` | {item['removed']} | {item['winners_removed']} | "
            f"{item['losses_removed']} | {fmt(item['net_saved'])} |"
        )
    lines += [
        "",
        "En el protocolo oficial de 14 operaciones, `core` y `extended` solo quitan dos pérdidas (2025-09-03 y 2025-09-19) y **ninguna ganadora**.",
        "",
        "## Conclusión",
        "",
        "- **Sí existe un filtro que evita la mayoría de las 8 pérdidas sin quitar ganadoras en esta muestra.** `extended` evita 7/8 y 0 ganadoras; `core` evita 4/8 y 0 ganadoras.",
        "- **No hay una regla simple que evite las 8 sin quitar ganadoras.** Para atrapar también 09-04 hay que ampliar la ventana y se pierden 4 ganadoras.",
        "- La parte robusta es el momento adverso (`ret3`/`ret20`); la ventana 10:50–11:05/VWAP es la parte más frágil y necesita validación fuera de muestra.",
        "- No se modificó el motor ni la configuración activa. El holdout sigue sin usarse.",
        "",
        f"JSON: `{OUT_JSON.relative_to(ROOT)}`",
    ]
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(
        f"OK {len(rows)} ops | H11 {len(h11)} | "
        f"core {results['core']['hour11_losses_avoided']}/8 +{results['core']['net_delta_base']:.2f} | "
        f"extended {results['extended']['hour11_losses_avoided']}/8 +{results['extended']['net_delta_base']:.2f} | "
        f"wide {results['wide']['hour11_losses_avoided']}/8 winners {results['wide']['winners_removed']}"
    )
    print(f"JSON: {OUT_JSON.relative_to(ROOT)}")
    print(f"MD:   {OUT_MD.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
