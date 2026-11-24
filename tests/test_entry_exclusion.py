"""Ventana opcional de exclusión de entradas."""

from __future__ import annotations

import csv
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

import server.backtest as bt
from server.backtest import run_backtest
from server.config import RiskConfig, Settings
from server.db import Store
from server.engine import TradingEngine
from server.execution import ExecutionEngine
from server.market.feed import Tick
from server.models import Bar, Signal
from server.risk import RiskManager
from server.strategy.strategy import Assess, ORBStrategy
from server.timeutil import (
    et_date,
    et_hm,
    et_minutes,
    hm_to_minutes,
    local_dt,
    timestamp_for,
)

ROOT = Path(__file__).resolve().parents[1]
REAL_CSV = ROOT / "tests" / "fixtures" / "bars_mnq_nq_es_1m_3sessions.csv"
ROLL_DAY = "2025-12-24"
ROLL_SHIFT = -10.0


def _sim_dataset(day: date, bars: list[Bar]) -> dict:
    selected_range = {
        "first_ts": bars[0].ts,
        "last_ts": bars[-1].ts,
        "first_et": f"{day.isoformat()} {et_hm(bars[0].ts)}",
        "last_et": f"{day.isoformat()} {et_hm(bars[-1].ts)}",
    }
    return {
        "id": f"entry-exclusion-{day.isoformat()}",
        "series_id": f"entry-exclusion-{day.isoformat()}",
        "selected_id": f"entry-exclusion-{day.isoformat()}",
        "kind": "synthetic",
        "source": "synthetic",
        "data_source": "synthetic",
        "generator": "build_session",
        "generator_version": "1",
        "schema_version": "synthetic-v1",
        "sessions": {"count": 1, "available": 1, "excluded": 0, "dates": [day.isoformat()]},
        "selected_range": selected_range,
        "range": selected_range,
        "all_sessions": [day.isoformat()],
        "contracts": {},
        "contracts_by_session": {},
        "expiry_by_session": {},
        "roll_sessions": [],
        "excluded_sessions": [],
        "manifest": {},
    }


def _sweep_minutes(start: str, end: str) -> list[str]:
    return [
        f"{minute // 60:02d}:{minute % 60:02d}"
        for minute in range(hm_to_minutes(start), hm_to_minutes(end) + 1)
    ]


# Minutos del horario operativo; fuera de un cambio de hora en las zonas usadas.
_OPERATIONAL_MINUTES = _sweep_minutes("09:00", "15:30")


def _signal(signal_id: str = "exclusion") -> Signal:
    return Signal(
        id=signal_id,
        ts=0,
        direction="long",
        entry_price=20_000,
        stop=19_990,
        target=20_030,
        qty=0,
        risk_amount=0,
        signal_type="ORB",
        entry_reason="test",
        reference_level=0,
        breakout_level=0,
    )


def _risk(
    start: str = "",
    end: str = "",
    timezone: str = "America/New_York",
) -> RiskManager:
    return RiskManager(
        Settings(
            orb={"timezone": timezone},
            risk={
                "entry_exclusion_start": start,
                "entry_exclusion_end": end,
            },
        )
    )


def _evaluate(
    risk: RiskManager,
    hhmm: str,
    day: date = date(2025, 6, 3),
    tz_name: str | None = None,
    trades_today: int = 0,
):
    timezone = tz_name or risk.settings.orb.timezone
    return risk.evaluate(
        _signal(),
        equity=25_000,
        open_positions=0,
        day_pnl=0,
        day_start_equity=25_000,
        trades_today=trades_today,
        now_ts=timestamp_for(day, hhmm, timezone),
        last_exit_ts=None,
        consecutive_losses=0,
        has_pending_entry=False,
    )


def test_entry_exclusion_is_empty_by_default_and_legacy_configs_load() -> None:
    settings = Settings()
    assert settings.risk.entry_exclusion_start == ""
    assert settings.risk.entry_exclusion_end == ""

    legacy = settings.model_dump()
    legacy["risk"].pop("entry_exclusion_start")
    legacy["risk"].pop("entry_exclusion_end")
    restored = Settings.model_validate(legacy)
    assert restored.risk.entry_exclusion_start == ""
    assert restored.risk.entry_exclusion_end == ""


def test_entry_exclusion_normalizes_times_and_rejects_incomplete_pairs() -> None:
    config = RiskConfig(
        entry_exclusion_start="9:05",
        entry_exclusion_end=" 10:07 ",
    )
    assert config.entry_exclusion_start == "09:05"
    assert config.entry_exclusion_end == "10:07"

    for start, end in (
        ("10:00", ""),
        ("", "10:00"),
        ("10:00", "10:00"),
        ("11:00", "10:00"),
        ("24:00", "25:00"),
        ("9", "10:00"),
    ):
        with pytest.raises(ValidationError):
            RiskConfig(entry_exclusion_start=start, entry_exclusion_end=end)


def test_entry_exclusion_blocks_only_the_configured_half_open_window() -> None:
    risk = _risk("10:00", "11:00")

    assert _evaluate(risk, "09:59").ok
    blocked = _evaluate(risk, "10:00")
    assert not blocked.ok
    assert "exclusión" in blocked.reason.lower()
    assert not _evaluate(risk, "10:59").ok
    # El fin es exclusivo: a las 11:00:00 ya se permiten entradas nuevas.
    assert _evaluate(risk, "11:00").ok


def test_entry_exclusion_1100_1300_blocks_until_1259_and_reopens_at_1300() -> None:
    risk = _risk("11:00", "13:00")

    assert _evaluate(risk, "10:59").ok
    assert not _evaluate(risk, "11:00").ok
    assert not _evaluate(risk, "12:59").ok
    assert _evaluate(risk, "13:00").ok


def test_daily_trade_limit_is_checked_before_the_exclusion_window() -> None:
    """Con el cupo agotado manda el cupo: la reapertura de las 13:00 no lo repone."""
    settings = Settings(
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
            "max_trades_per_day": 1,
            "cooldown_minutes": 0,
        }
    )
    risk = RiskManager(settings)
    day = date(2025, 6, 3)

    for hhmm in ("11:00", "12:59", "13:00"):
        decision = _evaluate(risk, hhmm, day=day, trades_today=1)
        assert not decision.ok
        assert decision.reason == "Máximo de operaciones diarias alcanzado (1)"
        assert "exclusión" not in decision.reason.lower()

    # Sin el cupo agotado, la ventana sigue siendo la que decide: 12:59 está
    # excluida y 13:00 permite una entrada nueva.
    inside = _evaluate(risk, "12:59", day=day)
    assert not inside.ok
    assert "exclusión" in inside.reason.lower()
    assert _evaluate(risk, "13:00", day=day).ok


