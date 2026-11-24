"""Utilidades de tiempo de sesión (America/New_York, DST incluido)."""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
from functools import lru_cache
from zoneinfo import ZoneInfo


@lru_cache(maxsize=8)
def zone(name: str) -> ZoneInfo:
    return ZoneInfo(name)


def local_dt(ts: int, tz_name: str = "America/New_York") -> datetime:
    return datetime.fromtimestamp(ts, tz=zone(tz_name))


def et_date(ts: int, tz_name: str = "America/New_York") -> date:
    return local_dt(ts, tz_name).date()


def et_date_str(ts: int, tz_name: str = "America/New_York") -> str:
    return et_date(ts, tz_name).isoformat()


def et_hm(ts: int, tz_name: str = "America/New_York") -> str:
    return local_dt(ts, tz_name).strftime("%H:%M")


def et_minutes(ts: int, tz_name: str = "America/New_York") -> int:
    d = local_dt(ts, tz_name)
    return d.hour * 60 + d.minute


def hm_to_minutes(hhmm: str) -> int:
    """'HH:MM' -> minutos desde medianoche."""
    h, m = (int(x) for x in hhmm.split(":"))
    return h * 60 + m


def next_weekday(day: date) -> date:
    """Siguiente día hábil (lunes a viernes)."""
    day += timedelta(days=1)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def timestamp_for(day: date, hhmm: str, tz_name: str = "America/New_York") -> int:
    h, m = (int(x) for x in hhmm.split(":"))
    dt = datetime.combine(day, dtime(h, m), tzinfo=zone(tz_name))
    return int(dt.timestamp())
