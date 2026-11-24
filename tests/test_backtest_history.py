"""Historial de backtests: listado, detalle y comparación."""

from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from server.api import router
from server.config import Settings
from server.db import Store

ROOT = Path(__file__).resolve().parents[1]
LEGACY_FIXTURE = ROOT / "tests" / "fixtures" / "db" / "v1_real_yedbot.db"


def _app(store: Store) -> FastAPI:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.state.engine = SimpleNamespace(settings=Settings(), store=store)
    return app


def _result(
    result_id: str,
    *,
    created_ts: int,
    net_profit: float,
    avg_r: float,
    variant: str | None = None,
    preset: str | None = None,
    dataset_sha256: str = "a" * 64,
    config_sha256: str = "b" * 64,
    code_sha256: str = "c" * 64,
    dataset_id: str = "dataset-history",
) -> dict:
    return {
        "id": result_id,
        "created_ts": created_ts,
        "label": f"resultado {result_id}",
        "data_source": "synthetic",
        "dataset_id": dataset_id,
        "dataset": {"id": dataset_id},
        "config": {"days": 3},
        "metrics": {
            "trades": 2,
            "net_profit": net_profit,
            "max_drawdown_pct": 1.5,
            "profit_factor": 2.0,
            "avg_r": avg_r,
            "equity_curve": [{"ts": 1, "equity": 25_000.0}],
        },
        "trades": [],
        "equity": [{"ts": 1, "equity": 25_000.0}],
        "funnel": {"schema": "funnel-v1", "sessions": [], "summary": {}},
        "days_detail": [],
        "experiment": {
            "config_sha256": config_sha256,
            "code_sha256": code_sha256,
            "dataset_sha256": dataset_sha256,
            "data_source": "synthetic",
            "dataset_id": dataset_id,
        },
        "variant": variant,
        "preset": preset,
    }


def _legacy_store(tmp_path: Path) -> Store:
    path = tmp_path / "history.db"
    shutil.copyfile(LEGACY_FIXTURE, path)
    return Store(path)


def _legacy_rows(store: Store) -> list[dict]:
    with store._lock:
        return [dict(row) for row in store._conn.execute("SELECT * FROM backtests ORDER BY id")]


def _unindex_legacy(store: Store) -> None:
    """Simula el legado que quedó fuera de las tablas nuevas."""
    with store._lock:
        for legacy in _legacy_rows(store):
            run = store._conn.execute(
                "SELECT id FROM backtest_runs WHERE legacy_backtest_id = ?",
                (legacy["id"],),
            ).fetchone()
            if run is None:
                continue
            store._conn.execute(
                "DELETE FROM backtest_results WHERE backtest_run_id = ?", (run["id"],)
            )
            store._conn.execute("DELETE FROM backtest_runs WHERE id = ?", (run["id"],))
        store._conn.commit()


def test_history_lists_new_and_legacy_runs_with_pagination(tmp_path: Path) -> None:
    store = _legacy_store(tmp_path)
    try:
        store.save_backtest(
            _result("new-1", created_ts=3_000_000_000_000, net_profit=100.0, avg_r=1.0)
        )
        store.save_backtest(
            [
                _result(
                    "variant-1",
                    created_ts=3_000_000_000_001,
                    net_profit=50.0,
                    avg_r=0.5,
                    variant="orb",
                ),
                _result(
                    "variant-2",
                    created_ts=3_000_000_000_002,
                    net_profit=75.0,
                    avg_r=0.8,
                    variant="full",
                ),
            ],
            kind="variants",
        )

        with TestClient(_app(store)) as client:
            response = client.get("/api/backtest/runs")
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["total"] == 3
            assert body["limit"] == 25
            assert body["offset"] == 0
            assert len(body["items"]) == 3
            assert sum(1 for item in body["items"] if item["legacy"]) == 1
            assert {item["kind"] for item in body["items"]} == {"single", "variants"}

            single = client.get("/api/backtest/runs?kind=single").json()
            assert single["total"] == 2
            assert all(item["kind"] == "single" for item in single["items"])

            variants = client.get("/api/backtest/runs?kind=variants").json()
            assert variants["total"] == 1
            assert variants["items"][0]["result_count"] == 2

            legacy = client.get("/api/backtest/runs?legacy=true").json()
            assert legacy["total"] == 1
            assert legacy["items"][0]["legacy"] is True

            page = client.get("/api/backtest/runs?limit=1&offset=1").json()
            assert page["total"] == 3
            assert page["limit"] == 1
            assert page["offset"] == 1
            assert len(page["items"]) == 1
    finally:
        store.close()