@pytest.mark.parametrize(
    ("exclusion_start", "exclusion_end"),
    [("09:05", "10:07"), ("11:00", "13:00")],
)
@pytest.mark.parametrize("day", [date(2025, 6, 3), date(2025, 3, 9), date(2025, 11, 2)])
@pytest.mark.parametrize(
    "tz_name",
    ["America/New_York", "America/Los_Angeles", "Europe/Madrid", "Asia/Tokyo"],
)
def test_entry_exclusion_agrees_between_risk_and_execution_at_every_minute(
    exclusion_start: str, exclusion_end: str, day: date, tz_name: str
) -> None:
    """Las dos copias de la ventana no pueden divergir en ningún minuto operativo."""
    settings = Settings(
        orb={"timezone": tz_name},
        risk={
            "entry_exclusion_start": exclusion_start,
            "entry_exclusion_end": exclusion_end,
        },
    )
    risk = RiskManager(settings)
    execution = ExecutionEngine(settings)
    start = hm_to_minutes(exclusion_start)
    end = hm_to_minutes(exclusion_end)

    for hhmm in _OPERATIONAL_MINUTES:
        ts = timestamp_for(day, hhmm, tz_name)
        # El barrido no cruza el salto de hora en estas fechas y zonas.
        assert et_hm(ts, tz_name) == hhmm
        expected = start <= hm_to_minutes(hhmm) < end

        assert execution._entry_excluded(ts) is expected, f"{day} {tz_name} {hhmm}"

        decision = risk.evaluate(
            _signal(),
            equity=25_000,
            open_positions=0,
            day_pnl=0,
            day_start_equity=25_000,
            trades_today=0,
            now_ts=ts,
            last_exit_ts=None,
            consecutive_losses=0,
            has_pending_entry=False,
        )
        risk_excluded = not decision.ok and "exclusión" in decision.reason.lower()
        assert risk_excluded is expected, f"{day} {tz_name} {hhmm}: {decision.reason}"
        assert decision.ok is not expected, f"{day} {tz_name} {hhmm}: {decision.reason}"


@pytest.mark.parametrize(
    ("day", "expected_offset_hours"),
    [
        (date(2025, 3, 9), -4),
        (date(2025, 11, 2), -5),
    ],
)
def test_entry_exclusion_uses_configured_timezone_on_dst_days(
    day: date, expected_offset_hours: int
) -> None:
    """La ventana se evalúa en hora local incluso en los cambios de hora."""
    tz_name = "America/New_York"
    risk = _risk("11:00", "13:00", timezone=tz_name)

    assert local_dt(timestamp_for(day, "11:00", tz_name), tz_name).utcoffset() == timedelta(
        hours=expected_offset_hours
    )
    assert local_dt(timestamp_for(day, "13:00", tz_name), tz_name).utcoffset() == timedelta(
        hours=expected_offset_hours
    )

    assert _evaluate(risk, "10:59", day=day, tz_name=tz_name).ok
    blocked = _evaluate(risk, "11:00", day=day, tz_name=tz_name)
    assert not blocked.ok
    assert "exclusión" in blocked.reason.lower()
    assert not _evaluate(risk, "12:59", day=day, tz_name=tz_name).ok
    assert _evaluate(risk, "13:00", day=day, tz_name=tz_name).ok


@pytest.mark.parametrize("day", [date(2025, 3, 9), date(2025, 11, 2)])
@pytest.mark.parametrize(
    "tz_name",
    ["America/Los_Angeles", "Europe/Madrid", "Asia/Tokyo"],
)
def test_entry_exclusion_uses_orb_timezone_not_hardcoded_et(
    day: date, tz_name: str
) -> None:
    """Con otra zona, un filtro en ET hardcodeada daría otro resultado."""
    risk = _risk("11:00", "13:00", timezone=tz_name)

    # En estas zonas las 11:00 locales no son las 11:00 ET.
    assert et_minutes(timestamp_for(day, "11:00", tz_name)) != 11 * 60
    blocked = _evaluate(risk, "11:00", day=day, tz_name=tz_name)
    assert not blocked.ok
    assert "exclusión" in blocked.reason.lower()
    assert not _evaluate(risk, "12:59", day=day, tz_name=tz_name).ok
    assert _evaluate(risk, "13:00", day=day, tz_name=tz_name).ok


@pytest.mark.parametrize("day", [date(2025, 3, 9), date(2025, 11, 2)])
@pytest.mark.parametrize(
    "tz_name",
    ["America/New_York", "America/Los_Angeles", "Europe/Madrid", "Asia/Tokyo"],
)
def test_pending_entry_cancellation_uses_orb_timezone(day: date, tz_name: str) -> None:
    """La cancelación de una entrada pendiente también respeta la zona configurada."""
    settings = Settings(
        orb={"timezone": tz_name},
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
        },
    )
    engine = ExecutionEngine(settings)

    pending = _signal("pending-timezone")
    pending.ts = timestamp_for(day, "13:05", tz_name)
    engine.arm(pending)
    engine.on_bar(
        Bar(timestamp_for(day, "11:00", tz_name), 20_000, 20_000.5, 19_999.5, 20_000)
    )

    assert engine.pending_entry is None
    assert "pending-timezone" in engine.seen_signals

    allowed = _signal("allowed-timezone")
    allowed.ts = timestamp_for(day, "13:00", tz_name)
    engine.arm(allowed)
    engine.on_bar(
        Bar(timestamp_for(day, "13:00", tz_name), 20_000, 20_000.5, 19_999.5, 20_000)
    )
    assert engine.position is not None


def test_paper_engine_uses_the_entry_exclusion(tmp_path) -> None:
    settings = Settings(
        risk={
            "entry_exclusion_start": "10:00",
            "entry_exclusion_end": "11:00",
        }
    )
    store = Store(tmp_path / "entry-exclusion.db")
    try:
        engine = TradingEngine(store, settings)
        engine.status = "running"
        engine.strategy.evaluate = lambda *_: Assess(signal=_signal())
        engine._evaluate(timestamp_for(date(2025, 6, 3), "10:00") - 60)

        assert engine.execution.pending_entry is None
        assert "exclusion" in engine._rejected

        engine.risk.settings.risk.entry_exclusion_start = ""
        engine.risk.settings.risk.entry_exclusion_end = ""
        engine._rejected.clear()
        engine.strategy.evaluate = lambda *_: Assess(signal=_signal("allowed"))
        engine._evaluate(timestamp_for(date(2025, 6, 3), "10:00") - 60)

        assert engine.execution.pending_entry is not None
    finally:
        store.close()


def test_paper_engine_allows_entry_at_the_exclusion_end_boundary(tmp_path) -> None:
    settings = Settings(
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
        }
    )
    store = Store(tmp_path / "entry-exclusion-boundary.db")
    try:
        engine = TradingEngine(store, settings)
        engine.status = "running"
        engine.strategy.evaluate = lambda *_: Assess(signal=_signal("at-1300"))
        engine._evaluate(timestamp_for(date(2025, 6, 3), "13:00") - 60)

        assert engine.execution.pending_entry is not None
        assert "exclusion" not in engine._rejected
    finally:
        store.close()


