"""Filtro de geometría mínima stop/ORB.

La regla rechaza una entrada cuando el stop estructural es menor que una
fracción del ancho del Opening Range. Es opt-in: con el valor por defecto 0.0
no cambia ninguna decisión ni el comportamiento histórico.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from pathlib import Path

from server.backtest import run_backtest
from server.config import RiskConfig, Settings
from server.db import Store
from server.engine import TradingEngine
from server.market.feed import Tick
from server.models import Signal
from server.risk import RiskManager
from server.strategy.strategy import Assess, ORBStrategy
from server.timeutil import et_date, et_hm, timestamp_for

DAY = date(2025, 6, 3)


def _signal(
    signal_id: str = "stop-or",
    *,
    stop_points: float = 25.0,
    orb_high: float | None = 20_050.0,
    orb_low: float | None = 19_950.0,
) -> Signal:
    meta: dict[str, float] = {}
    if orb_high is not None:
        meta["orb_high"] = orb_high
    if orb_low is not None:
        meta["orb_low"] = orb_low
    return Signal(
        id=signal_id,
        ts=0,
        direction="long",
        entry_price=20_000.0,
        stop=20_000.0 - stop_points,
        target=20_000.0 + 3 * stop_points,
        qty=0,
        risk_amount=0,
        signal_type="ORB",
        entry_reason="test",
        reference_level=0,
        breakout_level=0,
        meta=meta,
    )


def _risk(**risk: object) -> RiskManager:
    return RiskManager(Settings(risk={"cooldown_minutes": 0, **risk}))


def _evaluate(
    risk: RiskManager,
    signal: Signal,
    hhmm: str = "14:00",
    *,
    trades_today: int = 0,
):
    return risk.evaluate(
        signal,
        equity=25_000,
        open_positions=0,
        day_pnl=0,
        day_start_equity=25_000,
        trades_today=trades_today,
        now_ts=timestamp_for(DAY, hhmm),
        last_exit_ts=None,
        consecutive_losses=0,
        has_pending_entry=False,
    )


def test_min_stop_or_ratio_is_disabled_by_default_and_legacy_configs_load() -> None:
    assert RiskConfig().min_stop_or_ratio == 0.0
    settings = Settings()
    assert settings.risk.min_stop_or_ratio == 0.0

    legacy = settings.model_dump()
    legacy["risk"].pop("min_stop_or_ratio")
    restored = Settings.model_validate(legacy)
    assert restored.risk.min_stop_or_ratio == 0.0


def test_disabled_filter_allows_narrow_stops_and_missing_orb() -> None:
    risk = _risk()
    # 20 ticks sobre un ORB de 400 ticks: 0.05, muy por debajo de 0.25.
    assert _evaluate(risk, _signal(stop_points=5.0)).ok
    assert _evaluate(risk, _signal(orb_high=None, orb_low=None)).ok


def test_rejects_below_boundary_and_accepts_at_or_above_it() -> None:
    risk = _risk(min_stop_or_ratio=0.25)

    # ORB de 100 puntos = 400 ticks. 24.9 puntos = 99.6 ticks => 0.249.
    below = _evaluate(risk, _signal(stop_points=24.9))
    assert not below.ok
    assert "stop/ORB" in below.reason

    # La frontera es inclusiva: 25 puntos = 100 ticks => exactamente 0.250.
    assert _evaluate(risk, _signal(stop_points=25.0)).ok
    assert _evaluate(risk, _signal(stop_points=30.0)).ok


def test_active_filter_fails_closed_without_a_valid_orb_width() -> None:
    risk = _risk(min_stop_or_ratio=0.25)

    missing = _evaluate(risk, _signal(orb_high=None, orb_low=None))
    assert not missing.ok
    assert "stop/ORB" in missing.reason

    zero_width = _evaluate(risk, _signal(orb_high=20_000.0, orb_low=20_000.0))
    assert not zero_width.ok
    assert "stop/ORB" in zero_width.reason

    inverted = _evaluate(risk, _signal(orb_high=19_950.0, orb_low=20_050.0))
    assert not inverted.ok
    assert "stop/ORB" in inverted.reason


def test_daily_quota_and_exclusion_take_priority_over_stop_or_ratio() -> None:
    settings = Settings(
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
            "max_trades_per_day": 1,
            "min_stop_or_ratio": 0.25,
            "cooldown_minutes": 0,
        }
    )
    risk = RiskManager(settings)
    narrow = _signal(stop_points=10.0)

    quota = _evaluate(risk, narrow, "11:30", trades_today=1)
    assert not quota.ok
    assert "Máximo de operaciones diarias" in quota.reason
    assert "exclusión" not in quota.reason.lower()
    assert "stop/ORB" not in quota.reason

    excluded = _evaluate(risk, narrow, "11:30", trades_today=0)
    assert not excluded.ok
    assert "exclusión" in excluded.reason.lower()
    assert "stop/ORB" not in excluded.reason

    filtered = _evaluate(risk, narrow, "14:00", trades_today=0)
    assert not filtered.ok
    assert "stop/ORB" in filtered.reason


def _write_parity_csv(path: Path, days: list[date]) -> Path:
    """Tres sesiones RTH; la primera contiene el TP que cierra la entrada buena."""
    rows = ["timestamp,symbol,open,high,low,close,volume"]
    for day in days:
        start = timestamp_for(day, "09:00")
        for index in range(420):
            ts = start + index * 60
            hhmm = et_hm(ts)
            open_, high, low, close = 20_000.0, 20_000.5, 19_999.5, 20_000.0
            if day == days[0] and hhmm == "10:25":
                # Target de 20075 para la entrada de 10:20.
                open_, high, low, close = 20_000.0, 20_080.0, 19_999.5, 20_030.0
            rows.append(f"{ts},MNQ,{open_},{high},{low},{close},100")
            rows.append(f"{ts},NQ,{open_ + 3},{high + 3},{low + 3},{close + 3},100")
            rows.append(f"{ts},ES,5730,5731,5729,5730,100")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _parity_settings(path: Path) -> Settings:
    settings = Settings(
        risk={
            "min_stop_or_ratio": 0.25,
            "cooldown_minutes": 0,
            "max_trades_per_day": 10,
        }
    )
    settings.feed.provider = "csv"
    settings.feed.csv_path = str(path)
    settings.feed.start_date = DAY.isoformat()
    settings.feed.loop_sessions = False
    return settings


def _drive_engine(engine: TradingEngine, until: date | None = None) -> int:
    assert engine.feed is not None
    processed = 0
    for tick_bars in engine.feed.dataset.bars:
        ts = tick_bars["NQ"].ts
        if until is not None and et_date(ts) > until:
            break
        engine._process(Tick(ts=ts, bars=tick_bars))
        processed += 1
    return processed


def _trade_signature(trade: dict) -> tuple:
    return (
        trade["meta"]["signal_id"],
        trade["direction"],
        trade["qty"],
        trade["entry_ts"],
        trade["entry_price"],
        trade["exit_ts"],
        trade["exit_price"],
        trade["exit_reason"],
        trade["pnl"],
    )


def test_paper_and_backtest_match_with_min_stop_or_ratio_active(
    monkeypatch, tmp_path: Path
) -> None:
    days = [date(2025, 6, 3), date(2025, 6, 4), date(2025, 6, 5)]
    path = _write_parity_csv(tmp_path / "stop-or-parity.csv", days)
    schedule = {
        days[0]: {
            "10:20": ("ratio-at-threshold", 25.0),
            "10:30": ("ratio-below-threshold", 24.9),
            "10:40": ("ratio-above-threshold", 30.0),
        },
        days[1]: {
            "10:30": ("ratio-below-threshold-day2", 24.9),
        },
    }

    def fake_evaluate(self, nq, es, trade_window_open):
        timezone = self.settings.orb.timezone
        day = et_date(nq[-1].ts, timezone)
        hhmm = et_hm(nq[-1].ts, timezone)
        entry = schedule.get(day, {}).get(hhmm)
        if entry is None:
            return Assess()
        signal_id, stop_points = entry
        signal = _signal(signal_id, stop_points=stop_points)
        signal.ts = nq[-1].ts + 60
        return Assess(signal=signal)

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    settings = _parity_settings(path)

    backtest = run_backtest(settings, days=3, start=DAY, label="stop-or-parity")
    store = Store(tmp_path / "stop-or-parity.db")
    try:
        engine = TradingEngine(store, settings)
        engine.status = "running"
        # Se detiene al cerrar el día 2: ``_rejected`` se limpia al iniciar la
        # sesión siguiente, así que el rechazo se captura antes del día 3.
        assert _drive_engine(engine, until=days[1]) == 2 * 420
        paper = [asdict(trade) for trade in engine.execution.closed_trades]
        rejected = set(engine._rejected)
    finally:
        store.close()

    expected = ["ratio-at-threshold", "ratio-above-threshold"]
    assert [trade["meta"]["signal_id"] for trade in backtest["trades"]] == expected
    assert [trade["meta"]["signal_id"] for trade in paper] == expected
    assert "ratio-below-threshold" not in {
        trade["meta"]["signal_id"] for trade in backtest["trades"]
    }
    assert "ratio-below-threshold-day2" in rejected
    assert [_trade_signature(trade) for trade in paper] == [
        _trade_signature(trade) for trade in backtest["trades"]
    ]

    # El backtest deja constancia del motivo exacto en el embudo de la sesión
    # donde la única señal fue rechazada por geometría.
    record = next(
        row for row in backtest["funnel"]["sessions"] if row["date"] == days[1].isoformat()
    )
    assert "stop/ORB" in (record.get("risk") or {}).get("reason", "")