def test_history_cursor_pagination_is_stable_under_new_insertions(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "cursor.db")
    try:
        for result_id, created_ts in (
            ("run-old", 100),
            ("run-mid", 200),
            ("run-newest", 300),
        ):
            store.save_backtest(
                _result(result_id, created_ts=created_ts, net_profit=1.0, avg_r=0.1)
            )

        with TestClient(_app(store)) as client:
            first = client.get("/api/backtest/runs", params={"limit": 2})
            assert first.status_code == 200, first.text
            first_body = first.json()
            assert [item["label"] for item in first_body["items"]] == [
                "resultado run-newest",
                "resultado run-mid",
            ]
            assert first_body["has_more"] is True
            cursor = first_body["next_cursor"]
            assert cursor

            # Insertar una corrida nueva (más reciente) no desplaza la
            # segunda página del cursor.
            store.save_backtest(
                _result("run-inserted", created_ts=400, net_profit=2.0, avg_r=0.2)
            )
            second = client.get(
                "/api/backtest/runs", params={"limit": 2, "cursor": cursor}
            )
            assert second.status_code == 200, second.text
            second_body = second.json()
            assert [item["label"] for item in second_body["items"]] == [
                "resultado run-old"
            ]
            assert second_body["has_more"] is False
            assert second_body["next_cursor"] is None
            assert second_body["offset"] == 0
            assert second_body["total"] == 4

            # La primera página normal sí refleja la inserción; limit/offset
            # sigue funcionando para clientes antiguos.
            legacy_page = client.get(
                "/api/backtest/runs", params={"limit": 2, "offset": 1}
            ).json()
            assert [item["label"] for item in legacy_page["items"]] == [
                "resultado run-newest",
                "resultado run-mid",
            ]
            assert legacy_page["offset"] == 1
    finally:
        store.close()


def test_history_filters_by_date_dataset_and_label_and_cursor_keeps_them(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "filters.db")
    base = 1_700_000_000_000
    try:
        store.save_backtest(
            _result(
                "run-a",
                created_ts=base,
                net_profit=10.0,
                avg_r=0.2,
                dataset_id="dataset-a",
            ),
            label="Alpha NY",
        )
        store.save_backtest(
            _result(
                "run-b",
                created_ts=base + 1_000_000,
                net_profit=20.0,
                avg_r=0.4,
                dataset_id="dataset-b",
            ),
            label="Beta",
        )
        store.save_backtest(
            _result(
                "run-c",
                created_ts=base + 2_000_000,
                net_profit=30.0,
                avg_r=0.6,
                dataset_id="dataset-a",
            ),
            label="Alpha London",
        )

        with TestClient(_app(store)) as client:
            by_label = client.get("/api/backtest/runs", params={"label": "alpha"})
            assert by_label.status_code == 200, by_label.text
            assert [item["label"] for item in by_label.json()["items"]] == [
                "Alpha London",
                "Alpha NY",
            ]

            by_dataset = client.get(
                "/api/backtest/runs", params={"dataset": "dataset-a"}
            )
            assert by_dataset.status_code == 200, by_dataset.text
            assert [item["label"] for item in by_dataset.json()["items"]] == [
                "Alpha London",
                "Alpha NY",
            ]

            by_dataset_id = client.get(
                "/api/backtest/runs", params={"dataset_id": "dataset-b"}
            )
            assert by_dataset_id.status_code == 200, by_dataset_id.text
            assert [item["label"] for item in by_dataset_id.json()["items"]] == [
                "Beta"
            ]

            by_date_from = client.get(
                "/api/backtest/runs", params={"date_from": str(base + 1_000_000)}
            )
            assert by_date_from.status_code == 200, by_date_from.text
            assert [item["label"] for item in by_date_from.json()["items"]] == [
                "Alpha London",
                "Beta",
            ]

            by_date_to = client.get(
                "/api/backtest/runs", params={"date_to": str(base + 1_000_000)}
            )
            assert by_date_to.status_code == 200, by_date_to.text
            assert [item["label"] for item in by_date_to.json()["items"]] == [
                "Beta",
                "Alpha NY",
            ]

            by_day = client.get(
                "/api/backtest/runs",
                params={"date_from": "2023-11-14", "date_to": "2023-11-14"},
            )
            assert by_day.status_code == 200, by_day.text
            assert [item["label"] for item in by_day.json()["items"]] == [
                "Alpha London",
                "Beta",
                "Alpha NY",
            ]

            no_rows = client.get(
                "/api/backtest/runs", params={"date_from": "2023-11-15"}
            )
            assert no_rows.status_code == 200, no_rows.text
            assert no_rows.json()["items"] == []

            first = client.get(
                "/api/backtest/runs",
                params={"dataset": "dataset-a", "limit": 1},
            ).json()
            assert [item["label"] for item in first["items"]] == ["Alpha London"]
            cursor = first["next_cursor"]
            assert cursor

            store.save_backtest(
                _result(
                    "run-d",
                    created_ts=base + 3_000_000,
                    net_profit=40.0,
                    avg_r=0.8,
                    dataset_id="dataset-a",
                ),
                label="Alpha Tokyo",
            )
            second = client.get(
                "/api/backtest/runs",
                params={"dataset": "dataset-a", "limit": 1, "cursor": cursor},
            )
            assert second.status_code == 200, second.text
            assert [item["label"] for item in second.json()["items"]] == ["Alpha NY"]
    finally:
        store.close()


