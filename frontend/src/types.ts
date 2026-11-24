export type PhaseStatus = 'pending' | 'in_progress' | 'confirmed' | 'rejected' | 'expired' | 'waiting';

export interface Phase {
  key: string;
  label: string;
  status: PhaseStatus;
  detail: string;
  ts: number | null;
}

export interface Quote {
  symbol: string;
  last: number;
  change: number;
  change_pct: number;
  ts: number | null;
  volume: number;
}

export interface OHLC {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface Marker {
  ts: number;
  price: number;
  type: string;
  direction: string;
  label: string;
}

export interface OpeningRange {
  date: string;
  start_ts: number;
  end_ts: number;
  high: number;
  low: number;
  mid: number;
  width: number;
  width_pct: number;
  bars: number;
  complete: boolean;
}

export interface SmtInfo {
  bias: 'bullish' | 'bearish';
  level: number;
  primary_prev: number;
  primary_last: number;
  reference_prev: number;
  reference_last: number;
  confirm_ts: number;
  expires_ts: number;
  pivot_ts: number;
}

export interface BreakoutInfo {
  direction: 'long' | 'short';
  level: number;
  close: number;
  ts: number;
  confirm_ts: number;
  timeframe: string;
  type: string;
  failed?: boolean;
}

export interface RetestInfo {
  level: number;
  name: string;
  touch_ts: number;
  touch_price: number;
  tolerance_ticks: number;
}

export interface Signal {
  id: string;
  ts: number;
  direction: 'long' | 'short';
  entry_price: number;
  stop: number;
  target: number;
  qty: number;
  risk_amount: number;
  signal_type: string;
  entry_reason: string;
  reference_level: number;
  breakout_level: number;
  smt_bias: string | null;
}

export interface Position {
  id: string;
  symbol: string;
  direction: 'long' | 'short';
  qty: number;
  entry_price: number;
  entry_ts: number;
  stop: number;
  target: number;
  initial_stop: number;
  risk_amount: number;
  signal_id: string;
  signal_type: string;
  entry_reason: string;
  mode: string;
  current_price: number;
  unrealized: number;
  r_multiple: number;
  mfe_r?: number;
  mae_r?: number;
  mfe_usd?: number;
  mae_usd?: number;
  open_drawdown?: number;
}

export interface Order {
  id: string;
  symbol: string;
  side: 'buy' | 'sell';
  qty: number;
  order_type: string;
  limit_price: number | null;
  role: 'entry' | 'stop' | 'target';
  status: string;
  created_ts: number;
  filled_ts: number | null;
  filled_price: number | null;
  reason: string;
}

export interface Trade {
  id: string;
  mode: string;
  symbol: string;
  direction: 'long' | 'short';
  qty: number;
  entry_ts: number;
  entry_price: number;
  exit_ts: number;
  exit_price: number;
  stop: number;
  target: number;
  pnl: number;
  gross_pnl: number;
  fees: number;
  r_multiple: number;
  risk_amount: number;
  signal_type: string;
  entry_reason: string;
  exit_reason: string;
  duration_sec: number;
  mfe_r?: number;
  mae_r?: number;
  mfe_usd?: number;
  mae_usd?: number;
  open_drawdown?: number;
  contract?: string;
  expiry?: string | null;
  meta?: Record<string, unknown>;
}

export interface EquityPoint {
  ts: number;
  equity: number;
}

export interface Stats {
  trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number;
  profit_factor: number | null;
  expectancy: number;
  net_profit: number;
  gross_profit: number;
  gross_loss: number;
  fees: number;
  avg_win: number;
  avg_loss: number;
  avg_trade: number;
  avg_r: number;
  avg_mfe_r?: number;
  avg_mae_r?: number;
  avg_open_drawdown?: number;
  max_open_drawdown?: number;
  max_open_drawdown_pct?: number;
  open_drawdown?: number;
  open_drawdown_pct?: number;
  avg_mfe?: number;
  avg_mae?: number;
  total_r: number;
  avg_win_r: number;
  avg_loss_r: number;
  best_trade: number;
  worst_trade: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  sharpe: number | null;
  sortino: number | null;
  best_win_streak: number;
  worst_loss_streak: number;
  avg_duration_sec: number;
  equity_curve: EquityPoint[];
  daily: Array<{ key: string; label: string; pnl: number }>;
  monthly: Array<{ key: string; label: string; trades: number; pnl: number; wins: number; win_rate: number }>;
  by_hour: Array<{ key: number; label: string; trades: number; pnl: number; wins: number; win_rate: number }>;
  by_direction: Array<{ key: string; label: string; trades: number; pnl: number; wins: number; win_rate: number }>;
  by_signal: Array<{ key: string; label: string; trades: number; pnl: number; wins: number; win_rate: number }>;
  by_weekday: Array<{ key: number; label: string; trades: number; pnl: number; wins: number }>;
  distribution: { wins: number; losses: number; breakeven: number };
}

export interface EventItem {
  id: number;
  ts: number;
  level: 'INFO' | 'SUCCESS' | 'WARNING' | 'ERROR' | string;
  category: string;
  message: string;
  meta?: Record<string, unknown>;
}

export interface FeedInfo {
  kind: string;
  label: string;
  quality: string;
  connected: boolean;
  detail: string;
  simulated?: boolean;
  source?: string | null;
  path?: string | null;
  dataset_id?: string | null;
  series_id?: string | null;
  file_hash?: string | null;
  schema_version?: string | null;
  contracts?: Record<string, string[]>;
  contract_column?: boolean;
  contracts_declared?: boolean;
  expiry_column?: boolean;
  contract_expiries?: Record<string, string>;
  series_mode?: 'raw' | 'adjusted';
  contracts_by_session?: Record<string, Record<string, string>>;
  rolls?: Array<Record<string, unknown>>;
  roll_sessions?: string[];
  excluded_sessions?: string[];
  range?: DatasetRange | null;
  sessions?: number | null;
  all_sessions?: string[];
  bars?: number | null;
  first_ts?: number | null;
  last_ts?: number | null;
  aligned?: boolean | null;
  session?: string | null;
  last_bar_ts?: number | null;
  last_update_ms?: number | null;
  stale?: boolean;
  delayed?: boolean;
}

export interface DatasetRange {
  first_ts: number | null;
  last_ts: number | null;
  first_et: string | null;
  last_et: string | null;
}

export interface DatasetInfo {
  id: string;
  series_id?: string;
  selected_id?: string;
  kind: 'csv' | 'synthetic' | string;
  source?: string;
  schema_version?: string;
  path?: string | null;
  file_name?: string | null;
  file_hash?: string | null;
  row_count?: number;
  common_bars?: number;
  contracts?: Record<string, string[]>;
  contract_column?: boolean;
  contracts_declared?: boolean;
  expiry_column?: boolean;
  contract_expiries?: Record<string, string>;
  series_mode?: 'raw' | 'adjusted';
  contracts_by_session?: Record<string, Record<string, string>>;
  expiry_by_session?: Record<string, Record<string, string>>;
  rolls?: Array<Record<string, unknown>>;
  roll_sessions?: string[];
  excluded_sessions?: string[];
  all_sessions?: string[];
  range?: DatasetRange;
  selected_range?: DatasetRange;
  requested_start?: string | null;
  selection?: 'start_date' | 'last_n' | 'default' | string;
  sessions?: { count: number; available: number; dates: string[] };
  aligned?: boolean;
  gaps?: { count: number; max_gap_seconds: number };
  warnings?: string[];
  generator?: string;
  generator_version?: string;
}

export interface Snapshot {
  server_time: number;
  status: 'running' | 'paused' | 'stopped';
  mode: 'paper' | 'live';
  instrument: string;
  reference_symbol: string;
  comparison_symbol: string;
  data: FeedInfo;
  session: {
    date: string | null;
    or_start: string;
    or_end: string;
    timezone: string;
    trade_window_start: string;
    trade_window_end: string;
    close_time: string;
  };
  quotes: Record<string, Quote>;
  opening_range: OpeningRange | null;
  assessment: {
    phases: Phase[];
    breakout: BreakoutInfo | null;
    smt: SmtInfo | null;
    retest: RetestInfo | null;
    reject: string | null;
    signal: Signal | null;
    reference_level: number | null;
    atr: number | null;
  };
  position: Position | null;
  orders: Order[];
  risk: {
    equity: number;
    day_start_equity: number;
    daily_pnl: number;
    daily_pnl_pct: number;
    cum_pnl: number;
    risk_per_trade_pct: number;
    risk_open_pct: number;
    risk_open_amount: number;
    trades_today: number;
    max_trades_per_day: number;
    daily_loss_limit: number;
    daily_profit_limit: number | null;
    max_daily_loss_pct: number;
    max_drawdown_pct: number;
    open_drawdown: number;
    open_drawdown_pct: number;
    max_open_drawdown: number;
    emergency: boolean;
    emergency_reason: string | null;
    blocked_reason: string | null;
    initial_capital: number;
  };
  stats: Stats;
  day_stats: Stats;
  recent_trades: Trade[];
  ambiguous_bars: {
    count: number;
    recent: AmbiguousBar[];
  };
  events: EventItem[];
  chart: {
    bars: OHLC[];
    nq: Array<{ t: number; c: number }>;
    es: Array<{ t: number; c: number }>;
    markers: Marker[];
    smt: SmtInfo | null;
  };
  config: Record<string, unknown>;
  settings: Record<string, any>;
}

export interface ForwardValidationMetrics {
  ops: number;
  net_usd: number;
  profit_factor: number;
  max_drawdown_usd: number;
  max_drawdown_pct: number;
  expectancy_usd: number;
  expectancy_r: number;
  total_r: number;
}

export type ForwardValidationStatus = 'reference' | 'validated' | 'rejected' | 'insufficient_data';

export interface ForwardValidationCandidate {
  id: string;
  label: string;
  short_label: string;
  role: 'baseline' | 'candidate';
  profile: string | null;
  profile_sha256: string | null;
  implementation: string;
  production_available?: boolean;
  dev_metrics: ForwardValidationMetrics;
  forward_metrics: ForwardValidationMetrics | null;
  forward_status: ForwardValidationStatus;
  forward_note: string;
}

export interface ForwardValidationReport {
  schema: string;
  generated_at: string;
  status: string;
  decision: {
    kind: 'keep_current' | 'adopt_candidate';
    label: string;
    adopted_candidate: string | null;
    live_config_updated: boolean;
    current_profile: string;
    current_profile_sha256: string;
    summary: string;
    reasons: string[];
  };
  development: {
    window: string;
    start: string;
    end: string;
    sessions: number;
    status: 'in_sample' | string;
    role: string;
    source: string;
    note: string;
  };
  forward: {
    status: ForwardValidationStatus | string;
    evaluated: boolean;
    attempts: number;
    available_sessions: number;
    available_bars: number;
    dataset_last_session: string;
    dataset_last_bar_et: string;
    summary: string;
    reasons: string[];
    candidate_forward_protocol: string | null;
    earliest_preregistered_window?: {
      start: string;
      end: string;
      source: string;
      hypothesis: string;
      applicable_to_candidates: boolean;
    };
  };
  holdout: {
    id: string;
    start: string;
    end: string;
    sessions: number;
    status: string;
    executed: boolean;
    used_for_decision: boolean;
    lock_path: string;
    lock_sha256: string;
  };
  candidates: ForwardValidationCandidate[];
  integrity: Record<string, unknown>;
}

export interface BacktestResult {
  backtest_run_id?: string | null;
  // Vínculo plano con el ledger; las cinco claves se emiten juntas.
  ledger_status?: 'pending' | 'sent' | null;
  hypothesis_id?: string | null;
  ledger_event_id?: string | null;
  ledger_event_sha256?: string | null;
  ledger_error?: string | null;
  id: string;
  created_ts: number;
  label: string;
  data_source: string;
  data_quality?: string;
  dataset_id?: string;
  dataset?: DatasetInfo;
  data_range?: DatasetRange;
  is_synthetic?: boolean;
  config: Record<string, any>;
  metrics: Stats & { days_traded: number; winning_days: number; losing_days: number };
  diagnostics?: {
    intrabar_model?: Record<string, string | number>;
    ambiguous_bars?: { count: number; items: AmbiguousBar[] };
  };
  trades: Trade[];
  equity: EquityPoint[];
  days_detail: Array<{ date: string; pnl: number; trades: number; equity: number }>;
  variant?: string;
}

export interface PresetComparisonRow {
  result_id?: string;
  preset: string;
  label: string;
  group: string;
  description: string;
  is_synthetic: boolean;
  trades: number;
  signals: number;
  breakouts: number;
  retests: number;
  days_traded: number;
  win_rate: number;
  profit_factor: number | null;
  expectancy: number;
  net_profit: number;
  max_drawdown: number;
  max_drawdown_pct: number;
  avg_r: number;
  total_r: number;
  sharpe: number | null;
  sortino: number | null;
  stop_losses: number;
  take_profits: number;
  session_closes: number;
  stop_loss_rate: number;
  take_profit_rate: number;
  avg_stop_ticks: number;
  stop_cap_sessions: number;
  qty_zero_sessions: number;
  final_equity: number | null;
  delta?: Record<string, number | null>;
}

export interface PresetCatalogEntry {
  key: string;
  label: string;
  group: string;
  description: string;
  default: boolean;
  patch: Record<string, unknown>;
}

export interface PresetCatalogSample {
  provider: string;
  kind: 'csv' | 'synthetic';
  path: string | null;
  file_name: string | null;
  series_mode: 'raw' | 'adjusted' | string;
  exclude_roll_sessions: boolean;
}

export interface PresetCatalogResponse {
  presets: PresetCatalogEntry[];
  default: string[];
  count: number;
  total: number;
  sample: PresetCatalogSample;
  note: string;
}

export type PresetSampleStatus = 'activity' | 'no_trades' | 'insufficient';

export interface PresetSample {
  status: PresetSampleStatus;
  active_presets: number;
  total_presets: number;
  sessions: number;
  days_requested: number;
  min_sessions: number;
  detail: string;
}

export interface PresetComparisonResponse {
  backtest_run_id?: string | null;
  created_ts: number;
  data_source: string;
  is_synthetic: boolean;
  dataset?: DatasetInfo;
  dataset_id?: string;
  days_requested: number;
  sessions: number;
  overrides: Record<string, unknown>;
  base_config: Record<string, any>;
  default_presets: boolean;
  preset_keys: string[];
  comparison: PresetComparisonRow[];
  sample: PresetSample;
  note: string;
}

export interface AmbiguousBar {
  ts: number;
  direction: 'long' | 'short';
  open: number;
  high: number;
  low: number;
  close: number;
  stop: number;
  target: number;
  gap_stop: boolean;
  gap_target: boolean;
  resolution: 'stop_loss_first' | string;
  mfe_r?: number;
  mae_r?: number;
  open_drawdown?: number;
  trade_id?: string;
  exit_price?: number;
  pnl?: number;
}

export interface TradesResponse {
  items: Trade[];
  total: number;
  limit: number;
  offset: number;
}
