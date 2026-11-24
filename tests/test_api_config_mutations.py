"""Contrato HTTP de mutaciones de configuración, aislado del perfil real.

Cada test usa un ``config.json`` temporal monkeypatcheando
``server.config.CONFIG_PATH``. El ``save_settings`` real escribe ahí, de modo que
se comprueban validación, persistencia y atomicidad sin tocar
``data/config.json`` ni ``profiles/backtest_real/config.json``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import router
from server.config import CONFIG_PATH, Settings, load_settings
from server.db import Store
from server.engine import TradingEngine
from server.models import Position

ROOT = Path(__file__).resolve().parents[1]
REAL_PROFILE = ROOT / "profiles" / "backtest_real" / "config.json"
REAL_CONFIG_BYTES = CONFIG_PATH.read_bytes() if CONFIG_PATH.exists() else None
REAL_PROFILE_BYTES = REAL_PROFILE.read_bytes()


def _position() -> Position:
    return Position(
        id="config-open-position",
        symbol="MNQ",
        direction="long",
        qty=1,
        entry_price=20_000.0,
        entry_ts=1_700_000_000,
        stop=19_950.0,
        target=20_150.0,
        initial_stop=19_950.0,
        risk_amount=100.0,
        signal_id="config-signal",
        signal_type="ORB+SMT+Retest",
        entry_reason="posición de prueba de configuración",
    )


def _saved(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def real_config_is_untouched():
    yield
    if REAL_CONFIG_BYTES is not None:
        assert CONFIG_PATH.read_bytes() == REAL_CONFIG_BYTES
    assert REAL_PROFILE.read_bytes() == REAL_PROFILE_BYTES


@pytest.fixture
def profile(tmp_path, monkeypatch):
    directory = tmp_path / "profile"
    directory.mkdir()
    config_path = directory / "config.json"
    config_path.write_text(Settings().model_dump_json(indent=2), encoding="utf-8")
    assert config_path.resolve() != CONFIG_PATH.resolve()

    # save_settings() resuelve CONFIG_PATH en server.config en cada llamada.
    monkeypatch.setattr("server.config.CONFIG_PATH", config_path)

    store = Store(directory / "test.db")
    engine = TradingEngine(store, Settings())
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.engine = engine
    with TestClient(app) as client:
        yield client, engine, config_path
    store.close()


def test_put_config_valid_patch_updates_engine_and_persists(profile) -> None:
    client, engine, config_path = profile
    initial_bytes = config_path.read_bytes()
    before = engine.settings.model_dump()

    response = client.put(
        "/api/config",
        json={
            "patch": {
                "strategy": {"tp_rr": 2.25},
                "risk": {"max_trades_per_day": 4},
            }
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["message"] == "Configuración guardada"
    assert body["settings"]["strategy"]["tp_rr"] == 2.25
    assert body["settings"]["risk"]["max_trades_per_day"] == 4
    assert engine.settings.model_dump() == body["settings"]
    assert engine.settings.strategy.tp_rr == 2.25
    assert engine.settings.risk.max_trades_per_day == 4
    assert engine.settings.model_dump() != before
    assert engine.execution.settings is engine.settings
    assert engine.risk.settings is engine.settings

    saved = _saved(config_path)
    assert saved == engine.settings.model_dump()
    assert Settings.model_validate(saved).model_dump() == engine.settings.model_dump()
    assert load_settings().model_dump() == engine.settings.model_dump()
    assert config_path.read_bytes() != initial_bytes
    assert not list(config_path.parent.glob(".cfg-*"))


@pytest.mark.parametrize(
    "patch",
    [
        {"strategy": {"tp_rr": 99}},
        {"strategy": {"tp_rr": "alto"}},
        {"orb": {"start": "10:00", "end": "09:00"}},
    ],
)
def test_put_config_rejects_invalid_patch_without_mutation(profile, patch) -> None:
    client, engine, config_path = profile
    before_settings = engine.settings
    before = engine.settings.model_dump()
    before_bytes = config_path.read_bytes()

    response = client.put("/api/config", json={"patch": patch})

    assert response.status_code == 400, response.text
    assert "Configuración inválida" in response.json()["detail"]
    assert engine.settings is before_settings
    assert engine.settings.model_dump() == before
    assert config_path.read_bytes() == before_bytes
    assert not list(config_path.parent.glob(".cfg-*"))


def test_partial_patch_is_all_or_nothing(profile) -> None:
    client, engine, config_path = profile
    before = engine.settings.model_dump()
    before_bytes = config_path.read_bytes()

    response = client.put(
        "/api/config",
        json={
            "patch": {
                "risk": {"max_trades_per_day": 5},
                "strategy": {"tp_rr": 99},
            }
        },
    )

    assert response.status_code == 400, response.text
    assert "Configuración inválida" in response.json()["detail"]
    assert engine.settings.model_dump() == before
    assert engine.settings.strategy.tp_rr == 3.0
    assert engine.settings.risk.max_trades_per_day == 3
    assert config_path.read_bytes() == before_bytes


def test_force_is_required_only_for_critical_sections_with_open_position(profile) -> None:
    client, engine, config_path = profile
    position = _position()
    engine.execution.position = position

    # feed no es una sección crítica: se aplica sin force.
    response = client.put(
        "/api/config",
        json={"patch": {"feed": {"replay_speed": 3.0}}, "force": False},
    )
    assert response.status_code == 200, response.text
    assert engine.settings.feed.replay_speed == 3.0
    assert engine.execution.position is position
    after_noncritical = config_path.read_bytes()

    # strategy sí es crítica: sin force se rechaza antes de validar.
    response = client.put(
        "/api/config",
        json={"patch": {"strategy": {"tp_rr": 2.5}}, "force": False},
    )
    assert response.status_code == 400, response.text
    assert "posición abierta" in response.json()["detail"]
    assert engine.settings.strategy.tp_rr == 3.0
    assert engine.execution.position is position
    assert config_path.read_bytes() == after_noncritical

    response = client.put(
        "/api/config",
        json={"patch": {"strategy": {"tp_rr": 2.5}}, "force": True},
    )
    assert response.status_code == 200, response.text
    assert engine.settings.strategy.tp_rr == 2.5
    assert engine.execution.position is position
    assert _saved(config_path)["strategy"]["tp_rr"] == 2.5


def test_forced_invalid_patch_is_still_rejected(profile) -> None:
    client, engine, config_path = profile
    engine.execution.position = _position()
    before = engine.settings.model_dump()
    before_bytes = config_path.read_bytes()

    response = client.put(
        "/api/config",
        json={"patch": {"risk": {"max_trades_per_day": 0}}, "force": True},
    )

    assert response.status_code == 400, response.text
    assert "Configuración inválida" in response.json()["detail"]
    assert engine.settings.model_dump() == before
    assert config_path.read_bytes() == before_bytes


def test_reset_restores_defaults_and_persists(profile) -> None:
    client, engine, config_path = profile

    changed = client.put(
        "/api/config",
        json={
            "patch": {
                "strategy": {"tp_rr": 2.25},
                "risk": {"max_trades_per_day": 5},
            }
        },
    )
    assert changed.status_code == 200, changed.text
    assert engine.settings.strategy.tp_rr == 2.25

    response = client.post("/api/config/reset")

    assert response.status_code == 200, response.text
    body = response.json()
    defaults = Settings().model_dump()
    assert body["ok"] is True
    assert body["message"] == "Configuración guardada"
    assert body["settings"] == defaults
    assert engine.settings.model_dump() == defaults
    assert engine.settings.strategy.tp_rr == 3.0
    assert engine.settings.risk.max_trades_per_day == 3
    assert _saved(config_path) == defaults
    assert load_settings().model_dump() == defaults
    assert config_path.read_text(encoding="utf-8") == Settings().model_dump_json(
        indent=2
    )
    assert not list(config_path.parent.glob(".cfg-*"))


def test_reset_forces_with_open_position(profile) -> None:
    client, engine, config_path = profile
    engine.execution.position = _position()

    changed = client.put(
        "/api/config",
        json={"patch": {"strategy": {"tp_rr": 2.5}}, "force": True},
    )
    assert changed.status_code == 200, changed.text
    assert engine.settings.strategy.tp_rr == 2.5

    response = client.post("/api/config/reset")

    assert response.status_code == 200, response.text
    assert engine.settings == Settings()
    assert engine.execution.position is not None
    assert _saved(config_path) == Settings().model_dump()
