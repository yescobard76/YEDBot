"""Migraciones v1/v2 -> v5 sobre copias reales de ``data/yedbot.db``.

Fase 0: ``v1_real_yedbot.db`` es una copia hecha en solo lectura desde la
base real (sha256 ``7fe7901b35e697ad7ec8fc80505f298065535ceeedd91d2641264015beb0b3bf``),
con las tablas operativas y una fila legacy en ``backtests``. El test queda
en rojo hasta que la migración cree ``schema_migrations``, ``backtest_runs``
y ``backtest_results``, haga el backfill mínimo y aborte con rollback ante un
JSON legacy inválido.

``v2_real_yedbot.db`` es una copia de esa base real después de aplicar solo
las migraciones 001 y 002 (sha256
``51d826fabe688a0a0d44d2714b8b7027dcc971ff6e021ec7c495a9f9b511cd0e``). Sirve
para comprobar que una base que ya está en v2 recibe las columnas de
idempotencia, su índice único parcial, el outbox del ledger, el vínculo al
evento del ledger y un backup v2 antes de aplicar las migraciones 003–005.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from server import migrations
from server.db import Store

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "db" / "v1_real_yedbot.db"
V2_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "db" / "v2_real_yedbot.db"
V2_TABLES = {"schema_migrations", "backtest_runs", "backtest_results"}
BASE_TABLES = ("trades", "events", "equity", "kv", "backtests")
V3_COLUMNS = {"idempotency_key", "idempotency_fingerprint"}


def _rows(conn: sqlite3.Connection, table: str) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }


def _unique_columns(conn: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    unique: set[tuple[str, ...]] = set()
    for index in conn.execute(f"PRAGMA index_list({table})"):
        if not index[2]:
            continue
        columns = tuple(
            row[2] for row in conn.execute(f"PRAGMA index_info({index[1]})")
        )
        unique.add(columns)
    return unique


def _copy_fixture(tmp_path: Path) -> Path:
    assert FIXTURE.exists(), f"Falta el fixture v1 {FIXTURE}"
    db_path = tmp_path / "v1_real.db"
    shutil.copy2(FIXTURE, db_path)
    return db_path


def _copy_v2_fixture(tmp_path: Path) -> Path:
    assert V2_FIXTURE.exists(), f"Falta el fixture v2 {V2_FIXTURE}"
    db_path = tmp_path / "v2_real.db"
    shutil.copy2(V2_FIXTURE, db_path)
    return db_path


def test_migrates_v1_database_with_backtests(tmp_path: Path) -> None:
    db_path = _copy_fixture(tmp_path)
    with closing(sqlite3.connect(db_path)) as conn:
        legacy = {table: _rows(conn, table) for table in BASE_TABLES}
        legacy_tables = _tables(conn)
        legacy_backtests_columns = _columns(conn, "backtests")

    assert legacy["backtests"], "El fixture debe contener al menos un backtest legacy"
    assert set(BASE_TABLES) <= legacy_tables
    assert not (V2_TABLES & legacy_tables)

    store = Store(db_path)
    try:
        missing = V2_TABLES - _tables(store._conn)
        assert not missing, f"Faltan tablas de la migracion: {sorted(missing)}"

        # La migración es aditiva: no toca el esquema ni las filas v1.
        assert _columns(store._conn, "backtests") == legacy_backtests_columns
        for table in BASE_TABLES:
            assert _rows(store._conn, table) == legacy[table], table

        run_columns = _columns(store._conn, "backtest_runs")
        assert "hypothesis_id" not in run_columns
        assert {"idempotency_key", "idempotency_fingerprint"} <= run_columns
        assert {"trades", "net_profit", "max_drawdown_pct"}.isdisjoint(run_columns)
        assert ("legacy_backtest_id",) in _unique_columns(
            store._conn, "backtest_runs"
        )
        assert ("primary_result_id",) in _unique_columns(
            store._conn, "backtest_runs"
        )
        assert ("idempotency_key",) in _unique_columns(store._conn, "backtest_runs")

        result_columns = _columns(store._conn, "backtest_results")
        assert "backtest_run_id" in result_columns
        assert "run_id" not in result_columns
        assert ("backtest_run_id", "result_key") in _unique_columns(
            store._conn, "backtest_results"
        )

        runs = _rows(store._conn, "backtest_runs")
        results = _rows(store._conn, "backtest_results")
        assert len(runs) == len(legacy["backtests"])
        assert len(results) == len(legacy["backtests"])

        runs_by_legacy = {row["legacy_backtest_id"]: row for row in runs}
        results_by_legacy = {row["id"]: row for row in results}
        for old in legacy["backtests"]:
            run = runs_by_legacy[old["id"]]
            result = results_by_legacy[old["id"]]
            metrics = json.loads(old["metrics"])

            assert run["id"] != old["id"]
            assert run["kind"] == "single"
            assert run["legacy_backtest_id"] == old["id"]
            assert run["primary_result_id"] == old["id"]
            assert run["result_count"] == 1
            assert run["payload_json"] is None

            assert result["backtest_run_id"] == run["id"]
            assert result["result_key"] == "single"
            assert result["payload_json"] is None
            assert json.loads(result["metrics_json"]) == metrics
            assert result["trades"] == metrics["trades"]
            assert result["net_profit"] == pytest.approx(metrics["net_profit"])
            assert result["max_drawdown_pct"] == pytest.approx(
                metrics["max_drawdown_pct"]
            )
            assert result["profit_factor"] == metrics.get("profit_factor")

        assert store._conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert store._conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[
            0
        ] >= 1

        # Los lectores actuales siguen devolviendo el payload completo legacy;
        # el bloque plano del ledger siempre está presente y es null sin outbox.
        old = legacy["backtests"][0]
        full = store.get_backtest(old["id"])
        assert full == {
            "ledger_status": None,
            "hypothesis_id": None,
            "ledger_event_id": None,
            "ledger_event_sha256": None,
            "ledger_error": None,
            "id": old["id"],
            "created_ts": old["created_ts"],
            "label": old["label"],
            "data_source": old["data_source"],
            "dataset": json.loads(old["dataset"]),
            "diagnostics": json.loads(old["diagnostics"]),
            "experiment": json.loads(old["experiment"]),
            "config": json.loads(old["config"]),
            "metrics": json.loads(old["metrics"]),
            "trades": json.loads(old["trades"]),
            "equity": json.loads(old["equity"]),
        }
        assert store.latest_backtest() == full

        runs_before = _rows(store._conn, "backtest_runs")
        results_before = _rows(store._conn, "backtest_results")
    finally:
        store.close()

    # Segunda apertura: la migración es idempotente.
    store = Store(db_path)
    try:
        assert _rows(store._conn, "backtest_runs") == runs_before
        assert _rows(store._conn, "backtest_results") == results_before
        assert _rows(store._conn, "backtests") == legacy["backtests"]
    finally:
        store.close()


def test_migration_creates_pre_migration_backup(tmp_path: Path) -> None:
    db_path = _copy_fixture(tmp_path)
    with closing(sqlite3.connect(db_path)) as conn:
        legacy = {table: _rows(conn, table) for table in BASE_TABLES}

    store = Store(db_path)
    try:
        assert V2_TABLES <= _tables(store._conn)
    finally:
        store.close()

    backups = sorted((tmp_path / "backups").glob("pre-migration-v5-*.db"))
    assert len(backups) == 1, backups

    with closing(sqlite3.connect(backups[0])) as backup:
        tables = _tables(backup)
        assert set(BASE_TABLES) <= tables
        for table in BASE_TABLES:
            assert _rows(backup, table) == legacy[table], table
        assert not (V2_TABLES & tables)


def test_migrates_v2_database_to_v5_with_idempotency_outbox_and_backup(
    tmp_path: Path,
) -> None:
    db_path = _copy_v2_fixture(tmp_path)
    tracked = (*BASE_TABLES, *sorted(V2_TABLES))

    with closing(sqlite3.connect(db_path)) as conn:
        assert V2_TABLES <= _tables(conn)
        assert _columns(conn, "backtest_runs").isdisjoint(V3_COLUMNS)
        assert "idx_backtest_runs_idempotency" not in {
            row[1] for row in conn.execute("PRAGMA index_list(backtest_runs)")
        }
        assert [row[0] for row in conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )] == [1, 2]
        v2_columns = {table: _columns(conn, table) for table in tracked}
        v2_rows = {table: _rows(conn, table) for table in tracked}
        assert v2_rows["backtest_runs"], "El fixture v2 debe conservar las corridas"
        assert v2_rows["backtest_results"], "El fixture v2 debe conservar los resultados"

    store = Store(db_path)
    try:
        run_columns = _columns(store._conn, "backtest_runs")
        assert V3_COLUMNS <= run_columns
        column_types = {
            row[1]: row[2]
            for row in store._conn.execute("PRAGMA table_info(backtest_runs)")
        }
        assert {column_types[column] for column in V3_COLUMNS} == {"TEXT"}

        indexes = {
            row[1]: row
            for row in store._conn.execute("PRAGMA index_list(backtest_runs)")
        }
        assert "idx_backtest_runs_idempotency" in indexes
        idempotency_index = indexes["idx_backtest_runs_idempotency"]
        assert idempotency_index[2] == 1, "el índice debe ser UNIQUE"
        assert idempotency_index[4] == 1, "el índice debe ser parcial"
        assert tuple(
            row[2]
            for row in store._conn.execute(
                f"PRAGMA index_info({idempotency_index[1]})"
            )
        ) == ("idempotency_key",)
        index_sql = store._conn.execute(
            "SELECT sql FROM sqlite_master "
            "WHERE type = 'index' AND name = 'idx_backtest_runs_idempotency'"
        ).fetchone()[0]
        assert "WHERE idempotency_key IS NOT NULL" in " ".join(index_sql.split())

        assert [row[0] for row in store._conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )] == [1, 2, 3, 4, 5]
        assert "backtest_ledger_outbox" in _tables(store._conn)
        assert {"ledger_event_id", "ledger_event_sha256"} <= _columns(
            store._conn, "backtest_ledger_outbox"
        )
        outbox_indexes = {
            row[1]: row
            for row in store._conn.execute(
                "PRAGMA index_list(backtest_ledger_outbox)"
            )
        }
        assert "idx_backtest_ledger_outbox_event" in outbox_indexes
        event_index = outbox_indexes["idx_backtest_ledger_outbox_event"]
        assert event_index[2] == 1, "el índice del evento debe ser UNIQUE"
        assert event_index[4] == 1, "el índice del evento debe ser parcial"

        # v5 es aditiva: conserva las filas y columnas de la base v2.
        for table in tracked:
            after = _rows(store._conn, table)
            assert len(after) >= len(v2_rows[table])
            assert [
                {column: row[column] for column in v2_columns[table]}
                for row in after[: len(v2_rows[table])]
            ] == v2_rows[table], table
        assert all(
            row["idempotency_key"] is None
            and row["idempotency_fingerprint"] is None
            for row in _rows(store._conn, "backtest_runs")
        )

        # El índice único impide reutilizar una clave no nula.
        store._conn.execute(
            "INSERT INTO backtest_runs ("
            "id, created_ts, kind, label, data_source, result_count, "
            "idempotency_key"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("v3-duplicate-a", 1, "single", "a", "synthetic", 0, "dup-key"),
        )
        with pytest.raises(sqlite3.IntegrityError):
            store._conn.execute(
                "INSERT INTO backtest_runs ("
                "id, created_ts, kind, label, data_source, result_count, "
                "idempotency_key"
                ") VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("v3-duplicate-b", 2, "single", "b", "synthetic", 0, "dup-key"),
            )
        store._conn.rollback()
    finally:
        store.close()

    backups = sorted((tmp_path / "backups").glob("pre-migration-v5-*.db"))
    assert len(backups) == 1, backups
    with closing(sqlite3.connect(backups[0])) as backup:
        assert V2_TABLES <= _tables(backup)
        assert "backtest_ledger_outbox" not in _tables(backup)
        assert _columns(backup, "backtest_runs").isdisjoint(V3_COLUMNS)
        assert "idx_backtest_runs_idempotency" not in {
            row[1] for row in backup.execute("PRAGMA index_list(backtest_runs)")
        }
        assert [row[0] for row in backup.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )] == [1, 2]
        for table in tracked:
            assert _rows(backup, table) == v2_rows[table], table


def test_migrates_v4_outbox_to_v5_preserving_the_existing_row(tmp_path: Path) -> None:
    db_path = tmp_path / "v4.db"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute(
            "CREATE TABLE schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_ts INTEGER NOT NULL, "
            "checksum TEXT NOT NULL)"
        )
        for version in range(1, 5):
            conn.execute(
                "INSERT INTO schema_migrations (version, applied_ts, checksum) "
                "VALUES (?, ?, ?)",
                (version, 1, "fixture"),
            )
        conn.executescript(migrations.V4_SCHEMA)
        conn.execute(
            "INSERT INTO backtest_ledger_outbox ("
            "backtest_run_id, result_id, hypothesis_id, status, attempts, "
            "created_ts, updated_ts"
            ") VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("run-v4", "result-v4", "H-V4", "pending", 2, 10, 20),
        )
        conn.commit()

    store = Store(db_path)
    try:
        assert {"ledger_event_id", "ledger_event_sha256"} <= _columns(
            store._conn, "backtest_ledger_outbox"
        )
        row = _rows(store._conn, "backtest_ledger_outbox")[0]
        assert row["backtest_run_id"] == "run-v4"
        assert row["status"] == "pending"
        assert row["ledger_event_id"] is None
        assert row["ledger_event_sha256"] is None
        assert [item[0] for item in store._conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        )] == [1, 2, 3, 4, 5]
    finally:
        store.close()


def test_migration_rolls_back_on_invalid_legacy_json(tmp_path: Path) -> None:
    db_path = _copy_fixture(tmp_path)
    with closing(sqlite3.connect(db_path)) as conn:
        old = _rows(conn, "backtests")[0]
        conn.execute(
            "UPDATE backtests SET metrics = ? WHERE id = ?", ("{invalid", old["id"])
        )
        conn.commit()
        before = {table: _rows(conn, table) for table in BASE_TABLES}

    # El plan fija el id en el error y el rollback, no la clase de excepción.
    with pytest.raises(Exception, match=old["id"]):
        Store(db_path)

    with closing(sqlite3.connect(db_path)) as conn:
        assert {table: _rows(conn, table) for table in BASE_TABLES} == before
        tables = _tables(conn)
        for table in V2_TABLES:
            if table in tables:
                count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                assert count == 0, table
