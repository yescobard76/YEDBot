"""Rutas y puertos del arnés forward."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FORWARD_ROOT = PROJECT_ROOT / "data" / "forward"

ARM_PORTS = {"control": 8775, "treatment": 8776}
PANEL_PORT = 8778

_WINDOW_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def validate_window_id(window_id: str) -> str:
    value = (window_id or "").strip()
    if not _WINDOW_RE.match(value):
        raise ValueError(
            "window_id inválido: usa letras, números, punto, guion o guion bajo"
        )
    return value


def validate_arm(arm: str) -> str:
    value = (arm or "").strip().lower()
    if value not in ARM_PORTS:
        raise ValueError(f"brazo inválido: {arm!r} (usa control o treatment)")
    return value


def window_dir(window_id: str) -> Path:
    return FORWARD_ROOT / validate_window_id(window_id)


def arm_dir(window_id: str, arm: str) -> Path:
    return window_dir(window_id) / "arms" / validate_arm(arm)


def profile_dir(window_id: str, arm: str) -> Path:
    return arm_dir(window_id, arm) / "profile"


def snapshot_path(window_id: str, arm: str) -> Path:
    return profile_dir(window_id, arm) / "snapshot.json"


def ledger_path(window_id: str, arm: str) -> Path:
    return arm_dir(window_id, arm) / "ledger.jsonl"


def supervisor_ledger_path(window_id: str, arm: str) -> Path:
    return arm_dir(window_id, arm) / "supervisor.jsonl"


def sessions_dir(window_id: str, arm: str) -> Path:
    return arm_dir(window_id, arm) / "sessions"


def heartbeat_path(window_id: str, arm: str) -> Path:
    return arm_dir(window_id, arm) / "heartbeat.json"
