"""Contrato HTTP de los endpoints sin tests directos.

Cubre estado, claves obligatorias y no mutación de:

``/status``, ``/config``, ``/trades``, ``/stats``, ``/orders``, ``/events``,
``/chart/history``, ``/backtest/run``, ``/backtest/latest``, ``/datasets``,
``/data/validate`` y ``/trades/export.csv``.

Usa un ``TradingEngine`` real sobre SQLite temporal, sin arrancar el servidor
ni el feed, y el extracto real de tres sesiones para ``/data/validate``. La
configuración activa y el perfil real se leen solo para comprobar que no
cambian.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import router
from server.backtest import VARIANTS
from server.config import CONFIG_PATH, Settings
from server.db import Store
from server.engine import TradingEngine
from server.market.csv_data import DATA_SCHEMA_VERSION, REQUIRED_SYMBOLS, SERIES_MODES
from server.models import Bar
from server.strategy.strategy import PHASE_ORDER

ROOT = Path(__file__).resolve().parents[1]
CSV_FIXTURE = ROOT / "tests" / "fixtures" / "bars_mnq_nq_es_1m_3sessions.csv"
PROFILE = ROOT / "profiles" / "backtest_real" / "config.json"
PROFILE_BYTES = PROFILE.read_bytes()
ACTIVE_BYTES = CONFIG_PATH.read_bytes() if CONFIG_PATH.exists() else None

SESSION_DATE = "2025-06-03"
NOW = int(time.time())
RISK = 75.0

CSV_HEADERS = [
    "Fecha",
    "Hora",
    "Instrumento",
    "Direccion",
    "Cantidad",
    "Entrada",
    "Salida",
    "StopLoss",
    "TakeProfit",
    "ResultadoUSD",
    "R",
    "DuracionSeg",
    "TipoSenal",
    "MotivoEntrada",
    "MotivoSalida",
    "Modo",
]

GET_MATRIX = [
    (
        "/api/status",
        {
            "server_time",
            "status",
            "mode",
            "instrument",
            "data",
            "session",
            "quotes",
            "assessment",
            "position",
            "orders",
            "risk",
            "stats",
            "day_stats",
            "recent_trades",
            "ambiguous_bars",
            "events",
            "chart",
            "config",
            "settings",
        },
    ),
    ("/api/config", {"settings", "defaults", "mode"}),
    ("/api/trades", {"items", "total", "limit", "offset"}),
    (
        "/api/stats",
        {
            "trades",
            "wins",
            "losses",
            "win_rate",
            "profit_factor",
            "expectancy",
            "net_profit",
            "max_drawdown",
            "max_drawdown_pct",
            "equity_curve",
            "daily",
            "monthly",
            "by_hour",
            "by_direction",
            "by_signal",
            "by_weekday",
        },
    ),
    ("/api/orders", {"items", "position"}),
    ("/api/events", {"items"}),
    ("/api/chart/history", {"bars", "count", "session"}),
    ("/api/backtest/latest", {"result"}),
    (
        "/api/datasets",
        {
            "provider",
            "csv_path",
            "required_symbols",
            "schema_version",
            "format",
            "series_modes",
            "series_mode",
            "exclude_roll_sessions",
            "roll_policy",
            "synthetic_available",
            "note",
        },
    ),
]


def _trade(
    trade_id: str,
    *,
    exit_ts: int,
    pnl: float,
    r_multiple: float,
    exit_reason: str,
    exit_price: float,
) -> dict:
    return {
        "id": trade_id,
        "mode": "paper",
        "signal_id": f"signal-{trade_id}",
        "symbol": "MNQ",
        "direction": "long",
        "qty": 1,
        "entry_ts": exit_ts - 3600,
        "entry_price": 20_000.0,
        "exit_ts": exit_ts,
        "exit_price": exit_price,
        "stop": 19_962.5,
        "target": 20_112.5,
        "pnl": pnl,
        "gross_pnl": pnl - 1.24,
        "fees": 1.24,
        "r_multiple": r_multiple,
        "risk_amount": RISK,
        "signal_type": "ORB+SMT+Retest",
        "entry_reason": "contrato HTTP",
        "exit_reason": exit_reason,
        "duration_sec": 3600,
        "mfe_r": 2.2,
        "mae_r": -0.2,
        "mfe_usd": 165.0,
        "mae_usd": -15.0,
        "open_drawdown": 10.0,
        "contract": "MNQZ5",
        "expiry": "2025-12-19",
        "meta": {},
    }


@pytest.fixture(scope="module")
def engine(tmp_path_factory) -> TradingEngine:
    """Motor real con historial determinista: una pérdida y una ganancia."""
    store = Store(tmp_path_factory.mktemp("api_contract") / "contract.db")
    store.insert_trade(
        _trade(
            "contract-loss",
            exit_ts=NOW - 7200,
            pnl=-RISK,
            r_multiple=-1.0,
            exit_reason="stop_loss",
            exit_price=19_962.5,
        )
    )
    store.insert_trade(
        _trade(
            "contract-win",
            exit_ts=NOW - 3600,
            pnl=150.0,
            r_multiple=2.0,
            exit_reason="take_profit",
            exit_price=20_075.0,
        )
    )
    store.insert_event("INFO", "contract", "Evento de contrato", {"suite": "api"})

    instance = TradingEngine(store, Settings())
    instance.session_date = SESSION_DATE
    for index in range(120):
        close = 20_000.0 + index
        instance.chart_history.append(
            Bar(
                NOW - 120 * 60 + index * 60,
                close - 5,
                close + 10,
                close - 10,
                close,
                100 + index,
            ).as_dict()
        )
    yield instance
    store.close()


@pytest.fixture(scope="module")
def client(engine) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.engine = engine
    with TestClient(app) as instance:
        yield instance


@pytest.fixture(scope="module")
def backtest_run(client) -> dict:
    response = client.post(
        "/api/backtest/run",
        json={"days": 3, "persist": True, "label": "contrato-api"},
    )
    assert response.status_code == 200, response.text
    return response.json()


@pytest.mark.parametrize(("path", "required"), GET_MATRIX)
def test_get_contract_matrix(client, path: str, required: set[str]) -> None:
    response = client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert required <= set(body), f"{path} no devuelve {sorted(required - set(body))}"
    json.dumps(body)


def test_status_contract(client, engine) -> None:
    body = client.get("/api/status").json()

    assert isinstance(body["server_time"], int) and body["server_time"] > 0
    assert body["status"] == engine.status
    assert body["mode"] == engine.settings.mode
    assert body["instrument"] == engine.settings.instrument
    assert body["reference_symbol"] == engine.settings.reference_symbol
    assert body["comparison_symbol"] == engine.settings.comparison_symbol

    assert {"kind", "label", "quality", "connected", "detail", "stale", "delayed"} <= set(
        body["data"]
    )
    assert body["data"]["kind"] == "simulated"
    assert body["data"]["connected"] is True

    assert body["session"]["date"] == SESSION_DATE
    assert body["session"]["or_start"] == engine.settings.orb.start
    assert body["session"]["or_end"] == engine.settings.orb.end
    assert body["session"]["trade_window_start"] == engine.settings.risk.trade_window_start
    assert body["session"]["close_time"] == engine.settings.risk.session_close_time

    assert set(body["quotes"]) == {"MNQ", "NQ", "ES"}
    for quote in body["quotes"].values():
        assert {"last", "change", "change_pct", "ts", "volume"} <= set(quote)

    phases = body["assessment"]["phases"]
    assert [phase["key"] for phase in phases] == [key for key, _ in PHASE_ORDER]
    assert all({"key", "label", "status", "detail", "ts"} <= set(phase) for phase in phases)
    assert {"breakout", "smt", "retest", "reject", "signal", "reference_level", "atr"} <= set(
        body["assessment"]
    )

    assert body["position"] is None
    assert body["orders"] == []
    assert body["stats"]["trades"] == 2
    assert len(body["recent_trades"]) == 2
    assert isinstance(body["ambiguous_bars"]["count"], int)
    assert isinstance(body["ambiguous_bars"]["recent"], list)
    assert {"bars", "nq", "es", "markers", "smt"} <= set(body["chart"])

    assert body["risk"]["initial_capital"] == engine.settings.risk.initial_capital
    assert isinstance(body["risk"]["equity"], float)
    assert body["config"]["provider"] == engine.settings.feed.provider
    assert body["config"]["confirm_tf"] == engine.settings.strategy.confirm_tf
    assert body["settings"] == engine.settings.model_dump()


def test_config_contract(client, engine) -> None:
    body = client.get("/api/config").json()

    assert set(body) == {"settings", "defaults", "mode"}
    assert body["settings"] == engine.settings.model_dump()
    assert body["defaults"] == Settings().model_dump()
    assert body["mode"] == engine.settings.mode
    assert body["settings"]["mode"] == body["mode"]
    for section in ("orb", "smt", "strategy", "risk", "execution", "feed", "live"):
        assert section in body["settings"]


def test_trades_contract_with_pagination_and_filters(client) -> None:
    body = client.get("/api/trades").json()

    assert body["total"] == 2
    assert [item["id"] for item in body["items"]] == ["contract-win", "contract-loss"]
    assert body["limit"] == 50
    assert body["offset"] == 0
    for item in body["items"]:
        assert {"id", "symbol", "direction", "qty", "entry_ts", "exit_ts", "pnl"} <= set(item)

    page = client.get("/api/trades", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 2
    assert len(page["items"]) == 1
    assert page["items"][0]["id"] == "contract-loss"

    shorts = client.get("/api/trades", params={"direction": "short"}).json()
    assert shorts["total"] == 0
    assert shorts["items"] == []

    for params in ({"limit": 0}, {"limit": 501}, {"offset": -1}):
        assert client.get("/api/trades", params=params).status_code == 422


def test_stats_contract_and_metric_invariants(client) -> None:
    body = client.get("/api/stats").json()

    assert body["trades"] == 2
    assert body["wins"] == 1
    assert body["losses"] == 1
    assert body["breakeven"] == 0
    assert body["win_rate"] == 50.0
    assert body["profit_factor"] == 2.0
    assert body["expectancy"] == 37.5
    assert body["net_profit"] == 75.0
    assert body["gross_profit"] == 150.0
    assert body["gross_loss"] == -75.0
    assert body["fees"] == 2.48
    assert body["avg_r"] == 0.5
    assert body["total_r"] == 1.0
    assert body["max_drawdown"] == 75.0
    assert body["max_drawdown_pct"] == 0.3
    assert body["equity_trough"] == 24_925.0
    assert [point["equity"] for point in body["equity_curve"]] == [25_000.0, 24_925.0, 25_075.0]
    assert [bucket["key"] for bucket in body["by_direction"]] == ["long"]

    filtered = client.get("/api/stats", params={"period": "all"}).json()
    assert filtered["trades"] == body["trades"]
    assert filtered["net_profit"] == body["net_profit"]


def test_orders_contract_without_position(client) -> None:
    assert client.get("/api/orders").json() == {"items": [], "position": None}


def test_events_contract_and_level_filter(client) -> None:
    body = client.get("/api/events").json()

    assert len(body["items"]) == 1
    item = body["items"][0]
    assert {"id", "ts", "level", "category", "message", "meta"} <= set(item)
    assert item["level"] == "INFO"
    assert item["category"] == "contract"
    assert item["message"] == "Evento de contrato"
    assert item["meta"] == {"suite": "api"}

    assert client.get("/api/events", params={"level": "ERROR"}).json()["items"] == []


def test_chart_history_contract_and_limit(client) -> None:
    body = client.get("/api/chart/history").json()

    assert body["count"] == 120
    assert body["session"] == SESSION_DATE
    assert len(body["bars"]) == 120
    assert {"t", "o", "h", "l", "c", "v"} <= set(body["bars"][0])
    assert body["bars"][-1]["c"] == 20_119.0

    last = client.get("/api/chart/history", params={"limit": 100}).json()
    assert last["count"] == 100
    assert last["bars"][0]["c"] == 20_020.0
    assert last["bars"][-1]["c"] == 20_119.0

    assert client.get("/api/chart/history", params={"limit": 99}).status_code == 422
    assert client.get("/api/chart/history", params={"limit": 10_001}).status_code == 422


def test_backtest_run_contract(backtest_run) -> None:
    body = backtest_run

    assert {
        "id",
        "created_ts",
        "label",
        "data_source",
        "data_quality",
        "dataset_id",
        "dataset",
        "data_range",
        "config",
        "metrics",
        "diagnostics",
        "trades",
        "equity",
        "days_detail",
        "funnel",
        "overrides",
        "is_synthetic",
    } <= set(body)
    assert isinstance(body["id"], str) and len(body["id"]) == 16
    assert body["created_ts"] > 0
    assert body["label"] == "contrato-api"
    assert body["data_source"] == "synthetic"
    assert body["is_synthetic"] is True
    assert body["data_quality"] == "simulated"
    assert body["overrides"] == {}
    assert body["dataset"]["kind"] == "synthetic"
    assert body["config"]["strategy"]["tp_rr"] == Settings().strategy.tp_rr

    metrics = body["metrics"]
    for key in (
        "trades",
        "signals",
        "breakouts",
        "net_profit",
        "win_rate",
        "profit_factor",
        "max_drawdown",
        "stop_losses",
        "take_profits",
        "session_closes",
        "stop_cap_sessions",
        "qty_zero_sessions",
        "days_traded",
        "equity_curve",
    ):
        assert key in metrics
    assert metrics["trades"] == len(body["trades"])
    assert body["equity"] == metrics["equity_curve"]

    assert len(body["days_detail"]) == 3
    assert len(body["funnel"]["sessions"]) == 3
    assert body["funnel"]["schema"] == "funnel-v1"
    assert body["funnel"]["summary"]["sessions"] == 3


def test_backtest_latest_returns_persisted_result(client, backtest_run) -> None:
    result = client.get("/api/backtest/latest").json()["result"]

    assert result["id"] == backtest_run["id"]
    assert set(result) == {
        "ledger_status",
        "hypothesis_id",
        "ledger_event_id",
        "ledger_event_sha256",
        "ledger_error",
        "id",
        "created_ts",
        "label",
        "data_source",
        "dataset",
        "diagnostics",
        "experiment",
        "config",
        "metrics",
        "trades",
        "equity",
    }
    assert result["label"] == "contrato-api"
    assert result["data_source"] == "synthetic"
    assert result["dataset"]["kind"] == "synthetic"
    assert result["metrics"]["trades"] == backtest_run["metrics"]["trades"]
    assert result["equity"] == backtest_run["equity"]


def test_backtest_compare_contract(client) -> None:
    response = client.post(
        "/api/backtest/run", json={"days": 3, "compare": True, "persist": False}
    )
    assert response.status_code == 200, response.text
    body = response.json()

    assert set(body) == {"variants", "data_source", "backtest_run_id"}
    assert body["backtest_run_id"] is None
    assert body["data_source"] == "synthetic"
    assert [variant["variant"] for variant in body["variants"]] == list(VARIANTS)
    for variant in body["variants"]:
        assert {"id", "variant", "metrics", "trades", "equity", "funnel"} <= set(variant)
        assert variant["data_source"] == "synthetic"
        assert variant["metrics"]["trades"] == len(variant["trades"])


def test_backtest_run_request_validation(client) -> None:
    for payload in ({"days": 2}, {"days": 251}, {"days": "tres"}):
        assert client.post("/api/backtest/run", json=payload).status_code == 422

    response = client.post("/api/backtest/run", json={"days": 3, "start_date": "2025-13-01"})
    assert response.status_code == 400
    assert "YYYY-MM-DD" in response.json()["detail"]


def test_datasets_contract(client, engine) -> None:
    body = client.get("/api/datasets").json()

    assert body["provider"] == engine.settings.feed.provider
    assert body["csv_path"] == engine.settings.feed.csv_path
    assert body["required_symbols"] == list(REQUIRED_SYMBOLS)
    assert body["schema_version"] == DATA_SCHEMA_VERSION
    assert body["series_modes"] == sorted(SERIES_MODES)
    assert body["series_mode"] == engine.settings.feed.series_mode
    assert body["exclude_roll_sessions"] == engine.settings.feed.exclude_roll_sessions
    assert body["synthetic_available"] is True
    assert body["format"]
    assert body["roll_policy"]
    assert body["note"]


def test_data_validate_contract(client) -> None:
    body = client.post(
        "/api/data/validate",
        json={
            "path": str(CSV_FIXTURE),
            "series_mode": "raw",
            "exclude_roll_sessions": True,
        },
    ).json()

    assert body["ok"] is True
    assert body["path"] == str(CSV_FIXTURE)
    assert body["series_mode"] == "raw"
    assert body["exclude_roll_sessions"] is True
    assert body["schema_version"] == DATA_SCHEMA_VERSION
    assert set(body["symbols"]) == set(REQUIRED_SYMBOLS)
    assert set(body["manifest"]["symbols"]) == set(REQUIRED_SYMBOLS)
    assert all(count > 0 for count in body["manifest"]["symbols"].values())
    assert body["common_bars"] > 0
    assert body["session_count"] == 3
    assert len(body["sessions"]) == 3
    assert body["range"]["first_et"].startswith("2025-12-24")
    assert body["range"]["last_et"].startswith("2025-12-29")
    assert len(body["file_hash"]) == 64
    assert int(body["file_hash"], 16) >= 0
    assert body["dataset_id"]
    assert body["series_id"]
    assert {"ok", "invalid_sessions", "expected_bars", "missing_sessions"} <= set(
        body["session_validation"]
    )
    assert isinstance(body["warnings"], list)
    assert body["manifest"]


def test_data_validate_error_matrix(client, tmp_path) -> None:
    missing = client.post(
        "/api/data/validate", json={"path": str(tmp_path / "no_existe.csv")}
    )
    assert missing.status_code == 400
    assert "No existe el CSV" in missing.json()["detail"]

    other = tmp_path / "barras.txt"
    other.write_text("timestamp,symbol\n", encoding="utf-8")
    non_csv = client.post("/api/data/validate", json={"path": str(other)})
    assert non_csv.status_code == 400
    assert "extensión" in non_csv.json()["detail"]

    bad_mode = client.post(
        "/api/data/validate",
        json={"path": str(CSV_FIXTURE), "series_mode": "intradia"},
    )
    assert bad_mode.status_code == 400
    assert "series_mode" in bad_mode.json()["detail"]


def test_trades_export_contract(client) -> None:
    response = client.get("/api/trades/export.csv", params={"period": "all"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert re.fullmatch(
        r'attachment; filename="yedbot_operaciones_\d{4}-\d{2}-\d{2}\.csv"',
        response.headers["content-disposition"],
    )
    assert response.content.startswith(b"\xef\xbb\xbf")

    lines = response.content.decode("utf-8-sig").strip().splitlines()
    assert lines[0].split(";") == CSV_HEADERS
    assert len(lines) == 3

    rows = [line.split(";") for line in lines[1:]]
    assert [row[2] for row in rows] == ["MNQ", "MNQ"]
    assert [row[3] for row in rows] == ["Larga", "Larga"]
    assert [row[9] for row in rows] == ["-75.00", "150.00"]
    assert [row[10] for row in rows] == ["-1.00", "2.00"]
    assert [row[15] for row in rows] == ["paper", "paper"]

    filtered = client.get("/api/trades/export.csv", params={"direction": "short"})
    assert filtered.status_code == 200
    assert len(filtered.content.decode("utf-8-sig").strip().splitlines()) == 1


def test_no_mutacion_de_configuracion_activa(client, engine) -> None:
    settings_obj = engine.settings
    before = settings_obj.model_dump()

    for path, _ in GET_MATRIX:
        assert client.get(path).status_code == 200, path
    assert client.get("/api/trades/export.csv").status_code == 200
    assert (
        client.post(
            "/api/data/validate",
            json={
                "path": str(CSV_FIXTURE),
                "series_mode": "raw",
                "exclude_roll_sessions": True,
            },
        ).status_code
        == 200
    )

    response = client.post(
        "/api/backtest/run",
        json={
            "days": 3,
            "persist": False,
            "overrides": {"strategy": {"tp_rr": 1.25}},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overrides"] == {"strategy": {"tp_rr": 1.25}}
    assert body["config"]["strategy"]["tp_rr"] == 1.25

    assert engine.settings is settings_obj
    assert engine.settings.model_dump() == before
    assert engine.settings.strategy.tp_rr == before["strategy"]["tp_rr"]

    config = client.get("/api/config").json()
    assert config["settings"] == before
    assert config["defaults"] == Settings().model_dump()

    if ACTIVE_BYTES is not None:
        assert CONFIG_PATH.read_bytes() == ACTIVE_BYTES
    assert PROFILE.read_bytes() == PROFILE_BYTES
