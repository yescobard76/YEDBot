r"""Digest diario encadenado del forward y del 8765.

Escribe un JSON fuera del proyecto (por defecto
``$env:USERPROFILE\YEDBot-audit\forward-digests`` en PowerShell, o
``~/YEDBot-audit/forward-digests`` en Python) con:

- hashes de todos los archivos de la ventana forward;
- estado read-only del panel;
- PID y hashes de configuración del 8765 (nunca abre su SQLite);
- ``prev_digest_sha256`` y ``digest_sha256`` para detectar borrados o
  reescrituras de la cadena.

El script no abre SQLite, no arranca el bot y no escribe dentro del proyecto.
La copia fuera de la máquina se hace con ``scripts/forward_digest_publish.py``
(scp + verificación SHA-256 remota) y se documenta en
``docs/FORWARD_OPERACION.md``; este script solo produce el artefacto externo.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
if str(PROJECT) not in sys.path:
    sys.path.insert(0, str(PROJECT))

from server.forward.paths import (  # noqa: E402
    FORWARD_ROOT,
    validate_window_id,
    window_dir,
)

SCHEMA = "forward-digest-v1"
GENESIS = "0" * 64
DEFAULT_AUDIT_DIR = Path(
    os.environ.get("YED_AUDIT_DIR", str(Path.home() / "YEDBot-audit"))
)


def now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path, base: Path) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": path.relative_to(base).as_posix(),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256_file(path),
    }


def window_files(root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        records.append(file_record(path, root))
    return records


def pid_on_port(port: int) -> int | None:
    try:
        output = subprocess.run(
            ["netstat", "-ano"], capture_output=True, text=True, timeout=30
        ).stdout
    except Exception:  # noqa: BLE001
        return None
    pattern = re.compile(
        rf"127\.0\.0\.1:{port}\s+0\.0\.0\.0:0\s+LISTENING\s+(\d+)"
    )
    for line in output.splitlines():
        match = pattern.search(line)
        if match:
            return int(match.group(1))
    return None


def config_hashes() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for relative in (
        "data/config.json",
        "profiles/live_8765/config.json",
    ):
        path = PROJECT / relative
        result[relative] = sha256_file(path) if path.exists() else None
    return result


def panel_state(root: Path) -> dict[str, Any]:
    try:
        from server.forward.panel import summarize_window

        summary = summarize_window(root)
        return {
            "status": summary.get("status"),
            "capture_ok": (summary.get("capture") or {}).get("ok"),
            "arms": {
                arm: {
                    "status": item.get("status"),
                    "chain_ok": item.get("chain_ok"),
                    "hash_ok": item.get("hash_ok"),
                    "sessions_valid": item.get("sessions_valid"),
                }
                for arm, item in (summary.get("arms") or {}).items()
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def prior_digest(out_dir: Path, current: Path) -> str:
    candidates = [
        path
        for path in sorted(out_dir.glob("digest-*.json"))
        if path != current
    ]
    if not candidates:
        return GENESIS
    try:
        payload = json.loads(candidates[-1].read_text(encoding="utf-8"))
        value = str(payload.get("digest_sha256") or "")
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"digest anterior ilegible: {candidates[-1]}: {exc}") from exc
    if not value:
        raise SystemExit(f"digest anterior sin digest_sha256: {candidates[-1]}")
    return value


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=str(path.parent), prefix=".forward-digest-", suffix=".tmp"
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


def out_dir_external(raw: str) -> Path:
    out = Path(raw).expanduser()
    if not out.is_absolute():
        out = (PROJECT / out).resolve()
    else:
        out = out.resolve()
    project = os.path.normcase(str(PROJECT))
    candidate = os.path.normcase(str(out))
    if candidate == project or candidate.startswith(project + os.sep):
        raise SystemExit(
            f"out-dir dentro del proyecto: {out}; usa un directorio externo "
            f"(por defecto {DEFAULT_AUDIT_DIR / 'forward-digests'})"
        )
    return out


def build_digest(window_id: str, out_dir: Path, day: str, force: bool) -> int:
    root = window_dir(window_id)
    if not root.exists():
        print(f"FORWARD_DIGEST_FAIL: no existe {root}", file=sys.stderr)
        return 2
    target = out_dir / f"digest-{day}.json"
    if target.exists() and not force:
        print(
            json.dumps(
                {
                    "ok": True,
                    "skipped": "digest del día ya existe",
                    "path": str(target),
                },
                ensure_ascii=False,
            )
        )
        return 0

    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "generated_at": now_utc(),
        "day": day,
        "window_id": window_id,
        "project": str(PROJECT),
        "files": window_files(root),
        "panel": panel_state(root),
        "8765": {
            "pid": pid_on_port(8765),
            "configs": config_hashes(),
        },
        "prev_digest_sha256": prior_digest(out_dir, target),
    }
    payload["digest_sha256"] = sha256_bytes(canonical(payload))
    atomic_write(
        target,
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode(
            "utf-8"
        ),
    )
    print(
        json.dumps(
            {
                "ok": True,
                "path": str(target),
                "digest_sha256": payload["digest_sha256"],
                "files": len(payload["files"]),
                "panel_status": payload["panel"].get("status"),
                "pid_8765": payload["8765"]["pid"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def verify_chain(out_dir: Path) -> int:
    files = sorted(out_dir.glob("digest-*.json"))
    if not files:
        print(f"FORWARD_DIGEST_FAIL: no hay digests en {out_dir}", file=sys.stderr)
        return 2
    previous = GENESIS
    for path in files:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            print(f"FORWARD_DIGEST_FAIL: {path}: JSON inválido: {exc}", file=sys.stderr)
            return 2
        claimed = str(payload.get("digest_sha256") or "")
        body = {key: value for key, value in payload.items() if key != "digest_sha256"}
        actual = sha256_bytes(canonical(body))
        if claimed != actual:
            print(f"FORWARD_DIGEST_FAIL: {path}: digest_sha256 no coincide", file=sys.stderr)
            return 2
        if payload.get("prev_digest_sha256") != previous:
            print(f"FORWARD_DIGEST_FAIL: {path}: cadena de digests rota", file=sys.stderr)
            return 2
        previous = claimed
    print(
        json.dumps(
            {
                "ok": True,
                "digests": len(files),
                "last": str(files[-1]),
                "last_digest_sha256": previous,
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-id", default="")
    parser.add_argument(
        "--out-dir",
        default=str(DEFAULT_AUDIT_DIR / "forward-digests"),
        help="Directorio EXTERNO al proyecto.",
    )
    parser.add_argument(
        "--date",
        default=datetime.now().astimezone().date().isoformat(),
        help="Día del digest (YYYY-MM-DD); por defecto hoy local.",
    )
    parser.add_argument("--force", action="store_true", help="Reescribe el digest del día.")
    parser.add_argument("--verify", action="store_true", help="Verifica la cadena y sale.")
    args = parser.parse_args(argv)
    try:
        out_dir = out_dir_external(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.verify:
            return verify_chain(out_dir)
        if not args.window_id:
            parser.error("--window-id es obligatorio salvo con --verify")
        window_id = validate_window_id(args.window_id)
        return build_digest(window_id, out_dir, args.date, args.force)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"FORWARD_DIGEST_FAIL: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
