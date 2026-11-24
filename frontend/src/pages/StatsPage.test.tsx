import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type {
  BacktestResult,
  DatasetInfo,
  PresetCatalogEntry,
  PresetCatalogResponse,
  PresetComparisonResponse,
  PresetComparisonRow,
  PresetSample,
  Stats,
} from '../types';
import StatsPage from './StatsPage';

const mocks = vi.hoisted(() => ({
  stats: vi.fn(),
  latestBacktest: vi.fn(),
  presetCatalog: vi.fn(),
  presets: vi.fn(),
  snap: {
    stats: null as Stats | null,
    risk: { equity: 25_000 },
  },
}));

vi.mock('../api', () => ({
  api: {
    stats: mocks.stats,
    latestBacktest: mocks.latestBacktest,
    presetCatalog: mocks.presetCatalog,
    presets: mocks.presets,
  },
}));

vi.mock('../store', () => ({
  useApp: () => ({ snap: mocks.snap }),
}));

function makeStats(): Stats {
  return {
    trades: 0,
    wins: 0,
    losses: 0,
    breakeven: 0,
    win_rate: 0,
    profit_factor: null,
    expectancy: 0,
    net_profit: 0,
    gross_profit: 0,
    gross_loss: 0,
    fees: 0,
    avg_win: 0,
    avg_loss: 0,
    avg_trade: 0,
    avg_r: 0,
    total_r: 0,
    avg_win_r: 0,
    avg_loss_r: 0,
    best_trade: 0,
    worst_trade: 0,
    max_drawdown: 0,
    max_drawdown_pct: 0,
    sharpe: null,
    sortino: null,
    best_win_streak: 0,
    worst_loss_streak: 0,
    avg_duration_sec: 0,
    equity_curve: [],
    daily: [],
    monthly: [],
    by_hour: [],
    by_direction: [],
    by_signal: [],
    by_weekday: [],
    distribution: { wins: 0, losses: 0, breakeven: 0 },
  };
}

function makeRow(index: number): PresetComparisonRow {
  return {
    preset: index === 0 ? 'baseline' : `preset_${index}`,
    label: index === 0 ? 'Base actual' : `Preset ${index}`,
    group: index === 0 ? 'base' : 'frecuencia',
    description: `Descripción ${index}`,
    is_synthetic: false,
    trades: index,
    signals: index,
    breakouts: 0,
    retests: 0,
    days_traded: 3,
    win_rate: 50,
    profit_factor: 1.2,
    expectancy: 10,
    net_profit: 100 + index,
    max_drawdown: 50,
    max_drawdown_pct: 0.2,
    avg_r: 0.1,
    total_r: 0.3,
    sharpe: null,
    sortino: null,
    stop_losses: 1,
    take_profits: 1,
    session_closes: 0,
    stop_loss_rate: 50,
    take_profit_rate: 50,
    avg_stop_ticks: 12,
    stop_cap_sessions: 0,
    qty_zero_sessions: 0,
    final_equity: 25_100,
  };
}

function makeSavedBacktest(): BacktestResult {
  const metrics = {
    ...makeStats(),
    trades: 1,
    wins: 1,
    net_profit: 125,
    equity_curve: [{ ts: 1_700_000_000, equity: 25_125 }],
    days_traded: 3,
    winning_days: 1,
    losing_days: 0,
  };
  const result: BacktestResult = {
    id: 'bt-saved',
    created_ts: 1_700_000_000_000,
    label: 'Backtest conservado',
    data_source: 'synthetic',
    data_quality: 'simulated',
    is_synthetic: true,
    dataset: { id: 'dataset-saved', kind: 'synthetic' },
    config: { days: 3, risk: { initial_capital: 25_000 } },
    metrics,
    diagnostics: {},
    trades: [],
    equity: metrics.equity_curve,
    days_detail: [{ date: '2025-01-02', pnl: 125, trades: 1, equity: 25_125 }],
  };
  // La respuesta de /backtest/latest no guarda estos campos derivados.
  delete (result as Partial<BacktestResult>).data_quality;
  delete (result as Partial<BacktestResult>).is_synthetic;
  delete (result as Partial<BacktestResult>).days_detail;
  return result;
}

