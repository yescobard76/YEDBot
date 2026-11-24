"""Control del motor: reanudar exige una tarea de replay viva."""

from __future__ import annotations

import pytest

from server.config import Settings
from server.db import Store
from server.engine import TradingEngine


class _TaskStub:
    def __init__(self, done: bool) -> None:
        self._done = done

    def done(self) -> bool:
        return self._done


@pytest.fixture
def engine(tmp_path):
    store = Store(tmp_path / "control.db")
    instance = TradingEngine(store, Settings())
    yield instance
    store.close()


def test_resume_rejects_without_loop_task(engine: TradingEngine) -> None:
    engine.status = "paused"
    engine._task = None

    ok, message = engine.resume()

    assert ok is False
    assert "Iniciar" in message
    assert engine.status == "stopped"
    assert not any("Motor reanudado" in e["message"] for e in engine.store.list_events(limit=20))


def test_resume_rejects_when_loop_task_finished(engine: TradingEngine) -> None:
    engine.status = "paused"
    engine._task = _TaskStub(done=True)

    ok, message = engine.resume()

    assert ok is False
    assert "Iniciar" in message
    assert engine.status == "stopped"
    assert not any("Motor reanudado" in e["message"] for e in engine.store.list_events(limit=20))


def test_resume_accepts_live_loop_task(engine: TradingEngine) -> None:
    engine.status = "paused"
    engine._task = _TaskStub(done=False)

    ok, message = engine.resume()

    assert ok is True
    assert message == "Motor reanudado"
    assert engine.status == "running"
    assert any("Motor reanudado" in e["message"] for e in engine.store.list_events(limit=20))
