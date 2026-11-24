"""Migraciones aditivas de la base SQLite.

La versión 001 registra el esquema base y completa las columnas aditivas que
pueden faltar en bases antiguas. La versión 002 crea ``backtest_runs`` y
``backtest_results`` y hace el backfill mínimo de ``backtests``. La versión 003
añade la idempotencia opcional de las peticiones de backtest. La versión 004
añade el outbox que relaciona una corrida persistida con su registro de
hipótesis en el ledger. La versión 005 guarda el ``event_id`` y el hash del
registro exacto del ledger en ese outbox.

La migración nunca renombra, reconstruye ni escribe ``backtests``. El backfill
solo copia el índice y las métricas; ``trades``, ``equity``, ``config`` y
``diagnostics`` siguen viviendo en la fila legacy.
"""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 5

BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    mode TEXT NOT NULL DEFAULT 'paper',
    signal_id TEXT NOT NULL DEFAULT '',
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    qty INTEGER NOT NULL,
    entry_ts INTEGER NOT NULL,
    entry_price REAL NOT NULL,
    exit_ts INTEGER NOT NULL,
    exit_price REAL NOT NULL,
    stop REAL NOT NULL,
    target REAL NOT NULL,
    pnl REAL NOT NULL,
    gross_pnl REAL NOT NULL,
    fees REAL NOT NULL,
    r_multiple REAL NOT NULL,
    risk_amount REAL NOT NULL,
    signal_type TEXT NOT NULL,
    entry_reason TEXT NOT NULL,
    exit_reason TEXT NOT NULL,
    duration_sec INTEGER NOT NULL,
    mfe_r REAL NOT NULL DEFAULT 0,
    mae_r REAL NOT NULL DEFAULT 0,
    mfe_usd REAL NOT NULL DEFAULT 0,
    mae_usd REAL NOT NULL DEFAULT 0,
    open_drawdown REAL NOT NULL DEFAULT 0,
    contract TEXT NOT NULL DEFAULT '',
    expiry TEXT NOT NULL DEFAULT '',
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_trades_exit ON trades(exit_ts DESC);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    level TEXT NOT NULL,
    category TEXT NOT NULL,
    message TEXT NOT NULL,
    meta TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts DESC);

CREATE TABLE IF NOT EXISTS equity (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts INTEGER NOT NULL,
    equity REAL NOT NULL,
    mode TEXT NOT NULL DEFAULT 'paper'
);

