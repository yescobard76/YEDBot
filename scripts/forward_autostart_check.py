"""Verifica la tarea programada real del forward: alta, disparo y recuperación.

No arranca el 8765 ni el 8766. Registra hashes antes/después y escribe
`AUTOSTART_EVIDENCE.json` dentro de la ventana.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
WINDOW_ID = "2026-12-01_p1_filter025"
WINDOW = PROJECT / "data" / "forward" / WINDOW_ID
TASK = "YEDBot-Forward-Autorun"
BOT_TASK = "YEDBot-8766"
PYTHON = sys.executable


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": sha256(path),
    }


def db_state(path: Path) -> dict[str, Any]:
    return {
        suffix: file_state(path.with_name(path.name + suffix))
        for suffix in ("", "-wal", "-shm")
    }


def listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def pid_on_port(port: int) -> int | None:
    output = subprocess.run(
        ["netstat", "-ano"], capture_output=True, text=True, timeout=30
    ).stdout
    pattern = re.compile(rf"[:.]{port}\s+\S+\s+LISTENING\s+(\d+)")
    for line in output.splitlines():
        match = pattern.search(line)
        if match:
            return int(match.group(1))
    return None


def call(method: str, url: str, payload: Any = None, timeout: float = 6.0):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(body)
            except json.JSONDecodeError:
                return response.status, body
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, body


def wait_http(port: int, timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if listening(port):
            try:
                status, _ = call("GET", f"http://127.0.0.1:{port}/api/health", timeout=2)
                if status == 200:
                    return True
            except Exception:  # noqa: BLE001
                pass
        time.sleep(0.4)
    return False


def wait_port_gone(port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not listening(port):
            return True
        time.sleep(0.3)
    return not listening(port)


def powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-Command", script],
        capture_output=True,
        text=True,
        timeout=60,
    )


def task_info(name: str) -> dict[str, Any]:
    script = (
        f"$t=Get-ScheduledTask -TaskName '{name}'; "
        f"$i=Get-ScheduledTaskInfo -TaskName '{name}'; "
        "[pscustomobject]@{TaskName=$t.TaskName;State=[string]$t.State;"
        "Execute=$t.Actions[0].Execute;Arguments=$t.Actions[0].Arguments;"
        "WorkingDirectory=$t.Actions[0].WorkingDirectory;"
        "NextRunTime=if($i.NextRunTime){$i.NextRunTime.ToString('o')}else{$null};"
        "LastRunTime=if($i.LastRunTime){$i.LastRunTime.ToString('o')}else{$null};"
        "LastTaskResult=$i.LastTaskResult} | ConvertTo-Json -Compress"
    )
    result = powershell(script)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "Get-ScheduledTask falló")
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    return payload


def db_counts(path: Path) -> dict[str, int]:
    if not path.exists():
        return {"trades": -1, "equity": -1}
    uri = f"file:{path.as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True)
        try:
            counts = {}
            for table in ("trades", "equity"):
                try:
                    counts[table] = int(
                        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    )
                except sqlite3.Error:
                    counts[table] = -1
            return counts
        finally:
            conn.close()
    except sqlite3.Error:
        return {"trades": -1, "equity": -1}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


class Evidence:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []

    def check(self, name: str, ok: bool, detail: Any = "") -> None:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.checks)


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001
        pass
    evidence = Evidence()
    if not WINDOW.exists():
        print(f"ABORTADO: no existe la ventana {WINDOW}", file=sys.stderr)
        return 2
    busy = [port for port in (8775, 8776, 8778) if listening(port)]
    if busy:
        print(f"ABORTADO: puertos ocupados {busy}", file=sys.stderr)
        return 2

    snapshot = json.loads(
        (WINDOW / "arms" / "control" / "profile" / "snapshot.json").read_text(
            encoding="utf-8"
        )
    )
    guarded = {
        "data/config.json": PROJECT / "data/config.json",
        "profiles/backtest_real/config.json": PROJECT / "profiles/backtest_real/config.json",
        "profiles/p2_freq/config.json": PROJECT / "profiles/p2_freq/config.json",
        "docs/protocolo_backtest.lock.json": PROJECT / "docs/protocolo_backtest.lock.json",
    }
    before = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "8765_listening": listening(8765),
        "8766": {
            "health": call("GET", "http://127.0.0.1:8766/api/health", timeout=4),
            "pid": pid_on_port(8766),
            "task": task_info(BOT_TASK),
        },
        "task": task_info(TASK),
        "files": {name: file_state(path) for name, path in guarded.items()},
        "db_8765": db_state(PROJECT / "data/yedbot.db"),
        "db_8766": db_state(PROJECT / "reports/backtest/preset_card_8766.db"),
    }

    task = before["task"]
    arguments = str(task.get("Arguments") or "")
    evidence.check(
        "la tarea existe y está lista",
        task.get("TaskName") == TASK and task.get("State") in ("Ready", "Running"),
        {"state": task.get("State")},
    )
    evidence.check(
        "próximo disparo definido",
        bool(str(task.get("NextRunTime") or "").strip())
        and str(task.get("NextRunTime")) != "null",
        task.get("NextRunTime"),
    )
    evidence.check(
        "acción acotada al forward (8775/8776, sin 8765/8766)",
        "server.forward.autorun" in arguments
        and WINDOW_ID in arguments
        and "8775,8776" in arguments
        and "8765" not in arguments
        and "8766" not in arguments
        and "server.main" not in arguments
        and "uvicorn" not in arguments,
        arguments,
    )
    evidence.check(
        "working directory correcto",
        str(task.get("WorkingDirectory") or "").lower()
        == str(PROJECT).lower(),
        task.get("WorkingDirectory"),
    )

    started = powershell(f"Start-ScheduledTask -TaskName '{TASK}'")
    evidence.check(
        "disparo manual aceptado por el Programador",
        started.returncode == 0,
        started.stderr.strip() or "Start-ScheduledTask ok",
    )

    up_control = wait_http(8775)
    up_treatment = wait_http(8776)
    evidence.check("brazo control con health 200 por la tarea", up_control, 8775)
    evidence.check("brazo treatment con health 200 por la tarea", up_treatment, 8776)

    states = {
        arm: call("GET", f"http://127.0.0.1:{port}/api/forward/state")[1]
        for arm, port in (("control", 8775), ("treatment", 8776))
    }
    window_ok = all(
        states[arm].get("window_id") == WINDOW_ID and states[arm].get("arm") == arm
        for arm in ("control", "treatment")
    )
    profile_ok = all(
        "data\\forward" in str(states[arm].get("db_path") or "")
        or "data/forward" in str(states[arm].get("db_path") or "")
        for arm in ("control", "treatment")
    )
    evidence.check(
        "ambos brazos usan la ventana y perfiles forward",
        window_ok and profile_ok,
        {arm: states[arm].get("db_path") for arm in states},
    )
    evidence.check(
        "config y código coinciden con el snapshot T0",
        all(
            states[arm].get("config_file_sha256")
            == json.loads(
                (
                    WINDOW / "arms" / arm / "profile" / "snapshot.json"
                ).read_text(encoding="utf-8")
            )["config_file_sha256"]
            for arm in ("control", "treatment")
        ),
        {arm: states[arm].get("config_file_sha256") for arm in states},
    )

    counts = {
        arm: db_counts(WINDOW / "arms" / arm / "profile" / "yedbot.db")
        for arm in ("control", "treatment")
    }
    evidence.check(
        "DB paper vacía en data/forward (0 trades, 0 equity)",
        all(value["trades"] == 0 and value["equity"] == 0 for value in counts.values()),
        counts,
    )
    running_task = task_info(TASK)
    evidence.check(
        "la tarea figura en ejecución tras el disparo",
        running_task.get("State") == "Running",
        {
            "state": running_task.get("State"),
            "last_result": running_task.get("LastTaskResult"),
            "last_run": running_task.get("LastRunTime"),
        },
    )

    heartbeat = json.loads(
        (WINDOW / "arms" / "control" / "heartbeat.json").read_text(encoding="utf-8")
    )
    old_pid = int(heartbeat["pid"])
    os.kill(old_pid, signal.SIGTERM)
    deadline = time.time() + 45
    restarted = False
    while time.time() < deadline:
        try:
            current = json.loads(
                (WINDOW / "arms" / "control" / "heartbeat.json").read_text(
                    encoding="utf-8"
                )
            )
            new_pid = int(current.get("pid") or 0)
            if (
                new_pid not in (0, old_pid)
                and current.get("status") == "running"
                and call("GET", "http://127.0.0.1:8775/api/health", timeout=1)[0] == 200
            ):
                restarted = True
                break
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)

    events = read_jsonl(WINDOW / "arms" / "control" / "supervisor.jsonl")
    names = [str(item.get("event") or "") for item in events]
    exit_index = next(
        (
            index
            for index, item in enumerate(events)
            if item.get("event") == "ARM_EXIT"
            and int((item.get("detail") or {}).get("pid") or 0) == old_pid
        ),
        -1,
    )
    sequence_ok = (
        exit_index >= 0
        and "ARM_RESTART" in names[exit_index:]
        and "ARM_SPAWN" in names[exit_index:]
        and names.index("ARM_RESTART", exit_index)
        < names.index("ARM_SPAWN", exit_index)
    )
    evidence.check(
        "matar el brazo produce ARM_EXIT -> ARM_RESTART -> ARM_SPAWN",
        restarted and sequence_ok,
        {"pid": old_pid, "events": names[-6:]},
    )
    evidence.check(
        "el brazo vuelve a health 200 tras el reinicio",
        up_control and call("GET", "http://127.0.0.1:8775/api/health", timeout=2)[0] == 200,
        8775,
    )

    stopped = subprocess.run(
        [
            PYTHON,
            "-m",
            "server.forward.autorun",
            "--window-id",
            WINDOW_ID,
            "--ports",
            "8775,8776",
            "--stop",
        ],
        cwd=PROJECT,
        capture_output=True,
        text=True,
        timeout=90,
    )
    evidence.check(
        "parada ordenada del autorun",
        stopped.returncode == 0,
        stopped.stderr.strip() or "stop ok",
    )
    gone = all([wait_port_gone(port, timeout=25) for port in (8775, 8776, 8778)])
    evidence.check("no quedan puertos forward escuchando", gone, "8775/8776/8778")
    powershell(
        f"$s=(Get-ScheduledTask -TaskName '{TASK}').State; "
        f"if ($s -eq 'Running') {{ Stop-ScheduledTask -TaskName '{TASK}' }}"
    )

    after = {
        "time": datetime.now().isoformat(timespec="seconds"),
        "8765_listening": listening(8765),
        "8766": {
            "health": call("GET", "http://127.0.0.1:8766/api/health", timeout=4),
            "pid": pid_on_port(8766),
            "task": task_info(BOT_TASK),
        },
        "task": task_info(TASK),
        "files": {name: file_state(path) for name, path in guarded.items()},
        "db_8765": db_state(PROJECT / "data/yedbot.db"),
        "db_8766": db_state(PROJECT / "reports/backtest/preset_card_8766.db"),
    }

    identical = (
        before["files"] == after["files"]
        and before["db_8765"] == after["db_8765"]
        and before["db_8766"] == after["db_8766"]
    )
    evidence.check(
        "hashes de config, DB y lock del 8765/8766 idénticos",
        identical,
        {
            "configs": before["files"] == after["files"],
            "db_8765": before["db_8765"] == after["db_8765"],
            "db_8766": before["db_8766"] == after["db_8766"],
        },
    )
    evidence.check(
        "el 8766 no se reinició",
        before["8766"]["pid"] == after["8766"]["pid"]
        and before["8766"]["task"].get("LastRunTime")
        == after["8766"]["task"].get("LastRunTime")
        and after["8766"]["health"][0] == 200,
        {
            "pid_before": before["8766"]["pid"],
            "pid_after": after["8766"]["pid"],
            "task_last_run_before": before["8766"]["task"].get("LastRunTime"),
            "task_last_run_after": after["8766"]["task"].get("LastRunTime"),
        },
    )
    evidence.check(
        "el 8765 sigue sin arrancar",
        before["8765_listening"] is False and after["8765_listening"] is False,
        {"before": before["8765_listening"], "after": after["8765_listening"]},
    )
    evidence.check(
        "la tarea queda registrada y lista tras la prueba",
        after["task"].get("TaskName") == TASK
        and after["task"].get("State") in ("Ready", "Running")
        and bool(str(after["task"].get("NextRunTime") or "").strip()),
        {
            "state": after["task"].get("State"),
            "next": after["task"].get("NextRunTime"),
            "last": after["task"].get("LastRunTime"),
        },
    )

    payload = {
        "window_id": WINDOW_ID,
        "task": TASK,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "before": before,
        "after": after,
        "checks": evidence.checks,
        "ok": evidence.ok,
    }
    (WINDOW / "AUTOSTART_EVIDENCE.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "passed": sum(1 for item in evidence.checks if item["ok"]),
                "failed": sum(1 for item in evidence.checks if not item["ok"]),
                "evidence": str(WINDOW / "AUTOSTART_EVIDENCE.json"),
            },
            indent=2,
        )
    )
    return 0 if evidence.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
