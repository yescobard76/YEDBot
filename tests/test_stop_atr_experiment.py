"""Tests del pre-registro E-ATR-1, sin ejecutar backtests."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from research.stop_atr import (
    ATR_STOP_CODE_FILES,
    CODE_PROVENANCE_ALGORITHM,
    PREREGISTRATION_LOCK_PATH,
    StopAtrLockError,
    assert_execution_blocked,
    compute_code_provenance,
    control_overrides,
    effective_fill_risk_gate,
    load_stop_atr_lock,
    payload_sha256,
    treatment_overrides,
    verify_execution_lock_provenance,
)
from server.config import Settings, apply_settings
from server.execution import ExecutionEngine
from server.market.synthetic import build_session
from server.models import Bar, Signal
from server.risk import RiskManager
from server.strategy.orb import OpeningRange
from server.strategy.strategy import ORBStrategy
from server.timeutil import timestamp_for

ROOT = Path(__file__).resolve().parents[1]
LOCK_PATH = ROOT / "docs" / "experimento_stop_atr.lock.json"


def _execution_lock(lock: dict) -> dict:
    return {
        "pre_registration": {
            "path": PREREGISTRATION_LOCK_PATH,
            "payload_sha256": lock["payload_sha256"],
            "code_provenance_sha256": lock["code_provenance"]["combined_sha256"],
        },
        "code_provenance": deepcopy(lock["code_provenance"]),
    }


def _orb() -> OpeningRange:
    return OpeningRange(
        date="2025-06-03",
        start_ts=0,
        end_ts=0,
        high=100.0,
        low=90.0,
        mid=95.0,
        width=10.0,
        width_pct=1.0,
        bars=60,
        complete=True,
    )


def _first_signal(settings: Settings):
    data = build_session(date(2025, 6, 3), settings)
    strategy = ORBStrategy(settings)
    for i in range(3, len(data["NQ"])):
        assess = strategy.evaluate(data["NQ"][:i], data["ES"][:i], True)
        if assess.signal is not None:
            return assess
    return None


def _first_cap(settings: Settings):
    data = build_session(date(2025, 6, 3), settings)
    strategy = ORBStrategy(settings)
    for i in range(3, len(data["NQ"])):
        assess = strategy.evaluate(data["NQ"][:i], data["ES"][:i], True)
        if assess.reject_code == "stop_cap":
            return assess
    return None


def test_lock_integrity_and_execution_gate() -> None:
    lock = load_stop_atr_lock()

    assert lock["experiment"]["id"] == "E-ATR-1"
    assert lock["experiment"]["version"] == "1.4"
    assert lock["experiment"]["status"] == "pre_registered_not_executed"
    assert lock["experiment"]["only_change"] == "strategy.sl_mode"
    assert lock["payload_sha256"] == payload_sha256(lock)

    gate = lock["execution_gate"]
    assert gate["can_execute"] is False
    assert gate["external_sample_required"] is True
    assert gate["execution_lock_requirements"] == {
        "code_provenance": "exact_copy_and_recompute",
        "pre_registration_binding": "payload_sha256_and_code_sha256",
        "on_mismatch": "reject_execution",
    }
    assert lock["sample"]["status"] == "pending"
    assert lock["sample"]["start"] is None
    assert lock["sample"]["end"] is None

    analysis = lock["analysis"]
    assert analysis["primary"]["name"] == "paired_delta_r_common_entries"
    assert analysis["primary"]["cluster"] == "session"
    assert analysis["primary"]["bootstrap_resamples"] == 10_000
    assert analysis["primary"]["seed"] == 20261121
    assert analysis["sample_minimum"] == {
        "common_entries": 20,
        "trades_per_arm": 20,
        "sessions": 60,
    }
    assert analysis["guardrails"]["max_drawdown_max_usd"] == 2500.0
    assert analysis["integrity"]["target_equals_3r"] is True
    assert analysis["integrity"]["max_sl_ticks_checked_before_sizing"] is True
    assert analysis["integrity"]["same_entry_rule_as_control"] is True

    with pytest.raises(StopAtrLockError, match="externa|bloqueada"):
        assert_execution_blocked(lock)


def test_lock_freezes_atr_stop_code_provenance() -> None:
    lock = load_stop_atr_lock()
    provenance = lock["code_provenance"]

    assert provenance["algorithm"] == CODE_PROVENANCE_ALGORITHM
    assert provenance["scope"] == list(ATR_STOP_CODE_FILES)
    assert provenance["entrypoints"] == [
        "ORBStrategy.evaluate",
        "ORBStrategy._stop",
        "atr",
        "true_range",
        "aggregate",
    ]
    assert set(provenance["files"]) == set(ATR_STOP_CODE_FILES)
    assert provenance == compute_code_provenance(ROOT, ATR_STOP_CODE_FILES)
    assert len(provenance["combined_sha256"]) == 64


def test_execution_lock_must_verify_frozen_code_provenance() -> None:
    lock = load_stop_atr_lock()
    execution = _execution_lock(lock)

    assert verify_execution_lock_provenance(execution) == lock["code_provenance"]

    missing = deepcopy(execution)
    missing.pop("code_provenance")
    with pytest.raises(StopAtrLockError, match="code_provenance"):
        verify_execution_lock_provenance(missing)

    changed = deepcopy(execution)
    changed["code_provenance"]["files"]["server/strategy/strategy.py"] = "0" * 64
    with pytest.raises(StopAtrLockError, match="no coincide"):
        verify_execution_lock_provenance(changed)

    wrong_payload = deepcopy(execution)
    wrong_payload["pre_registration"]["payload_sha256"] = "0" * 64
    with pytest.raises(StopAtrLockError, match="payload pre-registrado"):
        verify_execution_lock_provenance(wrong_payload)

    wrong_code = deepcopy(execution)
    wrong_code["pre_registration"]["code_provenance_sha256"] = "0" * 64
    with pytest.raises(StopAtrLockError, match="hash de código"):
        verify_execution_lock_provenance(wrong_code)


def test_execution_lock_rejects_changed_atr_source(tmp_path: Path) -> None:
    lock = load_stop_atr_lock()
    execution = _execution_lock(lock)
    root = tmp_path / "project"
    for relative in lock["code_provenance"]["scope"]:
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())

    assert verify_execution_lock_provenance(execution, root=root) == lock["code_provenance"]

    (root / "server" / "strategy" / "strategy.py").write_text(
        "# fuente alterada\n", encoding="utf-8"
    )
    with pytest.raises(StopAtrLockError, match="código actual"):
        verify_execution_lock_provenance(execution, root=root)


def test_tampered_lock_is_rejected(tmp_path: Path) -> None:
    frozen = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    frozen["frozen"]["strategy"]["atr_sl_mult"] = 1.3
    frozen_path = tmp_path / "tampered-frozen.lock.json"
    frozen_path.write_text(json.dumps(frozen), encoding="utf-8")
    with pytest.raises(StopAtrLockError, match="alterado"):
        load_stop_atr_lock(frozen_path)

    provenance = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    provenance["code_provenance"]["files"]["server/strategy/strategy.py"] = "0" * 64
    provenance["payload_sha256"] = payload_sha256(provenance)
    provenance_path = tmp_path / "tampered-provenance.lock.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    with pytest.raises(StopAtrLockError, match="code_provenance"):
        load_stop_atr_lock(provenance_path)


def test_treatment_changes_only_sl_mode() -> None:
    lock = load_stop_atr_lock()
    assert lock["arms"]["control"]["overrides"] == {}
    assert lock["arms"]["treatment"]["overrides"] == {"strategy": {"sl_mode": "atr"}}
    assert control_overrides() == {}
    assert treatment_overrides() == {"strategy": {"sl_mode": "atr"}}

    control = Settings()
    treatment = apply_settings(control, treatment_overrides())
    assert control.strategy.sl_mode == "structural"
    assert treatment.strategy.sl_mode == "atr"

    control_dump = control.model_dump()
    treatment_dump = treatment.model_dump()
    control_dump["strategy"].pop("sl_mode")
    treatment_dump["strategy"].pop("sl_mode")
    assert control_dump == treatment_dump


def test_atr_stop_uses_multiplier_and_rejects_missing_atr() -> None:
    strategy = ORBStrategy(Settings(strategy={"sl_mode": "atr"}))
    orb = _orb()

    assert strategy._stop(100.0, "long", orb, [], 0, 10.0, 15) == pytest.approx(88.0)
    assert strategy._stop(100.0, "short", orb, [], 0, 10.0, 15) == pytest.approx(112.0)
    assert strategy._stop(100.0, "long", orb, [], 0, 0.0, 15) is None
    assert strategy._stop(100.0, "short", orb, [], 0, 0.0, 15) is None


def test_atr_signal_target_is_three_r() -> None:
    assess = _first_signal(Settings(strategy={"sl_mode": "atr"}))
    assert assess is not None and assess.signal is not None
    signal = assess.signal
    risk = signal.entry_price - signal.stop

    assert risk > 0
    assert signal.target > signal.entry_price
    assert signal.target - signal.entry_price == pytest.approx(3.0 * risk, abs=0.01)
    assert signal.meta["rr"] == 3.0


def test_planned_sizing_never_exceeds_one_percent_of_equity() -> None:
    risk = RiskManager(Settings())
    equity = 25_000.0

    for stop_ticks in (50, 100, 200):
        qty, amount, error = risk.size(equity, stop_ticks)
        assert error == ""
        assert qty <= 5
        assert amount <= equity * 0.01 + 1e-9

    assert risk.size(equity, 100)[:2] == (5, pytest.approx(250.0))
    assert risk.size(equity, 200)[:2] == (2, pytest.approx(200.0))


def test_stop_cap_blocks_before_target_and_sizing() -> None:
    assess = _first_cap(Settings(strategy={"sl_mode": "atr", "atr_sl_mult": 5.0}))
    assert assess is not None
    assert assess.signal is None
    assert assess.reject_code == "stop_cap"
    assert assess.event_metrics["stop_ticks"] > 200

    # El presupuesto del 1 % sí permitiría un contrato con 300 ticks; el cap
    # compartido rechaza antes de llegar al sizing y antes de calcular target.
    qty, amount, error = RiskManager(Settings()).size(equity=25_000.0, stop_ticks=300)
    assert error == ""
    assert qty == 1
    assert amount == pytest.approx(150.0)


def test_effective_fill_risk_gate_covers_slippage_and_preserves_3r() -> None:
    settings = Settings()
    settings.execution.slippage_ticks = 1
    settings.execution.max_slippage_ticks = 4
    signal = Signal(
        id="fill-gate",
        ts=timestamp_for(date(2025, 6, 3), "10:30"),
        direction="long",
        entry_price=20_000.0,
        stop=19_975.0,
        target=20_075.0,
        qty=5,
        risk_amount=250.0,
        signal_type="ORB",
        entry_reason="test",
        reference_level=0.0,
        breakout_level=0.0,
    )
    decision = RiskManager(settings).evaluate(
        signal,
        equity=25_000.0,
        open_positions=0,
        day_pnl=0.0,
        day_start_equity=25_000.0,
        trades_today=0,
        now_ts=signal.ts,
        last_exit_ts=None,
        consecutive_losses=0,
        has_pending_entry=False,
    )
    assert decision.ok is True
    assert decision.qty == 5
    assert decision.risk_amount == 250.0

    engine = ExecutionEngine(settings)
    engine.arm(replace(signal, ts=1000, qty=decision.qty, risk_amount=decision.risk_amount))
    engine.on_bar(Bar(1000, 20_000.0, 20_000.5, 19_999.5, 20_000.0))
    position = engine.position
    assert position is not None
    assert position.entry_price == pytest.approx(20_000.25)
    assert position.target == pytest.approx(20_075.0)
    assert position.risk_amount == pytest.approx(252.5)
    assert position.meta["planned_risk_amount"] == pytest.approx(250.0)

    passed, allowed = effective_fill_risk_gate(
        equity=25_000.0,
        qty_filled=position.qty,
        effective_fill_risk=position.risk_amount,
        tick_value=settings.execution.tick_value,
        max_slippage_ticks=settings.execution.max_slippage_ticks,
    )
    assert passed is True
    assert allowed == pytest.approx(260.0)

    failed, limit = effective_fill_risk_gate(
        equity=25_000.0,
        qty_filled=5,
        effective_fill_risk=352.5,
        tick_value=settings.execution.tick_value,
        max_slippage_ticks=settings.execution.max_slippage_ticks,
    )
    assert failed is False
    assert limit == pytest.approx(260.0)