def test_pending_entry_is_cancelled_if_fill_falls_in_exclusion() -> None:
    settings = Settings(
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
        }
    )
    engine = ExecutionEngine(settings)
    day = date(2025, 6, 3)

    pending = _signal("pending-crosses")
    pending.ts = timestamp_for(day, "11:05")
    engine.arm(pending)
    engine.on_bar(
        Bar(timestamp_for(day, "11:00"), 20_000, 20_000.5, 19_999.5, 20_000)
    )

    assert engine.pending_entry is None
    assert engine.position is None
    assert engine.closed_trades == []
    assert engine.pending_orders == []
    assert "pending-crosses" in engine.seen_signals

    allowed = _signal("at-1300")
    allowed.ts = timestamp_for(day, "13:00")
    engine.arm(allowed)
    engine.on_bar(
        Bar(timestamp_for(day, "13:00"), 20_000, 20_000.5, 19_999.5, 20_000)
    )

    assert engine.position is not None


def test_pending_entry_at_the_exclusion_end_only_survives_if_rearmed_at_the_boundary() -> None:
    """Cruce del borde final: la cancelación mira la vela, no el momento del fill.

    Una orden pendiente viva a las 12:59 se cancela aunque su fill caería a las
    13:00; solo una orden armada con el borde ya abierto llega a llenarse.
    """
    settings = Settings(
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
        }
    )
    day = date(2025, 6, 3)
    flat = Bar(timestamp_for(day, "12:59"), 20_000, 20_000.5, 19_999.5, 20_000)

    stale = ExecutionEngine(settings)
    pending = _signal("armed-before-the-end")
    pending.ts = timestamp_for(day, "13:00")
    stale.arm(pending)
    stale.on_bar(flat)

    assert stale.pending_entry is None
    assert stale.position is None
    assert stale.closed_trades == []
    assert "armed-before-the-end" in stale.seen_signals
    # Tampoco revive al procesar la vela del borde ya abierto.
    stale.on_bar(
        Bar(timestamp_for(day, "13:00"), 20_000, 20_000.5, 19_999.5, 20_000)
    )
    assert stale.position is None

    reopened = ExecutionEngine(settings)
    fresh = _signal("armed-at-the-end")
    fresh.ts = timestamp_for(day, "13:00")
    reopened.arm(fresh)
    reopened.on_bar(
        Bar(timestamp_for(day, "13:00"), 20_000, 20_000.5, 19_999.5, 20_000)
    )

    assert reopened.pending_entry is None
    assert reopened.position is not None


def test_open_position_before_exclusion_stays_open_and_is_managed(tmp_path) -> None:
    """El filtro bloquea entradas nuevas, no cierra una posición ya abierta."""
    settings = Settings(
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
        }
    )
    store = Store(tmp_path / "entry-exclusion-open-position.db")
    try:
        engine = TradingEngine(store, settings)
        engine.status = "running"
        day = date(2025, 6, 3)

        # Entrada válida a las 10:59, justo antes de la ventana.
        engine.strategy.evaluate = lambda *_: Assess(signal=_signal("before-window"))
        engine._evaluate(timestamp_for(day, "10:59") - 60)
        assert engine.execution.pending_entry is not None
        engine.execution.on_bar(
            Bar(timestamp_for(day, "10:59"), 20_000, 20_000.5, 19_999.5, 20_000)
        )
        position = engine.execution.position
        assert position is not None
        position_id = position.id
        assert position.entry_ts < timestamp_for(day, "11:00")

        # Señal nueva durante la ventana: no se arma ni se toca la posición.
        engine.strategy.evaluate = lambda *_: Assess(signal=_signal("during-window"))
        engine._evaluate(timestamp_for(day, "11:30") - 60)
        assert engine.assess.signal is not None
        assert engine.assess.signal.id == "during-window"
        assert engine.execution.position is not None
        assert engine.execution.position.id == position_id
        assert engine.execution.pending_entry is None
        assert engine.execution.closed_trades == []

        # La gestión normal sigue activa: el target se toca dentro de la ventana.
        engine.execution.on_bar(
            Bar(timestamp_for(day, "11:31"), 20_025, 20_040, 20_024, 20_035)
        )
        assert engine.execution.position is None
        assert len(engine.execution.closed_trades) == 1
        assert engine.execution.closed_trades[0].exit_reason == "take_profit"

        # A las 13:00 el filtro ya permite una entrada nueva.
        engine.strategy.evaluate = lambda *_: Assess(signal=_signal("after-window"))
        engine._evaluate(timestamp_for(day, "13:00") - 60)
        assert engine.execution.pending_entry is not None
    finally:
        store.close()


def _real_roll_fixture(path: Path) -> Path:
    """Reescribe el CSV real con un roll H26->M26 y una base de -10 puntos.

    Las barras son las del fixture real; solo cambian el contrato declarado y
    el nivel de la sesión vieja, para que el loader detecte el roll y ajuste
    la serie. El desplazamiento desaparece al aplicar el offset.
    """
    with REAL_CSV.open(encoding="utf-8", newline="") as source, path.open(
        "w", encoding="utf-8", newline=""
    ) as target:
        writer = csv.writer(target)
        writer.writerow(
            ["timestamp", "symbol", "open", "high", "low", "close", "volume", "contract", "expiry"]
        )
        for row in csv.DictReader(source):
            old = row["timestamp"][:10] <= ROLL_DAY
            shift = ROLL_SHIFT if old else 0.0
            writer.writerow(
                [
                    row["timestamp"],
                    row["symbol"],
                    f"{float(row['open']) + shift:.4f}",
                    f"{float(row['high']) + shift:.4f}",
                    f"{float(row['low']) + shift:.4f}",
                    f"{float(row['close']) + shift:.4f}",
                    row["volume"],
                    f"{row['symbol']}{'H26' if old else 'M26'}",
                    "2026-03-20" if old else "2026-06-19",
                ]
            )
    return path


def _real_csv_settings(
    path: Path, *, exclusion: bool, exclude_roll_sessions: bool
) -> Settings:
    settings = Settings()
    settings.feed.provider = "csv"
    settings.feed.csv_path = str(path)
    settings.feed.series_mode = "adjusted"
    settings.feed.exclude_roll_sessions = exclude_roll_sessions
    if exclusion:
        settings.risk.entry_exclusion_start = "11:00"
        settings.risk.entry_exclusion_end = "13:00"
    return settings


def _entries_in_exclusion(result: dict, start: str = "11:00", end: str = "13:00") -> int:
    """Misma definición que ``reports/backtest/run_entry_exclusion_compare.py``."""
    timezone = result["config"]["orb"]["timezone"]
    start_min = hm_to_minutes(start)
    end_min = hm_to_minutes(end)
    return sum(
        1
        for trade in result["trades"]
        if start_min <= et_minutes(int(trade["entry_ts"]), timezone) < end_min
    )


def _partial_settings(exclusion: bool = True) -> Settings:
    settings = Settings(execution={"simulate_partial_fills": True})
    if exclusion:
        settings.risk.entry_exclusion_start = "11:00"
        settings.risk.entry_exclusion_end = "13:00"
    return settings


