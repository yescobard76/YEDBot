"""Modelo ``BacktestResult`` y fixture dorado de tres sesiones.

El golden se generó con la configuración congelada del protocolo apuntando al
extracto de tres sesiones (2025-12-24, 2025-12-26 y 2025-12-29). El perfil vivo
puede contener ajustes experimentales (por ejemplo 240/24); esta prueba
restaura el lock solo en memoria, no lo escribe en el perfil. No usa el holdout
ni modifica la configuración activa.
"""

from __future__ import annotations

import copy
import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from server.api import BacktestResult
from server.backtest import run_backtest
from server.config import Settings

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles" / "backtest_real" / "config.json"
PROFILE_BYTES = PROFILE.read_bytes()
CSV_FIXTURE = ROOT / "tests" / "fixtures" / "bars_mnq_nq_es_1m_3sessions.csv"
GOLDEN_PATH = ROOT / "tests" / "fixtures" / "backtest_golden_3sessions.json"
LOCK_PATH = ROOT / "docs" / "protocolo_backtest.lock.json"
GOLDEN = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
# El golden se generó con el lock. Se usa como base para que los ajustes
# experimentales del perfil vivo no conviertan una regresión en un falso
# positivo del fixture.
GOLDEN_SETTINGS = json.loads(LOCK_PATH.read_text(encoding="utf-8"))["settings"]
DEVELOPMENT_END = "2026-07-01"

TRADE_FIELDS = (
    "direction",
    "qty",
    "entry_ts",
    "exit_ts",
    "entry_price",
    "exit_price",
    "stop",
    "target",
    "pnl",
    "gross_pnl",
    "fees",
    "r_multiple",
    "risk_amount",
    "signal_type",
    "exit_reason",
    "duration_sec",
)


@pytest.fixture(scope="module")
def settings() -> Settings:
    instance = Settings.model_validate(GOLDEN_SETTINGS)
    instance.feed.csv_path = str(CSV_FIXTURE)
    return instance


@pytest.fixture(scope="module")
def result(settings) -> dict:
    window = GOLDEN["window"]
    return run_backtest(
        settings,
        window["days"],
        None,
        "golden-3s",
        date.fromisoformat(window["start_date"]),
    )


@pytest.fixture(scope="module")
def validated(result) -> BacktestResult:
    return BacktestResult.model_validate(result)


def test_golden_runs_on_the_three_session_fixture(result, validated) -> None:
    assert validated.data_source == "csv"
    assert validated.is_synthetic is False
    assert validated.data_quality == "historical"

    dataset = result["dataset"]
    assert dataset["file_name"] == GOLDEN["dataset"]["file_name"]
    assert dataset["file_hash"] == GOLDEN["dataset"]["file_hash"]
    assert dataset["series_id"] == GOLDEN["dataset"]["series_id"]
    assert dataset["row_count"] == GOLDEN["dataset"]["row_count"]
    assert dataset["common_bars"] == GOLDEN["dataset"]["common_bars"]
    assert dataset["sessions"]["dates"] == GOLDEN["dataset"]["sessions"]
    assert dataset["selected_range"] == GOLDEN["dataset"]["selected_range"]
    assert validated.config["risk"]["initial_capital"] == GOLDEN["initial_capital"]


def test_golden_metrics_match_known_pnl(result, validated) -> None:
    metrics = result["metrics"]
    for key, expected in GOLDEN["metrics"].items():
        if key == "equity_curve":
            continue
        actual = metrics[key]
        if isinstance(expected, float):
            assert actual == pytest.approx(expected, abs=1e-9), key
        else:
            assert actual == expected, key

    assert metrics["net_profit"] == pytest.approx(732.56)
    assert metrics["equity_curve"] == GOLDEN["metrics"]["equity_curve"]
    assert result["equity"] == GOLDEN["equity"]
    assert result["days_detail"] == GOLDEN["days_detail"]

    assert validated.metrics.trades == len(validated.trades) == 2
    assert validated.metrics.net_profit == pytest.approx(732.56)
    assert validated.metrics.equity_curve == validated.equity
    assert validated.equity[-1].equity == pytest.approx(25_732.56)
    assert validated.days_detail[-1].trades == 0


def test_golden_trades_match_known_operations(result, validated) -> None:
    assert len(result["trades"]) == len(GOLDEN["trades"]) == 2
    for trade, expected in zip(result["trades"], GOLDEN["trades"]):
        assert trade["meta"]["signal_id"] == expected["signal_id"]
        for key in TRADE_FIELDS:
            if isinstance(expected[key], float):
                assert trade[key] == pytest.approx(expected[key], abs=1e-9), key
            else:
                assert trade[key] == expected[key], key

    assert validated.trades[0].duration_sec == 7_440
    assert validated.trades[1].exit_reason == "session_close"
    assert sum(trade.pnl for trade in validated.trades) == pytest.approx(732.56)


def test_golden_uses_development_sessions_only(result) -> None:
    sessions = {day["date"] for day in result["days_detail"]}
    assert sessions == set(GOLDEN["dataset"]["sessions"])
    assert all(day < DEVELOPMENT_END for day in sessions)


def test_golden_restores_the_lock_without_touching_the_live_profile(settings) -> None:
    assert settings.strategy.setup_validity_minutes == 150
    assert settings.strategy.retest_tolerance_ticks == 12
    assert settings.risk.max_sl_ticks == 200
    assert PROFILE.read_bytes() == PROFILE_BYTES


def _reject(result: dict, mutate, match: str) -> None:
    data = copy.deepcopy(result)
    mutate(data)
    with pytest.raises(ValidationError, match=match):
        BacktestResult.model_validate(data)


def test_model_rejects_trade_count_mismatch(result) -> None:
    _reject(result, lambda data: data["metrics"].__setitem__("trades", 3), "metrics.trades")


def test_model_rejects_net_profit_mismatch(result) -> None:
    _reject(
        result,
        lambda data: data["metrics"].__setitem__(
            "net_profit", data["metrics"]["net_profit"] + 10
        ),
        "net_profit",
    )


def test_model_rejects_equity_out_of_sync(result) -> None:
    def mutate(data: dict) -> None:
        curve = copy.deepcopy(data["metrics"]["equity_curve"])
        curve[-1]["equity"] += 10
        data["metrics"]["equity_curve"] = curve

    _reject(result, mutate, "equity debe coincidir")


def test_model_rejects_inconsistent_win_rate(result) -> None:
    _reject(result, lambda data: data["metrics"].__setitem__("win_rate", 50.0), "win_rate")


def test_model_rejects_profit_factor_without_losses(result) -> None:
    _reject(
        result,
        lambda data: data["metrics"].__setitem__("profit_factor", 1.0),
        "profit_factor",
    )


def test_model_rejects_drawdown_that_curve_does_not_show(result) -> None:
    _reject(
        result,
        lambda data: data["metrics"].__setitem__("max_drawdown", 5.0),
        "max_drawdown",
    )


def test_model_rejects_inconsistent_trade_duration(result) -> None:
    _reject(
        result,
        lambda data: data["trades"][0].__setitem__(
            "duration_sec", data["trades"][0]["duration_sec"] + 1
        ),
        "duration_sec",
    )


def test_model_rejects_days_detail_that_does_not_sum(result) -> None:
    _reject(
        result,
        lambda data: data["days_detail"][0].__setitem__(
            "pnl", data["days_detail"][0]["pnl"] + 10
        ),
        "days_detail",
    )


def test_model_rejects_synthetic_flag_mismatch(result) -> None:
    _reject(result, lambda data: data.__setitem__("is_synthetic", True), "is_synthetic")
