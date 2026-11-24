"""Reproducibilidad y procedencia de los datasets usados en backtest."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from server.backtest import run_backtest, run_variants
from server.config import Settings
from server.db import Store
from server.market.csv_data import CsvDataset, inspect_csv
from server.market.feed import CSVFeed
from server.market.synthetic import build_session


def _write_sessions(
    path: Path,
    days: list[date],
    *,
    with_contract: bool = False,
    volume_bump: float = 0.0,
) -> Path:
    """Exporta sesiones sintéticas a CSV para probar la capa de procedencia."""
    settings = Settings()
    header = "timestamp,symbol,open,high,low,close,volume"
    if with_contract:
        header += ",contract"
    rows = [header]
    for day in days:
        data = build_session(day, settings)
        for symbol in ("MNQ", "NQ", "ES"):
            for index, bar in enumerate(data[symbol]):
                volume = bar.volume + (volume_bump if symbol == "NQ" and index == 0 else 0.0)
                values = [str(bar.ts), symbol, f"{bar.open:.4f}", f"{bar.high:.4f}", f"{bar.low:.4f}", f"{bar.close:.4f}", f"{volume:.2f}"]
                if with_contract:
                    values.append(f"{symbol}Z26")
                rows.append(",".join(values))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _settings(path: Path) -> Settings:
    settings = Settings()
    settings.feed.provider = "csv"
    settings.feed.csv_path = str(path)
    settings.feed.replay_speed = 200
    return settings


def _trade_signature(result: dict) -> list[tuple]:
    return [
        (
            trade["symbol"],
            trade["direction"],
            trade["qty"],
            trade["entry_ts"],
            trade["entry_price"],
            trade["exit_ts"],
            trade["exit_price"],
            trade["pnl"],
            trade["r_multiple"],
        )
        for trade in result["trades"]
    ]


def test_dataset_identity_is_content_based_and_path_independent(tmp_path: Path):
    days = [date(2025, 6, 3), date(2025, 6, 4)]
    first = _write_sessions(tmp_path / "first.csv", days)
    second = _write_sessions(tmp_path / "second.csv", days)
    changed = _write_sessions(tmp_path / "changed.csv", days, volume_bump=1.0)

    a = CsvDataset.load(first)
    b = CsvDataset.load(second)
    c = CsvDataset.load(changed)

    assert a.dataset_id == b.dataset_id
    assert a.file_hash == b.file_hash
    assert a.dataset_id != c.dataset_id
    assert a.file_hash != c.file_hash
    assert a.manifest["row_count"] == b.manifest["row_count"]
    assert a.manifest["range"]["first_ts"] < a.manifest["range"]["last_ts"]
    assert a.manifest["session_count"] == 2
    assert a.manifest["sessions"] == ["2025-06-03", "2025-06-04"]


def test_optional_contract_is_recorded_in_manifest_and_feed(tmp_path: Path):
    path = _write_sessions(tmp_path / "contracts.csv", [date(2025, 6, 3)], with_contract=True)
    dataset = CsvDataset.load(path)
    assert dataset.contracts == {"ES": ["ESZ26"], "MNQ": ["MNQZ26"], "NQ": ["NQZ26"]}
    assert dataset.manifest["contract_column"] is True
    assert dataset.manifest["contracts_declared"] is True

    feed = CSVFeed(_settings(path))
    info = feed.describe()
    assert info["dataset_id"] == dataset.dataset_id
    assert info["contracts"]["NQ"] == ["NQZ26"]
    assert info["schema_version"] == "1.1"


def test_csv_backtest_saves_identity_range_contracts_and_full_config(tmp_path: Path):
    path = _write_sessions(tmp_path / "bars.csv", [date(2025, 6, 3), date(2025, 6, 4)], with_contract=True)
    result = run_backtest(_settings(path), days=3, label="procedencia")

    dataset = result["dataset"]
    assert result["dataset_id"] == dataset["id"]
    assert dataset["kind"] == "csv"
    assert dataset["file_hash"]
    assert dataset["contracts"]["MNQ"] == ["MNQZ26"]
    assert dataset["range"]["first_ts"] == dataset["selected_range"]["first_ts"]
    assert dataset["sessions"]["count"] == 2
    assert dataset["sessions"]["dates"] == ["2025-06-03", "2025-06-04"]
    assert dataset["selection"] == "last_n"
    assert dataset["code"]["algorithm"] == "sha256-tree-v1"
    assert len(dataset["code"]["sha256"]) == 64
    assert dataset["code"]["files"] >= 1

    assert result["config"]["feed"]["provider"] == "csv"
    assert result["config"]["feed"]["csv_path"] == str(path)
    assert result["config"]["execution"]["commission_per_contract_side"] == pytest.approx(0.62)
    assert result["config"]["execution"]["slippage_ticks"] == 1

    overridden = run_backtest(
        _settings(path),
        days=3,
        overrides={"execution": {"commission_per_contract_side": 1.25, "slippage_ticks": 3}},
    )
    assert overridden["config"]["execution"]["commission_per_contract_side"] == pytest.approx(1.25)
    assert overridden["config"]["execution"]["slippage_ticks"] == 3
    assert overridden["dataset"]["id"] == result["dataset"]["id"]


def test_csv_start_date_is_applied_and_recorded(tmp_path: Path):
    path = _write_sessions(
        tmp_path / "bars.csv",
        [date(2025, 6, 3), date(2025, 6, 4), date(2025, 6, 5)],
    )
    result = run_backtest(_settings(path), days=3, start=date(2025, 6, 4))
    dataset = result["dataset"]
    assert dataset["requested_start"] == "2025-06-04"
    assert dataset["selection"] == "start_date"
    assert dataset["sessions"]["count"] == 2
    assert dataset["sessions"]["dates"] == ["2025-06-04", "2025-06-05"]
    assert dataset["selected_range"]["first_et"].startswith("2025-06-04")
    assert result["config"]["days"] == 2


def test_csv_start_date_outside_range_is_rejected(tmp_path: Path):
    path = _write_sessions(tmp_path / "bars.csv", [date(2025, 6, 3), date(2025, 6, 4)])
    with pytest.raises(ValueError, match="fuera del rango"):
        run_backtest(_settings(path), days=3, start=date(2025, 6, 10))
    with pytest.raises(ValueError, match="fuera del rango"):
        run_backtest(_settings(path), days=3, start=date(2025, 6, 1))


def test_same_dataset_and_config_are_reproducible(tmp_path: Path):
    path = _write_sessions(tmp_path / "bars.csv", [date(2025, 6, 3), date(2025, 6, 4)])
    settings = _settings(path)
    first = run_backtest(settings, days=3)
    second = run_backtest(settings, days=3)

    assert first["dataset"]["id"] == second["dataset"]["id"]
    assert first["dataset"]["selected_id"] == second["dataset"]["selected_id"]
    assert first["dataset"]["code"] == second["dataset"]["code"]
    assert first["metrics"] == second["metrics"]
    assert _trade_signature(first) == _trade_signature(second)


def test_backtest_provenance_survives_sqlite_roundtrip(tmp_path: Path):
    path = _write_sessions(tmp_path / "bars.csv", [date(2025, 6, 3)])
    result = run_backtest(_settings(path), days=3)
    store = Store(tmp_path / "provenance.db")
    try:
        store.save_backtest(result)
        loaded = store.latest_backtest()
    finally:
        store.close()

    assert loaded is not None
    assert loaded["dataset"]["id"] == result["dataset"]["id"]
    assert loaded["dataset"]["file_hash"] == result["dataset"]["file_hash"]
    assert loaded["dataset"]["contracts"] == result["dataset"]["contracts"]
    assert loaded["config"]["execution"] == result["config"]["execution"]
    assert loaded["diagnostics"] == result["diagnostics"]
    assert loaded["experiment"] == result["experiment"]


def test_variants_share_the_same_dataset_identity(tmp_path: Path):
    path = _write_sessions(tmp_path / "bars.csv", [date(2025, 6, 3), date(2025, 6, 4)])
    results = run_variants(_settings(path), days=3)
    ids = {result["dataset"]["id"] for result in results}
    assert len(results) == 4
    assert len(ids) == 1
    assert all(result["dataset"]["selected_id"] for result in results)


def test_validation_report_exposes_provenance(tmp_path: Path):
    path = _write_sessions(tmp_path / "bars.csv", [date(2025, 6, 3)])
    report = inspect_csv(path)
    assert report["ok"] is True
    assert report["dataset_id"]
    assert report["file_hash"]
    assert report["contracts"] == {"ES": [], "MNQ": [], "NQ": []}
    assert report["session_count"] == 1
    assert report["manifest"]["dataset_id"] == report["dataset_id"]


def test_store_migrates_old_backtests_table(tmp_path: Path):
    db_path = tmp_path / "old.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE backtests (id TEXT PRIMARY KEY, created_ts INTEGER NOT NULL, "
        "label TEXT NOT NULL, data_source TEXT NOT NULL, config TEXT NOT NULL, "
        "metrics TEXT NOT NULL, trades TEXT NOT NULL, equity TEXT NOT NULL)"
    )
    conn.commit()
    conn.close()

    store = Store(db_path)
    try:
        columns = {row[1] for row in store._conn.execute("PRAGMA table_info(backtests)").fetchall()}
    finally:
        store.close()
    assert "dataset" in columns
    assert "diagnostics" in columns
    assert "experiment" in columns