CREATE TABLE IF NOT EXISTS kv (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS backtests (
    id TEXT PRIMARY KEY,
    created_ts INTEGER NOT NULL,
    label TEXT NOT NULL,
    data_source TEXT NOT NULL,
    dataset TEXT NOT NULL DEFAULT '{}',
    diagnostics TEXT NOT NULL DEFAULT '{}',
    experiment TEXT NOT NULL DEFAULT '{}',
    config TEXT NOT NULL,
    metrics TEXT NOT NULL,
    trades TEXT NOT NULL,
    equity TEXT NOT NULL
);
"""

TRADE_COLUMNS = {
    "mfe_r": "REAL NOT NULL DEFAULT 0",
    "mae_r": "REAL NOT NULL DEFAULT 0",
    "mfe_usd": "REAL NOT NULL DEFAULT 0",
    "mae_usd": "REAL NOT NULL DEFAULT 0",
    "open_drawdown": "REAL NOT NULL DEFAULT 0",
    "contract": "TEXT NOT NULL DEFAULT ''",
    "expiry": "TEXT NOT NULL DEFAULT ''",
    "signal_id": "TEXT NOT NULL DEFAULT ''",
}

BACKTEST_COLUMNS = {
    "dataset": "TEXT NOT NULL DEFAULT '{}'",
    "diagnostics": "TEXT NOT NULL DEFAULT '{}'",
    "experiment": "TEXT NOT NULL DEFAULT '{}'",
}

V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_runs (
    id TEXT PRIMARY KEY,
    created_ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    label TEXT NOT NULL,
    data_source TEXT NOT NULL,
    dataset_id TEXT,
    dataset_sha256 TEXT,
    config_sha256 TEXT,
    code_sha256 TEXT,
    days_requested INTEGER,
    sessions INTEGER,
    result_count INTEGER NOT NULL DEFAULT 0,
    primary_result_id TEXT,
    summary_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT,
    legacy_backtest_id TEXT,
    UNIQUE (legacy_backtest_id),
    UNIQUE (primary_result_id)
);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_created ON backtest_runs(created_ts DESC);
CREATE INDEX IF NOT EXISTS idx_backtest_runs_dataset ON backtest_runs(dataset_id);

CREATE TABLE IF NOT EXISTS backtest_results (
    id TEXT PRIMARY KEY,
    backtest_run_id TEXT NOT NULL REFERENCES backtest_runs(id) ON DELETE CASCADE,
    result_key TEXT NOT NULL,
    created_ts INTEGER NOT NULL,
    label TEXT NOT NULL,
    variant TEXT,
    preset TEXT,
    data_source TEXT NOT NULL,
    dataset_id TEXT,
    config_sha256 TEXT,
    code_sha256 TEXT,
    dataset_sha256 TEXT,
    trades INTEGER NOT NULL,
    net_profit REAL NOT NULL,
    max_drawdown_pct REAL NOT NULL,
    profit_factor REAL,
    metrics_json TEXT NOT NULL,
    payload_json TEXT,
    UNIQUE (backtest_run_id, result_key)
);
CREATE INDEX IF NOT EXISTS idx_backtest_results_created ON backtest_results(created_ts DESC);
"""

V3_COLUMNS = {
    "idempotency_key": "TEXT",
    "idempotency_fingerprint": "TEXT",
}

V3_SCHEMA = """
ALTER TABLE backtest_runs ADD COLUMN idempotency_key TEXT;
ALTER TABLE backtest_runs ADD COLUMN idempotency_fingerprint TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_runs_idempotency
    ON backtest_runs(idempotency_key) WHERE idempotency_key IS NOT NULL;
"""

# Un outbox local permite que la corrida y la obligación de registrarla en el
# ledger JSONL se creen en la misma transacción SQLite. El archivo JSONL no
# participa en la transacción; el estado pending permite reintentar después.
V4_SCHEMA = """
CREATE TABLE IF NOT EXISTS backtest_ledger_outbox (
    backtest_run_id TEXT PRIMARY KEY REFERENCES backtest_runs(id) ON DELETE CASCADE,
    result_id TEXT NOT NULL,
    hypothesis_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_ts INTEGER NOT NULL,
    updated_ts INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_backtest_ledger_outbox_status
    ON backtest_ledger_outbox(status, created_ts);
"""

# El estado ``sent`` deja de ser solo una promesa: el outbox conserva el id
# del evento y el hash canónico de la entrada JSONL que lo acredita.
V5_COLUMNS = {
    "ledger_event_id": "TEXT",
    "ledger_event_sha256": "TEXT",
}

V5_SCHEMA = """
ALTER TABLE backtest_ledger_outbox ADD COLUMN ledger_event_id TEXT;
ALTER TABLE backtest_ledger_outbox ADD COLUMN ledger_event_sha256 TEXT;
CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_ledger_outbox_event
    ON backtest_ledger_outbox(ledger_event_id)
    WHERE ledger_event_id IS NOT NULL;
"""


def migrate(conn: sqlite3.Connection, path: Path) -> None:
    """Aplica las migraciones pendientes de forma transaccional.

    El backup se hace solo cuando hay una base existente y una versión
    pendiente. Una base nueva se crea directamente dentro de la transacción.
    """

    conn.execute("PRAGMA foreign_keys=ON")
    applied = _applied_version(conn)
    if applied < SCHEMA_VERSION:
        if _has_user_tables(conn):
            _backup_before_migration(conn, path)

        conn.execute("BEGIN IMMEDIATE")
        try:
            if applied < 1:
                _apply_001(conn)
            if applied < 2:
                _apply_002(conn)
            if applied < 3:
                _apply_003(conn)
            if applied < 4:
                _apply_004(conn)
            if applied < 5:
                _apply_005(conn)
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    _runtime_pragmas(conn)


def _runtime_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.commit()


def _apply_001(conn: sqlite3.Connection) -> None:
    _execute_all(conn, BASE_SCHEMA)
    _ensure_columns(conn, "backtests", BACKTEST_COLUMNS)
    _ensure_columns(conn, "trades", TRADE_COLUMNS)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_trades_signal ON trades(signal_id)")
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, "
        "applied_ts INTEGER NOT NULL, "
        "checksum TEXT NOT NULL)"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_ts, checksum) "
        "VALUES (?, ?, ?)",
        (1, _now_ms(), _checksum(BASE_SCHEMA)),
    )


