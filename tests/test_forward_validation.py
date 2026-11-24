"""Contrato del informe forward y de su endpoint de solo lectura."""

from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import router
from server.config import Settings
from server.validation import REPORT_PATH, load_forward_validation

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    # Este endpoint no usa el motor, pero el router incluye otros que sí.
    app.state.engine = None
    return TestClient(app)


def test_report_exists_and_has_required_sections() -> None:
    report = load_forward_validation()
    assert report["schema"] == "forward-validation-v1"
    assert report["decision"]["kind"] == "keep_current"
    assert report["decision"]["live_config_updated"] is False
    assert report["decision"]["current_profile"] == "data/config.json"
    assert report["status"] == "insufficient_data"
    assert [item["id"] for item in report["candidates"]] == [
        "baseline_manual",
        "p2",
        "p2_be_1r",
    ]


def test_development_and_forward_are_explicitly_separated() -> None:
    report = load_forward_validation()
    assert report["development"]["status"] == "in_sample"
    assert report["development"]["role"] == "context_only_not_validation"
    forward = report["forward"]
    assert forward["status"] == "insufficient_data"
    assert forward["available_sessions"] == 0
    assert forward["evaluated"] is False
    assert forward["attempts"] == 0
    assert forward["candidate_forward_protocol"] is None
    assert forward["dataset_last_session"] < "2026-07-01"
    for candidate in report["candidates"]:
        assert candidate["forward_metrics"] is None
        assert candidate["forward_status"] in {"reference", "insufficient_data"}


def test_holdout_is_sealed_and_not_used() -> None:
    report = load_forward_validation()
    holdout = report["holdout"]
    assert holdout["id"] == "H1"
    assert holdout["start"] == "2026-07-01"
    assert holdout["end"] == "2026-10-30"
    assert holdout["status"] == "sealed_not_executed"
    assert holdout["executed"] is False
    assert holdout["used_for_decision"] is False
    assert holdout["lock_sha256"] == _sha(ROOT / "docs" / "protocolo_backtest.lock.json")


def test_development_metrics_are_the_expected_in_sample_values() -> None:
    report = load_forward_validation()
    metrics = {item["id"]: item["dev_metrics"] for item in report["candidates"]}
    assert metrics["baseline_manual"] == {
        "ops": 72,
        "net_usd": 2022.94,
        "profit_factor": 1.22,
        "expectancy_usd": 28.10,
        "max_drawdown_usd": 2891.66,
        "max_drawdown_pct": 9.79,
        "expectancy_r": 0.18,
        "total_r": 13.19,
    }
    assert metrics["p2"]["ops"] == 46
    assert metrics["p2"]["net_usd"] == 2471.78
    assert metrics["p2"]["profit_factor"] == 1.39
    assert metrics["p2_be_1r"]["net_usd"] == 2036.52
    assert metrics["p2_be_1r"]["profit_factor"] == 1.48
    assert metrics["p2_be_1r"]["max_drawdown_usd"] == 1794.46


def test_sources_and_profiles_match_the_report_hashes() -> None:
    report = load_forward_validation()
    integrity = report["integrity"]
    assert integrity["protocol_v1_2_lock"] == _sha(ROOT / "docs" / "protocolo_backtest.lock.json")
    assert integrity["profiles_p2_freq"] == _sha(ROOT / "profiles" / "p2_freq" / "config.json")
    assert integrity["profiles_backtest_real"] == _sha(ROOT / "profiles" / "backtest_real" / "config.json")
    assert integrity["dataset_development"] == _sha(ROOT / "data" / "real" / "bars_mnq_nq_es_1m.csv")
    assert integrity["config_changed"] is False
    assert integrity["holdout_bars_read"] is False
    assert integrity["forward_csv_exists"] is False


def test_report_hash_sidecar_is_portable_and_matches() -> None:
    line = (REPORT_PATH.parent / "forward_validation.sha256").read_bytes().decode("utf-8")
    assert "\r" not in line
    digest, name = line.strip().split("  ")
    assert name == REPORT_PATH.name
    assert digest == _sha(REPORT_PATH)


def test_forward_endpoint_returns_the_report() -> None:
    assert REPORT_PATH.exists()
    with _client() as client:
        response = client.get("/api/validation/forward")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["decision"]["kind"] == "keep_current"
    assert body["forward"]["available_sessions"] == 0
    assert body["holdout"]["executed"] is False


def test_forward_endpoint_reports_invalid_artifact(monkeypatch) -> None:
    import server.validation as validation

    monkeypatch.setattr(validation, "REPORT_PATH", ROOT / "reports" / "backtest" / "missing.json")
    with _client() as client:
        response = client.get("/api/validation/forward")
    assert response.status_code == 503
