"""Identidad canónica de experimentos y ledger append-only de hipótesis.

La identidad de una ejecución combina tres hashes:

- ``config_sha256``: configuración de trading canónica (JSON ordenado). Excluye
  ``feed``, ``live`` y ``mode`` porque son parámetros operativos; el dataset se
  identifica por separado.
- ``code_sha256``: árbol de ``server/`` y ``tests/`` con ``sha256-tree-v1``.
- ``dataset_sha256``: fuente de datos normalizada. Para CSV incluye el hash del
  archivo, el modo de serie y el esquema; para sintéticos, el generador.

El backtest adjunta esta identidad a cada resultado y el arranque paper la
compara con el último backtest persistido antes de operar. El ledger es un
JSONL append-only en ``reports/experiments/ledger.jsonl`` (o en la ruta de
``YED_EXPERIMENT_LEDGER``): registrar o ejecutar nunca reescribe entradas
anteriores. ``POST /api/backtest/run`` acepta ``hypothesis_id`` para registrar
una corrida individual en ese ledger.

Nada de este módulo modifica la configuración activa, la estrategia ni el
holdout.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .config import BASE_DIR, Settings
from .confirmatory import (
    CODE_HASH_ALGORITHM,
    _canonical_json,
    compute_code_hash,
    settings_sha256,
)

EXPERIMENT_SCHEMA = "experiment-v1"
EXPERIMENT_LEDGER_SCHEMA = "experiment-ledger-v1"
CONFIG_HASH_ALGORITHM = "sha256-canonical-config-v1"
DATASET_HASH_ALGORITHM = "sha256-dataset-source-v1"
DEFAULT_LEDGER_PATH = BASE_DIR / "reports" / "experiments" / "ledger.jsonl"

# ``feed`` define la fuente de datos, ``live`` es entorno y ``mode`` es el modo
# de ejecución. Ninguno de los tres debe hacer fallar la paridad de la regla.
NON_PARITY_CONFIG_KEYS = frozenset({"feed", "live", "mode"})

_METRIC_KEYS = (
    "trades",
    "win_rate",
    "profit_factor",
    "expectancy",
    "net_profit",
    "max_drawdown",
    "max_drawdown_pct",
    "total_r",
    "avg_r",
    "sharpe",
    "sortino",
    "stop_losses",
    "take_profits",
    "stop_cap_sessions",
    "qty_zero_sessions",
)


class ExperimentError(RuntimeError):
    """La identidad de una ejecución no se puede construir o verificar."""


class ParityError(ExperimentError):
    """Backtest y paper no comparten configuración o código."""


class LedgerError(ExperimentError):
    """El ledger de hipótesis no se puede leer o escribir de forma segura."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def ledger_record_sha256(record: Mapping[str, Any]) -> str:
    """SHA-256 de la representación canónica de una entrada del ledger.

    El hash identifica el contenido del registro, no el salto de línea que lo
    separa de la siguiente entrada. Se calcula con la misma serialización que
    usa ``ExperimentLedger.append`` para que pueda verificarse desde disco.
    """
    return _sha256(dict(record))


def _ledger_record_matches(
    record: Mapping[str, Any], run_id: str, result_id: str
) -> bool:
    """¿La entrada del ledger acredita esta corrida por run_id o result_id?"""
    record_run = str(record.get("run_id") or "").strip()
    raw_result = record.get("result_id")
    record_result = str(raw_result).strip() if raw_result is not None else None
    if record_run and record_run == run_id:
        return True
    if record_result and record_result == result_id:
        return True
    # Entradas anteriores a ``run_id`` separado usaban el id del resultado
    # también como run_id y no guardaban ``result_id``.
    return bool(record_result is None and record_run and record_run == result_id)


