"""Arranque de un brazo forward aislado.

El proceso fija `YED_PROFILE_DIR`, `YED_CONFIG_PATH` y `YED_DB_PATH` antes de
importar el motor. Si el perfil no coincide con el snapshot T0, no arranca: no
hay valores por defecto ni renombrado silencioso de la configuración.
"""

from __future__ import annotations

import argparse
import os
import sys

from .identity import read_snapshot
from .ledger import Ledger
from .loader import ForwardIntegrityError, load_strict
from .paths import (
    ARM_PORTS,
    arm_dir,
    ledger_path,
    profile_dir,
    validate_arm,
    validate_window_id,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arranca un brazo forward aislado.")
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--port", type=int, default=None)
    args = parser.parse_args(argv)

    window_id = validate_window_id(args.window_id)
    arm = validate_arm(args.arm)
    port = args.port or ARM_PORTS[arm]
    profile = profile_dir(window_id, arm)

    os.environ["YED_PROFILE_DIR"] = str(profile)
    os.environ["YED_CONFIG_PATH"] = str(profile / "config.json")
    os.environ["YED_DB_PATH"] = str(profile / "yedbot.db")
    os.environ["YED_OPEN"] = "0"

    snapshot = read_snapshot(profile)
    ledger = Ledger(ledger_path(window_id, arm), window_id, arm)

    try:
        settings = load_strict(profile, snapshot)
    except ForwardIntegrityError as exc:
        ledger.append(
            "INTEGRITY_FAIL",
            {
                "stage": "startup",
                "problems": exc.problems,
                "config_path": str(profile / "config.json"),
                "defaults_used": False,
                "renamed_broken": False,
            },
        )
        print("FORWARD_INTEGRITY_FAIL: el brazo no arranca", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 3

    ledger.append(
        "ARM_STARTED",
        {
            "pid": os.getpid(),
            "port": port,
            "profile_dir": str(profile),
            "config_file_sha256": snapshot.get("config_file_sha256"),
            "code_sha256": snapshot.get("code_sha256"),
            "initial_capital": settings.risk.initial_capital,
            "mode": settings.mode,
            "defaults_used": False,
        },
    )

    from .app import serve

    print(
        f"forward arm {window_id}/{arm} en http://127.0.0.1:{port} "
        f"(perfil {profile})",
        flush=True,
    )
    serve(
        window_id=window_id,
        arm=arm,
        port=port,
        settings=settings,
        snapshot=snapshot,
        ledger=ledger,
    )
    ledger.append("ARM_EXITED", {"reason": "server_exit", "pid": os.getpid()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
