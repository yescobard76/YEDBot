"""Persistencia de backtests: corridas nuevas, lectura y reset."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server import api as api_module
from server.api import router
from server.config import Settings
from server.db import Store

ROOT = Path(__file__).resolve().parents[1]
LEGACY_FIXTURE = ROOT / "tests" / "fixtures" / "db" / "v1_real_yedbot.db"


def _app(store: Store, settings: Settings | None = None) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.engine = SimpleNamespace(settings=settings or Settings(), store=store)
    return app


def _rows(store: Store, table: str) -> list[dict]:
    with store._lock:
        return [dict(row) for row in store._conn.execute(f"SELECT * FROM {table}")]


def _single_result(result_id: str = "result-1") -> dict:
    return {
        "id": result_id,
        "created_ts": 1_800_000_000_000,
        "label": "single persistido",
        "data_source": "synthetic",
        "config": {"days": 3},
        "metrics": {
            "trades": 1,
            "net_profit": 50.0,
            "max_drawdown_pct": 1.5,
            "profit_factor": 2.0,
            "equity_curve": [{"ts": 1, "equity": 25_050.0}],
        },
        "trades": [{"id": "t1", "pnl": 50.0}],
        "equity": [{"ts": 1, "equity": 25_050.0}],
    }


def test_single_run_writes_new_tables_and_reads_legacy_projection(tmp_path: Path) -> None:
    store = Store(tmp_path / "single.db")
    try:
        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/run",
                json={"days": 3, "persist": True, "label": "single nuevo"},
            )
        assert response.status_code == 200, response.text
        result = response.json()

        runs = _rows(store, "backtest_runs")
        results = _rows(store, "backtest_results")
        assert len(runs) == 1
        assert len(results) == 1
        run = runs[0]
        stored = results[0]
        assert result["backtest_run_id"] == run["id"]
        assert run["kind"] == "single"
        assert run["result_count"] == 1
        assert run["primary_result_id"] == result["id"]
        assert run["id"] != result["id"]
        assert run["payload_json"]
        assert stored["id"] == result["id"]
        assert stored["backtest_run_id"] == run["id"]
        assert stored["result_key"] == "single"
        assert stored["payload_json"]
        assert json.loads(stored["payload_json"])["id"] == result["id"]
        assert "trades" not in json.loads(stored["metrics_json"])
        assert "equity_curve" not in json.loads(stored["metrics_json"])
        assert _rows(store, "backtests") == []

        latest = store.latest_backtest()
        assert latest is not None
        assert latest["id"] == result["id"]
        assert set(latest) == {
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
        assert store.get_backtest(result["id"]) == latest
    finally:
        store.close()


def test_single_persist_false_does_not_write_or_link_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "single-no-persist.db")
    try:
        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/run",
                json={"days": 3, "persist": False, "label": "single sin guardar"},
            )
        assert response.status_code == 200, response.text
        assert response.json()["backtest_run_id"] is None
        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
        assert store.latest_backtest() is None
    finally:
        store.close()


def test_duplicate_result_id_is_rejected_without_extra_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "duplicate.db")
    try:
        store.save_backtest(_single_result("same-result"))

        with pytest.raises(ValueError, match="ya guardados"):
            store.save_backtest(_single_result("same-result"))

        assert len(_rows(store, "backtest_runs")) == 1
        assert len(_rows(store, "backtest_results")) == 1
        assert store.get_backtest("same-result")["id"] == "same-result"
    finally:
        store.close()


def test_failed_variant_rolls_back_run_and_previous_results(tmp_path: Path) -> None:
    store = Store(tmp_path / "rollback.db")
    try:
        valid = _single_result("valid")
        valid["variant"] = "orb"
        invalid = _single_result("invalid")
        invalid["variant"] = "full"
        invalid["metrics"]["trades"] = "no-es-un-entero"

        with pytest.raises(ValueError, match="métricas"):
            store.save_backtest([valid, invalid], kind="variants")

        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
    finally:
        store.close()


def test_invalid_single_response_is_not_persisted(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "invalid-single.db")
    monkeypatch.setattr("server.api.run_backtest", lambda *args, **kwargs: {"id": "invalid"})
    try:
        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/run",
                json={"days": 3, "persist": True},
            )

        assert response.status_code == 400
        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
    finally:
        store.close()


def test_invalid_variants_response_is_not_persisted(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "invalid-variants.db")
    monkeypatch.setattr(
        "server.api.run_variants",
        lambda *args, **kwargs: [{"id": "invalid", "data_source": "synthetic"}],
    )
    try:
        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/run",
                json={"days": 3, "compare": True, "persist": True},
            )

        assert response.status_code == 400
        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
    finally:
        store.close()


def test_invalid_presets_response_is_not_persisted(tmp_path: Path, monkeypatch) -> None:
    store = Store(tmp_path / "invalid-presets.db")
    invalid = {
        "created_ts": 1,
        "data_source": "synthetic",
        "is_synthetic": True,
        "dataset": None,
        "dataset_id": None,
        "days_requested": 3,
        "sessions": 4,
        "overrides": {},
        "base_config": {},
        "default_presets": False,
        "preset_keys": ["baseline"],
        "comparison": [],
        "sample": {},
    }
    monkeypatch.setattr("server.api.run_presets", lambda *args, **kwargs: invalid)
    try:
        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/presets",
                json={"days": 3, "presets": ["baseline"], "persist": True},
            )

        assert response.status_code == 400
        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
    finally:
        store.close()


def test_idempotency_key_reuses_single_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "idempotent-single.db")
    payload = {
        "days": 3,
        "persist": True,
        "label": "single idempotente",
        "idempotency_key": "single-key",
    }
    try:
        with TestClient(_app(store)) as client:
            first = client.post("/api/backtest/run", json=payload)
            monkeypatch.setattr(
                api_module,
                "run_backtest",
                lambda *args, **kwargs: pytest.fail("no debe repetir la simulación"),
            )
            second = client.post("/api/backtest/run", json=payload)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json() == second.json()
        assert first.json()["backtest_run_id"] == second.json()["backtest_run_id"]
        runs = _rows(store, "backtest_runs")
        results = _rows(store, "backtest_results")
        assert len(runs) == 1
        assert runs[0]["idempotency_key"] == "single-key"
        assert len(results) == 1
        assert first.json()["id"] == results[0]["id"]
        assert second.json()["id"] == results[0]["id"]
    finally:
        store.close()


def test_idempotency_key_reuses_variants_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "idempotent-variants.db")
    payload = {
        "days": 3,
        "compare": True,
        "persist": True,
        "idempotency_key": "variants-key",
    }
    try:
        with TestClient(_app(store)) as client:
            first = client.post("/api/backtest/run", json=payload)
            monkeypatch.setattr(
                api_module,
                "run_variants",
                lambda *args, **kwargs: pytest.fail("no debe repetir la simulación"),
            )
            second = client.post("/api/backtest/run", json=payload)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json() == second.json()
        assert first.json()["backtest_run_id"] == second.json()["backtest_run_id"]
        assert len(_rows(store, "backtest_runs")) == 1
        saved = _rows(store, "backtest_results")
        assert len(saved) == 4
        stored_ids = {row["variant"]: row["id"] for row in saved}
        first_ids = {item["variant"]: item["id"] for item in first.json()["variants"]}
        retry_ids = {item["variant"]: item["id"] for item in second.json()["variants"]}
        assert first_ids == stored_ids
        assert retry_ids == stored_ids
    finally:
        store.close()


def test_idempotency_key_reuses_presets_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(tmp_path / "idempotent-presets.db")
    payload = {
        "days": 3,
        "presets": ["baseline"],
        "persist": True,
        "idempotency_key": "presets-key",
    }
    try:
        with TestClient(_app(store)) as client:
            first = client.post("/api/backtest/presets", json=payload)
            monkeypatch.setattr(
                api_module,
                "run_presets",
                lambda *args, **kwargs: pytest.fail("no debe repetir la simulación"),
            )
            second = client.post("/api/backtest/presets", json=payload)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json() == second.json()
        assert first.json()["backtest_run_id"] == second.json()["backtest_run_id"]
        assert len(_rows(store, "backtest_runs")) == 1
        saved = _rows(store, "backtest_results")
        assert len(saved) == 1
        stored_ids = {row["preset"]: row["id"] for row in saved}
        first_ids = {
            row["preset"]: row["result_id"] for row in first.json()["comparison"]
        }
        retry_ids = {
            row["preset"]: row["result_id"] for row in second.json()["comparison"]
        }
        assert first_ids == stored_ids
        assert retry_ids == stored_ids
    finally:
        store.close()


def test_idempotency_key_with_different_payload_returns_conflict(tmp_path: Path) -> None:
    store = Store(tmp_path / "idempotent-conflict.db")
    try:
        with TestClient(_app(store)) as client:
            first = client.post(
                "/api/backtest/run",
                json={
                    "days": 3,
                    "persist": True,
                    "label": "primero",
                    "idempotency_key": "conflict-key",
                },
            )
            second = client.post(
                "/api/backtest/run",
                json={
                    "days": 3,
                    "persist": True,
                    "label": "otro",
                    "idempotency_key": "conflict-key",
                },
            )

        assert first.status_code == 200, first.text
        assert second.status_code == 409, second.text
        assert "payload distinto" in second.json()["detail"]
        assert len(_rows(store, "backtest_runs")) == 1
        assert len(_rows(store, "backtest_results")) == 1
    finally:
        store.close()


def test_without_idempotency_key_each_request_creates_a_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "without-idempotency.db")
    payload = {"days": 3, "persist": True}
    try:
        with TestClient(_app(store)) as client:
            first = client.post("/api/backtest/run", json=payload)
            second = client.post("/api/backtest/run", json=payload)

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        assert first.json()["backtest_run_id"] != second.json()["backtest_run_id"]
        assert len(_rows(store, "backtest_runs")) == 2
        assert len(_rows(store, "backtest_results")) == 2
    finally:
        store.close()


def test_save_backtest_does_not_touch_frozen_backtests_table(tmp_path: Path) -> None:
    path = tmp_path / "frozen.db"
    shutil.copyfile(LEGACY_FIXTURE, path)
    store = Store(path)
    try:
        before = _rows(store, "backtests")
        assert len(before) == 1

        store.save_backtest(_single_result("new-after-backfill"))

        assert _rows(store, "backtests") == before
        assert len(_rows(store, "backtest_runs")) == 2
    finally:
        store.close()


def test_variants_run_writes_every_result_in_one_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "variants.db")
    try:
        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/run",
                json={"days": 3, "compare": True, "persist": True},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        variants = body["variants"]

        runs = _rows(store, "backtest_runs")
        results = _rows(store, "backtest_results")
        assert len(runs) == 1
        assert len(results) == len(variants) == 4
        run = runs[0]
        assert body["backtest_run_id"] == run["id"]
        assert run["kind"] == "variants"
        assert run["result_count"] == 4
        assert run["primary_result_id"] == variants[0]["id"]
        assert {row["result_key"] for row in results} == {
            item["variant"] for item in variants
        }
        assert all(row["backtest_run_id"] == run["id"] for row in results)
        assert all(row["variant"] == row["result_key"] for row in results)
        assert _rows(store, "backtests") == []
        assert store.latest_backtest() is None
    finally:
        store.close()


def test_variants_persist_false_does_not_write_or_link_run(tmp_path: Path) -> None:
    store = Store(tmp_path / "variants-no-persist.db")
    try:
        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/run",
                json={"days": 3, "compare": True, "persist": False},
            )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["backtest_run_id"] is None
        assert len(body["variants"]) == 4
        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
    finally:
        store.close()


def test_presets_run_writes_baseline_and_selected_presets(tmp_path: Path) -> None:
    store = Store(tmp_path / "presets.db")
    try:
        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/presets",
                json={
                    "days": 3,
                    "presets": ["baseline", "sl_cap_600"],
                    "persist": True,
                },
            )
        assert response.status_code == 200, response.text
        body = response.json()

        runs = _rows(store, "backtest_runs")
        results = _rows(store, "backtest_results")
        assert len(runs) == 1
        assert len(results) == 2
        run = runs[0]
        assert body["backtest_run_id"] == run["id"]
        assert run["kind"] == "presets"
        assert run["result_count"] == 2
        assert run["primary_result_id"] == next(
            row["id"] for row in results if row["result_key"] == "baseline"
        )
        assert [row["result_key"] for row in results] == ["baseline", "sl_cap_600"]
        assert all(row["preset"] == row["result_key"] for row in results)
        assert _rows(store, "backtests") == []
        assert store.latest_backtest() is None
    finally:
        store.close()


def test_presets_persist_false_does_not_write(tmp_path: Path) -> None:
    store = Store(tmp_path / "presets-no-persist.db")
    try:
        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/presets",
                json={"days": 3, "presets": ["baseline"], "persist": False},
            )
        assert response.status_code == 200, response.text
        assert response.json()["backtest_run_id"] is None
        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
    finally:
        store.close()


def test_reset_deletes_new_runs_results_and_legacy_index(tmp_path: Path) -> None:
    store = Store(tmp_path / "reset-new.db")
    try:
        store.save_backtest(_single_result())
        deleted = store.clear_history(delete_backtests=True)

        assert deleted["backtests"] == 1
        assert _rows(store, "backtests") == []
        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
        assert store.latest_backtest() is None
        assert store.get_backtest("result-1") is None
    finally:
        store.close()


def test_reset_deletes_legacy_rows_indexed_by_the_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    shutil.copyfile(LEGACY_FIXTURE, db_path)
    store = Store(db_path)
    try:
        deleted = store.clear_history(delete_backtests=True)

        assert deleted["backtests"] == 1
        assert _rows(store, "backtests") == []
        assert _rows(store, "backtest_runs") == []
        assert _rows(store, "backtest_results") == []
        assert store.latest_backtest() is None
    finally:
        store.close()
