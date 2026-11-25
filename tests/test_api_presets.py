"""Contrato HTTP de presets: catálogo, errores y CSV real recortado.

El cliente usa un perfil fixture independiente
(``tests/fixtures/presets_profile/config.json``) y un feed propio
(``tests/fixtures/bars_mnq_nq_es_1m_3sessions.csv``). Las expectativas de
procedencia, configuración y métricas son constantes del fixture: no se
derivan del mismo objeto ``Settings`` que recibe la API, para que ignorar la
configuración no pase inadvertido.
"""

from __future__ import annotations

import copy
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from server.api import PresetComparisonResponse, router
from server.backtest import DEFAULT_PRESETS, PRESETS, preset_sample
from server.config import Settings
from server.db import Store

ROOT = Path(__file__).resolve().parents[1]
# Perfil independiente: no se carga el perfil de producción ni se deriva la
# expectativa del objeto de settings que recibe la API.
FIXTURE_PROFILE = ROOT / "tests" / "fixtures" / "presets_profile" / "config.json"
CSV_FIXTURE_REL = "tests/fixtures/bars_mnq_nq_es_1m_3sessions.csv"
CSV_FIXTURE = ROOT / CSV_FIXTURE_REL
EXPECTED_NOTE = (
    "Comparación exploratoria sobre el mismo dataset. Los presets no se "
    "aplican a la configuración activa ni al holdout."
)
WINDOW = {"days": 3, "start_date": "2025-12-24"}
EXPECTED_FEED = {
    "provider": "csv",
    "kind": "csv",
    "path": CSV_FIXTURE_REL,
    "file_name": CSV_FIXTURE.name,
    "series_mode": "raw",
    "exclude_roll_sessions": False,
}
EXPECTED_BASELINE = {
    "trades": 1,
    "signals": 1,
    "win_rate": 100.0,
    "profit_factor": None,
    "expectancy": 101.0,
    "net_profit": 101.0,
    "max_drawdown": 0.0,
    "max_drawdown_pct": 0.0,
    "avg_r": 1.92,
    "total_r": 1.92,
    "stop_losses": 0,
    "take_profits": 1,
    "final_equity": 12446.0,
}
FIXTURE_PROFILE_BYTES = FIXTURE_PROFILE.read_bytes()


def _app(settings: Settings) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.engine = SimpleNamespace(settings=settings, store=Store(":memory:"))
    return app


@pytest.fixture(scope="module")
def profile_settings() -> Settings:
    """Settings del fixture, independientes del perfil real."""
    return Settings.model_validate_json(
        FIXTURE_PROFILE.read_text(encoding="utf-8")
    )


@pytest.fixture(scope="module")
def client(profile_settings):
    """Cliente del fixture: catálogo y errores de petición."""
    with TestClient(_app(profile_settings)) as instance:
        yield instance


@pytest.fixture(scope="module")
def payload(profile_settings):
    with TestClient(_app(profile_settings)) as instance:
        response = instance.post("/api/backtest/presets", json=WINDOW)
    assert response.status_code == 200, response.text
    return response.json()


def _reject(payload: dict, mutate, match: str) -> None:
    data = copy.deepcopy(payload)
    mutate(data)
    with pytest.raises(ValidationError, match=match):
        PresetComparisonResponse.model_validate(data)


def _active_row(data: dict) -> dict:
    row = next((item for item in data["comparison"] if item["trades"] > 0), None)
    assert row is not None, "el fixture debe contener una fila con operaciones"
    return row


def test_presets_contract_uses_three_sessions_of_real_csv(payload):
    assert payload["data_source"] == "csv"
    assert payload["is_synthetic"] is False
    assert payload["sessions"] == 3
    assert payload["default_presets"] is True
    assert payload["preset_keys"] == list(DEFAULT_PRESETS)
    assert [row["preset"] for row in payload["comparison"]] == list(DEFAULT_PRESETS)
    assert payload["dataset"]["kind"] == "csv"
    assert payload["dataset"]["file_name"] == CSV_FIXTURE.name
    assert payload["dataset"]["selected_range"]["first_et"].startswith("2025-12-24")
    assert payload["dataset"]["selected_range"]["last_et"].startswith("2025-12-29")
    assert payload["note"] == EXPECTED_NOTE

    base = payload["base_config"]
    assert base["risk"]["initial_capital"] == 12345.0
    assert base["risk"]["max_contracts"] == 2
    assert base["risk"]["max_sl_ticks"] == 120
    assert base["strategy"]["setup_validity_minutes"] == 180
    assert base["strategy"]["retest_tolerance_ticks"] == 18
    assert base["strategy"]["tp_rr"] == 2.0
    assert base["feed"] == {
        "provider": "csv",
        "csv_path": CSV_FIXTURE_REL,
        "series_mode": "raw",
        "exclude_roll_sessions": False,
        "replay_speed": 7.0,
        "loop_sessions": False,
        "start_date": "",
        "latency_ms": 0,
    }

    baseline = payload["comparison"][0]
    assert baseline["preset"] == "baseline"
    for key, value in EXPECTED_BASELINE.items():
        assert baseline[key] == value, (key, baseline[key], value)

    sample = payload["sample"]
    assert sample["status"] == "activity"
    assert sample["active_presets"] == 9
    assert sample["total_presets"] == len(DEFAULT_PRESETS)


