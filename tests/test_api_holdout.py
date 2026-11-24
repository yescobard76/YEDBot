"""Contrato HTTP del bloqueo del holdout, sin ejecutar el holdout.

Los CSV de holdout de estos tests son **sintéticos**: se generan con
``build_session`` para fechas del holdout (2026-07-01/02) y no contienen
observaciones reales. Así se prueba el guardia sin abrir el holdout sellado.

La regla es la misma en las tres rutas: cualquier CSV que contenga sesiones
desde ``HOLDOUT_START`` se rechaza completo, aunque la ventana pedida empiece
en desarrollo. Solo ``server.confirmatory.run_holdout`` pasa
``allow_holdout=True``; las peticiones HTTP no pueden activar ese flag.
"""

from __future__ import annotations

import ast
import inspect
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import (
    BacktestRequest,
    CsvValidateRequest,
    PresetBacktestRequest,
    router,
)
from server.backtest import prepare_dataset, run_backtest, run_presets, run_variants
from server.config import Settings
from server.db import Store
from server.engine import TradingEngine
from server.market.csv_data import (
    HOLDOUT_END,
    HOLDOUT_START,
    REQUIRED_SYMBOLS,
    refuse_holdout_sessions,
)
from server.market.synthetic import build_session

ROOT = Path(__file__).resolve().parents[1]
DEV_CSV = ROOT / "tests" / "fixtures" / "bars_mnq_nq_es_1m_3sessions.csv"
DEV_START = "2025-12-24"
MIXED_DAYS = [
    date(2026, 6, 26),
    date(2026, 6, 29),
    date(2026, 6, 30),
    HOLDOUT_START,
    date(2026, 7, 2),
]


def _write_synthetic_sessions(path: Path, days: list[date]) -> Path:
    settings = Settings()
    rows = ["timestamp,symbol,open,high,low,close,volume"]
    for day in days:
        data = build_session(day, settings)
        for symbol in REQUIRED_SYMBOLS:
            for bar in data[symbol]:
                rows.append(
                    f"{bar.ts},{symbol},{bar.open:.4f},{bar.high:.4f},"
                    f"{bar.low:.4f},{bar.close:.4f},{bar.volume:.2f}"
                )
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return path


def _app(engine: TradingEngine) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.engine = engine
    return app


@pytest.fixture(scope="module")
def holdout_csv(tmp_path_factory) -> Path:
    return _write_synthetic_sessions(
        tmp_path_factory.mktemp("holdout") / "bars_with_holdout.csv",
        MIXED_DAYS,
    )


@pytest.fixture(scope="module")
def engine(tmp_path_factory, holdout_csv) -> TradingEngine:
    settings = Settings(
        feed={
            "provider": "csv",
            "csv_path": str(holdout_csv),
            "series_mode": "raw",
            "exclude_roll_sessions": True,
        }
    )
    store = Store(tmp_path_factory.mktemp("api_holdout") / "holdout.db")
    instance = TradingEngine(store, settings)
    yield instance
    store.close()


@pytest.fixture(scope="module")
def client(engine) -> TestClient:
    with TestClient(_app(engine)) as instance:
        yield instance


@pytest.fixture(scope="module")
def dev_client(tmp_path_factory) -> TestClient:
    settings = Settings(
        feed={
            "provider": "csv",
            "csv_path": str(DEV_CSV),
            "series_mode": "raw",
            "exclude_roll_sessions": True,
        }
    )
    store = Store(tmp_path_factory.mktemp("api_dev") / "dev.db")
    instance = TradingEngine(store, settings)
    with TestClient(_app(instance)) as test_client:
        yield test_client
    store.close()


