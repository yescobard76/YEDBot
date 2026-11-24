"""Atomicidad entre una corrida persistida y su entrada en el ledger."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import api as api_module
from server.api import router
from server.config import Settings
from server.db import Store
from server.experiments import ExperimentLedger, LedgerError, ledger_record_sha256


def _app(store: Store) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.engine = SimpleNamespace(settings=Settings(), store=store)
    return app


def _rows(store: Store, table: str) -> list[dict]:
    with store._lock:
        return [dict(row) for row in store._conn.execute(f"SELECT * FROM {table}")]


def _result(result_id: str = "outbox-result") -> dict:
    return {
        "id": result_id,
        "created_ts": 1_800_000_100_000,
        "label": "corrida con outbox",
        "data_source": "synthetic",
        "dataset": {"id": "dataset-outbox", "kind": "synthetic"},
        "config": {"days": 3},
        "metrics": {
            "trades": 0,
            "net_profit": 0.0,
            "max_drawdown_pct": 0.0,
            "profit_factor": None,
        },
        "trades": [],
        "equity": [{"ts": 1, "equity": 25_000.0}],
        "experiment": {
            "schema_version": "experiment-v1",
            "config_sha256": "a" * 64,
            "code_sha256": "b" * 64,
            "dataset_sha256": "c" * 64,
            "config_hash_algorithm": "sha256-canonical-config-v1",
            "code_hash_algorithm": "sha256-tree-v1",
            "dataset_hash_algorithm": "sha256-dataset-source-v1",
            "data_source": "synthetic",
            "dataset_id": "dataset-outbox",
            "selected_id": "selected-outbox",
            "sessions": 3,
        },
    }


def test_outbox_insert_failure_rolls_back_the_whole_run(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "outbox-rollback.db")
    try:
        def _fail_outbox(*args, **kwargs):
            raise RuntimeError("no se pudo crear el outbox")

        monkeypatch.setattr(store, "_insert_ledger_outbox", _fail_outbox)

        with pytest.raises(RuntimeError, match="outbox"):
            store.save_backtest(_result(), hypothesis_id="H-OUTBOX")

        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
        assert _rows(store, "backtest_ledger_outbox") == []
    finally:
        store.close()


def test_ledger_failure_leaves_a_visible_pending_run_and_retry_finishes_it(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "outbox-api.db")
    ledger_path = tmp_path / "ledger.jsonl"
    payload = {
        "days": 3,
        "persist": True,
        "hypothesis_id": "H-API-1",
        "label": "fallo y reintento",
    }
    try:

        class _FailingLedger:
            def record_backtest(self, *args, **kwargs):
                raise LedgerError("ledger no disponible")

        monkeypatch.setattr(api_module, "ExperimentLedger", _FailingLedger)

        with TestClient(_app(store)) as client:
            response = client.post("/api/backtest/run", json=payload)

            assert response.status_code == 200, response.text
            body = response.json()
            run_id = body["backtest_run_id"]
            assert run_id
            assert body["ledger_status"] == "pending"
            assert body["hypothesis_id"] == "H-API-1"
            assert body["ledger_event_id"] is None
            assert body["ledger_event_sha256"] is None
            assert "ledger no disponible" in body["ledger_error"]
            assert "ledger" not in body
            assert len(_rows(store, "backtest_runs")) == 1
            assert len(_rows(store, "backtest_results")) == 1

            outbox = store.get_ledger_outbox(run_id)
            assert outbox is not None
            assert outbox["status"] == "pending"
            assert outbox["attempts"] == 1

            status = client.get(f"/api/backtest/ledger/{run_id}")
            assert status.status_code == 200, status.text
            assert status.json()["status"] == "pending"
            assert status.json()["ledger_event_id"] is None
            assert status.json()["ledger_event_sha256"] is None

            # El historial sigue mostrando la corrida: no queda invisible.
            history = client.get("/api/backtest/runs")
            assert history.status_code == 200, history.text
            assert history.json()["total"] == 1
            item = history.json()["items"][0]
            assert item["id"] == run_id
            assert item["ledger_status"] == "pending"
            assert item["hypothesis_id"] == "H-API-1"
            assert item["ledger_event_id"] is None
            assert item["ledger_event_sha256"] is None
            assert "ledger no disponible" in item["ledger_error"]
            detail = client.get(f"/api/backtest/runs/{run_id}")
            assert detail.status_code == 200, detail.text
            detail_run = detail.json()["run"]
            assert detail_run["ledger_status"] == "pending"
            assert detail_run["hypothesis_id"] == "H-API-1"
            assert detail_run["ledger_event_id"] is None
            assert detail_run["ledger_event_sha256"] is None
            assert "ledger no disponible" in detail_run["ledger_error"]
            assert "ledger" not in detail_run
            latest = client.get("/api/backtest/latest")
            assert latest.status_code == 200, latest.text
            assert latest.json()["result"]["ledger_status"] == "pending"
            assert latest.json()["result"]["hypothesis_id"] == "H-API-1"
            assert latest.json()["result"]["ledger_event_id"] is None
            assert "ledger no disponible" in latest.json()["result"]["ledger_error"]
            result_detail = client.get(f"/api/backtest/results/{body['id']}")
            assert result_detail.status_code == 200, result_detail.text
            assert result_detail.json()["ledger_status"] == "pending"
            assert result_detail.json()["ledger_event_id"] is None

            monkeypatch.setattr(
                api_module,
                "ExperimentLedger",
                lambda: ExperimentLedger(ledger_path),
            )
            retried = client.post("/api/backtest/ledger/retry")

            assert retried.status_code == 200, retried.text
            retried_body = retried.json()
            assert retried_body["ok"] is True
            assert retried_body["retried"] == 1
            assert retried_body["items"][0]["backtest_run_id"] == run_id
            assert retried_body["items"][0]["status"] == "sent"

            sent = client.get(f"/api/backtest/ledger/{run_id}")
            assert sent.status_code == 200, sent.text
            sent_body = sent.json()
            assert sent_body["status"] == "sent"
            assert sent_body["attempts"] == 2
            assert sent_body["ledger_event_id"]
            assert len(sent_body["ledger_event_sha256"]) == 64

            sent_history = client.get("/api/backtest/runs").json()["items"][0]
            assert sent_history["ledger_event_id"] == sent_body["ledger_event_id"]
            assert (
                sent_history["ledger_event_sha256"]
                == sent_body["ledger_event_sha256"]
            )
            sent_detail = client.get(f"/api/backtest/runs/{run_id}").json()["run"]
            assert sent_detail["ledger_event_id"] == sent_body["ledger_event_id"]
            assert (
                sent_detail["ledger_event_sha256"]
                == sent_body["ledger_event_sha256"]
            )
            assert sent_detail["ledger_error"] is None
            assert "ledger" not in sent_detail
            sent_latest = client.get("/api/backtest/latest").json()["result"]
            assert sent_latest["ledger_event_id"] == sent_body["ledger_event_id"]
            sent_result = client.get(
                f"/api/backtest/results/{body['id']}"
            ).json()
            assert sent_result["ledger_event_sha256"] == sent_body["ledger_event_sha256"]

            # Un segundo reintento no duplica la entrada del ledger.
            again = client.post("/api/backtest/ledger/retry")
            assert again.status_code == 200, again.text
            assert again.json()["retried"] == 0

        records = ExperimentLedger(ledger_path).runs("H-API-1")
        assert len(records) == 1
        record = records[0]
        assert record["run_id"] == run_id
        assert record["result_id"] == body["id"]
        assert sent_body["ledger_event_id"] == record["event_id"]
        assert sent_body["ledger_event_sha256"] == ledger_record_sha256(record)
    finally:
        store.close()


def test_idempotent_replay_flushes_pending_without_rerunning_simulation(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "outbox-idempotent.db")
    ledger_path = tmp_path / "ledger-idempotent.jsonl"
    payload = {
        "days": 3,
        "persist": True,
        "hypothesis_id": "H-IDEMPOTENT-API",
        "idempotency_key": "ledger-retry-key",
    }
    try:

        class _FailingLedger:
            def record_backtest(self, *args, **kwargs):
                raise LedgerError("ledger caído")

        monkeypatch.setattr(api_module, "ExperimentLedger", _FailingLedger)
        with TestClient(_app(store)) as client:
            first = client.post("/api/backtest/run", json=payload)
            assert first.status_code == 200, first.text
            assert first.json()["ledger_status"] == "pending"
            run_id = first.json()["backtest_run_id"]

            monkeypatch.setattr(
                api_module,
                "run_backtest",
                lambda *args, **kwargs: pytest.fail("no debe repetir la simulación"),
            )
            second = client.post("/api/backtest/run", json=payload)
            assert second.status_code == 200, second.text
            assert second.json()["backtest_run_id"] == run_id
            assert second.json()["ledger_status"] == "pending"

            monkeypatch.setattr(
                api_module,
                "ExperimentLedger",
                lambda: ExperimentLedger(ledger_path),
            )
            third = client.post("/api/backtest/run", json=payload)
            assert third.status_code == 200, third.text
            assert third.json()["backtest_run_id"] == run_id
            assert third.json()["ledger_status"] == "sent"
            assert third.json()["ledger_event_id"]
            assert len(third.json()["ledger_event_sha256"]) == 64

        assert len(_rows(store, "backtest_runs")) == 1
        assert len(_rows(store, "backtest_ledger_outbox")) == 1
        outbox = store.get_ledger_outbox(run_id)
        assert outbox["status"] == "sent"
        records = ExperimentLedger(ledger_path).runs("H-IDEMPOTENT-API")
        assert len(records) == 1
        assert outbox["ledger_event_id"] == records[0]["event_id"]
        assert outbox["ledger_event_sha256"] == ledger_record_sha256(records[0])
    finally:
        store.close()


def test_runs_without_outbox_keep_the_same_flat_ledger_contract(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "no-outbox.db")
    try:
        store.save_backtest(_result("without-outbox"))
        with TestClient(_app(store)) as client:
            item = client.get("/api/backtest/runs").json()["items"][0]
            detail = client.get(f"/api/backtest/runs/{item['id']}").json()["run"]
            latest = client.get("/api/backtest/latest").json()["result"]
            result_detail = client.get(
                f"/api/backtest/results/{latest['id']}"
            ).json()

        for payload in (item, detail, latest, result_detail):
            assert payload["ledger_status"] is None
            assert payload["hypothesis_id"] is None
            assert payload["ledger_event_id"] is None
            assert payload["ledger_event_sha256"] is None
            assert payload["ledger_error"] is None
        assert "ledger" not in detail
    finally:
        store.close()


def test_ledger_record_is_idempotent_for_a_persisted_run_id() -> None:
    # Esta prueba no requiere SQLite: protege el caso en que el append llegó
    # a disco pero el proceso falló antes de marcar el outbox como enviado.
    import hashlib
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        ledger = ExperimentLedger(Path(directory) / "ledger.jsonl")
        first = ledger.record_backtest(
            _result(), hypothesis_id="H-IDEMPOTENT", run_id="run-persistido"
        )
        second = ledger.record_backtest(
            _result(), hypothesis_id="H-IDEMPOTENT", run_id="run-persistido"
        )

        assert second == first
        assert len(ledger.runs("H-IDEMPOTENT")) == 1
        assert first["run_id"] == "run-persistido"
        assert first["result_id"] == "outbox-result"
        line = ledger.path.read_text(encoding="utf-8").splitlines()[0]
        assert ledger_record_sha256(first) == hashlib.sha256(
            line.encode("utf-8")
        ).hexdigest()