def _ledger_unresolved(
    identity: Mapping[str, Any],
    reason: str,
    detail: str,
    candidate_event_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Fila que la conciliación no puede enlazar, con su motivo explícito."""
    return {
        **identity,
        "reason": reason,
        "detail": detail,
        "candidate_event_ids": list(candidate_event_ids),
    }


def reconcile_ledger_links(
    outbox_rows: Sequence[Mapping[str, Any]],
    records: Sequence[Mapping[str, Any]],
    *,
    claimed_event_ids: Iterable[str] = (),
) -> dict[str, Any]:
    """Reconstruye vínculos de outbox ``sent`` anteriores a la migración v5.

    Cada fila se empareja con una única entrada ``experiment.completed`` por
    ``run_id``, por ``result_id`` o por el formato histórico que usaba el id
    del resultado también como ``run_id``. No se inventan vínculos: una fila
    sin entrada, con varias candidatas, sin ``event_id`` o cuyo evento ya está
    reclamado por otro outbox se devuelve en ``unresolved`` con el motivo.
    """
    completed = [
        record
        for record in records
        if isinstance(record, Mapping)
        and record.get("event") == "experiment.completed"
    ]
    claimed = {str(value) for value in claimed_event_ids if value}
    links: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for row in outbox_rows:
        run_id = str(row.get("backtest_run_id") or "").strip()
        result_id = str(row.get("result_id") or "").strip()
        identity = {
            "backtest_run_id": run_id,
            "result_id": result_id,
            "hypothesis_id": row.get("hypothesis_id"),
        }
        candidates = [
            record
            for record in completed
            if _ledger_record_matches(record, run_id, result_id)
        ]
        if not candidates:
            unresolved.append(
                _ledger_unresolved(
                    identity,
                    "ledger_entry_missing",
                    (
                        "No hay una entrada experiment.completed con este "
                        "run_id ni result_id."
                    ),
                )
            )
            continue
        if len(candidates) > 1:
            unresolved.append(
                _ledger_unresolved(
                    identity,
                    "ledger_entry_ambiguous",
                    (
                        "Varias entradas del ledger coinciden con la corrida; "
                        "no se elige ninguna."
                    ),
                    (str(record.get("event_id") or "") for record in candidates),
                )
            )
            continue
        record = candidates[0]
        event_id = str(record.get("event_id") or "").strip()
        if not event_id:
            unresolved.append(
                _ledger_unresolved(
                    identity,
                    "ledger_entry_without_event_id",
                    "La entrada del ledger no tiene event_id.",
                )
            )
            continue
        if event_id in claimed:
            unresolved.append(
                _ledger_unresolved(
                    identity,
                    "ledger_event_already_linked",
                    (
                        "El event_id de la entrada ya está vinculado a otra "
                        "corrida."
                    ),
                    [event_id],
                )
            )
            continue
        claimed.add(event_id)
        links.append(
            {
                **identity,
                "status": "sent",
                "ledger_event_id": event_id,
                "ledger_event_sha256": ledger_record_sha256(record),
            }
        )
    return {"linked": links, "unresolved": unresolved}


def _normalise_source(value: Any) -> str:
    raw = str(value or "").strip().lower()
    if raw == "csv":
        return "csv"
    if raw in {"synthetic", "simulated", "generator"}:
        return "synthetic"
    if raw == "live":
        return "live"
    raise ExperimentError(f"Origen de dataset no reconocido: {value!r}")


def _assert_hash(name: str, value: str) -> None:
    if not isinstance(value, str) or len(value) != 64:
        raise ExperimentError(f"{name} debe ser un SHA-256 hexadecimal de 64 caracteres")
    try:
        int(value, 16)
    except ValueError as exc:
        raise ExperimentError(
            f"{name} debe ser un SHA-256 hexadecimal de 64 caracteres"
        ) from exc


def _session_count(dataset: Mapping[str, Any]) -> int:
    sessions = dataset.get("sessions")
    if isinstance(sessions, dict):
        return max(0, int(sessions.get("count") or 0))
    if isinstance(sessions, int):
        return max(0, sessions)
    if isinstance(sessions, list):
        return len(sessions)
    return 0


def canonical_config(settings: Settings) -> dict[str, Any]:
    """Serializa solo la configuración que define la regla y el riesgo.

    ``feed``, ``live`` y ``mode`` quedan fuera: la fuente de datos se fija con
    ``dataset_sha256`` y el modo no cambia las decisiones de la estrategia.
    """
    payload = settings.model_dump(mode="json")
    return {
        key: value
        for key, value in payload.items()
        if key not in NON_PARITY_CONFIG_KEYS
    }


def config_sha256(settings: Settings) -> str:
    """Hash canónico de la configuración de trading."""
    return settings_sha256(canonical_config(settings))


def current_code_sha256(
    root: Path | None = None,
    code_roots: Sequence[Path] | None = None,
) -> str:
    """SHA-256 del árbol de código ejecutado."""
    base = Path(root or BASE_DIR).resolve()
    roots = (
        list(code_roots)
        if code_roots
        else [path for path in (base / "server", base / "tests") if path.exists()]
    )
    digest, _ = compute_code_hash(base, roots)
    return digest


def dataset_source(dataset: Mapping[str, Any]) -> dict[str, Any]:
    """Normaliza la fuente de datos que se va a hashear.

    El hash identifica el activo de datos, no la ventana seleccionada. Dos
    backtests con distinta ``start_date`` sobre el mismo CSV comparten fuente;
    ``selected_id`` queda en la identidad para distinguir la muestra.
    """
    kind = _normalise_source(
        dataset.get("kind") or dataset.get("data_source") or dataset.get("source")
    )
    if kind == "csv":
        manifest = dataset.get("manifest") or {}
        file_hash = dataset.get("file_hash") or manifest.get("file_hash")
        if not file_hash:
            raise ExperimentError(
                "El dataset CSV no expone file_hash; no se puede fijar su identidad"
            )
        return {
            "kind": "csv",
            "file_hash": str(file_hash),
            "series_mode": str(
                dataset.get("series_mode")
                or manifest.get("series_mode")
                or "adjusted"
            ),
            "schema_version": dataset.get("schema_version")
            or manifest.get("schema_version"),
        }
    if kind == "synthetic":
        return {
            "kind": "synthetic",
            "generator": str(dataset.get("generator") or "build_session"),
            "generator_version": str(dataset.get("generator_version") or "1"),
        }
    return {
        "kind": "live",
        "provider": str(dataset.get("provider") or "live"),
    }


def dataset_sha256(dataset: Mapping[str, Any]) -> str:
    """Hash canónico de la fuente de datos."""
    return _sha256(dataset_source(dataset))


@dataclass(frozen=True, slots=True)
class ExperimentIdentity:
    """Identidad inmutable de una ejecución de backtest o paper."""

    config_sha256: str
    code_sha256: str
    dataset_sha256: str
    data_source: str
    dataset_id: str | None = None
    series_id: str | None = None
    selected_id: str | None = None
    sessions: int = 0
    schema_version: str = EXPERIMENT_SCHEMA
    config_hash_algorithm: str = CONFIG_HASH_ALGORITHM
    code_hash_algorithm: str = CODE_HASH_ALGORITHM
    dataset_hash_algorithm: str = DATASET_HASH_ALGORITHM

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "config_sha256": self.config_sha256,
            "code_sha256": self.code_sha256,
            "dataset_sha256": self.dataset_sha256,
            "config_hash_algorithm": self.config_hash_algorithm,
            "code_hash_algorithm": self.code_hash_algorithm,
            "dataset_hash_algorithm": self.dataset_hash_algorithm,
            "data_source": self.data_source,
            "dataset_id": self.dataset_id,
            "series_id": self.series_id,
            "selected_id": self.selected_id,
            "sessions": int(self.sessions),
        }

    def validate(self) -> "ExperimentIdentity":
        if self.schema_version != EXPERIMENT_SCHEMA:
            raise ExperimentError(
                f"Schema de experimento no soportado: {self.schema_version!r}"
            )
        _normalise_source(self.data_source)
        _assert_hash("config_sha256", self.config_sha256)
        _assert_hash("code_sha256", self.code_sha256)
        _assert_hash("dataset_sha256", self.dataset_sha256)
        if self.sessions < 0:
            raise ExperimentError("sessions no puede ser negativo")
        return self

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ExperimentIdentity":
        if not isinstance(value, Mapping):
            raise ExperimentError("La identidad del experimento no es un objeto")
        missing = [
            key
            for key in ("config_sha256", "code_sha256", "dataset_sha256")
            if not value.get(key)
        ]
        if missing:
            raise ExperimentError(
                "Identidad incompleta; faltan: " + ", ".join(sorted(missing))
            )
        identity = cls(
            config_sha256=str(value["config_sha256"]),
            code_sha256=str(value["code_sha256"]),
            dataset_sha256=str(value["dataset_sha256"]),
            data_source=_normalise_source(value.get("data_source")),
            dataset_id=str(value["dataset_id"]) if value.get("dataset_id") else None,
            series_id=str(value["series_id"]) if value.get("series_id") else None,
            selected_id=(
                str(value["selected_id"]) if value.get("selected_id") else None
            ),
            sessions=int(value.get("sessions") or 0),
            schema_version=str(value.get("schema_version") or EXPERIMENT_SCHEMA),
            config_hash_algorithm=str(
                value.get("config_hash_algorithm") or CONFIG_HASH_ALGORITHM
            ),
            code_hash_algorithm=str(
                value.get("code_hash_algorithm") or CODE_HASH_ALGORITHM
            ),
            dataset_hash_algorithm=str(
                value.get("dataset_hash_algorithm") or DATASET_HASH_ALGORITHM
            ),
        )
        return identity.validate()


def build_identity(
    settings: Settings,
    dataset: Mapping[str, Any],
    *,
    code_sha256: str | None = None,
) -> ExperimentIdentity:
    """Construye la identidad de un backtest a partir de su dataset."""
    provenance_code = (dataset.get("code") or {}).get("sha256")
    if code_sha256 and provenance_code and code_sha256 != provenance_code:
        raise ExperimentError(
            "El hash de código no coincide con la procedencia del dataset"
        )
    if not code_sha256:
        code_sha256 = provenance_code or current_code_sha256()
    identity = ExperimentIdentity(
        config_sha256=config_sha256(settings),
        code_sha256=str(code_sha256),
        dataset_sha256=dataset_sha256(dataset),
        data_source=_normalise_source(
            dataset.get("kind") or dataset.get("data_source") or dataset.get("source")
        ),
        dataset_id=str(dataset["id"]) if dataset.get("id") else None,
        series_id=str(dataset["series_id"]) if dataset.get("series_id") else None,
        selected_id=(
            str(dataset["selected_id"]) if dataset.get("selected_id") else None
        ),
        sessions=_session_count(dataset),
    )
    return identity.validate()


def identity_from_feed(settings: Settings, feed: Any) -> ExperimentIdentity:
    """Identidad de la fuente que va a consumir el motor paper."""
    kind = str(getattr(feed, "kind", "") or "").lower()
    quality = str(getattr(feed, "quality", "") or "").lower()
    if kind == "csv":
        dataset = getattr(feed, "dataset", None)
        manifest = getattr(feed, "manifest", {}) or {}
        file_hash = getattr(dataset, "file_hash", None) or manifest.get("file_hash")
        if not file_hash:
            raise ExperimentError(
                "El feed CSV no expone file_hash; no se puede verificar la paridad"
            )
        payload: dict[str, Any] = {
            "kind": "csv",
            "id": getattr(dataset, "dataset_id", None) or manifest.get("dataset_id"),
            "series_id": getattr(dataset, "series_id", None)
            or manifest.get("series_id"),
            "file_hash": file_hash,
            "series_mode": getattr(dataset, "series_mode", None)
            or manifest.get("series_mode")
            or settings.feed.series_mode,
            "schema_version": manifest.get("schema_version"),
            "sessions": {"count": int(manifest.get("session_count") or 0)},
        }
    elif kind == "live":
        payload = {"kind": "live", "provider": "live"}
    elif kind == "simulated" or quality == "simulated":
        payload = {
            "kind": "synthetic",
            "generator": "build_session",
            "generator_version": "1",
            "sessions": 0,
        }
    else:
        raise ExperimentError(f"Feed sin identidad de dataset: {kind or quality!r}")
    return build_identity(settings, payload, code_sha256=current_code_sha256())


def assert_identity_matches(
    identity: ExperimentIdentity,
    *,
    settings: Settings | None = None,
    dataset: Mapping[str, Any] | None = None,
) -> ExperimentIdentity:
    """Comprueba que la identidad se puede recomputar desde sus fuentes."""
    identity.validate()
    if settings is not None:
        expected_config = config_sha256(settings)
        if identity.config_sha256 != expected_config:
            raise ParityError(
                "Paridad de configuración rota: "
                f"{identity.config_sha256[:12]} != {expected_config[:12]}"
            )
    if dataset is not None:
        expected_dataset = dataset_sha256(dataset)
        if identity.dataset_sha256 != expected_dataset:
            raise ParityError(
                "Paridad de dataset rota: "
                f"{identity.dataset_sha256[:12]} != {expected_dataset[:12]}"
            )
        provenance_code = (dataset.get("code") or {}).get("sha256")
        if provenance_code and identity.code_sha256 != provenance_code:
            raise ParityError(
                "Paridad de código rota: "
                f"{identity.code_sha256[:12]} != {str(provenance_code)[:12]}"
            )
        dataset_id = dataset.get("id")
        if dataset_id and identity.dataset_id and identity.dataset_id != str(dataset_id):
            raise ParityError("Paridad de dataset_id rota")
    return identity


def assert_result_identity(
    result: Mapping[str, Any],
    *,
    settings: Settings | None = None,
) -> ExperimentIdentity:
    """Valida el bloque ``experiment`` de un resultado de backtest."""
    value = result.get("experiment")
    if not isinstance(value, Mapping):
        raise ExperimentError("El resultado no contiene identidad de experimento")
    dataset = result.get("dataset")
    if not isinstance(dataset, Mapping):
        raise ExperimentError("El resultado no contiene procedencia de dataset")
    identity = ExperimentIdentity.from_dict(value)
    assert_identity_matches(
        identity,
        settings=settings,
        dataset=dataset,
    )
    dataset_id = result.get("dataset_id")
    if dataset_id and identity.dataset_id != str(dataset_id):
        raise ParityError("El dataset_id del resultado no coincide con su identidad")
    return identity


def assert_parity(
    actual: ExperimentIdentity | Mapping[str, Any],
    expected: ExperimentIdentity | Mapping[str, Any],
    *,
    compare_dataset: bool = True,
    context: str = "paper",
) -> None:
    """Exige que dos ejecuciones compartan configuración, código y dataset."""
    left = actual if isinstance(actual, ExperimentIdentity) else ExperimentIdentity.from_dict(actual)
    right = expected if isinstance(expected, ExperimentIdentity) else ExperimentIdentity.from_dict(expected)
    left.validate()
    right.validate()
    differences: list[str] = []
    if left.config_sha256 != right.config_sha256:
        differences.append(
            f"config {left.config_sha256[:12]} != {right.config_sha256[:12]}"
        )
    if left.code_sha256 != right.code_sha256:
        differences.append(
            f"código {left.code_sha256[:12]} != {right.code_sha256[:12]}"
        )
    if compare_dataset and left.dataset_sha256 != right.dataset_sha256:
        differences.append(
            f"dataset {left.dataset_sha256[:12]} != {right.dataset_sha256[:12]}"
        )
    if differences:
        raise ParityError(
            f"Paridad de {context} rota: " + "; ".join(differences)
        )


def _ledger_path(path: Path | str | None) -> Path:
    if path is not None:
        value = Path(path).expanduser()
    else:
        raw = os.environ.get("YED_EXPERIMENT_LEDGER", "").strip()
        value = Path(raw).expanduser() if raw else DEFAULT_LEDGER_PATH
    return value if value.is_absolute() else BASE_DIR / value


def _clean_hypothesis_id(value: str) -> str:
    hypothesis_id = str(value or "").strip()
    if not hypothesis_id:
        raise LedgerError("hypothesis_id no puede estar vacío")
    if "\n" in hypothesis_id or "\r" in hypothesis_id:
        raise LedgerError("hypothesis_id no puede contener saltos de línea")
    return hypothesis_id


class ExperimentLedger:
    """Ledger JSONL append-only de hipótesis y corridas registradas."""

    def __init__(self, path: Path | str | None = None) -> None:
        self.path = _ledger_path(path)

    def records(self) -> list[dict[str, Any]]:
        """Lee el ledger completo; un archivo inexistente es un ledger vacío."""
        if not self.path.exists():
            return []
        out: list[dict[str, Any]] = []
        with self.path.open("r", encoding="utf-8") as handle:
            for number, line in enumerate(handle, 1):
                raw = line.strip()
                if not raw:
                    continue
                try:
                    record = json.loads(raw)
                except ValueError as exc:
                    raise LedgerError(
                        f"Ledger corrupto en {self.path}: línea {number}"
                    ) from exc
                if not isinstance(record, dict):
                    raise LedgerError(
                        f"Ledger corrupto en {self.path}: línea {number} no es un objeto"
                    )
                out.append(record)
        return out

    def append(self, event: str, **fields: Any) -> dict[str, Any]:
        """Añade una entrada y la sincroniza a disco sin tocar las anteriores."""
        if not event:
            raise LedgerError("El evento del ledger requiere un nombre")
        reserved = {"schema_version", "event", "event_id", "created_at"}
        overlap = reserved.intersection(fields)
        if overlap:
            raise LedgerError(
                "El evento no puede sobrescribir campos reservados: "
                + ", ".join(sorted(overlap))
            )
        record = {
            "schema_version": EXPERIMENT_LEDGER_SCHEMA,
            "event": event,
            "event_id": uuid.uuid4().hex,
            "created_at": _utc_now(),
            **fields,
        }
        payload = _canonical_json(record) + b"\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            str(self.path),
            os.O_CREAT | os.O_APPEND | os.O_WRONLY,
            0o644,
        )
        try:
            offset = 0
            while offset < len(payload):
                written = os.write(descriptor, payload[offset:])
                if written <= 0:
                    raise LedgerError("No se pudo escribir el ledger de experimentos")
                offset += written
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return record

    def register(
        self,
        hypothesis_id: str,
        title: str,
        *,
        description: str = "",
        config_sha256: str | None = None,
    ) -> dict[str, Any]:
        """Registra una hipótesis una sola vez."""
        key = _clean_hypothesis_id(hypothesis_id)
        clean_title = str(title or "").strip()
        if not clean_title:
            raise LedgerError("La hipótesis requiere un título")
        for record in self.records():
            if (
                record.get("event") == "hypothesis.registered"
                and record.get("hypothesis_id") == key
            ):
                raise LedgerError(f"La hipótesis {key!r} ya está registrada")
        return self.append(
            "hypothesis.registered",
            hypothesis_id=key,
            title=clean_title,
            description=str(description or ""),
            config_sha256=config_sha256,
        )

    def record_backtest(
        self,
        result: Mapping[str, Any],
        *,
        hypothesis_id: str,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        """Registra una corrida con su identidad y métricas principales.

        ``run_id`` debe ser el id de ``backtest_runs`` cuando la corrida está
        persistida; ``result_id`` conserva el id del resultado primario. Si no
        se pasa, se mantiene el comportamiento histórico de usar el id del
        resultado como identificador de corrida. La operación es idempotente
        por ``(hypothesis_id, run_id)`` para que un reintento del outbox no
        duplique la entrada si el append anterior sí llegó a disco.
        """
        key = _clean_hypothesis_id(hypothesis_id)
        identity = ExperimentIdentity.from_dict(result.get("experiment") or {})
        result_id = str(result.get("id") or "").strip()
        if not result_id:
            raise LedgerError("El backtest no tiene id; no se puede registrar")
        persisted_run_id = str(run_id or "").strip() or result_id
        for record in self.records():
            if (
                record.get("event") == "experiment.completed"
                and record.get("hypothesis_id") == key
                and (
                    record.get("run_id") == persisted_run_id
                    or record.get("result_id") == result_id
                    # Entradas anteriores a este cambio usaban el id del
                    # resultado también como run_id.
                    or (
                        record.get("result_id") is None
                        and record.get("run_id") == result_id
                    )
                )
            ):
                return record
        metrics = result.get("metrics") or {}
        summary = {
            name: metrics.get(name)
            for name in _METRIC_KEYS
            if name in metrics
        }
        return self.append(
            "experiment.completed",
            hypothesis_id=key,
            mode="backtest",
            status="completed",
            run_id=persisted_run_id,
            result_id=result_id,
            run_created_ts=result.get("created_ts"),
            label=result.get("label"),
            data_source=result.get("data_source"),
            dataset_id=result.get("dataset_id"),
            selected_id=identity.selected_id,
            overrides=result.get("overrides") or {},
            metrics=summary,
            identity=identity.as_dict(),
        )

    def runs(self, hypothesis_id: str) -> list[dict[str, Any]]:
        """Corridas registradas para una hipótesis."""
        key = _clean_hypothesis_id(hypothesis_id)
        return [
            record
            for record in self.records()
            if record.get("event") == "experiment.completed"
            and record.get("hypothesis_id") == key
        ]

    def hypotheses(self) -> dict[str, dict[str, Any]]:
        """Hipótesis registradas con su número de corridas."""
        registered: dict[str, dict[str, Any]] = {}
        runs: dict[str, int] = {}
        for record in self.records():
            event = record.get("event")
            key = record.get("hypothesis_id")
            if not isinstance(key, str):
                continue
            if event == "hypothesis.registered":
                registered[key] = {
                    "hypothesis_id": key,
                    "title": record.get("title"),
                    "description": record.get("description"),
                    "config_sha256": record.get("config_sha256"),
                    "registered_at": record.get("created_at"),
                    "registered": True,
                    "run_count": 0,
                }
            elif event == "experiment.completed":
                runs[key] = runs.get(key, 0) + 1
        for key, count in runs.items():
            if key not in registered:
                registered[key] = {
                    "hypothesis_id": key,
                    "title": None,
                    "description": None,
                    "config_sha256": None,
                    "registered_at": None,
                    "registered": False,
                    "run_count": 0,
                }
        for key, item in registered.items():
            item["run_count"] = runs.get(key, 0)
        return registered
