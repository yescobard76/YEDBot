"""Pruebas de los módulos críticos: ORB, SMT, riesgo y ejecución."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from server.config import SMTConfig, Settings
from server.execution import ExecutionEngine
from server.market.synthetic import build_session
from server.models import Bar, Signal
from server.risk import RiskManager
from server.strategy.indicators import aggregate
from server.strategy.orb import OpeningRange, build_opening_range
from server.strategy.smt import detect_divergence, find_pivots
from server.strategy.strategy import ORBStrategy
from server.timeutil import timestamp_for


def bar(ts: int, o: float, h: float, l: float, c: float, v: float = 100) -> Bar:
    return Bar(ts, o, h, l, c, v)


def session_bars(day: date, spec: dict[int, tuple[float, float, float, float]]) -> list[Bar]:
    bars = []
    for i in range(0, 200):
        ts = timestamp_for(day, "09:00") + i * 60
        o, h, l, c = spec.get(i, (100, 100.5, 99.5, 100))
        bars.append(bar(ts, o, h, l, c))
    return bars


def test_opening_range_freezes_and_computes_midpoint():
    settings = Settings()
    day = date(2025, 6, 3)
    bars = []
    for i in range(0, 70):
        ts = timestamp_for(day, "09:00") + i * 60
        hi = 20_850 if i == 10 else 20_840
        lo = 20_810 if i == 30 else 20_820
        bars.append(bar(ts, 20_830, hi, lo, 20_830))
    orb = build_opening_range(bars, settings.orb, 0.25)
    assert orb is not None
    assert orb.complete is True
    assert orb.high == 20_850
    assert orb.low == 20_810
    assert orb.mid == pytest.approx(20_830)
    assert orb.width == pytest.approx(40)


def test_opening_range_not_complete_inside_window():
    settings = Settings()
    day = date(2025, 6, 3)
    bars = [bar(timestamp_for(day, "09:00") + i * 60, 100, 101, 99, 100) for i in range(30)]
    orb = build_opening_range(bars, settings.orb, 0.25)
    assert orb is not None and orb.complete is False


def _divergence_bars():
    """NQ hace mínimo más bajo; ES mantiene el suyo (divergencia alcista)."""
    day = date(2025, 6, 3)
    nq, es = [], []
    for i in range(0, 80):
        ts = timestamp_for(day, "09:00") + i * 60
        nq_low = 99.0 if i == 20 else (96.0 if i == 40 else 100.0)
        es_low = 99.0 if i == 20 else (99.4 if i == 40 else 100.0)
        nq.append(bar(ts, 100.2, 100.6, nq_low, 100.3))
        es.append(bar(ts, 100.2, 100.6, es_low, 100.3))
    return nq, es


def test_pivots_require_confirmation():
    nq, _ = _divergence_bars()
    pivots = find_pivots(nq[:30], 2, "low")
    # El mínimo del índice 20 se confirma en el 22.
    assert any(p.index == 20 and p.confirmed_index == 22 for p in pivots)
    assert not any(p.index == 20 for p in find_pivots(nq[:21], 2, "low"))


def test_smt_bullish_detection_and_no_lookahead():
    nq, es = _divergence_bars()
    cfg = SMTConfig(pivot_depth=2, window_minutes=60, tolerance_ticks=8, min_break_ticks=1, validity_minutes=120)
    div = detect_divergence(nq, es, cfg, 0.25)
    assert div is not None
    assert div.bias == "bullish"
    assert div.level == pytest.approx(99.0)
    # Antes de confirmarse el pivote no puede existir divergencia.
    assert detect_divergence(nq[:41], es[:41], cfg, 0.25) is None


def test_smt_bearish_detection():
    day = date(2025, 6, 3)
    nq, es = [], []
    for i in range(80):
        ts = timestamp_for(day, "09:00") + i * 60
        nq_high = 101.0 if i == 20 else (104.0 if i == 40 else 100.0)
        es_high = 101.0 if i == 20 else (101.4 if i == 40 else 100.0)
        nq.append(bar(ts, 100, nq_high, 99.8, 100))
        es.append(bar(ts, 100, es_high, 99.8, 100))
    cfg = SMTConfig(pivot_depth=2, window_minutes=60, tolerance_ticks=8, min_break_ticks=1)
    div = detect_divergence(nq, es, cfg, 0.25)
    assert div is not None and div.bias == "bearish"


def test_position_sizing_uses_tick_value_and_caps():
    settings = Settings()
    risk = RiskManager(settings)
    sig = Signal(
        id="x", ts=0, direction="long", entry_price=20_000, stop=19_975, target=20_100,
        qty=0, risk_amount=0, signal_type="ORB", entry_reason="", reference_level=0, breakout_level=0,
    )
    qty, amount, err = risk.size(equity=25_000, stop_ticks=100)
    assert err == ""
    assert qty == 5  # 250 USD de riesgo / (100 ticks * 0.5 USD) = 5
    assert amount == pytest.approx(250)


def test_risk_blocks_daily_loss_and_max_trades():
    settings = Settings()
    risk = RiskManager(settings)
    sig = Signal(
        id="x", ts=0, direction="long", entry_price=20_000, stop=19_990, target=20_030,
        qty=0, risk_amount=0, signal_type="ORB", entry_reason="", reference_level=0, breakout_level=0,
    )
    now = timestamp_for(date(2025, 6, 3), "10:30")
    blocked = risk.evaluate(
        sig, equity=25_000, open_positions=0, day_pnl=-800, day_start_equity=25_000,
        trades_today=1, now_ts=now, last_exit_ts=None, consecutive_losses=0, has_pending_entry=False,
    )
    assert not blocked.ok and "pérdida diaria" in blocked.reason.lower()

    maxed = risk.evaluate(
        sig, equity=25_000, open_positions=0, day_pnl=0, day_start_equity=25_000,
        trades_today=3, now_ts=now, last_exit_ts=None, consecutive_losses=0, has_pending_entry=False,
    )
    assert not maxed.ok and "máximo de operaciones" in maxed.reason.lower()


def test_execution_bracket_and_take_profit():
    settings = Settings()
    engine = ExecutionEngine(settings)
    sig = Signal(
        id="s1", ts=1000, direction="long", entry_price=20_000, stop=19_990, target=20_030,
        qty=2, risk_amount=20, signal_type="ORB+SMT+Retest", entry_reason="test", reference_level=0, breakout_level=0,
    )
    engine.arm(sig)
    engine.on_bar(bar(1000, 20_000, 20_001, 19_999, 20_000))
    assert engine.position is not None
    assert engine.position.entry_price >= 20_000
    engine.on_bar(bar(1060, 20_010, 20_035, 20_005, 20_030))
    assert engine.position is None
    trade = engine.closed_trades[-1]
    assert trade.exit_reason == "take_profit"
    assert trade.pnl > 0


def test_execution_stop_wins_ambiguous_bar():
    settings = Settings()
    engine = ExecutionEngine(settings)
    sig = Signal(
        id="s2", ts=1000, direction="long", entry_price=20_000, stop=19_990, target=20_030,
        qty=1, risk_amount=10, signal_type="ORB", entry_reason="test", reference_level=0, breakout_level=0,
    )
    engine.arm(sig)
    engine.on_bar(bar(1000, 20_000, 20_000.5, 19_999.5, 20_000))
    engine.on_bar(bar(1060, 20_000, 20_040, 19_980, 20_010))
    trade = engine.closed_trades[-1]
    assert trade.exit_reason == "stop_loss"
    assert trade.pnl < 0


def test_strategy_produces_a_signal_only_after_opening_range():
    settings = Settings()
    day = date(2025, 6, 3)
    data = build_session(day, settings)
    nq, es = data["NQ"], data["ES"]
    strategy = ORBStrategy(settings)
    first_signal = None
    for i in range(3, len(nq)):
        assess = strategy.evaluate(nq[:i], es[:i], True)
        if assess.signal:
            first_signal = (nq[i - 1].ts, assess)
            break
    assert first_signal is not None, "La estrategia debe generar una señal en la sesión sintética"
    ts, assess = first_signal
    assert ts >= timestamp_for(day, "10:00"), "No puede haber señales antes de cerrar el Opening Range"
    assert assess.signal.stop < assess.signal.entry_price < assess.signal.target
    assert assess.phase("entry")["status"] == "confirmed"
    keys = [p["key"] for p in assess.phases]
    assert keys == ["session", "opening_range", "breakout", "smt", "retest", "entry", "management"]


def test_strategy_does_not_signal_before_or_close():
    settings = Settings()
    day = date(2025, 6, 3)
    data = build_session(day, settings)
    strategy = ORBStrategy(settings)
    nq, es = data["NQ"], data["ES"]
    for i in range(2, 60):
        assess = strategy.evaluate(nq[:i], es[:i], True)
        assert assess.signal is None


def test_or_retracement_reference_is_shallower_than_mid():
    settings = Settings(
        strategy={"entry_reference": "or_retracement", "or_retracement_pct": 0.382}
    )
    strategy = ORBStrategy(settings)
    orb = OpeningRange(
        date="2025-06-03",
        start_ts=0,
        end_ts=0,
        high=100.0,
        low=90.0,
        mid=95.0,
        width=10.0,
        width_pct=1.0,
        bars=60,
        complete=True,
    )
    breakout_long = {"direction": "long", "level": 100.0, "close": 101.0, "ts": 0}
    ref, name = strategy._reference(breakout_long, orb, [])
    assert ref == pytest.approx(96.18)
    assert ref > orb.mid
    assert "38.2%" in name

    breakout_short = {"direction": "short", "level": 90.0, "close": 89.0, "ts": 0}
    ref_short, _ = strategy._reference(breakout_short, orb, [])
    assert ref_short == pytest.approx(93.82)
    assert ref_short < orb.mid


def _first_signal(settings: Settings) -> Signal | None:
    day = date(2025, 6, 3)
    data = build_session(day, settings)
    strategy = ORBStrategy(settings)
    for i in range(3, len(data["NQ"])):
        assess = strategy.evaluate(data["NQ"][:i], data["ES"][:i], True)
        if assess.signal is not None:
            return assess.signal
    return None


def test_recovery_close_can_be_disabled_independently_of_entry_trigger():
    loose = _first_signal(
        Settings(strategy={"require_recovery_close": False, "entry_trigger": "close"})
    )
    loose_touch = _first_signal(
        Settings(strategy={"require_recovery_close": False, "entry_trigger": "touch"})
    )
    strict = _first_signal(
        Settings(strategy={"require_recovery_close": True, "entry_trigger": "close"})
    )
    assert loose is not None and loose_touch is not None and strict is not None
    assert loose.meta["require_recovery_close"] is False
    assert loose.meta["entry_reference"] == "or_mid"
    assert "sin exigir cierre de recuperación" in loose.entry_reason
    # Sin recuperación, la señal nace en la vela del toque y no depende del
    # disparador; con recuperación, espera a una vela posterior.
    assert loose.meta["trigger_ts"] == loose.meta["retest_ts"]
    assert loose_touch.ts == loose.ts
    assert strict.meta["trigger_ts"] > strict.meta["retest_ts"]
    assert loose.ts < strict.ts
    assert Settings().strategy.require_recovery_close is True


def _reference_orb() -> OpeningRange:
    return OpeningRange(
        date="2025-06-03",
        start_ts=0,
        end_ts=0,
        high=100.0,
        low=90.0,
        mid=95.0,
        width=10.0,
        width_pct=1.0,
        bars=60,
        complete=True,
    )


def test_retest_depth_defaults_to_mid_and_shallow_depth_is_opt_in():
    default = Settings()
    assert default.strategy.retest_depth == 1.0
    orb = _reference_orb()
    long = {"direction": "long", "level": 100.0, "close": 101.0, "ts": 0}
    short = {"direction": "short", "level": 90.0, "close": 89.0, "ts": 0}

    base = ORBStrategy(default)
    assert base._reference(long, orb, [])[0] == pytest.approx(orb.mid)
    assert base._reference(short, orb, [])[0] == pytest.approx(orb.mid)

    shallow = ORBStrategy(Settings(strategy={"retest_depth": 0.25}))
    assert shallow._reference(long, orb, [])[0] == pytest.approx(98.75)
    assert shallow._reference(short, orb, [])[0] == pytest.approx(91.25)

    edge = ORBStrategy(Settings(strategy={"retest_depth": 0.0}))
    assert edge._reference(long, orb, [])[0] == pytest.approx(orb.high)
    assert edge._reference(short, orb, [])[0] == pytest.approx(orb.low)

    with pytest.raises(ValidationError):
        Settings(strategy={"retest_depth": 1.01})
    with pytest.raises(ValidationError):
        Settings(strategy={"retest_depth": -0.01})


def test_retest_depth_one_does_not_change_the_signal():
    baseline = _first_signal(Settings())
    explicit = _first_signal(Settings(strategy={"retest_depth": 1.0}))
    assert baseline is not None and explicit is not None
    assert explicit.id == baseline.id
    assert explicit.ts == baseline.ts
    assert explicit.entry_price == baseline.entry_price
    assert explicit.stop == baseline.stop
    assert explicit.target == baseline.target


def test_confirmation_stop_is_available_but_not_active_by_default():
    assert Settings().strategy.sl_mode == "structural"
    assert Settings(strategy={"sl_mode": "confirmation"}).strategy.sl_mode == "confirmation"

    day = date(2025, 6, 3)
    bars = session_bars(day, {i: (100.0, 100.5, 96.0, 100.0) for i in range(200)})
    entry_ts = timestamp_for(day, "10:01")
    structural = ORBStrategy(Settings())._stop(
        100.0, "long", _reference_orb(), bars, entry_ts, 1.0, 15
    )
    confirmation = ORBStrategy(Settings(strategy={"sl_mode": "confirmation"}))._stop(
        100.0, "long", _reference_orb(), bars, entry_ts, 1.0, 15
    )
    assert structural is not None and confirmation is not None
    assert confirmation == pytest.approx(95.0)
    assert confirmation > structural


def test_event_metrics_are_annotated_on_the_first_signal():
    signal = _first_signal(Settings())
    assert signal is not None
    meta = signal.meta
    assert str(meta["event_id"]).startswith("2025-06-03-long-")
    assert meta["retest_distance_ticks"] > 0
    assert meta["direct_stop_ticks"] > 0
    assert meta["entry_delay_min"] >= 0
    assert meta["retest_depth"] == 1.0
    assert meta["sl_mode"] == "structural"
