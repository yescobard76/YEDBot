"""Diagnóstico legacy de solo lectura, previo a ``Store`` y a las migraciones.

El diagnóstico normal de ``Store.legacy_diagnostics`` necesita que las tablas
nuevas existan. Cuando una fila legacy inválida aborta el backfill, ``Store``
no llega a abrirse y ese diagnóstico no puede ejecutarse. Este módulo abre la
base con ``mode=ro``, reutiliza las mismas validaciones que el backfill y no
crea tablas, backups ni modifica ``backtests``.

Uso::

    python -m server.diagnostics --db data/yedbot.db
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Any, Sequence

from .config import DB_PATH
from .migrations import SCHEMA_VERSION, _created_ts, _json_object, _metrics

# ``_backfill`` valida estos cuatro campos antes de insertar una fila legacy.
# Un fallo en cualquiera de ellos aborta la transacción de migración.
BLOCKING_CODES = frozenset(
    {
        "created_ts_invalid",
        "dataset_invalid",
        "experiment_invalid",
        "metrics_invalid",
    }
)

JSON_FIELDS = (
    ("diagnostics", dict, "{}"),
    ("config", dict, "{}"),
    ("trades", list, "[]"),
    ("equity", list, "[]"),
)


def _open_read_only(path: Path) -> sqlite3.Connection:
    """Abre SQLite sin permitir escrituras y sin crear la base si no existe."""
    if not path.exists():
        raise FileNotFoundError(f"No existe la base de datos: {path}")
    uri = f"{path.resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")
    return conn


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}


def _schema_version(
    conn: sqlite3.Connection, tables: set[str]
) -> tuple[int, list[str]]:
    if "schema_migrations" not in tables:
        return 0, []
    try:
        row = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()
        return int(row[0] or 0), []
    except (sqlite3.Error, TypeError, ValueError):
        return 0, ["schema_migrations_invalid"]


def _index_state(
    conn: sqlite3.Connection, tables: set[str]
) -> tuple[dict[str, sqlite3.Row], set[str], list[str]]:
    """Lee el índice nuevo si existe, sin exigir que la migración esté hecha."""
    runs: dict[str, sqlite3.Row] = {}
    result_ids: set[str] = set()
    warnings: list[str] = []

    if "backtest_runs" in tables:
        columns = _columns(conn, "backtest_runs")
        required = {"id", "legacy_backtest_id", "primary_result_id"}
        if required <= columns:
            for row in conn.execute(
                "SELECT id, legacy_backtest_id, primary_result_id "
                "FROM backtest_runs WHERE legacy_backtest_id IS NOT NULL"
            ):
                runs[str(row["legacy_backtest_id"])] = row
        else:
            warnings.append("backtest_runs_schema_incomplete")

    if "backtest_results" in tables:
        if "id" in _columns(conn, "backtest_results"):
            result_ids = {
                str(row[0]) for row in conn.execute("SELECT id FROM backtest_results")
            }
        else:
            warnings.append("backtest_results_schema_incomplete")

    return runs, result_ids, warnings


def _row_problems(row: dict[str, Any]) -> tuple[int | None, list[dict[str, str]]]:
    """Aplica las validaciones del backfill y las de lectura del detalle."""
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

    for field, expected, empty in JSON_FIELDS:
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


def diagnose_database(path: Path | str = DB_PATH) -> dict[str, Any]:
    """Diagnostica ``backtests`` sin abrir ``Store`` ni ejecutar migraciones.

    ``migration_blockers`` contiene los ids cuyas validaciones harían fallar el
    backfill de v2. Las filas ya indexadas no se vuelven a procesar y, por
    tanto, no bloquean la migración aunque su detalle siga siendo inválido.
    """
    db_path = Path(path)
    conn = _open_read_only(db_path)
    try:
        tables = _tables(conn)
        version, warnings = _schema_version(conn, tables)
        runs, result_ids, index_warnings = _index_state(conn, tables)
        warnings.extend(index_warnings)

        if "backtests" not in tables:
            warnings.append("backtests_missing")
            rows: list[dict[str, Any]] = []
        else:
            rows = [
                dict(row) for row in conn.execute("SELECT * FROM backtests").fetchall()
            ]

        indexed = 0
        invalid = 0
        blockers: list[str] = []
        items: list[dict[str, Any]] = []
        for row in rows:
            row_id = str(row.get("id") or "")
            run = runs.get(row_id)
            run_id = str(run["id"]) if run is not None else None
            primary_id = (
                str(run["primary_result_id"])
                if run is not None and run["primary_result_id"] is not None
                else None
            )
            result_id = (
                primary_id
                if run is not None and primary_id in result_ids
                else None
            )
            if run is not None:
                indexed += 1

            created_ts, problems = _row_problems(row)
            if run_id is None:
                problems.append(
                    {
                        "code": "missing_index",
                        "detail": (
                            "No está indexada en backtest_runs; no aparece en el "
                            "historial paginado."
                        ),
                    }
                )
            elif result_id is None:
                problems.append(
                    {
                        "code": "missing_result",
                        "detail": (
                            "La corrida indexada no tiene resultado primario en "
                            "backtest_results."
                        ),
                    }
                )

            has_invalid = any(
                problem["code"] != "missing_index" for problem in problems
            )
            if has_invalid:
                invalid += 1

            # El backfill de v2 solo procesa filas sin índice. En v2 o v3 ya
            # no se ejecuta: una fila inválida puede impedir leer su detalle,
            # pero no bloquear una migración futura.
            will_backfill = version < 2 and run_id is None
            migration_blocker = will_backfill and any(
                problem["code"] in BLOCKING_CODES for problem in problems
            )
            if migration_blocker:
                blockers.append(row_id)

            if not problems:
                continue
            items.append(
                {
                    "id": row_id,
                    "created_ts": created_ts,
                    "label": row.get("label"),
                    "indexed": run_id is not None,
                    "backtest_run_id": run_id,
                    "primary_result_id": primary_id,
                    "status": "invalid" if has_invalid else "unindexed",
                    "problems": problems,
                    "migration_blocker": migration_blocker,
                }
            )

        return {
            "database": str(db_path),
            "read_only": True,
            "schema_version": version,
            "migration_required": version < SCHEMA_VERSION,
            "migration_blocked": bool(blockers),
            "migration_blockers": blockers,
            "total": len(rows),
            "indexed": indexed,
            "unindexed": len(rows) - indexed,
            "invalid": invalid,
            "items": items,
            "warnings": warnings,
        }
    finally:
        conn.close()


def legacy_diagnostics(path: Path | str = DB_PATH) -> dict[str, Any]:
    """Alias de :func:`diagnose_database` para el preflight legacy."""
    return diagnose_database(path)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnóstico legacy de solo lectura antes de abrir Store o migrar. "
            "No crea tablas, backups ni modifica backtests."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DB_PATH,
        help=f"Ruta de SQLite (por defecto: {DB_PATH})",
    )
    args = parser.parse_args(argv)
    try:
        report = diagnose_database(args.db)
    except (FileNotFoundError, sqlite3.Error, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if report["migration_blocked"] else 0


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