def test_history_rejects_invalid_cursor_and_inverted_dates(tmp_path: Path) -> None:
    store = Store(tmp_path / "cursor-invalid.db")
    try:
        with TestClient(_app(store)) as client:
            invalid = client.get("/api/backtest/runs", params={"cursor": "no-es-un-cursor"})
            assert invalid.status_code == 400, invalid.text

            inverted = client.get(
                "/api/backtest/runs",
                params={"date_from": "2023-11-15", "date_to": "2023-11-14"},
            )
            assert inverted.status_code == 400, inverted.text
    finally:
        store.close()


def test_history_detail_resolves_new_and_legacy_results(tmp_path: Path) -> None:
    store = _legacy_store(tmp_path)
    try:
        store.save_backtest(
            _result("new-1", created_ts=3_000_000_000_000, net_profit=100.0, avg_r=1.0)
        )
        with TestClient(_app(store)) as client:
            listing = client.get("/api/backtest/runs").json()["items"]
            legacy_item = next(item for item in listing if item["legacy"])
            new_item = next(item for item in listing if not item["legacy"])

            legacy_detail = client.get(f"/api/backtest/runs/{legacy_item['id']}")
            assert legacy_detail.status_code == 200, legacy_detail.text
            legacy_body = legacy_detail.json()
            assert legacy_body["run"]["legacy"] is True
            assert legacy_body["warnings"] == []
            assert len(legacy_body["results"]) == 1
            legacy_result_id = legacy_body["results"][0]["id"]
            assert client.get(f"/api/backtest/results/{legacy_result_id}").status_code == 200

            new_detail = client.get(f"/api/backtest/runs/{new_item['id']}")
            assert new_detail.status_code == 200, new_detail.text
            new_body = new_detail.json()
            assert new_body["run"]["legacy"] is False
            assert new_body["results"][0]["result_key"] == "single"
            new_result = client.get(f"/api/backtest/results/{new_body['results'][0]['id']}")
            assert new_result.status_code == 200, new_result.text
            assert new_result.json()["funnel"]["schema"] == "funnel-v1"

            missing = client.get("/api/backtest/runs/no-existe")
            assert missing.status_code == 404
            assert client.get("/api/backtest/results/no-existe").status_code == 404
    finally:
        store.close()


