"""Tests sintéticos del diseño de validación por bloques.

No leen datos de mercado, no ejecutan backtests y no tocan configuración,
presets ni holdout. Solo comprueban el contrato del diseño.
"""

from __future__ import annotations

from datetime import date

import pytest

from research.validacion_bloques import (
    BlockSample,
    BlockValidationError,
    PlaceboCandidate,
    SequentialAlphaSpending,
    design_spec,
    evaluate_validation,
    generate_placebo_entries,
    paired_block_bootstrap,
    validate_blocks,
)


def _block(
    block_id: str,
    candidate: list[float] | tuple[float, ...],
    baseline: list[float] | tuple[float, ...],
    placebo: list[float] | tuple[float, ...] | None = None,
) -> BlockSample:
    return BlockSample(
        block_id=block_id,
        candidate_r=tuple(candidate),
        baseline_r=tuple(baseline),
        placebo_r=tuple(placebo or ()),
    )


def _constant_blocks(
    candidate_r: float,
    *,
    baseline_r: float = 0.0,
    placebo_r: float = 0.0,
    trades: int = 20,
) -> list[BlockSample]:
    return [
        _block(
            f"b{index}",
            [candidate_r] * trades,
            [baseline_r] * trades,
            [placebo_r] * trades,
        )
        for index in range(1, 5)
    ]


def test_block_sample_rejects_non_finite_values() -> None:
    with pytest.raises(BlockValidationError, match="no finitos"):
        _block("b1", [0.1, float("nan")], [0.0, 0.0])


def test_block_sample_rejects_placebo_length_mismatch() -> None:
    with pytest.raises(BlockValidationError, match="placebo_r"):
        _block("b1", [0.1, 0.0], [0.0, 0.0], [0.0])


def test_validate_blocks_requires_minimum_in_every_block() -> None:
    blocks = _constant_blocks(0.10)
    result = validate_blocks(blocks, min_trades_per_block=20)
    assert result.status == "ready"
    assert result.candidate_trades == 80
    assert result.baseline_trades == 80
    assert result.placebo_trades == 80

    blocks[2] = _block("b3", [0.10] * 19, [0.0] * 20, [0.0] * 19)
    result = validate_blocks(blocks, min_trades_per_block=20)
    assert result.status == "insufficient"
    assert any("b3" in blocker and "candidato" in blocker for blocker in result.blockers)


def test_validate_blocks_does_not_pool_a_small_block() -> None:
    blocks = _constant_blocks(0.10)
    blocks[0] = _block("b1", [0.10] * 2, [0.0] * 2, [0.0] * 2)
    result = validate_blocks(blocks, min_trades_per_block=20)
    assert result.status == "insufficient"
    assert result.candidate_trades == 62


def test_validate_blocks_requires_placebo_unless_disabled() -> None:
    blocks = [
        _block(f"b{index}", [0.10] * 20, [0.0] * 20)
        for index in range(1, 5)
    ]
    required = validate_blocks(blocks, require_placebo=True)
    assert required.status == "insufficient"
    assert all("placebo ausente" in blocker for blocker in required.blockers)

    optional = validate_blocks(blocks, require_placebo=False)
    assert optional.status == "ready"


def test_paired_bootstrap_is_reproducible_and_paired() -> None:
    blocks = [
        _block("b1", [0.05] * 20, [0.0] * 20),
        _block("b2", [0.10] * 20, [0.0] * 20),
        _block("b3", [0.15] * 20, [0.0] * 20),
        _block("b4", [0.20] * 20, [0.0] * 20),
    ]
    first = paired_block_bootstrap(blocks, resamples=2_000, seed=7)
    second = paired_block_bootstrap(blocks, resamples=2_000, seed=7)

    assert first == second
    assert first.control == "baseline"
    assert first.block_ids == ("b1", "b2", "b3", "b4")
    assert first.block_differences == pytest.approx((0.05, 0.10, 0.15, 0.20))
    assert first.observed_diff == pytest.approx(0.125)
    assert first.p_value_one_sided < 0.01
    assert first.ci_low > 0.0
    assert first.ci_high < 0.30


def test_paired_bootstrap_zero_effect_is_not_significant() -> None:
    blocks = _constant_blocks(0.10, baseline_r=0.10)
    result = paired_block_bootstrap(blocks, resamples=500, seed=11)
    assert result.observed_diff == pytest.approx(0.0)
    assert result.ci_low == pytest.approx(0.0)
    assert result.ci_high == pytest.approx(0.0)
    assert result.p_value_one_sided == pytest.approx(1.0)


def test_paired_bootstrap_constant_effect_has_narrow_ci() -> None:
    blocks = _constant_blocks(0.10)
    result = paired_block_bootstrap(blocks, resamples=500, seed=11)
    assert result.observed_diff == pytest.approx(0.10)
    assert result.ci_low == pytest.approx(0.10)
    assert result.ci_high == pytest.approx(0.10)
    assert result.p_value_one_sided < 0.01