def test_partial_remainder_completes_an_open_position_inside_the_exclusion() -> None:
    """El remanente de un fill parcial no es una entrada nueva: completa la posición."""
    engine = ExecutionEngine(_partial_settings())
    day = date(2025, 6, 3)
    signal = _signal("partial-entry")
    signal.qty = 5
    signal.ts = timestamp_for(day, "10:59")
    engine.arm(signal)

    engine.on_bar(Bar(timestamp_for(day, "10:59"), 20_000, 20_000.5, 19_999.5, 20_000))

    assert engine.position is not None
    assert engine.position.qty == 3
    assert engine.pending_entry is not None
    assert engine.pending_entry.id == "partial-entry-partial"
    assert engine.pending_entry.meta["partial"] is True
    assert engine.pending_entry.ts == timestamp_for(day, "11:00")

    # El remanente cruza el inicio de la ventana y completa la posición abierta.
    engine.on_bar(Bar(timestamp_for(day, "11:00"), 20_002, 20_002.5, 20_001.5, 20_002))

    assert engine.pending_entry is None
    assert engine.pending_orders == []
    assert engine.position is not None
    assert engine.position.qty == 5
    assert engine.position.entry_price == pytest.approx(20_001.05)
    # El tamaño planificado no se reescribe al completar la segunda tranche.
    assert engine.position.meta["planned_qty"] == 5
    assert engine.closed_trades == []


def test_partial_remainder_is_cancelled_if_the_position_closed_before_it_fills() -> None:
    """Sin posición abierta, el remanente abriría una entrada nueva: se cancela."""
    engine = ExecutionEngine(_partial_settings())
    day = date(2025, 6, 3)
    signal = _signal("partial-entry")
    signal.qty = 5
    signal.ts = timestamp_for(day, "10:59")
    engine.arm(signal)

    # La primera tranche entra y sale por stop en la misma vela; el remanente
    # queda pendiente para la vela siguiente.
    engine.on_bar(Bar(timestamp_for(day, "10:59"), 20_000, 20_001, 19_985, 19_990))

    assert engine.position is None
    assert len(engine.closed_trades) == 1
    assert engine.closed_trades[0].qty == 3
    assert engine.closed_trades[0].exit_reason == "stop_loss"
    assert engine.pending_entry is not None

    engine.on_bar(Bar(timestamp_for(day, "11:00"), 19_990, 19_992, 19_988, 19_990))

    assert engine.pending_entry is None
    assert engine.position is None
    assert len(engine.closed_trades) == 1
    assert "partial-entry-partial" in engine.seen_signals


@pytest.mark.parametrize(
    ("direction", "exit_hhmm", "expected_exit_reason"),
    [
        ("long", "11:31", "take_profit"),
        ("long", "12:59", "take_profit"),
        ("short", "11:31", "stop_loss"),
        ("short", "12:59", "stop_loss"),
    ],
    ids=["long-tp-1131", "long-tp-1259", "short-sl-1131", "short-sl-1259"],
)
def test_simulate_keeps_open_position_alive_and_managed_inside_exclusion(
    monkeypatch, direction, exit_hhmm, expected_exit_reason
) -> None:
    """La posición abierta antes de 11:00 sigue viva; long sale por TP y short por SL."""
    settings = Settings(
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
            # Aísla el filtro: la reentrada de las 13:00 no debe chocar con
            # el cooldown posterior a la salida de las 12:59.
            "cooldown_minutes": 0,
        }
    )
    day = date(2025, 6, 3)

    def bar(hhmm: str, open_: float, high: float, low: float, close: float) -> Bar:
        return Bar(timestamp_for(day, hhmm), open_, high, low, close, volume=100)

    flat = (20_000.0, 20_000.5, 19_999.5, 20_000.0)
    times = [
        "10:57",
        "10:58",
        "10:59",
        "11:00",
        "11:01",
        "11:30",
        "11:31",
        "12:58",
        "12:59",
        "13:00",
        "13:01",
        "13:05",
    ]

    def exit_bar(hhmm: str) -> Bar:
        if direction == "long":
            return bar(hhmm, 20_025.0, 20_040.0, 20_024.0, 20_035.0)
        # Short: toca el stop (20,010) sin llegar al target (19,970).
        return bar(hhmm, 20_005.0, 20_020.0, 19_995.0, 20_015.0)

    bars = [
        exit_bar(hhmm) if hhmm == exit_hhmm else bar(hhmm, *flat)
        for hhmm in times
    ]
    sessions = [(day, {"NQ": bars, "MNQ": bars, "ES": bars})]
    dataset = _sim_dataset(day, bars)

    def fake_evaluate(self, nq, es, trade_window_open):
        signal = None
        hm = et_hm(nq[-1].ts, self.settings.orb.timezone)
        if hm == "10:58":
            signal = _signal("before-window")
            if direction == "short":
                signal.direction = "short"
                signal.stop = 20_010
                signal.target = 19_970
            signal.ts = nq[-1].ts + 60
        elif hm == "12:59":
            signal = _signal("after-window")
            signal.ts = nq[-1].ts + 60
        return Assess(signal=signal)

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    result = bt._simulate(
        settings,
        sessions,
        "synthetic",
        "entry-exclusion-backtest",
        dataset,
    )

    trades = result["trades"]
    assert [trade["meta"]["signal_id"] for trade in trades] == [
        "before-window",
        "after-window",
    ]
    before = trades[0]
    assert before["direction"] == direction
    assert before["entry_ts"] == timestamp_for(day, "10:59")
    assert before["entry_ts"] < timestamp_for(day, "11:00") < before["exit_ts"]
    # La posición sigue viva al entrar en la ventana y solo la cierra la
    # gestión normal (TP o SL), nunca el filtro de exclusión.
    assert before["exit_ts"] == timestamp_for(day, exit_hhmm)
    assert before["exit_reason"] == expected_exit_reason

    after = trades[1]
    assert after["entry_ts"] == timestamp_for(day, "13:00")


