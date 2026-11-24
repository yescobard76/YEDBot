"""Generador de sesiones sintéticas para replay y backtests de demostración.

IMPORTANTE: estos datos son SIMULADOS. Nunca se presentan como mercado real:
el snapshot incluye ``quality = "simulated"`` y la UI muestra una insignia
permanente. El generador es determinista por fecha, de modo que un replay y su
backtest asociado producen exactamente las mismas velas.
"""

from __future__ import annotations

import random
import time
from datetime import date

from ..config import Settings
from ..models import Bar
from ..timeutil import et_date, et_minutes, next_weekday, timestamp_for

SESSION_OPEN = 8 * 60 + 30
SESSION_CLOSE = 16 * 60
OR_START = 9 * 60
OR_END = 10 * 60


def _bar(o: float, h: float, l: float, c: float, ts: int, vol: float, tick: float) -> Bar:
    q = lambda v: round(round(v / tick) * tick, 2)  # noqa: E731
    o, c = q(o), q(c)
    return Bar(ts, o, q(max(h, o, c)), q(min(l, o, c)), c, float(round(vol)))


def _walk(
    price: float,
    o: float,
    drift: float,
    vol: float,
    shock: float,
    rng: random.Random,
) -> tuple[float, float, float]:
    high = low = price
    for step in range(4):
        price += drift / 4.0 + rng.gauss(0.0, vol / 2.0)
        if step == 3:
            price += shock
        high, low = max(high, price), min(low, price)
    return price, high, low


