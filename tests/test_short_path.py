"""Camino Short de extremo a extremo y deduplicación al reiniciar el replay."""

from __future__ import annotations

from datetime import date

import pytest

from server.config import Settings
from server.db import Store
from server.engine import TradingEngine
from server.market.feed import Tick
from server.market.synthetic import build_bearish_session, build_session
from server.models import Bar, Position
from server.strategy.strategy import ORBStrategy
from server.timeutil import timestamp_for


def _replay(engine: TradingEngine, day: date, data: dict[str, list]) -> None:
    """Reproduce una sesión completa por el mismo camino que usa el feed."""
    engine.status = "running"
    start_ts = timestamp_for(day, "09:00")
    bars = zip(data["NQ"], data["MNQ"], data["ES"])
    for nq, mnq, es in bars:
        if nq.ts < start_ts:
            continue
        engine._process(Tick(ts=nq.ts, bars={"NQ": nq, "MNQ": mnq, "ES": es}))


def _first_signal(day: date, data: dict[str, list], settings: Settings):
    strategy = ORBStrategy(settings)
    for i in range(3, len(data["NQ"])):
        assess = strategy.evaluate(data["NQ"][:i], data["ES"][:i], True)
        if assess.signal is not None:
            return assess.signal
    return None


def test_bearish_synthetic_session_trades_short(tmp_path):
    settings = Settings()
    day = date(2025, 6, 4)
    data = build_bearish_session(day, settings)

    # Determinista: la misma fecha produce exactamente las mismas velas.
    assert build_bearish_session(day, settings) == data

    # 1) La estrategia genera una señal Short de ruptura bajista con SMT bajista.
    signal = _first_signal(day, data, settings)
    assert signal is not None, "La sesión bajista debe generar una señal"
    assert signal.direction == "short"
    assert signal.signal_type == "ORB+SMT+Retest"
    assert signal.smt_bias == "bearish"
    assert signal.target < signal.entry_price < signal.stop
    assert signal.id.startswith(f"{day.isoformat()}-short-")

    # 2) El motor ejecuta esa misma señal y la registra como operación Short.
    store = Store(tmp_path / "short.db")
    try:
        engine = TradingEngine(store, settings)
        _replay(engine, day, data)

        trades = store.all_closed_trades()
        assert len(trades) == 1
        trade = trades[0]
        assert trade["direction"] == "short"
        assert trade["signal_id"] == signal.id
        assert trade["exit_reason"] in {"take_profit", "session_close"}
        assert engine.execution.position is None
        assert trade["target"] < trade["entry_price"] < trade["stop"]
    finally:
        store.close()


def test_replay_restart_does_not_duplicate_entries(tmp_path, monkeypatch):
    settings = Settings()
    day = date(2025, 6, 4)
    data = build_session(day, settings)
    db = tmp_path / "restart.db"
    # El estado solo se restaura si la sesión guardada coincide con "hoy".
    # Se fija la fecha para probar el reinicio de la misma sesión.
    monkeypatch.setattr("server.engine.et_date_str", lambda _: day.isoformat())

    store = Store(db)
    try:
        first = TradingEngine(store, settings)
        _replay(first, day, data)
        before = store.all_closed_trades()
        assert before, "La sesión alcista debe generar una operación"
        equity_before = first.equity
        day_before = (first.day_realized, first.trades_today, first.consecutive_losses)
        assert day_before[1] >= 1
        assert first.execution.last_exit_ts is not None
        assert first.execution.position is None
    finally:
        store.close()

    store = Store(db)
    try:
        second = TradingEngine(store, settings)
        # Los contadores se recuperan antes de la primera vela y no se
        # reinician al reanudar la misma sesión.
        assert (second.day_realized, second.trades_today, second.consecutive_losses) == day_before
        assert second.execution.last_exit_ts is not None
        _replay(second, day, data)
        after = store.all_closed_trades()

        assert len(after) == len(before)
        assert {t["signal_id"] for t in after} == {t["signal_id"] for t in before}
        assert second.equity == pytest.approx(equity_before)
        assert (second.day_realized, second.trades_today, second.consecutive_losses) == day_before
        assert second.execution.last_exit_ts is not None
    finally:
        store.close()


def test_new_session_does_not_close_position_when_replay_rewinds(tmp_path):
    settings = Settings()
    store = Store(tmp_path / "rewind.db")
    try:
        engine = TradingEngine(store, settings)
        day1 = date(2025, 6, 3)
        day2 = date(2025, 6, 4)
        engine.execution.position = Position(
            id="p1",
            symbol="MNQ",
            direction="long",
            qty=1,
            entry_price=100.0,
            entry_ts=timestamp_for(day2, "10:00"),
            stop=99.0,
            target=103.0,
            initial_stop=99.0,
            risk_amount=2.0,
            signal_id="s1",
            signal_type="ORB",
            entry_reason="test",
        )
        bar = Bar(ts=timestamp_for(day1, "09:00"), open=100.0, high=101.0, low=99.0, close=100.5, volume=1)

        engine._new_session(day1, bar)

        assert engine.execution.position is not None
        assert engine.execution.position.id == "p1"
        assert store.all_closed_trades() == []
    finally:
        store.close()
