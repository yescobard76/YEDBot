"""Validación del CSV histórico: formato, alineación, sesiones y feed."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from server.backtest import prepare_dataset, run_backtest, run_variants
from server.config import Settings
from server.db import Store
from server.engine import TradingEngine
from server.market.csv_data import CsvDataset, HOLDOUT_START, inspect_csv, load_bars
from server.market.feed import CSVFeed, SimulatedFeed, build_feed
from server.market.sessions import validate_sessions
from server.market.synthetic import build_session
from server.timeutil import timestamp_for

# 09:00 ET (EDT) = 13:00 UTC. La ventana RTH operativa es 09:00–16:00 ET.
BASE = datetime(2025, 6, 3, 13, 0, tzinfo=timezone.utc)


def _rows(
    count: int = 420,
    *,
    base: datetime = BASE,
    skip: tuple[str, int] | None = None,
) -> list[str]:
    out: list[str] = []
    for i in range(count):
        ts = (base + timedelta(minutes=i)).isoformat()
        for symbol, price_base in (("MNQ", 20_840.0), ("NQ", 20_843.0), ("ES", 5_730.0)):
            if skip == (symbol, i):
                continue
            price = price_base + i
            out.append(f"{ts},{symbol},{price},{price + 2},{price - 2},{price + 1},100")
    return out


def _write(path: Path, rows: list[str]) -> Path:
    path.write_text("timestamp,symbol,open,high,low,close,volume\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def _session_rows(day: date, end: str, count: int | None = None) -> list[str]:
    start = timestamp_for(day, "09:00")
    total = (timestamp_for(day, end) - start) // 60
    base = datetime.fromtimestamp(start, tz=timezone.utc)
    return _rows(count=total if count is None else count, base=base)


def _settings(path: Path) -> Settings:
    settings = Settings()
    settings.feed.provider = "csv"
    settings.feed.csv_path = str(path)
    settings.feed.replay_speed = 200
    return settings


def test_aligned_full_session_is_accepted_and_feed_is_historical(tmp_path: Path):
    path = _write(tmp_path / "bars.csv", _rows())
    rows = load_bars(path)
    assert sorted(rows) == ["ES", "MNQ", "NQ"]
    dataset = CsvDataset.load(path)
    assert len(dataset) == 420
    assert dataset.report["ok"] and dataset.report["aligned"]
    assert dataset.report["session_validation"]["ok"] is True
    session = dataset.report["session_validation"]["sessions"][0]
    assert session["bars_in_window"] == 420
    assert session["or_bars"] == 60
    assert session["or_complete"] is True

    feed = CSVFeed(_settings(path))
    tick = asyncio.run(feed.next_tick())
    assert tick is not None
    assert tick.ts == int(BASE.timestamp())
    assert len({bar.ts for bar in tick.bars.values()}) == 1
    info = feed.describe()
    assert info["quality"] == "historical"
    assert info["simulated"] is False
    assert info["aligned"] is True
    assert info["bars"] == 420
    assert "SIN" not in info["label"]


def test_misaligned_series_is_rejected_with_details(tmp_path: Path):
    path = _write(tmp_path / "bars.csv", _rows(skip=("ES", 1)))
    report = inspect_csv(path)
    assert report["ok"] is False
    assert report["aligned"] is False
    assert report["missing"]["ES"] == 1
    assert report["common_bars"] == 419
    assert any("desalineados" in error for error in report["errors"])
    with pytest.raises(ValueError, match="desalineados"):
        CsvDataset.load(path)


def test_intra_session_gap_blocks_dataset_and_or(tmp_path: Path):
    path = _write(tmp_path / "bars.csv", _rows(skip=("NQ", 30)))
    report = inspect_csv(path)
    assert report["ok"] is False
    validation = report["session_validation"]
    assert validation["ok"] is False
    session = validation["sessions"][0]
    assert session["missing_bars"] == 1
    assert session["first_missing"] == "2025-06-03 09:30"
    assert session["or_bars"] == 59
    assert session["or_complete"] is False
    assert any("incompleta" in error for error in validation["errors"])
    with pytest.raises(ValueError, match="incompleta"):
        CsvDataset.load(path)
    with pytest.raises(ValueError, match="incompleta"):
        CSVFeed(_settings(path))


def test_truncated_session_is_rejected(tmp_path: Path):
    path = _write(tmp_path / "bars.csv", _rows(count=100))
    report = inspect_csv(path)
    assert report["ok"] is False
    session = report["session_validation"]["sessions"][0]
    assert session["valid"] is False
    assert session["missing_bars"] == 320
    assert session["first_missing"] == "2025-06-03 10:40"


def test_weekend_bars_are_rejected(tmp_path: Path):
    saturday = datetime(2025, 6, 7, 13, 0, tzinfo=timezone.utc)  # 09:00 ET
    path = _write(tmp_path / "bars.csv", _rows(base=saturday))
    report = inspect_csv(path)
    assert report["ok"] is False
    assert any("día no hábil" in error for error in report["errors"])
    assert report["session_validation"]["sessions"][0]["trading_day"] is False


def test_holiday_bars_are_rejected(tmp_path: Path):
    july_fourth = datetime(2025, 7, 4, 13, 0, tzinfo=timezone.utc)  # 09:00 ET
    path = _write(tmp_path / "bars.csv", _rows(base=july_fourth))
    report = inspect_csv(path)
    assert report["ok"] is False
    assert any("día no hábil" in error for error in report["errors"])


def test_invalid_csv_blocks_engine_and_backtest(tmp_path: Path):
    path = _write(tmp_path / "bars.csv", _rows(count=100))
    settings = _settings(path)
    with pytest.raises(ValueError, match="incompleta"):
        run_backtest(settings, days=3)

    store = Store(tmp_path / "engine.db")
    try:
        engine = TradingEngine(store, settings)
        assert engine.feed is None
        assert "incompleta" in (engine.feed_error or "")
        ok, message = asyncio.run(engine.start())
        assert ok is False
        assert "incompleta" in message
    finally:
        store.close()


def test_missing_complete_session_blocks_replay_and_backtest(tmp_path: Path):
    # 2025-06-03 y 2025-06-05 completos; falta por completo el día hábil 06-04.
    rows = _rows() + _rows(base=BASE + timedelta(days=2))
    path = _write(tmp_path / "missing_session.csv", rows)

    report = inspect_csv(path)
    validation = report["session_validation"]
    assert report["ok"] is False
    assert validation["ok"] is False
    assert validation["missing_sessions"] == ["2025-06-04"]
    assert [s["date"] for s in validation["sessions"]] == [
        "2025-06-03",
        "2025-06-04",
        "2025-06-05",
    ]
    assert validation["sessions"][1]["missing_session"] is True
    assert any("completa ausente" in error for error in validation["errors"])

    with pytest.raises(ValueError, match="completa ausente"):
        CsvDataset.load(path)
    with pytest.raises(ValueError, match="completa ausente"):
        run_backtest(_settings(path), days=3)

    store = Store(tmp_path / "missing_engine.db")
    try:
        engine = TradingEngine(store, _settings(path))
        assert engine.feed is None
        assert "completa ausente" in (engine.feed_error or "")
        ok, message = asyncio.run(engine.start())
        assert ok is False
        assert "completa ausente" in message
    finally:
        store.close()


def test_unexpected_early_close_is_rejected_with_an_explicit_reason(tmp_path: Path):
    path = _write(tmp_path / "early_close.csv", _rows(count=240))
    report = inspect_csv(path)
    session = report["session_validation"]["sessions"][0]

    assert report["ok"] is False
    assert session["scheduled_early_close"] is False
    assert session["truncated"] is True
    assert session["early_close"] is True
    assert session["bars_in_window"] == 240
    assert any("cierre anticipado" in error for error in report["session_validation"]["errors"])
    with pytest.raises(ValueError, match="cierre anticipado"):
        CsvDataset.load(path)
    with pytest.raises(ValueError, match="cierre anticipado"):
        run_backtest(_settings(path), days=3)


@pytest.mark.parametrize(
    ("day", "end", "bars"),
    [
        (date(2025, 7, 3), "13:00", 240),
        (date(2025, 11, 28), "13:15", 255),
        (date(2025, 12, 24), "13:15", 255),
        (date(2026, 11, 27), "13:15", 255),
        (date(2026, 12, 24), "13:15", 255),
    ],
)
def test_cme_early_close_sessions_are_accepted(
    tmp_path: Path, day: date, end: str, bars: int
):
    path = _write(tmp_path / f"cme_early_close_{day}.csv", _session_rows(day, end))
    report = inspect_csv(path)
    validation = report["session_validation"]
    session = validation["sessions"][0]

    assert report["ok"] is True, report["errors"]
    assert session["valid"] is True
    assert session["scheduled_early_close"] is True
    assert session["early_close"] is True
    assert session["expected_end"] == end
    assert session["expected_bars"] == bars
    assert session["bars_in_window"] == bars
    assert session["missing_bars"] == 0
    assert session["or_complete"] is True
    assert validation["early_close_sessions"] == [day.isoformat()]

    if day >= HOLDOUT_START:
        # Estas fechas posteriores al protocolo solo prueban el calendario; el
        # validador las acepta, pero el motor no carga nada desde 2026-07-01.
        with pytest.raises(ValueError, match="holdout sellado"):
            CsvDataset.load(path)
    else:
        dataset = CsvDataset.load(path)
        assert len(dataset) == bars
        assert dataset.report["session_validation"]["ok"] is True


def test_cme_early_close_still_rejects_a_truncated_session(tmp_path: Path):
    # El 28/11/2025 el cierre oficial es 13:15 ET: 240 velas se quedan 15
    # minutos cortas y deben seguir bloqueando el dataset.
    path = _write(
        tmp_path / "cme_early_close_truncated.csv",
        _session_rows(date(2025, 11, 28), "13:15", count=240),
    )
    report = inspect_csv(path)
    validation = report["session_validation"]
    session = validation["sessions"][0]

    assert report["ok"] is False
    assert validation["ok"] is False
    assert session["scheduled_early_close"] is True
    assert session["truncated"] is True
    assert session["valid"] is False
    assert session["missing_bars"] == 15
    assert session["first_missing"] == "2025-11-28 13:00"
    assert any("incompleta" in error for error in validation["errors"])
    with pytest.raises(ValueError, match="incompleta"):
        CsvDataset.load(path)


def test_omitted_cme_early_close_is_not_a_missing_session(tmp_path: Path):
    # 26/11 completo, 27/11 feriado, 28/11 cierre anticipado omitido, fin de
    # semana y 01/12 completo. La media sesión opcional no debe bloquear.
    rows = _session_rows(date(2025, 11, 26), "16:00") + _session_rows(
        date(2025, 12, 1), "16:00"
    )
    path = _write(tmp_path / "omitted_early_close.csv", rows)
    report = inspect_csv(path)
    validation = report["session_validation"]

    assert report["ok"] is True, report["errors"]
    assert validation["ok"] is True
    assert validation["missing_sessions"] == []
    assert validation["skipped_early_close_sessions"] == ["2025-11-28"]
    assert [session["date"] for session in validation["sessions"]] == [
        "2025-11-26",
        "2025-12-01",
    ]
    assert CsvDataset.load(path).report["session_validation"]["ok"] is True


def test_cme_early_close_does_not_block_backtest(tmp_path: Path):
    path = _write(
        tmp_path / "cme_early_close_backtest.csv",
        _session_rows(date(2025, 11, 28), "13:15"),
    )
    result = run_backtest(_settings(path), days=3)

    assert result["data_source"] == "csv"
    assert result["data_quality"] == "historical"
    assert result["dataset"]["sessions"]["dates"] == ["2025-11-28"]


def test_missing_only_the_final_minute_is_reported_as_incomplete(tmp_path: Path):
    path = _write(tmp_path / "missing_last_minute.csv", _rows(count=419))
    report = inspect_csv(path)
    session = report["session_validation"]["sessions"][0]

    assert report["ok"] is False
    assert session["early_close"] is False
    assert session["missing_bars"] == 1
    assert any("incompleta" in error for error in report["session_validation"]["errors"])


def test_premarket_is_optional_but_never_counts_as_an_rth_session(tmp_path: Path):
    premarket = BASE - timedelta(minutes=30)  # 08:30 ET

    only_premarket = _write(tmp_path / "premarket_only.csv", _rows(count=30, base=premarket))
    report = inspect_csv(only_premarket)
    session = report["session_validation"]["sessions"][0]
    assert report["ok"] is False
    assert session["premarket_bars"] == 30
    assert session["bars_in_window"] == 0
    assert session["or_complete"] is False
    assert any("sin velas RTH" in error for error in report["session_validation"]["errors"])
    with pytest.raises(ValueError, match="sin velas RTH"):
        CsvDataset.load(only_premarket)

    full_with_premarket = _write(
        tmp_path / "premarket_plus_rth.csv",
        _rows(count=450, base=premarket),
    )
    report = inspect_csv(full_with_premarket)
    session = report["session_validation"]["sessions"][0]
    assert report["ok"] is True
    assert session["premarket_bars"] == 30
    assert session["bars_in_window"] == 420
    assert session["or_complete"] is True
    assert CsvDataset.load(full_with_premarket).report["session_validation"]["ok"] is True


def test_synthetic_session_still_satisfies_rth_validation():
    data = build_session(BASE.date(), Settings())
    validation = validate_sessions(bar.ts for bar in data["NQ"])

    assert validation["ok"] is True
    assert validation["missing_sessions"] == []
    assert validation["sessions"][0]["bars_in_window"] == 420
    # El generador conserva su premarket 08:30–09:00 para el gráfico simulado.
    assert validation["sessions"][0]["premarket_bars"] == 30


def test_csv_feed_honors_start_date(tmp_path: Path):
    second = BASE + timedelta(days=1)  # 2025-06-04 09:00 ET
    path = _write(tmp_path / "two_sessions.csv", _rows() + _rows(base=second))

    settings = _settings(path)
    settings.feed.start_date = "2025-06-04"
    feed = CSVFeed(settings)
    tick = asyncio.run(feed.next_tick())

    assert tick is not None
    assert tick.ts == int(second.timestamp())
    assert all(
        datetime.fromtimestamp(bar.ts, tz=timezone.utc).date() == second.date()
        for bar in tick.bars.values()
    )


def test_csv_load_refuses_sessions_in_holdout_without_opt_in(tmp_path: Path):
    path = _write(
        tmp_path / "holdout.csv",
        _session_rows(date(2026, 7, 1), "16:00"),
    )
    # El CSV es válido como datos; lo que se bloquea es cargarlo para operar.
    with pytest.raises(ValueError, match="holdout sellado"):
        CsvDataset.load(path)
    with pytest.raises(ValueError, match="holdout sellado"):
        CSVFeed(_settings(path))
    # Solo el comando confirmatorio lo lee, con opt-in explícito.
    assert CsvDataset.load(path, allow_holdout=True).manifest["all_sessions"] == [
        "2026-07-01"
    ]


def test_backtest_refuses_csv_with_holdout_even_with_development_start(tmp_path: Path):
    path = _write(
        tmp_path / "dev_and_holdout.csv",
        _session_rows(date(2026, 6, 30), "16:00")
        + _session_rows(date(2026, 7, 1), "16:00"),
    )

    # La selección por fecha no basta: cargar el archivo ya mezcla el holdout.
    with pytest.raises(ValueError, match="holdout sellado"):
        prepare_dataset(_settings(path), days=3, start=date(2026, 6, 30))
    with pytest.raises(ValueError, match="holdout sellado"):
        run_backtest(_settings(path), days=3)
    with pytest.raises(ValueError, match="holdout sellado"):
        run_variants(_settings(path), days=3)

    sessions, source, _ = prepare_dataset(_settings(path), days=3, allow_holdout=True)
    assert source == "csv"
    assert [day.isoformat() for day, _ in sessions] == ["2026-06-30", "2026-07-01"]


def test_csv_feed_accepts_last_development_session(tmp_path: Path):
    path = _write(
        tmp_path / "development.csv",
        _session_rows(date(2026, 6, 30), "16:00"),
    )

    feed = CSVFeed(_settings(path))

    assert feed.manifest["all_sessions"] == ["2026-06-30"]


def test_synthetic_feed_still_starts_without_csv_validation():
    settings = Settings()
    settings.feed.start_date = "2025-06-03"
    settings.feed.replay_speed = 200

    feed = build_feed(settings)
    assert isinstance(feed, SimulatedFeed)
    tick = asyncio.run(feed.next_tick())
    assert tick is not None
    assert tick.ts == int(BASE.timestamp())
    assert set(tick.bars) == {"MNQ", "NQ", "ES"}


def test_invalid_start_date_is_rejected_by_simulated_feed():
    settings = Settings()
    settings.feed.start_date = "04/06/2025"

    with pytest.raises(ValueError, match="start_date inválida"):
        build_feed(settings)


def test_csv_feed_is_one_shot_even_if_loop_is_enabled(tmp_path: Path):
    path = _write(tmp_path / "bars.csv", _rows())
    settings = _settings(path)
    settings.feed.loop_sessions = True
    feed = CSVFeed(settings)
    feed.index = len(feed.dataset)

    assert asyncio.run(feed.next_tick()) is None

    feed.rewind()
    assert feed.index == 0


def test_invalid_csv_start_date_is_not_saved(tmp_path: Path, monkeypatch):
    path = _write(tmp_path / "bars.csv", _rows())
    settings = _settings(path)
    store = Store(tmp_path / "config.db")
    try:
        engine = TradingEngine(store, settings)
        monkeypatch.setattr("server.engine.save_settings", lambda _: None)

        ok, message = asyncio.run(engine.update_settings({"feed": {"start_date": "2025-06-10"}}))

        assert ok is False
        assert "posterior al último dato" in message
        assert engine.settings.feed.start_date == ""
        assert engine.feed is not None
    finally:
        store.close()


def test_valid_csv_start_date_rebuilds_feed(tmp_path: Path, monkeypatch):
    second = BASE + timedelta(days=1)
    path = _write(tmp_path / "two_sessions.csv", _rows() + _rows(base=second))
    settings = _settings(path)
    store = Store(tmp_path / "config.db")
    try:
        engine = TradingEngine(store, settings)
        monkeypatch.setattr("server.engine.save_settings", lambda _: None)

        ok, _ = asyncio.run(engine.update_settings({"feed": {"start_date": "2025-06-04"}}))

        assert ok is True
        assert isinstance(engine.feed, CSVFeed)
        tick = asyncio.run(engine.feed.next_tick())
        assert tick is not None
        assert tick.ts == int(second.timestamp())
    finally:
        store.close()


def test_duplicate_timestamp_is_rejected(tmp_path: Path):
    rows = _rows()
    path = _write(tmp_path / "bars.csv", rows + [rows[0]])
    with pytest.raises(ValueError, match="duplicado"):
        load_bars(path)


def test_incoherent_ohlc_is_rejected(tmp_path: Path):
    rows = _rows()
    ts = BASE.isoformat()
    rows[0] = f"{ts},MNQ,20840,20841,20839,20850,100"
    path = _write(tmp_path / "bars.csv", rows)
    with pytest.raises(ValueError, match="OHLC"):
        load_bars(path)


def test_naive_timestamp_is_rejected(tmp_path: Path):
    rows = _rows()
    rows[0] = rows[0].replace(BASE.isoformat(), "2025-06-03T09:00:00")
    path = _write(tmp_path / "bars.csv", rows)
    with pytest.raises(ValueError, match="zona horaria"):
        load_bars(path)


def test_epoch_seconds_are_accepted(tmp_path: Path):
    rows = []
    for i in range(420):
        ts = int((BASE + timedelta(minutes=i)).timestamp())
        for symbol, price_base in (("MNQ", 20_840.0), ("NQ", 20_843.0), ("ES", 5_730.0)):
            price = price_base + i
            rows.append(f"{ts},{symbol},{price},{price + 2},{price - 2},{price + 1},1")
    path = _write(tmp_path / "bars.csv", rows)
    assert inspect_csv(path)["ok"] is True


def test_epoch_milliseconds_are_rejected(tmp_path: Path):
    rows = _rows()
    rows[0] = rows[0].replace(BASE.isoformat(), str(int(BASE.timestamp() * 1000)))
    path = _write(tmp_path / "bars.csv", rows)
    with pytest.raises(ValueError, match="milisegundos"):
        load_bars(path)


def test_missing_file_reports_error(tmp_path: Path):
    report = inspect_csv(tmp_path / "nope.csv")
    assert report["ok"] is False
    assert "No se encontró" in report["errors"][0]
