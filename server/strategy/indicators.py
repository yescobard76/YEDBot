"""Indicadores y agregación de velas (sin look-ahead)."""

from __future__ import annotations

from ..models import Bar


def aggregate(bars: list[Bar], minutes: int) -> list[Bar]:
    """Agrupa velas de 1m en buckets alineados al reloj.

    Los timestamps de ET son offsets enteros de hora respecto a UTC, por lo que
    el alineamiento por epoch módulo ``minutes*60`` coincide con la hora local.
    """
    if not bars or minutes <= 1:
        return list(bars)
    span = minutes * 60
    buckets: dict[int, Bar] = {}
    for bar in bars:
        key = bar.ts - bar.ts % span
        cur = buckets.get(key)
        if cur is None:
            buckets[key] = Bar(key, bar.open, bar.high, bar.low, bar.close, bar.volume)
        else:
            cur.high = max(cur.high, bar.high)
            cur.low = min(cur.low, bar.low)
            cur.close = bar.close
            cur.volume += bar.volume
    last_bar_ts = bars[-1].ts
    return [buckets[k] for k in sorted(buckets) if buckets[k].ts + span <= last_bar_ts + 60]


def true_range(prev_close: float | None, bar: Bar) -> float:
    if prev_close is None:
        return bar.high - bar.low
    return max(bar.high - bar.low, abs(bar.high - prev_close), abs(bar.low - prev_close))


def atr(bars: list[Bar], period: int = 14) -> float | None:
    if len(bars) < 2:
        return None
    trs: list[float] = []
    prev_close = None
    for bar in bars[-(period + 1):]:
        trs.append(true_range(prev_close, bar))
        prev_close = bar.close
    if not trs:
        return None
    if len(trs) < period:
        return sum(trs) / len(trs)
    # Suavizado de Wilder
    value = sum(trs[:period]) / period
    for tr in trs[period:]:
        value = (value * (period - 1) + tr) / period
    return value


def vwap_series(bars: list[Bar]) -> list[float]:
    cum_pv = 0.0
    cum_v = 0.0
    out: list[float] = []
    for bar in bars:
        typical = (bar.high + bar.low + bar.close) / 3
        vol = max(bar.volume, 0.0)
        cum_pv += typical * vol
        cum_v += vol
        out.append(cum_pv / cum_v if cum_v else bar.close)
    return out


def find_swing(bars: list[Bar], direction: str, depth: int = 3) -> float | None:
    """Último swing confirmado (no repinta) antes de la última vela."""
    n = len(bars)
    if n < depth * 2 + 1:
        return None
    for i in range(n - 1 - depth, depth - 1, -1):
        window = bars[i - depth:i + depth + 1]
        if direction == "long":
            if all(b.low >= bars[i].low for b in window):
                return bars[i].low
        else:
            if all(b.high <= bars[i].high for b in window):
                return bars[i].high
    low = min(b.low for b in bars[-depth * 2:])
    high = max(b.high for b in bars[-depth * 2:])
    return low if direction == "long" else high
