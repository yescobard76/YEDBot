"""API HTTP y WebSocket. Toda mutación exige una acción explícita del usuario."""

from __future__ import annotations

import asyncio
import csv
import io
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import __version__
from .backtest import (
    DEFAULT_PRESETS,
    MAX_BACKTEST_DAYS,
    MIN_BACKTEST_DAYS,
    PRESETS,
    SAMPLE_MIN_SESSIONS,
    preset_catalog,
    run_backtest,
    run_presets,
    run_variants,
)
from .config import BASE_DIR, Settings
from .db import IdempotencyConflict
from .experiments import (
    ExperimentLedger,
    LedgerError,
    ledger_record_sha256,
    reconcile_ledger_links,
)
from .market.csv_data import (
    DATA_SCHEMA_VERSION,
    REQUIRED_SYMBOLS,
    SERIES_MODES,
    inspect_csv,
    refuse_holdout_sessions,
)
from .schemas import (
    BacktestVariantsResponse,
    ChartHistoryResponse,
    DatasetInfo,
    DatasetRange,
    EventsResponse,
    OrdersResponse,
    PresetCatalogResponse,
    PresetSample,
    Snapshot,
    Stats,
    TradesResponse,
)
from .timeutil import et_date_str, local_dt
from .validation import ValidationReportError, load_forward_validation

router = APIRouter()
ET = ZoneInfo("America/New_York")

DEFAULT_COMPARE_METRICS = ("net_profit", "profit_factor", "max_drawdown_pct", "avg_r")
COMPARE_METRIC_CATALOG = (
    "trades",
    "win_rate",
    "profit_factor",
    "expectancy",
    "net_profit",
    "max_drawdown",
    "max_drawdown_pct",
    "total_r",
    "avg_r",
    "sharpe",
    "sortino",
    "stop_losses",
    "take_profits",
    "stop_cap_sessions",
    "qty_zero_sessions",
)


class ConfigUpdate(BaseModel):
    patch: dict[str, Any] = Field(default_factory=dict)
    force: bool = False


class ForwardValidationMetrics(BaseModel):
    model_config = ConfigDict(extra="allow")

    ops: int = Field(ge=0)
    net_usd: float
    profit_factor: float = Field(ge=0)
    max_drawdown_usd: float = Field(ge=0)
    max_drawdown_pct: float = Field(ge=0, le=100)
    expectancy_usd: float
    expectancy_r: float
    total_r: float