def _build_session(day: date, settings: Settings, direction: int) -> dict[str, list[Bar]]:
    """Genera 08:30–16:00 ET para MNQ, NQ y ES con un patrón ORB+SMT reproducible.

    ``direction`` es 1 para el patrón alcista y -1 para su espejo bajista. El
    generador es determinista por fecha y dirección; ambos caminos comparten
    exactamente la misma estructura y secuencia de aleatoriedad.
    """
    tick = settings.execution.tick_size
    day_seed = int(day.strftime("%Y%m%d"))
    seed = day_seed + (0xBEA5 if direction < 0 else 0)
    rng = random.Random(seed)
    base_nq = 20_800.0 + (day_seed % 11) * 13.0
    minutes = list(range(SESSION_OPEN, SESSION_CLOSE))
    stamps = [timestamp_for(day, f"{m // 60:02d}:{m % 60:02d}") for m in minutes]
    anchor = base_nq

    nq: list[Bar] = []
    price = base_nq - 6.0 * direction
    for idx, m in enumerate(minutes):
        if m == 9 * 60 + 19:
            drift, shock = 0.0, -10.0 * direction
        elif m == 9 * 60 + 46:
            drift, shock = 0.4 * direction, -19.0 * direction
        elif m < OR_START:
            drift, shock = -0.04 * direction, 0.0
        elif m < OR_END:
            drift, shock = 0.09 * (anchor - price), 0.0
        else:
            drift, shock = 0.0, 0.0
        o = price
        price, high, low = _walk(price, o, drift, 0.62, shock, rng)
        nq.append(_bar(o, high, low, price, stamps[idx], 900 + 700 * rng.random() + (1700 if shock else 0), tick))

    or_bars = [b for b in nq if 9 * 60 <= et_minutes(b.ts) < 10 * 60]
    orh = max(b.high for b in or_bars)
    orl = min(b.low for b in or_bars)
    mid = (orh + orl) / 2

    # Continuación post-OR: ruptura, retroceso al 50% y expansión.
    price = next(b.close for b in nq if et_minutes(b.ts) == OR_END - 1)
    for bar in nq:
        m = et_minutes(bar.ts)
        if m < OR_END:
            continue
        if m < 10 * 60 + 14:
            drift = 0.3 * direction
        elif m < 10 * 60 + 30:
            drift = 1.15 * direction
        elif m < 10 * 60 + 46:
            drift = 0.25 * (mid - price)
        elif m < 11 * 60 + 40:
            drift = 0.55 * direction
        elif m < 13 * 60:
            drift = 0.04 * direction
        else:
            drift = -0.02 * direction
        o = price
        shock = 1.2 * direction if m == 10 * 60 + 31 else 0.0
        price, high, low = _walk(price, o, drift, 0.6, shock, rng)
        vol = 800 + 800 * rng.random() + (900 if 10 * 60 <= m < 11 * 60 else 0)
        rebuilt = _bar(o, high, low, price, bar.ts, vol, tick)
        bar.open, bar.high, bar.low, bar.close, bar.volume = (
            rebuilt.open,
            rebuilt.high,
            rebuilt.low,
            rebuilt.close,
            rebuilt.volume,
        )

    # ES: misma estructura y shocks más suaves. En el camino alcista, el barrido
    # de mínimo de NQ no lo confirma ES (SMT alcista); en el bajista ocurre lo
    # simétrico con el máximo.
    base_es = 5_700.0 + (seed % 13) * 4.0
    es_anchor = base_es
    es: list[Bar] = []
    es_price = base_es
    for idx, m in enumerate(minutes):
        if m == 9 * 60 + 19:
            drift, shock = 0.0, -5.0 * direction
        elif m == 9 * 60 + 46:
            drift, shock = 0.05 * direction, -0.75 * direction
        elif m < OR_START:
            drift, shock = -0.01 * direction, 0.0
        elif m < OR_END:
            drift, shock = 0.09 * (es_anchor - es_price), 0.0
        else:
            drift, shock = 0.0, 0.0
        o = es_price
        es_price, high, low = _walk(es_price, o, drift, 0.18, shock, rng)
        es.append(_bar(o, high, low, es_price, stamps[idx], 700 + 600 * rng.random(), tick))

    # ES sigue la tendencia de NQ después del OR, con beta reducida.
    nq_map = {b.ts: b for b in nq}
    for bar in es:
        if et_minutes(bar.ts) < OR_END:
            continue
        ref = nq_map[bar.ts]
        target = base_es + (ref.close - anchor) * 0.22
        bar.open, bar.high, bar.low, bar.close = (
            round(round((bar.open + (target - bar.close) * 0.5) / tick) * tick, 2),
            round(round((bar.high + (target - bar.close) * 0.5) / tick) * tick, 2),
            round(round((bar.low + (target - bar.close) * 0.5) / tick) * tick, 2),
            round(round(target / tick) * tick, 2),
        )
        bar.high = max(bar.high, bar.open, bar.close)
        bar.low = min(bar.low, bar.open, bar.close)

    mnq = [
        Bar(b.ts, round(b.open - 2.75, 2), round(b.high - 2.75, 2), round(b.low - 2.75, 2), round(b.close - 2.75, 2), b.volume)
        for b in nq
    ]
    return {"MNQ": mnq, "NQ": nq, "ES": es}


def build_session(day: date, settings: Settings) -> dict[str, list[Bar]]:
    """Genera 08:30–16:00 ET para MNQ, NQ y ES con un patrón ORB+SMT alcista."""
    return _build_session(day, settings, 1)


def build_bearish_session(day: date, settings: Settings) -> dict[str, list[Bar]]:
    """Espejo bajista de ``build_session``.

    NQ barre un máximo superior que ES no confirma (divergencia SMT bajista),
    rompe el ORL, retestea el 50% del rango desde abajo y expande a la baja.
    Sirve para ejercitar el camino Short de la estrategia sin datos reales.
    """
    return _build_session(day, settings, -1)


def build_days(
    settings: Settings, count: int = 60, start: date | None = None
) -> list[tuple[date, dict[str, list[Bar]]]]:
    """Genera ``count`` sesiones hábiles consecutivas (deterministas)."""
    if start is None:
        start = et_date(int(time.time()))
    days: list[tuple[date, dict[str, list[Bar]]]] = []
    day = start
    while len(days) < count:
        if day.weekday() < 5:
            days.append((day, build_session(day, settings)))
        day = next_weekday(day)
    return days
