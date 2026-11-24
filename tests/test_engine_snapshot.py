"""Pruebas de integración del motor sin arrancar el servidor."""

from __future__ import annotations

import asyncio
from datetime import date

from server.config import Settings
from server.db import Store
from server.engine import TradingEngine
from server.market.synthetic import build_session
from server.strategy.strategy import Assess
from server.timeutil import et_date_str


def test_engine_snapshot_contract(tmp_path):
    settings = Settings()
    store = Store(tmp_path / "snapshot.db")
    engine = TradingEngine(store, settings)
    day = date(2025, 6, 3)
    data = build_session(day, settings)
    engine.mnq = data["MNQ"][:40]
    engine.nq = data["NQ"][:40]
    engine.es = data["ES"][:40]
    engine.session_date = et_date_str(engine.nq[-1].ts)
    engine.last_tick_ts = engine.nq[-1].ts

    snap = engine.snapshot()
    assert snap["quotes"]["MNQ"]["last"] > 0
    assert snap["quotes"]["NQ"]["last"] > snap["quotes"]["ES"]["last"]
    assert len(snap["chart"]["bars"]) == 40
    assert [p["key"] for p in snap["assessment"]["phases"]] == [
        "session",
        "opening_range",
        "breakout",
        "smt",
        "retest",
        "entry",
        "management",
    ]
    assert snap["risk"]["initial_capital"] == settings.risk.initial_capital
    assert "equity_curve" in snap["stats"]
    # El estado serializado debe ser JSON-compatible (FastAPI lo envía tal cual).
    import json

    json.dumps(snap)
    store.close()


def test_live_mode_is_refused_without_adapter(tmp_path):
    settings = Settings(mode="live")
    store = Store(tmp_path / "live.db")
    engine = TradingEngine(store, settings)
    ok, message = asyncio.run(engine.start())
    assert ok is False
    assert "LIVE" in message
    store.close()


def test_simulated_mode_is_refused_without_explicit_opt_in(tmp_path, monkeypatch):
    monkeypatch.delenv("YED_ALLOW_SIMULATED", raising=False)
    settings = Settings()
    store = Store(tmp_path / "simulated.db")
    engine = TradingEngine(store, settings)
    ok, message = asyncio.run(engine.start())
    assert ok is False
    assert "sintético" in message
    assert engine.status == "stopped"
    store.close()


def test_phase_timeline_keeps_confirmed_smt_after_setup_expiry(tmp_path):
    settings = Settings()
    store = Store(tmp_path / "timeline.db")
    engine = TradingEngine(store, settings)
    engine.session_date = "2025-01-28"

    def phases(smt_status, smt_detail, retest_status, retest_detail):
        return [
            {"key": "session", "label": "Sesión iniciada", "status": "confirmed", "detail": "Sesión en curso", "ts": 100},
            {"key": "opening_range", "label": "Opening Range completado", "status": "confirmed", "detail": "H 21319.50 · L 21159.50", "ts": 200},
            {"key": "breakout", "label": "Ruptura detectada", "status": "confirmed", "detail": "Alcista", "ts": 300},
            {"key": "smt", "label": "Divergencia SMT", "status": smt_status, "detail": smt_detail, "ts": 400 if smt_status == "confirmed" else None},
            {"key": "retest", "label": "Retesteo", "status": retest_status, "detail": retest_detail, "ts": 500 if retest_status == "expired" else None},
            {"key": "entry", "label": "Confirmación de entrada", "status": "pending", "detail": "Sin señal", "ts": None},
            {"key": "management", "label": "Gestión de operación", "status": "waiting", "detail": "En espera de ejecución", "ts": None},
        ]

    engine._remember(Assess(phases=phases("confirmed", "Alcista · NQ vs ES", "in_progress", "Esperando retesteo")))
    engine._remember(Assess(phases=phases("pending", "Esperando divergencia NQ/ES", "expired", "Setup expirado")))

    timeline = {phase["key"]: phase for phase in engine.snapshot()["assessment"]["phases"]}
    assert timeline["smt"]["status"] == "confirmed"
    assert timeline["smt"]["detail"] == "Alcista · NQ vs ES"
    assert timeline["smt"]["ts"] == 400
    assert timeline["retest"]["status"] == "expired"
    assert timeline["retest"]["ts"] == 500
    store.close()