def test_history_compare_get_and_post_compute_deltas(tmp_path: Path) -> None:
    store = Store(tmp_path / "compare.db")
    try:
        store.save_backtest(
            _result("base", created_ts=100, net_profit=100.0, avg_r=1.0)
        )
        store.save_backtest(
            _result("alt", created_ts=101, net_profit=150.0, avg_r=1.5)
        )
        with TestClient(_app(store)) as client:
            response = client.get(
                "/api/backtest/runs/compare",
                params={
                    "result_ids": ["base", "alt"],
                    "baseline_id": "base",
                    "metrics": ["net_profit", "avg_r"],
                },
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["baseline_id"] == "base"
            assert body["comparable"] is True
            assert body["warnings"] == []
            assert [row["result_id"] for row in body["rows"]] == ["base", "alt"]
            assert body["rows"][0]["delta_vs_baseline"] == {"net_profit": 0.0, "avg_r": 0.0}
            assert body["rows"][1]["delta_vs_baseline"] == {"net_profit": 50.0, "avg_r": 0.5}

            post = client.post(
                "/api/backtest/compare",
                json={
                    "result_ids": ["base", "alt"],
                    "baseline_id": "base",
                    "metrics": ["net_profit", "avg_r"],
                },
            )
            assert post.status_code == 200, post.text
            assert post.json()["rows"] == body["rows"]

            alias = client.get(
                "/api/backtest/runs/compare",
                params={"ids": "base,alt", "metrics": "net_profit"},
            )
            assert alias.status_code == 200, alias.text
            assert alias.json()["baseline_id"] == "base"
    finally:
        store.close()


def test_history_compare_rejects_invalid_requests_and_mixes_legacy(tmp_path: Path) -> None:
    store = _legacy_store(tmp_path)
    try:
        store.save_backtest(
            _result("new-1", created_ts=3_000_000_000_000, net_profit=100.0, avg_r=1.0)
        )
        with TestClient(_app(store)) as client:
            listing = client.get("/api/backtest/runs").json()["items"]
            legacy_item = next(item for item in listing if item["legacy"])
            legacy_detail = client.get(f"/api/backtest/runs/{legacy_item['id']}").json()
            legacy_result_id = legacy_detail["results"][0]["id"]

            mixed = client.get(
                "/api/backtest/runs/compare",
                params={"ids": [legacy_result_id, "new-1"], "baseline_id": "new-1"},
            )
            assert mixed.status_code == 200, mixed.text
            mixed_body = mixed.json()
            assert len(mixed_body["rows"]) == 2
            assert {row["result_id"] for row in mixed_body["rows"]} == {
                legacy_result_id,
                "new-1",
            }

            assert (
                client.get(
                    "/api/backtest/runs/compare",
                    params={"result_ids": ["new-1"]},
                ).status_code
                == 400
            )
            assert (
                client.get(
                    "/api/backtest/runs/compare",
                    params={"result_ids": ["new-1", "new-1"]},
                ).status_code
                == 400
            )
            assert (
                client.get(
                    "/api/backtest/runs/compare",
                    params={"result_ids": ["new-1", "no-existe"]},
                ).status_code
                == 404
            )
            assert (
                client.get(
                    "/api/backtest/runs/compare",
                    params={"result_ids": ["new-1", "new-1", "new-1", "new-1", "new-1"]},
                ).status_code
                == 400
            )
            assert (
                client.get(
                    "/api/backtest/runs/compare",
                    params={"result_ids": ["new-1", "new-1"], "metrics": "no_existe"},
                ).status_code
                == 400
            )
    finally:
        store.close()


def test_legacy_diagnostics_reports_clean_fixture_without_writing(tmp_path: Path) -> None:
    store = _legacy_store(tmp_path)
    try:
        before = _legacy_rows(store)
        with TestClient(_app(store)) as client:
            response = client.get("/api/backtest/runs/legacy-diagnostics")

        assert response.status_code == 200, response.text
        assert response.json() == {
            "total": 1,
            "indexed": 1,
            "unindexed": 0,
            "invalid": 0,
            "items": [],
            "read_only": True,
        }
        assert _legacy_rows(store) == before
    finally:
        store.close()


def test_legacy_diagnostics_reports_unindexed_row_without_writing(tmp_path: Path) -> None:
    store = _legacy_store(tmp_path)
    try:
        legacy = _legacy_rows(store)[0]
        with store._lock:
            run = store._conn.execute(
                "SELECT id FROM backtest_runs WHERE legacy_backtest_id = ?",
                (legacy["id"],),
            ).fetchone()
            assert run is not None
            store._conn.execute(
                "DELETE FROM backtest_results WHERE backtest_run_id = ?", (run["id"],)
            )
            store._conn.execute("DELETE FROM backtest_runs WHERE id = ?", (run["id"],))
            store._conn.commit()

        before = _legacy_rows(store)
        with TestClient(_app(store)) as client:
            response = client.get("/api/backtest/runs/legacy-diagnostics")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["indexed"] == 0
        assert body["unindexed"] == 1
        assert body["invalid"] == 0
        assert body["items"] == [
            {
                "id": legacy["id"],
                "created_ts": legacy["created_ts"],
                "label": legacy["label"],
                "indexed": False,
                "backtest_run_id": None,
                "primary_result_id": None,
                "status": "unindexed",
                "problems": [
                    {
                        "code": "missing_index",
                        "detail": (
                            "No está indexada en backtest_runs; no aparece en el "
                            "historial paginado."
                        ),
                    }
                ],
            }
        ]
        assert _legacy_rows(store) == before
    finally:
        store.close()


def test_legacy_diagnostics_reports_invalid_row_without_writing(tmp_path: Path) -> None:
    store = _legacy_store(tmp_path)
    try:
        legacy = _legacy_rows(store)[0]
        with store._lock:
            store._conn.execute(
                "UPDATE backtests SET metrics = ? WHERE id = ?",
                ("{invalid", legacy["id"]),
            )
            store._conn.commit()

        before = _legacy_rows(store)
        with TestClient(_app(store)) as client:
            response = client.get("/api/backtest/runs/legacy-diagnostics")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 1
        assert body["indexed"] == 1
        assert body["unindexed"] == 0
        assert body["invalid"] == 1
        item = body["items"][0]
        assert item["id"] == legacy["id"]
        assert item["indexed"] is True
        assert item["status"] == "invalid"
        assert item["problems"][0]["code"] == "metrics_invalid"
        assert legacy["id"] in item["problems"][0]["detail"]
        assert _legacy_rows(store) == before
    finally:
        store.close()


def test_legacy_repair_dry_run_reports_valid_unindexed_without_writing(
    tmp_path: Path,
) -> None:
    store = _legacy_store(tmp_path)
    try:
        _unindex_legacy(store)
        legacy = _legacy_rows(store)[0]
        before = _legacy_rows(store)
        with store._lock:
            assert store._conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0] == 0
            assert store._conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0] == 0

        with TestClient(_app(store)) as client:
            get_report = client.get("/api/backtest/runs/legacy-repair")
            post_report = client.post("/api/backtest/runs/legacy-repair")

        for response in (get_report, post_report):
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["dry_run"] is True
            assert body["read_only"] is True
            assert body["wrote_backtests"] is False
            assert body["total"] == 1
            assert body["indexed"] == 0
            assert body["unindexed"] == 1
            assert body["candidates"] == 1
            assert body["valid"] == 1
            assert body["invalid"] == 0
            assert body["reindexed"] == 0
            assert body["would_reindex"] == 1
            assert body["items"] == [
                {
                    "id": legacy["id"],
                    "created_ts": legacy["created_ts"],
                    "label": legacy["label"],
                    "status": "would_reindex",
                    "indexed": False,
                    "backtest_run_id": None,
                    "primary_result_id": None,
                    "problems": [],
                }
            ]

        assert _legacy_rows(store) == before
        with store._lock:
            assert store._conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0] == 0
            assert store._conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0] == 0
    finally:
        store.close()