@pytest.mark.parametrize(
    ("signal_hhmm", "expected_on_trades"),
    [
        ("10:59", 0),
        ("11:00", 0),
        ("12:59", 1),
        ("13:00", 1),
    ],
)
def test_simulate_boundary_matrix_is_exact_subset(
    monkeypatch, signal_hhmm, expected_on_trades
) -> None:
    """Matriz 10:59/11:00/12:59/13:00 con subconjunto exacto del baseline."""
    day = date(2025, 6, 3)

    def bar(hhmm: str, open_: float, high: float, low: float, close: float) -> Bar:
        return Bar(timestamp_for(day, hhmm), open_, high, low, close, volume=100)

    flat = (20_000.0, 20_000.5, 19_999.5, 20_000.0)
    times = [
        "10:57",
        "10:58",
        "10:59",
        "11:00",
        "11:01",
        "12:59",
        "13:00",
        "13:01",
        "13:05",
    ]
    bars = [bar(hhmm, *flat) for hhmm in times]
    sessions = [(day, {"NQ": bars, "MNQ": bars, "ES": bars})]
    dataset = _sim_dataset(day, bars)

    def fake_evaluate(self, nq, es, trade_window_open):
        if et_hm(nq[-1].ts, self.settings.orb.timezone) == signal_hhmm:
            signal = _signal(f"boundary-{signal_hhmm}")
            signal.ts = nq[-1].ts + 60
            return Assess(signal=signal)
        return Assess()

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    off = bt._simulate(Settings(), sessions, "synthetic", "off", dataset)
    on = bt._simulate(
        Settings(
            risk={
                "entry_exclusion_start": "11:00",
                "entry_exclusion_end": "13:00",
            }
        ),
        sessions,
        "synthetic",
        "on",
        dataset,
    )

    off_trades = off["trades"]
    on_trades = on["trades"]
    expected_id = f"boundary-{signal_hhmm}"
    assert [trade["meta"]["signal_id"] for trade in off_trades] == [expected_id]
    baseline_entry = off_trades[0]["entry_ts"]
    if expected_on_trades:
        assert baseline_entry >= timestamp_for(day, "13:00")
    else:
        assert (
            timestamp_for(day, "11:00")
            <= baseline_entry
            < timestamp_for(day, "13:00")
        )
    assert len(on_trades) == expected_on_trades
    assert {trade["meta"]["signal_id"] for trade in on_trades} <= {
        trade["meta"]["signal_id"] for trade in off_trades
    }

    if expected_on_trades:
        assert [trade["meta"]["signal_id"] for trade in on_trades] == [expected_id]
        assert [
            (trade["entry_ts"], trade["exit_ts"], trade["pnl"])
            for trade in on_trades
        ] == [
            (trade["entry_ts"], trade["exit_ts"], trade["pnl"])
            for trade in off_trades
        ]
    else:
        assert on_trades == []


@pytest.mark.parametrize("signal_hhmm", _sweep_minutes("10:55", "13:05"))
def test_simulate_per_minute_sweep_is_the_exact_subset_of_the_baseline(
    monkeypatch, signal_hhmm
) -> None:
    """Minuto a minuto: se conserva el trade solo si su fill cae fuera de [11:00, 13:00)."""
    day = date(2025, 6, 3)

    def bar(hhmm: str) -> Bar:
        return Bar(
            timestamp_for(day, hhmm),
            20_000.0,
            20_000.5,
            19_999.5,
            20_000.0,
            volume=100,
        )

    times = _sweep_minutes("10:54", "13:10")
    bars = [bar(hhmm) for hhmm in times]
    sessions = [(day, {"NQ": bars, "MNQ": bars, "ES": bars})]
    dataset = _sim_dataset(day, bars)

    def fake_evaluate(self, nq, es, trade_window_open):
        if et_hm(nq[-1].ts, self.settings.orb.timezone) == signal_hhmm:
            signal = _signal(f"sweep-{signal_hhmm}")
            signal.ts = nq[-1].ts + 60
            return Assess(signal=signal)
        return Assess()

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    baseline = bt._simulate(Settings(), sessions, "synthetic", "sweep-off", dataset)
    filtered = bt._simulate(
        Settings(
            risk={
                "entry_exclusion_start": "11:00",
                "entry_exclusion_end": "13:00",
            }
        ),
        sessions,
        "synthetic",
        "sweep-on",
        dataset,
    )

    off_trades = baseline["trades"]
    # El baseline contiene exactamente el trade de este minuto, con fill al
    # siguiente open; así el subconjunto filtrado se compara contra él.
    assert [trade["meta"]["signal_id"] for trade in off_trades] == [
        f"sweep-{signal_hhmm}"
    ]
    source = off_trades[0]
    assert source["entry_ts"] == timestamp_for(day, signal_hhmm) + 60

    on_trades = filtered["trades"]
    if timestamp_for(day, "11:00") <= source["entry_ts"] < timestamp_for(day, "13:00"):
        assert on_trades == []
    else:
        assert len(on_trades) == 1
        kept = on_trades[0]
        assert kept["meta"]["signal_id"] == source["meta"]["signal_id"]
        assert (
            kept["entry_ts"],
            kept["exit_ts"],
            kept["pnl"],
            kept["exit_reason"],
        ) == (
            source["entry_ts"],
            source["exit_ts"],
            source["pnl"],
            source["exit_reason"],
        )


def test_simulate_signals_at_all_four_boundaries_only_blocks_window_entries(
    monkeypatch,
) -> None:
    """Una sesión con señales en 10:59, 11:00, 12:59 y 13:00."""
    day = date(2025, 6, 3)

    def bar(hhmm: str) -> Bar:
        # El target se toca en la misma barra de entrada para que la siguiente
        # señal pueda evaluarse sin que la posición anterior la tape.
        return Bar(
            timestamp_for(day, hhmm),
            open=20_000.0,
            high=20_040.0,
            low=19_999.0,
            close=20_000.0,
            volume=100,
        )

    times = ["10:59", "11:00", "11:01", "12:59", "13:00", "13:01", "13:05"]
    bars = [bar(hhmm) for hhmm in times]
    sessions = [(day, {"NQ": bars, "MNQ": bars, "ES": bars})]
    dataset = _sim_dataset(day, bars)
    signal_times = {"10:59", "11:00", "12:59", "13:00"}

    def fake_evaluate(self, nq, es, trade_window_open):
        hm = et_hm(nq[-1].ts, self.settings.orb.timezone)
        if hm in signal_times:
            signal = _signal(f"boundary-{hm}")
            signal.ts = nq[-1].ts + 60
            return Assess(signal=signal)
        return Assess()

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    common_risk = {"cooldown_minutes": 0, "max_trades_per_day": 10}
    baseline = bt._simulate(
        Settings(risk=common_risk),
        sessions,
        "synthetic",
        "baseline",
        dataset,
    )
    filtered = bt._simulate(
        Settings(
            risk={
                **common_risk,
                "entry_exclusion_start": "11:00",
                "entry_exclusion_end": "13:00",
            }
        ),
        sessions,
        "synthetic",
        "filtered",
        dataset,
    )

    off_trades = baseline["trades"]
    on_trades = filtered["trades"]
    off_ids = [trade["meta"]["signal_id"] for trade in off_trades]
    on_ids = [trade["meta"]["signal_id"] for trade in on_trades]

    assert off_ids == [
        "boundary-10:59",
        "boundary-11:00",
        "boundary-12:59",
        "boundary-13:00",
    ]
    assert on_ids == ["boundary-12:59", "boundary-13:00"]
    assert set(on_ids) <= set(off_ids)

    off_by_id = {trade["meta"]["signal_id"]: trade for trade in off_trades}
    for signal_id in on_ids:
        kept = on_trades[on_ids.index(signal_id)]
        source = off_by_id[signal_id]
        assert (
            kept["entry_ts"],
            kept["exit_ts"],
            kept["pnl"],
        ) == (
            source["entry_ts"],
            source["exit_ts"],
            source["pnl"],
        )

    removed = set(off_ids) - set(on_ids)
    assert removed == {"boundary-10:59", "boundary-11:00"}
    for signal_id in removed:
        entry_ts = off_by_id[signal_id]["entry_ts"]
        assert timestamp_for(day, "11:00") <= entry_ts < timestamp_for(day, "13:00")
    for signal_id in on_ids:
        assert off_by_id[signal_id]["entry_ts"] >= timestamp_for(day, "13:00")


