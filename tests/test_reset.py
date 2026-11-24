"""Reinicio del historial local sin tocar el esquema ni los datos de mercado."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

import server.api as api_module
from server import reset as reset_cli
from server.api import router
from server.config import Settings
from server.db import Store
from server.engine import TradingEngine
from server.models import Position, TradeRecord


def _trade(trade_id: str = "t1", pnl: float = 2.0) -> TradeRecord:
    return TradeRecord(
        id=trade_id,
        symbol="MNQ",
        direction="long",
        qty=1,
        entry_ts=1000,
        entry_price=100.0,
        exit_ts=1060,
        exit_price=101.0,
        stop=99.0,
        target=103.0,
        pnl=pnl,
        gross_pnl=pnl,
        fees=0.0,
        r_multiple=1.0,
        risk_amount=2.0,
        signal_type="ORB",
        entry_reason="test",
        exit_reason="target",
        duration_sec=60,
    )


def _backtest(bt_id: str = "bt1") -> dict:
    return {
        "id": bt_id,
        "created_ts": 2000,
        "label": "backtest guardado",
        "data_source": "synthetic",
        "config": {"strategy": {}},
        "metrics": {"trades": 1},
        "trades": [],
        "equity": [],
    }


def test_clear_history_deletes_operational_tables_and_preserves_backtests(tmp_path):
    store = Store(tmp_path / "history.db")
    trade = _trade()
    try:
        store.insert_trade(trade.as_dict())
        store.insert_event("INFO", "test", "evento")
        store.insert_equity(1000, 25_000.0)
        store.set_kv("engine_state", {"position": None})
        store.save_backtest(_backtest())

        deleted = store.clear_history()

        assert deleted["trades"] == 1
        assert deleted["events"] == 1
        assert deleted["equity"] == 1
        assert deleted["kv"] == 1
        assert deleted["backtests"] == 1
        assert store.all_closed_trades() == []
        assert store.list_events() == []
        assert store.equity_series() == []
        assert store.get_kv("engine_state") is None
        assert store.latest_backtest()["id"] == "bt1"

        deleted = store.clear_history(delete_backtests=True)

        assert deleted["backtests"] == 1
        assert store.latest_backtest() is None
    finally:
        store.close()


def test_clear_history_reports_vacuum_failure_without_raising(tmp_path, monkeypatch):
    store = Store(tmp_path / "vacuum.db")
    try:
        store.insert_trade(_trade().as_dict())
        store.save_backtest(_backtest())

        def _fail_vacuum():
            raise sqlite3.OperationalError("database is locked")

        monkeypatch.setattr(store, "_vacuum", _fail_vacuum)

        deleted = store.clear_history(delete_backtests=True)

        assert deleted["trades"] == 1
        assert deleted["backtests"] == 1
        assert deleted["vacuum_error"] == "database is locked"
        assert store.all_closed_trades() == []
        assert store.latest_backtest() is None
    finally:
        store.close()


def _position() -> Position:
    return Position(
        id="open-position",
        symbol="MNQ",
        direction="long",
        qty=1,
        entry_price=100.0,
        entry_ts=1000,
        stop=99.0,
        target=103.0,
        initial_stop=99.0,
        risk_amount=2.0,
        signal_id="signal-open",
        signal_type="ORB",
        entry_reason="test",
    )


def test_engine_reset_stats_uses_configured_capital_without_saving(tmp_path, monkeypatch):
    def _unexpected_save(_):
        raise AssertionError("el reset de estadísticas no debe guardar configuración")

    monkeypatch.setattr("server.engine.save_settings", _unexpected_save)
    store = Store(tmp_path / "reset-stats.db")
    try:
        settings = Settings()
        settings.risk.initial_capital = 31_000.0
        before = settings.model_dump()
        store.insert_trade(_trade(pnl=125.0).as_dict())
        store.insert_equity(1060, 31_125.0)
        store.save_backtest(_backtest())
        engine = TradingEngine(store, settings)
        assert engine.equity == 31_125.0

        ok, message = asyncio.run(engine.reset_stats())

        assert ok is True
        assert "31.000" in message
        assert "backtests" not in message
        assert engine.equity == 31_000.0
        assert engine.settings.model_dump() == before
        assert engine.stats()["trades"] == 0
        assert store.all_closed_trades() == []
        assert store.equity_series() == []
        assert store.latest_backtest()["id"] == "bt1"
        state = store.get_kv("engine_state")
        assert state["equity"] == 31_000.0
        assert state["position"] is None
    finally:
        store.close()


def test_engine_reset_stats_deletes_backtests_only_when_requested(tmp_path):
    store = Store(tmp_path / "reset-backtests.db")
    try:
        store.save_backtest(_backtest())
        engine = TradingEngine(store, Settings())

        ok, message = asyncio.run(engine.reset_stats(delete_backtests=True))

        assert ok is True
        assert "backtests eliminados: 1" in message
        assert store.latest_backtest() is None
    finally:
        store.close()


def test_engine_reset_stats_rewinds_the_chart_and_feed(tmp_path):
    store = Store(tmp_path / "reset-chart.db")
    try:
        engine = TradingEngine(store, Settings())
        old_feed = engine.feed
        assert old_feed is not None
        engine.chart_history.append({"t": 1, "o": 1.0, "h": 1.0, "l": 1.0, "c": 1.0, "v": 1})
        engine.nq.append(object())
        engine.mnq.append(object())
        engine.es.append(object())
        engine.session_date = "2025-01-14"
        engine.last_tick_ts = 1
        old_feed.index = 42

        ok, _ = asyncio.run(engine.reset_stats())

        assert ok is True
        assert engine.feed is old_feed
        assert engine.feed.index == 0
        assert len(engine.chart_history) == 0
        assert engine.nq == []
        assert engine.mnq == []
        assert engine.es == []
        assert engine.session_date is None
        assert engine.last_tick_ts is None
        state = store.get_kv("engine_state")
        assert state["session_date"] is None
    finally:
        store.close()


def test_engine_reset_stats_clears_active_emergency(tmp_path):
    store = Store(tmp_path / "reset-emergency.db")
    try:
        engine = TradingEngine(store, Settings())
        engine.emergency("prueba", close_positions=False)
        assert engine.risk.emergency is True
        assert store.get_kv("engine_state")["emergency"] is True

        ok, message = asyncio.run(engine.reset_stats())

        assert ok is True
        assert "emergencia" in message.lower()
        assert engine.risk.emergency is False
        assert engine.risk.emergency_reason == ""
        assert engine.risk.emergency_ts is None
        state = store.get_kv("engine_state")
        assert state["emergency"] is False
        assert state["emergency_reason"] == ""
        assert state["emergency_ts"] is None
    finally:
        store.close()


def test_cli_reset_is_a_full_reset_and_deletes_backtests(tmp_path, monkeypatch, capsys):
    calls: dict[str, object] = {}

    class FakeStore:
        def __init__(self, path):
            calls["path"] = path

        def clear_history(self, *, delete_backtests: bool = False):
            calls["delete_backtests"] = delete_backtests
            return {"trades": 0, "events": 0, "equity": 0, "kv": 0, "backtests": 1}

        def close(self):
            calls["closed"] = True

    monkeypatch.setattr(reset_cli, "Store", FakeStore)
    monkeypatch.setattr(reset_cli, "BASE_DIR", tmp_path)
    monkeypatch.setattr(reset_cli, "CONFIG_PATH", tmp_path / "config.json")
    monkeypatch.setattr(reset_cli, "PROFILE_DIR", tmp_path / "profile")
    monkeypatch.setattr(reset_cli, "_server_is_running", lambda *_: False)
    monkeypatch.setattr(reset_cli, "_backup_database", lambda *_: None)
    monkeypatch.setattr(reset_cli, "_backup_file", lambda *_: False)
    monkeypatch.setattr(reset_cli, "_activate_real_csv", lambda *_: None)

    assert reset_cli.main(["--yes"]) == 0
    assert calls["delete_backtests"] is True
    assert calls["closed"] is True
    capsys.readouterr()


def test_engine_reset_stats_refuses_an_open_position(tmp_path):
    store = Store(tmp_path / "reset-open.db")
    try:
        engine = TradingEngine(store, Settings())
        engine.execution.position = _position()

        ok, message = asyncio.run(engine.reset_stats())

        assert ok is False
        assert "posición abierta" in message
        assert engine.execution.position is not None
        assert engine.equity == 25_000.0
    finally:
        store.close()


def test_reset_preview_reports_counts_without_deleting(tmp_path):
    store = Store(tmp_path / "api-reset-preview.db")
    try:
        store.insert_trade(_trade(pnl=50.0).as_dict())
        store.insert_equity(1060, 25_050.0)
        store.save_backtest(_backtest())
        engine = TradingEngine(store, Settings())
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state.engine = engine

        with TestClient(app) as client:
            default_response = client.get("/api/stats/reset/preview")
            assert default_response.status_code == 200, default_response.text
            default_body = default_response.json()
            assert default_body["delete_backtests"] is False
            assert default_body["requires_confirmation"] is False
            assert default_body["archive"] is False
            assert default_body["counts"]["backtests"] == 1

            response = client.get(
                "/api/stats/reset/preview?delete_backtests=true&archive=true"
            )

            assert response.status_code == 200, response.text
            body = response.json()
            assert set(body) == {
                "counts",
                "delete_backtests",
                "requires_confirmation",
                "archive",
            }
            assert set(body["counts"]) == {"trades", "events", "equity", "kv", "backtests"}
            assert body["delete_backtests"] is True
            assert body["requires_confirmation"] is True
            assert body["archive"] is True
            assert body["counts"]["trades"] == 1
            assert body["counts"]["equity"] == 1
            assert body["counts"]["backtests"] == 1
            assert store.all_closed_trades()
            assert store.latest_backtest() is not None
    finally:
        store.close()


def test_reset_stats_endpoint_survives_vacuum_failure(tmp_path, monkeypatch):
    store = Store(tmp_path / "api-reset-vacuum.db")
    try:
        store.insert_trade(_trade().as_dict())
        engine = TradingEngine(store, Settings())
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state.engine = engine
        monkeypatch.setattr(
            store,
            "_vacuum",
            lambda: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")),
        )

        with TestClient(app) as client:
            response = client.post("/api/stats/reset")

            assert response.status_code == 200, response.text
            assert "compactación" in response.json()["message"]
            assert client.get("/api/stats").json()["trades"] == 0
    finally:
        store.close()


def test_reset_stats_endpoint_requires_confirmation_before_deleting_backtests(tmp_path):
    store = Store(tmp_path / "api-reset-confirm.db")
    try:
        store.save_backtest(_backtest())
        engine = TradingEngine(store, Settings())
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state.engine = engine

        with TestClient(app) as client:
            response = client.post(
                "/api/stats/reset", json={"delete_backtests": True}
            )

            assert response.status_code == 409, response.text
            assert "confirmaci" in response.json()["detail"].lower()
            assert store.latest_backtest()["id"] == "bt1"

            response = client.post(
                "/api/stats/reset",
                json={"delete_backtests": True, "confirm": True},
            )
            assert response.status_code == 422, response.text
            assert store.latest_backtest()["id"] == "bt1"

            response = client.post(
                "/api/stats/reset",
                json={"delete_backtests": True, "confirm_delete_backtests": True},
            )

            assert response.status_code == 200, response.text
            assert store.latest_backtest() is None
    finally:
        store.close()


def test_reset_stats_endpoint_keeps_configuration_and_returns_message(tmp_path):
    store = Store(tmp_path / "api-reset.db")
    try:
        settings = Settings()
        settings.risk.initial_capital = 31_000.0
        before = settings.model_dump()
        store.insert_trade(_trade(pnl=50.0).as_dict())
        store.save_backtest(_backtest())
        engine = TradingEngine(store, settings)
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state.engine = engine

        with TestClient(app) as client:
            # Sin body se usa el default conservador; el frontend puede enviar
            # el flag explícito, pero no debe ser obligatorio.
            response = client.post("/api/stats/reset")

            assert response.status_code == 200, response.text
            body = response.json()
            assert body["ok"] is True
            assert "31.000" in body["message"]
            assert set(body) == {
                "ok",
                "message",
                "counts",
                "delete_backtests",
                "archive_path",
            }
            assert body["counts"]["backtests"] == 1
            assert body["delete_backtests"] is False
            assert body["archive_path"] is None
            assert engine.settings.model_dump() == before
            assert client.get("/api/stats").json()["trades"] == 0
            assert store.latest_backtest()["id"] == "bt1"
    finally:
        store.close()


def test_reset_stats_endpoint_deletes_backtests_only_when_requested(tmp_path):
    store = Store(tmp_path / "api-reset-backtests.db")
    try:
        store.save_backtest(_backtest())
        engine = TradingEngine(store, Settings())
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state.engine = engine

        with TestClient(app) as client:
            response = client.post(
                "/api/stats/reset",
                json={"delete_backtests": True, "confirm_delete_backtests": True},
            )

            assert response.status_code == 200, response.text
            assert "backtests eliminados: 1" in response.json()["message"]
            assert store.latest_backtest() is None
    finally:
        store.close()


def test_reset_stats_endpoint_archives_database_before_deleting(tmp_path, monkeypatch):
    monkeypatch.setattr(api_module, "BASE_DIR", tmp_path)
    store = Store(tmp_path / "archived.db")
    try:
        store.insert_trade(_trade().as_dict())
        store.save_backtest(_backtest())
        engine = TradingEngine(store, Settings())
        app = FastAPI()
        app.include_router(router, prefix="/api")
        app.state.engine = engine

        with TestClient(app) as client:
            response = client.post(
                "/api/stats/reset",
                json={
                    "delete_backtests": True,
                    "confirm_delete_backtests": True,
                    "archive": True,
                },
            )

            assert response.status_code == 200, response.text
            body = response.json()
            archive_dir = body["archive_path"]
            assert archive_dir
            assert body["counts"]["backtests"] == 1
            assert body["delete_backtests"] is True
            backup = Path(archive_dir) / "archived.db"
            assert backup.exists()
            with sqlite3.connect(backup) as conn:
                assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == 1
                assert conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0] == 1
            assert store.latest_backtest() is None
    finally:
        store.close()


def test_cli_reset_dry_run_shows_counts_without_touching_data(tmp_path, monkeypatch, capsys):
    database = tmp_path / "preview.db"
    store = Store(database)
    try:
        store.insert_trade(_trade().as_dict())
        store.save_backtest(_backtest())
    finally:
        store.close()

    monkeypatch.setattr(reset_cli, "DB_PATH", database)
    monkeypatch.setattr(reset_cli, "BASE_DIR", tmp_path)
    monkeypatch.setattr(reset_cli, "_server_is_running", lambda *_: False)
    monkeypatch.setattr(
        reset_cli, "_backup_database", lambda *_: (_ for _ in ()).throw(AssertionError("no debe archivar"))
    )

    assert reset_cli.main(["--dry-run"]) == 0

    body = json.loads(capsys.readouterr().out)
    assert body["dry_run"] is True
    assert body["counts"]["trades"] == 1
    assert body["counts"]["backtests"] == 1
    assert body["delete_backtests"] is True
    assert body["requires_confirmation"] is True
    assert not (tmp_path / "backups").exists()
    reopened = Store(database)
    try:
        assert reopened.all_closed_trades()
        assert reopened.latest_backtest()["id"] == "bt1"
    finally:
        reopened.close()