def test_paired_bootstrap_uses_placebo_arm() -> None:
    blocks = _constant_blocks(0.10, placebo_r=0.0)
    result = paired_block_bootstrap(blocks, control="placebo", resamples=500, seed=2)
    assert result.control == "placebo"
    assert result.observed_diff == pytest.approx(0.10)
    assert result.p_value_one_sided < 0.01


def test_paired_bootstrap_rejects_invalid_inputs() -> None:
    blocks = _constant_blocks(0.10)
    with pytest.raises(BlockValidationError, match="al menos 2 bloques"):
        paired_block_bootstrap(blocks[:1])
    with pytest.raises(BlockValidationError, match="resamples"):
        paired_block_bootstrap(blocks, resamples=99)
    with pytest.raises(BlockValidationError, match="control"):
        paired_block_bootstrap(blocks, control="other")  # type: ignore[arg-type]


def test_alpha_spending_matches_obf_for_two_looks() -> None:
    alpha = SequentialAlphaSpending()
    assert alpha.looks == 2
    assert alpha.cumulative_alpha[-1] == pytest.approx(0.05, abs=1e-12)
    assert sum(alpha.nominal_alphas) == pytest.approx(0.05, abs=1e-12)
    assert alpha.nominal_alphas[0] == pytest.approx(0.0100046269, abs=1e-9)
    assert alpha.nominal_alphas[1] == pytest.approx(0.0399953731, abs=1e-9)
    assert alpha.z_boundaries[0] == pytest.approx(2.326174307, abs=1e-9)
    assert alpha.z_boundaries[1] == pytest.approx(1.750739766, abs=1e-9)
    assert alpha.z_boundaries[0] > alpha.z_boundaries[1]


def test_alpha_spending_decisions_use_nominal_levels() -> None:
    alpha = SequentialAlphaSpending()
    assert alpha.decide(0.005, 1).status == "efficacy"
    assert alpha.decide(0.020, 1).status == "continue"
    assert alpha.decide(0.030, 2).status == "efficacy"
    assert alpha.decide(0.045, 2).status == "no_efficacy"
    assert alpha.nominal_alpha(2) == pytest.approx(0.0399953731, abs=1e-9)
    assert alpha.z_boundary(2) == pytest.approx(1.750739766, abs=1e-9)


@pytest.mark.parametrize(
    "fractions",
    [
        (),
        (0.5, 0.9),
        (0.5, 0.5),
        (0.0, 1.0),
        (0.5, 1.1),
    ],
)
def test_alpha_spending_rejects_invalid_fractions(
    fractions: tuple[float, ...],
) -> None:
    with pytest.raises(BlockValidationError):
        SequentialAlphaSpending(information_fractions=fractions)


def test_alpha_spending_rejects_invalid_parameters() -> None:
    with pytest.raises(BlockValidationError, match="total_alpha"):
        SequentialAlphaSpending(total_alpha=0.0)
    with pytest.raises(BlockValidationError, match="sides"):
        SequentialAlphaSpending(sides=3)
    with pytest.raises(BlockValidationError, match="method"):
        SequentialAlphaSpending(method="pocock")
    with pytest.raises(BlockValidationError, match="look"):
        SequentialAlphaSpending().decide(0.01, 3)


def test_placebo_generator_preserves_session_and_direction() -> None:
    day1 = date(2024, 1, 2)
    day2 = date(2024, 1, 3)
    candidates = [
        PlaceboCandidate(day1, "long", 100),
        PlaceboCandidate(day1, "short", 200),
        PlaceboCandidate(day2, "long", 300),
    ]
    eligible = {
        day1: [100, 110, 120],
        day2: [300, 310, 320],
    }
    first = generate_placebo_entries(candidates, eligible, seed=42)
    second = generate_placebo_entries(candidates, eligible, seed=42)

    assert first == second
    assert len(first.entries) == 3
    assert first.seed == 42
    assert first.method == "same_session_same_direction_uniform_entry_minute"
    for source, entry in zip(candidates, first.entries):
        assert entry.session == source.session
        assert entry.direction == source.direction
        assert entry.source_entry_ts == source.entry_ts
        assert entry.entry_ts in eligible[source.session]
        assert entry.entry_ts != source.entry_ts


def test_placebo_generator_accepts_iso_session_keys() -> None:
    day = date(2024, 1, 2)
    candidates = [PlaceboCandidate(day, "long", 100)]
    plan = generate_placebo_entries(candidates, {"2024-01-02": [100, 110]}, seed=1)
    assert plan.entries[0].session == day
    assert plan.entries[0].entry_ts == 110


def test_placebo_generator_requires_an_alternative_entry() -> None:
    day = date(2024, 1, 2)
    with pytest.raises(BlockValidationError, match="distintos"):
        generate_placebo_entries(
            [PlaceboCandidate(day, "long", 100)],
            {day: [100]},
            seed=1,
        )


