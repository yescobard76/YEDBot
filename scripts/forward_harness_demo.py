"""Prueba end-to-end del arnés forward: aislamiento, integridad y solo lectura.

Levanta dos brazos (8775/8776), fuerza una caída para ver la recuperación,
intenta rutas mutantes, edita el config a mano y rompe el JSON. Todo queda
registrado en los artefactos de la ventana. No arranca, detiene ni escribe en
el 8765/8766.
"""

from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT = Path(__file__).resolve().parents[1]
FORWARD_ROOT = PROJECT / "data" / "forward"
PYTHON = sys.executable
CLEAN_ENV = {key: value for key, value in os.environ.items() if not key.startswith("YED_")}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def file_state(path: Path, *, hash_file: bool = True) -> dict[str, Any]:
    if not path.exists():
        return {"exists": False}
    stat = path.stat()
    return {
        "exists": True,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": (
            sha256(path) if hash_file and stat.st_size < 20_000_000 else None
        ),
    }


def listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.4)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def call(method: str, url: str, payload: Any = None, timeout: float = 8.0):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            try:
                parsed = json.loads(body)
            except json.JSONDecodeError:
                parsed = body
            return response.status, parsed
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed = body
        return exc.code, parsed


def wait_http(url: str, timeout: float = 45.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            status, _ = call("GET", url, timeout=2.0)
            if status == 200:
                return True
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.4)
    return False


def wait_port_gone(port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not listening(port):
            return True
        time.sleep(0.3)
    return not listening(port)


def wait_heartbeat(path: Path, timeout: float = 30.0) -> dict | None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if value.get("status") == "running" and int(value.get("pid") or 0):
                return value
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)
    return None


def stop_arm(port: int, window_id: str) -> bool:
    try:
        status, body = call(
            "GET", f"http://127.0.0.1:{port}/api/forward/state", timeout=3
        )
        if status == 200 and body.get("window_id") == window_id:
            call("POST", f"http://127.0.0.1:{port}/api/forward/stop", timeout=5)
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def read_jsonl(path: Path) -> list[dict]:
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

    def check(self, name: str, ok: bool, detail: Any = "") -> bool:
        self.checks.append({"name": name, "ok": bool(ok), "detail": detail})
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        return bool(ok)

    @property
    def ok(self) -> bool:
        return all(item["ok"] for item in self.checks)


