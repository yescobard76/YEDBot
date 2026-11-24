"""Métricas E-1 por evento: embudo, CSV y resumen del backtest."""

from __future__ import annotations

import csv
from datetime import date

from server.backtest import run_backtest
from server.config import Settings
from server.funnel import write_csv


def _result():
    return run_backtest(Settings(), 3, None, "event-metrics", date(2025, 6, 3))


def test_event_metrics_reach_funnel_and_backtest_metrics() -> None:
    result = _result()
    event_metrics = result["metrics"]["event_metrics"]

    assert event_metrics["events"] >= 1
    assert event_metrics["signals"] >= 1
    assert event_metrics["retest_distance_ticks"]["count"] >= 1
    assert event_metrics["direct_stop_ticks"]["count"] >= 1
    assert event_metrics["entry_delay_min"]["count"] >= 1
    assert event_metrics == result["funnel"]["summary"]["event_metrics"]

    events = [
        record
        for record in result["funnel"]["sessions"]
        if record.get("event_id") is not None
    ]
    assert len(events) == event_metrics["events"]
    first = next(record for record in events if record.get("signal"))
    assert first["retest_distance_ticks"] is not None
    assert first["direct_stop_ticks"] is not None
    assert first["entry_delay_min"] is not None
    assert first["signal"]["event_id"] == first["event_id"]


def test_event_metrics_are_exported_in_funnel_csv(tmp_path) -> None:
    result = _result()
    target = write_csv(result["funnel"]["sessions"], tmp_path / "funnel.csv")

    with target.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert {
            "event_id",
            "retest_distance_ticks",
            "direct_stop_ticks",
            "direct_stop_cap_binding",
            "entry_delay_min",
            "stop_cap_binding",
        } <= set(reader.fieldnames or [])
        row = next(item for item in reader if item["event_id"])

    assert row["retest_distance_ticks"] != ""
    assert row["direct_stop_ticks"] != ""
    assert row["entry_delay_min"] != ""
    assert row["stop_cap_binding"] in {"True", "False"}
