"""Tests del harness de continuación selectiva, sin tocar producción."""

from __future__ import annotations

import copy
import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from research.continuacion_selectiva import (
    ContinuationCandidate,
    ContinuationRule,
    HypothesisLockError,
    ValidationWindowError,
    assert_allowed_dates,
    assert_allowed_window,
    assert_control_settings,
    evaluate_candidate,
    evaluate_gates,
    load_hypothesis_lock,
    payload_sha256,
    scan_session,
)
from server.config import Settings
from server.market.sessions import is_trading_day
from server.models import Bar, Divergence
from server.timeutil import timestamp_for

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = json.loads(
    (ROOT / "tests" / "fixtures" / "continuacion_selectiva.json").read_text(
        encoding="utf-8"
    )
)


def _candidate(data: dict) -> ContinuationCandidate:
    return ContinuationCandidate.from_mapping(data)


def _rule() -> ContinuationRule:
    return ContinuationRule.from_lock(load_hypothesis_lock())


def test_lock_payload_matches_and_is_pre_registered() -> None:
    lock = load_hypothesis_lock()
    assert lock["status"] == "pre_registered_not_executed"
    assert lock["version"] == "1.1"
    assert lock["payload_sha256"] == payload_sha256(lock)
    assert lock["hypothesis_id"] == "H-CONT-SELECTIVA-2024"
    assert lock["validation"]["contract_suffixes"] == [
        "H24",
        "M24",
        "U24",
        "Z24",
        "H25",
    ]
    assert "inconclusive_min_continuation_trades" not in lock["gates"]


def test_tampered_lock_is_rejected(tmp_path: Path) -> None:
    source = json.loads(
        (ROOT / "docs" / "hipotesis_continuacion_selectiva.lock.json").read_text(
            encoding="utf-8"
        )
    )
    source["rule"]["extension"]["min"] = 0.8
    target = tmp_path / "lock.json"
    target.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(HypothesisLockError, match="alterado"):
        load_hypothesis_lock(target)


def test_executed_lock_is_rejected(tmp_path: Path) -> None:
    source = json.loads(
        (ROOT / "docs" / "hipotesis_continuacion_selectiva.lock.json").read_text(
            encoding="utf-8"
        )
    )
    source["status"] = "executed"
    target = tmp_path / "executed.json"
    target.write_text(json.dumps(source), encoding="utf-8")

    with pytest.raises(HypothesisLockError, match="pre_registered_not_executed"):
        load_hypothesis_lock(target)


def test_control_is_150_12_200() -> None:
    assert_control_settings(Settings())

    active = Settings().model_copy(deep=True)
    active.strategy.setup_validity_minutes = 240
    active.strategy.retest_tolerance_ticks = 24
    active.risk.max_sl_ticks = 300
    with pytest.raises(ValueError, match="Control distinto"):
        assert_control_settings(active)


def test_protocol_lock_control_is_150_12_200() -> None:
    protocol = json.loads(
        (ROOT / "docs" / "protocolo_backtest.lock.json").read_text(encoding="utf-8")
    )
    settings = protocol["settings"]
    assert settings["strategy"]["entry_reference"] == "or_mid"
    assert settings["strategy"]["use_smt"] is True
    assert settings["strategy"]["setup_validity_minutes"] == 150
    assert settings["strategy"]["retest_tolerance_ticks"] == 12
    assert settings["risk"]["max_sl_ticks"] == 200


def test_2024_calendar_has_251_sessions() -> None:
    start = date(2024, 1, 2)
    end = date(2024, 12, 30)
    sessions = [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if is_trading_day(start + timedelta(days=offset))
    ]
    assert len(sessions) == 251
    assert sessions[0] == start
    assert sessions[-1] == end
    assert 251 - 4 == 247


def test_candidate_outside_2024_is_rejected() -> None:
    data = copy.deepcopy(FIXTURE["valid_candidate"])
    data["session_date"] = "2025-01-10"

    with pytest.raises(ValidationWindowError, match="W1-W6"):
        evaluate_candidate(_candidate(data), _rule())


def test_allowed_2024_dates_pass() -> None:
    assert assert_allowed_dates(FIXTURE["dates"]["allowed"]) == (
        date(2024, 1, 2),
        date(2024, 12, 30),
    )


