"""Persistencia SQLite: operaciones, eventos, equity, config y estado del motor.

Se usa sqlite3 en modo WAL con un lock de proceso. Las escrituras son cortas y
el motor corre en un único event loop, por lo que el coste es despreciable y se
evita cualquier dependencia extra.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Iterable

from .config import DB_PATH
from .migrations import (
    _legacy_problems,
    migrate,
    repair_legacy_backtests as _repair_legacy_backtests,
)
from .timeutil import et_date_str, et_hm

TRADE_FIELDS = (
    "id, mode, signal_id, symbol, direction, qty, entry_ts, entry_price, exit_ts, exit_price, "
    "stop, target, pnl, gross_pnl, fees, r_multiple, risk_amount, signal_type, "
    "entry_reason, exit_reason, duration_sec, mfe_r, mae_r, mfe_usd, mae_usd, "
    "open_drawdown, contract, expiry, meta"
)

BACKTEST_RUN_KINDS = frozenset({"single", "variants", "presets"})

# Proyección única del vínculo en todas las lecturas. Las cinco claves se
# exponen siempre juntas; ``None`` significa que la corrida no tiene outbox.
_LEDGER_SELECT = (
    "o.status AS ledger_status, o.hypothesis_id AS hypothesis_id, "
    "o.ledger_event_id AS ledger_event_id, "
    "o.ledger_event_sha256 AS ledger_event_sha256, "
    "o.last_error AS ledger_error"
)
_LEDGER_FIELDS = (
    "ledger_status",
    "hypothesis_id",
    "ledger_event_id",
    "ledger_event_sha256",
    "ledger_error",
)


def _ledger_link_values(event_id: Any, event_sha256: Any) -> tuple[str, str]:
    """Valida el par event_id/hash que acredita una entrada del ledger."""
    value = str(event_id or "").strip()
    digest = str(event_sha256 or "").strip()
    if not value:
        raise ValueError("ledger_event_id no puede estar vacío")
    if len(digest) != 64:
        raise ValueError("ledger_event_sha256 debe ser un SHA-256 de 64 caracteres")
    try:
        int(digest, 16)
    except ValueError as exc:
        raise ValueError("ledger_event_sha256 debe ser hexadecimal") from exc
    return value, digest


class IdempotencyConflict(ValueError):
    """La misma clave de petición se usó con un payload distinto."""


def _idempotency_fingerprint(kind: str, request: dict[str, Any] | None) -> str:
    """Huella canónica de una petición idempotente."""
    return hashlib.sha256(
        json.dumps(
            {"kind": kind, "request": request},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _encode_run_cursor(created_ts: int, run_id: str) -> str:
    """Cursor opaco y estable para el historial descendente."""
    payload = json.dumps(
        {"v": 1, "created_ts": int(created_ts), "id": str(run_id)},
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_run_cursor(cursor: str) -> tuple[int, str]:
    """Valida un cursor de historial o lanza ``ValueError``."""
    try:
        padded = str(cursor) + "=" * (-len(str(cursor)) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("cursor no es un objeto")
        created_ts = int(payload["created_ts"])
        run_id = str(payload["id"])
        if not run_id:
            raise ValueError("cursor sin id")
        return created_ts, run_id
    except (KeyError, TypeError, ValueError, UnicodeError, binascii.Error) as exc:
        raise ValueError("cursor de historial inválido") from exc


def _normalise_backtest(
    result: dict[str, Any] | list[dict[str, Any]],
    kind: str | None,
    label: str | None,
    days_requested: int | None,
    request: dict[str, Any] | None,
) -> dict[str, Any]:
    source: dict[str, Any] = {}
    if isinstance(result, dict) and isinstance(result.get("results"), list):
        source = result
        results = list(result["results"])
        kind = kind or "presets"
    elif isinstance(result, list):
        results = list(result)
        kind = kind or "variants"
    elif isinstance(result, dict):
        results = [result]
        kind = kind or "single"
    else:
        raise ValueError("resultado de backtest inválido")

    kind = str(kind)
    if kind not in BACKTEST_RUN_KINDS:
        raise ValueError(f"tipo de corrida desconocido: {kind}")
    if not results or any(not isinstance(item, dict) for item in results):
        raise ValueError("la corrida no contiene resultados válidos")
    if kind == "single" and len(results) != 1:
        raise ValueError("una corrida single debe tener un único resultado")

    if kind == "presets":
        primary = next(
            (item for item in results if item.get("preset") == "baseline"),
            results[0],
        )
    else:
        primary = results[0]

    if days_requested is None:
        days_requested = source.get("days_requested")
    sessions = source.get("sessions")
    if sessions is None:
        config = primary.get("config")
        sessions = (config or {}).get("days") if isinstance(config, dict) else None
    if days_requested is None and isinstance(sessions, int):
        days_requested = sessions
    if label is None:
        suffix = f" · {days_requested} sesiones" if days_requested else ""
        label = {
            "single": str(primary.get("label") or "Backtest"),
            "variants": f"Variantes{suffix}",
            "presets": f"Presets{suffix}",
        }[kind]

    keys: list[str] = []
    ids: list[str] = []
    for item in results:
        result_id = str(item.get("id") or "")
        if not result_id or result_id in ids:
            raise ValueError("los resultados de una corrida necesitan ids únicos")
        if kind == "single":
            result_key = "single"
        else:
            field = "variant" if kind == "variants" else "preset"
            result_key = str(item.get(field) or "")
            if not result_key:
                raise ValueError(f"resultado sin {field}")
        if result_key in keys:
            raise ValueError(f"result_key duplicado: {result_key}")
        ids.append(result_id)
        keys.append(result_key)

    return {
        "kind": kind,
        "results": results,
        "result_ids": ids,
        "result_keys": keys,
        "primary": primary,
        "primary_id": str(primary.get("id") or ""),
        "label": str(label),
        "days_requested": int(days_requested) if days_requested is not None else None,
        "sessions": int(sessions) if sessions is not None else None,
        "request": request,
    }


def _backtest_identity(item: dict[str, Any]) -> dict[str, Any]:
    experiment = item.get("experiment")
    experiment = experiment if isinstance(experiment, dict) else {}
    dataset = item.get("dataset")
    dataset = dataset if isinstance(dataset, dict) else {}
    manifest = dataset.get("manifest")
    manifest = manifest if isinstance(manifest, dict) else {}
    code = dataset.get("code")
    code = code if isinstance(code, dict) else {}
    return {
        "data_source": str(item.get("data_source") or ""),
        "dataset_id": item.get("dataset_id")
        or dataset.get("id")
        or dataset.get("selected_id")
        or experiment.get("dataset_id"),
        "dataset_sha256": experiment.get("dataset_sha256")
        or dataset.get("file_hash")
        or manifest.get("file_hash"),
        "config_sha256": experiment.get("config_sha256"),
        "code_sha256": experiment.get("code_sha256") or code.get("sha256"),
    }


def _backtest_metrics(item: dict[str, Any]) -> tuple[int, float, float, float | None, str]:
    metrics = item.get("metrics")
    metrics = metrics if isinstance(metrics, dict) else {}
    trades = metrics.get("trades", len(item.get("trades") or []))
    net_profit = metrics.get("net_profit", 0.0)
    max_drawdown_pct = metrics.get("max_drawdown_pct", 0.0)
    profit_factor = metrics.get("profit_factor")
    try:
        trades = int(trades)
        net_profit = float(net_profit or 0.0)
        max_drawdown_pct = float(max_drawdown_pct or 0.0)
        profit_factor = None if profit_factor is None else float(profit_factor)
    except (TypeError, ValueError) as exc:
        raise ValueError("métricas de backtest inválidas") from exc
    compact = {
        key: value
        for key, value in metrics.items()
        if key not in ("trades", "equity_curve")
    }
    return trades, net_profit, max_drawdown_pct, profit_factor, json.dumps(
        compact, ensure_ascii=False
    )


def _backtest_projection(payload: dict[str, Any]) -> dict[str, Any]:
    """Mantiene la forma histórica que consumen ``latest`` y ``get_backtest``."""
    return {
        "id": payload["id"],
        "created_ts": payload["created_ts"],
        "label": payload.get("label") or "",
        "data_source": payload.get("data_source") or "",
        "dataset": payload.get("dataset") or {},
        "diagnostics": payload.get("diagnostics") or {},
        "experiment": payload.get("experiment") or {},
        "config": payload.get("config") or {},
        "metrics": payload.get("metrics") or {},
        "trades": payload.get("trades") or [],
        "equity": payload.get("equity") or [],
    }


class Store:
    def __init__(self, path: Path | str = DB_PATH) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            try:
                migrate(self._conn, self.path)
            except Exception:
                self._conn.close()
                raise

    # ------------------------------------------------------------------ trades
    def insert_trade(self, trade: dict[str, Any]) -> None:
        row = dict(trade)
        row.setdefault("mode", "paper")
        meta = row.get("meta")
        if isinstance(meta, dict):
            if not row.get("signal_id"):
                row["signal_id"] = str(meta.get("signal_id") or "")
            row["meta"] = json.dumps(meta)
        else:
            row["meta"] = meta or "{}"
        cols = ", ".join(row.keys())
        marks = ", ".join("?" for _ in row)
        with self._lock:
            self._conn.execute(f"INSERT OR REPLACE INTO trades ({cols}) VALUES ({marks})", tuple(row.values()))
            self._conn.commit()

    def _trade_query(self, filters: dict[str, Any] | None = None) -> tuple[str, list[Any]]:
        filters = filters or {}
        where: list[str] = []
        args: list[Any] = []
        if filters.get("mode"):
            where.append("mode = ?")
            args.append(filters["mode"])
        if filters.get("direction"):
            where.append("direction = ?")
            args.append(filters["direction"])
        if filters.get("result") == "win":
            where.append("pnl > 0")
        elif filters.get("result") == "loss":
            where.append("pnl < 0")
        elif filters.get("result") == "be":
            where.append("pnl = 0")
        if filters.get("signal_type"):
            where.append("signal_type = ?")
            args.append(filters["signal_type"])
        if filters.get("date_from"):
            where.append("exit_ts >= ?")
            args.append(int(filters["date_from"]))
        if filters.get("date_to"):
            where.append("exit_ts <= ?")
            args.append(int(filters["date_to"]))
        if filters.get("symbol"):
            where.append("symbol = ?")
            args.append(filters["symbol"])
        sql = f"SELECT {TRADE_FIELDS} FROM trades"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY exit_ts DESC"
        return sql, args

    def list_trades(self, filters: dict[str, Any] | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        sql, args = self._trade_query(filters)
        sql += " LIMIT ? OFFSET ?"
        with self._lock:
            rows = self._conn.execute(sql, (*args, limit, offset)).fetchall()
        return [self._trade_row(r) for r in rows]

    def count_trades(self, filters: dict[str, Any] | None = None) -> int:
        sql, args = self._trade_query(filters)
        sql = f"SELECT COUNT(*) FROM ({sql})"
        with self._lock:
            return int(self._conn.execute(sql, args).fetchone()[0])

    def all_closed_trades(self, mode: str | None = None) -> list[dict]:
        return self.list_trades({"mode": mode} if mode else {}, limit=100_000)

    def history_counts(self) -> dict[str, int]:
        """Cuenta las filas que afecta un reinicio sin modificar la base.

        Sirve para la previsualización del borrado. ``backtests`` cuenta
        corridas persistidas, igual que el mensaje histórico del reinicio.
        """
        tables = ["trades", "events", "equity", "kv"]
        with self._lock:
            counts = {
                table: int(self._conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in tables
            }
            # El mensaje histórico cuenta corridas, no filas legacy sueltas.
            counts["backtests"] = int(
                self._conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0]
            )
        return counts

    def archive_to(self, destination: Path | str) -> Path:
        """Guarda una copia consistente de la base con la API de SQLite.

        La copia se hace antes de borrar y no sobrescribe un archivo previo.
        """
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError(str(destination))
        with self._lock:
            target = sqlite3.connect(str(destination))
            try:
                self._conn.backup(target)
                target.commit()
            finally:
                target.close()
        return destination

    def _vacuum(self) -> None:
        """Mantenimiento opcional; un fallo aquí no revierte el borrado ya confirmado."""
        self._conn.execute("VACUUM")

    def clear_history(self, *, delete_backtests: bool = False) -> dict[str, Any]:
        """Elimina operaciones, eventos, equidad y estado del motor.

        Los backtests guardados se conservan salvo que ``delete_backtests``
        sea True. No toca configuración, perfiles ni archivos de datos.
        Devuelve siempre los conteos previos, incluidos los backtests aunque
        se conserven. Si ``VACUUM`` falla, el borrado sigue siendo válido y se
        informa en ``vacuum_error``.
        """
        tables = ["trades", "events", "equity", "kv"]
        history_tables = (
            [
                "backtest_ledger_outbox",
                "backtest_results",
                "backtest_runs",
                "backtests",
            ]
            if delete_backtests
            else []
        )
        with self._lock:
            counts = self.history_counts()
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                for table in [*tables, *history_tables]:
                    self._conn.execute(f"DELETE FROM {table}")
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            # El DELETE ya está confirmado. La compactación es mantenimiento
            # opcional: un fallo de VACUUM no debe convertir un reinicio
            # exitoso en un error para el operador.
            try:
                self._vacuum()
            except Exception as exc:  # noqa: BLE001
                counts["vacuum_error"] = str(exc)
        return counts

    def traded_signal_ids(self, mode: str | None = None) -> set[str]:
        """Ids de señal ya operados. Base de la deduplicación al reiniciar un replay.

        Las operaciones anteriores a la columna ``signal_id`` lo guardaban solo
        en ``meta``; se leen de ahí sin reescribir la base de datos.
        """
        sql = "SELECT signal_id, meta FROM trades"
        args: list[Any] = []
        if mode:
            sql += " WHERE mode = ?"
            args.append(mode)
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        out: set[str] = set()
        for row in rows:
            sid = str(row["signal_id"] or "")
            if not sid:
                try:
                    sid = str((json.loads(row["meta"] or "{}") or {}).get("signal_id") or "")
                except (json.JSONDecodeError, AttributeError, TypeError):
                    sid = ""
            if sid:
                out.add(sid)
        return out

    @staticmethod
    def _trade_row(row: sqlite3.Row) -> dict[str, Any]:
        data = dict(row)
        try:
            data["meta"] = json.loads(data.get("meta") or "{}")
        except json.JSONDecodeError:
            data["meta"] = {}
        return data

    # ------------------------------------------------------------------ events
    def insert_event(self, level: str, category: str, message: str, meta: dict | None = None) -> dict[str, Any]:
        ts = int(time.time() * 1000)
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO events (ts, level, category, message, meta) VALUES (?,?,?,?,?)",
                (ts, level, category, message, json.dumps(meta or {})),
            )
            self._conn.commit()
            eid = cur.lastrowid
            self._conn.execute(
                "DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 5000)"
            )
            self._conn.commit()
        return {"id": eid, "ts": ts, "level": level, "category": category, "message": message, "meta": meta or {}}

    def list_events(self, level: str | None = None, limit: int = 200) -> list[dict]:
        sql = "SELECT id, ts, level, category, message, meta FROM events"
        args: list[Any] = []
        if level and level != "all":
            sql += " WHERE level = ?"
            args.append(level)
        sql += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            rows = self._conn.execute(sql, (*args, limit)).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            try:
                d["meta"] = json.loads(d.get("meta") or "{}")
            except json.JSONDecodeError:
                d["meta"] = {}
            out.append(d)
        return out

    # ------------------------------------------------------------------ equity
    def insert_equity(self, ts: int, equity: float, mode: str = "paper") -> None:
        with self._lock:
            self._conn.execute("INSERT INTO equity (ts, equity, mode) VALUES (?,?,?)", (ts, equity, mode))
            self._conn.execute("DELETE FROM equity WHERE id NOT IN (SELECT id FROM equity ORDER BY id DESC LIMIT 20000)")
            self._conn.commit()

    def equity_series(self, limit: int = 500) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, equity FROM equity ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"ts": r["ts"], "equity": r["equity"]} for r in reversed(rows)]

    # ---------------------------------------------------------------------- kv
    def set_kv(self, key: str, value: Any) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO kv (key, value) VALUES (?,?)", (key, json.dumps(value))
            )
            self._conn.commit()

    def get_kv(self, key: str, default: Any = None) -> Any:
        with self._lock:
            row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except json.JSONDecodeError:
            return default

    def delete_kv(self, key: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM kv WHERE key = ?", (key,))
            self._conn.commit()

    # --------------------------------------------------------------- backtests
    def save_backtest(
        self,
        result: dict[str, Any] | list[dict[str, Any]],
        *,
        kind: str | None = None,
        label: str | None = None,
        days_requested: int | None = None,
        request: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
        response: dict[str, Any] | None = None,
        hypothesis_id: str | None = None,
    ) -> str:
        """Guarda una corrida completa en las tablas nuevas y devuelve su id.

        Acepta un resultado individual, una lista de resultados (variantes) o
        un contenedor con ``results`` (presets). ``backtests`` queda congelada.
        Una ``idempotency_key`` opcional reutiliza la corrida existente solo si
        la petición canónica coincide. ``response`` se guarda como snapshot en
        ``summary_json`` para que un reintento no dependa de una simulación nueva.

        Cuando se pasa ``hypothesis_id``, la corrida y su fila pendiente del
        outbox del ledger se insertan en la misma transacción. El JSONL se
        escribe después; si falla, el outbox queda reintentable.
        """
        run = _normalise_backtest(result, kind, label, days_requested, request)
        idempotency_key = str(idempotency_key) if idempotency_key else None
        hypothesis = str(hypothesis_id or "").strip() or None
        if hypothesis_id is not None and not hypothesis:
            raise ValueError("hypothesis_id no puede estar vacío")
        if hypothesis and ("\n" in hypothesis or "\r" in hypothesis):
            raise ValueError("hypothesis_id no puede contener saltos de línea")
        fingerprint = None
        if idempotency_key:
            fingerprint = _idempotency_fingerprint(run["kind"], run["request"])
        primary = run["primary"]
        identity = _backtest_identity(primary)
        run_id = uuid.uuid4().hex
        request_json = (
            json.dumps(run["request"], ensure_ascii=False)
            if isinstance(run["request"], dict)
            else None
        )
        response_snapshot = None
        if response is not None and idempotency_key:
            response_snapshot = dict(response)
            response_snapshot["backtest_run_id"] = run_id
        response_json = (
            json.dumps(response_snapshot, ensure_ascii=False)
            if response_snapshot is not None
            else "{}"
        )
        created_ts = int(primary.get("created_ts") or time.time() * 1000)
        experiment = primary.get("experiment")
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                if idempotency_key:
                    existing_run = self._conn.execute(
                        "SELECT id, idempotency_fingerprint, primary_result_id, "
                        "created_ts FROM backtest_runs WHERE idempotency_key = ?",
                        (idempotency_key,),
                    ).fetchone()
                    if existing_run is not None:
                        if existing_run["idempotency_fingerprint"] != fingerprint:
                            raise IdempotencyConflict(
                                "idempotency_key reutilizada con un payload distinto"
                            )
                        if hypothesis:
                            outbox = self._conn.execute(
                                "SELECT hypothesis_id FROM backtest_ledger_outbox "
                                "WHERE backtest_run_id = ?",
                                (str(existing_run["id"]),),
                            ).fetchone()
                            if outbox is None:
                                if not existing_run["primary_result_id"]:
                                    raise ValueError(
                                        "la corrida existente no tiene resultado primario "
                                        "para registrar en el ledger"
                                    )
                                self._insert_ledger_outbox(
                                    str(existing_run["id"]),
                                    str(existing_run["primary_result_id"]),
                                    hypothesis,
                                    int(existing_run["created_ts"]),
                                )
                            elif str(outbox["hypothesis_id"]) != hypothesis:
                                raise IdempotencyConflict(
                                    "idempotency_key reutilizada con otra hipótesis"
                                )
                        self._conn.commit()
                        return str(existing_run["id"])
                marks = ", ".join("?" for _ in run["result_ids"])
                existing = self._conn.execute(
                    f"SELECT id FROM backtest_results WHERE id IN ({marks})",
                    tuple(run["result_ids"]),
                ).fetchall()
                if existing:
                    duplicate = ", ".join(str(row["id"]) for row in existing)
                    raise ValueError(f"resultados ya guardados: {duplicate}")
                self._conn.execute(
                    "INSERT INTO backtest_runs ("
                    "id, created_ts, kind, label, data_source, dataset_id, "
                    "dataset_sha256, config_sha256, code_sha256, days_requested, "
                    "sessions, result_count, primary_result_id, payload_json, "
                    "summary_json, idempotency_key, idempotency_fingerprint"
                    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        run_id,
                        created_ts,
                        run["kind"],
                        run["label"],
                        identity["data_source"],
                        identity["dataset_id"],
                        identity["dataset_sha256"],
                        identity["config_sha256"],
                        identity["code_sha256"],
                        run["days_requested"],
                        run["sessions"],
                        len(run["results"]),
                        run["primary_id"],
                        request_json,
                        response_json,
                        idempotency_key,
                        fingerprint,
                    ),
                )
                for result_id, result_key, item in zip(
                    run["result_ids"], run["result_keys"], run["results"]
                ):
                    item_identity = _backtest_identity(item)
                    trades, net_profit, max_drawdown_pct, profit_factor, metrics_json = (
                        _backtest_metrics(item)
                    )
                    self._conn.execute(
                        "INSERT INTO backtest_results ("
                        "id, backtest_run_id, result_key, created_ts, label, "
                        "variant, preset, data_source, dataset_id, config_sha256, "
                        "code_sha256, dataset_sha256, trades, net_profit, "
                        "max_drawdown_pct, profit_factor, metrics_json, payload_json"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            result_id,
                            run_id,
                            result_key,
                            int(item.get("created_ts") or created_ts),
                            str(item.get("label") or result_key),
                            item.get("variant") if run["kind"] == "variants" else None,
                            item.get("preset") if run["kind"] == "presets" else None,
                            item_identity["data_source"],
                            item_identity["dataset_id"],
                            item_identity["config_sha256"],
                            item_identity["code_sha256"],
                            item_identity["dataset_sha256"],
                            trades,
                            net_profit,
                            max_drawdown_pct,
                            profit_factor,
                            metrics_json,
                            json.dumps(item, ensure_ascii=False),
                        ),
                    )
                # Solo un backtest individual de la configuración activa ancla
                # paper. Variantes, presets y overrides son exploraciones y no
                # deben autorizar una configuración distinta a la viva.
                if (
                    run["kind"] == "single"
                    and isinstance(experiment, dict)
                    and not primary.get("overrides")
                    and not primary.get("variant")
                    and not primary.get("preset")
                ):
                    self._conn.execute(
                        "INSERT OR REPLACE INTO kv (key, value) VALUES (?, ?)",
                        ("experiment.parity", json.dumps(experiment)),
                    )
                if hypothesis:
                    if run["kind"] != "single":
                        raise ValueError("hypothesis_id solo se admite en corridas individuales")
                    self._insert_ledger_outbox(
                        run_id,
                        run["primary_id"],
                        hypothesis,
                        created_ts,
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return run_id

    def _insert_ledger_outbox(
        self,
        run_id: str,
        result_id: str,
        hypothesis_id: str,
        created_ts: int,
    ) -> None:
        """Inserta la obligación pendiente dentro de una transacción existente."""
        self._conn.execute(
            "INSERT INTO backtest_ledger_outbox ("
            "backtest_run_id, result_id, hypothesis_id, status, attempts, "
            "last_error, created_ts, updated_ts"
            ") VALUES (?, ?, ?, 'pending', 0, NULL, ?, ?)",
            (run_id, result_id, hypothesis_id, created_ts, created_ts),
        )

    def get_ledger_outbox(self, run_id: str) -> dict[str, Any] | None:
        """Estado del outbox de una corrida, con el payload para reintentar."""
        with self._lock:
            row = self._conn.execute(
                "SELECT o.backtest_run_id, o.result_id, o.hypothesis_id, "
                "o.status, o.attempts, o.last_error, o.created_ts, o.updated_ts, "
                "o.ledger_event_id, o.ledger_event_sha256, "
                "res.payload_json AS result_json "
                "FROM backtest_ledger_outbox o "
                "LEFT JOIN backtest_results res ON res.id = o.result_id "
                "WHERE o.backtest_run_id = ?",
                (run_id,),
            ).fetchone()
        return dict(row) if row else None

    def pending_ledger_run_ids(self, limit: int = 100) -> list[str]:
        """Corridas pendientes en orden de creación, listas para reintentar."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT backtest_run_id FROM backtest_ledger_outbox "
                "WHERE status = 'pending' "
                "ORDER BY created_ts, backtest_run_id LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [str(row[0]) for row in rows]

    def sent_ledger_outbox_without_event(self) -> list[dict[str, Any]]:
        """Filas ``sent`` anteriores a v5 que aún no guardan su vínculo."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT backtest_run_id, result_id, hypothesis_id, status, "
                "attempts, created_ts, updated_ts "
                "FROM backtest_ledger_outbox "
                "WHERE status = 'sent' AND ledger_event_id IS NULL "
                "ORDER BY created_ts, backtest_run_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def linked_ledger_event_ids(self) -> set[str]:
        """Eventos del ledger ya reclamados por un outbox."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT ledger_event_id FROM backtest_ledger_outbox "
                "WHERE ledger_event_id IS NOT NULL"
            ).fetchall()
        return {str(row[0]) for row in rows}

    def link_ledger_events(self, links: Iterable[dict[str, Any]]) -> int:
        """Guarda vínculos históricos sin cambiar estado ni sumar intentos.

        Solo toca filas ``sent`` que todavía no tienen evento. El índice único
        parcial impide reutilizar un ``ledger_event_id``; la transacción se
        revierte completa si algún vínculo entra en conflicto.
        """
        prepared: list[tuple[str, str, int, str]] = []
        for link in links:
            run_id = str(link.get("backtest_run_id") or "").strip()
            if not run_id:
                raise ValueError("el vínculo del ledger requiere backtest_run_id")
            event_id, event_sha256 = _ledger_link_values(
                link.get("ledger_event_id"),
                link.get("ledger_event_sha256"),
            )
            prepared.append(
                (event_id, event_sha256, int(time.time() * 1000), run_id)
            )
        if not prepared:
            return 0
        with self._lock:
            try:
                cursor = self._conn.executemany(
                    "UPDATE backtest_ledger_outbox SET ledger_event_id = ?, "
                    "ledger_event_sha256 = ?, updated_ts = ? "
                    "WHERE backtest_run_id = ? AND status = 'sent' "
                    "AND ledger_event_id IS NULL",
                    prepared,
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
        return int(cursor.rowcount or 0)

    def mark_ledger_sent(
        self,
        run_id: str,
        *,
        ledger_event_id: str,
        ledger_event_sha256: str,
    ) -> None:
        """Marca la corrida como enviada y guarda el vínculo exacto al ledger."""
        event_id, event_sha256 = _ledger_link_values(
            ledger_event_id, ledger_event_sha256
        )
        with self._lock:
            self._conn.execute(
                "UPDATE backtest_ledger_outbox SET status = 'sent', "
                "attempts = attempts + 1, last_error = NULL, "
                "ledger_event_id = ?, ledger_event_sha256 = ?, updated_ts = ? "
                "WHERE backtest_run_id = ?",
                (event_id, event_sha256, int(time.time() * 1000), run_id),
            )
            self._conn.commit()

    def mark_ledger_pending(self, run_id: str, error: str) -> None:
        message = str(error or "")[:2000]
        with self._lock:
            self._conn.execute(
                "UPDATE backtest_ledger_outbox SET status = 'pending', "
                "attempts = attempts + 1, last_error = ?, updated_ts = ? "
                "WHERE backtest_run_id = ?",
                (message, int(time.time() * 1000), run_id),
            )
            self._conn.commit()

    def idempotent_response(
        self,
        *,
        kind: str,
        request: dict[str, Any] | None,
        idempotency_key: str | None,
    ) -> tuple[str, dict[str, Any]] | None:
        """Devuelve el snapshot persistido de una petición idempotente.

        La consulta es solo de lectura. Si la clave no existe devuelve ``None``;
        si existe con otra huella lanza ``IdempotencyConflict``. Las corridas
        antiguas sin snapshot devuelven ``None`` para conservar el fallback
        anterior.
        """
        key = str(idempotency_key) if idempotency_key else None
        if not key:
            return None
        fingerprint = _idempotency_fingerprint(kind, request)
        with self._lock:
            row = self._conn.execute(
                "SELECT id, idempotency_fingerprint, summary_json "
                "FROM backtest_runs WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        if row is None:
            return None
        if row["idempotency_fingerprint"] != fingerprint:
            raise IdempotencyConflict(
                "idempotency_key reutilizada con un payload distinto"
            )
        try:
            snapshot = json.loads(row["summary_json"] or "{}")
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError("snapshot idempotente inválido") from exc
        if not isinstance(snapshot, dict) or not snapshot:
            return None
        return str(row["id"]), snapshot

    def latest_backtest(self) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT r.id AS run_id, r.legacy_backtest_id, "
                "res.id AS result_id, res.payload_json, "
                + _LEDGER_SELECT
                + " FROM backtest_runs r "
                "JOIN backtest_results res ON res.id = r.primary_result_id "
                "LEFT JOIN backtest_ledger_outbox o ON o.backtest_run_id = r.id "
                "WHERE r.kind = 'single' "
                "ORDER BY r.created_ts DESC, r.id DESC LIMIT 1"
            ).fetchone()
        if not row:
            return None
        result = self._backtest_from_result(
            row["payload_json"], row["legacy_backtest_id"], row["result_id"]
        )
        return self._attach_ledger_fields(result, row)

    @staticmethod
    def _attach_ledger_fields(
        result: dict[str, Any] | None, row: sqlite3.Row
    ) -> dict[str, Any] | None:
        """Añade el bloque plano del ledger, también cuando no hay outbox."""
        if result is None:
            return result
        result.update({key: row[key] for key in _LEDGER_FIELDS})
        return result

    def get_backtest(self, bt_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT r.id AS run_id, r.legacy_backtest_id, "
                "res.id AS result_id, res.payload_json, "
                + _LEDGER_SELECT
                + " FROM backtest_results res "
                "JOIN backtest_runs r ON r.id = res.backtest_run_id "
                "LEFT JOIN backtest_ledger_outbox o ON o.backtest_run_id = r.id "
                "WHERE res.id = ?",
                (bt_id,),
            ).fetchone()
        if row:
            result = self._backtest_from_result(
                row["payload_json"], row["legacy_backtest_id"], row["result_id"]
            )
            return self._attach_ledger_fields(result, row)
        # Compatibilidad con una fila legacy que no llegó a indexarse.
        legacy = self._legacy_backtest(bt_id)
        if legacy is not None:
            legacy.update(dict.fromkeys(_LEDGER_FIELDS))
        return legacy

    def _backtest_from_result(
        self,
        payload_json: str | None,
        legacy_id: str | None,
        result_id: str,
    ) -> dict[str, Any] | None:
        if payload_json:
            return _backtest_projection(json.loads(payload_json))
        return self._legacy_backtest(legacy_id or result_id)

    def list_backtest_runs(
        self,
        *,
        limit: int = 25,
        offset: int = 0,
        kind: str | None = None,
        legacy: bool | None = None,
        date_from: int | None = None,
        date_to: int | None = None,
        dataset_id: str | None = None,
        label: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        """Lista corridas con paginación estable por cursor y filtros.

        ``limit/offset`` sigue disponible para clientes antiguos. Cuando se
        pasa ``cursor``, el offset se ignora y la página se ancla al último
        ``(created_ts, id)``, de modo que insertar corridas nuevas no desplaza
        ni duplica las páginas siguientes. ``total`` cuenta el conjunto
        filtrado completo, sin la restricción posicional del cursor.
        """
        where: list[str] = []
        args: list[Any] = []
        if kind is not None:
            where.append("r.kind = ?")
            args.append(kind)
        if legacy is not None:
            where.append(
                "r.legacy_backtest_id IS NOT NULL"
                if legacy
                else "r.legacy_backtest_id IS NULL"
            )
        if date_from is not None:
            where.append("r.created_ts >= ?")
            args.append(int(date_from))
        if date_to is not None:
            where.append("r.created_ts <= ?")
            args.append(int(date_to))
        if dataset_id:
            where.append("r.dataset_id = ?")
            args.append(dataset_id)
        if label:
            escaped = (
                str(label)
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            where.append("LOWER(r.label) LIKE ? ESCAPE '\\'")
            args.append(f"%{escaped.lower()}%")

        position = _decode_run_cursor(cursor) if cursor else None
        page_where = list(where)
        page_args = list(args)
        if position is not None:
            # El orden es (created_ts DESC, id DESC). El cursor apunta al
            # último elemento ya entregado; no usa OFFSET.
            page_where.append(
                "(r.created_ts < ? OR (r.created_ts = ? AND r.id < ?))"
            )
            page_args.extend([position[0], position[0], position[1]])

        clause = (" WHERE " + " AND ".join(page_where)) if page_where else ""
        count_clause = (" WHERE " + " AND ".join(where)) if where else ""
        query = (
            "SELECT r.id, r.created_ts, r.kind, r.label, r.data_source, "
            "r.dataset_id, r.days_requested, r.sessions, r.result_count, "
            "r.legacy_backtest_id, res.trades, res.net_profit, "
            "res.max_drawdown_pct, "
            + _LEDGER_SELECT
            + " FROM backtest_runs r "
            "LEFT JOIN backtest_results res ON res.id = r.primary_result_id "
            "LEFT JOIN backtest_ledger_outbox o ON o.backtest_run_id = r.id"
            + clause
            + " ORDER BY r.created_ts DESC, r.id DESC LIMIT ?"
        )
        params = [*page_args, limit + 1]
        if position is None:
            query += " OFFSET ?"
            params.append(offset)
        with self._lock:
            total = int(
                self._conn.execute(
                    "SELECT COUNT(*) FROM backtest_runs r" + count_clause, args
                ).fetchone()[0]
            )
            rows = self._conn.execute(query, params).fetchall()
        has_more = len(rows) > limit
        page_rows = rows[:limit]
        items = []
        for row in page_rows:
            item = dict(row)
            item["legacy"] = bool(item.pop("legacy_backtest_id"))
            items.append(item)
        next_cursor = None
        if has_more and items:
            last = items[-1]
            next_cursor = _encode_run_cursor(last["created_ts"], last["id"])
        effective_offset = offset if position is None else 0
        return {
            "items": items,
            "total": total,
            "limit": limit,
            "offset": effective_offset,
            "has_more": has_more,
            "next_cursor": next_cursor,
            "next_offset": (
                effective_offset + len(items)
                if position is None and has_more
                else None
            ),
        }

    def get_backtest_run(self, run_id: str) -> dict[str, Any] | None:
        """Devuelve metadatos de una corrida y el resumen de sus resultados."""
        with self._lock:
            row = self._conn.execute(
                "SELECT r.id, r.created_ts, r.kind, r.label, r.data_source, "
                "r.dataset_id, r.dataset_sha256, r.config_sha256, r.code_sha256, "
                "r.days_requested, r.sessions, r.result_count, "
                "r.primary_result_id, r.legacy_backtest_id, "
                + _LEDGER_SELECT
                + " FROM backtest_runs r "
                "LEFT JOIN backtest_ledger_outbox o ON o.backtest_run_id = r.id "
                "WHERE r.id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                return None
            results = self._conn.execute(
                "SELECT id, result_key, label, variant, preset, trades, "
                "net_profit, max_drawdown_pct, profit_factor "
                "FROM backtest_results WHERE backtest_run_id = ? "
                "ORDER BY created_ts, id",
                (run_id,),
            ).fetchall()
            legacy_id = row["legacy_backtest_id"]
            legacy_missing = bool(legacy_id) and self._conn.execute(
                "SELECT 1 FROM backtests WHERE id = ?", (legacy_id,)
            ).fetchone() is None
        run = dict(row)
        run["legacy"] = bool(legacy_id)
        run.pop("legacy_backtest_id", None)
        warnings = ["legacy_source_missing"] if legacy_missing else []
        return {
            "run": run,
            "results": [dict(item) for item in results],
            "warnings": warnings,
        }

    def legacy_diagnostics(self) -> dict[str, Any]:
        """Explica qué filas legacy no se indexaron o no se pueden leer.

        Es estrictamente de lectura: no escribe en ``backtests`` ni en las
        tablas nuevas. La validación reutiliza las mismas reglas del backfill y
        añade los JSON que consumen los lectores de detalle.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT b.*, r.id AS run_id, r.primary_result_id, "
                "res.id AS result_id "
                "FROM backtests b "
                "LEFT JOIN backtest_runs r ON r.legacy_backtest_id = b.id "
                "LEFT JOIN backtest_results res ON res.id = r.primary_result_id "
                "ORDER BY b.created_ts, b.id"
            ).fetchall()

        indexed = 0
        invalid = 0
        items: list[dict[str, Any]] = []
        for row in rows:
            row_id = str(row["id"] or "")
            run_id = row["run_id"]
            if run_id is not None:
                indexed += 1

            created_ts, problems = _legacy_problems(dict(row))

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
            elif row["result_id"] is None:
                problems.append(
                    {
                        "code": "missing_result",
                        "detail": (
                            "La corrida indexada no tiene resultado primario en "
                            "backtest_results."
                        ),
                    }
                )

            if not problems:
                continue
            if any(problem["code"] != "missing_index" for problem in problems):
                invalid += 1
            items.append(
                {
                    "id": row_id,
                    "created_ts": created_ts,
                    "label": row["label"],
                    "indexed": run_id is not None,
                    "backtest_run_id": run_id,
                    "primary_result_id": row["primary_result_id"],
                    "status": (
                        "invalid" if any(
                            problem["code"] != "missing_index" for problem in problems
                        ) else "unindexed"
                    ),
                    "problems": problems,
                }
            )

        return {
            "total": len(rows),
            "indexed": indexed,
            "unindexed": len(rows) - indexed,
            "invalid": invalid,
            "items": items,
            "read_only": True,
        }

    def repair_legacy_backtests(self, *, dry_run: bool = True) -> dict[str, Any]:
        """Repara el legado no indexado con dry-run seguro por defecto."""
        with self._lock:
            return _repair_legacy_backtests(self._conn, dry_run=dry_run)

    def backtest_results_for_compare(
        self, result_ids: list[str]
    ) -> list[dict[str, Any]]:
        """Lee los resultados pedidos con las columnas necesarias para comparar."""
        if not result_ids:
            return []
        marks = ", ".join("?" for _ in result_ids)
        with self._lock:
            rows = self._conn.execute(
                "SELECT res.id, res.backtest_run_id, res.result_key, res.label, "
                "res.variant, res.preset, res.metrics_json, res.trades, "
                "res.net_profit, res.max_drawdown_pct, res.profit_factor, "
                "res.dataset_sha256, res.config_sha256, res.code_sha256, "
                "r.legacy_backtest_id "
                "FROM backtest_results res "
                "JOIN backtest_runs r ON r.id = res.backtest_run_id "
                f"WHERE res.id IN ({marks})",
                tuple(result_ids),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_backtest_result(self, result_id: str) -> dict[str, Any] | None:
        """Payload completo de un resultado nuevo; legacy cae a su proyección."""
        with self._lock:
            row = self._conn.execute(
                "SELECT res.payload_json, r.id AS run_id, "
                "o.status AS ledger_status, o.hypothesis_id AS hypothesis_id, "
                "o.last_error AS ledger_error, "
                "o.ledger_event_id AS ledger_event_id, "
                "o.ledger_event_sha256 AS ledger_event_sha256 "
                "FROM backtest_results res "
                "JOIN backtest_runs r ON r.id = res.backtest_run_id "
                "LEFT JOIN backtest_ledger_outbox o ON o.backtest_run_id = r.id "
                "WHERE res.id = ?",
                (result_id,),
            ).fetchone()
        if row and row["payload_json"]:
            result = json.loads(row["payload_json"])
            if not isinstance(result, dict):
                return result
            return self._attach_ledger_fields(result, row)
        return self.get_backtest(result_id)

    def _legacy_backtest(self, bt_id: str | None) -> dict[str, Any] | None:
        if not bt_id:
            return None
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM backtests WHERE id = ?", (bt_id,)
            ).fetchone()
        return self._backtest_row(row) if row else None

    @staticmethod
    def _backtest_row(row: sqlite3.Row) -> dict[str, Any]:
        return _backtest_projection({
            "id": row["id"],
            "created_ts": row["created_ts"],
            "label": row["label"],
            "data_source": row["data_source"],
            "dataset": json.loads(row["dataset"] or "{}"),
            "diagnostics": json.loads(row["diagnostics"] or "{}"),
            "experiment": json.loads(row["experiment"] or "{}"),
            "config": json.loads(row["config"]),
            "metrics": json.loads(row["metrics"]),
            "trades": json.loads(row["trades"]),
            "equity": json.loads(row["equity"]),
        })

    def close(self) -> None:
        with self._lock:
            self._conn.close()


def read_history_counts(path: Path | str = DB_PATH) -> dict[str, int]:
    """Cuenta el historial sin abrir ``Store`` ni ejecutar migraciones.

    Se usa en la previsualización de consola para que un ``--dry-run`` no
    cree ni modifique la base. Si una tabla todavía no existe, cuenta cero.
    """
    database = Path(path)
    if not database.exists():
        return {"trades": 0, "events": 0, "equity": 0, "kv": 0, "backtests": 0}
    connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        counts: dict[str, int] = {}
        for table in ("trades", "events", "equity", "kv", "backtest_runs"):
            try:
                counts["backtests" if table == "backtest_runs" else table] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                )
            except sqlite3.Error:
                counts["backtests" if table == "backtest_runs" else table] = 0
        return counts
    finally:
        connection.close()


def trade_date_label(ts: int) -> str:
    return et_date_str(ts)


def trade_time_label(ts: int) -> str:
    return et_hm(ts)


def legacy_diagnostics(path: Path | str = DB_PATH) -> dict[str, Any]:
    """Diagnóstico legacy sin abrir ``Store`` ni ejecutar migraciones."""
    from .diagnostics import diagnose_database

    return diagnose_database(path)
