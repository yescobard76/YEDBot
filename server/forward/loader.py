"""Loader estricto de configuración forward.

A diferencia de :func:`server.config.load_settings`, este loader no crea valores
por defecto, no renombra configuraciones corruptas y no escribe nada. Si el
archivo no coincide con el snapshot T0 o no parsea, el brazo no arranca.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .identity import file_sha256, verify_snapshot


class ForwardIntegrityError(RuntimeError):
    """La configuración del brazo no coincide con la identidad congelada."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = list(dict.fromkeys(problems))
        super().__init__("; ".join(self.problems))


def load_strict(
    profile: Path,
    snapshot: Mapping[str, Any],
    *,
    check_code: bool = True,
) -> Any:
    profile = Path(profile)
    problems = verify_snapshot(profile, snapshot, check_code=check_code)

    config_path = profile / str(snapshot.get("config_path") or "config.json")
    payload: Any = None
    if config_path.exists():
        raw = config_path.read_bytes()
        try:
            payload = json.loads(raw)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"JSON inválido: {exc}")

    if payload is not None:
        from server.config import Settings

        try:
            settings = Settings.model_validate(payload)
        except Exception as exc:  # noqa: BLE001
            problems.append(f"config inválida: {exc}")
            settings = None
        if settings is not None:
            if settings.mode != "paper":
                problems.append(f"mode debe ser paper, no {settings.mode!r}")
            if settings.live.live_enabled:
                problems.append("live.live_enabled debe ser false en forward")
            if problems:
                raise ForwardIntegrityError(problems)
            return settings

    if not problems:
        problems.append("config no utilizable")
    raise ForwardIntegrityError(problems)


def config_hash(profile: Path, snapshot: Mapping[str, Any]) -> str:
    path = Path(profile) / str(snapshot.get("config_path") or "config.json")
    return file_sha256(path) if path.exists() else ""
