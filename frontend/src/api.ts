import type {
  BacktestResult,
  ForwardValidationReport,
  OHLC,
  PresetCatalogResponse,
  PresetComparisonResponse,
} from './types';

const BASE = '/api';

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    let message = `Error ${res.status}`;
    try {
      const body = await res.json();
      message = body?.detail || message;
    } catch {
      /* respuesta no JSON */
    }
    throw new Error(typeof message === 'string' ? message : JSON.stringify(message));
  }
  return (await res.json()) as T;
}

export const api = {
  status: () => request<any>('/status'),
  forwardValidation: () => request<ForwardValidationReport>('/validation/forward'),
  config: () => request<any>('/config'),
  saveConfig: (patch: any, force = false) =>
    request<any>('/config', { method: 'PUT', body: JSON.stringify({ patch, force }) }),
  resetConfig: () => request<any>('/config/reset', { method: 'POST' }),
  bot: (action: 'start' | 'pause' | 'resume' | 'stop') =>
    request<any>(`/bot/${action}`, { method: 'POST' }),
  closePosition: () => request<any>('/position/close', { method: 'POST' }),
  cancelOrders: () => request<any>('/orders/cancel', { method: 'POST' }),
  emergency: (reason: string, closePositions: boolean) =>
    request<any>('/emergency', {
      method: 'POST',
      body: JSON.stringify({ reason, close_positions: closePositions }),
    }),
  clearEmergency: () => request<any>('/emergency', { method: 'DELETE' }),
  trades: (params: Record<string, string | number>) => {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== '' && v !== undefined && v !== null) qs.set(k, String(v));
    });
    return request<any>(`/trades?${qs.toString()}`);
  },
  events: (level?: string, limit = 200) =>
    request<any>(`/events?level=${encodeURIComponent(level || 'all')}&limit=${limit}`),
  stats: (period?: string) => request<any>(`/stats${period ? `?period=${period}` : ''}`),
  previewResetStats: (deleteBacktests = false, archive = false) => {
    const qs = new URLSearchParams({
      delete_backtests: deleteBacktests ? 'true' : 'false',
      archive: archive ? 'true' : 'false',
    });
    return request<any>(`/stats/reset/preview?${qs.toString()}`);
  },
  resetStats: (
    deleteBacktests = false,
    options: { confirmDeleteBacktests?: boolean; archive?: boolean } = {},
  ) =>
    request<any>('/stats/reset', {
      method: 'POST',
      body: JSON.stringify({
        delete_backtests: deleteBacktests,
        confirm_delete_backtests: options.confirmDeleteBacktests ?? false,
        archive: options.archive ?? false,
      }),
    }),
  chartHistory: (limit = 6000) =>
    request<{ bars: OHLC[]; count: number; session: string | null }>(`/chart/history?limit=${limit}`),
  backtest: (payload: { days: number; overrides?: any; compare?: boolean; start_date?: string; idempotency_key?: string }) =>
    request<any>('/backtest/run', { method: 'POST', body: JSON.stringify(payload) }),
  latestBacktest: () => request<{ result: BacktestResult | null }>('/backtest/latest'),
  presetCatalog: () => request<PresetCatalogResponse>('/backtest/presets'),
  presets: (payload: { days: number; presets?: string[]; overrides?: any; start_date?: string; idempotency_key?: string }) =>
    request<PresetComparisonResponse>('/backtest/presets', { method: 'POST', body: JSON.stringify(payload) }),
  validateCsv: (path?: string, seriesMode = 'adjusted', excludeRollSessions = true) =>
    request<any>('/data/validate', {
      method: 'POST',
      body: JSON.stringify({
        path: path || null,
        series_mode: seriesMode,
        exclude_roll_sessions: excludeRollSessions,
      }),
    }),
};

export function wsUrl(): string {
  const proto = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${proto}://${window.location.host}/api/ws`;
}