@pytest.mark.parametrize("start_date", ["2026-06-29", "2026-07-01", "2026-07-02"])
def test_backtest_run_rejects_windows_that_cross_the_holdout(
    client, engine, start_date: str
) -> None:
    before = engine.settings.model_dump()

    response = client.post(
        "/api/backtest/run",
        json={"days": 3, "start_date": start_date, "persist": True},
    )

    assert response.status_code == 400, response.text
    detail = response.json()["detail"]
    assert "CSV bloqueado" in detail
    assert HOLDOUT_START.isoformat() in detail
    assert engine.store.latest_backtest() is None
    assert engine.settings.model_dump() == before


def test_backtest_run_rejects_mixed_csv_even_for_a_development_window(
    client, engine
) -> None:
    # 26, 29 y 30 de junio: la ventana pedida no toca el holdout, pero el
    # archivo sí. El bloqueo es del CSV completo, no solo de la selección.
    response = client.post(
        "/api/backtest/run",
        json={"days": 3, "start_date": "2026-06-26", "persist": True},
    )

    assert response.status_code == 400, response.text
    assert "CSV bloqueado" in response.json()["detail"]
    assert engine.store.latest_backtest() is None


@pytest.mark.parametrize("start_date", ["2026-06-29", "2026-07-01"])
def test_backtest_presets_rejects_windows_that_cross_the_holdout(
    client, engine, start_date: str
) -> None:
    before = engine.settings.model_dump()

    response = client.post(
        "/api/backtest/presets",
        json={"days": 3, "start_date": start_date},
    )

    assert response.status_code == 400, response.text
    assert "CSV bloqueado" in response.json()["detail"]
    assert engine.settings.model_dump() == before


def test_data_validate_rejects_csv_with_holdout_sessions(client, holdout_csv) -> None:
    before = holdout_csv.read_bytes()

    response = client.post(
        "/api/data/validate",
        json={"path": str(holdout_csv), "series_mode": "raw"},
    )

    assert response.status_code == 400, response.text
    body = response.json()
    assert "CSV bloqueado" in body["detail"]
    assert HOLDOUT_START.isoformat() in body["detail"]
    assert "ok" not in body
    assert holdout_csv.read_bytes() == before


def test_data_validate_accepts_development_csv(client) -> None:
    response = client.post(
        "/api/data/validate",
        json={"path": str(DEV_CSV), "series_mode": "raw"},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is True
    assert body["session_count"] == 3


def test_backtest_run_accepts_a_development_window(dev_client) -> None:
    response = dev_client.post(
        "/api/backtest/run",
        json={"days": 3, "start_date": DEV_START, "persist": False},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["data_source"] == "csv"
    assert body["is_synthetic"] is False


def test_holdout_guard_boundary_uses_development_end_inclusive() -> None:
    refuse_holdout_sessions([date(2026, 6, 30), "2026-06-29"])

    with pytest.raises(ValueError, match="CSV bloqueado"):
        refuse_holdout_sessions([HOLDOUT_START])
    with pytest.raises(ValueError, match="CSV bloqueado"):
        refuse_holdout_sessions([HOLDOUT_END])


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/backtest/run", {"days": 3, "allow_holdout": True}),
        ("/api/backtest/presets", {"days": 3, "allow_holdout": True}),
        (
            "/api/data/validate",
            {"path": str(DEV_CSV), "allow_holdout": True},
        ),
    ],
)
def test_http_requests_cannot_enable_allow_holdout(client, path, payload) -> None:
    response = client.post(path, json=payload)

    assert response.status_code == 422, response.text
    assert "allow_holdout" in response.text


def test_request_models_do_not_expose_allow_holdout() -> None:
    for model in (BacktestRequest, PresetBacktestRequest, CsvValidateRequest):
        assert "allow_holdout" not in model.model_fields


def test_only_confirmatory_route_enables_allow_holdout() -> None:
    calls: set[str] = set()
    for path in (ROOT / "server").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "allow_holdout"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    calls.add(path.relative_to(ROOT).as_posix())

    assert calls == {"server/confirmatory.py"}
    for function in (prepare_dataset, run_backtest, run_variants, run_presets):
        assert inspect.signature(function).parameters["allow_holdout"].default is False
