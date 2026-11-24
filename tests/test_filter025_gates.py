"""Tests de la evaluacion de gates del filtro 0,25 sobre artefactos W1-W6.

No ejecutan backtests: importan el evaluador y leen los JSON ya congelados.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "reports" / "backtest"))

import filter025_gates as gates  # noqa: E402


def _by_id(report: dict) -> dict[str, dict]:
    return {gate["id"]: gate for gate in report["gates"]}


def test_real_artifacts_produce_inconclusive_global_verdict() -> None:
    report = gates.evaluate(write=False)

    assert report["schema"] == "filter025-gates-v1"
    assert report["scope"] == "historical_w1_w6_read_only"
    assert report["backtest_executed"] is False
    assert report["holdout_read"] is False
    assert report["aggregate"]["accepted"]["trades"] == 17
    assert report["aggregate"]["baseline"]["trades"] == 46
    assert report["aggregate"]["rejected"]["trades"] == 29
    assert report["summary"]["global"] == "INCONCLUSO"
    assert report["summary"]["PASS"] == 13
    assert report["summary"]["FALLA"] == 4
    assert report["summary"]["INCONCLUSO"] == 5
    assert report["summary"]["NO_EVALUABLE"] == 1
    assert report["decision"]["promotion"] == "NO"


def test_quarterly_coverage_concentration_and_rejected_consistency_are_discriminating() -> None:
    report = gates.evaluate(write=False)
    by_id = _by_id(report)

    coverage = by_id["Q1_QUARTER_COVERAGE"]
    assert coverage["state"] == "FALLA"
    assert coverage["values"]["active_quarters"] == 4
    assert coverage["values"]["empty_blocks"] == ["W5", "W6"]
    assert report["quarterly"]["blocks"][4]["accepted"] == 0
    assert report["quarterly"]["blocks"][5]["accepted"] == 0

    concentration = by_id["Q3_QUARTER_CONCENTRATION"]
    assert concentration["state"] == "FALLA"
    assert concentration["values"]["top2_share_pct"] == 85.28
    assert concentration["values"]["top2_share_pct"] > 80.0

    rejected = by_id["Q4_REJECTED_CONSISTENCY"]
    assert rejected["state"] == "FALLA"
    assert rejected["values"]["passing_quarters"] == 3
    assert rejected["values"]["empty_rejected_blocks"] == ["W4"]

    consistency = by_id["Q2_QUARTER_CONSISTENCY"]
    assert consistency["state"] == "PASS"
    assert consistency["values"]["active_quarters"] == 4
    assert consistency["values"]["positive_active"] == 3
    assert consistency["values"]["positive_share"] == 0.75


def test_bootstrap_positive_numeric_result_cannot_pass_without_sample_or_coverage() -> None:
    report = gates.evaluate(write=False)
    gate = _by_id(report)["E2_BOOTSTRAP"]

    assert gate["state"] == "INCONCLUSO"
    assert gate["values"]["ci_lower"] > 0
    assert gate["values"]["numeric_ci_lower_positive"] is True
    assert gate["values"]["sample_ok"] is False
    assert gate["values"]["coverage_ok"] is False
    assert gate["values"]["min_valid_resamples_ok"] is True
    assert gate["values"]["valid_resamples"] >= 9500
    assert report["bootstrap"]["ci_lower"] > 0
    assert "no puede dar PASS" in gate["reason"]


def test_old_trivial_block_gate_is_replaced_by_active_discriminating_gates() -> None:
    report = gates.evaluate(write=False)
    demo = report["recalibration_demo"]

    assert demo["old_G7"]["state"] == "PASS"
    assert demo["old_G7"]["empty_blocks"] == ["W5", "W6"]
    assert demo["old_G7"]["old_min_reachable"] is False
    assert demo["old_G7"]["max_block_trades"] == 8
    assert demo["old_G7"]["old_min_trades"] == 15
    assert demo["new_Q1_coverage"]["state"] == "FALLA"
    assert demo["new_Q3_concentration"]["state"] == "FALLA"
    assert demo["new_Q4_rejected_consistency"]["state"] == "FALLA"
    assert demo["old_trivial_gate_now_fails"] is True

    block_gate = _by_id(report)["Q5_BLOCK_PF"]
    assert block_gate["state"] == "PASS"
    assert block_gate["values"]["old_min_trades"] == 15
    assert block_gate["values"]["new_min_trades"] == 3
    assert block_gate["values"]["old_min_reachable"] is False
    assert len(block_gate["values"]["eligible_blocks"]) == 3


def test_unreachable_sample_minima_are_inconclusive_not_pass() -> None:
    report = gates.evaluate(write=False)
    by_id = _by_id(report)

    for gate_id in ("S0_TOTAL_SAMPLE", "S2_BASELINE", "S3_COHORT", "S4_BLOCK_SAMPLE"):
        assert by_id[gate_id]["state"] == "INCONCLUSO", gate_id
    assert by_id["S0_TOTAL_SAMPLE"]["values"]["trades"] == 17
    assert by_id["S0_TOTAL_SAMPLE"]["values"]["shorts"] == 8
    assert by_id["S2_BASELINE"]["values"]["baseline"] == 46
    assert by_id["S3_COHORT"]["values"]["accepted"] == 17
    assert by_id["S3_COHORT"]["values"]["rejected"] == 29
    assert by_id["S4_BLOCK_SAMPLE"]["values"]["qualifying_blocks"] == 2


def test_cost_gate_is_not_faked_with_an_incompatible_stress_artifact() -> None:
    report = gates.evaluate(write=False)
    gate = _by_id(report)["P6_COST_STRESS"]

    assert gate["state"] == "NO_EVALUABLE"
    assert gate["values"]["artifact"] is None
    assert gate["values"]["gate_used"] is False


def test_config_declares_recalibrated_thresholds_and_input_scope() -> None:
    config = json.loads(
        (ROOT / "reports" / "backtest" / "filter025_gates.config.json").read_text(
            encoding="utf-8"
        )
    )
    assert config["filter_threshold"] == 0.25
    assert config["sample"]["min_accepted"] == 24
    assert config["sample"]["min_rejected"] == 30
    assert config["bootstrap"]["min_accepted"] == 24
    assert config["bootstrap"]["min_rejected"] == 30
    assert config["bootstrap"]["min_active_quarters"] == 5
    assert config["quarterly"]["min_active_quarters"] == 5
    assert config["quarterly"]["max_top2_net_share_pct"] == 80.0
    assert config["monthly"]["max_zero_month_streak"] == 4
    assert config["inputs"]["filter_artifact"].endswith(
        "_manual_filter025_w1_w6.json"
    )


def test_output_artifact_matches_evaluator_contract() -> None:
    output = json.loads(
        (ROOT / "reports" / "backtest" / "filter025_gates.json").read_text(
            encoding="utf-8"
        )
    )
    assert output["schema"] == "filter025-gates-v1"
    assert output["summary"]["global"] == "INCONCLUSO"
    assert output["decision"]["global"] == "INCONCLUSO"
    assert output["holdout_read"] is False
    assert output["backtest_executed"] is False
    assert len(output["gates"]) == len({gate["id"] for gate in output["gates"]})
    assert all(gate.get("reason") for gate in output["gates"])