def main() -> int:
    busy = [port for port in (8775, 8776, 8778) if listening(port)]
    if busy:
        print(
            "ABORTADO: hay procesos escuchando en "
            f"{busy}; la prueba debe partir de puertos libres.",
            file=sys.stderr,
        )
        return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    window_id = f"HARNESS-{stamp}-{os.getpid()}"
    root = FORWARD_ROOT / window_id
    evidence = Evidence()

    before = {
        "8765_listening": listening(8765),
        "8766_health": call("GET", "http://127.0.0.1:8766/api/health", timeout=4),
        "files": {
            "data/config.json": file_state(PROJECT / "data/config.json"),
            "profiles/p2_freq/config.json": file_state(PROJECT / "profiles/p2_freq/config.json"),
            "profiles/backtest_real/config.json": file_state(
                PROJECT / "profiles/backtest_real/config.json"
            ),
            "docs/protocolo_backtest.lock.json": file_state(
                PROJECT / "docs/protocolo_backtest.lock.json"
            ),
            "data/yedbot.db": file_state(
                PROJECT / "data/yedbot.db", hash_file=False
            ),
            "reports/backtest/preset_card_8766.db": file_state(
                PROJECT / "reports/backtest/preset_card_8766.db", hash_file=False
            ),
        },
    }

    init = subprocess.run(
        [
            PYTHON,
            "-m",
            "server.forward.init_window",
            "--window-id",
            window_id,
            "--kind",
            "harness",
            "--note",
            "Prueba hostil de arnés; sin feed, cero trades. No es desempeño.",
        ],
        cwd=PROJECT,
        env=CLEAN_ENV,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if init.returncode != 0:
        print(init.stdout)
        print(init.stderr, file=sys.stderr)
        return 2
    evidence.check("ventana T0 creada", True, window_id)
    (root / "logs").mkdir(parents=True, exist_ok=True)

    window = json.loads((root / "window.json").read_text(encoding="utf-8"))
    control = "arms/control"
    treatment = "arms/treatment"
    t0 = {
        arm: json.loads(
            (root / "arms" / arm / "profile" / "snapshot.json").read_text(encoding="utf-8")
        )["config_file_sha256"]
        for arm in ("control", "treatment")
    }

    def spawn_supervisor(arm: str, port: int) -> tuple[subprocess.Popen, Any]:
        log = (root / "logs" / f"supervisor-{arm}.out").open("ab")
        process = subprocess.Popen(
            [
                PYTHON,
                "-m",
                "server.forward.supervisor",
                "--window-id",
                window_id,
                "--arm",
                arm,
                "--port",
                str(port),
                "--max-restarts",
                "4",
                "--restart-delay",
                "1.5",
            ],
            cwd=PROJECT,
            env=CLEAN_ENV,
            stdout=log,
            stderr=subprocess.STDOUT,
        )
        return process, log

    control_sup, control_log = spawn_supervisor("control", 8775)
    treatment_sup, treatment_log = spawn_supervisor("treatment", 8776)
    panel_proc = None
    panel_log = None
    try:
        ok_control = wait_http("http://127.0.0.1:8775/api/health")
        ok_treatment = wait_http("http://127.0.0.1:8776/api/health")
        evidence.check("brazo control arranca en 8775", ok_control, "health 200")
        evidence.check("brazo treatment arranca en 8776", ok_treatment, "health 200")

        state_control = call("GET", "http://127.0.0.1:8775/api/forward/state")[1]
        state_treatment = call("GET", "http://127.0.0.1:8776/api/forward/state")[1]
        evidence.check(
            "los brazos responden con la ventana de esta prueba",
            state_control.get("window_id") == window_id
            and state_treatment.get("window_id") == window_id
            and state_control.get("arm") == "control"
            and state_treatment.get("arm") == "treatment",
            {
                "control": state_control.get("window_id"),
                "treatment": state_treatment.get("window_id"),
            },
        )
        evidence.check(
            "perfil y DB aislados (control)",
            "data\\forward" in state_control["db_path"]
            or "data/forward" in state_control["db_path"],
            state_control["db_path"],
        )
        evidence.check(
            "perfil y DB aislados (treatment)",
            "data\\forward" in state_treatment["db_path"]
            or "data/forward" in state_treatment["db_path"],
            state_treatment["db_path"],
        )
        evidence.check(
            "el 8765 no se arranca ni se toca",
            not listening(8765) and not before["8765_listening"],
            "8765 sin listener antes y después",
        )

        heartbeat = wait_heartbeat(root / control / "heartbeat.json")
        if heartbeat is None:
            raise RuntimeError("el supervisor no publicó heartbeat con PID")
        old_pid = int(heartbeat["pid"])
        os.kill(old_pid, signal.SIGTERM)
        deadline = time.time() + 40
        restarted = False
        while time.time() < deadline:
            try:
                current = json.loads(
                    (root / control / "heartbeat.json").read_text(encoding="utf-8")
                )
                if (
                    int(current.get("pid") or 0) not in (0, old_pid)
                    and current.get("status") == "running"
                    and call("GET", "http://127.0.0.1:8775/api/health", timeout=1)[0] == 200
                ):
                    restarted = True
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.5)
        supervisor_events = read_jsonl(root / control / "supervisor.jsonl")
        restart_events = [item for item in supervisor_events if item["event"] == "ARM_RESTART"]
        evidence.check(
            "recuperación tras caída registrada",
            restarted and bool(restart_events),
            f"pid {old_pid} terminado; ARM_RESTART={len(restart_events)}",
        )

        mutations = [
            ("PUT", "/api/config", {"patch": {"risk": {"max_contracts": 7}}}),
            ("POST", "/api/bot/start", None),
            ("POST", "/api/position/close", None),
            ("POST", "/api/orders/cancel", None),
            ("POST", "/api/emergency", {"reason": "prueba", "close_positions": False}),
            ("DELETE", "/api/emergency", None),
            ("POST", "/api/stats/reset", None),
        ]
        blocked = []
        for method, path, payload in mutations:
            status, body = call(method, f"http://127.0.0.1:8775{path}", payload)
            blocked.append({"method": method, "path": path, "status": status})
            if status != 403:
                print(f"  inesperado {method} {path} -> {status} {body}")
        evidence.check(
            "rutas mutantes bloqueadas (403)",
            all(item["status"] == 403 for item in blocked),
            blocked,
        )

        state_after = call("GET", "http://127.0.0.1:8775/api/forward/state")[1]
        evidence.check(
            "violación marca NO_VÁLIDA en el ledger",
            state_after["status"] == "NO_VALIDA"
            and state_after["chain_ok"] is True,
            f"status={state_after['status']} chain_ok={state_after['chain_ok']}",
        )

        close_control = subprocess.run(
            [PYTHON, "-m", "server.forward.session", "--window-id", window_id,
             "--arm", "control", "--date", "2026-11-24"],
            cwd=PROJECT, env=CLEAN_ENV, capture_output=True, text=True, timeout=120,
        )
        close_treatment = subprocess.run(
            [PYTHON, "-m", "server.forward.session", "--window-id", window_id,
             "--arm", "treatment", "--date", "2026-11-24"],
            cwd=PROJECT, env=CLEAN_ENV, capture_output=True, text=True, timeout=120,
        )
        control_session = json.loads(close_control.stdout)
        treatment_session = json.loads(close_treatment.stdout)
        evidence.check(
            "sesión sellada con export e hashes",
            control_session["valid"] is True
            and control_session["record"]["artifacts"]["equity_sha256"],
            control_session["session_file"],
        )
        evidence.check(
            "segundo brazo sellado de forma independiente",
            treatment_session["valid"] is True,
            treatment_session["session_file"],
        )

        panel_log = (root / "panel.out").open("ab")
        panel_proc = subprocess.Popen(
            [PYTHON, "-m", "server.forward.panel", "--port", "8778"],
            cwd=PROJECT, env=CLEAN_ENV, stdout=panel_log, stderr=subprocess.STDOUT,
        )
        panel_ok = wait_http("http://127.0.0.1:8778/", timeout=30)
        panel_status, panel_summary = call(
            "GET", f"http://127.0.0.1:8778/api/forward/windows/{window_id}"
        )
        control_panel = panel_summary["arms"]["control"]
        treatment_panel = panel_summary["arms"]["treatment"]
        evidence.check(
            "panel lee artefactos y muestra sesiones/equity/DD/hashes",
            panel_ok
            and control_panel["sessions_valid"] == 1
            and control_panel["trades_total"] == 0
            and control_panel["equity"] == 25000.0
            and control_panel["max_drawdown"] == 0.0
            and control_panel["chain_ok"]
            and control_panel["hash_ok"],
            {
                "sessions": control_panel["sessions_valid"],
                "trades": control_panel["trades_total"],
                "equity": control_panel["equity"],
                "dd": control_panel["max_drawdown"],
                "chain_ok": control_panel["chain_ok"],
                "hash_ok": control_panel["hash_ok"],
            },
        )
        post_panel = call("POST", "http://127.0.0.1:8778/api/forward/summary")
        evidence.check(
            "panel sin escritura (POST=405)",
            post_panel[0] == 405,
            post_panel,
        )
        (root / "panel_summary.json").write_text(
            json.dumps(panel_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        html_status, html_body = call("GET", "http://127.0.0.1:8778/")
        if isinstance(html_body, str):
            (root / "panel.html").write_text(html_body, encoding="utf-8")
        evidence.check("panel HTML servido en solo lectura", html_status == 200, html_status)

        config_path = root / control / "profile" / "config.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config["risk"]["max_contracts"] = 7
        config_path.write_text(
            json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        edited_hash = sha256(config_path)
        evidence.check(
            "edición manual del config detectada como hash distinto",
            edited_hash != t0["control"],
            {"t0": t0["control"], "editado": edited_hash},
        )

        hostile_close = subprocess.run(
            [PYTHON, "-m", "server.forward.session", "--window-id", window_id,
             "--arm", "control", "--date", "2026-11-25"],
            cwd=PROJECT, env=CLEAN_ENV, capture_output=True, text=True, timeout=120,
        )
        hostile = json.loads(hostile_close.stdout)
        evidence.check(
            "cierre de sesión con config editado queda NO VÁLIDO",
            hostile["valid"] is False
            and any("config_file_sha256" in item for item in hostile["problems"]),
            hostile["problems"],
        )

        call("POST", "http://127.0.0.1:8775/api/forward/stop")
        control_sup.wait(timeout=25)
        if control_sup.poll() is None:
            control_sup.terminate()
            control_sup.wait(timeout=15)
        wait_port_gone(8775)
        control_log.close()

        strict = subprocess.run(
            [PYTHON, "-m", "server.forward.arm", "--window-id", window_id,
             "--arm", "control", "--port", "8775"],
            cwd=PROJECT, env=CLEAN_ENV, capture_output=True, text=True, timeout=120,
        )
        broken_files = sorted(
            path.name for path in (root / control / "profile").glob("*.broken")
        )
        evidence.check(
            "loader estricto rechaza hash desalineado (exit 3)",
            strict.returncode == 3
            and "FORWARD_INTEGRITY_FAIL" in strict.stderr
            and not broken_files,
            {"rc": strict.returncode, "broken": broken_files},
        )

        config_path.write_text("{", encoding="utf-8")
        corrupt_hash = sha256(config_path)
        corrupt = subprocess.run(
            [PYTHON, "-m", "server.forward.arm", "--window-id", window_id,
             "--arm", "control", "--port", "8775"],
            cwd=PROJECT, env=CLEAN_ENV, capture_output=True, text=True, timeout=120,
        )
        evidence.check(
            "loader estricto rechaza JSON corrupto sin usar defaults",
            corrupt.returncode == 3
            and "JSON inválido" in corrupt.stderr
            and sha256(config_path) == corrupt_hash
            and not sorted((root / control / "profile").glob("*.broken")),
            {"rc": corrupt.returncode, "stderr": corrupt.stderr.strip().splitlines()[:2]},
        )

        stop_treatment = call("POST", "http://127.0.0.1:8776/api/forward/stop")
        wait_port_gone(8776)
        treatment_sup.wait(timeout=20)
        treatment_log.close()
        treatment_ledger = read_jsonl(root / treatment / "ledger.jsonl")
        evidence.check(
            "único control legítimo: parar deja la ventana etiquetada",
            stop_treatment[0] == 200
            and any(item["event"] == "STOPPED" for item in treatment_ledger),
            {"stop": stop_treatment, "last": treatment_ledger[-1]["event"]},
        )

        panel_status, panel_summary = call(
            "GET", f"http://127.0.0.1:8778/api/forward/windows/{window_id}"
        )
        control_panel = panel_summary["arms"]["control"]
        treatment_panel = panel_summary["arms"]["treatment"]
        evidence.check(
            "panel final: control NO_VÁLIDA y treatment DETENIDA",
            panel_summary["status"] == "NO_VALIDA"
            and control_panel["status"] == "NO_VALIDA"
            and treatment_panel["status"] == "DETENIDA"
            and len(control_panel["integrity_failures"]) >= 1
            and control_panel["chain_ok"],
            {
                "window": panel_summary["status"],
                "control": control_panel["status"],
                "treatment": treatment_panel["status"],
                "integrity_failures": len(control_panel["integrity_failures"]),
                "sessions": control_panel["sessions_sealed"],
            },
        )
        (root / "panel_summary_final.json").write_text(
            json.dumps(panel_summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        html_status, html_body = call("GET", "http://127.0.0.1:8778/")
        if isinstance(html_body, str):
            (root / "panel.html").write_text(html_body, encoding="utf-8")

    finally:
        stop_arm(8775, window_id)
        stop_arm(8776, window_id)
        time.sleep(1.0)
        for process in (control_sup, treatment_sup):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
        for handle in (control_log, treatment_log):
            try:
                handle.close()
            except Exception:  # noqa: BLE001
                pass
        if panel_proc is not None and panel_proc.poll() is None:
            panel_proc.terminate()
            try:
                panel_proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                panel_proc.kill()
        if panel_log is not None:
            panel_log.close()

    after = {
        "8765_listening": listening(8765),
        "8766_health": call("GET", "http://127.0.0.1:8766/api/health", timeout=4),
        "files": {
            "data/config.json": file_state(PROJECT / "data/config.json"),
            "profiles/p2_freq/config.json": file_state(PROJECT / "profiles/p2_freq/config.json"),
            "profiles/backtest_real/config.json": file_state(
                PROJECT / "profiles/backtest_real/config.json"
            ),
            "docs/protocolo_backtest.lock.json": file_state(
                PROJECT / "docs/protocolo_backtest.lock.json"
            ),
            "data/yedbot.db": file_state(
                PROJECT / "data/yedbot.db", hash_file=False
            ),
            "reports/backtest/preset_card_8766.db": file_state(
                PROJECT / "reports/backtest/preset_card_8766.db", hash_file=False
            ),
        },
    }
    same_files = all(before["files"][name] == after["files"][name] for name in before["files"])
    same_8766 = (
        before["8766_health"][0] == after["8766_health"][0]
        and before["8766_health"][1].get("status") == "ok"
        and after["8766_health"][1].get("status") == "ok"
    )
    evidence.check(
        "8765/8766 configs, DB y lock intactos",
        same_files and same_8766 and before["8765_listening"] == after["8765_listening"],
        {"files_unchanged": same_files, "8766_ok": same_8766},
    )

    payload = {
        "window_id": window_id,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "read_only_panel": True,
        "external_anchor": "excluded_by_scope",
        "before": before,
        "after": after,
        "t0": t0,
        "checks": evidence.checks,
        "ok": evidence.ok,
    }
    (root / "HARNESS_EVIDENCE.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    summary = {
        "window_id": window_id,
        "passed": sum(1 for item in evidence.checks if item["ok"]),
        "failed": sum(1 for item in evidence.checks if not item["ok"]),
        "evidence": str(root / "HARNESS_EVIDENCE.json"),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if evidence.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
