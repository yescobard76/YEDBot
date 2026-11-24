"""Calendario de sesiones: fines de semana y feriados de mercado."""

from __future__ import annotations

from datetime import date

from server.config import Settings
from server.market.sessions import early_close_time, is_market_holiday, is_trading_day
from server.market.synthetic import build_session
from server.strategy.orb import build_opening_range
from server.timeutil import timestamp_for


def test_weekends_are_not_trading_days():
    assert not is_trading_day(date(2025, 6, 7))  # sábado
    assert not is_trading_day(date(2025, 6, 8))  # domingo
    assert is_trading_day(date(2025, 6, 9))      # lunes


def test_known_market_holidays_are_not_trading_days():
    assert is_market_holiday(date(2025, 1, 1))       # Año Nuevo
    assert is_market_holiday(date(2025, 4, 18))      # Viernes Santo
    assert is_market_holiday(date(2025, 7, 4))       # Independencia
    assert is_market_holiday(date(2025, 11, 27))     # Thanksgiving
    assert is_market_holiday(date(2025, 12, 25))     # Navidad
    assert not is_trading_day(date(2025, 7, 4))
    assert not is_trading_day(date(2025, 12, 25))


def test_adjacent_business_days_remain_trading_days():
    assert is_trading_day(date(2025, 7, 3))
    assert is_trading_day(date(2025, 11, 28))
    assert is_trading_day(date(2025, 12, 24))


def test_cme_early_close_calendar_uses_et_close_times():
    assert early_close_time(date(2025, 7, 3)) == "13:00"
    assert early_close_time(date(2025, 11, 28)) == "13:15"
    assert early_close_time(date(2025, 12, 24)) == "13:15"
    assert early_close_time(date(2026, 11, 27)) == "13:15"
    assert early_close_time(date(2026, 12, 24)) == "13:15"

    # Víspera de Año Nuevo y una sesión normal conservan el cierre de 16:00.
    assert early_close_time(date(2025, 12, 31)) is None
    assert early_close_time(date(2025, 6, 3)) is None
    # Un feriado no es una sesión acortada.
    assert early_close_time(date(2025, 11, 27)) is None
    assert early_close_time(date(2025, 12, 25)) is None


def test_opening_range_needs_all_60_minutes():
    settings = Settings()
    day = date(2025, 6, 3)
    bars = build_session(day, settings)["MNQ"]
    full = build_opening_range(bars, settings.orb)
    assert full is not None and full.complete and full.bars == 60

    missing = timestamp_for(day, "09:30")
    partial = [bar for bar in bars if bar.ts != missing]
    incomplete = build_opening_range(partial, settings.orb)
    assert incomplete is not None
    assert incomplete.bars == 59
    assert incomplete.complete is False
