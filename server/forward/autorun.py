"""Arranque de una ventana forward completa: dos brazos y panel.

Es el proceso que registra el Programador de tareas. Lanza un supervisor por
brazo (que a su vez arranca y recupera el brazo) y, opcionalmente, el panel de
solo lectura. Nunca toca el 8765 ni el 8766.
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
from typing import Any

from .identity import now_utc
from .ledger import Ledger
from .paths import ARM_PORTS, PROJECT_ROOT, window_dir

STATE_SCHEMA = "forward-autorun-state-v1"


def state_path(window_id: str) -> Path:
    return window_dir(window_id) / "autorun_state.json"


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".autorun-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _clean_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("YED_")}
    env["PYTHONUNBUFFERED"] = "1"
    return env


def parse_ports(raw: str) -> dict[str, int]:
    values = [item.strip() for item in (raw or "").split(",") if item.strip()]
    if len(values) != 2:
        raise ValueError("--ports debe ser '8775,8776'")
    ports = {"control": int(values[0]), "treatment": int(values[1])}
    if ports != ARM_PORTS:
        raise ValueError(f"los puertos forward son fijos: {ARM_PORTS}")
    return ports


def _process_state(window_id: str, children: dict[str, dict[str, Any]], panel: bool, ports: dict[str, int]) -> dict[str, Any]:
    return {
        "schema": STATE_SCHEMA,
        "window_id": window_id,
        "autorun_pid": os.getpid(),
        "status": "running",
        "panel": panel,
        "ports": ports,
        "processes": {
            name: item["process"].pid
            for name, item in children.items()
            if item["process"].poll() is None
        },
        "updated_at": now_utc(),
    }


def run(window_id: str, ports: dict[str, int], panel: bool, max_restarts: int = 5) -> int:
    root = window_dir(window_id)
    (root / "logs").mkdir(parents=True, exist_ok=True)
    ledger = Ledger(root / "autorun.jsonl", window_id, "autorun")
    stop_file = root / "autorun.stop"
    if stop_file.exists():
        stop_file.unlink()

    ledger.append(
        "AUTORUN_START",
        {
            "autorun_pid": os.getpid(),
            "ports": ports,
            "panel": panel,
            "max_restarts": max_restarts,
            "command": sys.argv,
        },
    )

    stopping = {"value": False}

    def _stop(_signum, _frame) -> None:
        stopping["value"] = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    children: dict[str, dict[str, Any]] = {}
    env = _clean_env()

    def spawn(name: str, command: list[str], log_name: str) -> None:
        log = (root / "logs" / log_name).open("ab")
        process = subprocess.Popen(
            command,
            cwd=str(PROJECT_ROOT),
            env=env,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        ledger.append(
            "PROCESS_SPAWN",
            {"name": name, "pid": process.pid, "command": command},
        )
        children[name] = {
            "process": process,
            "log": log,
            "log_name": log_name,
            "command": command,
            "restarts": 0,
        }

    for arm, port in ports.items():
        spawn(
            f"supervisor-{arm}",
            [
                sys.executable,
                "-m",
                "server.forward.supervisor",
                "--window-id",
                window_id,
                "--arm",
                arm,
                "--port",
                str(port),
            ],
            f"supervisor-{arm}.out",
        )
    if panel:
        spawn(
            "panel",
            [sys.executable, "-m", "server.forward.panel", "--port", "8778"],
            "panel.out",
        )

    _write_state(state_path(window_id), _process_state(window_id, children, panel, ports))

    try:
        while not stopping["value"] and not stop_file.exists():
            for name in list(children):
                item = children.get(name)
                if item is None:
                    continue
                process = item["process"]
                if process.poll() is None:
                    continue
                ledger.append(
                    "PROCESS_EXIT",
                    {"name": name, "pid": process.pid, "returncode": process.returncode},
                )
                try:
                    item["log"].close()
                except Exception:  # noqa: BLE001
                    pass
                if process.returncode == 0:
                    del children[name]
                    continue
                if item["restarts"] >= max_restarts:
                    ledger.append(
                        "AUTORUN_GAVE_UP",
                        {
                            "name": name,
                            "returncode": process.returncode,
                            "restarts": item["restarts"],
                        },
                    )
                    del children[name]
                    continue
                deadline = time.time() + 5.0
                while time.time() < deadline and not stopping["value"]:
                    time.sleep(0.2)
                ledger.append(
                    "PROCESS_RESTART",
                    {
                        "name": name,
                        "returncode": process.returncode,
                        "attempt": item["restarts"] + 1,
                    },
                )
                item["restarts"] += 1
                spawn(name, item["command"], item["log_name"])
            _write_state(
                state_path(window_id), _process_state(window_id, children, panel, ports)
            )
            time.sleep(1.0)
    finally:
        # Parar los brazos por HTTP para que los supervisores salgan con 0 y no
        # dejen hijos huérfanos cuando se termina el proceso del autorun.
        import urllib.request

        for port in ports.values():
            try:
                request = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/forward/stop", method="POST"
                )
                urllib.request.urlopen(request, timeout=3).read()
            except Exception:  # noqa: BLE001
                pass
        time.sleep(2.0)
        for item in list(children.values()):
            process = item["process"]
            if process.poll() is None:
                process.terminate()
        deadline = time.time() + 10
        for item in list(children.values()):
            process = item["process"]
            try:
                process.wait(timeout=max(0.1, deadline - time.time()))
            except subprocess.TimeoutExpired:
                process.kill()
            try:
                item["log"].close()
            except Exception:  # noqa: BLE001
                pass
        ledger.append(
            "AUTORUN_STOP",
            {
                "reason": "signal" if stopping["value"] else "stop_file",
                "autorun_pid": os.getpid(),
            },
        )
        final = _process_state(window_id, {}, panel, ports)
        final["status"] = "stopped"
        final["processes"] = {}
        _write_state(state_path(window_id), final)
        if stop_file.exists():
            stop_file.unlink()

    return 0


def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    try:
        output = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
    except Exception:  # noqa: BLE001
        return False
    return str(pid) in output


def stop(window_id: str, ports: dict[str, int]) -> int:
    """Detiene el autorun de forma ordenada mediante su stop file.

    El autorun para los brazos por HTTP, termina supervisores y panel, y sale.
    El llamador debe ejecutar esto antes de `Stop-ScheduledTask`; si la tarea ya
    se detuvo, los brazos se paran igualmente por HTTP.
    """
    root = window_dir(window_id)
    state_file = state_path(window_id)
    state: dict[str, Any] = {}
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            state = {}

    stop_file = root / "autorun.stop"
    stop_file.write_text("stop\n", encoding="utf-8")
    autorun_pid = int(state.get("autorun_pid") or 0)
    deadline = time.time() + 25
    while time.time() < deadline:
        current = {}
        if state_file.exists():
            try:
                current = json.loads(state_file.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                current = {}
        if current.get("status") == "stopped" or not _pid_alive(autorun_pid):
            break
        time.sleep(0.5)

    import urllib.request

    for port in ports.values():
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/forward/stop", method="POST"
            )
            urllib.request.urlopen(request, timeout=3).read()
        except Exception:  # noqa: BLE001
            pass

    if stop_file.exists():
        stop_file.unlink()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arranca la ventana forward completa.")
    parser.add_argument("--window-id", required=True)
    parser.add_argument("--ports", default="8775,8776")
    parser.add_argument("--panel", action="store_true")
    parser.add_argument("--stop", action="store_true")
    parser.add_argument("--max-restarts", type=int, default=5)
    args = parser.parse_args(argv)
    ports = parse_ports(args.ports)
    if args.stop:
        return stop(args.window_id, ports)
    return run(args.window_id, ports, args.panel, args.max_restarts)


if __name__ == "__main__":
    raise SystemExit(main())