class ForwardValidationCandidate(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    label: str
    short_label: str
    role: Literal["baseline", "candidate"]
    profile: str | None
    profile_sha256: str | None
    implementation: str
    production_available: bool | None = None
    dev_metrics: ForwardValidationMetrics
    forward_metrics: ForwardValidationMetrics | None
    forward_status: Literal["reference", "validated", "rejected", "insufficient_data"]
    forward_note: str


class ForwardValidationDecision(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: Literal["keep_current", "adopt_candidate"]
    label: str
    adopted_candidate: str | None
    live_config_updated: bool
    current_profile: str
    current_profile_sha256: str
    summary: str
    reasons: list[str]


class ForwardValidationDevelopment(BaseModel):
    model_config = ConfigDict(extra="allow")

    window: str
    start: str
    end: str
    sessions: int = Field(ge=0)
    status: str
    role: str
    source: str
    note: str


class ForwardValidationWindow(BaseModel):
    model_config = ConfigDict(extra="allow")

    start: str
    end: str
    source: str
    hypothesis: str
    applicable_to_candidates: bool


class ForwardValidationForward(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    evaluated: bool
    attempts: int = Field(ge=0)
    available_sessions: int = Field(ge=0)
    available_bars: int = Field(ge=0)
    dataset_last_session: str
    dataset_last_bar_et: str
    summary: str
    reasons: list[str]
    candidate_forward_protocol: str | None
    earliest_preregistered_window: ForwardValidationWindow | None = None


class ForwardValidationHoldout(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    start: str
    end: str
    sessions: int = Field(ge=0)
    status: str
    executed: bool
    used_for_decision: bool
    lock_path: str
    lock_sha256: str


class ForwardValidationReport(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    schema_version: str = Field(alias="schema")
    generated_at: str
    status: str
    decision: ForwardValidationDecision
    development: ForwardValidationDevelopment
    forward: ForwardValidationForward
    holdout: ForwardValidationHoldout
    candidates: list[ForwardValidationCandidate] = Field(min_length=1)
    integrity: dict[str, Any]


class EmergencyRequest(BaseModel):
    reason: str = "Intervención manual"
    close_positions: bool = False


class ResetStatsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    delete_backtests: bool = False
    confirm_delete_backtests: bool = False
    archive: bool = False


class CsvValidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str | None = None
    series_mode: str | None = None
    exclude_roll_sessions: bool | None = None


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=30, ge=3, le=250)
    overrides: dict[str, Any] = Field(default_factory=dict)
    compare: bool = False
    label: str | None = None
    persist: bool = True
    start_date: str | None = None
    hypothesis_id: str | None = Field(default=None, min_length=1, max_length=120)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class PresetBacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    days: int = Field(default=20, ge=3, le=250)
    presets: list[str] = Field(default_factory=list)
    overrides: dict[str, Any] = Field(default_factory=dict)
    start_date: str | None = None
    persist: bool = True
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


class BacktestCompareRequest(BaseModel):
    """Comparación de 2–4 resultados guardados."""

    model_config = ConfigDict(extra="forbid")

    result_ids: list[str] = Field(min_length=2, max_length=4)
    baseline_id: str | None = None
    metrics: list[str] = Field(default_factory=list)


class LegacyRepairRequest(BaseModel):
    """Opciones de la reparación legacy; dry-run por defecto."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool = True


class PresetEquityPoint(BaseModel):
    """Punto de la curva de equity de una fila de comparación."""

    model_config = ConfigDict(extra="forbid")

    ts: int = Field(ge=0)
    equity: float


class PresetComparisonRow(BaseModel):
    """Métricas de un preset; las invariantes replican ``server.stats``."""

    model_config = ConfigDict(extra="forbid")

    result_id: str | None = Field(default=None, min_length=1)
    preset: str = Field(min_length=1)
    label: str = Field(min_length=1)
    group: str = Field(min_length=1)
    description: str = Field(min_length=1)
    is_synthetic: bool
    trades: int = Field(ge=0)
    signals: int = Field(ge=0)
    breakouts: int = Field(ge=0)
    retests: int = Field(ge=0)
    days_traded: int = Field(ge=0)
    win_rate: float = Field(ge=0, le=100)
    profit_factor: float | None = Field(ge=0)
    expectancy: float
    net_profit: float
    max_drawdown: float = Field(ge=0)
    max_drawdown_pct: float = Field(ge=0)
    avg_r: float
    total_r: float
    sharpe: float | None
    sortino: float | None
    stop_losses: int = Field(ge=0)
    take_profits: int = Field(ge=0)
    session_closes: int = Field(ge=0)
    stop_loss_rate: float = Field(ge=0, le=100)
    take_profit_rate: float = Field(ge=0, le=100)
    avg_stop_ticks: float = Field(ge=0)
    stop_cap_sessions: int = Field(ge=0)
    qty_zero_sessions: int = Field(ge=0)
    final_equity: float | None
    config: dict[str, Any] = Field(default_factory=dict)
    equity: list[PresetEquityPoint] = Field(default_factory=list)
    delta: dict[str, float | None] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _metric_invariants(self) -> "PresetComparisonRow":
        if self.trades == 0:
            zeros = {
                "net_profit": self.net_profit,
                "expectancy": self.expectancy,
                "win_rate": self.win_rate,
                "avg_r": self.avg_r,
                "total_r": self.total_r,
                "max_drawdown": self.max_drawdown,
                "max_drawdown_pct": self.max_drawdown_pct,
                "stop_losses": self.stop_losses,
                "take_profits": self.take_profits,
                "session_closes": self.session_closes,
                "stop_loss_rate": self.stop_loss_rate,
                "take_profit_rate": self.take_profit_rate,
                "avg_stop_ticks": self.avg_stop_ticks,
            }
            nonzero = [name for name, value in zeros.items() if value != 0]
            if nonzero:
                raise ValueError(
                    "una fila sin operaciones debe tener a cero: "
                    + ", ".join(nonzero)
                )
            if self.profit_factor is not None:
                raise ValueError("profit_factor debe ser None cuando trades == 0")
            if self.final_equity is None:
                raise ValueError("final_equity debe existir aunque no haya operaciones")
            return self

        if self.stop_losses + self.take_profits + self.session_closes > self.trades:
            raise ValueError("SL + TP + cierres de sesión no puede superar trades")
        if abs(self.stop_loss_rate - self.stop_losses / self.trades * 100) > 0.01:
            raise ValueError("stop_loss_rate debe ser stop_losses / trades")
        if abs(self.take_profit_rate - self.take_profits / self.trades * 100) > 0.01:
            raise ValueError("take_profit_rate debe ser take_profits / trades")
        if abs(self.expectancy * self.trades - self.net_profit) > 0.01 * self.trades + 0.01:
            raise ValueError("expectancy debe ser net_profit / trades")
        if abs(self.avg_r * self.trades - self.total_r) > 0.01 * self.trades + 0.01:
            raise ValueError("avg_r debe ser total_r / trades")
        return self


class PresetComparisonResponse(BaseModel):
    """Respuesta de ``POST /backtest/presets`` con invariantes cruzadas."""

    model_config = ConfigDict(extra="forbid")

    backtest_run_id: str | None = None
    created_ts: int = Field(gt=0)
    data_source: Literal["csv", "synthetic"]
    is_synthetic: bool
    dataset: DatasetInfo | None = None
    dataset_id: str | None = None
    days_requested: int = Field(ge=MIN_BACKTEST_DAYS, le=MAX_BACKTEST_DAYS)
    sessions: int = Field(ge=1)
    overrides: dict[str, Any]
    base_config: dict[str, Any]
    preset_keys: list[str] = Field(min_length=1)
    comparison: list[PresetComparisonRow] = Field(min_length=1)
    default_presets: bool
    sample: PresetSample
    note: str = Field(min_length=1)

    @model_validator(mode="after")
    def _response_invariants(self) -> "PresetComparisonResponse":
        if self.is_synthetic != (self.data_source != "csv"):
            raise ValueError("is_synthetic debe corresponder a data_source")
        if self.dataset is not None and self.dataset.kind != self.data_source:
            raise ValueError("dataset.kind debe coincidir con data_source")
        if self.dataset_id and self.dataset is not None and self.dataset_id != self.dataset.id:
            raise ValueError("dataset_id debe coincidir con dataset.id")
        if self.sessions > self.days_requested:
            raise ValueError("sessions no puede superar days_requested")

        keys = self.preset_keys
        if len(set(keys)) != len(keys):
            raise ValueError("preset_keys no puede contener duplicados")
        unknown = [key for key in keys if key not in PRESETS]
        if unknown:
            raise ValueError(f"presets desconocidos: {', '.join(unknown)}")
        if keys[0] != "baseline":
            raise ValueError("preset_keys debe empezar por baseline")
        if [row.preset for row in self.comparison] != keys:
            raise ValueError("preset_keys y comparison deben coincidir en orden")
        if self.default_presets and keys != list(DEFAULT_PRESETS):
            raise ValueError(
                f"default_presets=True exige exactamente los {len(DEFAULT_PRESETS)} presets por defecto"
            )

        initial = (self.base_config.get("risk") or {}).get("initial_capital")
        for row in self.comparison:
            if row.is_synthetic != self.is_synthetic:
                raise ValueError("is_synthetic debe ser igual en todas las filas")
            if row.days_traded > self.sessions:
                raise ValueError("days_traded no puede superar sessions")
            if max(row.signals, row.breakouts, row.retests) > self.sessions:
                raise ValueError("señales/rupturas/retesteos no pueden superar sessions")
            if row.stop_cap_sessions > self.sessions:
                raise ValueError("stop_cap_sessions no puede superar sessions")
            if row.qty_zero_sessions > self.sessions:
                raise ValueError("qty_zero_sessions no puede superar sessions")
            if initial is not None and row.final_equity is not None:
                expected = float(initial) + row.net_profit
                if abs(row.final_equity - expected) > 0.02:
                    raise ValueError("final_equity debe ser initial_capital + net_profit")

        active = sum(1 for row in self.comparison if row.trades > 0)
        if self.sample.active_presets != active:
            raise ValueError("sample.active_presets debe contar las filas con operaciones")
        if self.sample.total_presets != len(self.comparison):
            raise ValueError("sample.total_presets debe coincidir con comparison")
        if self.sample.sessions != self.sessions:
            raise ValueError("sample.sessions debe coincidir con sessions")
        if self.sample.days_requested != self.days_requested:
            raise ValueError("sample.days_requested debe coincidir con days_requested")
        if self.sample.min_sessions != SAMPLE_MIN_SESSIONS:
            raise ValueError("sample.min_sessions debe ser el mínimo del servidor")
        expected_status = (
            "insufficient"
            if self.sessions < SAMPLE_MIN_SESSIONS
            else "no_trades" if active == 0 else "activity"
        )
        if self.sample.status != expected_status:
            raise ValueError("sample.status no coincide con la muestra")
        return self


class BacktestEquityPoint(BaseModel):
    """Punto de la curva de equity de un backtest."""

    model_config = ConfigDict(extra="forbid")

    ts: int = Field(ge=0)
    equity: float


class BacktestTrade(BaseModel):
    """Operación cerrada de un backtest; conserva los campos extra del motor."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(min_length=1)
    symbol: str = Field(min_length=1)
    direction: Literal["long", "short"]
    qty: int = Field(ge=1)
    entry_ts: int = Field(ge=0)
    exit_ts: int = Field(ge=0)
    entry_price: float
    exit_price: float
    stop: float
    target: float
    pnl: float
    gross_pnl: float
    fees: float = Field(ge=0)
    r_multiple: float
    risk_amount: float = Field(ge=0)
    signal_type: str = Field(min_length=1)
    exit_reason: str = Field(min_length=1)
    duration_sec: int = Field(ge=0)
    mode: str = Field(min_length=1)

    @model_validator(mode="after")
    def _trade_invariants(self) -> "BacktestTrade":
        if self.exit_ts < self.entry_ts:
            raise ValueError("exit_ts no puede ser anterior a entry_ts")
        if self.duration_sec != self.exit_ts - self.entry_ts:
            raise ValueError("duration_sec debe ser exit_ts - entry_ts")
        if abs(self.pnl - (self.gross_pnl - self.fees)) > 0.011:
            raise ValueError("pnl debe ser gross_pnl - fees")
        if self.direction == "long" and not (self.stop < self.entry_price < self.target):
            raise ValueError("un largo exige stop < entry_price < target")
        if self.direction == "short" and not (self.target < self.entry_price < self.stop):
            raise ValueError("un corto exige target < entry_price < stop")
        return self


class BacktestMetrics(BaseModel):
    """Métricas del backtest; los campos no modelados viajan como extra."""

    model_config = ConfigDict(extra="allow")

    trades: int = Field(ge=0)
    wins: int = Field(ge=0)
    losses: int = Field(ge=0)
    breakeven: int = Field(ge=0)
    win_rate: float = Field(ge=0, le=100)
    profit_factor: float | None = Field(default=None, ge=0)
    expectancy: float
    net_profit: float
    gross_profit: float = Field(ge=0)
    gross_loss: float = Field(le=0)
    fees: float = Field(ge=0)
    max_drawdown: float = Field(ge=0)
    max_drawdown_pct: float = Field(ge=0, le=100)
    equity_trough: float
    total_r: float
    avg_r: float
    avg_stop_ticks: float = Field(ge=0)
    stop_losses: int = Field(ge=0)
    take_profits: int = Field(ge=0)
    session_closes: int = Field(ge=0)
    stop_loss_rate: float = Field(ge=0, le=100)
    take_profit_rate: float = Field(ge=0, le=100)
    signals: int = Field(ge=0)
    breakouts: int = Field(ge=0)
    retests: int = Field(ge=0)
    stop_cap_sessions: int = Field(ge=0)
    qty_zero_sessions: int = Field(ge=0)
    days_traded: int = Field(ge=0)
    winning_days: int = Field(ge=0)
    losing_days: int = Field(ge=0)
    equity_curve: list[BacktestEquityPoint] = Field(min_length=1)


class BacktestDay(BaseModel):
    """Resultado de una sesión simulada."""

    model_config = ConfigDict(extra="allow")

    date: str = Field(min_length=1)
    pnl: float
    trades: int = Field(ge=0)
    equity: float


class ExperimentIdentityPayload(BaseModel):
    """Identidad canónica de la ejecución; los hashes son SHA-256 hex."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["experiment-v1"]
    config_sha256: str = Field(min_length=64, max_length=64)
    code_sha256: str = Field(min_length=64, max_length=64)
    dataset_sha256: str = Field(min_length=64, max_length=64)
    config_hash_algorithm: str = Field(min_length=1)
    code_hash_algorithm: str = Field(min_length=1)
    dataset_hash_algorithm: str = Field(min_length=1)
    data_source: Literal["csv", "synthetic", "live"]
    dataset_id: str | None = None
    series_id: str | None = None
    selected_id: str | None = None
    sessions: int = Field(default=0, ge=0)


class BacktestResult(BaseModel):
    """Resultado completo de ``POST /backtest/run`` con invariantes cruzadas."""

    model_config = ConfigDict(extra="forbid")

    backtest_run_id: str | None = None
    # Bloque plano del ledger: las cinco claves se emiten juntas; None = sin vínculo.
    ledger_status: Literal["pending", "sent"] | None = None
    hypothesis_id: str | None = None
    ledger_event_id: str | None = None
    ledger_event_sha256: str | None = None
    ledger_error: str | None = None
    id: str = Field(min_length=1)
    created_ts: int = Field(gt=0)
    label: str = Field(min_length=1)
    data_source: Literal["csv", "synthetic"]
    data_quality: Literal["historical", "simulated"]
    dataset_id: str | None = None
    dataset: DatasetInfo | None = None
    data_range: DatasetRange | None = None
    config: dict[str, Any]
    metrics: BacktestMetrics
    diagnostics: dict[str, Any] = Field(default_factory=dict)
    trades: list[BacktestTrade]
    equity: list[BacktestEquityPoint] = Field(min_length=1)
    days_detail: list[BacktestDay]
    funnel: dict[str, Any] = Field(default_factory=dict)
    overrides: dict[str, Any] = Field(default_factory=dict)
    is_synthetic: bool
    variant: str | None = None
    experiment: ExperimentIdentityPayload | None = None

    @model_validator(mode="after")
    def _result_invariants(self) -> "BacktestResult":
        if self.is_synthetic != (self.data_source != "csv"):
            raise ValueError("is_synthetic debe corresponder a data_source")
        expected_quality = "historical" if self.data_source == "csv" else "simulated"
        if self.data_quality != expected_quality:
            raise ValueError("data_quality debe corresponder a data_source")

        if self.dataset is not None and self.dataset.kind != self.data_source:
            raise ValueError("dataset.kind debe coincidir con data_source")
        if self.dataset_id and self.dataset is not None and self.dataset_id != self.dataset.id:
            raise ValueError("dataset_id debe coincidir con dataset.id")
        if self.experiment is not None:
            if self.experiment.data_source != self.data_source:
                raise ValueError("experiment.data_source debe coincidir con data_source")
            if (
                self.dataset_id
                and self.experiment.dataset_id is not None
                and self.experiment.dataset_id != self.dataset_id
            ):
                raise ValueError("experiment.dataset_id debe coincidir con dataset_id")

        metrics = self.metrics
        trades = self.trades
        if metrics.trades != len(trades):
            raise ValueError("metrics.trades debe coincidir con len(trades)")

        wins = sum(1 for trade in trades if trade.pnl > 0)
        losses = sum(1 for trade in trades if trade.pnl < 0)
        breakeven = len(trades) - wins - losses
        if (metrics.wins, metrics.losses, metrics.breakeven) != (wins, losses, breakeven):
            raise ValueError("metrics.wins/losses/breakeven deben contar los trades")
        if wins + losses + breakeven > metrics.trades:
            raise ValueError("wins + losses + breakeven no puede superar trades")

        tolerance = 0.011 * max(len(trades), 1) + 0.011
        if abs(sum(trade.pnl for trade in trades) - metrics.net_profit) > tolerance:
            raise ValueError("metrics.net_profit debe ser la suma de pnl")
        if abs(sum(trade.fees for trade in trades) - metrics.fees) > tolerance:
            raise ValueError("metrics.fees debe ser la suma de fees")
        if abs(sum(trade.pnl for trade in trades if trade.pnl > 0) - metrics.gross_profit) > tolerance:
            raise ValueError("metrics.gross_profit debe sumar los trades ganadores")
        if abs(sum(trade.pnl for trade in trades if trade.pnl < 0) - metrics.gross_loss) > tolerance:
            raise ValueError("metrics.gross_loss debe sumar los trades perdedores")

        if metrics.gross_loss == 0:
            if metrics.profit_factor is not None:
                raise ValueError("profit_factor debe ser None cuando no hay pérdidas")
        else:
            expected_pf = metrics.gross_profit / abs(metrics.gross_loss)
            if metrics.profit_factor is None or abs(metrics.profit_factor - expected_pf) > 0.011:
                raise ValueError("profit_factor debe ser gross_profit / |gross_loss|")

        if metrics.trades:
            if abs(metrics.expectancy * metrics.trades - metrics.net_profit) > tolerance:
                raise ValueError("expectancy debe ser net_profit / trades")
            expected_win_rate = metrics.wins / metrics.trades * 100
            if abs(metrics.win_rate - expected_win_rate) > 0.011:
                raise ValueError("win_rate debe ser wins / trades")
            if abs(metrics.stop_loss_rate - metrics.stop_losses / metrics.trades * 100) > 0.011:
                raise ValueError("stop_loss_rate debe ser stop_losses / trades")
            if abs(metrics.take_profit_rate - metrics.take_profits / metrics.trades * 100) > 0.011:
                raise ValueError("take_profit_rate debe ser take_profits / trades")
            if abs(metrics.avg_r * metrics.trades - metrics.total_r) > tolerance:
                raise ValueError("avg_r debe ser total_r / trades")
            if abs(sum(trade.r_multiple for trade in trades) - metrics.total_r) > tolerance:
                raise ValueError("total_r debe ser la suma de r_multiple")
        else:
            if any(
                value != 0
                for value in (
                    metrics.net_profit,
                    metrics.expectancy,
                    metrics.win_rate,
                    metrics.avg_r,
                    metrics.total_r,
                    metrics.stop_losses,
                    metrics.take_profits,
                    metrics.session_closes,
                    metrics.stop_loss_rate,
                    metrics.take_profit_rate,
                    metrics.avg_stop_ticks,
                )
            ):
                raise ValueError("sin operaciones las métricas deben estar a cero")

        if metrics.stop_losses + metrics.take_profits + metrics.session_closes > metrics.trades:
            raise ValueError("SL + TP + cierres de sesión no puede superar trades")
        if metrics.days_traded != len(self.days_detail):
            raise ValueError("days_traded debe coincidir con len(days_detail)")
        if metrics.winning_days != sum(1 for day in self.days_detail if day.pnl > 0):
            raise ValueError("winning_days debe contar los días con pnl positivo")
        if metrics.losing_days != sum(1 for day in self.days_detail if day.pnl < 0):
            raise ValueError("losing_days debe contar los días con pnl negativo")
        if abs(sum(day.pnl for day in self.days_detail) - metrics.net_profit) > tolerance:
            raise ValueError("days_detail debe sumar net_profit")
        if sum(day.trades for day in self.days_detail) != metrics.trades:
            raise ValueError("days_detail debe sumar trades")

        sessions = int((self.funnel.get("summary") or {}).get("sessions") or 0)
        if not sessions:
            sessions = len(self.funnel.get("sessions") or [])
        if sessions:
            for name in ("signals", "breakouts", "retests", "stop_cap_sessions", "qty_zero_sessions"):
                if getattr(metrics, name) > sessions:
                    raise ValueError(f"metrics.{name} no puede superar las sesiones")

        if [(point.ts, point.equity) for point in metrics.equity_curve] != [
            (point.ts, point.equity) for point in self.equity
        ]:
            raise ValueError("equity debe coincidir con metrics.equity_curve")
        for previous, current in zip(self.equity, self.equity[1:]):
            if current.ts < previous.ts:
                raise ValueError("equity_curve debe tener ts no decrecientes")

        initial = (self.config.get("risk") or {}).get("initial_capital")
        if initial is None:
            raise ValueError("config.risk.initial_capital es obligatorio")
        initial = float(initial)
        curve = self.equity
        if abs(curve[0].equity - initial) > 0.011:
            raise ValueError("equity_curve debe empezar en initial_capital")

        ordered = sorted(trades, key=lambda trade: trade.exit_ts)
        if trades and len(curve) != len(trades) + 1:
            raise ValueError("equity_curve debe tener un punto por operación")
        if not trades and len(curve) != 1:
            raise ValueError("sin operaciones equity_curve debe tener un solo punto")
        for index, trade in enumerate(ordered):
            if curve[index + 1].ts != trade.exit_ts:
                raise ValueError("equity_curve debe avanzar con exit_ts")
            delta = curve[index + 1].equity - curve[index].equity
            if abs(delta - trade.pnl) > 0.011:
                raise ValueError("equity_curve debe sumar pnl por operación")
        expected_final = initial + metrics.net_profit
        if abs(curve[-1].equity - expected_final) > 0.011:
            raise ValueError("la equity final debe ser initial_capital + net_profit")

        peak = initial
        worst = 0.0
        worst_pct = 0.0
        trough = initial
        for point in curve:
            peak = max(peak, point.equity)
            drawdown = peak - point.equity
            if drawdown > worst + 1e-9:
                worst = drawdown
                worst_pct = drawdown / peak * 100 if peak else 0.0
                trough = point.equity
        if abs(worst - metrics.max_drawdown) > 0.011:
            raise ValueError("max_drawdown debe coincidir con la curva")
        if abs(worst_pct - metrics.max_drawdown_pct) > 0.011:
            raise ValueError("max_drawdown_pct debe coincidir con la curva")
        if abs(trough - metrics.equity_trough) > 0.011:
            raise ValueError("equity_trough debe coincidir con la curva")
        return self


def _engine(request: Request):
    return request.app.state.engine


@router.get("/health")
async def health() -> dict:
    return {"status": "ok", "version": __version__, "time": int(time.time() * 1000)}


@router.get("/validation/forward", response_model=ForwardValidationReport)
async def forward_validation() -> dict:
    """Informe de decisión forward; solo lectura y sin acceso al holdout."""
    try:
        return load_forward_validation()
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=503,
            detail="El informe de validación forward no está generado.",
        ) from exc
    except ValidationReportError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Informe de validación forward inválido: {exc}",
        ) from exc


@router.get("/status", response_model=Snapshot)
async def status(request: Request) -> dict:
    return _engine(request).snapshot()


@router.get("/config")
async def get_config(request: Request) -> dict:
    engine = _engine(request)
    return {
        "settings": engine.settings.model_dump(),
        "defaults": Settings().model_dump(),
        "mode": engine.settings.mode,
    }


@router.put("/config")
async def put_config(payload: ConfigUpdate, request: Request) -> dict:
    engine = _engine(request)
    ok, message = await engine.update_settings(payload.patch, payload.force)
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "settings": engine.settings.model_dump()}


@router.post("/config/reset")
async def reset_config(request: Request) -> dict:
    engine = _engine(request)
    ok, message = await engine.reset_settings()
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "settings": engine.settings.model_dump()}


@router.post("/bot/{action}")
async def bot_action(action: str, request: Request) -> dict:
    engine = _engine(request)
    if action == "start":
        ok, message = await engine.start()
    elif action == "pause":
        ok, message = engine.pause()
    elif action == "resume":
        ok, message = engine.resume()
    elif action == "stop":
        ok, message = await engine.stop()
    else:
        raise HTTPException(status_code=404, detail="Acción no válida")
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message, "status": engine.status}


@router.post("/position/close")
async def close_position(request: Request) -> dict:
    engine = _engine(request)
    ok, message = engine.close_position()
    if not ok:
        raise HTTPException(status_code=400, detail=message)
    return {"ok": True, "message": message}


@router.post("/orders/cancel")
async def cancel_orders(request: Request) -> dict:
    engine = _engine(request)
    ok, message = engine.cancel_orders()
    return {"ok": ok, "message": message}


@router.post("/emergency")
async def emergency(payload: EmergencyRequest, request: Request) -> dict:
    engine = _engine(request)
    ok, message = engine.emergency(payload.reason, payload.close_positions)
    return {"ok": ok, "message": message, "emergency": engine.risk.emergency}


@router.delete("/emergency")
async def clear_emergency(request: Request) -> dict:
    engine = _engine(request)
    ok, message = engine.clear_emergency()
    return {"ok": ok, "message": message}


def _filters(
    period: str | None,
    date_from: str | None,
    date_to: str | None,
    direction: str | None,
    result: str | None,
    signal_type: str | None,
) -> dict:
    filters: dict[str, Any] = {}
    now = datetime.now(ET)
    if period and period != "all":
        if period == "today":
            start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "week":
            start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == "month":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == "30d":
            start = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            start = None
        if start:
            filters["date_from"] = int(start.timestamp())
            filters["date_to"] = int(now.timestamp())
    if date_from:
        filters["date_from"] = _parse_ts(date_from)
    if date_to:
        filters["date_to"] = _parse_ts(date_to)
    if direction and direction != "all":
        filters["direction"] = direction
    if result and result != "all":
        filters["result"] = result
    if signal_type and signal_type != "all":
        filters["signal_type"] = signal_type
    return filters


def _parse_ts(value: str) -> int:
    try:
        return int(float(value))
    except ValueError:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ET)
        return int(dt.timestamp())


def _parse_backtest_ts(value: str, *, end: bool = False) -> int:
    """Convierte fechas/epoch a milisegundos para ``backtest_runs``.

    Los valores numéricos pequeños se interpretan como segundos y los grandes
    como milisegundos. Una fecha ISO sin hora en ``date_to`` incluye el día
    completo.
    """
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        number = None
    if number is not None:
        try:
            milliseconds = (
                int(number * 1000)
                if abs(number) < 100_000_000_000
                else int(number)
            )
        except (OverflowError, ValueError) as exc:
            raise ValueError(f"fecha inválida: {value}") from exc
        return milliseconds
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"fecha inválida: {value}") from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ET)
    date_only = len(text) == 10 and text[4:5] == "-" and text[7:8] == "-"
    if end and date_only:
        dt += timedelta(days=1)
        return int(dt.timestamp() * 1000) - 1
    return int(dt.timestamp() * 1000)


@router.get("/trades", response_model=TradesResponse)
async def list_trades(
    request: Request,
    period: str | None = "30d",
    date_from: str | None = None,
    date_to: str | None = None,
    direction: str | None = None,
    result: str | None = None,
    signal_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> dict:
    store = _engine(request).store
    filters = _filters(period, date_from, date_to, direction, result, signal_type)
    items = store.list_trades(filters, limit=limit, offset=offset)
    return {
        "items": items,
        "total": store.count_trades(filters),
        "limit": limit,
        "offset": offset,
    }


@router.get("/trades/export.csv")
async def export_trades(
    request: Request,
    period: str | None = "all",
    date_from: str | None = None,
    date_to: str | None = None,
    direction: str | None = None,
    result: str | None = None,
    signal_type: str | None = None,
) -> Response:
    engine = _engine(request)
    filters = _filters(period, date_from, date_to, direction, result, signal_type)
    rows = engine.store.list_trades(filters, limit=100_000)
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "Fecha", "Hora", "Instrumento", "Direccion", "Cantidad", "Entrada", "Salida",
            "StopLoss", "TakeProfit", "ResultadoUSD", "R", "DuracionSeg", "TipoSenal",
            "MotivoEntrada", "MotivoSalida", "Modo",
        ]
    )
    for t in sorted(rows, key=lambda r: r["exit_ts"]):
        dt_in = local_dt(int(t["entry_ts"]))
        writer.writerow(
            [
                dt_in.strftime("%d/%m/%Y"),
                dt_in.strftime("%H:%M:%S"),
                t["symbol"],
                "Larga" if t["direction"] == "long" else "Corta",
                t["qty"],
                f"{t['entry_price']:.2f}",
                f"{t['exit_price']:.2f}",
                f"{t['stop']:.2f}",
                f"{t['target']:.2f}",
                f"{t['pnl']:.2f}",
                f"{t['r_multiple']:.2f}",
                t["duration_sec"],
                t["signal_type"],
                t["entry_reason"],
                t["exit_reason"],
                t["mode"],
            ]
        )
    stamp = et_date_str(int(time.time()))
    return Response(
        content="\ufeff" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="yedbot_operaciones_{stamp}.csv"'},
    )


@router.get("/stats", response_model=Stats)
async def stats(request: Request, period: str | None = None) -> dict:
    engine = _engine(request)
    if period:
        from .stats import compute_stats

        rows = engine.store.list_trades(_filters(period, None, None, None, None, None), limit=100_000)
        return compute_stats(rows, engine.settings.risk.initial_capital)
    return engine.stats()


def _archive_reset_database(store: Any) -> str:
    """Copia la base antes de un reinicio; devuelve el directorio del archivo."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    directory = Path(BASE_DIR) / "backups" / f"reset_{stamp}"
    suffix = 1
    while directory.exists():
        directory = Path(BASE_DIR) / "backups" / f"reset_{stamp}_{suffix}"
        suffix += 1
    store.archive_to(directory / store.path.name)
    return str(directory)


@router.get("/stats/reset/preview")
async def preview_reset_stats(
    request: Request, delete_backtests: bool = False, archive: bool = False
) -> dict[str, Any]:
    """Devuelve los conteos y las opciones del próximo reinicio, sin borrar nada.

    ``counts`` siempre incluye los backtests guardados. Si ``delete_backtests``
    es verdadero, ``requires_confirmation`` indica que el POST debe incluir
    ``confirm_delete_backtests=true``. ``archive`` refleja si se solicitó la
    copia previa; la ruta real solo se conoce al ejecutar el reinicio.
    """
    counts = _engine(request).store.history_counts()
    return {
        "counts": counts,
        "delete_backtests": delete_backtests,
        "requires_confirmation": delete_backtests,
        "archive": archive,
    }


@router.post("/stats/reset")
async def reset_stats(request: Request, payload: ResetStatsRequest | None = None) -> dict:
    """Reinicia operaciones, equidad y eventos; conserva los backtests salvo petición explícita.

    El body es opcional para que un POST sin contenido use el valor conservador.
    Borrar backtests exige ``confirm_delete_backtests=true``.
    ``archive=true`` guarda una copia SQLite consistente antes de borrar; la
    respuesta incluye su ruta en ``archive_path``. ``counts`` siempre contiene
    los conteos previos, incluidos los backtests aunque se conserven.
    """
    engine = _engine(request)
    data = payload or ResetStatsRequest()
    delete_backtests = bool(data.delete_backtests)
    confirmed = bool(data.confirm_delete_backtests)
    if delete_backtests and not confirmed:
        raise HTTPException(
            status_code=409,
            detail=(
                "Eliminar los backtests requiere confirmación explícita: "
                "envía confirm_delete_backtests=true."
            ),
        )
    if getattr(getattr(engine, "execution", None), "position", None):
        raise HTTPException(
            status_code=409,
            detail="Hay una posición abierta. Ciérrala antes de reiniciar las estadísticas.",
        )
    counts = engine.store.history_counts()
    archive_path = _archive_reset_database(engine.store) if data.archive else None
    ok, message = await engine.reset_stats(delete_backtests=delete_backtests)
    if not ok:
        raise HTTPException(status_code=409, detail=message)
    return {
        "ok": True,
        "message": message,
        "counts": counts,
        "delete_backtests": delete_backtests,
        "archive_path": archive_path,
    }


@router.get("/events", response_model=EventsResponse)
async def events(request: Request, level: str | None = None, limit: int = 200) -> dict:
    return {"items": _engine(request).store.list_events(level, limit)}


@router.get("/orders", response_model=OrdersResponse)
async def orders(request: Request) -> dict:
    engine = _engine(request)
    return {"items": engine.execution.orders_snapshot(), "position": engine.execution.position_dict(engine.last_price)}


@router.get("/chart/history", response_model=ChartHistoryResponse)
async def chart_history(request: Request, limit: int = Query(default=3000, ge=100, le=10000)) -> dict:
    """Velas MNQ procesadas, incluidas las de sesiones anteriores."""
    engine = _engine(request)
    bars = list(engine.chart_history)[-limit:]
    return {"bars": bars, "count": len(bars), "session": engine.session_date}


def _flush_ledger_outbox(store: Any, run_id: str) -> dict[str, Any]:
    """Intenta convertir una fila del outbox en una entrada JSONL.

    La corrida ya está confirmada en SQLite. Cualquier fallo del archivo deja
    el outbox en ``pending`` y devuelve el error para que el cliente pueda
    reintentar sin repetir la simulación.
    """
    outbox = store.get_ledger_outbox(run_id)
    if outbox is None:
        return {"status": "missing", "error": "la corrida no tiene outbox de ledger"}
    if outbox.get("status") == "sent":
        return {
            "status": "sent",
            "ledger_event_id": outbox.get("ledger_event_id"),
            "ledger_event_sha256": outbox.get("ledger_event_sha256"),
        }
    try:
        raw = outbox.get("result_json")
        if not raw:
            raise ValueError("el resultado de la corrida no está disponible")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("el resultado persistido no es un objeto")
        record = ExperimentLedger().record_backtest(
            payload,
            hypothesis_id=str(outbox["hypothesis_id"]),
            run_id=run_id,
        )
        event_id = str(record.get("event_id") or "").strip()
        if not event_id:
            raise ValueError("el registro del ledger no tiene event_id")
        event_sha256 = ledger_record_sha256(record)
        store.mark_ledger_sent(
            run_id,
            ledger_event_id=event_id,
            ledger_event_sha256=event_sha256,
        )
        return {
            "status": "sent",
            "ledger_event_id": event_id,
            "ledger_event_sha256": event_sha256,
        }
    except Exception as exc:  # noqa: BLE001
        message = str(exc)
        try:
            store.mark_ledger_pending(run_id, message)
        except Exception:  # noqa: BLE001
            pass
        return {
            "status": "pending",
            "error": message,
            "hypothesis_id": str(outbox["hypothesis_id"]),
        }


def _reconcile_ledger_outbox(store: Any) -> dict[str, Any]:
    """Reconstruye el vínculo de corridas ``sent`` anteriores a la v5.

    Solo lee el ledger y escribe los vínculos que puede demostrar por
    ``run_id``/``result_id``. Las filas sin una única entrada verificable se
    devuelven en ``unresolved`` con su motivo, sin inventar eventos ni alterar
    el estado o los intentos del outbox.
    """
    rows = store.sent_ledger_outbox_without_event()
    report: dict[str, Any] = {
        "ok": True,
        "scanned": len(rows),
        "linked": 0,
        "updated": 0,
        "unresolved": [],
        "unresolved_count": 0,
        "ledger_records": 0,
    }
    if not rows:
        return report
    try:
        records = ExperimentLedger().records()
    except (LedgerError, OSError) as exc:
        unresolved = [
            {
                "backtest_run_id": row.get("backtest_run_id"),
                "result_id": row.get("result_id"),
                "hypothesis_id": row.get("hypothesis_id"),
                "reason": "ledger_unreadable",
                "detail": str(exc),
                "candidate_event_ids": [],
            }
            for row in rows
        ]
        report.update(
            {
                "ok": False,
                "unresolved": unresolved,
                "unresolved_count": len(unresolved),
                "error": str(exc),
            }
        )
        return report
    outcome = reconcile_ledger_links(
        rows,
        records,
        claimed_event_ids=store.linked_ledger_event_ids(),
    )
    report.update(
        {
            "ok": not outcome["unresolved"],
            "linked": len(outcome["linked"]),
            "updated": store.link_ledger_events(outcome["linked"]),
            "unresolved": outcome["unresolved"],
            "unresolved_count": len(outcome["unresolved"]),
            "ledger_records": len(records),
        }
    )
    return report


def _with_ledger_state(
    result: BacktestResult, state: dict[str, Any], hypothesis_id: str
) -> BacktestResult:
    """Proyecta el outbox en el bloque plano, sin formas distintas por estado."""
    sent = state.get("status") == "sent"
    return result.model_copy(
        update={
            "ledger_status": "sent" if sent else "pending",
            "hypothesis_id": hypothesis_id,
            "ledger_event_id": state.get("ledger_event_id") if sent else None,
            "ledger_event_sha256": (
                state.get("ledger_event_sha256") if sent else None
            ),
            "ledger_error": None if sent else state.get("error"),
        }
    )


@router.post("/backtest/ledger/retry")
async def retry_backtest_ledger(
    request: Request, run_id: str | None = Query(default=None)
) -> dict[str, Any]:
    """Reintenta los registros pendientes sin volver a simular la corrida."""
    store = _engine(request).store
    if run_id:
        outbox = store.get_ledger_outbox(run_id)
        if outbox is None:
            raise HTTPException(status_code=404, detail="Corrida sin outbox de ledger")
        targets = [run_id] if outbox.get("status") == "pending" else []
    else:
        targets = store.pending_ledger_run_ids()
    outcomes = [
        {"backtest_run_id": target, **_flush_ledger_outbox(store, target)}
        for target in targets
    ]
    return {
        "ok": all(item.get("status") == "sent" for item in outcomes),
        "retried": len(outcomes),
        "items": outcomes,
    }


@router.post("/backtest/ledger/reconcile")
async def reconcile_backtest_ledger(request: Request) -> dict[str, Any]:
    """Enlaza corridas ``sent`` previas a v5 con su entrada del ledger."""
    store = _engine(request).store
    return await asyncio.to_thread(_reconcile_ledger_outbox, store)


@router.get("/backtest/ledger/{run_id}")
async def backtest_ledger_status(request: Request, run_id: str) -> dict[str, Any]:
    """Estado visible del outbox para una corrida persistida."""
    outbox = _engine(request).store.get_ledger_outbox(run_id)
    if outbox is None:
        raise HTTPException(status_code=404, detail="Corrida sin outbox de ledger")
    return {
        key: outbox[key]
        for key in (
            "backtest_run_id",
            "result_id",
            "hypothesis_id",
            "status",
            "attempts",
            "last_error",
            "ledger_event_id",
            "ledger_event_sha256",
            "created_ts",
            "updated_ts",
        )
    }


@router.post(
    "/backtest/run", response_model=BacktestResult | BacktestVariantsResponse
)
async def backtest(payload: BacktestRequest, request: Request) -> Any:
    engine = _engine(request)
    if payload.hypothesis_id is not None:
        cleaned_hypothesis = str(payload.hypothesis_id).strip()
        if not cleaned_hypothesis or "\n" in cleaned_hypothesis or "\r" in cleaned_hypothesis:
            raise HTTPException(
                status_code=400,
                detail="hypothesis_id no puede estar vacío ni contener saltos de línea",
            )
        payload.hypothesis_id = cleaned_hypothesis
    if payload.hypothesis_id and payload.compare:
        raise HTTPException(
            status_code=400,
            detail="hypothesis_id requiere una corrida individual (compare=false)",
        )
    start = None
    if payload.start_date:
        try:
            from datetime import date as _date

            start = _date.fromisoformat(payload.start_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="start_date debe ser YYYY-MM-DD") from exc
    request_data = payload.model_dump()
    try:
        if payload.compare:
            if payload.persist and payload.idempotency_key:
                replay = engine.store.idempotent_response(
                    kind="variants",
                    request=request_data,
                    idempotency_key=payload.idempotency_key,
                )
                if replay is not None:
                    run_id, snapshot = replay
                    return BacktestVariantsResponse.model_validate(
                        {**snapshot, "backtest_run_id": run_id}
                    )
            results = await asyncio.to_thread(run_variants, engine.settings, payload.days, payload.overrides, start)
            body = BacktestVariantsResponse.model_validate(
                {
                    "variants": results,
                    "data_source": results[0]["data_source"] if results else "synthetic",
                    "backtest_run_id": None,
                }
            )
            backtest_run_id = None
            if payload.persist and results:
                backtest_run_id = engine.store.save_backtest(
                    results,
                    kind="variants",
                    label=payload.label,
                    days_requested=payload.days,
                    request=request_data,
                    idempotency_key=payload.idempotency_key,
                    response=body.model_dump(mode="json"),
                )
                if payload.idempotency_key:
                    replay = engine.store.idempotent_response(
                        kind="variants",
                        request=request_data,
                        idempotency_key=payload.idempotency_key,
                    )
                    if replay is not None:
                        run_id, snapshot = replay
                        body = BacktestVariantsResponse.model_validate(
                            {**snapshot, "backtest_run_id": run_id}
                        )
                        backtest_run_id = run_id
            return body.model_copy(update={"backtest_run_id": backtest_run_id})
        if payload.persist and payload.idempotency_key:
            replay = engine.store.idempotent_response(
                kind="single",
                request=request_data,
                idempotency_key=payload.idempotency_key,
            )
            if replay is not None:
                run_id, snapshot = replay
                replayed = BacktestResult.model_validate(
                    {**snapshot, "backtest_run_id": run_id}
                )
                if payload.hypothesis_id:
                    ledger_state = _flush_ledger_outbox(engine.store, run_id)
                    replayed = _with_ledger_state(
                        replayed, ledger_state, payload.hypothesis_id
                    )
                return replayed
        result = await asyncio.to_thread(
            run_backtest, engine.settings, payload.days, payload.overrides, payload.label, start
        )
        validated = BacktestResult.model_validate(result)
        backtest_run_id = None
        if payload.persist:
            backtest_run_id = engine.store.save_backtest(
                result,
                kind="single",
                request=request_data,
                idempotency_key=payload.idempotency_key,
                response=validated.model_dump(mode="json"),
                hypothesis_id=payload.hypothesis_id,
            )
            if payload.idempotency_key:
                replay = engine.store.idempotent_response(
                    kind="single",
                    request=request_data,
                    idempotency_key=payload.idempotency_key,
                )
                if replay is not None:
                    run_id, snapshot = replay
                    validated = BacktestResult.model_validate(
                        {**snapshot, "backtest_run_id": run_id}
                    )
                    backtest_run_id = run_id
            validated = validated.model_copy(
                update={"backtest_run_id": backtest_run_id}
            )
        if payload.hypothesis_id:
            if backtest_run_id:
                ledger_state = _flush_ledger_outbox(engine.store, backtest_run_id)
                validated = _with_ledger_state(
                    validated, ledger_state, payload.hypothesis_id
                )
            else:
                # Sin persistencia no hay corrida SQLite que relacionar; se
                # conserva el registro directo histórico.
                ExperimentLedger().record_backtest(
                    result, hypothesis_id=payload.hypothesis_id
                )
        return validated
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Backtest falló: {exc}") from exc


@router.get("/backtest/presets", response_model=PresetCatalogResponse)
async def backtest_presets_catalog(request: Request) -> dict:
    """Catálogo y procedencia configurada, sin ejecutar la simulación."""
    feed = _engine(request).settings.feed
    kind = "csv" if feed.provider == "csv" else "synthetic"
    path = feed.csv_path if kind == "csv" else None
    return {
        "presets": preset_catalog(),
        "default": list(DEFAULT_PRESETS),
        "count": len(DEFAULT_PRESETS),
        "total": len(PRESETS),
        "sample": {
            "provider": feed.provider,
            "kind": kind,
            "path": path,
            "file_name": Path(path).name if path else None,
            "series_mode": feed.series_mode,
            "exclude_roll_sessions": feed.exclude_roll_sessions,
        },
        "note": (
            "Los presets se aplican solo a la simulación, nunca al motor en vivo; "
            "no ejecutan el holdout ni modifican la configuración activa."
        ),
    }


@router.post("/backtest/presets", response_model=PresetComparisonResponse)
async def backtest_presets(
    payload: PresetBacktestRequest, request: Request
) -> PresetComparisonResponse:
    engine = _engine(request)
    start = None
    if payload.start_date:
        try:
            from datetime import date as _date

            start = _date.fromisoformat(payload.start_date)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="start_date debe ser YYYY-MM-DD") from exc
    request_data = payload.model_dump()
    try:
        if payload.persist and payload.idempotency_key:
            replay = engine.store.idempotent_response(
                kind="presets",
                request=request_data,
                idempotency_key=payload.idempotency_key,
            )
            if replay is not None:
                run_id, snapshot = replay
                return PresetComparisonResponse.model_validate(
                    {**snapshot, "backtest_run_id": run_id}
                )
        result = await asyncio.to_thread(
            run_presets,
            engine.settings,
            payload.days,
            payload.presets or None,
            payload.overrides,
            start,
        )
        body = {
            key: result[key]
            for key in (
                "created_ts",
                "data_source",
                "is_synthetic",
                "dataset",
                "dataset_id",
                "days_requested",
                "sessions",
                "overrides",
                "base_config",
                "default_presets",
                "preset_keys",
                "comparison",
                "sample",
            )
        } | {
            "backtest_run_id": None,
            "note": (
                "Comparación exploratoria sobre el mismo dataset. Los presets no se "
                "aplican a la configuración activa ni al holdout."
            ),
        }
        validated = PresetComparisonResponse.model_validate(body)
        backtest_run_id = None
        if payload.persist:
            backtest_run_id = engine.store.save_backtest(
                result,
                kind="presets",
                days_requested=payload.days,
                request=request_data,
                idempotency_key=payload.idempotency_key,
                response=validated.model_dump(mode="json"),
            )
            if payload.idempotency_key:
                replay = engine.store.idempotent_response(
                    kind="presets",
                    request=request_data,
                    idempotency_key=payload.idempotency_key,
                )
                if replay is not None:
                    run_id, snapshot = replay
                    validated = PresetComparisonResponse.model_validate(
                        {**snapshot, "backtest_run_id": run_id}
                    )
                    backtest_run_id = run_id
        return validated.model_copy(update={"backtest_run_id": backtest_run_id})
    except IdempotencyConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"Comparación de presets falló: {exc}") from exc


def _split_query_values(values: list[str]) -> list[str]:
    out: list[str] = []
    for value in values:
        for part in str(value or "").split(","):
            clean = part.strip()
            if clean and clean not in out:
                out.append(clean)
    return out


def _compare_backtest_results(
    store,
    result_ids: list[str],
    baseline_id: str | None,
    metrics: list[str],
) -> dict:
    ids = _split_query_values(result_ids)
    if not 2 <= len(ids) <= 4:
        raise HTTPException(
            status_code=400,
            detail="La comparación requiere entre 2 y 4 resultados",
        )
    if baseline_id is None:
        baseline_id = ids[0]
    if baseline_id not in ids:
        raise HTTPException(
            status_code=400,
            detail="baseline_id debe estar incluido en result_ids",
        )

    selected = _split_query_values(metrics) or list(DEFAULT_COMPARE_METRICS)
    unknown = [metric for metric in selected if metric not in COMPARE_METRIC_CATALOG]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Métricas desconocidas: {', '.join(unknown)}",
        )

    rows = store.backtest_results_for_compare(ids)
    by_id = {str(row["id"]): row for row in rows}
    missing = [result_id for result_id in ids if result_id not in by_id]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Resultados no encontrados: {', '.join(missing)}",
        )
    ordered = [by_id[result_id] for result_id in ids]

    warnings: list[str] = []

    def warn(value: str) -> None:
        if value not in warnings:
            warnings.append(value)

    def metrics_data(row: dict) -> dict:
        try:
            data = json.loads(row.get("metrics_json") or "{}")
        except (TypeError, ValueError):
            warn("metrics_json_invalid")
            data = {}
        if not isinstance(data, dict):
            warn("metrics_json_invalid")
            data = {}
        for key in ("trades", "net_profit", "max_drawdown_pct", "profit_factor"):
            if key not in data and row.get(key) is not None:
                data[key] = row[key]
        return data

    baseline_data = metrics_data(next(row for row in ordered if row["id"] == baseline_id))
    comparable = True
    for field in ("dataset_sha256", "config_sha256", "code_sha256"):
        if len({row.get(field) for row in ordered}) > 1:
            comparable = False
            warn(f"{field}_mismatch")

    output_rows = []
    for row in ordered:
        data = metrics_data(row)
        values = {}
        delta = {}
        for metric in selected:
            if metric not in data:
                warn(f"missing_metric:{metric}")
            value = data.get(metric)
            values[metric] = value
            base = baseline_data.get(metric)
            if (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and isinstance(base, (int, float))
                and not isinstance(base, bool)
            ):
                delta[metric] = round(float(value) - float(base), 4)
            else:
                delta[metric] = None
        output_rows.append(
            {
                "result_id": row["id"],
                "backtest_run_id": row["backtest_run_id"],
                "label": row["label"],
                "variant": row["variant"],
                "preset": row["preset"],
                "metrics": values,
                "delta_vs_baseline": delta,
            }
        )
    return {
        "baseline_id": baseline_id,
        "comparable": comparable,
        "warnings": warnings,
        "rows": output_rows,
    }