def test_simulate_daily_trade_limit_is_not_consumed_by_excluded_signals(
    monkeypatch,
) -> None:
    """Con cupo 1, la señal interior no cuenta y la de 12:59 ocupa el único hueco."""
    day = date(2025, 6, 3)

    def bar(hhmm: str) -> Bar:
        return Bar(
            timestamp_for(day, hhmm),
            open=20_000.0,
            high=20_040.0,
            low=19_999.0,
            close=20_000.0,
            volume=100,
        )

    times = ["10:59", "11:00", "11:30", "11:31", "12:58", "12:59", "13:00", "13:01"]
    bars = [bar(hhmm) for hhmm in times]
    sessions = [(day, {"NQ": bars, "MNQ": bars, "ES": bars})]
    dataset = _sim_dataset(day, bars)
    signal_times = {"11:30", "12:59"}

    def fake_evaluate(self, nq, es, trade_window_open):
        hm = et_hm(nq[-1].ts, self.settings.orb.timezone)
        if hm in signal_times:
            signal = _signal(f"quota-{hm}")
            signal.ts = nq[-1].ts + 60
            return Assess(signal=signal)
        return Assess()

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    common_risk = {"cooldown_minutes": 0, "max_trades_per_day": 1}
    baseline = bt._simulate(
        Settings(risk=common_risk),
        sessions,
        "synthetic",
        "daily-quota-baseline",
        dataset,
    )
    filtered = bt._simulate(
        Settings(
            risk={
                **common_risk,
                "entry_exclusion_start": "11:00",
                "entry_exclusion_end": "13:00",
            }
        ),
        sessions,
        "synthetic",
        "daily-quota-filtered",
        dataset,
    )

    off_trades = baseline["trades"]
    on_trades = filtered["trades"]

    # Sin filtro, la señal de dentro de la ventana consume el único hueco y la
    # de las 12:59 ni se evalúa.
    assert [trade["meta"]["signal_id"] for trade in off_trades] == ["quota-11:30"]
    assert off_trades[0]["entry_ts"] == timestamp_for(day, "11:31")
    # Con filtro, la rechazada por exclusión no gasta cupo: entra la de 13:00.
    assert [trade["meta"]["signal_id"] for trade in on_trades] == ["quota-12:59"]
    assert on_trades[0]["entry_ts"] == timestamp_for(day, "13:00")
    assert on_trades[0]["exit_reason"] == "take_profit"

    # El filtro cambia qué señal ocupa el cupo, no cuántas operaciones permite.
    assert baseline["days_detail"][0]["trades"] == 1
    assert filtered["days_detail"][0]["trades"] == 1


def test_real_cooldown_blocks_first_signal_after_the_exclusion(monkeypatch) -> None:
    """El fin de la exclusión no garantiza entrada: el cooldown real sigue vivo."""
    day = date(2025, 6, 3)
    settings = Settings(
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
        }
    )
    assert settings.risk.cooldown_minutes == 5

    def bar(hhmm: str, high: float = 20_000.5, low: float = 19_999.5) -> Bar:
        return Bar(timestamp_for(day, hhmm), 20_000.0, high, low, 20_000.0, volume=100)

    times = [
        "10:58",
        "10:59",
        "11:00",
        "11:30",
        "12:58",
        "12:59",
        "13:00",
        "13:01",
        "13:02",
        "13:03",
        "13:04",
        "13:05",
    ]
    bars = [
        # El target se toca exactamente a las 12:59, justo antes de la exclusión.
        bar(hhmm, high=20_040.0, low=20_024.0) if hhmm == "12:59" else bar(hhmm)
        for hhmm in times
    ]
    sessions = [(day, {"NQ": bars, "MNQ": bars, "ES": bars})]
    dataset = _sim_dataset(day, bars)

    def fake_evaluate(self, nq, es, trade_window_open):
        hm = et_hm(nq[-1].ts, self.settings.orb.timezone)
        signal = None
        if hm == "10:58":
            signal = _signal("held-into-window")
        elif hm == "13:00":
            signal = _signal("blocked-at-1300")
        elif hm == "13:03":
            signal = _signal("after-cooldown")
        if signal is not None:
            signal.ts = nq[-1].ts + 60
        return Assess(signal=signal)

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    decisions: dict[str, tuple[bool, str, int]] = {}
    original_evaluate = RiskManager.evaluate

    def record_decision(self, signal, **kwargs):
        decision = original_evaluate(self, signal, **kwargs)
        decisions[signal.id] = (decision.ok, decision.reason, kwargs["now_ts"])
        return decision

    monkeypatch.setattr(RiskManager, "evaluate", record_decision)
    result = bt._simulate(
        settings,
        sessions,
        "synthetic",
        "real-cooldown",
        dataset,
    )

    blocked_ok, blocked_reason, blocked_ts = decisions["blocked-at-1300"]
    assert not blocked_ok
    assert "cooldown" in blocked_reason.lower()
    assert "exclusión" not in blocked_reason.lower()
    assert blocked_ts == timestamp_for(day, "13:01")

    allowed_ok, _, allowed_ts = decisions["after-cooldown"]
    assert allowed_ok
    assert allowed_ts == timestamp_for(day, "13:04")
    assert allowed_ts - timestamp_for(day, "12:59") == 5 * 60

    trades = result["trades"]
    assert [trade["meta"]["signal_id"] for trade in trades] == [
        "held-into-window",
        "after-cooldown",
    ]
    held = trades[0]
    assert held["exit_ts"] == timestamp_for(day, "12:59")
    assert held["exit_reason"] == "take_profit"
    after = trades[1]
    assert after["entry_ts"] == timestamp_for(day, "13:04")


