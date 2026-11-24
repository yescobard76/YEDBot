"""Diagnóstico legacy de solo lectura antes de Store y de las migraciones."""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from server.diagnostics import diagnose_database, main

ROOT = Path(__file__).resolve().parents[1]
V1_FIXTURE = ROOT / "tests" / "fixtures" / "db" / "v1_real_yedbot.db"
V2_FIXTURE = ROOT / "tests" / "fixtures" / "db" / "v2_real_yedbot.db"
NEW_TABLES = {"schema_migrations", "backtest_runs", "backtest_results"}


def _read_rows(path: Path) -> list[dict]:
    with closing(sqlite3.connect(path)) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM backtests")]


def _tables(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as conn:
        return {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }


def _invalid_v1(tmp_path: Path, column: str, value: str) -> tuple[Path, str, list[dict]]:
    assert V1_FIXTURE.exists(), f"Falta el fixture v1 {V1_FIXTURE}"
    path = tmp_path / "invalid-v1.db"
    shutil.copyfile(V1_FIXTURE, path)
    with closing(sqlite3.connect(path)) as conn:
        legacy_id = conn.execute("SELECT id FROM backtests LIMIT 1").fetchone()[0]
        conn.execute(
            f"UPDATE backtests SET {column} = ? WHERE id = ?", (value, legacy_id)
        )
        conn.commit()
    return path, legacy_id, _read_rows(path)


@pytest.mark.parametrize(
    ("column", "value", "code"),
    [
        ("metrics", "{invalid", "metrics_invalid"),
        ("dataset", "[]", "dataset_invalid"),
        ("experiment", "{invalid", "experiment_invalid"),
        ("created_ts", "not-an-int", "created_ts_invalid"),
    ],
)
def test_preflight_explains_migration_blockers_without_migrating(
    tmp_path: Path, column: str, value: str, code: str
) -> None:
    path, legacy_id, before_rows = _invalid_v1(tmp_path, column, value)
    before_bytes = path.read_bytes()

    report = diagnose_database(path)

    assert report["read_only"] is True
    assert report["schema_version"] == 0
    assert report["migration_required"] is True
    assert report["migration_blocked"] is True
    assert report["migration_blockers"] == [legacy_id]
    assert report["total"] == 1
    assert report["indexed"] == 0
    assert report["unindexed"] == 1
    assert report["invalid"] == 1
    item = report["items"][0]
    assert item["id"] == legacy_id
    assert item["status"] == "invalid"
    assert item["migration_blocker"] is True
    assert code in {problem["code"] for problem in item["problems"]}

    # El preflight no abre Store ni escribe la base en modo alguno.
    assert path.read_bytes() == before_bytes
    assert _read_rows(path) == before_rows
    assert not (NEW_TABLES & _tables(path))
    assert not (tmp_path / "backups").exists()


def test_preflight_clean_v2_uses_index_without_migrating(tmp_path: Path) -> None:
    assert V2_FIXTURE.exists(), f"Falta el fixture v2 {V2_FIXTURE}"
    path = tmp_path / "clean-v2.db"
    shutil.copyfile(V2_FIXTURE, path)
    before_bytes = path.read_bytes()

    report = diagnose_database(path)

    assert report["schema_version"] == 2
    assert report["migration_required"] is True
    assert report["migration_blocked"] is False
    assert report["migration_blockers"] == []
    assert report["total"] == 1
    assert report["indexed"] == 1
    assert report["unindexed"] == 0
    assert report["invalid"] == 0
    assert report["items"] == []
    assert path.read_bytes() == before_bytes
    assert not (tmp_path / "backups").exists()


def test_preflight_cli_reports_blockers_without_migrating(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path, legacy_id, _ = _invalid_v1(tmp_path, "metrics", "{invalid")

    exit_code = main(["--db", str(path)])

    assert exit_code == 1
    report = json.loads(capsys.readouterr().out)
    assert report["migration_blocked"] is True
    assert report["migration_blockers"] == [legacy_id]
    assert not (NEW_TABLES & _tables(path))
    assert not (tmp_path / "backups").exists()
