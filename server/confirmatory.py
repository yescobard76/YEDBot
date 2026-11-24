"""Modo confirmatorio: preflight criptográfico y sello one-shot del holdout.

El módulo no ejecuta ningún backtest al importarse. ``verify`` solo lee
artefactos; ``freeze`` valida y congela la identidad del dataset; y
``run_holdout`` exige una confirmación explícita y crea el sello **antes** de
llamar al motor.

Cadena de confianza que se comprueba antes de ejecutar:

- SHA-256 del protocolo contra ``lock["protocol_sha256"]``.
- SHA-256 del lock contra el manifiesto de dataset congelado.
- ``lock["settings"]`` contra ``Settings`` y contra el perfil activo.
- SHA-256 del árbol de código (``server/`` y ``tests/``) contra el manifiesto.
- SHA-256 del CSV, ``dataset_id`` y ``series_id`` contra el manifiesto.
- Conteos D1-D8 y ventanas de desarrollo/holdout del lock.

El holdout se sella con un archivo creado de forma atómica (``O_EXCL``) y un
ledger append-only. Cualquier sello, ledger o resultado previo bloquea un
segundo intento; no hay opción de recuperación automática.

Uso::

    python -m server.confirmatory verify
    python -m server.confirmatory freeze --dataset data/real/bars_mnq_nq_es_1m.csv
    python -m server.confirmatory run-holdout --execute --confirm "EJECUTAR HOLDOUT"

``run-holdout`` no se ejecuta en esta fase.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from .config import BASE_DIR, Settings, load_settings
from .market.csv_data import CsvDataset, REQUIRED_SYMBOLS

CONFIRMATORY_SCHEMA = "confirmatory-v1"
DATASET_MANIFEST_SCHEMA = "dataset-manifest-v1"
HOLDOUT_SEAL_SCHEMA = "holdout-seal-v1"
HOLDOUT_RECEIPT_SCHEMA = "holdout-receipt-v1"
HOLDOUT_CONFIRMATION = "EJECUTAR HOLDOUT"
CODE_HASH_ALGORITHM = "sha256-tree-v1"


class ConfirmatoryError(RuntimeError):
    """El preflight no es válido o falta un artefacto obligatorio."""


class HoldoutAlreadySealed(ConfirmatoryError):
    """El holdout ya fue reservado; no se permite un segundo intento."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def settings_sha256(settings: dict[str, Any]) -> str:
    """Hash canónico de la configuración del lock, no del formato del archivo."""
    return _sha256_bytes(_canonical_json(settings))