def test_simulate_cancels_pending_entry_before_fill_inside_exclusion(
    monkeypatch,
) -> None:
    """Una orden armada antes de las 11:00 no se llena dentro de la ventana."""
    day = date(2025, 6, 3)

    def bar(hhmm: str, open_: float, high: float, low: float, close: float) -> Bar:
        return Bar(timestamp_for(day, hhmm), open_, high, low, close, volume=100)

    flat = (20_000.0, 20_000.5, 19_999.5, 20_000.0)
    times = ["10:57", "10:58", "10:59", "11:00", "11:05", "12:59", "13:00", "13:01", "13:05"]
    bars = [bar(hhmm, *flat) for hhmm in times]
    sessions = [(day, {"NQ": bars, "MNQ": bars, "ES": bars})]
    dataset = _sim_dataset(day, bars)

    def fake_evaluate(self, nq, es, trade_window_open):
        hm = et_hm(nq[-1].ts, self.settings.orb.timezone)
        if hm == "10:58":
            signal = _signal("pending-crosses")
            # Se arma antes de las 11:00, pero su fill sería a las 11:05.
            signal.ts = timestamp_for(day, "11:05")
            return Assess(signal=signal)
        if hm == "12:59":
            signal = _signal("after-window")
            signal.ts = nq[-1].ts + 60
            return Assess(signal=signal)
        return Assess()

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    armed: list[str] = []
    original_arm = ExecutionEngine.arm

    def record_arm(self, signal):
        armed.append(signal.id)
        return original_arm(self, signal)

    monkeypatch.setattr(ExecutionEngine, "arm", record_arm)
    result = bt._simulate(
        Settings(
            risk={
                "entry_exclusion_start": "11:00",
                "entry_exclusion_end": "13:00",
            }
        ),
        sessions,
        "synthetic",
        "pending-crosses",
        dataset,
    )

    # La orden sí llegó a armarse antes de las 11:00; el guard la canceló
    # cuando su fill habría caído dentro de la ventana.
    assert "pending-crosses" in armed
    assert [trade["meta"]["signal_id"] for trade in result["trades"]] == [
        "after-window"
    ]
    assert result["trades"][0]["entry_ts"] == timestamp_for(day, "13:00")


def test_simulate_pending_entry_cannot_wait_out_the_window_until_the_reopening(
    monkeypatch,
) -> None:
    """Un pendiente armado antes de la ventana no sobrevive hasta las 13:00.

    Ambas órdenes se llenarían a las 13:00; la diferencia es cuándo se armaron.
    """
    day = date(2025, 6, 3)

    def bar(hhmm: str) -> Bar:
        return Bar(
            timestamp_for(day, hhmm),
            20_000.0,
            20_000.5,
            19_999.5,
            20_000.0,
            volume=100,
        )

    times = [
        "10:57",
        "10:58",
        "10:59",
        "11:00",
        "11:01",
        "12:58",
        "12:59",
        "13:00",
        "13:01",
        "13:05",
    ]
    bars = [bar(hhmm) for hhmm in times]
    sessions = [(day, {"NQ": bars, "MNQ": bars, "ES": bars})]
    dataset = _sim_dataset(day, bars)

    def fake_evaluate(self, nq, es, trade_window_open):
        hm = et_hm(nq[-1].ts, self.settings.orb.timezone)
        if hm == "10:58":
            signal = _signal("armed-early")
            # El fill caería exactamente en la reapertura.
            signal.ts = timestamp_for(day, "13:00")
            return Assess(signal=signal)
        if hm == "12:59":
            signal = _signal("armed-at-the-end")
            signal.ts = nq[-1].ts + 60
            return Assess(signal=signal)
        return Assess()

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    baseline = bt._simulate(Settings(), sessions, "synthetic", "late-fill-off", dataset)
    filtered = bt._simulate(
        Settings(
            risk={
                "entry_exclusion_start": "11:00",
                "entry_exclusion_end": "13:00",
            }
        ),
        sessions,
        "synthetic",
        "late-fill-on",
        dataset,
    )

    # Sin filtro, la orden temprana espera hasta las 13:00 y la señal del borde
    # ni se arma porque ya hay una entrada pendiente.
    assert [trade["meta"]["signal_id"] for trade in baseline["trades"]] == [
        "armed-early"
    ]
    assert baseline["trades"][0]["entry_ts"] == timestamp_for(day, "13:00")

    # Con filtro, la orden temprana se cancela a las 11:00: a las 13:00 entra
    # la señal evaluada en el borde, no la que cruzó la ventana.
    assert [trade["meta"]["signal_id"] for trade in filtered["trades"]] == [
        "armed-at-the-end"
    ]
    assert filtered["trades"][0]["entry_ts"] == timestamp_for(day, "13:00")


def test_simulate_partial_entry_crossing_the_window_is_identical_to_the_baseline(
    monkeypatch,
) -> None:
    """Dos fills (10:59 y 11:00) dejan la misma posición con filtro y sin él."""
    day = date(2025, 6, 3)

    def bar(hhmm: str) -> Bar:
        if hhmm == "11:00":
            # El segundo fill tiene un precio distinto para fijar la media.
            return Bar(
                timestamp_for(day, hhmm),
                20_002.0,
                20_002.5,
                20_001.5,
                20_002.0,
                volume=100,
            )
        return Bar(
            timestamp_for(day, hhmm),
            20_000.0,
            20_000.5,
            19_999.5,
            20_000.0,
            volume=100,
        )

    bars = [bar(hhmm) for hhmm in _sweep_minutes("10:57", "13:05")]
    sessions = [(day, {"NQ": bars, "MNQ": bars, "ES": bars})]
    dataset = _sim_dataset(day, bars)

    def fake_evaluate(self, nq, es, trade_window_open):
        if et_hm(nq[-1].ts, self.settings.orb.timezone) == "10:58":
            signal = _signal("partial-entry")
            signal.ts = nq[-1].ts + 60
            return Assess(signal=signal)
        return Assess()

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    baseline = bt._simulate(
        _partial_settings(exclusion=False), sessions, "synthetic", "partial-off", dataset
    )
    filtered = bt._simulate(
        _partial_settings(), sessions, "synthetic", "partial-on", dataset
    )

    off_trades = baseline["trades"]
    assert [trade["meta"]["signal_id"] for trade in off_trades] == ["partial-entry"]
    assert off_trades[0]["entry_ts"] == timestamp_for(day, "10:59")
    # 3 contratos a las 10:59 y 2 a las 11:00: la posición planificada completa.
    assert off_trades[0]["qty"] == 5
    assert off_trades[0]["entry_price"] == pytest.approx(20_001.05)

    on_trades = filtered["trades"]
    assert len(on_trades) == 1
    kept = on_trades[0]
    assert kept["qty"] == 5
    assert (
        kept["entry_ts"],
        kept["entry_price"],
        kept["exit_ts"],
        kept["pnl"],
    ) == (
        off_trades[0]["entry_ts"],
        off_trades[0]["entry_price"],
        off_trades[0]["exit_ts"],
        off_trades[0]["pnl"],
    )


