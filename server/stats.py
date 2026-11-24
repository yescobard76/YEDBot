"""Métricas de rendimiento a partir de operaciones cerradas reales o backtests."""

from __future__ import annotations

import math
import statistics
from datetime import date, datetime
from typing import Any, Iterable

from .timeutil import et_date, local_dt

TRADING_DAYS = 252


def _safe_div(a: float, b: float) -> float | None:
    if b == 0:
        return None
    return a / b


def _streaks(pnls: list[float]) -> tuple[int, int, int, int]:
    """Devuelve (racha ganadora actual, máxima, racha perdedora actual, máxima)."""
    best_w = worst_l = cur_w = cur_l = 0
    last_win: int = 0
    for pnl in pnls:
        if pnl > 0:
            cur_w = cur_w + 1 if last_win >= 0 else 1
            cur_l = 0
            last_win = 1
            best_w = max(best_w, cur_w)
        elif pnl < 0:
            cur_l = cur_l + 1 if last_win <= 0 else 1
            cur_w = 0
            last_win = -1
            worst_l = max(worst_l, cur_l)
        else:
            cur_w = cur_l = 0
    return cur_w, best_w, cur_l, worst_l


def equity_curve(trades: list[dict], initial: float) -> list[dict]:
    equity = initial
    out = [{"ts": trades[0]["entry_ts"] if trades else 0, "equity": round(equity, 2)}]
    for t in sorted(trades, key=lambda x: x["exit_ts"]):
        equity += float(t["pnl"])
        out.append({"ts": int(t["exit_ts"]), "equity": round(equity, 2)})
    return out


def max_drawdown(curve: list[dict], initial: float) -> tuple[float, float, float]:
    peak = initial
    worst_abs = 0.0
    worst_pct = 0.0
    trough = initial
    for point in curve:
        eq = float(point["equity"])
        peak = max(peak, eq)
        dd = peak - eq
        if dd > worst_abs:
            worst_abs = dd
            worst_pct = (dd / peak * 100) if peak else 0.0
            trough = eq
    return round(worst_abs, 2), round(worst_pct, 3), round(trough, 2)


