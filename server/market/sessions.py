"""Calendario y validación de integridad de sesiones RTH.

La ventana operativa de la aplicación es 09:00–16:00 ET: incluye la hora
completa del Opening Range (09:00–10:00) y el cierre de sesión. Se exige una
vela de 1 minuto por cada minuto de esa ventana. Los datos premarket opcionales
(antes de las 09:00) no cuentan como parte de la sesión.

Los días con cierre anticipado oficial de CME para futuros de índices se
validan contra su hora de cierre real: 13:00 ET el 3 de julio y 13:15 ET el
viernes después de Thanksgiving y Nochebuena. Cualquier otro corte antes de las
16:00 ET sigue siendo un dataset truncado.

Un día hábil presente en el CSV debe estar completo. Un fin de semana o feriado
no debe traer barras; si las trae, el dataset se rechaza. Un día de cierre
anticipado omitido no se considera una sesión completa ausente.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache
from typing import Iterable

from ..timeutil import et_date, hm_to_minutes, local_dt, timestamp_for

SESSION_START = "09:00"
SESSION_END = "16:00"
OR_START = "09:00"
OR_END = "10:00"
OR_MINUTES = 60
EARLY_CLOSE_MIN_GAP = 30 * 60  # evita llamar "cierre" a un único minuto final ausente


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _easter(year: int) -> date:
    """Domingo de Pascua (algoritmo gregoriano anónimo)."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=16)
def market_holidays(year: int) -> frozenset[date]:
    """Feriados de mercado de EE. UU. relevantes para futuros de índices."""
    holidays = {
        _observed(date(year, 1, 1)),          # Año Nuevo
        _nth_weekday(year, 1, 0, 3),          # Martin Luther King
        _nth_weekday(year, 2, 0, 3),          # Presidents' Day
        _easter(year) - timedelta(days=2),    # Viernes Santo
        _last_weekday(year, 5, 0),            # Memorial Day
        _observed(date(year, 6, 19)),         # Juneteenth
        _observed(date(year, 7, 4)),          # Independencia
        _nth_weekday(year, 9, 0, 1),          # Labor Day
        _nth_weekday(year, 11, 3, 4),         # Thanksgiving
        _observed(date(year, 12, 25)),        # Navidad
    }
    return frozenset(holidays)


def is_market_holiday(day: date) -> bool:
    # El Año Nuevo observado puede caer el 31 de diciembre del año anterior.
    return day in market_holidays(day.year) or day in market_holidays(day.year + 1)


def is_trading_day(day: date) -> bool:
    return day.weekday() < 5 and not is_market_holiday(day)


@lru_cache(maxsize=2048)
def early_close_time(day: date) -> str | None:
    """Hora de cierre RTH de CME para índices en una sesión acortada.

    Solo aplica a días que el calendario considera hábiles. El 3 de julio
    cierra a las 13:00 ET; el viernes posterior a Thanksgiving y Nochebuena
    cierran a las 13:15 ET. La víspera de Año Nuevo conserva el cierre regular
    de las 16:00 ET y no se marca como cierre anticipado.
    """
    if not is_trading_day(day):
        return None
    if day.month == 7 and day.day == 3:
        return "13:00"
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    if day == thanksgiving + timedelta(days=1):
        return "13:15"
    if day.month == 12 and day.day == 24:
        return "13:15"
    return None


def _expected_stamps(day: date, start: str, end: str) -> list[int]:
    start_ts = timestamp_for(day, start)
    end_ts = timestamp_for(day, end)
    return list(range(start_ts, end_ts, 60))


def _fmt(ts: int | None) -> str | None:
    if ts is None:
        return None
    return local_dt(ts).strftime("%Y-%m-%d %H:%M")