@pytest.mark.parametrize("exclude_roll_sessions", [True, False])
def test_real_csv_with_rolls_and_adjusted_series_has_no_entries_in_exclusion(
    tmp_path: Path, exclude_roll_sessions: bool
) -> None:
    """El filtro también se cumple sobre el CSV real con roll y serie adjusted."""
    path = _real_roll_fixture(tmp_path / "bars_roll_adjusted.csv")
    baseline = run_backtest(
        _real_csv_settings(
            path, exclusion=False, exclude_roll_sessions=exclude_roll_sessions
        ),
        days=4,
        label="real-roll-baseline",
    )
    filtered = run_backtest(
        _real_csv_settings(
            path, exclusion=True, exclude_roll_sessions=exclude_roll_sessions
        ),
        days=4,
        label="real-roll-filtered",
    )

    dataset = filtered["dataset"]
    assert filtered["data_source"] == "csv"
    assert filtered["data_quality"] == "historical"
    assert dataset["series_mode"] == "adjusted"
    assert dataset["roll_sessions"] == [ROLL_DAY]
    assert dataset["excluded_sessions"] == (
        [ROLL_DAY] if exclude_roll_sessions else []
    )
    roll = dataset["rolls"][0]
    assert roll["from"]["MNQ"] == "MNQH26"
    assert roll["to"]["MNQ"] == "MNQM26"
    assert roll["offsets"]["MNQ"] != 0
    assert dataset["contracts_by_session"]["2025-12-26"]["MNQ"] == "MNQM26"

    # Con la estrategia real, la sesión del 26/12 entra a las 11:09 ET: la
    # métrica del protocolo no es trivialmente cero antes de filtrar.
    assert _entries_in_exclusion(baseline) == 1
    assert _entries_in_exclusion(filtered) == 0

    source_trades = baseline["trades"]
    kept = filtered["trades"]
    if exclude_roll_sessions:
        # La sesión de roll se excluye: queda la entrada de las 11:09 y el
        # filtro deja la sesión sin operaciones.
        assert [et_hm(int(trade["entry_ts"])) for trade in source_trades] == ["11:09"]
        assert kept == []
        return

    assert [et_hm(int(trade["entry_ts"])) for trade in source_trades] == [
        "10:26",
        "11:09",
    ]
    source_by_id = {trade["meta"]["signal_id"]: trade for trade in source_trades}
    assert [trade["meta"]["signal_id"] for trade in kept] == [
        source_trades[0]["meta"]["signal_id"]
    ]
    for trade in kept:
        original = source_by_id[trade["meta"]["signal_id"]]
        assert (trade["entry_ts"], trade["exit_ts"], trade["pnl"]) == (
            original["entry_ts"],
            original["exit_ts"],
            original["pnl"],
        )


def _write_parity_csv(path: Path, days: list[date]) -> Path:
    """Sesiones RTH completas con TP, SL y cierre de sesión en la primera."""
    rows = ["timestamp,symbol,open,high,low,close,volume"]
    for day in days:
        start = timestamp_for(day, "09:00")
        for index in range(420):
            ts = start + index * 60
            hhmm = et_hm(ts)
            mnq = (20_000.0, 20_000.5, 19_999.5, 20_000.0)
            if day == days[0] and hhmm == "10:25":  # target de la entrada de 10:21
                mnq = (20_000.0, 20_040.0, 19_999.5, 20_030.0)
            elif day == days[0] and hhmm == "11:01":  # stop dentro de la ventana
                mnq = (20_000.0, 20_000.5, 19_985.0, 19_990.0)
            rows.append(f"{ts},MNQ,{mnq[0]},{mnq[1]},{mnq[2]},{mnq[3]},100")
            rows.append(
                f"{ts},NQ,{mnq[0] + 3},{mnq[1] + 3},{mnq[2] + 3},{mnq[3] + 3},100"
            )
            rows.append(f"{ts},ES,5730,5731,5729,5730,100")
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _parity_settings(path: Path) -> Settings:
    settings = Settings(
        risk={
            "entry_exclusion_start": "11:00",
            "entry_exclusion_end": "13:00",
            "cooldown_minutes": 0,
            "max_trades_per_day": 10,
        }
    )
    settings.feed.provider = "csv"
    settings.feed.csv_path = str(path)
    settings.feed.start_date = "2025-06-03"
    settings.feed.loop_sessions = False
    return settings


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


def _drive_engine(engine: TradingEngine) -> int:
    """Procesa las mismas velas del feed sin el pacing del replay."""
    assert engine.feed is not None
    bars = engine.feed.dataset.bars
    for tick_bars in bars:
        engine._process(Tick(ts=tick_bars["NQ"].ts, bars=tick_bars))
    return len(bars)


def test_paper_and_backtest_match_with_the_exclusion_window_active(
    monkeypatch, tmp_path: Path
) -> None:
    """Las mismas barras y señales dan el mismo conjunto de trades en ambos motores."""
    days = [date(2025, 6, 3), date(2025, 6, 4), date(2025, 6, 5)]
    day = days[0]
    path = _write_parity_csv(tmp_path / "parity.csv", days)
    schedule = {
        "10:20": "parity-1020",  # entra y sale por TP antes de la ventana
        "10:58": "parity-1058",  # la posición cruza la ventana y sale por SL
        "11:30": "parity-1130",  # plana dentro de la ventana: debe bloquearse
        "12:59": "parity-1259",  # reapertura exacta: entra a las 13:00
    }

    def fake_evaluate(self, nq, es, trade_window_open):
        timezone = self.settings.orb.timezone
        hhmm = et_hm(nq[-1].ts, timezone)
        # Solo la primera sesión emite señales; las otras dos dan el mínimo de
        # sesiones que exige run_backtest y deben quedar sin operaciones.
        if et_date(nq[-1].ts, timezone) == day and hhmm in schedule:
            signal = _signal(schedule[hhmm])
            signal.ts = nq[-1].ts + 60
            return Assess(signal=signal)
        return Assess()

    monkeypatch.setattr(ORBStrategy, "evaluate", fake_evaluate)
    settings = _parity_settings(path)

    backtest = run_backtest(
        settings, days=3, start=day, label="entry-exclusion-parity"
    )

    store = Store(tmp_path / "parity.db")
    try:
        engine = TradingEngine(store, settings)
        engine.status = "running"
        assert _drive_engine(engine) == 3 * 420
        paper = [asdict(trade) for trade in engine.execution.closed_trades]
    finally:
        store.close()

    expected_ids = ["parity-1020", "parity-1058", "parity-1259"]
    assert [trade["meta"]["signal_id"] for trade in backtest["trades"]] == expected_ids
    assert [trade["meta"]["signal_id"] for trade in paper] == expected_ids
    assert [trade["exit_reason"] for trade in paper] == [
        "take_profit",
        "stop_loss",
        "session_close",
    ]
    # La señal de las 11:30 se evalúa estando plana y el filtro la descarta en
    # los dos motores: no es un efecto de que hubiera una posición abierta.
    assert "parity-1130" not in {trade["meta"]["signal_id"] for trade in paper}
    assert "parity-1130" not in {
        trade["meta"]["signal_id"] for trade in backtest["trades"]
    }

    assert [_trade_signature(trade) for trade in paper] == [
        _trade_signature(trade) for trade in backtest["trades"]
    ]


def test_entry_exclusion_is_applied_by_the_backtest() -> None:
    baseline = run_backtest(
        Settings(),
        days=3,
        label="entry-exclusion-baseline",
        start=date(2025, 6, 3),
    )
    assert baseline["metrics"]["trades"] > 0

    blocked = run_backtest(
        Settings(
            risk={
                "entry_exclusion_start": "09:00",
                "entry_exclusion_end": "15:30",
            }
        ),
        days=3,
        label="entry-exclusion-blocked",
        start=date(2025, 6, 3),
    )
    assert blocked["metrics"]["trades"] == 0
    assert blocked["funnel"]["summary"]["signals"] > 0