function makeSample(overrides: Partial<PresetSample> = {}): PresetSample {
  return {
    status: 'activity',
    active_presets: 10,
    total_presets: 11,
    sessions: 3,
    days_requested: 3,
    min_sessions: 3,
    detail: '10 de 11 presets operan en 3 sesiones. Los deltas comparan variantes sobre el mismo dataset.',
    ...overrides,
  };
}

function makeDataset(allSessions: string[], selected: string[]): DatasetInfo {
  return {
    id: 'dataset-real',
    kind: 'csv',
    file_name: 'bars_mnq_nq_es_1m.csv',
    all_sessions: allSessions,
    sessions: {
      count: selected.length,
      available: allSessions.length,
      dates: selected,
    },
    selected_range: {
      first_ts: 1,
      last_ts: 2,
      first_et: `${selected[0]} 09:00`,
      last_et: `${selected[selected.length - 1]} 15:59`,
    },
  };
}

function makeResponse(overrides: Partial<PresetComparisonResponse> = {}): PresetComparisonResponse {
  const rows = Array.from({ length: 11 }, (_, index) => makeRow(index));
  return {
    created_ts: 1,
    data_source: 'csv',
    is_synthetic: false,
    dataset: {
      id: 'dataset-real',
      kind: 'csv',
      file_name: 'bars_mnq_nq_es_1m.csv',
      selected_range: {
        first_ts: 1,
        last_ts: 2,
        first_et: '2026-06-26 09:00',
        last_et: '2026-06-30 15:59',
      },
    },
    dataset_id: 'dataset-real',
    days_requested: 3,
    sessions: 3,
    overrides: {},
    base_config: {},
    default_presets: true,
    preset_keys: rows.map((row) => row.preset),
    comparison: rows,
    sample: makeSample(),
    note: 'Los presets no modifican la configuración activa.',
    ...overrides,
  };
}

function makeCatalog(): PresetCatalogResponse {
  const presets: PresetCatalogEntry[] = [
    {
      key: 'baseline',
      label: 'Base actual',
      group: 'base',
      description: 'Referencia',
      default: true,
      patch: {},
    },
    {
      key: 'rr_2',
      label: 'Objetivo 2.0R',
      group: 'objetivo',
      description: 'TP a dos veces el SL',
      default: true,
      patch: {},
    },
    {
      key: 'sl_cap_600',
      label: 'Tope SL 600 ticks',
      group: 'riesgo',
      description: 'Control de sizing',
      default: false,
      patch: {},
    },
  ];
  return {
    presets,
    default: ['baseline', 'rr_2'],
    count: 2,
    total: 3,
    sample: {
      provider: 'csv',
      kind: 'csv',
      path: 'data/real/bars_mnq_nq_es_1m.csv',
      file_name: 'bars_mnq_nq_es_1m.csv',
      series_mode: 'raw',
      exclude_roll_sessions: true,
    },
    note: 'Nota de catálogo servida por el backend.',
  };
}

const SEARCH_SESSIONS = [
  '2025-12-10',
  '2025-12-11',
  '2025-12-12',
  '2025-12-15',
  '2025-12-16',
  '2025-12-17',
  '2025-12-18',
  '2025-12-19',
  '2025-12-22',
];

function makeNoTradesResponse(): PresetComparisonResponse {
  const rows = Array.from({ length: 11 }, (_, index) => ({
    ...makeRow(index),
    trades: 0,
    signals: 0,
  }));
  return makeResponse({
    comparison: rows,
    dataset: makeDataset(SEARCH_SESSIONS, SEARCH_SESSIONS.slice(-3)),
    sample: makeSample({
      status: 'no_trades',
      active_presets: 0,
      detail: 'Ninguno de los 11 presets operó en 3 sesiones.',
    }),
  });
}

const HEADERS = [
  'Preset',
  'Ops.',
  'Señales',
  'WR',
  'PF',
  'Expectativa',
  'Neto',
  'DD',
  'SL',
  'ST ticks',
  'Caps',
  'Qty0',
];

async function runComparison() {
  fireEvent.click(screen.getByRole('button', { name: /Comparar presets/i }));
  await screen.findByRole('table');
}