def test_placebo_generator_rejects_unknown_method() -> None:
    day = date(2024, 1, 2)
    with pytest.raises(BlockValidationError, match="method"):
        generate_placebo_entries(
            [PlaceboCandidate(day, "long", 100)],
            {day: [100, 110]},
            seed=1,
            method="bootstrap",
        )


def test_placebo_generator_empty_candidates_is_empty_plan() -> None:
    plan = generate_placebo_entries([], {}, seed=1)
    assert plan.entries == ()
    assert plan.duplicate_entries == 0


def test_evaluate_validation_passes_when_all_gates_are_met() -> None:
    blocks = _constant_blocks(0.10)
    outcome = evaluate_validation(blocks, resamples=2_000, seed=3)

    assert outcome.status == "pass"
    assert outcome.look == 2
    assert outcome.blocks_observed == 4
    assert outcome.validation.status == "ready"
    assert outcome.baseline is not None
    assert outcome.baseline.observed_diff == pytest.approx(0.10)
    assert outcome.baseline.ci_low == pytest.approx(0.10)
    assert outcome.placebo is not None
    assert outcome.placebo.ci_low == pytest.approx(0.10)
    assert outcome.sequential is not None
    assert outcome.sequential.status == "efficacy"
    assert outcome.target_met is True
    assert outcome.placebo_met is True
    assert outcome.blockers == ()


def test_evaluate_validation_is_inconclusive_if_one_block_is_small() -> None:
    blocks = _constant_blocks(0.10)
    blocks[2] = _block("b3", [0.10] * 19, [0.0] * 20, [0.0] * 19)
    outcome = evaluate_validation(blocks, resamples=500, seed=3)

    assert outcome.status == "inconclusive"
    assert outcome.baseline is None
    assert outcome.sequential is None
    assert any("b3" in blocker for blocker in outcome.blockers)


def test_evaluate_validation_is_inconclusive_placebo_when_placebo_matches() -> None:
    blocks = _constant_blocks(0.10, placebo_r=0.10)
    outcome = evaluate_validation(blocks, resamples=1_000, seed=3)

    assert outcome.status == "inconclusive_placebo"
    assert outcome.target_met is True
    assert outcome.placebo_met is False
    assert outcome.placebo is not None
    assert outcome.placebo.ci_low == pytest.approx(0.0)
    assert "placebo_ci_not_above_zero" in outcome.blockers


def test_evaluate_validation_fails_if_target_effect_is_not_met() -> None:
    blocks = _constant_blocks(0.05)
    outcome = evaluate_validation(blocks, resamples=1_000, seed=3)

    assert outcome.status == "fail"
    assert outcome.sequential is not None
    assert outcome.sequential.status == "efficacy"
    assert outcome.target_met is False
    assert "target_effect_not_met" in outcome.blockers


def test_evaluate_validation_final_no_efficacy_fails() -> None:
    blocks = _constant_blocks(0.0)
    outcome = evaluate_validation(blocks, resamples=500, seed=3)

    assert outcome.status == "fail"
    assert outcome.sequential is not None
    assert outcome.sequential.status == "no_efficacy"
    assert "final_p_value_above_nominal_alpha" in outcome.blockers


def test_evaluate_validation_interim_continues_when_target_not_met() -> None:
    blocks = _constant_blocks(0.05)
    outcome = evaluate_validation(blocks, look=1, resamples=1_000, seed=3)

    assert outcome.status == "continue"
    assert outcome.blocks_observed == 2
    assert outcome.sequential is not None
    assert outcome.sequential.status == "efficacy"
    assert outcome.target_met is False
    assert "target_effect_not_met" in outcome.blockers


def test_evaluate_validation_requires_exactly_four_blocks() -> None:
    with pytest.raises(BlockValidationError, match="4 bloques"):
        evaluate_validation(_constant_blocks(0.10)[:3])


def test_evaluate_validation_rejects_invalid_look() -> None:
    with pytest.raises(BlockValidationError, match="look"):
        evaluate_validation(_constant_blocks(0.10), look=3)


def test_design_spec_is_explicitly_design_only() -> None:
    spec = design_spec()
    assert spec["schema"] == "validacion-bloques-v1"
    assert spec["status"] == "design_only_not_executed"
    assert spec["blocks"]["count"] == 4
    assert spec["blocks"]["min_trades_per_block"] == 20
    assert spec["blocks"]["min_total_candidate_trades"] == 80
    assert spec["endpoint"]["target_effect_r"] == 0.10
    assert spec["alpha_spending"]["total_alpha"] == 0.05
    assert spec["alpha_spending"]["sides"] == 1
    assert spec["placebo"]["seed"] == 20261121
    assert spec["execution"] == {
        "design_only": True,
        "validation_executed": False,
        "backtests_run": 0,
        "holdout_opened": False,
        "config_modified": False,
    }
