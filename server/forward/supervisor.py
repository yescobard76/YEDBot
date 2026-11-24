"""Supervisor de un brazo forward: arranque y recuperación tras caída.

El supervisor lanza el brazo como proceso hijo, registra cada arranque, salida
y reinicio en un ledger encadenado, y escribe un heartbeat con el PID vivo.
No reinicia una salida limpia (código 0) ni tras agotar el presupuesto.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .identity import now_utc
from .ledger import Ledger
from .paths import (
    ARM_PORTS,
    PROJECT_ROOT,
    arm_dir,
    heartbeat_path,
    supervisor_ledger_path,
    validate_arm,
    validate_window_id,
)


def _write_heartbeat(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".hb-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def run_supervisor(
    *,
    window_id: str,
    arm: str,
    port: int,
    max_restarts: int = 5,
    restart_delay: float = 2.0,
) -> int:
    window_id = validate_window_id(window_id)
    arm = validate_arm(arm)
    base = arm_dir(window_id, arm)
    log_path = base / "logs" / f"arm-{arm}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    heartbeat = heartbeat_path(window_id, arm)
    ledger = Ledger(supervisor_ledger_path(window_id, arm), window_id, arm)

    stopping = {"value": False}

    def _stop(signum, _frame) -> None:
        stopping["value"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    env = {key: value for key, value in os.environ.items() if not key.startswith("YED_")}
    env["PYTHONUNBUFFERED"] = "1"
    env["YED_FORWARD_SUPERVISED"] = "1"
    command = [
        sys.executable,
        "-m",
        "server.forward.arm",
        "--window-id",
        window_id,
        "--arm",
        arm,
        "--port",
        str(port),
    ]

    ledger.append(
        "SUPERVISOR_START",
        {
            "supervisor_pid": os.getpid(),
            "port": port,
            "max_restarts": max_restarts,
            "restart_delay": restart_delay,
            "command": command,
        },
    )
    _write_heartbeat(
        heartbeat,
        {"status": "starting", "supervisor_pid": os.getpid(), "port": port, "ts": now_utc()},
    )

    restarts = 0
    exit_code = 0
    while not stopping["value"]:
        with log_path.open("ab") as log:
            log.write(
                f"\n=== {now_utc()} supervisor spawn {command[-1]} ===\n".encode("utf-8")
            )
            log.flush()
            process = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        ledger.append("ARM_SPAWN", {"pid": process.pid, "attempt": restarts + 1})
        _write_heartbeat(
            heartbeat,
            {
                "status": "running",
                "pid": process.pid,
                "supervisor_pid": os.getpid(),
                "port": port,
                "restarts": restarts,
                "since": now_utc(),
            },
        )
        last_beat = 0.0
        while process.poll() is None and not stopping["value"]:
            time.sleep(0.2)
            if time.time() - last_beat >= 2.0:
                _write_heartbeat(
                    heartbeat,
                    {
                        "status": "running",
                        "pid": process.pid,
                        "supervisor_pid": os.getpid(),
                        "port": port,
                        "restarts": restarts,
                        "since": now_utc(),
                        "heartbeat_at": now_utc(),
                    },
                )
                last_beat = time.time()
        if stopping["value"] and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
        code = process.poll()
        ledger.append("ARM_EXIT", {"pid": process.pid, "returncode": code})
        _write_heartbeat(
            heartbeat,
            {
                "status": "exited",
                "pid": process.pid,
                "supervisor_pid": os.getpid(),
                "port": port,
                "returncode": code,
                "ts": now_utc(),
            },
        )
        if stopping["value"]:
            ledger.append("SUPERVISOR_STOP", {"reason": "signal", "returncode": code})
            break
        if code == 0:
            ledger.append("SUPERVISOR_STOP", {"reason": "clean_exit", "returncode": 0})
            break
        if restarts >= max_restarts:
            ledger.append(
                "SUPERVISOR_GAVE_UP",
                {"returncode": code, "restarts": restarts, "max_restarts": max_restarts},
            )
            exit_code = 4
            break
        restarts += 1
        ledger.append(
            "ARM_RESTART",
            {"returncode": code, "attempt": restarts, "delay_seconds": restart_delay},
        )
        _write_heartbeat(
            heartbeat,
            {
                "status": "restarting",
                "supervisor_pid": os.getpid(),
                "port": port,
                "restarts": restarts,
                "ts": now_utc(),
            },
        )
        deadline = time.time() + restart_delay
        while time.time() < deadline and not stopping["value"]:
            time.sleep(0.1)

    _write_heartbeat(
        heartbeat,
        {
            "status": "stopped",
            "supervisor_pid": os.getpid(),
            "port": port,
            "restarts": restarts,
            "ts": now_utc(),
        },
    )
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Supervisor de un brazo forward.")
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--arm", required=True)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--max-restarts", type=int, default=5)
    parser.add_argument("--restart-delay", type=float, default=2.0)
    args = parser.parse_args(argv)
    return run_supervisor(
        window_id=args.window_id,
        arm=args.arm,
        port=args.port or ARM_PORTS[args.arm],
        max_restarts=args.max_restarts,
        restart_delay=args.restart_delay,
    )


if __name__ == "__main__":
    raise SystemExit(main())
