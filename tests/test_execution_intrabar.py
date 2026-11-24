"""Modelo intrabar y auditoría de velas ambiguas."""

from __future__ import annotations

from server.config import Settings
from server.db import Store
from server.execution import ExecutionEngine
from server.models import Bar, Signal
from server.stats import compute_stats


def bar(ts: int, o: float, h: float, l: float, c: float, v: float = 100) -> Bar:
    return Bar(ts, o, h, l, c, v)


def signal(direction: str = "long", *, stop: float = 19_990, target: float = 20_030) -> Signal:
    return Signal(
        id="s1",
        ts=1000,
        direction=direction,  # type: ignore[arg-type]
        entry_price=20_000,
        stop=stop,
        target=target,
        qty=1,
        risk_amount=10,
        signal_type="ORB",
        entry_reason="test",
        reference_level=0,
        breakout_level=0,
    )


def engine_with(settings: Settings) -> ExecutionEngine:
    return ExecutionEngine(settings)


def fill(engine: ExecutionEngine, *, direction: str = "long", stop: float = 19_990, target: float = 20_030) -> None:
    engine.arm(signal(direction, stop=stop, target=target))
    engine.on_bar(bar(1000, 20_000, 20_000.5, 19_999.5, 20_000))


def test_stop_with_gap_fills_at_open_not_at_stop():
    settings = Settings()
    settings.execution.slippage_ticks = 1
    settings.execution.max_slippage_ticks = 4
    engine = engine_with(settings)
    fill(engine)

    engine.on_bar(bar(1060, 19_980, 19_985, 19_975, 19_980))

    trade = engine.closed_trades[-1]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == 19_979.75  # open 19_980 - 1 tick de slippage
    assert trade.meta["gap_stop"] is True
    assert engine.ambiguous_count == 0


def test_short_stop_with_gap_fills_at_open():
    settings = Settings()
    settings.execution.slippage_ticks = 1
    engine = engine_with(settings)
    fill(engine, direction="short", stop=20_010, target=19_970)

    engine.on_bar(bar(1060, 20_020, 20_025, 20_015, 20_020))

    trade = engine.closed_trades[-1]
    assert trade.exit_reason == "stop_loss"
    assert trade.exit_price == 20_020.25  # open 20_020 + 1 tick
    assert trade.meta["gap_stop"] is True


def test_target_applies_adverse_slippage():
    settings = Settings()
    settings.execution.slippage_ticks = 1
    engine = engine_with(settings)
    fill(engine)

    engine.on_bar(bar(1060, 20_010, 20_035, 20_005, 20_030))

    trade = engine.closed_trades[-1]
    assert trade.exit_reason == "take_profit"
    assert trade.exit_price == 20_029.75
    assert trade.exit_price < trade.target


def test_max_slippage_ticks_caps_configured_slippage():
    settings = Settings()
    settings.execution.slippage_ticks = 6
    settings.execution.max_slippage_ticks = 2
    engine = engine_with(settings)
    fill(engine)

    engine.on_bar(bar(1060, 20_010, 20_035, 20_005, 20_030))

    trade = engine.closed_trades[-1]
    assert trade.exit_reason == "take_profit"
    assert trade.exit_price == 20_029.50  # 2 ticks, no 6


def test_ambiguous_bar_is_reported_and_stop_wins():
    settings = Settings()
    settings.execution.slippage_ticks = 1
    engine = engine_with(settings)
    fill(engine)

    engine.on_bar(bar(1060, 20_000, 20_040, 19_980, 20_010))

    trade = engine.closed_trades[-1]
    report = engine.ambiguous_report()
    assert trade.exit_reason == "stop_loss"
    assert trade.meta["ambiguous_bar"] is True
    assert report["count"] == 1
    item = report["items"][0]
    assert item["ts"] == 1060
    assert item["direction"] == "long"
    assert item["resolution"] == "stop_loss_first"
    assert item["gap_stop"] is False
    assert item["trade_id"] == trade.id
    assert item["exit_price"] == trade.exit_price


def test_ambiguous_gap_bar_records_gap_and_open_exit():
    settings = Settings()
    settings.execution.slippage_ticks = 1
    engine = engine_with(settings)
    fill(engine)

    engine.on_bar(bar(1060, 19_980, 20_040, 19_975, 20_010))

    trade = engine.closed_trades[-1]
    item = engine.ambiguous_report()["items"][0]
    assert trade.exit_price == 19_979.75
    assert item["gap_stop"] is True
    assert item["resolution"] == "stop_loss_first"


def test_mfe_mae_and_open_drawdown_are_recorded():
    settings = Settings()
    settings.execution.slippage_ticks = 0
    settings.execution.commission_per_contract_side = 0
    engine = engine_with(settings)
    fill(engine)

    # Primera vela: +25 puntos de MFE, -5 de MAE y 60 USD de drawdown abierto.
    engine.on_bar(bar(1060, 20_001, 20_025, 19_995, 20_020))
    assert engine.position is not None
    assert engine.position.mfe_r == 2.5
    assert engine.position.mae_r == -0.5
    assert engine.position.open_drawdown == 60.0

    engine.on_bar(bar(1120, 20_020, 20_035, 20_015, 20_030))
    trade = engine.closed_trades[-1]
    assert trade.exit_reason == "take_profit"
    assert trade.mfe_r == 3.5
    assert trade.mae_r == -0.5
    assert trade.mfe_usd == 70.0
    assert trade.mae_usd == -10.0
    assert trade.open_drawdown == 60.0

    stats = compute_stats([trade.as_dict()], settings.risk.initial_capital)
    assert stats["avg_mfe_r"] == 3.5
    assert stats["avg_mae_r"] == -0.5
    assert stats["avg_open_drawdown"] == 60.0
    assert stats["max_open_drawdown"] == 60.0


def test_trade_excursions_survive_sqlite_roundtrip(tmp_path):
    settings = Settings()
    settings.execution.slippage_ticks = 0
    settings.execution.commission_per_contract_side = 0
    engine = engine_with(settings)
    fill(engine)
    engine.on_bar(bar(1060, 20_001, 20_025, 19_995, 20_020))
    engine.on_bar(bar(1120, 20_020, 20_035, 20_015, 20_030))
    trade = engine.closed_trades[-1]

    store = Store(tmp_path / "metrics.db")
    try:
        store.insert_trade(trade.as_dict())
        loaded = store.all_closed_trades()[0]
    finally:
        store.close()
    assert loaded["mfe_r"] == 3.5
    assert loaded["mae_r"] == -0.5
    assert loaded["open_drawdown"] == 60.0
