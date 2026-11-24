"""Calendario, selección de contrato activo y series continuas por roll."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from server.backtest import run_backtest
from server.config import Settings
from server.db import Store
from server.execution import ExecutionEngine
from server.market.contracts import (
    ContractSpec,
    default_expiry,
    parse_contract,
    select_active_contract,
)
from server.market.csv_data import CsvDataset, inspect_csv
from server.market.feed import CSVFeed
from server.market.synthetic import build_session
from server.models import Bar, Signal, TradeRecord
from server.timeutil import et_date

DAYS = [date(2025, 6, 3), date(2025, 6, 4), date(2025, 6, 5)]
ROLL_DAYS = [*DAYS, date(2025, 6, 6)]
OLD = "M25"  # vence 2025-06-20
NEW = "U25"  # vence 2025-09-19
OLD_EXPIRY = "2025-06-20"
NEW_EXPIRY = "2025-09-19"
BARS_PER_DAY = len(build_session(DAYS[0], Settings())["MNQ"])


def _write_roll_csv(
    path: Path,
    *,
    days: list[date] = ROLL_DAYS,
    roll_shift: float = 10.0,
    roll_shifts: dict[str, float] | None = None,
    roll_day_index: int = 2,
    truncate_roll: bool = False,
) -> Path:
    settings = Settings()
    rows = ["timestamp,symbol,open,high,low,close,volume,contract,expiry"]
    for index, day in enumerate(days):
        suffix = OLD if index <= roll_day_index else NEW
        expiry = OLD_EXPIRY if suffix == OLD else NEW_EXPIRY
        data = build_session(day, settings)
        count = 100 if truncate_roll and index == roll_day_index else len(data["MNQ"])
        for symbol in ("MNQ", "NQ", "ES"):
            if suffix == NEW:
                shift = roll_shifts.get(symbol, 0.0) if roll_shifts is not None else roll_shift
            else:
                shift = 0.0
            for bar in data[symbol][:count]:
                rows.append(
                    ",".join(
                        [
                            str(bar.ts),
                            symbol,
                            f"{bar.open + shift:.4f}",
                            f"{bar.high + shift:.4f}",
                            f"{bar.low + shift:.4f}",
                            f"{bar.close + shift:.4f}",
                            f"{bar.volume:.2f}",
                            f"{symbol}{suffix}",
                            expiry,
                        ]
                    )
                )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _settings(path: Path) -> Settings:
    settings = Settings()
    settings.feed.provider = "csv"
    settings.feed.csv_path = str(path)
    settings.feed.replay_speed = 200
    return settings


def test_contract_calendar_uses_third_friday_and_parses_codes():
    assert default_expiry(2025, 6) == date(2025, 6, 20)
    assert default_expiry(2025, 9) == date(2025, 9, 19)
    # El tercer viernes de abril de 2025 es Viernes Santo: vence el día hábil anterior.
    assert default_expiry(2025, 4) == date(2025, 4, 17)
    spec = parse_contract("MNQZ26", "MNQ")
    assert spec.root == "MNQ"
    assert spec.month == 12
    assert spec.year == 2026
    assert spec.expiry == date(2026, 12, 18)
    assert parse_contract("ESU27", "ES").expiry == date(2027, 9, 17)
    with pytest.raises(ValueError, match="no corresponde"):
        parse_contract("NQZ26", "MNQ")


def test_active_contract_is_nearest_unexpired_and_rolls_after_expiry():
    m25 = ContractSpec("MNQM25", "MNQ", 6, 2025, date(2025, 6, 20))
    u25 = ContractSpec("MNQU25", "MNQ", 9, 2025, date(2025, 9, 19))
    assert select_active_contract([u25, m25], date(2025, 6, 3)) is m25
    assert select_active_contract([u25, m25], date(2025, 6, 20)) is m25
    assert select_active_contract([u25, m25], date(2025, 6, 23)) is u25
    assert select_active_contract([m25], date(2025, 6, 23)) is None


def test_csv_selection_raw_adjusted_and_roll_exclusion(tmp_path: Path):
    path = _write_roll_csv(tmp_path / "rolls.csv")

    dataset = CsvDataset.load(path)
    assert dataset.series_mode == "adjusted"
    assert len(dataset) == 3 * BARS_PER_DAY  # el 5 de junio es la sesión de roll
    assert dataset.manifest["roll_sessions"] == ["2025-06-05"]
    assert dataset.excluded_sessions == ["2025-06-05"]
    assert dataset.manifest["sessions"] == ["2025-06-03", "2025-06-04", "2025-06-06"]
    assert dataset.manifest["all_sessions"] == [
        "2025-06-03",
        "2025-06-04",
        "2025-06-05",
        "2025-06-06",
    ]
    assert dataset.contracts == {
        "ES": ["ESM25", "ESU25"],
        "MNQ": ["MNQM25", "MNQU25"],
        "NQ": ["NQM25", "NQU25"],
    }
    assert dataset.manifest["contract_expiries"]["MNQM25"] == OLD_EXPIRY
    assert dataset.manifest["contracts_by_session"]["2025-06-03"]["MNQ"] == "MNQM25"
    assert dataset.manifest["contracts_by_session"]["2025-06-04"]["MNQ"] == "MNQM25"
    assert dataset.manifest["contracts_by_session"]["2025-06-06"]["MNQ"] == "MNQU25"
    assert "2025-06-05" not in dataset.manifest["contracts_by_session"]
    assert dataset.manifest["all_contracts_by_session"]["2025-06-05"]["MNQ"] == "MNQM25"
    assert dataset.report["session_validation"]["ok"] is True
    assert dataset.report["session_validation"]["sessions"][-1]["date"] == "2025-06-06"
    assert dataset.manifest["dataset_id"]
    assert dataset.manifest["series_id"]

    raw_all = CsvDataset.load(path, series_mode="raw", exclude_roll_sessions=False)
    adjusted_all = CsvDataset.load(path, series_mode="adjusted", exclude_roll_sessions=False)
    assert len(raw_all) == 4 * BARS_PER_DAY
    assert raw_all.manifest["excluded_sessions"] == []
    assert raw_all.manifest["roll_sessions"] == ["2025-06-05"]
    assert raw_all.manifest["rolls"][0]["excluded"] is False
    assert adjusted_all.manifest["rolls"][0]["excluded"] is False
    assert raw_all.series_id != adjusted_all.series_id

    event = adjusted_all.manifest["rolls"][0]
    offset = event["offsets"]["MNQ"]
    assert event["from"]["MNQ"] == "MNQM25"
    assert event["to"]["MNQ"] == "MNQU25"
    assert event["methods"]["MNQ"] in {"boundary", "overlap"}
    assert offset != 0
    assert event["basis_symbol"] == "MNQ"
    assert event["applied_offsets"]["MNQ"] == offset
    assert event["applied_offsets"]["NQ"] == offset
    assert event["basis_residual"]["NQ"] == 0.0

    # Las barras del contrato antiguo se desplazan; las del nuevo no.
    first_new_ts = next(
        tick["NQ"].ts for tick in adjusted_all.bars if et_date(tick["NQ"].ts) == ROLL_DAYS[3]
    )
    for raw_tick, adj_tick in zip(raw_all.bars, adjusted_all.bars):
        if adj_tick["NQ"].ts < first_new_ts:
            assert adj_tick["MNQ"].open == pytest.approx(raw_tick["MNQ"].open + offset)
        else:
            assert adj_tick["MNQ"].open == pytest.approx(raw_tick["MNQ"].open)

    # La serie por defecto ajusta el contrato saliente y excluye el roll.
    raw_selected = CsvDataset.load(path, series_mode="raw")
    for adj_tick, raw_tick in zip(dataset.bars, raw_selected.bars):
        expected = raw_tick["MNQ"].open + (
            offset if raw_tick["NQ"].ts < first_new_ts else 0.0
        )
        assert adj_tick["MNQ"].open == pytest.approx(expected)

    report = inspect_csv(path)
    assert report["ok"] is True
    assert report["series_mode"] == "adjusted"
    assert report["roll_sessions"] == ["2025-06-05"]
    assert report["excluded_sessions"] == ["2025-06-05"]
    assert report["common_bars"] == 3 * BARS_PER_DAY
    assert report["all_common_bars"] == 4 * BARS_PER_DAY


def test_adjusted_series_preserves_nq_mnq_basis(tmp_path: Path):
    # Offsets distintos por raiz: antes del arreglo NQ y MNQ quedaban con bases
    # separadas; ahora el par comparte el offset de ejecucion de MNQ.
    path = _write_roll_csv(
        tmp_path / "basis.csv",
        roll_shifts={"MNQ": 10.0, "NQ": 12.5, "ES": 3.0},
    )
    raw = CsvDataset.load(path, series_mode="raw")
    adjusted = CsvDataset.load(path, series_mode="adjusted")
    event = adjusted.manifest["rolls"][0]

    assert event["basis_symbol"] == "MNQ"
    mnq_offset = event["offsets"]["MNQ"]
    nq_offset = event["offsets"]["NQ"]
    es_offset = event["offsets"]["ES"]
    assert nq_offset != mnq_offset
    assert event["applied_offsets"]["MNQ"] == pytest.approx(mnq_offset)
    assert event["applied_offsets"]["NQ"] == pytest.approx(mnq_offset)
    assert event["applied_offsets"]["ES"] == pytest.approx(es_offset)
    assert event["basis_residual"]["NQ"] == pytest.approx(nq_offset - mnq_offset)
    assert event["basis_residual"]["MNQ"] == pytest.approx(0.0)

    first_new_ts = next(
        tick["NQ"].ts for tick in adjusted.bars if et_date(tick["NQ"].ts) == ROLL_DAYS[3]
    )
    for raw_tick, adj_tick in zip(raw.bars, adjusted.bars):
        assert adj_tick["NQ"].close - adj_tick["MNQ"].close == pytest.approx(
            raw_tick["NQ"].close - raw_tick["MNQ"].close
        )
        expected = mnq_offset if raw_tick["NQ"].ts < first_new_ts else 0.0
        assert adj_tick["NQ"].close == pytest.approx(raw_tick["NQ"].close + expected)
        assert adj_tick["MNQ"].close == pytest.approx(raw_tick["MNQ"].close + expected)
        expected_es = es_offset if raw_tick["ES"].ts < first_new_ts else 0.0
        assert adj_tick["ES"].close == pytest.approx(raw_tick["ES"].close + expected_es)


def test_feed_and_backtest_use_configured_series_and_exclude_roll(tmp_path: Path):
    path = _write_roll_csv(tmp_path / "rolls.csv")
    settings = _settings(path)
    settings.feed.series_mode = "raw"
    feed = CSVFeed(settings)
    info = feed.describe()
    assert info["series_mode"] == "raw"
    assert info["series_id"] == feed.dataset.series_id
    assert info["roll_sessions"] == ["2025-06-05"]
    assert info["excluded_sessions"] == ["2025-06-05"]
    assert info["sessions"] == 3
    assert info["bars"] == 3 * BARS_PER_DAY

    result = run_backtest(settings, days=3, label="rolls")
    provenance = result["dataset"]
    assert provenance["series_mode"] == "raw"
    assert provenance["series_id"] == feed.dataset.series_id
    assert provenance["roll_sessions"] == ["2025-06-05"]
    assert provenance["excluded_sessions"] == ["2025-06-05"]
    assert provenance["sessions"]["dates"] == ["2025-06-03", "2025-06-04", "2025-06-06"]
    assert provenance["contracts_by_session"]["2025-06-04"]["MNQ"] == "MNQM25"
    for trade in result["trades"]:
        assert trade.get("contract") in {None, "MNQM25", "MNQU25"}


def test_incomplete_roll_session_still_blocks_the_dataset(tmp_path: Path):
    path = _write_roll_csv(tmp_path / "bad_roll.csv", truncate_roll=True)
    report = inspect_csv(path)
    assert report["ok"] is False
    assert report["session_validation"]["ok"] is False
    assert any("2025-06-05" in error and "incompleta" in error for error in report["errors"])
    with pytest.raises(ValueError, match="incompleta"):
        CsvDataset.load(path)


def test_expiry_must_be_a_date_and_not_precede_the_bar(tmp_path: Path):
    settings = Settings()
    rows = ["timestamp,symbol,open,high,low,close,volume,contract,expiry"]
    for day in DAYS[:1]:
        data = build_session(day, settings)
        for symbol in ("MNQ", "NQ", "ES"):
            for bar in data[symbol]:
                rows.append(
                    f"{bar.ts},{symbol},{bar.open},{bar.high},{bar.low},{bar.close},{bar.volume},"
                    f"{symbol}M25,2025-06-02"
                )
    path = tmp_path / "expired.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="vencido"):
        CsvDataset.load(path)

    bad = tmp_path / "bad_expiry.csv"
    text = path.read_text(encoding="utf-8").replace("2025-06-02", "02/06/2025")
    bad.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match="expiry inválido"):
        CsvDataset.load(bad)


def test_expiry_without_contract_is_rejected(tmp_path: Path):
    settings = Settings()
    rows = ["timestamp,symbol,open,high,low,close,volume,expiry"]
    data = build_session(DAYS[0], settings)
    for symbol in ("MNQ", "NQ", "ES"):
        for bar in data[symbol]:
            rows.append(
                f"{bar.ts},{symbol},{bar.open},{bar.high},{bar.low},{bar.close},{bar.volume},2025-06-20"
            )
    path = tmp_path / "expiry_only.csv"
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="expiry requiere"):
        CsvDataset.load(path)


def test_old_feed_config_without_roll_fields_still_validates():
    old = Settings.model_validate(
        {
            "feed": {
                "provider": "csv",
                "csv_path": "data/bars.csv",
            }
        }
    )
    assert old.feed.series_mode == "adjusted"
    assert old.feed.exclude_roll_sessions is True


def test_old_trades_table_is_migrated_and_contract_roundtrips(tmp_path: Path):
    db_path = tmp_path / "old_trades.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE trades (id TEXT PRIMARY KEY, mode TEXT, symbol TEXT, direction TEXT, "
        "qty INTEGER, entry_ts INTEGER, entry_price REAL, exit_ts INTEGER, exit_price REAL, "
        "stop REAL, target REAL, pnl REAL, gross_pnl REAL, fees REAL, r_multiple REAL, "
        "risk_amount REAL, signal_type TEXT, entry_reason TEXT, exit_reason TEXT, "
        "duration_sec INTEGER, meta TEXT)"
    )
    conn.commit()
    conn.close()

    store = Store(db_path)
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(trades)").fetchall()}
        assert {"contract", "expiry"} <= columns
        trade = TradeRecord(
            id="t1",
            symbol="MNQ",
            direction="long",
            qty=1,
            entry_ts=100,
            entry_price=100.0,
            exit_ts=200,
            exit_price=101.0,
            stop=99.0,
            target=103.0,
            pnl=2.0,
            gross_pnl=2.0,
            fees=0.0,
            r_multiple=1.0,
            risk_amount=1.0,
            signal_type="ORB",
            entry_reason="test",
            exit_reason="target",
            duration_sec=100,
            contract="MNQM25",
            expiry=OLD_EXPIRY,
        )
        store.insert_trade(trade.as_dict())
        loaded = store.list_trades(limit=1)[0]
    finally:
        store.close()
    assert loaded["contract"] == "MNQM25"
    assert loaded["expiry"] == OLD_EXPIRY


def test_execution_trade_inherits_active_contract():
    engine = ExecutionEngine(Settings())
    signal = Signal(
        id="roll-signal",
        ts=1000,
        direction="long",
        entry_price=20_000,
        stop=19_990,
        target=20_030,
        qty=1,
        risk_amount=10,
        signal_type="ORB",
        entry_reason="test",
        reference_level=0,
        breakout_level=0,
        meta={"contract": "MNQM25", "expiry": OLD_EXPIRY},
    )
    engine.arm(signal)
    engine.on_bar(Bar(1000, 20_000, 20_001, 19_999, 20_000))
    engine.close(20_010, 1060, "manual")
    trade = engine.closed_trades[-1]
    assert trade.contract == "MNQM25"
    assert trade.expiry == OLD_EXPIRY
