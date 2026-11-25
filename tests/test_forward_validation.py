"""Contrato del informe forward y de su endpoint de solo lectura."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import router
from server.config import Settings
from server.validation import REPORT_PATH, load_forward_validation

ROOT = Path(__file__).resolve().parents[1]
BUILDER_PATH = ROOT / "reports" / "backtest" / "build_forward_validation.py"


def _builder():
    spec = importlib.util.spec_from_file_location("build_forward_validation_test", BUILDER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    # Este endpoint no usa el motor, pero el router incluye otros que sí.
    app.state.engine = None
    return TestClient(app)


@pytest.fixture
def generated_report(tmp_path, monkeypatch):
    builder = _builder()
    out_json = tmp_path / "forward_validation.json"
    out_md = tmp_path / "FORWARD_VALIDATION.md"
    out_hash = tmp_path / "forward_validation.sha256"
    monkeypatch.setattr(builder, "OUT_JSON", out_json)
    monkeypatch.setattr(builder, "OUT_MD", out_md)
    monkeypatch.setattr(builder, "OUT_HASH", out_hash)

    def run(manual: Path, live: Path | None = None):
        monkeypatch.setattr(builder, "MANUAL_PROFILE", manual)
        monkeypatch.setattr(builder, "LIVE_PROFILE", live or tmp_path / "missing_live.json")
        assert builder.main() == 0
        return json.loads(out_json.read_text(encoding="utf-8")), out_md.read_text(
            encoding="utf-8"
        )

    return run


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
    assert forward["candidate_forward_protocol"] == "H-P2-BE1R-MANUAL-FORWARD"
    assert report["protocols"]["p2_be_manual_forward"]["can_execute"] is False
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
        "max_drawdown_pct": 9.793,
        "expectancy_r": 0.18,
        "total_r": 13.19,
    }
    assert metrics["p2"]["ops"] == 46
    assert metrics["p2"]["net_usd"] == 2471.78
    assert metrics["p2"]["profit_factor"] == 1.39
    assert metrics["p2_be_1r"]["net_usd"] == 2036.52
    assert metrics["p2_be_1r"]["profit_factor"] == 1.48
    assert metrics["p2_be_1r"]["max_drawdown_usd"] == 1794.46


def test_manual_contract_limit_matches_the_current_config() -> None:
    report = load_forward_validation()
    config = json.loads((ROOT / "data" / "config.json").read_text(encoding="utf-8"))
    expected = config["risk"]["max_contracts"]
    contract = report["manual_8765"]["contract_limit"]

    assert contract["value"] == expected
    assert contract["status"] == "configured"
    assert contract["source"] == "data/config.json#risk.max_contracts"
    assert report["manual_8765"]["settings"]["max_contracts"] == expected
    assert report["candidates"][0]["label"].startswith(
        f"Manual 8765 · {expected} contratos"
    )


def test_report_reads_contract_limit_from_effective_config(generated_report, tmp_path) -> None:
    config = json.loads((ROOT / "data" / "config.json").read_text(encoding="utf-8"))
    config["risk"]["max_contracts"] = 11
    manual = tmp_path / "config.json"
    manual.write_text(json.dumps(config), encoding="utf-8")

    protected_before = _sha(ROOT / "data" / "config.json")
    report, md = generated_report(manual)
    contract = report["manual_8765"]["contract_limit"]

    assert contract["value"] == 11
    assert contract["status"] == "configured"
    assert contract["source"].endswith("config.json#risk.max_contracts")
    assert report["manual_8765"]["settings"]["max_contracts"] == 11
    assert report["candidates"][0]["label"].startswith("Manual 8765 · 11 contratos")
    assert "**Valor:** `11`" in md
    assert _sha(ROOT / "data" / "config.json") == protected_before


def test_report_marks_contract_limit_as_not_recorded_without_config(generated_report) -> None:
    report, md = generated_report(ROOT / "missing-manual-config.json")
    contract = report["manual_8765"]["contract_limit"]

    assert contract["value"] is None
    assert contract["status"] == "not_recorded"
    assert "no se asume" in contract["note"]
    assert "contratos no registrados" in report["candidates"][0]["label"]
    assert "**Valor:** `no registrado`" in md


def test_sources_and_profiles_match_the_report_hashes() -> None:
    report = load_forward_validation()
    integrity = report["integrity"]
    assert integrity["protocol_v1_2_lock"] == _sha(ROOT / "docs" / "protocolo_backtest.lock.json")
    assert integrity["profiles_p2_freq"] == _sha(ROOT / "profiles" / "p2_freq" / "config.json")
    assert integrity["profiles_backtest_real"] == _sha(ROOT / "profiles" / "backtest_real" / "config.json")
    assert integrity["dataset_development"] == _sha(ROOT / "data" / "real" / "bars_mnq_nq_es_1m.csv")
    assert integrity["live_vs_original_source"] == _sha(
        ROOT / "reports" / "backtest" / "live_vs_original_mission.json"
    )
    assert integrity["p2_be_forward_lock"] == _sha(
        ROOT / "docs" / "p2_be_1r_forward.lock.json"
    )
    assert integrity["config_changed"] is False
    assert integrity["holdout_bars_read"] is False
    assert integrity["forward_csv_exists"] is False


def test_forward_preregistration_lock_matches_protocol_and_is_sealed() -> None:
    lock = json.loads(
        (ROOT / "docs" / "p2_be_1r_forward.lock.json").read_text(encoding="utf-8")
    )
    assert lock["protocol_sha256"] == _sha(ROOT / "docs" / "P2_BE_1R_FORWARD.md")
    assert set(lock["arms"]) == {"M", "C", "T"}
    assert lock["sample"]["start"] == "2026-12-01"
    assert lock["sample"]["end"] == "2029-11-30"
    assert lock["holdout"]["executed"] is False
    assert lock["holdout"]["used_for_decision"] is False
    assert lock["execution_gate"]["can_execute"] is False


def test_development_source_is_verifiable_json_and_does_not_use_holdout() -> None:
    source_path = ROOT / "reports" / "backtest" / "live_vs_original_mission.json"
    source = json.loads(source_path.read_text(encoding="utf-8"))
    report = load_forward_validation()

    assert source["scope"]["holdout_used"] is False
    assert source["constraints"]["holdout_accessed"] is False
    assert source["constraints"]["configs_modified"] is False
    assert source["aggregate"]["live"]["net_profit"] == 2022.94
    assert source["aggregate"]["original"]["net_profit"] == 661.44
    assert report["development"]["source"].startswith(
        "reports/backtest/live_vs_original_mission.json"
    )
    assert report["integrity"]["live_vs_original_source"] == _sha(source_path)


def test_report_artifacts_are_portable_and_sidecar_matches() -> None:
    for path in (
        REPORT_PATH,
        REPORT_PATH.parent / "FORWARD_VALIDATION.md",
        REPORT_PATH.parent / "forward_validation.sha256",
    ):
        assert b"\r" not in path.read_bytes(), f"{path.name} debe usar LF"
    line = (REPORT_PATH.parent / "forward_validation.sha256").read_bytes().decode("utf-8")
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
