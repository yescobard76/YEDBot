"""Pruebas del backtester y de las métricas."""

from __future__ import annotations

import math
import statistics
from datetime import date

import pytest

from server.backtest import (
    DEFAULT_PRESETS,
    PRESETS,
    PROTECTED_PRESET_PATHS,
    resolve_presets,
    run_backtest,
    run_presets,
    run_variants,
)
from server.config import Settings
from server.stats import compute_stats
from server.timeutil import timestamp_for


def test_backtest_runs_and_reports_source():
    settings = Settings()
    result = run_backtest(settings, days=3, label="test")
    assert result["data_source"] == "synthetic"
    assert result["is_synthetic"] is True
    assert result["dataset"]["code"]["sha256"]
    m = result["metrics"]
    for key in ("win_rate", "profit_factor", "expectancy", "max_drawdown", "sharpe", "sortino", "net_profit"):
        assert key in m
    assert m["trades"] == len(result["trades"])
    assert len(result["equity"]) >= 1
    report = result["diagnostics"]["ambiguous_bars"]
    assert report["count"] == len(report["items"])
    assert m["ambiguous_bars"] == report["count"]
    assert result["diagnostics"]["intrabar_model"]["ambiguous_bar"] == "stop_loss_first"


def test_variants_share_dataset_and_differ_in_config():
    settings = Settings()
    results = run_variants(settings, days=3)
    assert len(results) == 4
    types = {r["variant"]: r["config"]["strategy"]["entry_reference"] for r in results}
    assert types["full"] == "or_mid"
    assert types["orb"] == "none"
    assert results[-1]["config"]["strategy"]["use_smt"] is True


def test_stats_math_on_known_trades():
    trades = [
        {"pnl": 300, "r_multiple": 3, "exit_ts": 1000, "entry_ts": 900, "direction": "long", "duration_sec": 100, "fees": 1},
        {"pnl": -100, "r_multiple": -1, "exit_ts": 2000, "entry_ts": 1900, "direction": "long", "duration_sec": 100, "fees": 1},
        {"pnl": -100, "r_multiple": -1, "exit_ts": 3000, "entry_ts": 2900, "direction": "short", "duration_sec": 100, "fees": 1},
        {"pnl": 300, "r_multiple": 3, "exit_ts": 4000, "entry_ts": 3900, "direction": "short", "duration_sec": 100, "fees": 1},
    ]
    s = compute_stats(trades, 25_000)
    assert s["trades"] == 4
    assert s["win_rate"] == 50.0
    assert s["profit_factor"] == 3.0
    assert s["net_profit"] == 400
    assert s["expectancy"] == 100
    assert s["max_drawdown"] == 200
    assert s["avg_r"] == 1.0


def test_sharpe_and_sortino_include_sessions_without_trades():
    days = [date(2025, 6, 3), date(2025, 6, 4), date(2025, 6, 5)]

    def trade(pnl: float, day: date) -> dict:
        return {
            "pnl": pnl,
            "r_multiple": pnl / 100,
            "entry_ts": timestamp_for(day, "10:00"),
            "exit_ts": timestamp_for(day, "15:59"),
            "direction": "long",
            "duration_sec": 60,
            "fees": 1,
        }

    trades = [trade(100.0, days[0]), trade(-50.0, days[2])]
    stats = compute_stats(trades, 1_000.0, sessions=days)

    returns = [0.1, 0.0, -0.05]
    expected_sharpe = round(
        statistics.fmean(returns) / statistics.pstdev(returns) * math.sqrt(252), 2
    )
    downside = [r for r in returns if r < 0]
    expected_sortino = round(
        statistics.fmean(returns)
        / math.sqrt(sum(r * r for r in downside) / len(returns))
        * math.sqrt(252),
        2,
    )

    assert [row["pnl"] for row in stats["daily"]] == [100.0, 0.0, -50.0]
    assert stats["sharpe"] == expected_sharpe
    assert stats["sortino"] == expected_sortino
    assert compute_stats(trades, 1_000.0)["sharpe"] != expected_sharpe


def test_backtest_rejects_out_of_range_days_instead_of_clamping():
    with pytest.raises(ValueError, match="entre 3 y 250"):
        run_backtest(Settings(), days=2)
    with pytest.raises(ValueError, match="entre 3 y 250"):
        run_variants(Settings(), days=251)


def _patch_paths(patch: dict, prefix: tuple[str, ...] = ()):
    for key, value in patch.items():
        path = (*prefix, key)
        if isinstance(value, dict):
            yield from _patch_paths(value, path)
        else:
            yield path