def test_legacy_repair_reindexes_valid_unindexed_without_touching_backtests(
    tmp_path: Path,
) -> None:
    store = _legacy_store(tmp_path)
    try:
        _unindex_legacy(store)
        legacy = _legacy_rows(store)[0]
        before = _legacy_rows(store)

        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/runs/legacy-repair", params={"dry_run": "false"}
            )
            assert response.status_code == 200, response.text
            body = response.json()
            assert body["dry_run"] is False
            assert body["read_only"] is False
            assert body["wrote_backtests"] is False
            assert body["total"] == 1
            assert body["indexed"] == 0
            assert body["unindexed"] == 1
            assert body["valid"] == 1
            assert body["invalid"] == 0
            assert body["reindexed"] == 1
            assert body["would_reindex"] == 0
            item = body["items"][0]
            assert item["id"] == legacy["id"]
            assert item["status"] == "reindexed"
            assert item["indexed"] is True
            assert item["primary_result_id"] == legacy["id"]
            run_id = item["backtest_run_id"]
            assert run_id

            listing = client.get("/api/backtest/runs?legacy=true")
            assert listing.status_code == 200, listing.text
            assert listing.json()["total"] == 1
            listed = listing.json()["items"][0]
            assert listed["id"] == run_id
            assert listed["legacy"] is True

            detail = client.get(f"/api/backtest/runs/{run_id}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["run"]["legacy"] is True
            assert detail.json()["results"][0]["id"] == legacy["id"]

            preview = client.get("/api/backtest/runs/legacy-repair")
            assert preview.status_code == 200, preview.text
            assert preview.json()["indexed"] == 1
            assert preview.json()["unindexed"] == 0
            assert preview.json()["would_reindex"] == 0
            assert preview.json()["items"] == []

        assert _legacy_rows(store) == before
        with store._lock:
            run = store._conn.execute(
                "SELECT id FROM backtest_runs WHERE legacy_backtest_id = ?",
                (legacy["id"],),
            ).fetchone()
            assert run is not None and run["id"] == run_id
            result = store._conn.execute(
                "SELECT backtest_run_id FROM backtest_results WHERE id = ?",
                (legacy["id"],),
            ).fetchone()
            assert result is not None and result["backtest_run_id"] == run_id
    finally:
        store.close()


def test_legacy_repair_reindexes_valid_rows_even_when_another_row_is_invalid(
    tmp_path: Path,
) -> None:
    store = _legacy_store(tmp_path)
    try:
        _unindex_legacy(store)
        legacy = _legacy_rows(store)[0]
        copied = dict(legacy)
        copied["id"] = "legacy-valid-copy"
        copied["label"] = "copia válida"
        columns = list(copied)
        with store._lock:
            store._conn.execute(
                "INSERT INTO backtests (" + ", ".join(columns) + ") "
                "VALUES (" + ", ".join("?" for _ in columns) + ")",
                tuple(copied[column] for column in columns),
            )
            store._conn.execute(
                "UPDATE backtests SET metrics = ? WHERE id = ?",
                ("{invalid", legacy["id"]),
            )
            store._conn.commit()
        before = _legacy_rows(store)

        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/runs/legacy-repair", params={"dry_run": "false"}
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["total"] == 2
        assert body["unindexed"] == 2
        assert body["valid"] == 1
        assert body["invalid"] == 1
        assert body["reindexed"] == 1
        by_id = {item["id"]: item for item in body["items"]}
        assert by_id[legacy["id"]]["status"] == "invalid"
        assert by_id[legacy["id"]]["problems"][0]["code"] == "metrics_invalid"
        assert by_id[copied["id"]]["status"] == "reindexed"
        assert by_id[copied["id"]]["primary_result_id"] == copied["id"]
        assert _legacy_rows(store) == before
        with store._lock:
            assert store._conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0] == 1
            result = store._conn.execute(
                "SELECT id FROM backtest_results WHERE id = ?", (copied["id"],)
            ).fetchone()
            assert result is not None
    finally:
        store.close()


