"""Esqueleto y verificación de la captura forward.

Este módulo prepara el contenedor de artefactos de una ventana forward sin
arrancar el motor ni ejecutar backtests:

- ``bars_forward.csv``: barras crudas 1m que después se validan y se sellan;
- ``signals.jsonl`` y ``trades.jsonl`` por brazo;
- ``equity.csv`` por brazo;
- ``manifest.json`` con el SHA-256 de cada stream y el estado de integridad.

El esqueleto nace vacío (solo cabeceras) y con ``status``
``skeleton_awaiting_capture``. No se considera una muestra forward válida ni
autoriza análisis. El guard de holdout se aplica tanto a la ventana como a
cualquier fecha de sesión que se pretenda capturar.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable

from server.market.csv_data import HOLDOUT_END, HOLDOUT_START, parse_timestamp
from server.market.sessions import is_trading_day
from server.timeutil import et_date

from .identity import now_utc
from .paths import FORWARD_ROOT, PROJECT_ROOT, validate_window_id

CAPTURE_SCHEMA = "forward-capture-v1"
CAPTURE_MANIFEST_SCHEMA = "forward-capture-manifest-v1"
STATUS_SKELETON = "skeleton_awaiting_capture"
STATUS_CAPTURED = "captured"
ARMS = ("control", "treatment")

# La ventana forward pre-registrada. Un esqueleto no puede empezar antes:
# W1-W6 y el holdout ya están cerrados para esta hipótesis.
FORWARD_START = date(2026, 12, 1)
FORWARD_END = date(2029, 11, 30)

BAR_HEADER: tuple[str, ...] = (
    "timestamp",
    "symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "contract",
    "expiry",
)
EQUITY_HEADER: tuple[str, ...] = ("seq", "ts", "equity", "peak", "drawdown")

# Ventanas que no pueden aparecer en un artefacto forward. El holdout H1 está
# incluido aquí para que el mensaje sea explícito aunque la ventana ya empiece
# después de él.
FORBIDDEN_WINDOWS: tuple[tuple[str, date, date], ...] = (
    ("W1-W6", date(2025, 1, 10), date(2026, 6, 30)),
    ("H1", HOLDOUT_START, HOLDOUT_END),
    ("EXTERNAL_2024", date(2024, 1, 2), date(2024, 12, 30)),
    ("BURN_IN", date(2026, 11, 23), date(2026, 11, 30)),
)


class CaptureError(ValueError):
    """La ventana, una fecha o un artefacto no cumplen el contrato."""


@dataclass(frozen=True)
class CapturePaths:
    """Rutas del esqueleto dentro de una ventana forward."""

    root: Path
    bars: Path
    manifest: Path
    signals: dict[str, Path]
    trades: dict[str, Path]
    equity: dict[str, Path]
    sessions: Path


def _as_date(value: date | str) -> date:
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise CaptureError(f"fecha inválida: {value!r} (usa YYYY-MM-DD)") from exc


def _overlaps(start: date, end: date, forbidden_start: date, forbidden_end: date) -> bool:
    return start <= forbidden_end and end >= forbidden_start


def _forbidden_for(day: date) -> tuple[str, date, date] | None:
    for item in FORBIDDEN_WINDOWS:
        if item[1] <= day <= item[2]:
            return item
    return None


def guard_session_date(day: date | str) -> date:
    """Valida una fecha de sesión antes de crear o capturar artefactos.

    Rechaza el holdout, las muestras in-sample/prohibidas y cualquier fecha
    fuera de la ventana forward. No descarga ni modifica datos.
    """
    value = _as_date(day)
    if HOLDOUT_START <= value <= HOLDOUT_END:
        raise CaptureError(
            "holdout sellado: "
            f"{value.isoformat()} pertenece a H1 "
            f"({HOLDOUT_START.isoformat()} → {HOLDOUT_END.isoformat()}); "
            "la captura forward no puede abrirlo"
        )
    forbidden = _forbidden_for(value)
    if forbidden is not None:
        name, start, end = forbidden
        raise CaptureError(
            f"muestra prohibida {name}: {value.isoformat()} está en "
            f"{start.isoformat()} → {end.isoformat()}"
        )
    if value < FORWARD_START or value > FORWARD_END:
        raise CaptureError(
            f"fecha fuera de la ventana forward: {value.isoformat()}; "
            f"la ventana permitida es {FORWARD_START.isoformat()} → {FORWARD_END.isoformat()}"
        )
    if not is_trading_day(value):
        raise CaptureError(f"{value.isoformat()} no es una sesión de trading")
    return value


def guard_window(start: date | str, end: date | str) -> tuple[date, date]:
    """Valida una ventana completa antes de crear el esqueleto."""
    first = _as_date(start)
    last = _as_date(end)
    if first > last:
        raise CaptureError("la fecha inicial no puede ser posterior a la final")
    for name, forbidden_start, forbidden_end in FORBIDDEN_WINDOWS:
        if _overlaps(first, last, forbidden_start, forbidden_end):
            if name == "H1":
                raise CaptureError(
                    "la ventana solapa el holdout sellado H1 "
                    f"({HOLDOUT_START.isoformat()} → {HOLDOUT_END.isoformat()})"
                )
            raise CaptureError(
                f"la ventana solapa la muestra prohibida {name} "
                f"({forbidden_start.isoformat()} → {forbidden_end.isoformat()})"
            )
    if first < FORWARD_START or last > FORWARD_END:
        raise CaptureError(
            "ventana fuera del forward pre-registrado: "
            f"{first.isoformat()} → {last.isoformat()}; "
            f"se permite {FORWARD_START.isoformat()} → {FORWARD_END.isoformat()}"
        )
    if not is_trading_day(first) or not is_trading_day(last):
        raise CaptureError("los extremos de la ventana deben ser sesiones de trading")
    return first, last


def capture_paths(root: Path | str | None = None, window_id: str = "") -> CapturePaths:
    """Devuelve las rutas del esqueleto sin crear nada."""
    base = Path(root) if root is not None else FORWARD_ROOT
    base = base.expanduser()
    window = validate_window_id(window_id)
    capture = base / window / "capture"
    return CapturePaths(
        root=capture,
        bars=capture / "bars_forward.csv",
        manifest=capture / "manifest.json",
        signals={arm: capture / "arms" / arm / "signals.jsonl" for arm in ARMS},
        trades={arm: capture / "arms" / arm / "trades.jsonl" for arm in ARMS},
        equity={arm: capture / "arms" / arm / "equity.csv" for arm in ARMS},
        sessions=capture / "sessions",
    )


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _manifest_hash(manifest: dict[str, Any]) -> str:
    payload = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    return _sha256_bytes(_canonical(payload))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=".forward-capture-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _header_bytes(header: Iterable[str]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(header))
    return buffer.getvalue().encode("utf-8")


def validate_bars_file(
    path: Path,
    *,
    start: date | str = FORWARD_START,
    end: date | str = FORWARD_END,
) -> list[str]:
    """Valida fechas, símbolos y OHLC de las barras ya escritas.

    No exige que todas las sesiones estén completas: el archivo puede estar a
    medio de una captura append-only. La validación de sesión completa se hace
    al sellar cada sesión, no aquí.
    """
    first, last = guard_window(start, end)
    errors: list[str] = []
    if not path.exists():
        return [f"faltan barras: {path}"]
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        return [f"no se pueden leer las barras: {exc}"]
    if not rows:
        return ["el CSV de barras no tiene cabecera"]
    if tuple(rows[0]) != BAR_HEADER:
        return [f"cabecera de barras inesperada: {rows[0]!r}"]

    seen: set[tuple[str, int]] = set()
    for number, row in enumerate(rows[1:], 2):
        if not any(cell.strip() for cell in row):
            continue
        if len(row) != len(BAR_HEADER):
            errors.append(f"fila {number}: {len(row)} columnas; se esperaban {len(BAR_HEADER)}")
            continue
        timestamp, symbol = row[0], row[1].upper()
        if symbol not in {"MNQ", "NQ", "ES"}:
            errors.append(f"fila {number}: símbolo no permitido {symbol!r}")
        try:
            ts = parse_timestamp(timestamp, number)
            session = et_date(ts)
        except ValueError as exc:
            errors.append(f"fila {number}: timestamp inválido: {exc}")
            continue
        if (symbol, ts) in seen:
            errors.append(f"fila {number}: timestamp duplicado para {symbol}")
        seen.add((symbol, ts))
        try:
            guard_session_date(session)
        except CaptureError as exc:
            errors.append(f"fila {number}: {exc}")
        if session < first or session > last:
            errors.append(
                f"fila {number}: sesión {session.isoformat()} fuera de la ventana "
                f"{first.isoformat()} → {last.isoformat()}"
            )
        prices: list[float] = []
        for offset, field in enumerate(("open", "high", "low", "close"), 2):
            try:
                value = float(row[offset])
            except (TypeError, ValueError):
                errors.append(f"fila {number}: {field} no numérico")
                prices.append(float("nan"))
                continue
            prices.append(value)
            if not math.isfinite(value) or value <= 0:
                errors.append(f"fila {number}: {field} inválido")
        if len(prices) == 4 and all(math.isfinite(value) for value in prices):
            open_price, high, low, close = prices
            if high < max(open_price, close) or low > min(open_price, close):
                errors.append(f"fila {number}: OHLC incoherente")
        try:
            volume = float(row[6])
        except (TypeError, ValueError):
            errors.append(f"fila {number}: volume no numérico")
        else:
            if not math.isfinite(volume) or volume < 0:
                errors.append(f"fila {number}: volume inválido")
    return errors


def _rows(path: Path, fmt: str) -> tuple[int, list[str], list[str]]:
    """Devuelve filas, cabecera y errores de un stream CSV/JSONL."""
    errors: list[str] = []
    if fmt == "jsonl":
        count = 0
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            count += 1
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"{path.name}: línea {number} no es JSON: {exc}")
                continue
            if not isinstance(value, dict):
                errors.append(f"{path.name}: línea {number} no es un objeto JSON")
        return count, [], errors

    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            rows = list(reader)
    except (OSError, csv.Error) as exc:
        return 0, [], [f"{path.name}: no se puede leer CSV: {exc}"]
    if not rows:
        return 0, [], [f"{path.name}: CSV sin cabecera"]
    header = rows[0]
    data_rows = [row for row in rows[1:] if any(cell.strip() for cell in row)]
    for number, row in enumerate(data_rows, 2):
        if len(row) != len(header):
            errors.append(
                f"{path.name}: fila {number} tiene {len(row)} columnas; "
                f"se esperaban {len(header)}"
            )
    return len(data_rows), header, errors


def _stream(
    path: Path,
    *,
    kind: str,
    arm: str | None,
    fmt: str,
    header: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    if not path.exists():
        raise CaptureError(f"falta el stream {kind}: {path}")
    rows, actual_header, errors = _rows(path, fmt)
    if errors:
        raise CaptureError("; ".join(errors))
    if header is not None and actual_header != list(header):
        raise CaptureError(
            f"{path.name}: cabecera {actual_header!r}; se esperaba {list(header)!r}"
        )
    return {
        "kind": kind,
        "arm": arm,
        "path": path.name,
        "format": fmt,
        "sha256": _sha256_file(path),
        "rows": rows,
        **({"header": list(header)} if header is not None else {}),
    }


def _stream_paths(paths: CapturePaths) -> dict[str, dict[str, Path]]:
    """Mapa estable de streams para el manifiesto y la verificación."""
    return {
        "bars": paths.bars,
        **{
            f"{arm}.signals": paths.signals[arm]
            for arm in ARMS
        },
        **{
            f"{arm}.trades": paths.trades[arm]
            for arm in ARMS
        },
        **{
            f"{arm}.equity": paths.equity[arm]
            for arm in ARMS
        },
    }


def _stream_info(paths: CapturePaths) -> dict[str, dict[str, Any]]:
    """Construye la sección de hashes del manifiesto."""
    result: dict[str, dict[str, Any]] = {}
    for stream_id, path in _stream_paths(paths).items():
        if stream_id == "bars":
            info = _stream(path, kind="bars", arm=None, fmt="csv", header=BAR_HEADER)
        elif stream_id.endswith(".signals"):
            arm = stream_id.removesuffix(".signals")
            info = _stream(path, kind="signals", arm=arm, fmt="jsonl")
        elif stream_id.endswith(".trades"):
            arm = stream_id.removesuffix(".trades")
            info = _stream(path, kind="trades", arm=arm, fmt="jsonl")
        else:
            arm = stream_id.removesuffix(".equity")
            info = _stream(path, kind="equity", arm=arm, fmt="csv", header=EQUITY_HEADER)
        # La ruta se publica relativa a capture/, no solo el basename.
        info["path"] = path.relative_to(paths.root).as_posix()
        result[stream_id] = info
    return result


def _project_relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return str(path)


def _build_manifest(
    *,
    paths: CapturePaths,
    window_id: str,
    start: date,
    end: date,
) -> dict[str, Any]:
    streams = _stream_info(paths)
    manifest: dict[str, Any] = {
        "schema": CAPTURE_MANIFEST_SCHEMA,
        "capture_schema": CAPTURE_SCHEMA,
        "window_id": window_id,
        "status": STATUS_SKELETON,
        "created_at": now_utc(),
        "captured_at": None,
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "allowed_start": FORWARD_START.isoformat(),
            "allowed_end": FORWARD_END.isoformat(),
        },
        "holdout": {
            "id": "H1",
            "start": HOLDOUT_START.isoformat(),
            "end": HOLDOUT_END.isoformat(),
            "sealed": True,
            "accessed": False,
            "status": "sealed_not_executed",
            "guard": "reject_session_dates",
        },
        "policy": {
            "series_mode": "raw",
            "allow_backfill": False,
            "allow_synthetic": False,
            "append_only": True,
            "per_session_manifest": True,
        },
        "target_feed": _project_relative(paths.root.parent / "bars_forward.csv"),
        "streams": streams,
        "sessions": {"dir": "sessions", "count": 0},
        "notes": [
            "Esqueleto únicamente: las cabeceras no son datos forward.",
            "No se arrancó el bot ni se ejecutó ningún backtest.",
            "La captura real debe validar cada sesión, sellarla y hashearla.",
        ],
    }
    manifest["manifest_sha256"] = _manifest_hash(manifest)
    return manifest


def _write_skeleton(paths: CapturePaths) -> None:
    # No se escribe el bars_forward.csv de la raíz de la ventana: ese archivo
    # activa el feed de los perfiles P1. El esqueleto vive aislado en capture/.
    _atomic_write(paths.bars, _header_bytes(BAR_HEADER))
    for arm in ARMS:
        _atomic_write(paths.signals[arm], b"")
        _atomic_write(paths.trades[arm], b"")
        _atomic_write(paths.equity[arm], _header_bytes(EQUITY_HEADER))
    paths.sessions.mkdir(parents=True, exist_ok=True)


def init_capture(
    *,
    window_id: str,
    root: Path | str | None = None,
    start: date | str = FORWARD_START,
    end: date | str = FORWARD_END,
) -> dict[str, Any]:
    """Crea (idempotentemente) el esqueleto forward y devuelve el manifiesto.

    No descarga barras, no abre la DB, no arranca el motor y no ejecuta
    backtests. Si ya existe un manifiesto, solo lo verifica; nunca lo
    sobrescribe.
    """
    window = validate_window_id(window_id)
    first, last = guard_window(start, end)
    paths = capture_paths(root, window)

    if paths.manifest.exists():
        report = verify_capture(window_id=window, root=root)
        if not report["ok"]:
            raise CaptureError(
                "el esqueleto ya existe pero no verifica: "
                + "; ".join(report["errors"])
            )
        return report["manifest"]

    if paths.root.exists() and any(paths.root.iterdir()):
        raise CaptureError(
            f"directorio de captura no vacío sin manifiesto: {paths.root}; "
            "no se sobrescribe"
        )

    paths.root.mkdir(parents=True, exist_ok=True)
    try:
        _write_skeleton(paths)
        manifest = _build_manifest(
            paths=paths, window_id=window, start=first, end=last
        )
        _atomic_write(
            paths.manifest,
            (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
                "utf-8"
            ),
        )
    except Exception:
        # Un fallo deja un directorio parcial; no se borra nada que el usuario
        # pudiera haber puesto allí. El siguiente init lo rechazará de forma
        # explícita.
        raise
    return manifest


def _resolve_stream(paths: CapturePaths, raw: str) -> Path:
    candidate = (paths.root / raw).resolve()
    root = paths.root.resolve()
    if root != candidate and root not in candidate.parents:
        raise CaptureError(f"ruta de stream fuera de capture/: {raw!r}")
    return candidate


def verify_capture(
    *, window_id: str, root: Path | str | None = None
) -> dict[str, Any]:
    """Verifica manifiesto, hashes, cabeceras y guard de holdout.

    Devuelve un informe serializable; no lanza por corrupción de artefactos.
    ``ok=False`` significa que la captura no debe usarse.
    """
    paths = capture_paths(root, window_id)
    errors: list[str] = []
    if not paths.manifest.exists():
        return {
            "ok": False,
            "window_id": window_id,
            "errors": [f"falta el manifiesto: {paths.manifest}"],
            "manifest": None,
        }
    try:
        manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "window_id": window_id,
            "errors": [f"manifiesto inválido: {exc}"],
            "manifest": None,
        }
    if not isinstance(manifest, dict):
        return {
            "ok": False,
            "window_id": window_id,
            "errors": ["el manifiesto debe ser un objeto JSON"],
            "manifest": None,
        }
    if manifest.get("schema") != CAPTURE_MANIFEST_SCHEMA:
        errors.append(
            f"schema inesperado: {manifest.get('schema')!r}; "
            f"se esperaba {CAPTURE_MANIFEST_SCHEMA!r}"
        )
    if manifest.get("window_id") != validate_window_id(window_id):
        errors.append("window_id del manifiesto no coincide")
    expected_manifest_hash = str(manifest.get("manifest_sha256") or "")
    if expected_manifest_hash != _manifest_hash(manifest):
        errors.append("manifest_sha256 no coincide: el manifiesto fue alterado")

    window = manifest.get("window")
    if not isinstance(window, dict):
        errors.append("manifest.window debe ser un objeto")
        window = {}
    try:
        start = _as_date(window["start"])
        end = _as_date(window["end"])
        guard_window(start, end)
    except (KeyError, TypeError, ValueError) as exc:
        errors.append(f"ventana del manifiesto inválida: {exc}")

    holdout = manifest.get("holdout")
    if not isinstance(holdout, dict):
        errors.append("manifest.holdout debe ser un objeto")
        holdout = {}
    if holdout.get("sealed") is not True:
        errors.append("holdout.sealed debe ser true")
    if holdout.get("accessed") is not False:
        errors.append("holdout.accessed debe ser false")
    if holdout.get("start") != HOLDOUT_START.isoformat() or holdout.get(
        "end"
    ) != HOLDOUT_END.isoformat():
        errors.append("los límites del holdout del manifiesto no coinciden")

    streams = manifest.get("streams")
    if not isinstance(streams, dict):
        errors.append("manifest.streams debe ser un objeto")
        streams = {}
    expected_ids = set(_stream_paths(paths))
    if set(streams) != expected_ids:
        missing = sorted(expected_ids - set(streams))
        extra = sorted(set(streams) - expected_ids)
        if missing:
            errors.append("faltan streams: " + ", ".join(missing))
        if extra:
            errors.append("streams no declarados: " + ", ".join(extra))

    for stream_id in sorted(expected_ids & set(streams)):
        info = streams.get(stream_id)
        if not isinstance(info, dict):
            errors.append(f"{stream_id}: entrada de stream inválida")
            continue
        raw_path = info.get("path")
        if not isinstance(raw_path, str) or not raw_path:
            errors.append(f"{stream_id}: falta path")
            continue
        try:
            path = _resolve_stream(paths, raw_path)
        except CaptureError as exc:
            errors.append(f"{stream_id}: {exc}")
            continue
        if not path.exists():
            errors.append(f"{stream_id}: falta {raw_path}")
            continue
        expected_hash = str(info.get("sha256") or "")
        actual_hash = _sha256_file(path)
        if expected_hash != actual_hash:
            errors.append(f"{stream_id}: sha256 no coincide")
        fmt = info.get("format")
        if fmt not in {"csv", "jsonl"}:
            errors.append(f"{stream_id}: formato no soportado {fmt!r}")
            continue
        expected_header = info.get("header")
        try:
            rows, actual_header, row_errors = _rows(path, str(fmt))
        except (OSError, ValueError) as exc:
            errors.append(f"{stream_id}: no se puede leer: {exc}")
            continue
        errors.extend(f"{stream_id}: {item}" for item in row_errors)
        if fmt == "csv" and expected_header is not None and actual_header != expected_header:
            errors.append(f"{stream_id}: cabecera distinta de la declarada")
        if int(info.get("rows", -1)) != rows:
            errors.append(f"{stream_id}: filas declaradas no coinciden")
        if stream_id == "bars":
            try:
                start = _as_date(manifest["window"]["start"])
                end = _as_date(manifest["window"]["end"])
                errors.extend(
                    f"{stream_id}: {item}"
                    for item in validate_bars_file(path, start=start, end=end)
                )
            except (KeyError, TypeError, ValueError) as exc:
                errors.append(f"{stream_id}: no se pudo validar la ventana: {exc}")

    status = manifest.get("status")
    if status not in {STATUS_SKELETON, STATUS_CAPTURED}:
        errors.append(f"status de captura no reconocido: {status!r}")
    if status == STATUS_CAPTURED and int(
        (streams.get("bars") or {}).get("rows", 0)
    ) <= 0:
        errors.append("una captura sellada no puede tener barras vacías")
    if status == STATUS_SKELETON:
        nonempty = [
            stream_id
            for stream_id, info in streams.items()
            if isinstance(info, dict) and int(info.get("rows") or 0) > 0
        ]
        if nonempty:
            errors.append(
                "el esqueleto tiene streams con datos; cambia el estado a capturado: "
                + ", ".join(sorted(nonempty))
            )

    return {
        "ok": not errors,
        "window_id": window_id,
        "errors": errors,
        "manifest": manifest,
    }


def load_manifest_strict(
    *, window_id: str, root: Path | str | None = None
) -> dict[str, Any]:
    """Carga el manifiesto solo si todos sus hashes y guardas verifican.

    Es la variante que deben usar los consumidores que no pueden continuar con
    un artefacto dudoso. ``verify_capture`` sigue existiendo para el panel, que
    necesita reportar el error en lugar de lanzarlo.
    """
    report = verify_capture(window_id=window_id, root=root)
    if not report.get("ok"):
        errors = report.get("errors") or ["manifiesto de captura no válido"]
        raise CaptureError("captura no verificada: " + "; ".join(str(item) for item in errors))
    manifest = report.get("manifest")
    if not isinstance(manifest, dict):
        raise CaptureError("captura sin manifiesto válido")
    return manifest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Crea o verifica el esqueleto de captura forward. "
            "No arranca el motor ni ejecuta backtests."
        )
    )
    parser.add_argument("command", choices=("init", "verify"))
    parser.add_argument("--window-id", required=True)
    parser.add_argument(
        "--root",
        type=Path,
        default=FORWARD_ROOT,
        help=f"Raíz de ventanas forward (por defecto {FORWARD_ROOT}).",
    )
    parser.add_argument("--start", default=FORWARD_START.isoformat())
    parser.add_argument("--end", default=FORWARD_END.isoformat())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "init":
            result = init_capture(
                window_id=args.window_id,
                root=args.root,
                start=args.start,
                end=args.end,
            )
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0
        report = verify_capture(window_id=args.window_id, root=args.root)
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["ok"] else 1
    except CaptureError as exc:
        print(f"FORWARD_CAPTURE_FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