describe('StatsPage · comparación de presets', () => {
  beforeEach(() => {
    mocks.stats.mockReset();
    mocks.latestBacktest.mockReset();
    mocks.presetCatalog.mockReset();
    mocks.presets.mockReset();
    mocks.snap.stats = makeStats();
    mocks.stats.mockResolvedValue(mocks.snap.stats);
    mocks.latestBacktest.mockResolvedValue({ result: null });
    mocks.presetCatalog.mockResolvedValue(makeCatalog());
  });

  it('carga el último backtest guardado al abrirse', async () => {
    mocks.latestBacktest.mockResolvedValue({ result: makeSavedBacktest() });

    render(<StatsPage />);

    expect(await screen.findByText(/Último backtest guardado/i)).toBeInTheDocument();
    expect(screen.getByText(/Backtest conservado/)).toBeInTheDocument();
    expect(document.querySelector('[data-loaded-backtest="true"]')).toBeInTheDocument();
    expect(await screen.findByDisplayValue('3')).toBeInTheDocument();
    expect(screen.queryByText('Sin backtest ejecutado')).not.toBeInTheDocument();
    expect(mocks.latestBacktest).toHaveBeenCalledTimes(1);
  });

  it('muestra las 12 columnas, el aviso, la carga y las 3 sesiones', async () => {
    let resolveRequest!: (value: PresetComparisonResponse) => void;
    mocks.presets.mockReturnValue(
      new Promise<PresetComparisonResponse>((resolve) => {
        resolveRequest = resolve;
      }),
    );

    render(<StatsPage />);

    expect(screen.getByText(/La configuración activa no cambia/i)).toBeInTheDocument();

    const sessions = screen.getAllByRole('spinbutton');
    expect(sessions).toHaveLength(2);
    fireEvent.change(sessions[1], { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: /Comparar presets/i }));

    expect(await screen.findByText('Comparando…')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Comparando…' })).toBeDisabled();

    resolveRequest(makeResponse());

    await screen.findByRole('table');
    const headers = screen.getAllByRole('columnheader').map((header) => header.textContent?.trim());
    expect(headers).toEqual(HEADERS);
    expect(mocks.presets).toHaveBeenCalledWith({ days: 3, start_date: undefined });
    expect(screen.getByText(/Muestra con actividad/i)).toBeInTheDocument();
    expect(screen.getByText(/10 de 11 presets operan/i)).toBeInTheDocument();
    expect(screen.queryByText(/Resultado obsoleto/i)).not.toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Buscar ventana con actividad/i }),
    ).not.toBeInTheDocument();
  });

  it('busca otra ventana de 3 sesiones solo al pulsar y se detiene en la primera con actividad', async () => {
    mocks.presets
      .mockResolvedValueOnce(makeNoTradesResponse())
      .mockResolvedValueOnce(
        makeResponse({ sample: makeSample({ status: 'no_trades', active_presets: 0 }) }),
      )
      .mockResolvedValueOnce(
        makeResponse({ sample: makeSample({ status: 'no_trades', active_presets: 0 }) }),
      )
      .mockResolvedValueOnce(
        makeResponse({ sample: makeSample({ status: 'activity', active_presets: 1 }) }),
      )
      .mockResolvedValueOnce(
        makeResponse({
          dataset: makeDataset(SEARCH_SESSIONS, ['2025-12-15', '2025-12-16', '2025-12-17']),
          sample: makeSample({ status: 'activity', active_presets: 1 }),
        }),
      );

    render(<StatsPage />);
    await runComparison();

    expect(mocks.presets).toHaveBeenCalledTimes(1);
    expect(screen.getByText(/La búsqueda no se ejecuta sola/i)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Buscar ventana con actividad/i }));

    expect(
      await screen.findByText(/Ventana con actividad encontrada desde 2025-12-15/),
    ).toBeInTheDocument();
    expect(mocks.presets).toHaveBeenCalledTimes(5);
    expect(mocks.presets).toHaveBeenNthCalledWith(2, {
      days: 3,
      presets: ['baseline'],
      start_date: '2025-12-17',
    });
    expect(mocks.presets).toHaveBeenNthCalledWith(3, {
      days: 3,
      presets: ['baseline'],
      start_date: '2025-12-16',
    });
    expect(mocks.presets).toHaveBeenNthCalledWith(4, {
      days: 3,
      presets: ['baseline'],
      start_date: '2025-12-15',
    });
    expect(mocks.presets).toHaveBeenNthCalledWith(5, { days: 3, start_date: '2025-12-15' });
    const dateInputs = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    expect(dateInputs[1].value).toBe('2025-12-15');
    expect(screen.queryByText(/Resultado obsoleto/i)).not.toBeInTheDocument();
  });

  it('toma del GET el catálogo, el número de presets y la procedencia de la muestra', async () => {
    render(<StatsPage />);

    expect(
      await screen.findByText(/Nota de catálogo servida por el backend/i),
    ).toBeInTheDocument();
    expect(mocks.presetCatalog).toHaveBeenCalledTimes(1);
    expect(screen.getByText('2 presets por defecto')).toBeInTheDocument();
    expect(screen.getByText('3 presets')).toBeInTheDocument();
    expect(screen.getByText(/Base actual · Objetivo 2\.0R/)).toBeInTheDocument();
    expect(
      screen.getByText(/CSV real · bars_mnq_nq_es_1m\.csv · serie raw · rolls excluidos/),
    ).toBeInTheDocument();
    expect(
      screen.getByText('Procedencia de la muestra configurada:', { selector: 'strong' }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/11 presets/)).not.toBeInTheDocument();
  });

  it('muestra el error y permite reintentar', async () => {
    mocks.presets.mockRejectedValueOnce(new Error('No se pudo comparar'));

    render(<StatsPage />);
    fireEvent.click(screen.getByRole('button', { name: /Comparar presets/i }));

    expect(await screen.findByText('No se pudo comparar')).toBeInTheDocument();
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Comparar presets/i })).not.toBeDisabled();
  });

  it('avisa cuando la muestra no tiene operaciones', async () => {
    const rows = Array.from({ length: 11 }, (_, index) => ({
      ...makeRow(index),
      trades: 0,
      signals: 0,
    }));
    mocks.presets.mockResolvedValue(
      makeResponse({
        comparison: rows,
        sample: makeSample({
          status: 'no_trades',
          active_presets: 0,
          detail: 'Ninguno de los 11 presets operó en 3 sesiones. Los ceros no distinguen variantes.',
        }),
      }),
    );

    render(<StatsPage />);
    await runComparison();

    expect(screen.getByText(/Muestra sin operaciones/i)).toBeInTheDocument();
    expect(screen.getByText(/Ninguno de los 11 presets operó/i)).toBeInTheDocument();
    expect(document.querySelector('[data-sample-status="no_trades"]')).toBeInTheDocument();
  });

  it('avisa cuando la muestra es insuficiente', async () => {
    mocks.presets.mockResolvedValue(
      makeResponse({
        sessions: 2,
        sample: makeSample({
          status: 'insufficient',
          sessions: 2,
          active_presets: 0,
          detail: 'Solo se evaluaron 2 de 3 sesiones mínimas. Los deltas no permiten comparar presets.',
        }),
      }),
    );

    render(<StatsPage />);
    await runComparison();

    expect(screen.getByText(/Muestra insuficiente/i)).toBeInTheDocument();
    expect(screen.getByText(/2 de 3 sesiones mínimas/i)).toBeInTheDocument();
    expect(document.querySelector('[data-sample-status="insufficient"]')).toBeInTheDocument();
  });

  it('marca el resultado como obsoleto al cambiar sesiones o fecha y lo limpia al recomparar', async () => {
    mocks.presets.mockResolvedValue(makeResponse());

    render(<StatsPage />);
    await runComparison();

    expect(screen.queryByText(/Resultado obsoleto/i)).not.toBeInTheDocument();

    fireEvent.change(screen.getAllByRole('spinbutton')[1], { target: { value: '5' } });
    expect(screen.getByText(/Resultado obsoleto/i)).toBeInTheDocument();
    expect(document.querySelector('.table-wrap')).toHaveStyle({ opacity: '0.55' });

    fireEvent.click(screen.getByRole('button', { name: /Comparar presets/i }));
    await screen.findByRole('table');

    expect(screen.queryByText(/Resultado obsoleto/i)).not.toBeInTheDocument();
    expect(mocks.presets).toHaveBeenLastCalledWith({ days: 5, start_date: undefined });

    const dates = document.querySelectorAll<HTMLInputElement>('input[type="date"]');
    fireEvent.change(dates[1], { target: { value: '2025-12-24' } });

    expect(screen.getByText(/Resultado obsoleto/i)).toBeInTheDocument();
    expect(document.querySelector('.table-wrap')).toHaveStyle({ opacity: '0.55' });
  });
});