@pytest.mark.parametrize(
    "key",
    ["w1", "w6", "holdout_start", "holdout_end"],
)
def test_w1_w6_and_holdout_dates_are_rejected(key: str) -> None:
    with pytest.raises(ValidationWindowError, match="prohibida|sellado"):
        assert_allowed_dates([FIXTURE["dates"][key]])


def test_outside_2024_is_rejected() -> None:
    with pytest.raises(ValidationWindowError, match="fuera de la muestra 2024"):
        assert_allowed_dates([FIXTURE["dates"]["outside"]])


def test_windows_overlapping_prohibited_samples_are_rejected() -> None:
    assert_allowed_window(date(2024, 1, 2), date(2024, 12, 30))
    with pytest.raises(ValidationWindowError, match="W1-W6"):
        assert_allowed_window(date(2024, 12, 30), date(2025, 1, 10))
    with pytest.raises(ValidationWindowError, match="holdout"):
        assert_allowed_window(date(2026, 7, 1), date(2026, 7, 2))


def test_valid_fixture_candidate_is_accepted() -> None:
    decision = evaluate_candidate(_candidate(FIXTURE["valid_candidate"]), _rule())

    assert decision.accepted is True
    assert decision.reasons == ()
    signal = decision.signal
    assert signal is not None
    assert signal.direction == "long"
    assert signal.age_minutes == 45.0
    assert signal.extension_atr == 2.0
    assert signal.entry_price == pytest.approx(104.1)
    assert signal.stop == pytest.approx(99.5)
    assert signal.target == pytest.approx(117.9)
    assert signal.stop_ticks == pytest.approx(18.4)
    assert signal.smt_bias == "bullish"


@pytest.mark.parametrize(
    "case",
    FIXTURE["invalid_cases"],
    ids=[case["name"] for case in FIXTURE["invalid_cases"]],
)
def test_invalid_fixture_cases_are_rejected(case: dict) -> None:
    data = copy.deepcopy(FIXTURE["valid_candidate"])
    data.update(copy.deepcopy(case["patch"]))

    decision = evaluate_candidate(_candidate(data), _rule())

    assert decision.accepted is False
    assert case["reason"] in decision.reasons


def _bars_for_scan(day: date) -> tuple[list[Bar], list[Bar], Divergence]:
    """Sesión 1m construida a mano: OR, ruptura, continuación y SMT inyectada."""

    def bar(minute: int, open_: float, high: float, low: float, close: float) -> Bar:
        hhmm = f"{minute // 60:02d}:{minute % 60:02d}"
        return Bar(timestamp_for(day, hhmm), open_, high, low, close)

    nq: list[Bar] = []
    es: list[Bar] = []
    for minute in range(9 * 60, 11 * 60 + 20):
        if minute < 10 * 60:
            nq.append(bar(minute, 10000.0, 10001.5, 9998.5, 10000.0))
        elif minute < 10 * 60 + 15:
            nq.append(bar(minute, 10000.0, 10004.5, 10000.0, 10004.0))
        elif minute < 10 * 60 + 30:
            nq.append(bar(minute, 10004.0, 10005.0, 10003.5, 10004.5))
        elif minute < 10 * 60 + 45:
            nq.append(bar(minute, 10004.5, 10005.5, 10004.0, 10005.0))
        elif minute < 11 * 60:
            nq.append(bar(minute, 10005.0, 10006.5, 10004.5, 10006.0))
        elif minute == 11 * 60:
            nq.append(bar(minute, 10006.25, 10007.0, 10006.0, 10006.5))
        else:
            nq.append(bar(minute, 10006.5, 10007.0, 10006.0, 10006.5))
        es.append(bar(minute, 5000.0, 5000.5, 4999.5, 5000.0))

    divergence = Divergence(
        bias="bullish",
        level=9999.0,
        primary_prev=9998.0,
        primary_last=9999.0,
        reference_prev=4998.0,
        reference_last=4998.5,
        confirm_ts=timestamp_for(day, "10:00"),
        expires_ts=timestamp_for(day, "12:00"),
        pivot_ts=timestamp_for(day, "09:55"),
    )
    return nq, es, divergence


