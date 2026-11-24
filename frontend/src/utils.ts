import { OHLC } from './types';

export const ET = 'America/New_York';

const numberFormats = new Map<number, Intl.NumberFormat>();

function numberFormat(digits: number): Intl.NumberFormat {
  let fmt = numberFormats.get(digits);
  if (!fmt) {
    fmt = new Intl.NumberFormat('en-US', {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    });
    numberFormats.set(digits, fmt);
  }
  return fmt;
}

const TIME_FMT = new Intl.DateTimeFormat('es-ES', {
  timeZone: ET,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const TIME_FMT_SHORT = new Intl.DateTimeFormat('es-ES', {
  timeZone: ET,
  hour: '2-digit',
  minute: '2-digit',
  hour12: false,
});

const DATE_FMT = new Intl.DateTimeFormat('es-ES', {
  timeZone: ET,
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
});

const FULL_DATE_TIME_FMT = new Intl.DateTimeFormat('en-CA', {
  timeZone: ET,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hourCycle: 'h23',
});

const CLOCK_TIME_FMT = new Intl.DateTimeFormat('es-ES', {
  timeZone: ET,
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
});

const CLOCK_DATE_FMT = new Intl.DateTimeFormat('es-ES', {
  timeZone: ET,
  weekday: 'short',
  day: '2-digit',
  month: 'short',
});

export function money(value: number | null | undefined, digits = 2, signed = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const formatted = numberFormat(digits).format(Math.abs(value));
  const sign = value < 0 ? '-' : signed && value > 0 ? '+' : '';
  return `${sign}$${formatted}`;
}

export function moneySigned(value: number): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${value >= 0 ? '+' : '-'}$${numberFormat(2).format(Math.abs(value))}`;
}

export function num(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return numberFormat(digits).format(value);
}

export function pct(value: number | null | undefined, digits = 2, signed = false): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  return `${signed && value > 0 ? '+' : ''}${num(value, digits)}%`;
}

export function timeET(ts?: number | null, withSeconds = true): string {
  if (!ts) return '—';
  return (withSeconds ? TIME_FMT : TIME_FMT_SHORT).format(new Date(ts * 1000));
}

export function dateET(ts?: number | null): string {
  if (!ts) return '—';
  return DATE_FMT.format(new Date(ts * 1000));
}

export function dateTimeET(ts?: number | null): string {
  if (!ts) return '—';
  const parts = FULL_DATE_TIME_FMT.formatToParts(new Date(ts * 1000));
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value || '';
  return `${part('year')}-${part('month')}-${part('day')} ${part('hour')}:${part('minute')}:${part('second')} ET`;
}

export function elapsed(seconds: number): string {
  if (!seconds || seconds < 0) return '—';
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  const clock = [h, m, s].map((x) => String(x).padStart(2, '0')).join(':');
  return d > 0 ? `${d}d ${clock}` : clock;
}

export function clockET(now: Date): { time: string; date: string } {
  return {
    time: CLOCK_TIME_FMT.format(now),
    date: CLOCK_DATE_FMT.format(now),
  };
}

export function duration(seconds: number): string {
  if (!seconds || seconds < 0) return '—';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return [h, m, s].map((x) => String(x).padStart(2, '0')).join(':');
}

export function mergeBars(...groups: OHLC[][]): OHLC[] {
  const byTime = new Map<number, OHLC>();
  for (const group of groups) {
    for (const bar of group) byTime.set(bar.t, bar);
  }
  return Array.from(byTime.values()).sort((a, b) => a.t - b.t);
}

export function aggregate(bars: OHLC[], minutes: number): OHLC[] {
  if (!bars.length || minutes <= 1) return bars;
  const span = minutes * 60;
  const out: OHLC[] = [];
  let current: OHLC | null = null;
  let currentKey = -1;
  for (const bar of bars) {
    const key = Math.floor(bar.t / span) * span;
    if (!current || key !== currentKey) {
      if (current) out.push(current);
      currentKey = key;
      current = { t: key, o: bar.o, h: bar.h, l: bar.l, c: bar.c, v: bar.v };
    } else {
      current.h = Math.max(current.h, bar.h);
      current.l = Math.min(current.l, bar.l);
      current.c = bar.c;
      current.v += bar.v;
    }
  }
  if (current) out.push(current);
  return out;
}

export function vwap(bars: OHLC[]): Array<{ t: number; value: number }> {
  let pv = 0;
  let vol = 0;
  return bars.map((b) => {
    const typical = (b.h + b.l + b.c) / 3;
    pv += typical * Math.max(b.v, 1);
    vol += Math.max(b.v, 1);
    return { t: b.t, value: pv / vol };
  });
}

export function atr(bars: OHLC[], period = 14): Array<{ t: number; value: number }> {
  const out: Array<{ t: number; value: number }> = [];
  const trs: number[] = [];
  for (let i = 0; i < bars.length; i++) {
    const prev = i > 0 ? bars[i - 1].c : bars[i].o;
    const tr = Math.max(bars[i].h - bars[i].l, Math.abs(bars[i].h - prev), Math.abs(bars[i].l - prev));
    trs.push(tr);
    if (i >= period - 1) {
      const slice = trs.slice(i - period + 1, i + 1);
      out.push({ t: bars[i].t, value: slice.reduce((a, b) => a + b, 0) / period });
    }
  }
  return out;
}

export function drawdownSeries(points: Array<{ ts: number; equity: number }>): Array<{ ts: number; dd: number }> {
  let peak = -Infinity;
  return points.map((p) => {
    peak = Math.max(peak, p.equity);
    return { ts: p.ts, dd: peak > 0 ? ((p.equity - peak) / peak) * 100 : 0 };
  });
}

export function levelLabel(status: string): string {
  const map: Record<string, string> = {
    pending: 'Pendiente',
    in_progress: 'En proceso',
    confirmed: 'Confirmado',
    rejected: 'Rechazado',
    expired: 'Expirado',
    waiting: 'En espera',
  };
  return map[status] || status;
}

export function exitReasonLabel(reason: string): string {
  const map: Record<string, string> = {
    take_profit: 'Take Profit',
    stop_loss: 'Stop Loss',
    session_close: 'Cierre de sesión',
    manual: 'Cierre manual',
    emergency: 'Emergencia',
  };
  return map[reason] || reason;
}