def _resolve(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _display(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _nested(value: Any, *keys: str, default: Any = None) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def _check(
    checks: list[dict[str, Any]],
    name: str,
    ok: bool,
    *,
    expected: Any = None,
    actual: Any = None,
    detail: str | None = None,
) -> None:
    item: dict[str, Any] = {"name": name, "ok": bool(ok)}
    if expected is not None:
        item["expected"] = expected
    if actual is not None:
        item["actual"] = actual
    if detail:
        item["detail"] = detail
    checks.append(item)


def _diff_settings(expected: Any, actual: Any, prefix: str = "") -> list[str]:
    """Lista las diferencias relevantes para no imprimir dos configuraciones enteras."""
    differences: list[str] = []
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            path = f"{prefix}.{key}" if prefix else key
            if key not in expected:
                differences.append(f"{path}: falta en el lock")
            elif key not in actual:
                differences.append(f"{path}: falta en la configuración activa")
            else:
                differences.extend(_diff_settings(expected[key], actual[key], path))
            if len(differences) >= 12:
                return differences[:12]
        return differences[:12]
    if expected != actual:
        differences.append(f"{prefix}: lock={expected!r} activo={actual!r}")
    return differences[:12]


def declared_settings(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Campos que un snapshot declara explícitamente, validados con el esquema actual.

    Un lock congelado no incluye campos añadidos después. ``exclude_unset``
    evita que sus defaults se sumen al snapshot y lo invaliden; los valores
    declarados siguen validándose y comparándose.
    """
    return Settings.model_validate(snapshot).model_dump(exclude_unset=True)


def _project_settings(actual: dict[str, Any], declared: dict[str, Any]) -> dict[str, Any]:
    """Recorta ``actual`` a las claves presentes en ``declared``, recursivamente."""
    projected: dict[str, Any] = {}
    for key, expected in declared.items():
        if key not in actual:
            continue
        value = actual[key]
        if isinstance(expected, dict) and isinstance(value, dict):
            projected[key] = _project_settings(value, expected)
        else:
            projected[key] = value
    return projected


def compute_code_hash(
    root: Path,
    code_roots: Sequence[Path] | None = None,
) -> tuple[str, int]:
    """SHA-256 determinista del árbol de código.

    Incluye solo archivos ``.py`` bajo ``server/`` y ``tests/`` (o las raíces
    indicadas), ordenados por ruta relativa con separadores POSIX. Cada entrada
    incluye longitud de ruta y de contenido para evitar concatenaciones
    ambiguas. No incluye ``__pycache__`` ni archivos generados.
    """
    root = Path(root).resolve()
    roots = list(code_roots) if code_roots else [root / "server", root / "tests"]
    files: list[Path] = []
    for raw_root in roots:
        base = _resolve(root, raw_root)
        if not base.exists():
            raise FileNotFoundError(f"No existe la raíz de código: {base}")
        files.extend(
            path
            for path in base.rglob("*.py")
            if "__pycache__" not in path.parts
        )
    unique = {path.resolve() for path in files}
    if not unique:
        raise ValueError("No hay archivos .py para calcular el hash del código")
    ordered = sorted(unique, key=lambda path: _display(root, path))
    digest = hashlib.sha256()
    digest.update(b"yed-code-tree-v1\0")
    for path in ordered:
        relative = _display(root, path).encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(4, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest(), len(ordered)


def _read_lock(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("El lock no es un objeto JSON")
    if not isinstance(value.get("settings"), dict):
        raise ValueError("El lock no contiene settings")
    return value, _sha256_bytes(raw)


def _read_json(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError(f"{path} no contiene un objeto JSON")
    return value, _sha256_bytes(raw)


def _write_exclusive_json(path: Path, value: Any) -> None:
    """Escribe JSON una sola vez; nunca sobrescribe un artefacto existente."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = _canonical_json(value) + b"\n"
    descriptor = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError("No se pudo escribir el artefacto JSON")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _session_dates(manifest: dict[str, Any], key: str) -> list[date]:
    values = manifest.get(key) or []
    if not isinstance(values, list):
        raise ValueError(f"manifest.{key} no es una lista")
    return [date.fromisoformat(str(value)) for value in values]


def _count_between(dates: Iterable[date], start: str, end: str) -> int:
    first = date.fromisoformat(start)
    last = date.fromisoformat(end)
    return sum(1 for value in dates if first <= value <= last)


def _window_summary(manifest: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    all_dates = _session_dates(manifest, "all_sessions")
    evaluated = _session_dates(manifest, "sessions")
    windows = []
    for window in lock.get("windows") or []:
        windows.append(
            {
                "id": window.get("id"),
                "start": window.get("start"),
                "end": window.get("end"),
                "calendar_sessions": _count_between(
                    all_dates, str(window["start"]), str(window["end"])
                ),
                "sessions": _count_between(
                    evaluated, str(window["start"]), str(window["end"])
                ),
            }
        )
    holdout = lock.get("holdout") or {}
    return {
        "windows": windows,
        "holdout": {
            "id": holdout.get("id"),
            "start": holdout.get("start"),
            "end": holdout.get("end"),
            "calendar_sessions": _count_between(
                all_dates, str(holdout["start"]), str(holdout["end"])
            )
            if holdout.get("start") and holdout.get("end")
            else 0,
            "sessions": _count_between(
                evaluated, str(holdout["start"]), str(holdout["end"])
            )
            if holdout.get("start") and holdout.get("end")
            else 0,
        },
    }


def _summarize_fills(path: Path, root: Path) -> dict[str, Any]:
    """Resume el CSV de rellenos y detecta minutos consecutivos (D6)."""
    if not path.exists():
        return {
            "path": _display(root, path),
            "present": False,
            "sha256": None,
            "count": 0,
            "max_consecutive": 0,
            "invalid_rows": 0,
            "duplicate_timestamps": 0,
        }
    digest = sha256_file(path)
    rows = 0
    invalid = 0
    groups: dict[tuple[str, str], dict[datetime, int]] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            rows += 1
            symbol = (raw.get("symbol") or "").strip().upper()
            contract = (raw.get("contract") or "").strip().upper()
            timestamp = (raw.get("timestamp") or "").strip()
            try:
                instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except ValueError:
                invalid += 1
                continue
            bucket = groups.setdefault((symbol, contract), {})
            bucket[instant] = bucket.get(instant, 0) + 1
    consecutive = 0
    duplicates = 0
    for bucket in groups.values():
        stamps = sorted(bucket)
        run = 0
        previous: datetime | None = None
        for stamp in stamps:
            duplicates += max(0, bucket[stamp] - 1)
            if previous is not None and (stamp - previous).total_seconds() == 60:
                run += 1
            else:
                run = 1
            consecutive = max(consecutive, run)
            previous = stamp
    return {
        "path": _display(root, path),
        "present": True,
        "sha256": digest,
        "count": rows,
        "max_consecutive": consecutive,
        "invalid_rows": invalid,
        "duplicate_timestamps": duplicates,
    }


def _dataset_checks(
    checks: list[dict[str, Any]],
    actual: dict[str, Any],
    fills: dict[str, Any],
    lock: dict[str, Any],
) -> dict[str, Any]:
    """Comprueba D1-D8 y las ventanas del lock contra el manifiesto validado."""
    expected = lock.get("dataset") or {}
    all_dates = _session_dates(actual, "all_sessions")
    evaluated = _session_dates(actual, "sessions")
    validation = actual.get("session_validation") or {}
    contracts = actual.get("contracts") or {}
    contract_count = sum(len(values) for values in contracts.values() if isinstance(values, list))
    contract_expiries = actual.get("contract_expiries") or {}
    rolls = actual.get("rolls") or []
    roll_sessions = actual.get("roll_sessions") or []
    early_closes = validation.get("scheduled_early_close_sessions") or []
    all_common_bars = int(actual.get("all_common_bars") or 0)

    expected_calendar = expected.get("expected_calendar_sessions")
    expected_evaluated = expected.get("expected_sessions")
    expected_contracts = expected.get("expected_contracts")
    expected_roll_events = expected.get("expected_roll_events")
    expected_roll_sessions = expected.get("expected_roll_sessions")
    expected_regular_bars = expected.get("expected_regular_bars")
    expected_early_closes = expected.get("expected_early_close_sessions")
    expected_minutes = expected.get("expected_total_minutes_per_symbol")
    expected_all_minutes = expected.get("expected_total_minutes_all_symbols")
    max_fills = expected.get("max_flat_filled_bars")

    if expected_calendar is not None:
        _check(
            checks,
            "dataset.calendar_sessions",
            len(all_dates) == int(expected_calendar),
            expected=int(expected_calendar),
            actual=len(all_dates),
        )
    if expected_evaluated is not None:
        _check(
            checks,
            "dataset.evaluated_sessions",
            len(evaluated) == int(expected_evaluated),
            expected=int(expected_evaluated),
            actual=len(evaluated),
        )
    if expected_contracts is not None:
        _check(
            checks,
            "dataset.contracts",
            contract_count == int(expected_contracts),
            expected=int(expected_contracts),
            actual=contract_count,
        )
        _check(
            checks,
            "dataset.contract_expiries",
            len(contract_expiries) == int(expected_contracts),
            expected=int(expected_contracts),
            actual=len(contract_expiries),
        )
    if expected_roll_events is not None:
        _check(
            checks,
            "dataset.roll_events",
            len(rolls) == int(expected_roll_events),
            expected=int(expected_roll_events),
            actual=len(rolls),
        )
    if expected_roll_sessions is not None:
        _check(
            checks,
            "dataset.roll_sessions",
            len(roll_sessions) == int(expected_roll_sessions),
            expected=int(expected_roll_sessions),
            actual=len(roll_sessions),
        )
    if expected_regular_bars is not None:
        _check(
            checks,
            "dataset.regular_bars",
            int(validation.get("expected_bars") or 0) == int(expected_regular_bars),
            expected=int(expected_regular_bars),
            actual=validation.get("expected_bars"),
        )
    if expected_early_closes is not None:
        _check(
            checks,
            "dataset.early_close_sessions",
            len(early_closes) == int(expected_early_closes),
            expected=int(expected_early_closes),
            actual=len(early_closes),
        )
    if expected_minutes is not None:
        _check(
            checks,
            "dataset.minutes_per_symbol",
            all_common_bars == int(expected_minutes),
            expected=int(expected_minutes),
            actual=all_common_bars,
        )
    if expected_all_minutes is not None:
        _check(
            checks,
            "dataset.minutes_all_symbols",
            all_common_bars * len(REQUIRED_SYMBOLS) == int(expected_all_minutes),
            expected=int(expected_all_minutes),
            actual=all_common_bars * len(REQUIRED_SYMBOLS),
        )

    _check(
        checks,
        "dataset.validator_ok",
        bool((actual.get("session_validation") or {}).get("ok")),
    )
    _check(
        checks,
        "dataset.invalid_sessions",
        int(validation.get("invalid_sessions") or 0) == 0,
        expected=0,
        actual=validation.get("invalid_sessions"),
    )
    _check(
        checks,
        "dataset.missing_sessions",
        int(validation.get("missing_session_count") or 0) == 0,
        expected=0,
        actual=validation.get("missing_session_count"),
    )
    # ``manifest.gaps`` cuenta también el hueco nocturno entre sesiones; no es
    # un hueco intra-sesión. La ausencia de minutos dentro de cada sesión ya la
    # verifican ``invalid_sessions`` y ``missing_session_count``.
    _check(checks, "dataset.aligned", bool(actual.get("aligned")))
    _check(
        checks,
        "dataset.series_mode",
        actual.get("series_mode") == "raw",
        expected="raw",
        actual=actual.get("series_mode"),
    )
    _check(
        checks,
        "dataset.exclude_roll_sessions",
        actual.get("exclude_roll_sessions") is True,
        expected=True,
        actual=actual.get("exclude_roll_sessions"),
    )
    _check(
        checks,
        "dataset.sessions_subset",
        set(evaluated).issubset(set(all_dates)),
        detail="Las sesiones evaluadas deben ser un subconjunto de las de calendario",
    )

    # D6: rellenos aislados y máximo del protocolo.
    if max_fills is not None:
        present = bool(fills.get("present"))
        _check(checks, "dataset.fills_present", present, expected=True, actual=present)
        if present:
            _check(
                checks,
                "dataset.fills_count",
                int(fills.get("count") or 0) <= int(max_fills),
                expected=f"<= {int(max_fills)}",
                actual=fills.get("count"),
            )
            _check(
                checks,
                "dataset.fills_not_consecutive",
                int(fills.get("max_consecutive") or 0) <= 1,
                expected="<= 1",
                actual=fills.get("max_consecutive"),
            )
            _check(
                checks,
                "dataset.fills_rows_valid",
                int(fills.get("invalid_rows") or 0) == 0
                and int(fills.get("duplicate_timestamps") or 0) == 0,
                expected="0 filas inválidas y 0 duplicados",
                actual={
                    "invalid_rows": fills.get("invalid_rows"),
                    "duplicate_timestamps": fills.get("duplicate_timestamps"),
                },
            )

    # Ventanas pre-registradas: no basta con que el total global cuadre.
    windows = lock.get("windows") or []
    for window in windows:
        identifier = str(window.get("id") or "?")
        start, end = str(window.get("start")), str(window.get("end"))
        all_count = _count_between(all_dates, start, end)
        evaluated_count = _count_between(evaluated, start, end)
        if window.get("calendar_sessions") is not None:
            _check(
                checks,
                f"dataset.window.{identifier}.calendar_sessions",
                all_count == int(window["calendar_sessions"]),
                expected=int(window["calendar_sessions"]),
                actual=all_count,
            )
        if window.get("sessions") is not None:
            _check(
                checks,
                f"dataset.window.{identifier}.sessions",
                evaluated_count == int(window["sessions"]),
                expected=int(window["sessions"]),
                actual=evaluated_count,
            )

    holdout = lock.get("holdout") or {}
    if holdout.get("start") and holdout.get("end"):
        holdout_all = _count_between(all_dates, str(holdout["start"]), str(holdout["end"]))
        holdout_eval = _count_between(evaluated, str(holdout["start"]), str(holdout["end"]))
        if holdout.get("calendar_sessions") is not None:
            _check(
                checks,
                "dataset.holdout.calendar_sessions",
                holdout_all == int(holdout["calendar_sessions"]),
                expected=int(holdout["calendar_sessions"]),
                actual=holdout_all,
            )
        if holdout.get("sessions") is not None:
            _check(
                checks,
                "dataset.holdout.sessions",
                holdout_eval == int(holdout["sessions"]),
                expected=int(holdout["sessions"]),
                actual=holdout_eval,
            )
        overlap = {
            value
            for window in windows
            for value in all_dates
            if str(window.get("start")) <= value.isoformat() <= str(window.get("end"))
        } & {
            value
            for value in all_dates
            if str(holdout["start"]) <= value.isoformat() <= str(holdout["end"])
        }
        _check(
            checks,
            "dataset.holdout.no_overlap",
            not overlap,
            detail=f"Sesiones solapadas: {sorted(value.isoformat() for value in overlap)[:5]}",
        )
    else:
        _check(checks, "dataset.holdout.present", False, detail="El lock no define holdout")

    # Todas las sesiones de calendario deben pertenecer a una ventana declarada
    # o al holdout; una sesión extra no puede colarse en el total.
    ranges = [
        (str(window.get("start")), str(window.get("end")))
        for window in windows
        if window.get("start") and window.get("end")
    ]
    if holdout.get("start") and holdout.get("end"):
        ranges.append((str(holdout["start"]), str(holdout["end"])))
    uncovered = [
        value.isoformat()
        for value in all_dates
        if not any(start <= value.isoformat() <= end for start, end in ranges)
    ]
    _check(
        checks,
        "dataset.sessions_covered_by_lock",
        not uncovered,
        detail=f"Sesiones fuera de las ventanas: {uncovered[:5]}",
    )

    return {
        "calendar_sessions": len(all_dates),
        "evaluated_sessions": len(evaluated),
        "all_common_bars": all_common_bars,
        "contracts": contract_count,
        "roll_events": len(rolls),
        "roll_sessions": len(roll_sessions),
        "windows": _window_summary(actual, lock),
    }


def _manifest_dataset_checks(
    checks: list[dict[str, Any]],
    manifest: dict[str, Any],
    actual: dict[str, Any],
    fills: dict[str, Any],
    lock: dict[str, Any],
) -> None:
    frozen = manifest.get("dataset") or {}
    comparisons = {
        "file_sha256": actual.get("file_hash"),
        "dataset_id": actual.get("dataset_id"),
        "series_id": actual.get("series_id"),
        "series_mode": actual.get("series_mode"),
        "exclude_roll_sessions": actual.get("exclude_roll_sessions"),
        "all_common_bars": actual.get("all_common_bars"),
    }
    for key, actual_value in comparisons.items():
        _check(
            checks,
            f"manifest.dataset.{key}",
            frozen.get(key) == actual_value,
            expected=frozen.get(key),
            actual=actual_value,
        )
    _check(
        checks,
        "manifest.dataset.all_sessions",
        int(frozen.get("all_sessions") or 0) == len(actual.get("all_sessions") or []),
        expected=frozen.get("all_sessions"),
        actual=len(actual.get("all_sessions") or []),
    )
    _check(
        checks,
        "manifest.dataset.sessions",
        int(frozen.get("sessions") or 0) == len(actual.get("sessions") or []),
        expected=frozen.get("sessions"),
        actual=len(actual.get("sessions") or []),
    )
    expected_windows = _window_summary(actual, lock)
    _check(
        checks,
        "manifest.dataset.windows",
        frozen.get("windows") == expected_windows,
        expected=frozen.get("windows"),
        actual=expected_windows,
    )
    frozen_fills = frozen.get("fills") or {}
    _check(
        checks,
        "manifest.dataset.fills_sha256",
        frozen_fills.get("sha256") == fills.get("sha256"),
        expected=frozen_fills.get("sha256"),
        actual=fills.get("sha256"),
    )
    _check(
        checks,
        "manifest.dataset.fills_count",
        int(frozen_fills.get("count") or 0) == int(fills.get("count") or 0),
        expected=frozen_fills.get("count"),
        actual=fills.get("count"),
    )
    _check(
        checks,
        "manifest.dataset.fills_max_consecutive",
        int(frozen_fills.get("max_consecutive") or 0)
        == int(fills.get("max_consecutive") or 0),
        expected=frozen_fills.get("max_consecutive"),
        actual=fills.get("max_consecutive"),
    )


def verify_confirmatory(
    *,
    root: Path | None = None,
    protocol_path: Path | None = None,
    lock_path: Path | None = None,
    dataset_manifest_path: Path | None = None,
    settings: Settings | None = None,
    code_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Verifica todos los artefactos sin ejecutar el backtest.

    Devuelve un informe serializable. ``ok`` es verdadero solo si todas las
    comprobaciones pasan. No escribe archivos.
    """
    root = Path(root or BASE_DIR).resolve()
    protocol_path = _resolve(root, protocol_path or "docs/PROTOCOLO_BACKTEST.md")
    lock_path = _resolve(root, lock_path or "docs/protocolo_backtest.lock.json")
    dataset_manifest_path = _resolve(
        root, dataset_manifest_path or "reports/backtest/dataset_manifest.json"
    )
    checks: list[dict[str, Any]] = []
    artifacts: dict[str, Any] = {
        "protocol": {"path": _display(root, protocol_path), "sha256": None},
        "lock": {"path": _display(root, lock_path), "sha256": None},
        "dataset_manifest": {
            "path": _display(root, dataset_manifest_path),
            "sha256": None,
        },
        "code": {"sha256": None, "files": 0, "algorithm": CODE_HASH_ALGORITHM},
        "dataset": {"path": None, "sha256": None},
    }

    try:
        lock, lock_sha = _read_lock(lock_path)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        _check(checks, "lock.readable", False, detail=str(exc))
        return {
            "schema_version": CONFIRMATORY_SCHEMA,
            "ok": False,
            "checked_at": _utc_now(),
            "checks": checks,
            "artifacts": artifacts,
            "fatal": f"No se pudo leer el lock: {exc}",
        }
    artifacts["lock"]["sha256"] = lock_sha
    _check(
        checks,
        "lock.status",
        lock.get("status") == "frozen-not-executed",
        expected="frozen-not-executed",
        actual=lock.get("status"),
    )

    try:
        protocol_sha = sha256_file(protocol_path)
        _check(checks, "protocol.readable", True)
    except OSError as exc:
        protocol_sha = None
        _check(checks, "protocol.readable", False, detail=str(exc))
    expected_protocol = lock.get("protocol_sha256")
    _check(
        checks,
        "protocol.sha256",
        protocol_sha is not None and protocol_sha == expected_protocol,
        expected=expected_protocol,
        actual=protocol_sha,
    )
    artifacts["protocol"]["sha256"] = protocol_sha

    # La configuración del lock debe ser válida y el perfil activo idéntico.
    expected_settings = lock.get("settings") or {}
    lock_settings_parsed = False
    try:
        declared = declared_settings(expected_settings)
        lock_settings_parsed = True
        _check(checks, "lock.settings_valid", declared == expected_settings)
    except Exception as exc:  # noqa: BLE001 - se reporta como fallo del preflight
        _check(checks, "lock.settings_valid", False, detail=str(exc))

    try:
        actual_settings = settings if settings is not None else load_settings()
        actual_config = _project_settings(actual_settings.model_dump(), expected_settings)
        config_expected = settings_sha256(expected_settings)
        config_actual = settings_sha256(actual_config)
        differences = _diff_settings(expected_settings, actual_config)
        _check(
            checks,
            "config.matches_lock",
            config_expected == config_actual,
            expected=config_expected,
            actual=config_actual,
            detail="; ".join(differences) if differences else None,
        )
    except Exception as exc:  # noqa: BLE001
        actual_settings = None
        actual_config = None
        config_expected = settings_sha256(expected_settings)
        config_actual = None
        _check(checks, "config.matches_lock", False, detail=str(exc))
    artifacts["config"] = {"sha256": config_expected}
    artifacts["config"]["actual_sha256"] = config_actual

    # Código actual: siempre se calcula, incluso si el manifiesto no existe.
    try:
        code_sha, code_files = compute_code_hash(root, code_roots)
        artifacts["code"]["sha256"] = code_sha
        artifacts["code"]["files"] = code_files
        _check(checks, "code.readable", True, actual=code_sha)
    except Exception as exc:  # noqa: BLE001
        code_sha = None
        code_files = 0
        _check(checks, "code.readable", False, detail=str(exc))

    # Manifiesto congelado del dataset.
    manifest: dict[str, Any] | None = None
    try:
        manifest, manifest_sha = _read_json(dataset_manifest_path)
        artifacts["dataset_manifest"]["sha256"] = manifest_sha
        _check(checks, "dataset_manifest.readable", True)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        manifest_sha = None
        _check(checks, "dataset_manifest.readable", False, detail=str(exc))

    if manifest is not None:
        _check(
            checks,
            "manifest.schema_version",
            manifest.get("schema_version") == DATASET_MANIFEST_SCHEMA,
            expected=DATASET_MANIFEST_SCHEMA,
            actual=manifest.get("schema_version"),
        )
        _check(
            checks,
            "manifest.protocol_sha256",
            _nested(manifest, "protocol", "sha256") == protocol_sha,
            expected=protocol_sha,
            actual=_nested(manifest, "protocol", "sha256"),
        )
        _check(
            checks,
            "manifest.protocol_version",
            _nested(manifest, "protocol", "version") == lock.get("protocol_version"),
            expected=lock.get("protocol_version"),
            actual=_nested(manifest, "protocol", "version"),
        )
        _check(
            checks,
            "manifest.lock_sha256",
            _nested(manifest, "lock", "sha256") == lock_sha,
            expected=lock_sha,
            actual=_nested(manifest, "lock", "sha256"),
        )
        _check(
            checks,
            "manifest.config_sha256",
            _nested(manifest, "lock", "config_sha256") == config_expected,
            expected=config_expected,
            actual=_nested(manifest, "lock", "config_sha256"),
        )
        _check(
            checks,
            "manifest.code_sha256",
            _nested(manifest, "code", "sha256") == code_sha,
            expected=_nested(manifest, "code", "sha256"),
            actual=code_sha,
        )
        _check(
            checks,
            "manifest.code_algorithm",
            _nested(manifest, "code", "algorithm") == CODE_HASH_ALGORITHM,
            expected=CODE_HASH_ALGORITHM,
            actual=_nested(manifest, "code", "algorithm"),
        )

    # Dataset: se valida de nuevo completo, no se confía en el manifiesto.
    dataset_path: Path | None = None
    fills: dict[str, Any] = {}
    if lock_settings_parsed:
        feed = expected_settings.get("feed") or {}
        if feed.get("provider") != "csv":
            _check(
                checks,
                "dataset.feed_provider",
                False,
                expected="csv",
                actual=feed.get("provider"),
            )
        else:
            dataset_path = _resolve(root, str(feed.get("csv_path") or ""))
            artifacts["dataset"]["path"] = _display(root, dataset_path)
            try:
                # El preflight verifica el dataset completo, holdout incluido.
                data = CsvDataset.load(
                    dataset_path,
                    REQUIRED_SYMBOLS,
                    series_mode=str(feed.get("series_mode") or "raw"),
                    exclude_roll_sessions=bool(feed.get("exclude_roll_sessions", True)),
                    allow_holdout=True,
                )
            except Exception as exc:  # noqa: BLE001 - cualquier error invalida D1/D2
                _check(checks, "dataset.valid", False, detail=str(exc))
            else:
                actual = data.manifest
                file_sha = sha256_file(dataset_path)
                artifacts["dataset"].update(
                    {
                        "sha256": file_sha,
                        "dataset_id": data.dataset_id,
                        "series_id": data.series_id,
                        "calendar_sessions": len(actual.get("all_sessions") or []),
                        "evaluated_sessions": len(actual.get("sessions") or []),
                    }
                )
                _check(checks, "dataset.valid", True)
                _check(
                    checks,
                    "dataset.file_sha256",
                    file_sha == actual.get("file_hash"),
                    expected=actual.get("file_hash"),
                    actual=file_sha,
                )
                frozen = (manifest or {}).get("dataset") or {}
                frozen_path = frozen.get("path")
                if frozen_path:
                    _check(
                        checks,
                        "manifest.dataset.path",
                        _resolve(root, frozen_path).resolve() == dataset_path.resolve(),
                        expected=str(frozen_path),
                        actual=_display(root, dataset_path),
                    )
                fills_path = _resolve(
                    root,
                    str(frozen.get("fills", {}).get("path") or ""),
                ) if frozen.get("fills") else dataset_path.with_name(
                    dataset_path.stem + "_fills.csv"
                )
                fills = _summarize_fills(fills_path, root)
                _dataset_checks(checks, actual, fills, lock)
                if manifest is not None:
                    _manifest_dataset_checks(checks, manifest, actual, fills, lock)
                artifacts["dataset"]["fills"] = fills

    ok = bool(checks) and all(item["ok"] for item in checks)
    return {
        "schema_version": CONFIRMATORY_SCHEMA,
        "ok": ok,
        "checked_at": _utc_now(),
        "root": str(root),
        "checks": checks,
        "artifacts": artifacts,
    }


def build_dataset_manifest(
    *,
    root: Path | None = None,
    protocol_path: Path | None = None,
    lock_path: Path | None = None,
    dataset_path: Path | None = None,
    fills_path: Path | None = None,
    settings: Settings | None = None,
    code_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Construye un manifiesto congelado sin ejecutar el backtest.

    Falla si el protocolo, la configuración, el dataset o D1-D8 no cuadran con
    el lock. La escritura del manifiesto la hace el llamador con
    :func:`_write_exclusive_json` o el comando ``freeze``.
    """
    root = Path(root or BASE_DIR).resolve()
    protocol_path = _resolve(root, protocol_path or "docs/PROTOCOLO_BACKTEST.md")
    lock_path = _resolve(root, lock_path or "docs/protocolo_backtest.lock.json")
    lock, lock_sha = _read_lock(lock_path)
    if lock.get("status") != "frozen-not-executed":
        raise ConfirmatoryError(
            "El lock no está en estado frozen-not-executed; no se congela el dataset"
        )
    protocol_sha = sha256_file(protocol_path)
    if protocol_sha != lock.get("protocol_sha256"):
        raise ConfirmatoryError("El hash del protocolo no coincide con el lock")
    expected_settings = lock.get("settings") or {}
    try:
        declared = declared_settings(expected_settings)
    except Exception as exc:  # noqa: BLE001
        raise ConfirmatoryError(f"Configuración del lock inválida: {exc}") from exc
    if declared != expected_settings:
        raise ConfirmatoryError("Settings no reproduce exactamente lock['settings']")
    # Si no se inyecta una configuración (tests o API), se exige que el perfil
    # activo sea el del lock; no se congela un dataset con una configuración
    # distinta a la que realmente se va a ejecutar. Solo se comparan las claves
    # declaradas por el lock: los campos nuevos con default no lo invalidan.
    actual_settings = settings if settings is not None else load_settings()
    actual_config = _project_settings(actual_settings.model_dump(), expected_settings)
    if actual_config != expected_settings:
        differences = _diff_settings(expected_settings, actual_config)
        raise ConfirmatoryError(
            "La configuración activa no coincide con el lock: " + "; ".join(differences)
        )

    feed = expected_settings.get("feed") or {}
    if feed.get("provider") != "csv":
        raise ConfirmatoryError("El protocolo confirmatorio exige feed.provider='csv'")
    configured_dataset = _resolve(root, str(feed.get("csv_path") or ""))
    dataset_path = (
        _resolve(root, dataset_path) if dataset_path is not None else configured_dataset
    )
    if dataset_path.resolve() != configured_dataset.resolve():
        raise ConfirmatoryError(
            "El CSV congelado debe ser exactamente feed.csv_path del lock: "
            f"{configured_dataset}"
        )
    # La congelación exige validar las 454 sesiones, holdout incluido.
    data = CsvDataset.load(
        dataset_path,
        REQUIRED_SYMBOLS,
        series_mode=str(feed.get("series_mode") or "raw"),
        exclude_roll_sessions=bool(feed.get("exclude_roll_sessions", True)),
        allow_holdout=True,
    )
    actual = data.manifest
    if fills_path is None:
        fills_path = dataset_path.with_name(dataset_path.stem + "_fills.csv")
    else:
        fills_path = _resolve(root, fills_path)
    fills = _summarize_fills(fills_path, root)

    checks: list[dict[str, Any]] = [
        {"name": "dataset.valid", "ok": True},
        {
            "name": "dataset.file_sha256",
            "ok": sha256_file(dataset_path) == actual.get("file_hash"),
        },
    ]
    _dataset_checks(checks, actual, fills, lock)
    failed = [item for item in checks if not item["ok"]]
    if failed:
        detail = "; ".join(
            f"{item['name']} (esperado={item.get('expected')!r}, actual={item.get('actual')!r})"
            for item in failed[:8]
        )
        raise ConfirmatoryError(f"El dataset no cumple el lock: {detail}")

    code_sha, code_files = compute_code_hash(root, code_roots)
    windows = _window_summary(actual, lock)
    display_roots = [
        _display(root, _resolve(root, path))
        for path in (code_roots or [root / "server", root / "tests"])
    ]
    return {
        "schema_version": DATASET_MANIFEST_SCHEMA,
        "created_at": _utc_now(),
        "protocol": {
            "path": _display(root, protocol_path),
            "sha256": protocol_sha,
            "version": lock.get("protocol_version"),
        },
        "lock": {
            "path": _display(root, lock_path),
            "sha256": lock_sha,
            "config_sha256": settings_sha256(expected_settings),
        },
        "code": {
            "sha256": code_sha,
            "algorithm": CODE_HASH_ALGORITHM,
            "roots": display_roots,
            "files": code_files,
        },
        "dataset": {
            "path": _display(root, dataset_path),
            "file_sha256": actual.get("file_hash"),
            "dataset_id": actual.get("dataset_id"),
            "series_id": actual.get("series_id"),
            "series_mode": actual.get("series_mode"),
            "exclude_roll_sessions": actual.get("exclude_roll_sessions"),
            "all_sessions": len(actual.get("all_sessions") or []),
            "sessions": len(actual.get("sessions") or []),
            "all_common_bars": actual.get("all_common_bars"),
            "contracts": actual.get("contracts") or {},
            "contract_expiries_count": len(actual.get("contract_expiries") or {}),
            "roll_events": len(actual.get("rolls") or []),
            "roll_sessions": actual.get("roll_sessions") or [],
            "range": actual.get("range"),
            "windows": windows,
            "fills": fills,
        },
    }


def freeze_dataset_manifest(
    *,
    output: Path,
    root: Path | None = None,
    protocol_path: Path | None = None,
    lock_path: Path | None = None,
    dataset_path: Path | None = None,
    fills_path: Path | None = None,
    settings: Settings | None = None,
    code_roots: Sequence[Path] | None = None,
) -> dict[str, Any]:
    """Crea el manifiesto una sola vez; nunca sobrescribe uno existente."""
    manifest = build_dataset_manifest(
        root=root,
        protocol_path=protocol_path,
        lock_path=lock_path,
        dataset_path=dataset_path,
        fills_path=fills_path,
        settings=settings,
        code_roots=code_roots,
    )
    _write_exclusive_json(output, manifest)
    return manifest


@dataclass(slots=True)
class HoldoutSeal:
    """Sello one-shot del holdout: archivo atómico más ledger append-only."""

    seal_path: Path
    ledger_path: Path
    result_path: Path
    receipt_path: Path

    def blockers(self) -> list[str]:
        paths = {
            "sello": self.seal_path,
            "ledger": self.ledger_path,
            "resultado": self.result_path,
            "recibo": self.receipt_path,
        }
        return [label for label, path in paths.items() if path.exists()]

    def assert_available(self) -> None:
        blockers = self.blockers()
        if blockers:
            raise HoldoutAlreadySealed(
                "Holdout ya sellado; se bloquea un segundo intento. "
                "Artefactos presentes: " + ", ".join(blockers)
            )

    def reserve(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Reserva el holdout antes de ejecutar. Si falla, el sello permanece."""
        self.assert_available()
        self.seal_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "schema_version": HOLDOUT_SEAL_SCHEMA,
            "status": "reserved",
            "run_id": uuid.uuid4().hex,
            "reserved_at": _utc_now(),
            **payload,
        }
        descriptor = os.open(
            str(self.seal_path),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o644,
        )
        try:
            os.write(descriptor, _canonical_json(record) + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        # En POSIX se puede reforzar con solo lectura. En Windows el atributo
        # read-only complica la limpieza de tests; O_EXCL y el ledger son la
        # garantía primaria.
        if os.name != "nt":
            try:
                os.chmod(self.seal_path, 0o444)
            except OSError:
                pass

        ledger_record = {
            **record,
            "event": "reserved",
            "seal_sha256": sha256_file(self.seal_path),
        }
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8") as handle:
                handle.write(_canonical_json(ledger_record).decode("utf-8") + "\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise ConfirmatoryError(
                "El sello se creó pero no se pudo escribir el ledger; "
                "el holdout queda bloqueado y no debe reintentarse"
            ) from exc
        return record


def _seal_payload(report: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    artifacts = report.get("artifacts") or {}
    holdout = lock.get("holdout") or {}
    return {
        "protocol_version": lock.get("protocol_version"),
        "protocol_sha256": _nested(artifacts, "protocol", "sha256"),
        "lock_sha256": _nested(artifacts, "lock", "sha256"),
        "config_sha256": _nested(artifacts, "config", "sha256"),
        "code_sha256": _nested(artifacts, "code", "sha256"),
        "dataset_manifest_sha256": _nested(artifacts, "dataset_manifest", "sha256"),
        "dataset_file_sha256": _nested(artifacts, "dataset", "sha256"),
        "dataset_id": _nested(artifacts, "dataset", "dataset_id"),
        "series_id": _nested(artifacts, "dataset", "series_id"),
        "holdout": {
            "start": holdout.get("start"),
            "end": holdout.get("end"),
            "sessions": holdout.get("sessions"),
            "calendar_sessions": holdout.get("calendar_sessions"),
        },
    }


def run_holdout(
    *,
    root: Path | None = None,
    protocol_path: Path | None = None,
    lock_path: Path | None = None,
    dataset_manifest_path: Path | None = None,
    seal_path: Path | None = None,
    ledger_path: Path | None = None,
    result_path: Path | None = None,
    receipt_path: Path | None = None,
    settings: Settings | None = None,
    code_roots: Sequence[Path] | None = None,
    runner: Callable[[Settings, int, date], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Verifica, reserva el sello y solo entonces ejecuta el holdout.

    La reserva ocurre antes de invocar ``runner``: si el proceso falla después,
    el holdout queda quemado y no se permite un segundo intento. No se llama
    desde la CLI sin ``--execute`` y la confirmación explícita.
    """
    root = Path(root or BASE_DIR).resolve()
    lock_path = _resolve(root, lock_path or "docs/protocolo_backtest.lock.json")
    dataset_manifest_path = _resolve(
        root, dataset_manifest_path or "reports/backtest/dataset_manifest.json"
    )
    seal = HoldoutSeal(
        seal_path=_resolve(root, seal_path or "reports/backtest/holdout.seal.json"),
        ledger_path=_resolve(root, ledger_path or "reports/backtest/holdout.ledger.jsonl"),
        result_path=_resolve(root, result_path or "reports/backtest/holdout.json"),
        receipt_path=_resolve(root, receipt_path or "reports/backtest/holdout.receipt.json"),
    )
    # Comprobación temprana: no se carga el CSV si el holdout ya está quemado.
    seal.assert_available()

    report = verify_confirmatory(
        root=root,
        protocol_path=protocol_path,
        lock_path=lock_path,
        dataset_manifest_path=dataset_manifest_path,
        settings=settings,
        code_roots=code_roots,
    )
    if not report.get("ok"):
        failed = [item["name"] for item in report.get("checks", []) if not item["ok"]]
        raise ConfirmatoryError(
            "Preflight falló; no se ejecutó el holdout: "
            + ", ".join(failed[:12])
            + ("..." if len(failed) > 12 else "")
        )

    lock, lock_sha = _read_lock(lock_path)
    expected_lock_sha = _nested(report, "artifacts", "lock", "sha256")
    if expected_lock_sha and lock_sha != expected_lock_sha:
        raise ConfirmatoryError(
            "El lock cambió entre la verificación y la reserva del holdout; no se ejecuta"
        )
    holdout = lock.get("holdout") or {}
    if not holdout.get("start") or not holdout.get("sessions"):
        raise ConfirmatoryError("El lock no define un holdout válido")
    effective = Settings.model_validate(lock["settings"])
    reservation = seal.reserve(_seal_payload(report, lock))

    def default_runner(config: Settings, days: int, start: date) -> list[dict[str, Any]]:
        from .backtest import run_variants

        return run_variants(config, days=days, start=start, allow_holdout=True)

    execute = runner or default_runner
    try:
        results = execute(
            effective,
            int(holdout["sessions"]),
            date.fromisoformat(str(holdout["start"])),
        )
    except BaseException:
        # El sello y el ledger ya existen: el holdout no se reintenta.
        raise
    if not isinstance(results, list):
        raise ConfirmatoryError("El runner del holdout no devolvió una lista de resultados")

    _write_exclusive_json(seal.result_path, results)
    receipt = {
        "schema_version": HOLDOUT_RECEIPT_SCHEMA,
        "status": "completed",
        "completed_at": _utc_now(),
        "seal": reservation,
        "verification": report,
        "result_sha256": sha256_file(seal.result_path),
        "result_path": _display(root, seal.result_path),
    }
    _write_exclusive_json(seal.receipt_path, receipt)
    return {
        "results": results,
        "seal": reservation,
        "result_path": seal.result_path,
        "receipt_path": seal.receipt_path,
    }


def _common_paths(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.root).resolve()
    return {
        "root": root,
        "protocol_path": _resolve(root, args.protocol),
        "lock_path": _resolve(root, args.lock),
        "dataset_manifest_path": _resolve(root, args.dataset_manifest),
    }


def _add_common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--root", default=str(BASE_DIR), help="Raíz del proyecto")
    parser.add_argument("--protocol", default="docs/PROTOCOLO_BACKTEST.md")
    parser.add_argument("--lock", default="docs/protocolo_backtest.lock.json")
    parser.add_argument(
        "--dataset-manifest",
        default="reports/backtest/dataset_manifest.json",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Preflight confirmatorio y sello one-shot del holdout. "
            "No ejecuta el backtest salvo run-holdout con confirmación explícita."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify = subparsers.add_parser("verify", help="Verifica todos los artefactos")
    _add_common(verify)

    freeze = subparsers.add_parser("freeze", help="Congela el manifiesto del dataset")
    _add_common(freeze)
    freeze.add_argument("--dataset", default=None, help="CSV a congelar")
    freeze.add_argument("--fills", default=None, help="CSV de rellenos")
    freeze.add_argument(
        "--output",
        default="reports/backtest/dataset_manifest.json",
        help="Manifiesto de salida (debe no existir)",
    )

    holdout = subparsers.add_parser("run-holdout", help="Ejecuta el holdout una sola vez")
    _add_common(holdout)
    holdout.add_argument("--execute", action="store_true", help="Confirma la ejecución real")
    holdout.add_argument("--confirm", default="", help=f"Debe ser {HOLDOUT_CONFIRMATION!r}")
    holdout.add_argument("--seal", default="reports/backtest/holdout.seal.json")
    holdout.add_argument("--ledger", default="reports/backtest/holdout.ledger.jsonl")
    holdout.add_argument("--result", default="reports/backtest/holdout.json")
    holdout.add_argument("--receipt", default="reports/backtest/holdout.receipt.json")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    # La salida es JSON consumible por otras herramientas; en Windows la
    # consola puede usar cp1252 y romper un pipeline UTF-8.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, OSError):
            pass
    parser = _parser()
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    if args.command == "verify":
        report = verify_confirmatory(**_common_paths(args))
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["ok"] else 1

    if args.command == "freeze":
        output = _resolve(root, args.output)
        try:
            manifest = freeze_dataset_manifest(
                output=output,
                root=root,
                protocol_path=args.protocol,
                lock_path=args.lock,
                dataset_path=args.dataset,
                fills_path=args.fills,
            )
        except (ConfirmatoryError, FileExistsError, OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(
            json.dumps(
                {
                    "ok": True,
                    "manifest": str(output),
                    "sha256": sha256_file(output),
                    "dataset_id": manifest["dataset"]["dataset_id"],
                    "series_id": manifest["dataset"]["series_id"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    if args.command == "run-holdout":
        if not args.execute or args.confirm != HOLDOUT_CONFIRMATION:
            parser.error(
                "run-holdout exige --execute y --confirm "
                f"{HOLDOUT_CONFIRMATION!r}; no se ejecutó nada"
            )
        try:
            result = run_holdout(
                root=root,
                protocol_path=args.protocol,
                lock_path=args.lock,
                dataset_manifest_path=args.dataset_manifest,
                seal_path=args.seal,
                ledger_path=args.ledger,
                result_path=args.result,
                receipt_path=args.receipt,
            )
        except (ConfirmatoryError, FileExistsError, OSError, ValueError) as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2
        print(
            json.dumps(
                {
                    "ok": True,
                    "result_path": str(result["result_path"]),
                    "receipt_path": str(result["receipt_path"]),
                    "run_id": result["seal"]["run_id"],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    parser.error("Comando desconocido")
    return 2


if __name__ == "__main__":  # pragma: no cover - CLI
    raise SystemExit(main())