@router.get("/backtest/runs")
async def backtest_runs(
    request: Request,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    kind: Literal["single", "variants", "presets"] | None = Query(default=None),
    legacy: bool | None = Query(default=None),
    date_from: str | None = Query(default=None),
    date_to: str | None = Query(default=None),
    dataset: str | None = Query(default=None),
    dataset_id: str | None = Query(default=None),
    label: str | None = Query(default=None),
    cursor: str | None = Query(default=None),
) -> dict:
    """Historial con paginación por cursor y filtros; ``limit/offset`` sigue vivo."""
    try:
        start = _parse_backtest_ts(date_from) if date_from else None
        end = _parse_backtest_ts(date_to, end=True) if date_to else None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if start is not None and end is not None and start > end:
        raise HTTPException(
            status_code=400, detail="date_from no puede ser posterior a date_to"
        )
    try:
        return _engine(request).store.list_backtest_runs(
            limit=limit,
            offset=offset,
            kind=kind,
            legacy=legacy,
            date_from=start,
            date_to=end,
            dataset_id=dataset_id or dataset,
            label=label,
            cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/backtest/runs/legacy-diagnostics")
async def legacy_backtest_diagnostics(request: Request) -> dict:
    """Diagnóstico de solo lectura del legado no indexado o inválido."""
    return _engine(request).store.legacy_diagnostics()


@router.get("/backtest/runs/legacy-repair")
async def preview_legacy_backtest_repair(request: Request) -> dict:
    """Dry-run explícito de la reindexación del legado."""
    return _engine(request).store.repair_legacy_backtests(dry_run=True)


@router.post("/backtest/runs/legacy-repair")
async def repair_legacy_backtest_rows(
    request: Request,
    payload: LegacyRepairRequest | None = None,
    dry_run: bool | None = Query(default=None),
) -> dict:
    """Reindexa filas legacy válidas; solo escribe con ``dry_run=false``."""
    effective = (
        dry_run
        if dry_run is not None
        else (payload.dry_run if payload is not None else True)
    )
    return _engine(request).store.repair_legacy_backtests(dry_run=effective)


@router.get("/backtest/runs/compare")
async def compare_backtest_runs(
    request: Request,
    result_ids: list[str] = Query(default=[]),
    ids: list[str] = Query(default=[]),
    baseline_id: str | None = Query(default=None),
    metrics: list[str] = Query(default=[]),
) -> dict:
    """Compara resultados guardados por id, con delta contra el baseline."""
    requested = _split_query_values(result_ids) + _split_query_values(ids)
    return _compare_backtest_results(
        _engine(request).store,
        requested,
        baseline_id,
        metrics,
    )


@router.post("/backtest/compare")
async def compare_backtest_results(payload: BacktestCompareRequest, request: Request) -> dict:
    """Alias POST del comparador para clientes que envían el cuerpo JSON."""
    return _compare_backtest_results(
        _engine(request).store,
        payload.result_ids,
        payload.baseline_id,
        payload.metrics,
    )


@router.get("/backtest/runs/{run_id}")
async def backtest_run_detail(run_id: str, request: Request) -> dict:
    """Detalle de una corrida y resumen de todos sus resultados."""
    detail = _engine(request).store.get_backtest_run(run_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="Corrida de backtest no encontrada")
    return detail


@router.get("/backtest/results/{result_id}")
async def backtest_result_detail(result_id: str, request: Request) -> dict:
    """Resultado completo, resolviendo payload nuevo o fila legacy."""
    result = _engine(request).store.get_backtest_result(result_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Resultado de backtest no encontrado")
    return result


@router.get("/backtest/latest")
async def latest_backtest(request: Request) -> dict:
    result = _engine(request).store.latest_backtest()
    return {"result": result}


@router.get("/datasets")
async def datasets(request: Request) -> dict:
    engine = _engine(request)
    return {
        "provider": engine.settings.feed.provider,
        "csv_path": engine.settings.feed.csv_path,
        "required_symbols": list(REQUIRED_SYMBOLS),
        "schema_version": DATA_SCHEMA_VERSION,
        "format": (
            "timestamp,symbol,open,high,low,close,volume[,contract][,expiry] · 1m · "
            "ISO-8601 con zona o epoch"
        ),
        "series_modes": sorted(SERIES_MODES),
        "series_mode": engine.settings.feed.series_mode,
        "exclude_roll_sessions": engine.settings.feed.exclude_roll_sessions,
        "roll_policy": "excluir la sesión de roll (última del contrato saliente)",
        "synthetic_available": True,
        "note": (
            "El generador sintético existe solo para replay/backtest de desarrollo. "
            "No representa el mercado real. Importa un CSV de tu proveedor para backtests reales. "
            "Cada backtest guarda dataset_id, series_id, hash, rango efectivo, contratos/vencimientos, "
            "plan de rolls y configuración de feed/ejecución."
        ),
    }


@router.post("/data/validate")
async def validate_data(payload: CsvValidateRequest, request: Request) -> dict:
    """Valida un CSV local sin aplicarlo ni arrancar el motor."""
    engine = _engine(request)
    raw = (payload.path or engine.settings.feed.csv_path or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="Indica la ruta del CSV a validar")
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = BASE_DIR / path
    path = path.resolve()
    if path.suffix.lower() != ".csv":
        raise HTTPException(status_code=400, detail="El archivo debe tener extensión .csv")
    if not path.is_file():
        raise HTTPException(status_code=400, detail=f"No existe el CSV: {path}")
    series_mode = payload.series_mode or engine.settings.feed.series_mode
    exclude_roll_sessions = (
        engine.settings.feed.exclude_roll_sessions
        if payload.exclude_roll_sessions is None
        else payload.exclude_roll_sessions
    )
    if series_mode not in SERIES_MODES:
        raise HTTPException(status_code=400, detail="series_mode debe ser raw o adjusted")
    report = await asyncio.to_thread(
        inspect_csv,
        path,
        REQUIRED_SYMBOLS,
        series_mode=series_mode,
        exclude_roll_sessions=exclude_roll_sessions,
    )
    try:
        refuse_holdout_sessions(report.get("all_sessions") or [])
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return report


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await websocket.accept()
    engine = websocket.app.state.engine
    queue = engine.subscribe()
    try:
        await websocket.send_json({"type": "snapshot", "data": engine.snapshot()})
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), timeout=12)
            except asyncio.TimeoutError:
                message = {"type": "ping", "data": {"ts": int(time.time() * 1000)}}
            await websocket.send_json(message)
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001
        pass
    finally:
        engine.unsubscribe(queue)
