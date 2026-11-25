"""Blindaje del arnés forward: hashes, cadena, cierre y panel read-only."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.experiments import config_sha256
from server.forward import identity, paths
from server.forward.capture import (
    CaptureError,
    init_capture,
    load_manifest_strict,
)
from server.forward.identity import (
    GENESIS,
    SNAPSHOT_SCHEMA,
    config_file_path,
)
from server.forward.ledger import Ledger, LedgerError, read_records, verify_chain
from server.forward.loader import ForwardIntegrityError, load_strict
from server.forward.panel import build_app, summarize_window
from server.forward.session import SessionError, close_session
from server.config import Settings
from server.timeutil import timestamp_for

WINDOW = "TEST-FORWARD-HARNESS"
ARM = "control"
FIXED_CODE = {
    "sha256": "a" * 64,
    "algorithm": "sha256-tree-v1",
    "roots": ["server", "tests"],
    "files": 1,
}


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    return _sha_bytes(path.read_bytes())


def _tree_state(root: Path) -> list[tuple[str, str, str, int]]:
    state: list[tuple[str, str, str, int]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            state.append((relative, "dir", "", path.stat().st_mtime_ns))
        else:
            state.append(
                (
                    relative,
                    "file",
                    _sha_file(path),
                    path.stat().st_mtime_ns,
                )
            )
    return state


def _config_payload() -> dict:
    return {
        "mode": "paper",
        "live": {"live_enabled": False},
        "feed": {
            "provider": "csv",
            "csv_path": "data/forward/test/bars_forward.csv",
            "series_mode": "raw",
            "loop_sessions": False,
            "replay_speed": 1.0,
        },
        "risk": {"max_contracts": 5, "max_sl_ticks": 200, "min_stop_or_ratio": 0.0},
    }


def _make_db(path: Path, *, with_trade: bool = True) -> None:
    conn = sqlite3.connect(path)
    try:
        conn.execute(
            "CREATE TABLE trades ("
            "id TEXT, mode TEXT, signal_id TEXT, direction TEXT, qty INTEGER, "
            "entry_ts INTEGER, exit_ts INTEGER, pnl REAL, r_multiple REAL, "
            "exit_reason TEXT)"
        )
        if with_trade:
            ts = timestamp_for(date(2026, 12, 1), "10:00")
            conn.execute(
                "INSERT INTO trades VALUES (?,?,?,?,?,?,?,?,?,?)",
                ("t-1", "paper", "s-1", "long", 1, ts, ts, 10.0, 1.0, "tp"),
            )
        conn.commit()
    finally:
        conn.close()


def _make_window(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(paths, "FORWARD_ROOT", tmp_path)
    monkeypatch.setattr(identity, "code_identity", lambda: dict(FIXED_CODE))

    profile = tmp_path / WINDOW / "arms" / ARM / "profile"
    profile.mkdir(parents=True)
    payload = _config_payload()
    raw = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    config_path = profile / "config.json"
    config_path.write_bytes(raw)
    settings = Settings.model_validate(payload)
    snapshot = {
        "schema": SNAPSHOT_SCHEMA,
        "window_id": WINDOW,
        "arm": ARM,
        "kind": "harness",
        "config_path": "config.json",
        "config_file_sha256": _sha_bytes(raw),
        "config_sha256": config_sha256(settings),
        "code_sha256": FIXED_CODE["sha256"],
        "code_files": FIXED_CODE["files"],
        "initial_capital": 25000.0,
    }
    (profile / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    arm_path = tmp_path / WINDOW / "arms" / ARM
    (arm_path / "sessions").mkdir()
    (arm_path / "logs").mkdir()
    (arm_path / "signals.jsonl").write_text("", encoding="utf-8")
    _make_db(profile / "yedbot.db")
    (tmp_path / WINDOW / "window.json").write_text(
        json.dumps(
            {
                "schema": "forward-window-v1",
                "window_id": WINDOW,
                "kind": "harness",
                "start_date": "2026-12-01",
                "arms": {
                    ARM: {
                        "port": 8775,
                        "profile_dir": f"arms/{ARM}/profile",
                        "config_file_sha256": snapshot["config_file_sha256"],
                        "code_sha256": snapshot["code_sha256"],
                    }
                },
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return profile


def _snapshot(profile: Path) -> dict:
    return json.loads((profile / "snapshot.json").read_text(encoding="utf-8"))


def _write_snapshot(profile: Path, snapshot: dict) -> None:
    (profile / "snapshot.json").write_text(
        json.dumps(snapshot, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def test_strict_loader_accepts_only_matching_config_and_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _make_window(tmp_path, monkeypatch)
    settings = load_strict(profile, _snapshot(profile))
    assert settings.mode == "paper"
    assert settings.risk.max_contracts == 5


def test_strict_loader_rejects_config_file_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _make_window(tmp_path, monkeypatch)
    snapshot = _snapshot(profile)
    config = profile / "config.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["risk"]["max_contracts"] = 7
    config.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    with pytest.raises(ForwardIntegrityError, match="config_file_sha256"):
        load_strict(profile, snapshot)
    assert not list(profile.glob("*.broken"))


def test_strict_loader_rejects_canonical_config_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _make_window(tmp_path, monkeypatch)
    snapshot = _snapshot(profile)
    snapshot["config_sha256"] = "0" * 64
    _write_snapshot(profile, snapshot)

    with pytest.raises(ForwardIntegrityError, match="config_sha256"):
        load_strict(profile, snapshot)


def test_strict_loader_rejects_code_hash(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _make_window(tmp_path, monkeypatch)
    monkeypatch.setattr(
        identity,
        "code_identity",
        lambda: {**FIXED_CODE, "sha256": "b" * 64},
    )
    with pytest.raises(ForwardIntegrityError, match="code_sha256"):
        load_strict(profile, _snapshot(profile))


def test_strict_loader_rejects_config_path_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _make_window(tmp_path, monkeypatch)
    snapshot = _snapshot(profile)
    snapshot["config_path"] = "../outside.json"
    _write_snapshot(profile, snapshot)

    with pytest.raises(ValueError, match="fuera del perfil"):
        config_file_path(profile, snapshot)
    with pytest.raises(ForwardIntegrityError, match="fuera del perfil"):
        load_strict(profile, snapshot)


def test_startup_write_failure_does_not_touch_global_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from server.forward import arm

    profile = _make_window(tmp_path, monkeypatch)
    config = profile / "config.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["risk"]["max_contracts"] = 9
    config.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    before = config.read_bytes()

    env_before = {
        key: os.environ.get(key)
        for key in ("YED_PROFILE_DIR", "YED_CONFIG_PATH", "YED_DB_PATH", "YED_OPEN")
    }
    try:
        rc = arm.main(["--window-id", WINDOW, "--arm", ARM, "--port", "8775"])
    finally:
        for key, value in env_before.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    assert rc == 3
    assert "FORWARD_INTEGRITY_FAIL" in capsys.readouterr().err
    assert config.read_bytes() == before
    records = read_records(tmp_path / WINDOW / "arms" / ARM / "ledger.jsonl")
    assert any(item["event"] == "INTEGRITY_FAIL" for item in records)
    assert verify_chain(records) == []


def test_ledger_is_chained_and_tamper_is_detected(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path, WINDOW, ARM)
    first = ledger.append("A", {"n": 1})
    second = ledger.append("B", {"n": 2})
    assert first["prev_sha256"] == GENESIS
    assert second["prev_sha256"] == first["sha256"]
    assert verify_chain(read_records(path)) == []

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered = json.loads(lines[0])
    tampered["detail"]["n"] = 99
    lines[0] = json.dumps(tampered, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerError, match="ledger corrupto"):
        Ledger(path, WINDOW, ARM)


def test_ledger_refuses_incomplete_tail_instead_of_concatenating(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = Ledger(path, WINDOW, ARM)
    ledger.append("A", {"n": 1})
    with path.open("ab") as handle:
        handle.write(b'{"partial":')

    with pytest.raises(LedgerError, match="cola incompleta"):
        ledger.append("B", {"n": 2})
    assert path.read_bytes().endswith(b'{"partial":')
    assert [item["event"] for item in read_records(path)] == ["A"]


def test_close_session_verifies_and_chains_sessions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    first = close_session(
        window_id=WINDOW, arm=ARM, session_date="2026-12-01", note="primera"
    )
    assert first["ok"] is True
    assert first["valid"] is True
    assert first["record"]["trades"]["count"] == 1
    assert first["record"]["cumulative"]["equity"] == 25010.0
    assert first["record"]["artifacts"]["trades_sha256"]

    second = close_session(
        window_id=WINDOW, arm=ARM, session_date="2026-12-02", note="segunda"
    )
    assert second["valid"] is True
    assert second["record"]["prev_session_sha256"] == first["record"]["session_sha256"]


def test_close_session_with_tampered_config_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _make_window(tmp_path, monkeypatch)
    config = profile / "config.json"
    payload = json.loads(config.read_text(encoding="utf-8"))
    payload["risk"]["max_contracts"] = 8
    config.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    result = close_session(window_id=WINDOW, arm=ARM, session_date="2026-12-02")
    assert result["valid"] is False
    assert any("config_file_sha256" in problem for problem in result["problems"])
    records = read_records(tmp_path / WINDOW / "arms" / ARM / "ledger.jsonl")
    assert any(item["event"] == "INTEGRITY_FAIL" for item in records)


def test_close_session_with_code_drift_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    monkeypatch.setattr(
        identity,
        "code_identity",
        lambda: {**FIXED_CODE, "sha256": "c" * 64},
    )

    result = close_session(window_id=WINDOW, arm=ARM, session_date="2026-12-02")
    assert result["valid"] is False
    assert any("code_sha256" in problem for problem in result["problems"])


def test_close_session_with_unreadable_db_is_invalid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _make_window(tmp_path, monkeypatch)
    (profile / "yedbot.db").unlink()

    result = close_session(window_id=WINDOW, arm=ARM, session_date="2026-12-02")
    assert result["valid"] is False
    assert result["problems"] == [f"DB del brazo ausente: {profile / 'yedbot.db'}"]


def test_close_session_rejects_holdout_date(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    with pytest.raises(SessionError, match="holdout sellado"):
        close_session(window_id=WINDOW, arm=ARM, session_date="2026-07-01")
    assert not (tmp_path / WINDOW / "arms" / ARM / "sessions" / "2026-07-01.json").exists()


def test_capture_loader_fails_on_tampered_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    manifest = init_capture(window_id=WINDOW, root=tmp_path)
    assert load_manifest_strict(window_id=WINDOW, root=tmp_path)["status"] == "skeleton_awaiting_capture"

    trades = tmp_path / WINDOW / "capture" / "arms" / ARM / "trades.jsonl"
    trades.write_text('{"tampered":true}\n', encoding="utf-8")
    with pytest.raises(CaptureError, match="captura no verificada"):
        load_manifest_strict(window_id=WINDOW, root=tmp_path)


def test_panel_is_read_only_and_reads_custom_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    init_capture(window_id=WINDOW, root=tmp_path)
    app = build_app(tmp_path)
    before = _tree_state(tmp_path)

    with TestClient(app) as client:
        summary = client.get("/api/forward/summary")
        assert summary.status_code == 200
        body = summary.json()
        assert body["read_only"] is True
        item = body["windows"][0]
        assert item["window_id"] == WINDOW
        assert item["capture"]["present"] is True
        assert item["capture"]["ok"] is True
        assert item["arms"][ARM]["chain_ok"] is True
        assert item["arms"][ARM]["hash_ok"] is True

        one = client.get(f"/api/forward/windows/{WINDOW}")
        assert one.status_code == 200
        assert one.json()["window_id"] == WINDOW

        page = client.get("/")
        assert page.status_code == 200
        assert "Forward · panel de solo lectura" in page.text
        assert WINDOW in page.text

        for path in ("/", "/api/forward/summary", f"/api/forward/windows/{WINDOW}"):
            head = client.head(path)
            assert head.status_code == 200, (path, head.status_code)
            assert head.text == ""
        assert client.head("/api/forward/windows/does-not-exist").status_code == 404

        for method in ("post", "put", "patch", "delete", "options"):
            blocked = getattr(client, method)("/api/forward/summary")
            assert blocked.status_code == 405, (method, blocked.status_code)
            assert blocked.json()["detail"].startswith("panel de solo lectura")

    assert _tree_state(tmp_path) == before


def test_panel_marks_broken_capture_and_does_not_open_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    init_capture(window_id=WINDOW, root=tmp_path)
    trades = tmp_path / WINDOW / "capture" / "arms" / ARM / "trades.jsonl"
    trades.write_text('{"tampered":true}\n', encoding="utf-8")

    def _no_sqlite(*_args, **_kwargs):
        raise AssertionError("el panel no debe abrir SQLite")

    monkeypatch.setattr(sqlite3, "connect", _no_sqlite)
    summary = summarize_window(tmp_path / WINDOW)
    assert summary["capture"]["ok"] is False
    assert summary["status"] == "NO_VALIDA"
    assert summary["arms"][ARM]["chain_ok"] is True


def test_panel_marks_incomplete_ledger_tail(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    ledger_path = tmp_path / WINDOW / "arms" / ARM / "ledger.jsonl"
    Ledger(ledger_path, WINDOW, ARM).append("ARM_STARTED", {"test": True})
    with ledger_path.open("ab") as handle:
        handle.write(b'{"partial":')

    summary = summarize_window(tmp_path / WINDOW)
    assert summary["arms"][ARM]["chain_ok"] is False
    assert any("cola incompleta" in item for item in summary["arms"][ARM]["chain_problems"])
    assert summary["status"] == "NO_VALIDA"


def test_panel_marks_window_id_mismatch_without_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    window_path = tmp_path / WINDOW / "window.json"
    payload = json.loads(window_path.read_text(encoding="utf-8"))
    payload["window_id"] = "OTRA-VENTANA"
    window_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    summary = summarize_window(tmp_path / WINDOW)
    assert summary["window_id"] == WINDOW
    assert summary["window"]["window_id"] == WINDOW
    assert summary["status"] == "NO_VALIDA"
    assert any("no coincide" in problem for problem in summary["window_problems"])
    assert ARM in summary["arms"]


def test_panel_marks_invalid_arm_without_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    window_path = tmp_path / WINDOW / "window.json"
    payload = json.loads(window_path.read_text(encoding="utf-8"))
    payload["arms"]["intruso"] = payload["arms"][ARM]
    window_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    summary = summarize_window(tmp_path / WINDOW)
    assert summary["status"] == "NO_VALIDA"
    assert ARM in summary["arms"]
    assert "intruso" not in summary["arms"]
    assert any("brazo inválido" in problem for problem in summary["window_problems"])


def test_panel_marks_invalid_window_json_without_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    window_path = tmp_path / WINDOW / "window.json"
    window_path.write_text("{invalido", encoding="utf-8")

    summary = summarize_window(tmp_path / WINDOW)
    assert summary["window_id"] == WINDOW
    assert summary["status"] == "NO_VALIDA"
    assert summary["error"] == "window.json inválido"
    assert summary["window_problems"] == ["window.json inválido"]
    assert summary["arms"] == {}


def test_panel_marks_invalid_session_chain_without_500(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    sessions = tmp_path / WINDOW / "arms" / ARM / "sessions"
    sessions.mkdir(exist_ok=True)
    (sessions / "2026-12-01.json").write_text("{invalido", encoding="utf-8")

    summary = summarize_window(tmp_path / WINDOW)
    assert summary["status"] == "NO_VALIDA"
    arm = summary["arms"][ARM]
    assert arm["session_chain_ok"] is False
    assert any("JSON inválido" in problem for problem in arm["session_chain_problems"])


def test_panel_marks_session_without_session_field(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    sessions = tmp_path / WINDOW / "arms" / ARM / "sessions"
    sessions.mkdir(exist_ok=True)
    (sessions / "2026-12-01.json").write_text(
        json.dumps({"valid": True}), encoding="utf-8"
    )

    summary = summarize_window(tmp_path / WINDOW)
    assert summary["status"] == "NO_VALIDA"
    arm = summary["arms"][ARM]
    assert arm["session_chain_ok"] is False
    assert any("sesión ausente" in problem for problem in arm["session_chain_problems"])


def test_panel_reads_snapshot_once_per_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _make_window(tmp_path, monkeypatch)
    from server.forward import panel

    calls: list[Path] = []
    original = panel._safe_json

    def _counting(path: Path):
        calls.append(Path(path))
        return original(path)

    monkeypatch.setattr(panel, "_safe_json", _counting)
    panel.summarize_window(tmp_path / WINDOW)
    assert sum(path.name == "snapshot.json" for path in calls) == 1
