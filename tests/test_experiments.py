"""Identidad canónica, paridad backtest/paper y ledger de hipótesis."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from server.backtest import run_backtest
from server.config import Settings
from server.db import Store
from server.engine import TradingEngine
from server.experiments import (
    ExperimentIdentity,
    ExperimentLedger,
    LedgerError,
    ParityError,
    assert_identity_matches,
    assert_parity,
    assert_result_identity,
    canonical_config,
    config_sha256,
    dataset_sha256,
)


def test_canonical_config_excludes_operational_sections() -> None:
    base = Settings()
    replay = base.model_copy(deep=True)
    replay.feed.replay_speed = 50
    replay.feed.loop_sessions = False
    replay.mode = "live"
    replay.live.live_enabled = True

    assert config_sha256(base) == config_sha256(replay)
    canonical = canonical_config(base)
    assert {"feed", "live", "mode"}.isdisjoint(canonical)
    assert canonical["strategy"] == base.strategy.model_dump(mode="json")

    changed = base.model_copy(deep=True)
    changed.risk.max_sl_ticks += 1
    assert config_sha256(base) != config_sha256(changed)


def test_backtest_attaches_a_recomputable_identity() -> None:
    settings = Settings()
    result = run_backtest(settings, days=3, label="identidad")

    identity = result["experiment"]
    assert identity["config_sha256"] == config_sha256(settings)
    assert identity["code_sha256"] == result["dataset"]["code"]["sha256"]
    assert identity["dataset_sha256"] == dataset_sha256(result["dataset"])
    assert identity["dataset_id"] == result["dataset"]["id"]
    assert identity["selected_id"] == result["dataset"]["selected_id"]
    assert identity["data_source"] == "synthetic"
    assert identity["sessions"] == 3

    validated = assert_result_identity(result, settings=settings)
    assert validated.config_sha256 == identity["config_sha256"]


def test_identity_rejects_dataset_or_config_tampering() -> None:
    settings = Settings()
    result = run_backtest(settings, days=3)
    identity = ExperimentIdentity.from_dict(result["experiment"])

    tampered_dataset = dict(result["dataset"])
    tampered_dataset["generator_version"] = "2"
    with pytest.raises(ParityError, match="dataset"):
        assert_identity_matches(identity, settings=settings, dataset=tampered_dataset)

    tampered_config = dict(result["experiment"])
    tampered_config["config_sha256"] = "0" * 64
    with pytest.raises(ParityError, match="config"):
        assert_parity(identity, tampered_config, compare_dataset=False)


def test_paper_start_refuses_config_drift_against_persisted_backtest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YED_ALLOW_SIMULATED", "1")
    settings = Settings()
    result = run_backtest(settings, days=3)

    store = Store(tmp_path / "paper.db")
    try:
        store.save_backtest(result)
        assert store.get_kv("experiment.parity") == result["experiment"]

        drifted = settings.model_copy(deep=True)
        drifted.risk.risk_per_trade_pct = 0.5
        engine = TradingEngine(store, drifted)
        ok, message = asyncio.run(engine.start())

        assert ok is False
        assert "paridad" in message.lower()
        assert store.get_kv("experiment.paper") is None
    finally:
        store.close()


def test_paper_start_records_identity_when_parity_holds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("YED_ALLOW_SIMULATED", "1")
    settings = Settings()
    result = run_backtest(settings, days=3)

    store = Store(tmp_path / "paper-ok.db")
    try:
        store.save_backtest(result)
        engine = TradingEngine(store, settings)

        async def start_stop() -> tuple[bool, str]:
            ok, message = await engine.start()
            await engine.stop()
            return ok, message

        ok, _ = asyncio.run(start_stop())
        assert ok is True

        recorded = store.get_kv("experiment.paper")
        assert recorded["config_sha256"] == config_sha256(settings)
        assert recorded["code_sha256"] == result["experiment"]["code_sha256"]
        assert recorded["dataset_sha256"] == result["experiment"]["dataset_sha256"]
    finally:
        store.close()


def test_hypothesis_ledger_is_append_only_and_records_runs(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger = ExperimentLedger(path)

    registered = ledger.register(
        "H-2026-01",
        "Continuación selectiva",
        description="Solo desarrollo; no toca el holdout.",
    )
    assert registered["event"] == "hypothesis.registered"
    first_entry = path.read_text(encoding="utf-8")

    with pytest.raises(LedgerError, match="ya está registrada"):
        ledger.register("H-2026-01", "Duplicada")
    assert path.read_text(encoding="utf-8") == first_entry

    result = run_backtest(Settings(), days=3, label="ledger")
    record = ledger.record_backtest(result, hypothesis_id="H-2026-01")

    assert record["event"] == "experiment.completed"
    assert record["run_id"] == result["id"]
    assert record["identity"] == result["experiment"]
    assert record["metrics"]["trades"] == result["metrics"]["trades"]

    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line]
    assert len(lines) == 2
    summary = ledger.hypotheses()["H-2026-01"]
    assert summary["title"] == "Continuación selectiva"
    assert summary["run_count"] == 1
    assert len(ledger.runs("H-2026-01")) == 1