def validate_sessions(
    stamps: Iterable[int],
    *,
    start: str = SESSION_START,
    end: str = SESSION_END,
) -> dict:
    """Valida que cada sesión presente sea un día hábil y esté completa.

    Los huecos entre sesiones (overnight, fin de semana) son normales. Un hueco
    dentro de la ventana, una sesión completa ausente, una sesión en día no
    hábil, un cierre anticipado no programado o un OR incompleto son errores: el
    dataset no debe llegar al replay ni al backtest. Los cierres anticipados
    oficiales de CME se validan contra su hora de cierre acortada. El premarket
    opcional se cuenta pero no sustituye ni completa la ventana RTH.
    """
    by_day: dict[date, set[int]] = {}
    for ts in stamps:
        by_day.setdefault(et_date(ts), set()).add(int(ts))

    errors: list[str] = []
    sessions_by_day: dict[date, dict] = {}
    expected_bars = hm_to_minutes(end) - hm_to_minutes(start)
    for day in sorted(by_day):
        actual = by_day[day]
        scheduled_close = early_close_time(day)
        session_end = end
        if scheduled_close is not None and hm_to_minutes(scheduled_close) < hm_to_minutes(end):
            session_end = scheduled_close
        scheduled_early_close = bool(
            scheduled_close is not None
            and hm_to_minutes(scheduled_close) <= hm_to_minutes(end)
        )
        expected = _expected_stamps(day, start, session_end)
        expected_set = set(expected)
        trading = is_trading_day(day)
        missing = sorted(expected_set - actual)
        extra = sorted(actual - expected_set)
        in_window = actual & expected_set
        or_expected = _expected_stamps(day, OR_START, OR_END)
        or_present = len(set(or_expected) & in_window)
        first_in_window = min(in_window) if in_window else None
        last_in_window = max(in_window) if in_window else None
        trailing_missing = bool(
            trading
            and in_window
            and missing
            and first_in_window == expected[0]
            and last_in_window < expected[-1]
            and all(ts > last_in_window for ts in missing)
        )
        unexpected_early_close = bool(
            trailing_missing
            and or_present == len(or_expected)
            and expected[-1] - last_in_window >= EARLY_CLOSE_MIN_GAP
        )
        session = {
            "date": day.isoformat(),
            "trading_day": trading,
            "bars_in_window": len(in_window),
            "expected_bars": len(expected),
            "expected_end": session_end,
            "regular_end": end,
            "missing_bars": len(missing),
            "first_missing": _fmt(missing[0]) if missing else None,
            "last_missing": _fmt(missing[-1]) if missing else None,
            "outside_window_bars": len(extra),
            "premarket_bars": sum(1 for ts in extra if ts < expected[0]),
            "afterhours_bars": sum(1 for ts in extra if ts >= expected[-1]),
            "or_bars": or_present,
            "or_expected_bars": len(or_expected),
            "or_complete": or_present == len(or_expected),
            "scheduled_early_close": scheduled_early_close,
            "truncated": trailing_missing,
            "early_close": scheduled_early_close or unexpected_early_close,
            "missing_session": False,
            "valid": False,
        }
        if not trading:
            if actual:
                errors.append(
                    f"Sesión {day.isoformat()} en día no hábil (fin de semana o feriado) con {len(actual)} velas"
                )
            session["valid"] = not actual
        elif missing or not session["or_complete"]:
            detail = []
            if missing:
                detail.append(
                    f"{len(missing)} velas faltantes ({session['first_missing']} → {session['last_missing']})"
                )
            if not session["or_complete"]:
                detail.append(f"OR incompleto ({or_present}/{len(or_expected)})")
            if not in_window:
                detail.append("sin velas RTH en la ventana (solo premarket o fuera de horario)")
            if scheduled_early_close:
                detail.append(f"cierre anticipado de CME programado a las {session_end}")
            elif unexpected_early_close:
                detail.append(
                    f"cierre anticipado no programado: última vela RTH {_fmt(last_in_window)} antes de {session_end}"
                )
            errors.append(f"Sesión {day.isoformat()} incompleta: " + "; ".join(detail))
        else:
            session["valid"] = True
        sessions_by_day[day] = session

    # Una sesión completa ausente entre dos sesiones presentes también invalida
    # el dataset. No se puede detectar mirando solo los días que aparecen en el
    # CSV, así que se recorre el calendario entre el primer y el último día.
    # Un cierre anticipado oficial omitido es opcional: no todas las fuentes
    # entregan esa media sesión, y su ausencia no debe bloquear el replay.
    skipped_early_close_sessions: list[str] = []
    if by_day:
        first_day, last_day = min(by_day), max(by_day)
        day = first_day
        while day <= last_day:
            if day not in by_day and is_trading_day(day):
                if early_close_time(day) is not None:
                    skipped_early_close_sessions.append(day.isoformat())
                    day += timedelta(days=1)
                    continue
                expected = _expected_stamps(day, start, end)
                sessions_by_day[day] = {
                    "date": day.isoformat(),
                    "trading_day": True,
                    "bars_in_window": 0,
                    "expected_bars": len(expected),
                    "expected_end": end,
                    "regular_end": end,
                    "missing_bars": len(expected),
                    "first_missing": _fmt(expected[0]),
                    "last_missing": _fmt(expected[-1]),
                    "outside_window_bars": 0,
                    "premarket_bars": 0,
                    "afterhours_bars": 0,
                    "or_bars": 0,
                    "or_expected_bars": len(_expected_stamps(day, OR_START, OR_END)),
                    "or_complete": False,
                    "scheduled_early_close": False,
                    "truncated": False,
                    "early_close": False,
                    "missing_session": True,
                    "valid": False,
                }
                errors.append(
                    f"Sesión {day.isoformat()} completa ausente: día hábil sin velas en el CSV"
                )
            day += timedelta(days=1)

    sessions = [sessions_by_day[day] for day in sorted(sessions_by_day)]
    if not by_day:
        errors.append("No hay velas para validar sesiones")
    missing_sessions = [session["date"] for session in sessions if session["missing_session"]]

    return {
        "ok": not errors,
        "expected_start": start,
        "expected_end": end,
        "expected_bars": expected_bars,
        "or_start": OR_START,
        "or_end": OR_END,
        "or_expected_bars": OR_MINUTES,
        "invalid_sessions": sum(1 for s in sessions if not s["valid"]),
        "missing_sessions": missing_sessions,
        "missing_session_count": len(missing_sessions),
        "early_close_sessions": [s["date"] for s in sessions if s["early_close"]],
        "scheduled_early_close_sessions": [
            s["date"] for s in sessions if s["scheduled_early_close"]
        ],
        "skipped_early_close_sessions": skipped_early_close_sessions,
        "premarket_bars": sum(int(s["premarket_bars"]) for s in sessions),
        "afterhours_bars": sum(int(s["afterhours_bars"]) for s in sessions),
        "sessions": sessions,
        "errors": errors,
    }
