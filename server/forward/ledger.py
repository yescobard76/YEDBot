"""Ledger append-only encadenado del arnés forward.

Cada registro incluye el hash del anterior. Reescribir, borrar o reordenar una
línea rompe la cadena y el panel lo muestra como `chain_ok=false`.

El append se serializa entre procesos con un lock de archivo y relee la cola
antes de calcular `seq` y `prev_sha256`, porque el brazo y el cierre de sesión
pueden escribir en el mismo ledger.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from pathlib import Path
from typing import Any, Iterable

from .identity import GENESIS, now_utc

LEDGER_SCHEMA = "forward-ledger-v1"
INVALID_EVENTS = frozenset({"VIOLATION", "INTEGRITY_FAIL"})
LOCK_TIMEOUT_SECONDS = 15.0


class LedgerError(RuntimeError):
    """El ledger no se puede leer o su cadena no es válida."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def record_sha256(record: dict[str, Any]) -> str:
    payload = {
        key: record.get(key)
        for key in (
            "schema",
            "seq",
            "ts",
            "window_id",
            "arm",
            "event",
            "detail",
            "prev_sha256",
        )
    }
    return hashlib.sha256(canonical_bytes(payload)).hexdigest()


def has_incomplete_tail(path: Path) -> bool:
    """Indica si el archivo termina a mitad de una línea.

    ``read_records`` ignora esa cola para no fallar durante un append en
    curso, pero el panel y un verificador estricto deben poder distinguirla de
    una cadena completa.
    """
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return False
    with path.open("rb") as handle:
        handle.seek(-1, os.SEEK_END)
        return handle.read(1) != b"\n"


def read_records(path: Path) -> list[dict[str, Any]]:
    """Lee el ledger ignorando una última línea incompleta (append en curso)."""
    path = Path(path)
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    lines = raw.splitlines(keepends=True)
    records: list[dict[str, Any]] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        if not line.endswith("\n"):
            # Un escritor puede estar a mitad de append; no es corrupción.
            break
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise LedgerError(f"{path}: línea {number} no es JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise LedgerError(f"{path}: línea {number} no es un objeto JSON")
        records.append(value)
    return records


def verify_chain(records: Iterable[dict[str, Any]]) -> list[str]:
    problems: list[str] = []
    previous = GENESIS
    for index, record in enumerate(records, start=1):
        if int(record.get("seq") or 0) != index:
            problems.append(f"seq {record.get('seq')} en la posición {index}")
        if str(record.get("prev_sha256") or "") != previous:
            problems.append(f"prev_sha256 roto en seq {record.get('seq')}")
        expected = record_sha256(record)
        if str(record.get("sha256") or "") != expected:
            problems.append(f"sha256 distinto en seq {record.get('seq')}")
        previous = str(record.get("sha256") or "")
    return problems


def derive_status(records: Iterable[dict[str, Any]]) -> str:
    events = [str(record.get("event") or "") for record in records]
    if any(event in INVALID_EVENTS for event in events):
        return "NO_VALIDA"
    if "STOPPED" in events:
        return "DETENIDA"
    if "SESSION_CLOSED" in events:
        return "ACTIVA"
    return "INICIADA"


class _FileLock:
    """Lock exclusivo entre procesos sobre un archivo lateral."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._handle = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+b")
        self._handle.seek(0, os.SEEK_END)
        if self._handle.tell() == 0:
            self._handle.write(b"\0")
            self._handle.flush()
        deadline = time.time() + LOCK_TIMEOUT_SECONDS
        while True:
            try:
                if os.name == "nt":
                    import msvcrt

                    self._handle.seek(0)
                    msvcrt.locking(self._handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX)
                return self
            except OSError:
                if time.time() >= deadline:
                    self._handle.close()
                    raise LedgerError(f"timeout esperando el lock {self.path}") from None
                time.sleep(0.02)

    def __exit__(self, *exc_info) -> None:
        if self._handle is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                self._handle.seek(0)
                msvcrt.locking(self._handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        finally:
            self._handle.close()
            self._handle = None


def lock_path(path: Path) -> Path:
    return Path(path).with_suffix(Path(path).suffix + ".lock")


class Ledger:
    """Escritor serializado; el hash enlaza con el último registro del archivo."""

    def __init__(self, path: Path, window_id: str, arm: str) -> None:
        self.path = Path(path)
        self.window_id = window_id
        self.arm = arm
        self._lock = threading.Lock()
        with _FileLock(lock_path(self.path)):
            records = read_records(self.path)
        problems = verify_chain(records)
        if problems:
            raise LedgerError(
                f"ledger corrupto en {self.path}: " + "; ".join(problems[:5])
            )

    def append(
        self,
        event: str,
        detail: dict[str, Any] | None = None,
        *,
        ts: str | None = None,
    ) -> dict[str, Any]:
        with self._lock, _FileLock(lock_path(self.path)):
            # Una cola sin salto de línea es un append interrumpido. No se
            # repara ni se concatena: hacerlo convertiría dos registros en una
            # línea inválida y rompería la cadena de forma silenciosa.
            if self.path.exists() and self.path.stat().st_size:
                with self.path.open("rb") as handle:
                    handle.seek(-1, os.SEEK_END)
                    if handle.read(1) != b"\n":
                        raise LedgerError(
                            f"ledger con cola incompleta en {self.path}; "
                            "se rechaza el append para no corromper la cadena"
                        )
            records = read_records(self.path)
            problems = verify_chain(records)
            if problems:
                raise LedgerError(
                    f"ledger corrupto en {self.path}: " + "; ".join(problems[:5])
                )
            previous = str(records[-1]["sha256"]) if records else GENESIS
            record: dict[str, Any] = {
                "schema": LEDGER_SCHEMA,
                "seq": len(records) + 1,
                "ts": ts or now_utc(),
                "window_id": self.window_id,
                "arm": self.arm,
                "event": event,
                "detail": detail or {},
                "prev_sha256": previous,
            }
            record["sha256"] = record_sha256(record)
            line = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode(
                "utf-8"
            )
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("ab") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            return record