def _apply_002(conn: sqlite3.Connection) -> None:
    _execute_all(conn, V2_SCHEMA)
    _backfill(conn)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_ts, checksum) "
        "VALUES (?, ?, ?)",
        (2, _now_ms(), _checksum(V2_SCHEMA)),
    )


def _apply_004(conn: sqlite3.Connection) -> None:
    _execute_all(conn, V4_SCHEMA)
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_ts, checksum) "
        "VALUES (?, ?, ?)",
        (4, _now_ms(), _checksum(V4_SCHEMA)),
    )


def _apply_005(conn: sqlite3.Connection) -> None:
    _ensure_columns(conn, "backtest_ledger_outbox", V5_COLUMNS)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_ledger_outbox_event "
        "ON backtest_ledger_outbox(ledger_event_id) "
        "WHERE ledger_event_id IS NOT NULL"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_ts, checksum) "
        "VALUES (?, ?, ?)",
        (5, _now_ms(), _checksum(V5_SCHEMA)),
    )


def _apply_003(conn: sqlite3.Connection) -> None:
    _ensure_columns(conn, "backtest_runs", V3_COLUMNS)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_backtest_runs_idempotency "
        "ON backtest_runs(idempotency_key) WHERE idempotency_key IS NOT NULL"
    )
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, applied_ts, checksum) "
        "VALUES (?, ?, ?)",
        (3, _now_ms(), _checksum(V3_SCHEMA)),
    )


def _backfill(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT b.* FROM backtests b "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM backtest_runs r WHERE r.legacy_backtest_id = b.id"
        ") "
        "ORDER BY b.created_ts, b.id"
    ).fetchall()
    for row in rows:
        old = dict(row)  # ``row_factory`` puede ser sqlite3.Row.
        _insert_legacy_index(conn, _legacy_backfill_record(old), uuid.uuid4().hex)


def _legacy_problems(row: dict[str, Any]) -> tuple[int | None, list[dict[str, str]]]:
    """Valida una fila legacy sin escribir ni depender de las tablas nuevas."""
    row_id = str(row.get("id") or "")
    problems: list[dict[str, str]] = []
    created_ts: int | None = None
    try:
        created_ts = _created_ts(row_id, row.get("created_ts"))
    except ValueError as exc:
        problems.append({"code": "created_ts_invalid", "detail": str(exc)})

    for field in ("dataset", "experiment"):
        try:
            _json_object(row_id, field, row.get(field))
        except ValueError as exc:
            problems.append({"code": f"{field}_invalid", "detail": str(exc)})

    try:
        _metrics(row_id, row.get("metrics"))
    except ValueError as exc:
        problems.append({"code": "metrics_invalid", "detail": str(exc)})

    for field, expected, empty in (
        ("diagnostics", dict, "{}"),
        ("config", dict, "{}"),
        ("trades", list, "[]"),
        ("equity", list, "[]"),
    ):
        try:
            value = json.loads(row.get(field) or empty)
        except (TypeError, json.JSONDecodeError):
            problems.append(
                {
                    "code": f"{field}_invalid",
                    "detail": f"backtest legacy {row_id}: {field} no es JSON válido",
                }
            )
            continue
        if not isinstance(value, expected):
            problems.append(
                {
                    "code": f"{field}_invalid",
                    "detail": f"backtest legacy {row_id}: {field} tiene un tipo inválido",
                }
            )
    return created_ts, problems


