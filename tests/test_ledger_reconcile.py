"""Conciliación de corridas ``sent`` anteriores a la migración v5."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import api as api_module
from server.api import router
from server.config import Settings
from server.db import Store
from server.experiments import (
    ExperimentLedger,
    ledger_record_sha256,
    reconcile_ledger_links,
)


def _app(store: Store) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.engine = SimpleNamespace(settings=Settings(), store=store)
    return app


def _result(result_id: str) -> dict:
    return {
        "id": result_id,
        "created_ts": 1_800_000_100_000,
        "label": "corrida previa a v5",
        "data_source": "synthetic",
        "dataset": {"id": "dataset-reconcile", "kind": "synthetic"},
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
            "dataset_id": "dataset-reconcile",
            "selected_id": "selected-reconcile",
            "sessions": 3,
        },
    }


def _insert_sent_run(
    store: Store,
    run_id: str,
    result_id: str,
    *,
    hypothesis_id: str = "H-RECON",
    attempts: int = 1,
) -> None:
    """Simula una fila ``sent`` creada antes de que existiera el vínculo."""
    created_ts = 1_800_000_000_000
    with store._lock:
        store._conn.execute(
            "INSERT INTO backtest_runs ("
            "id, created_ts, kind, label, data_source, result_count"
            ") VALUES (?, ?, 'single', ?, 'synthetic', 0)",
            (run_id, created_ts, f"corrida {run_id}"),
        )
        store._conn.execute(
            "INSERT INTO backtest_ledger_outbox ("
            "backtest_run_id, result_id, hypothesis_id, status, attempts, "
            "created_ts, updated_ts"
            ") VALUES (?, ?, ?, 'sent', ?, ?, ?)",
            (run_id, result_id, hypothesis_id, attempts, created_ts, created_ts),
        )
        store._conn.commit()


def test_reconcile_links_a_pre_v5_sent_run_with_its_ledger_entry(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "reconcile.db")
    ledger_path = tmp_path / "ledger.jsonl"
    try:
        _insert_sent_run(store, "run-a", "result-a", attempts=3)
        record = ExperimentLedger(ledger_path).record_backtest(
            _result("result-a"), hypothesis_id="H-RECON", run_id="run-a"
        )
        monkeypatch.setattr(
            api_module, "ExperimentLedger", lambda: ExperimentLedger(ledger_path)
        )

        with TestClient(_app(store)) as client:
            response = client.post("/api/backtest/ledger/reconcile")

            assert response.status_code == 200, response.text
            body = response.json()
            assert body["ok"] is True
            assert body["scanned"] == 1
            assert body["linked"] == 1
            assert body["updated"] == 1
            assert body["unresolved"] == []
            assert body["unresolved_count"] == 0
            assert body["ledger_records"] == 1

            outbox = store.get_ledger_outbox("run-a")
            assert outbox["status"] == "sent"
            assert outbox["attempts"] == 3, "conciliar no es un intento de envío"
            assert outbox["ledger_event_id"] == record["event_id"]
            assert outbox["ledger_event_sha256"] == ledger_record_sha256(record)

            status = client.get("/api/backtest/ledger/run-a")
            assert status.status_code == 200, status.text
            assert status.json()["ledger_event_id"] == record["event_id"]

            detail = client.get("/api/backtest/runs/run-a")
            assert detail.status_code == 200, detail.text
            detail_run = detail.json()["run"]
            assert detail_run["ledger_status"] == "sent"
            assert detail_run["hypothesis_id"] == "H-RECON"
            assert detail_run["ledger_event_id"] == record["event_id"]
            assert (
                detail_run["ledger_event_sha256"]
                == ledger_record_sha256(record)
            )
            assert detail_run["ledger_error"] is None
            assert "ledger" not in detail_run

            again = client.post("/api/backtest/ledger/reconcile")
            assert again.status_code == 200, again.text
            assert again.json()["scanned"] == 0
            assert again.json()["linked"] == 0

        # La conciliación enlaza; nunca escribe una entrada nueva.
        assert len(ExperimentLedger(ledger_path).records()) == 1
    finally:
        store.close()


def test_reconcile_reports_a_run_without_ledger_entry(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "missing.db")
    ledger_path = tmp_path / "empty-ledger.jsonl"
    try:
        _insert_sent_run(store, "run-missing", "result-missing")
        monkeypatch.setattr(
            api_module, "ExperimentLedger", lambda: ExperimentLedger(ledger_path)
        )

        with TestClient(_app(store)) as client:
            response = client.post("/api/backtest/ledger/reconcile")

            assert response.status_code == 200, response.text
            body = response.json()
            assert body["ok"] is False
            assert body["scanned"] == 1
            assert body["linked"] == 0
            assert body["updated"] == 0
            assert body["unresolved_count"] == 1
            item = body["unresolved"][0]
            assert item["backtest_run_id"] == "run-missing"
            assert item["result_id"] == "result-missing"
            assert item["hypothesis_id"] == "H-RECON"
            assert item["reason"] == "ledger_entry_missing"
            assert item["candidate_event_ids"] == []

            outbox = store.get_ledger_outbox("run-missing")
            assert outbox["status"] == "sent"
            assert outbox["attempts"] == 1
            assert outbox["ledger_event_id"] is None
            assert outbox["ledger_event_sha256"] is None

            # El estado previo a v5 se ve como sent sin vínculo, no como pending.
            detail = client.get("/api/backtest/runs/run-missing")
            assert detail.status_code == 200, detail.text
            detail_run = detail.json()["run"]
            assert detail_run["ledger_status"] == "sent"
            assert detail_run["ledger_event_id"] is None
            assert detail_run["ledger_event_sha256"] is None
    finally:
        store.close()


def test_reconcile_does_not_choose_between_ambiguous_entries(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "ambiguous.db")
    ledger_path = tmp_path / "ledger-ambiguous.jsonl"
    try:
        ledger = ExperimentLedger(ledger_path)
        by_run = ledger.append(
            "experiment.completed",
            hypothesis_id="H-RECON",
            run_id="run-ambiguous",
            result_id="result-other",
        )
        by_result = ledger.append(
            "experiment.completed",
            hypothesis_id="H-RECON",
            run_id="run-other",
            result_id="result-ambiguous",
        )
        _insert_sent_run(store, "run-ambiguous", "result-ambiguous")
        monkeypatch.setattr(
            api_module, "ExperimentLedger", lambda: ExperimentLedger(ledger_path)
        )

        with TestClient(_app(store)) as client:
            body = client.post("/api/backtest/ledger/reconcile").json()

        assert body["ok"] is False
        assert body["linked"] == 0
        assert body["unresolved_count"] == 1
        item = body["unresolved"][0]
        assert item["reason"] == "ledger_entry_ambiguous"
        assert item["candidate_event_ids"] == [
            by_run["event_id"],
            by_result["event_id"],
        ]
        outbox = store.get_ledger_outbox("run-ambiguous")
        assert outbox["ledger_event_id"] is None
        assert outbox["ledger_event_sha256"] is None
    finally:
        store.close()


def test_reconcile_accepts_a_legacy_entry_that_used_result_id_as_run_id(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "legacy.db")
    ledger_path = tmp_path / "ledger-legacy.jsonl"
    try:
        record = ExperimentLedger(ledger_path).append(
            "experiment.completed",
            hypothesis_id="H-RECON",
            run_id="result-legacy",
            result_id=None,
        )
        _insert_sent_run(store, "run-actual", "result-legacy")
        monkeypatch.setattr(
            api_module, "ExperimentLedger", lambda: ExperimentLedger(ledger_path)
        )

        with TestClient(_app(store)) as client:
            body = client.post("/api/backtest/ledger/reconcile").json()

        assert body["ok"] is True
        assert body["linked"] == 1
        outbox = store.get_ledger_outbox("run-actual")
        assert outbox["ledger_event_id"] == record["event_id"]
        assert outbox["ledger_event_sha256"] == ledger_record_sha256(record)
    finally:
        store.close()


def test_reconcile_does_not_reuse_an_event_already_linked_to_another_run(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "claimed.db")
    ledger_path = tmp_path / "ledger-claimed.jsonl"
    record = {
        "schema_version": "experiment-ledger-v1",
        "event": "experiment.completed",
        "event_id": "event-already-used",
        "created_at": "2026-01-01T00:00:00Z",
        "hypothesis_id": "H-RECON",
        "run_id": "run-y",
        "result_id": "result-y",
    }
    ledger_path.write_text(
        json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    try:
        _insert_sent_run(store, "run-x", "result-x")
        with store._lock:
            store._conn.execute(
                "UPDATE backtest_ledger_outbox SET ledger_event_id = ?, "
                "ledger_event_sha256 = ? WHERE backtest_run_id = ?",
                (
                    "event-already-used",
                    ledger_record_sha256(record),
                    "run-x",
                ),
            )
            store._conn.commit()
        _insert_sent_run(store, "run-y", "result-y")
        monkeypatch.setattr(
            api_module, "ExperimentLedger", lambda: ExperimentLedger(ledger_path)
        )

        with TestClient(_app(store)) as client:
            body = client.post("/api/backtest/ledger/reconcile").json()

        assert body["scanned"] == 1
        assert body["linked"] == 0
        item = body["unresolved"][0]
        assert item["backtest_run_id"] == "run-y"
        assert item["reason"] == "ledger_event_already_linked"
        assert item["candidate_event_ids"] == ["event-already-used"]
        assert store.get_ledger_outbox("run-y")["ledger_event_id"] is None
    finally:
        store.close()


def test_reconcile_reports_an_unreadable_ledger_without_linking(
    tmp_path: Path, monkeypatch
) -> None:
    store = Store(tmp_path / "corrupt.db")
    ledger_path = tmp_path / "ledger-corrupt.jsonl"
    ledger_path.write_text("{no es json}\n", encoding="utf-8")
    try:
        _insert_sent_run(store, "run-corrupt", "result-corrupt")
        monkeypatch.setattr(
            api_module, "ExperimentLedger", lambda: ExperimentLedger(ledger_path)
        )

        with TestClient(_app(store)) as client:
            response = client.post("/api/backtest/ledger/reconcile")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is False
        assert "corrupto" in body["error"]
        assert body["linked"] == 0
        assert body["unresolved_count"] == 1
        item = body["unresolved"][0]
        assert item["backtest_run_id"] == "run-corrupt"
        assert item["reason"] == "ledger_unreadable"
        assert store.get_ledger_outbox("run-corrupt")["ledger_event_id"] is None
    finally:
        store.close()


def test_reconcile_reports_entries_without_event_id() -> None:
    outcome = reconcile_ledger_links(
        [
            {
                "backtest_run_id": "run-noevent",
                "result_id": "result-noevent",
                "hypothesis_id": "H-RECON",
            }
        ],
        [
            {
                "event": "experiment.completed",
                "hypothesis_id": "H-RECON",
                "run_id": "run-noevent",
                "result_id": "result-noevent",
            }
        ],
    )

    assert outcome["linked"] == []
    assert outcome["unresolved"][0]["reason"] == "ledger_entry_without_event_id"