def test_legacy_repair_reports_invalid_without_indexing_or_touching_backtests(
    tmp_path: Path,
) -> None:
    store = _legacy_store(tmp_path)
    try:
        _unindex_legacy(store)
        legacy = _legacy_rows(store)[0]
        with store._lock:
            store._conn.execute(
                "UPDATE backtests SET metrics = ? WHERE id = ?",
                ("{invalid", legacy["id"],),
            )
            store._conn.commit()
        before = _legacy_rows(store)

        with TestClient(_app(store)) as client:
            response = client.post(
                "/api/backtest/runs/legacy-repair", json={"dry_run": False}
            )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["indexed"] == 0
        assert body["unindexed"] == 1
        assert body["valid"] == 0
        assert body["invalid"] == 1
        assert body["reindexed"] == 0
        assert body["would_reindex"] == 0
        item = body["items"][0]
        assert item["id"] == legacy["id"]
        assert item["status"] == "invalid"
        assert item["backtest_run_id"] is None
        assert item["problems"][0]["code"] == "metrics_invalid"
        assert _legacy_rows(store) == before
        with store._lock:
            assert store._conn.execute("SELECT COUNT(*) FROM backtest_runs").fetchone()[0] == 0
            assert store._conn.execute("SELECT COUNT(*) FROM backtest_results").fetchone()[0] == 0
    finally:
        store.close()