def _legacy_backfill_record(old: dict[str, Any]) -> dict[str, Any]:
    """Calcula las columnas nuevas de una fila legacy válida para indexarla."""
    old_id = str(old.get("id") or "")
    created_ts = _created_ts(old_id, old.get("created_ts"))
    trades, net_profit, max_drawdown_pct, profit_factor = _metrics(
        old_id, old.get("metrics")
    )
    dataset = _json_object(old_id, "dataset", old.get("dataset"))
    experiment = _json_object(old_id, "experiment", old.get("experiment"))
    dataset_id = _text(
        dataset.get("id")
        or dataset.get("selected_id")
        or experiment.get("dataset_id")
    )
    code = _mapping(dataset.get("code"))
    manifest = _mapping(dataset.get("manifest"))
    return {
        "id": old_id,
        "created_ts": created_ts,
        "label": str(old.get("label") or ""),
        "data_source": str(old.get("data_source") or ""),
        "dataset_id": dataset_id,
        "dataset_sha256": _text(
            experiment.get("dataset_sha256")
            or dataset.get("file_hash")
            or manifest.get("file_hash")
        ),
        "config_sha256": _text(experiment.get("config_sha256")),
        "code_sha256": _text(experiment.get("code_sha256") or code.get("sha256")),
        "trades": trades,
        "net_profit": net_profit,
        "max_drawdown_pct": max_drawdown_pct,
        "profit_factor": profit_factor,
        "metrics_json": old.get("metrics"),
    }


def _insert_legacy_index(
    conn: sqlite3.Connection, record: dict[str, Any], run_id: str
) -> tuple[str, str]:
    """Inserta la corrida y el resultado legacy en las tablas nuevas."""
    old_id = record["id"]
    conn.execute(
        "INSERT INTO backtest_runs ("
        "id, created_ts, kind, label, data_source, dataset_id, "
        "dataset_sha256, config_sha256, code_sha256, days_requested, "
        "sessions, result_count, primary_result_id, payload_json, "
        "legacy_backtest_id"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            record["created_ts"],
            "single",
            record["label"],
            record["data_source"],
            record["dataset_id"],
            record["dataset_sha256"],
            record["config_sha256"],
            record["code_sha256"],
            None,
            None,
            1,
            old_id,
            None,
            old_id,
        ),
    )
    conn.execute(
        "INSERT INTO backtest_results ("
        "id, backtest_run_id, result_key, created_ts, label, variant, "
        "preset, data_source, dataset_id, config_sha256, code_sha256, "
        "dataset_sha256, trades, net_profit, max_drawdown_pct, "
        "profit_factor, metrics_json, payload_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            old_id,
            run_id,
            "single",
            record["created_ts"],
            record["label"],
            None,
            None,
            record["data_source"],
            record["dataset_id"],
            record["config_sha256"],
            record["code_sha256"],
            record["dataset_sha256"],
            record["trades"],
            record["net_profit"],
            record["max_drawdown_pct"],
            record["profit_factor"],
            record["metrics_json"],
            None,
        ),
    )
    return old_id, run_id


def repair_legacy_backtests(
    conn: sqlite3.Connection, *, dry_run: bool = True
) -> dict[str, Any]:
    """Reindexa filas válidas de ``backtests`` que no tienen corrida nueva.

    Solo lee ``backtests`` y escribe en ``backtest_runs`` y
    ``backtest_results``. Las filas inválidas se reportan y no se tocan. Con
    ``dry_run=True`` no se ejecuta ninguna escritura ni transacción.
    """
    rows = conn.execute(
        "SELECT b.* FROM backtests b "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM backtest_runs r WHERE r.legacy_backtest_id = b.id"
        ") "
        "ORDER BY b.created_ts, b.id"
    ).fetchall()
    total = int(conn.execute("SELECT COUNT(*) FROM backtests").fetchone()[0])
    indexed = int(
        conn.execute(
            "SELECT COUNT(*) FROM backtests b WHERE EXISTS ("
            "SELECT 1 FROM backtest_runs r WHERE r.legacy_backtest_id = b.id"
            ")"
        ).fetchone()[0]
    )

    items: list[dict[str, Any]] = []
    invalid = 0
    reindexed = 0
    would_reindex = 0
    writes = bool(rows) and not dry_run
    if writes:
        conn.execute("BEGIN IMMEDIATE")
    try:
        for row in rows:
            old = dict(row)
            row_id = str(old.get("id") or "")
            created_ts, problems = _legacy_problems(old)
            conflict = conn.execute(
                "SELECT 1 FROM backtest_results WHERE id = ?", (row_id,)
            ).fetchone()
            if conflict is not None:
                problems.append(
                    {
                        "code": "result_id_exists",
                        "detail": (
                            f"backtest legacy {row_id}: el result_id ya existe "
                            "en backtest_results"
                        ),
                    }
                )

            if problems:
                invalid += 1
                status = "invalid"
                new_run_id = None
            elif dry_run:
                would_reindex += 1
                status = "would_reindex"
                new_run_id = None
            else:
                new_run_id = uuid.uuid4().hex
                _insert_legacy_index(
                    conn, _legacy_backfill_record(old), new_run_id
                )
                reindexed += 1
                status = "reindexed"

            items.append(
                {
                    "id": row_id,
                    "created_ts": created_ts,
                    "label": old.get("label"),
                    "status": status,
                    "indexed": status == "reindexed",
                    "backtest_run_id": new_run_id,
                    "primary_result_id": row_id if new_run_id else None,
                    "problems": problems,
                }
            )
        if writes:
            conn.commit()
    except Exception:
        if writes:
            conn.rollback()
        raise

    return {
        "dry_run": dry_run,
        "read_only": dry_run,
        "wrote_backtests": False,
        "total": total,
        "indexed": indexed,
        "unindexed": len(rows),
        "candidates": len(rows),
        "valid": len(rows) - invalid,
        "invalid": invalid,
        "reindexed": reindexed,
        "would_reindex": would_reindex,
        "items": items,
    }