def _aggregate(trades: list[dict], key_fn) -> list[dict]:
    buckets: dict[Any, dict] = {}
    for t in trades:
        key = key_fn(t)
        if key is None:
            continue
        b = buckets.setdefault(key, {"key": key, "trades": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        b["trades"] += 1
        b["pnl"] += float(t["pnl"])
        if t["pnl"] > 0:
            b["wins"] += 1
        elif t["pnl"] < 0:
            b["losses"] += 1
    return sorted(buckets.values(), key=lambda x: x["key"])


def compute_stats(
    trades: list[dict],
    initial_capital: float,
    sessions: Iterable[date | str] | None = None,
) -> dict[str, Any]:
    """Calcula métricas de rendimiento.

    ``sessions`` es el calendario de sesiones evaluadas. Si se proporciona, los
    días sin operaciones entran en la serie diaria con retorno cero, de modo que
    Sharpe y Sortino no se calculan solo sobre los días que tuvieron trades.
    """
    closed = sorted(trades, key=lambda t: t["exit_ts"])
    pnls = [float(t["pnl"]) for t in closed]
    total = len(closed)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = sum(losses)
    net = sum(pnls)
    curve = equity_curve(closed, initial_capital)
    dd_abs, dd_pct, trough = max_drawdown(curve, initial_capital)

    # Rendimiento diario para Sharpe / Sortino. El calendario manda cuando se
    # conoce: una sesión sin trades es un retorno 0, no una sesión inexistente.
    daily: dict[str, float] = {}
    if sessions is not None:
        for session in sessions:
            key = session.isoformat() if isinstance(session, date) else str(session)
            daily[key] = 0.0
    for t in closed:
        day = et_date(int(t["exit_ts"])).isoformat()
        daily[day] = daily.get(day, 0.0) + float(t["pnl"])
    returns = [daily[key] / initial_capital for key in sorted(daily)] if initial_capital else []
    sharpe = sortino = None
    if len(returns) >= 2:
        mean_r = statistics.fmean(returns)
        std = statistics.pstdev(returns)
        if std > 0:
            sharpe = round(mean_r / std * math.sqrt(TRADING_DAYS), 2)
        downside = [r for r in returns if r < 0]
        if len(downside) >= 1:
            dstd = math.sqrt(sum(r * r for r in downside) / len(returns))
            if dstd > 0:
                sortino = round(mean_r / dstd * math.sqrt(TRADING_DAYS), 2)

    rs = [float(t.get("r_multiple") or 0) for t in closed]
    mfe_rs = [float(t.get("mfe_r") or 0) for t in closed]
    mae_rs = [float(t.get("mae_r") or 0) for t in closed]
    open_dds = [float(t.get("open_drawdown") or 0) for t in closed]
    durations = [int(t.get("duration_sec") or 0) for t in closed]
    cur_w, best_w, cur_l, best_l = _streaks(pnls)
    win_rate = (len(wins) / total * 100) if total else 0.0
    profit_factor = _safe_div(gross_profit, abs(gross_loss))
    expectancy = _safe_div(net, total) if total else 0.0
    avg_r = statistics.fmean(rs) if rs else 0.0
    avg_mfe_r = statistics.fmean(mfe_rs) if mfe_rs else 0.0
    avg_mae_r = statistics.fmean(mae_rs) if mae_rs else 0.0
    avg_open_dd = statistics.fmean(open_dds) if open_dds else 0.0
    max_open_dd = max(open_dds, default=0.0)

    by_hour = []
    for bucket in _aggregate(
        closed, lambda t: local_dt(int(t["exit_ts"])).hour
    ):
        bucket["label"] = f"{int(bucket['key']):02d}:00"
        bucket["win_rate"] = round(bucket["wins"] / bucket["trades"] * 100, 1) if bucket["trades"] else 0
        by_hour.append(bucket)

    by_direction = []
    for bucket in _aggregate(closed, lambda t: t["direction"]):
        bucket["label"] = "Larga" if bucket["key"] == "long" else "Corta"
        bucket["win_rate"] = round(bucket["wins"] / bucket["trades"] * 100, 1) if bucket["trades"] else 0
        by_direction.append(bucket)

    by_signal = []
    for bucket in _aggregate(closed, lambda t: t.get("signal_type") or "ORB"):
        bucket["label"] = bucket["key"]
        bucket["win_rate"] = round(bucket["wins"] / bucket["trades"] * 100, 1) if bucket["trades"] else 0
        by_signal.append(bucket)

    weekday_names = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]
    by_weekday = []
    for bucket in _aggregate(closed, lambda t: et_date(int(t["exit_ts"])).weekday()):
        bucket["label"] = weekday_names[int(bucket["key"])]
        by_weekday.append(bucket)

    monthly: dict[str, dict] = {}
    for t in closed:
        d = local_dt(int(t["exit_ts"]))
        key = f"{d.year}-{d.month:02d}"
        m = monthly.setdefault(key, {"key": key, "label": key, "trades": 0, "pnl": 0.0, "wins": 0})
        m["trades"] += 1
        m["pnl"] += float(t["pnl"])
        if t["pnl"] > 0:
            m["wins"] += 1
    for m in monthly.values():
        m["win_rate"] = round(m["wins"] / m["trades"] * 100, 1) if m["trades"] else 0

    daily_series = [{"key": k, "label": k[5:], "pnl": round(v, 2)} for k, v in sorted(daily.items())]

    return {
        "trades": total,
        "wins": len(wins),
        "losses": len(losses),
        "breakeven": total - len(wins) - len(losses),
        "win_rate": round(win_rate, 2),
        "profit_factor": round(profit_factor, 2) if profit_factor is not None else None,
        "expectancy": round(expectancy or 0.0, 2),
        "net_profit": round(net, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "fees": round(sum(float(t.get("fees") or 0) for t in closed), 2),
        "avg_win": round(statistics.fmean(wins), 2) if wins else 0.0,
        "avg_loss": round(statistics.fmean(losses), 2) if losses else 0.0,
        "avg_trade": round(statistics.fmean(pnls), 2) if pnls else 0.0,
        "avg_r": round(avg_r, 2),
        "avg_mfe_r": round(avg_mfe_r, 2),
        "avg_mae_r": round(avg_mae_r, 2),
        "avg_open_drawdown": round(avg_open_dd, 2),
        "max_open_drawdown": round(max_open_dd, 2),
        "max_open_drawdown_pct": round(max_open_dd / initial_capital * 100, 3) if initial_capital else 0.0,
        "open_drawdown": round(max_open_dd, 2),
        "open_drawdown_pct": round(max_open_dd / initial_capital * 100, 3) if initial_capital else 0.0,
        "avg_mfe": round(avg_mfe_r, 2),
        "avg_mae": round(avg_mae_r, 2),
        "total_r": round(sum(rs), 2),
        "best_trade": round(max(pnls), 2) if pnls else 0.0,
        "worst_trade": round(min(pnls), 2) if pnls else 0.0,
        "max_drawdown": dd_abs,
        "max_drawdown_pct": dd_pct,
        "equity_trough": trough,
        "sharpe": sharpe,
        "sortino": sortino,
        "best_win_streak": best_w,
        "worst_loss_streak": best_l,
        "current_win_streak": cur_w,
        "current_loss_streak": cur_l,
        "avg_duration_sec": int(statistics.fmean(durations)) if durations else 0,
        "avg_win_r": round(statistics.fmean([r for r in rs if r > 0]), 2) if any(r > 0 for r in rs) else 0.0,
        "avg_loss_r": round(statistics.fmean([r for r in rs if r < 0]), 2) if any(r < 0 for r in rs) else 0.0,
        "equity_curve": curve,
        "daily": daily_series,
        "monthly": sorted(monthly.values(), key=lambda x: x["key"]),
        "by_hour": by_hour,
        "by_direction": by_direction,
        "by_signal": by_signal,
        "by_weekday": by_weekday,
        "distribution": {"wins": len(wins), "losses": len(losses), "breakeven": total - len(wins) - len(losses)},
    }