def test_scan_session_produces_a_causal_continuation_signal() -> None:
    day = date(2024, 3, 12)
    nq, es, divergence = _bars_for_scan(day)

    result = scan_session(
        day,
        nq,
        es,
        settings=Settings(),
        rule=_rule(),
        divergences=[divergence],
    )

    assert result.breakout is not None
    assert result.breakout["direction"] == "long"
    signal = result.signal
    assert signal is not None
    assert signal.signal_bar_ts == timestamp_for(day, "10:45")
    assert signal.signal_ts == timestamp_for(day, "11:00")
    assert signal.entry_ts == signal.signal_ts
    assert signal.entry_price == pytest.approx(10006.25)
    assert signal.smt_bias == "bullish"
    assert signal.age_minutes == 45.0


def test_scan_session_rejects_a_custom_rule() -> None:
    day = date(2024, 3, 12)
    with pytest.raises(ValueError, match="regla del escáner"):
        scan_session(
            day,
            [],
            [],
            settings=Settings(),
            rule=ContinuationRule(min_extension_atr=0.5),
        )


def test_scan_session_refuses_w1_before_reading_bars() -> None:
    with pytest.raises(ValidationWindowError, match="W1-W6"):
        scan_session(date(2025, 1, 10), [], [], settings=Settings(), rule=_rule())


def test_gate_fixture_passes() -> None:
    decision = evaluate_gates(**copy.deepcopy(FIXTURE["gates"]))

    assert decision.status == "candidate_for_paper_not_live"
    assert {gate.id for gate in decision.gates} == {
        "C1",
        "C2",
        "C3",
        "C4",
        "C5",
        "C6",
        "C7",
        "C8",
    }
    assert all(gate.passed for gate in decision.gates)


def test_gate_sample_rejects_w1() -> None:
    data = copy.deepcopy(FIXTURE["gates"])
    data["sample"]["start"] = "2025-01-10"
    data["sample"]["end"] = "2025-03-31"

    with pytest.raises(ValidationWindowError, match="W1-W6"):
        evaluate_gates(**data)


def test_gate_sample_requires_2024_contracts() -> None:
    data = copy.deepcopy(FIXTURE["gates"])
    data["sample"]["contract_suffixes"] = ["H25"]

    with pytest.raises(ValidationWindowError, match="contratos 2024"):
        evaluate_gates(**data)


def test_low_sample_is_inconclusive_not_promoted() -> None:
    data = copy.deepcopy(FIXTURE["gates"])
    data["continuation"]["trades"] = 10

    decision = evaluate_gates(**data)

    assert decision.status == "inconclusive"
    c2 = next(gate for gate in decision.gates if gate.id == "C2")
    assert c2.status == "inconclusive"


def test_failed_edge_is_rejected() -> None:
    data = copy.deepcopy(FIXTURE["gates"])
    data["continuation"]["profit_factor"] = 1.0

    decision = evaluate_gates(**data)

    assert decision.status == "rejected"
    c3 = next(gate for gate in decision.gates if gate.id == "C3")
    assert c3.status == "fail"


def test_excess_drawdown_is_rejected() -> None:
    data = copy.deepcopy(FIXTURE["gates"])
    data["portfolio"]["max_drawdown"] = 2600.0

    decision = evaluate_gates(**data)

    assert decision.status == "rejected"
    c5 = next(gate for gate in decision.gates if gate.id == "C5")
    assert c5.status == "fail"


def test_zero_quarter_counts_as_non_negative() -> None:
    data = copy.deepcopy(FIXTURE["gates"])
    data["quarters"][1] = {"trades": 6, "net_profit": 0.0, "profit_factor": 1.0}

    decision = evaluate_gates(**data)

    c6 = next(gate for gate in decision.gates if gate.id == "C6")
    assert c6.status == "pass"


def test_bad_quarter_is_rejected() -> None:
    data = copy.deepcopy(FIXTURE["gates"])
    data["quarters"][0] = {"trades": 10, "net_profit": 10.0, "profit_factor": 0.5}

    decision = evaluate_gates(**data)

    assert decision.status == "rejected"
    c6 = next(gate for gate in decision.gates if gate.id == "C6")
    assert c6.status == "fail"
