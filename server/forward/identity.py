"""Identidad congelada (T0) de un brazo forward.

El snapshot liga la configuración del perfil con el árbol de código que la
ejecuta. Cualquier cambio posterior se detecta al arrancar y al cerrar sesión.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .paths import PROJECT_ROOT, profile_dir, snapshot_path

SNAPSHOT_SCHEMA = "forward-snapshot-v1"
CODE_ALGORITHM = "sha256-tree-v1"
CODE_ROOTS = ("server", "tests")
GENESIS = "0" * 64


def now_utc() -> str:
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".forward-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def code_identity() -> dict[str, Any]:
    from server.confirmatory import compute_code_hash

    roots = [PROJECT_ROOT / name for name in CODE_ROOTS if (PROJECT_ROOT / name).exists()]
    digest, files = compute_code_hash(PROJECT_ROOT, roots)
    return {
        "sha256": digest,
        "algorithm": CODE_ALGORITHM,
        "roots": [root.name for root in roots],
        "files": files,
    }


def _deep_merge(base: dict[str, Any], patch: Mapping[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def resolve_config_path(raw: str | Path) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def init_arm(
    *,
    window_id: str,
    arm: str,
    base_config_path: str | Path,
    overrides: Mapping[str, Any],
    port: int,
    kind: str,
    note: str = "",
) -> dict[str, Any]:
    """Crea el perfil y el snapshot T0. Nunca sobrescribe un perfil existente."""
    profile = profile_dir(window_id, arm)
    config_path = profile / "config.json"
    snap_path = snapshot_path(window_id, arm)
    if config_path.exists() or snap_path.exists():
        raise FileExistsError(f"el perfil forward ya existe: {profile}")

    base_path = resolve_config_path(base_config_path)
    payload = json.loads(base_path.read_text(encoding="utf-8"))
    _deep_merge(payload, overrides)

    from server.config import Settings
    from server.experiments import config_sha256

    settings = Settings.model_validate(payload)
    raw = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    _atomic_write(config_path, raw)

    code = code_identity()
    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "window_id": window_id,
        "arm": arm,
        "kind": kind,
        "created_at": now_utc(),
        "port": port,
        "base_config": str(base_path),
        "config_path": "config.json",
        "config_file_sha256": hashlib.sha256(raw).hexdigest(),
        "config_sha256": config_sha256(settings),
        "code_sha256": code["sha256"],
        "code_algorithm": code["algorithm"],
        "code_roots": code["roots"],
        "code_files": code["files"],
        "initial_capital": settings.risk.initial_capital,
        "note": note,
    }
    _atomic_write(
        snap_path,
        (json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
    )
    return snapshot


def read_snapshot(profile: Path) -> dict[str, Any]:
    path = Path(profile) / "snapshot.json"
    if not path.exists():
        raise FileNotFoundError(f"falta el snapshot T0: {path}")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or value.get("schema") != SNAPSHOT_SCHEMA:
        raise ValueError(f"snapshot inválido: {path}")
    return value


def verify_snapshot(
    profile: Path,
    snapshot: Mapping[str, Any],
    *,
    check_code: bool = True,
) -> list[str]:
    """Devuelve problemas detectados; lista vacía significa identidad intacta."""
    profile = Path(profile)
    problems: list[str] = []

    config_path = profile / str(snapshot.get("config_path") or "config.json")
    if not config_path.exists():
        problems.append(f"config ausente: {config_path}")
    else:
        actual = file_sha256(config_path)
        expected = str(snapshot.get("config_file_sha256") or "")
        if actual != expected:
            problems.append(
                "config_file_sha256 distinto: "
                f"esperado {expected or '(vacío)'}, actual {actual}"
            )

    if check_code:
        expected_code = str(snapshot.get("code_sha256") or "")
        code = code_identity()
        if code["sha256"] != expected_code:
            problems.append(
                "code_sha256 distinto: "
                f"esperado {expected_code or '(vacío)'}, actual {code['sha256']}"
            )
        if int(snapshot.get("code_files") or 0) != int(code["files"]):
            problems.append(
                f"code_files distinto: esperado {snapshot.get('code_files')}, actual {code['files']}"
            )

    return problems
