"""Fase A — Opening Range."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import ORBConfig
from ..models import Bar
from ..timeutil import et_date, timestamp_for


@dataclass(slots=True)
class OpeningRange:
    date: str
    start_ts: int
    end_ts: int
    high: float
    low: float
    mid: float
    width: float
    width_pct: float
    bars: int
    complete: bool

    def as_dict(self) -> dict:
        return {
            "date": self.date,
            "start_ts": self.start_ts,
            "end_ts": self.end_ts,
            "high": round(self.high, 2),
            "low": round(self.low, 2),
            "mid": round(self.mid, 2),
            "width": round(self.width, 2),
            "width_pct": round(self.width_pct, 3),
            "bars": self.bars,
            "complete": self.complete,
        }


def build_opening_range(bars: list[Bar], cfg: ORBConfig, tick_size: float = 0.25) -> OpeningRange | None:
    """Calcula el OR de la sesión a la que pertenece la última vela.

    El rango se congela cuando llega la primera vela con ``ts >= end``.
    Solo se usan velas cuyo inicio está dentro de la ventana, nunca posteriores.
    """
    if not bars:
        return None
    day = et_date(bars[-1].ts, cfg.timezone)
    start_ts = timestamp_for(day, cfg.start, cfg.timezone)
    end_ts = timestamp_for(day, cfg.end, cfg.timezone)
    window = [b for b in bars if start_ts <= b.ts < end_ts]
    if not window:
        return None
    high = max(b.high for b in window)
    low = min(b.low for b in window)
    close = window[-1].close
    expected_bars = int((end_ts - start_ts) // 60)
    complete = bars[-1].ts >= end_ts and len(window) == expected_bars
    # Redondeo al tick del instrumento para que los niveles sean operables.
    high = round(round(high / tick_size) * tick_size, 4)
    low = round(round(low / tick_size) * tick_size, 4)
    width = max(high - low, 0.0)
    return OpeningRange(
        date=day.isoformat(),
        start_ts=start_ts,
        end_ts=end_ts,
        high=high,
        low=low,
        mid=round((high + low) / 2, 4),
        width=round(width, 4),
        width_pct=round(width / close * 100, 3) if close else 0.0,
        bars=len(window),
        complete=complete,
    )