def test_presets_do_not_override_structural_rules():
    assert "baseline" in PRESETS and "baseline" in DEFAULT_PRESETS
    assert set(DEFAULT_PRESETS) <= set(PRESETS)
    assert len(DEFAULT_PRESETS) == len(set(DEFAULT_PRESETS))
    for key, preset in PRESETS.items():
        touched = set(_patch_paths(preset["patch"]))
        forbidden = touched & PROTECTED_PRESET_PATHS
        assert not forbidden, f"{key} modifica reglas protegidas: {forbidden}"


def test_risk_control_presets_only_relax_stop_cap():
    control = PRESETS["sl_cap_600"]["patch"]
    or_level = PRESETS["entry_or_level_sl_cap_600"]["patch"]
    direct = PRESETS["direct_sl_cap_600"]["patch"]
    deep = PRESETS["deep_stop_sl_cap_600"]["patch"]
    for patch in (control, or_level, direct, deep):
        assert patch["risk"] == {"max_sl_ticks": 600}
        assert "risk_per_trade_pct" not in patch["risk"]
        assert "max_contracts" not in patch["risk"]
    assert control == {"risk": {"max_sl_ticks": 600}}
    assert or_level == {
        "strategy": {"entry_reference": "breakout_level"},
        "risk": {"max_sl_ticks": 600},
    }
    assert direct["strategy"] == {"entry_reference": "none"}
    assert deep["strategy"] == {"structural_depth": 6, "sl_buffer_ticks": 12}
    assert "sl_cap_600" not in DEFAULT_PRESETS
    assert "entry_or_level_sl_cap_600" not in DEFAULT_PRESETS


def test_retest_tolerance_presets_are_opt_in():
    for ticks in (24, 40):
        key = f"retest_tolerance_{ticks}"
        assert key in PRESETS
        assert key not in DEFAULT_PRESETS
        assert PRESETS[key]["patch"] == {
            "strategy": {"retest_tolerance_ticks": ticks}
        }
    assert PRESETS["setup_validity_180"]["patch"] == {
        "strategy": {"setup_validity_minutes": 180}
    }
    assert PRESETS["setup_validity_240"]["patch"] == {
        "strategy": {"setup_validity_minutes": 240}
    }


def test_resolve_presets_always_starts_with_baseline():
    assert resolve_presets(["sl_depth_6"]) == ["baseline", "sl_depth_6"]
    assert resolve_presets(["baseline", "sl_depth_6", "sl_depth_6"]) == ["baseline", "sl_depth_6"]
    assert resolve_presets(["all"])[:2] == ["baseline", "entry_breakout_direct"]
    with pytest.raises(ValueError, match="Presets desconocidos"):
        resolve_presets(["no_existe"])


def test_qty_zero_sessions_are_reported_when_budget_cannot_buy_one_contract():
    settings = Settings(
        risk={
            "initial_capital": 10_000,
            "risk_per_trade_pct": 0.1,
            "max_sl_ticks": 600,
        }
    )
    result = run_backtest(settings, days=3, label="qty0")
    metrics = result["metrics"]
    assert metrics["signals"] >= 1
    assert metrics["trades"] == 0
    assert metrics["stop_cap_sessions"] == 0
    assert metrics["qty_zero_sessions"] >= 1


def test_risk_control_preset_reports_cap_and_qty_zero_metric():
    result = run_presets(Settings(), days=3, presets=["sl_cap_600"])
    row = result["comparison"][1]
    assert row["preset"] == "sl_cap_600"
    assert row["config"]["max_sl_ticks"] == 600
    assert row["config"]["risk_per_trade_pct"] == 1.0
    assert "qty_zero_sessions" in row
    assert "qty_zero_sessions" in row["delta"]


def test_run_presets_uses_same_dataset_and_reports_deltas():
    result = run_presets(
        Settings(),
        days=3,
        presets=["baseline", "entry_retrace_382", "sl_depth_6"],
    )
    assert result["data_source"] == "synthetic"
    assert len(result["results"]) == 3
    assert [row["preset"] for row in result["comparison"]] == [
        "baseline",
        "entry_retrace_382",
        "sl_depth_6",
    ]
    assert {item["dataset"]["selected_id"] for item in result["results"]} == {
        result["dataset"]["selected_id"]
    }
    assert result["comparison"][0]["delta"] == {}
    assert result["comparison"][1]["delta"]["trades"] is not None
    for item in result["results"]:
        strategy = item["config"]["strategy"]
        assert strategy["confirm_tf"] == "15m"
        assert strategy["require_close_breakout"] is True
        assert strategy["allow_reentry_after_false_breakout"] is False
        assert "stop_losses" in item["metrics"]
        assert "avg_stop_ticks" in item["metrics"]
        assert "qty_zero_sessions" in item["metrics"]
        assert item["preset_label"]
        assert item["preset_group"]