def test_presets_catalog_matches_backend_counts_and_sample_provenance(client):
    response = client.get("/api/backtest/presets")
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["default"] == list(DEFAULT_PRESETS)
    assert body["count"] == len(DEFAULT_PRESETS)
    assert body["total"] == len(PRESETS)
    assert [preset["key"] for preset in body["presets"]] == list(PRESETS)
    assert {
        preset["key"] for preset in body["presets"] if preset["default"]
    } == set(DEFAULT_PRESETS)
    assert body["sample"] == EXPECTED_FEED
    assert body["note"]


def test_presets_rejects_too_few_sessions(client):
    response = client.post("/api/backtest/presets", json={"days": 2})
    assert response.status_code == 422


def test_presets_rejects_invalid_start_date(client):
    response = client.post(
        "/api/backtest/presets", json={**WINDOW, "start_date": "2025-13-01"}
    )
    assert response.status_code == 400
    assert "YYYY-MM-DD" in response.json()["detail"]


def test_presets_rejects_unknown_preset(client):
    response = client.post(
        "/api/backtest/presets", json={"days": 3, "presets": ["no_existe"]}
    )
    assert response.status_code == 400
    assert "desconocidos" in response.json()["detail"]


def test_response_rejects_non_default_eleven_presets(payload):
    replacement = next(key for key in PRESETS if key not in DEFAULT_PRESETS)

    def mutate(data: dict) -> None:
        data["preset_keys"][-1] = replacement
        data["comparison"][-1]["preset"] = replacement

    _reject(payload, mutate, "11 presets")


def test_response_rejects_comparison_out_of_sync(payload):
    _reject(payload, lambda data: data["comparison"].pop(), "preset_keys y comparison")


def test_response_rejects_inconsistent_expectancy(payload):
    def mutate(data: dict) -> None:
        row = _active_row(data)
        row["expectancy"] = row["net_profit"] / row["trades"] + 25

    _reject(payload, mutate, "expectancy")


def test_response_rejects_inconsistent_stop_loss_rate(payload):
    def mutate(data: dict) -> None:
        row = _active_row(data)
        expected = round(row["stop_losses"] / row["trades"] * 100, 2)
        row["stop_loss_rate"] = 0.0 if expected != 0.0 else 1.0

    _reject(payload, mutate, "stop_loss_rate")


def test_response_rejects_more_sessions_than_requested(payload):
    def mutate(data: dict) -> None:
        data["sessions"] = data["days_requested"] + 1
        data["sample"]["sessions"] = data["sessions"]

    _reject(payload, mutate, "sessions no puede superar")


def test_response_rejects_sample_count_mismatch(payload):
    def mutate(data: dict) -> None:
        data["sample"]["active_presets"] += 1

    _reject(payload, mutate, "active_presets")


def test_response_rejects_session_counters_above_sample(payload):
    def mutate(data: dict) -> None:
        data["comparison"][0]["qty_zero_sessions"] = data["sessions"] + 1

    _reject(payload, mutate, "qty_zero_sessions")


def test_response_rejects_synthetic_flag_mismatch(payload):
    _reject(payload, lambda data: data.__setitem__("is_synthetic", True), "is_synthetic")


def test_response_rejects_final_equity_mismatch(payload):
    def mutate(data: dict) -> None:
        row = _active_row(data)
        row["final_equity"] = (row["final_equity"] or 0) + 10

    _reject(payload, mutate, "final_equity")


def test_presets_does_not_mutate_or_persist_active_config(profile_settings):
    settings = profile_settings.model_copy(deep=True)
    before = settings.model_dump()
    app = _app(settings)

    with TestClient(app) as client:
        response = client.post(
            "/api/backtest/presets",
            json={
                "days": 3,
                "presets": ["baseline"],
                "overrides": {"strategy": {"tp_rr": 1.5}},
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_source"] == "csv"
    assert body["is_synthetic"] is False
    assert body["default_presets"] is False
    assert body["preset_keys"] == ["baseline"]
    assert body["overrides"] == {"strategy": {"tp_rr": 1.5}}
    assert body["base_config"]["strategy"]["tp_rr"] == 1.5
    assert body["base_config"]["risk"]["initial_capital"] == 12345.0
    assert settings.model_dump() == before
    assert app.state.engine.settings is settings
    assert FIXTURE_PROFILE.read_bytes() == FIXTURE_PROFILE_BYTES


def _row(trades: int) -> dict:
    return {"trades": trades}


def test_sample_state_with_activity():
    sample = preset_sample([_row(0), _row(3)], sessions=5, days_requested=5)
    assert sample["status"] == "activity"
    assert sample["active_presets"] == 1
    assert sample["total_presets"] == 2
    assert "1 de 2 presets" in sample["detail"]


def test_sample_state_without_trades():
    sample = preset_sample([_row(0), _row(0)], sessions=5, days_requested=5)
    assert sample["status"] == "no_trades"
    assert sample["active_presets"] == 0
    assert sample["total_presets"] == 2


def test_sample_state_insufficient_below_minimum_sessions():
    sample = preset_sample([_row(4)], sessions=2, days_requested=3)
    assert sample["status"] == "insufficient"
    assert "2 de 3 sesiones" in sample["detail"]


def test_sample_state_insufficient_without_rows():
    sample = preset_sample([], sessions=5, days_requested=5)
    assert sample["status"] == "insufficient"
    assert sample["total_presets"] == 0
