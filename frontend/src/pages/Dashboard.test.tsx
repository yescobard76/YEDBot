import { render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { Snapshot } from '../types';
import Dashboard from './Dashboard';

const mocks = vi.hoisted(() => ({
  forwardValidation: vi.fn(),
  state: { snap: null as Snapshot | null },
}));

vi.mock('../api', () => ({
  api: { forwardValidation: mocks.forwardValidation },
}));

vi.mock('../store', () => ({
  useApp: () => ({ snap: mocks.state.snap, chartHistory: [] }),
}));

vi.mock('../components/CandleChart', () => ({ default: () => null }));
vi.mock('../components/ValidationCard', () => ({ default: () => null }));
vi.mock('../components/panels', () => ({
  DaySnapshot: () => null,
  PositionPanel: () => null,
  StrategyPanel: () => null,
}));

function makeSnap(maxContracts: number): Snapshot {
  return {
    quotes: {},
    risk: {
      equity: 25_981.68,
      initial_capital: 25_000,
      daily_pnl: 0,
      daily_pnl_pct: 0,
      trades_today: 0,
      max_trades_per_day: 3,
      risk_per_trade_pct: 1,
      risk_open_amount: 0,
      risk_open_pct: 0,
      max_drawdown_pct: 0.945,
      open_drawdown: 0,
      daily_loss_limit: 750,
      emergency: false,
      blocked_reason: null,
    },
    opening_range: null,
    stats: {
      trades: 6,
      wins: 4,
      losses: 2,
      win_rate: 66.67,
      profit_factor: 3.06,
      expectancy: 163.61,
      net_profit: 981.68,
      avg_r: 1.08,
      total_r: 6.46,
      worst_loss_streak: 1,
      max_drawdown_pct: 0.945,
      equity_curve: [],
    },
    session: {
      date: '2025-01-27',
      trade_window_start: '09:00',
      trade_window_end: '15:30',
      close_time: '15:55',
    },
    assessment: {
      smt: null,
      atr: 100,
      reference_level: null,
      phases: [],
    },
    chart: { bars: [], markers: [] },
    position: null,
    recent_trades: [],
    data: { label: 'CSV histórico real', stale: false, last_bar_ts: null },
    settings: { risk: { max_contracts: maxContracts } },
  } as unknown as Snapshot;
}

describe('Dashboard · configuración y métricas históricas', () => {
  beforeEach(() => {
    mocks.forwardValidation.mockReset();
    mocks.forwardValidation.mockResolvedValue(null);
    mocks.state.snap = makeSnap(7);
  });

  it('rotula el histórico y toma el límite de contratos de la configuración real', () => {
    render(<Dashboard />);

    expect(screen.getByText('Rendimiento histórico')).toBeInTheDocument();
    expect(screen.getByText(/todas las operaciones cerradas/)).toBeInTheDocument();
    expect(screen.getByTestId('contract-limit')).toHaveTextContent('7 contratos máx.');
    expect(screen.queryByText('10 contratos máx.')).not.toBeInTheDocument();
  });
});
