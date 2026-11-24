"""Modelos públicos de respuesta que reflejan los tipos del frontend.

El frontend consume ``/api`` con interfaces TypeScript en ``frontend/src/types.ts``.
Estos modelos existen para que ``/openapi.json`` documente esos campos y para que
FastAPI valide la forma de las respuestas. Llevan ``extra="allow"`` cuando el
motor devuelve métricas adicionales que el frontend no consume: el contrato
declara lo necesario sin recortar la respuesta.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Phase(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    label: str
    status: Literal[
        "pending", "in_progress", "confirmed", "rejected", "expired", "waiting"
    ]
    detail: str
    ts: int | None


class Quote(BaseModel):
    model_config = ConfigDict(extra="allow")

    symbol: str
    last: float
    change: float
    change_pct: float
    ts: int | None
    volume: float


class OHLC(BaseModel):
    model_config = ConfigDict(extra="allow")

    t: int
    o: float
    h: float
    l: float
    c: float
    v: float


class ChartPoint(BaseModel):
    model_config = ConfigDict(extra="allow")

    t: int
    c: float


class Marker(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts: int
    price: float
    type: str
    direction: str
    label: str


class OpeningRange(BaseModel):
    model_config = ConfigDict(extra="allow")

    date: str
    start_ts: int
    end_ts: int
    high: float
    low: float
    mid: float
    width: float
    width_pct: float
    bars: int
    complete: bool


class SmtInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    bias: Literal["bullish", "bearish"]
    level: float
    primary_prev: float
    primary_last: float
    reference_prev: float
    reference_last: float
    confirm_ts: int
    expires_ts: int
    pivot_ts: int


class BreakoutInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    direction: Literal["long", "short"]
    level: float
    close: float
    ts: int
    confirm_ts: int
    timeframe: str
    type: str
    failed: bool | None = None


class RetestInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    level: float
    name: str
    touch_ts: int
    touch_price: float
    tolerance_ticks: int


class Signal(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    ts: int
    direction: Literal["long", "short"]
    entry_price: float
    stop: float
    target: float
    qty: int
    risk_amount: float
    signal_type: str
    entry_reason: str
    reference_level: float
    breakout_level: float
    smt_bias: str | None


class Position(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    symbol: str
    direction: Literal["long", "short"]
    qty: int
    entry_price: float
    entry_ts: int
    stop: float
    target: float
    initial_stop: float
    risk_amount: float
    signal_id: str
    signal_type: str
    entry_reason: str
    mode: str
    current_price: float
    unrealized: float
    r_multiple: float
    mfe_r: float | None = None
    mae_r: float | None = None
    mfe_usd: float | None = None
    mae_usd: float | None = None
    open_drawdown: float | None = None


class Order(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    symbol: str
    side: Literal["buy", "sell"]
    qty: int
    order_type: str
    limit_price: float | None
    role: Literal["entry", "stop", "target"]
    status: str
    created_ts: int
    filled_ts: int | None
    filled_price: float | None
    reason: str


class Trade(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    mode: str
    symbol: str
    direction: Literal["long", "short"]
    qty: int
    entry_ts: int
    entry_price: float
    exit_ts: int
    exit_price: float
    stop: float
    target: float
    pnl: float
    gross_pnl: float
    fees: float
    r_multiple: float
    risk_amount: float
    signal_type: str
    entry_reason: str
    exit_reason: str
    duration_sec: int
    mfe_r: float | None = None
    mae_r: float | None = None
    mfe_usd: float | None = None
    mae_usd: float | None = None
    open_drawdown: float | None = None
    contract: str | None = None
    expiry: str | None = None
    meta: dict[str, Any] | None = None


class EquityPoint(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts: int
    equity: float


class DailyBucket(BaseModel):
    key: str
    label: str
    pnl: float


class MonthlyBucket(BaseModel):
    key: str
    label: str
    trades: int
    pnl: float
    wins: int
    win_rate: float


class HourBucket(BaseModel):
    key: int
    label: str
    trades: int
    pnl: float
    wins: int
    win_rate: float


class DirectionBucket(BaseModel):
    key: str
    label: str
    trades: int
    pnl: float
    wins: int
    win_rate: float


class SignalBucket(BaseModel):
    key: str
    label: str
    trades: int
    pnl: float
    wins: int
    win_rate: float


class WeekdayBucket(BaseModel):
    key: int
    label: str
    trades: int
    pnl: float
    wins: int


class Distribution(BaseModel):
    wins: int
    losses: int
    breakeven: int


class Stats(BaseModel):
    model_config = ConfigDict(extra="allow")

    trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    profit_factor: float | None
    expectancy: float
    net_profit: float
    gross_profit: float
    gross_loss: float
    fees: float
    avg_win: float
    avg_loss: float
    avg_trade: float
    avg_r: float
    avg_mfe_r: float | None = None
    avg_mae_r: float | None = None
    avg_open_drawdown: float | None = None
    max_open_drawdown: float | None = None
    max_open_drawdown_pct: float | None = None
    open_drawdown: float | None = None
    open_drawdown_pct: float | None = None
    avg_mfe: float | None = None
    avg_mae: float | None = None
    total_r: float
    avg_win_r: float
    avg_loss_r: float
    best_trade: float
    worst_trade: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe: float | None
    sortino: float | None
    best_win_streak: int
    worst_loss_streak: int
    avg_duration_sec: int
    equity_curve: list[EquityPoint]
    daily: list[DailyBucket]
    monthly: list[MonthlyBucket]
    by_hour: list[HourBucket]
    by_direction: list[DirectionBucket]
    by_signal: list[SignalBucket]
    by_weekday: list[WeekdayBucket]
    distribution: Distribution


class EventItem(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    ts: int
    level: str
    category: str
    message: str
    meta: dict[str, Any] | None = None


class DatasetRange(BaseModel):
    model_config = ConfigDict(extra="allow")

    first_ts: int | None
    last_ts: int | None
    first_et: str | None
    last_et: str | None


class DatasetSessions(BaseModel):
    model_config = ConfigDict(extra="allow")

    count: int
    available: int
    dates: list[str]


class DatasetInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    series_id: str | None = None
    selected_id: str | None = None
    kind: str
    source: str | None = None
    schema_version: str | None = None
    path: str | None = None
    file_name: str | None = None
    file_hash: str | None = None
    row_count: int | None = None
    common_bars: int | None = None
    contracts: dict[str, list[str]] = Field(default_factory=dict)
    contract_column: bool | None = None
    contracts_declared: bool | None = None
    expiry_column: bool | None = None
    contract_expiries: dict[str, str] = Field(default_factory=dict)
    series_mode: str | None = None
    contracts_by_session: dict[str, dict[str, str]] = Field(default_factory=dict)
    expiry_by_session: dict[str, dict[str, str]] = Field(default_factory=dict)
    rolls: list[dict[str, Any]] = Field(default_factory=list)
    roll_sessions: list[str] = Field(default_factory=list)
    excluded_sessions: list[str] = Field(default_factory=list)
    all_sessions: list[str] = Field(default_factory=list)
    range: DatasetRange | None = None
    selected_range: DatasetRange | None = None
    requested_start: str | None = None
    selection: str | None = None
    sessions: DatasetSessions | None = None
    aligned: bool | None = None
    gaps: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
    generator: str | None = None
    generator_version: str | None = None


class FeedInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    kind: str
    label: str
    quality: str
    connected: bool
    detail: str
    simulated: bool | None = None
    source: str | None = None
    path: str | None = None
    dataset_id: str | None = None
    series_id: str | None = None
    file_hash: str | None = None
    schema_version: str | None = None
    contracts: dict[str, list[str]] | None = None
    contract_column: bool | None = None
    contracts_declared: bool | None = None
    expiry_column: bool | None = None
    contract_expiries: dict[str, str] | None = None
    series_mode: str | None = None
    contracts_by_session: dict[str, dict[str, str]] | None = None
    rolls: list[dict[str, Any]] | None = None
    roll_sessions: list[str] | None = None
    excluded_sessions: list[str] | None = None
    range: DatasetRange | None = None
    sessions: int | None = None
    all_sessions: list[str] | None = None
    bars: int | None = None
    first_ts: int | None = None
    last_ts: int | None = None
    aligned: bool | None = None
    session: str | None = None
    last_bar_ts: int | None = None
    last_update_ms: int | None = None
    stale: bool | None = None
    delayed: bool | None = None


class AmbiguousBar(BaseModel):
    model_config = ConfigDict(extra="allow")

    ts: int
    direction: Literal["long", "short"]
    open: float
    high: float
    low: float
    close: float
    stop: float
    target: float
    gap_stop: bool
    gap_target: bool
    resolution: str
    mfe_r: float | None = None
    mae_r: float | None = None
    open_drawdown: float | None = None
    trade_id: str | None = None
    exit_price: float | None = None
    pnl: float | None = None


class SnapshotSession(BaseModel):
    date: str | None
    or_start: str
    or_end: str
    timezone: str
    trade_window_start: str
    trade_window_end: str
    close_time: str


class SnapshotAssessment(BaseModel):
    phases: list[Phase]
    breakout: BreakoutInfo | None
    smt: SmtInfo | None
    retest: RetestInfo | None
    reject: str | None
    signal: Signal | None
    reference_level: float | None
    atr: float | None


class SnapshotRisk(BaseModel):
    model_config = ConfigDict(extra="allow")

    equity: float
    day_start_equity: float
    daily_pnl: float
    daily_pnl_pct: float
    cum_pnl: float
    risk_per_trade_pct: float
    risk_open_pct: float
    risk_open_amount: float
    trades_today: int
    max_trades_per_day: int
    daily_loss_limit: float
    daily_profit_limit: float | None
    max_daily_loss_pct: float
    max_drawdown_pct: float
    open_drawdown: float
    open_drawdown_pct: float
    max_open_drawdown: float
    emergency: bool
    emergency_reason: str | None
    blocked_reason: str | None
    initial_capital: float


class SnapshotAmbiguous(BaseModel):
    count: int
    recent: list[AmbiguousBar]


class SnapshotChart(BaseModel):
    bars: list[OHLC]
    nq: list[ChartPoint]
    es: list[ChartPoint]
    markers: list[Marker]
    smt: SmtInfo | None


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="allow")

    server_time: int
    status: str
    mode: str
    instrument: str
    reference_symbol: str
    comparison_symbol: str
    data: FeedInfo
    session: SnapshotSession
    quotes: dict[str, Quote]
    opening_range: OpeningRange | None
    assessment: SnapshotAssessment
    position: Position | None
    orders: list[Order]
    risk: SnapshotRisk
    stats: Stats
    day_stats: Stats
    recent_trades: list[Trade]
    ambiguous_bars: SnapshotAmbiguous
    events: list[EventItem]
    chart: SnapshotChart
    config: dict[str, Any]
    settings: dict[str, Any]


class TradesResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[Trade]
    total: int
    limit: int
    offset: int


class EventsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[EventItem]


class OrdersResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    items: list[Order]
    position: Position | None


class ChartHistoryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    bars: list[OHLC]
    count: int
    session: str | None


class PresetSample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["activity", "no_trades", "insufficient"]
    active_presets: int = Field(ge=0)
    total_presets: int = Field(ge=0)
    sessions: int = Field(ge=0)
    days_requested: int = Field(ge=0)
    min_sessions: int = Field(ge=1)
    detail: str = Field(min_length=1)


class PresetCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    label: str
    group: str
    description: str
    default: bool
    patch: dict[str, Any]


class PresetCatalogSample(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str
    kind: Literal["csv", "synthetic"]
    path: str | None
    file_name: str | None
    series_mode: str
    exclude_roll_sessions: bool


class PresetCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    presets: list[PresetCatalogEntry]
    default: list[str]
    count: int
    total: int
    sample: PresetCatalogSample
    note: str


class BacktestVariant(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    variant: str
    created_ts: int
    label: str
    data_source: Literal["csv", "synthetic"]
    data_quality: str
    dataset: dict[str, Any] | None = None
    dataset_id: str | None = None
    data_range: dict[str, Any] | None = None
    is_synthetic: bool
    config: dict[str, Any]
    metrics: dict[str, Any]
    diagnostics: dict[str, Any]
    trades: list[dict[str, Any]]
    equity: list[EquityPoint]
    days_detail: list[dict[str, Any]]
    funnel: dict[str, Any]


class BacktestVariantsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    backtest_run_id: str | None = None
    variants: list[BacktestVariant]
    data_source: Literal["csv", "synthetic"]