def _metrics(
    row_id: str, raw: Any
) -> tuple[int, float, float, float | None]:
    try:
        metrics = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"backtest legacy {row_id}: metrics no es JSON válido"
        ) from exc
    if not isinstance(metrics, dict):
        raise ValueError(f"backtest legacy {row_id}: metrics no es un objeto")
    try:
        trades = int(metrics["trades"])
        net_profit = float(metrics["net_profit"])
        max_drawdown_pct = float(metrics["max_drawdown_pct"])
        raw_profit_factor = metrics.get("profit_factor")
        profit_factor = (
            None if raw_profit_factor is None else float(raw_profit_factor)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"backtest legacy {row_id}: métricas inválidas") from exc
    if not all(
        math.isfinite(value)
        for value in (net_profit, max_drawdown_pct, profit_factor)
        if value is not None
    ):
        raise ValueError(f"backtest legacy {row_id}: métricas no finitas")
    return trades, net_profit, max_drawdown_pct, profit_factor


def _json_object(row_id: str, field: str, raw: Any) -> dict[str, Any]:
    try:
        value = json.loads(raw or "{}")
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(
            f"backtest legacy {row_id}: {field} no es JSON válido"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError(f"backtest legacy {row_id}: {field} no es un objeto")
    return value


def _created_ts(row_id: str, raw: Any) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"backtest legacy {row_id}: created_ts inválido") from exc


def _mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _text(value: Any) -> str | None:
    return str(value) if value not in (None, "") else None


def _execute_all(conn: sqlite3.Connection, sql: str) -> None:
    for statement in sql.split(";"):
        if statement.strip():
            conn.execute(statement)


def _ensure_columns(
    conn: sqlite3.Connection, table: str, columns: dict[str, str]
) -> None:
    existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, ddl in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def _applied_version(conn: sqlite3.Connection) -> int:
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if exists is None:
        return 0
    row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
    return int(row[0] or 0)


def _has_user_tables(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1"
        ).fetchone()
        is not None
    )


def _backup_before_migration(conn: sqlite3.Connection, path: Path) -> None:
    # Junto a la base: aísla perfiles y mantiene los tests en su tmp_path.
    backup_dir = path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    backup_path = (
        backup_dir
        / f"pre-migration-v{SCHEMA_VERSION}-{stamp}-{time.time_ns()}.db"
    )
    try:
        conn.execute("PRAGMA wal_checkpoint(FULL)")
    except sqlite3.OperationalError:
        pass
    destination = sqlite3.connect(str(backup_path))
    try:
        conn.backup(destination)
    finally:
        destination.close()


def _now_ms() -> int:
    return int(time.time() * 1000)


def _checksum(sql: str) -> str:
    return hashlib.sha256(sql.encode("utf-8")).hexdigest()
