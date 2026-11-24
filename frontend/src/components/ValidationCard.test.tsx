import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { ForwardValidationReport } from '../types';
import ValidationCard from './ValidationCard';

function report(): ForwardValidationReport {
      const dev = {
    ops: 72,
    net_usd: 2022.94,
    profit_factor: 1.22,
    max_drawdown_usd: 2891.66,
    max_drawdown_pct: 9.79,
    expectancy_usd: 28.1,
    expectancy_r: 0.18,
    total_r: 13.19,
  };
  return {
    schema: 'forward-validation-v1',
    generated_at: '2026-11-24T00:00:00+00:00',
    status: 'insufficient_data',
    decision: {
      kind: 'keep_current',
      label: 'Mantener manual 8765',
      adopted_candidate: null,
      live_config_updated: false,
      current_profile: 'data/config.json',
      current_profile_sha256: 'a'.repeat(64),
      summary: 'No hay muestra forward independiente.',
      reasons: [],
    },
    development: {
      window: 'W1-W6',
      start: '2025-01-10',
      end: '2026-06-30',
      sessions: 362,
      status: 'in_sample',
      role: 'context_only_not_validation',
      source: 'test',
      note: 'contexto',
    },
    forward: {
      status: 'insufficient_data',
      evaluated: false,
      attempts: 0,
      available_sessions: 0,
      available_bars: 0,
      dataset_last_session: '2026-06-30',
      dataset_last_bar_et: '2026-06-30T15:59:00-04:00',
      summary: '0 sesiones forward disponibles.',
      reasons: [],
      candidate_forward_protocol: null,
    },
    holdout: {
      id: 'H1',
      start: '2026-07-01',
      end: '2026-10-30',
      sessions: 85,
      status: 'sealed_not_executed',
      executed: false,
      used_for_decision: false,
      lock_path: 'docs/protocolo_backtest.lock.json',
      lock_sha256: 'b'.repeat(64),
    },
    candidates: [
      {
        id: 'baseline_manual',
        label: 'Manual 8765 · 10 contratos · SL 300 · 210/24',
        short_label: 'Manual 8765',
        role: 'baseline',
        profile: 'data/config.json',
        profile_sha256: 'c'.repeat(64),
        implementation: 'server.backtest',
        dev_metrics: dev,
        forward_metrics: null,
        forward_status: 'reference',
        forward_note: 'base',
      },
      {
        id: 'p2',
        label: 'P2 · 10 contratos · SL 200 · 210/24',
        short_label: 'P2',
        role: 'candidate',
        profile: 'profiles/p2_freq/config.json',
        profile_sha256: 'd'.repeat(64),
        implementation: 'server.backtest',
        dev_metrics: { ...dev, net_usd: 2471.78, profit_factor: 1.39 },
        forward_metrics: null,
        forward_status: 'insufficient_data',
        forward_note: 'sin forward',
      },
      {
        id: 'p2_be_1r',
        label: 'P2 + break-even 1R',
        short_label: 'P2 + BE 1R',
        role: 'candidate',
        profile: null,
        profile_sha256: null,
        implementation: 'experimental',
        production_available: false,
        dev_metrics: { ...dev, net_usd: 2036.52, profit_factor: 1.48 },
        forward_metrics: null,
        forward_status: 'insufficient_data',
        forward_note: 'sin forward',
      },
    ],
    integrity: {},
  };
}

describe('ValidationCard', () => {
  it('muestra desarrollo, forward insuficiente y la decisión de mantener', () => {
    render(<ValidationCard report={report()} />);

    expect(screen.getByText('Validación fuera de muestra')).toBeTruthy();
    expect(screen.getByText('Forward insuficiente')).toBeTruthy();
    expect(screen.getByText(/Mantener manual 8765/)).toBeTruthy();
    expect(screen.getByText(/No se modificó la configuración viva/)).toBeTruthy();
    expect(screen.getByText('Manual 8765')).toBeTruthy();
    expect(screen.getByText('P2')).toBeTruthy();
    expect(screen.getByText('P2 + BE 1R')).toBeTruthy();
    expect(screen.getAllByText('Sin validar')).toHaveLength(2);
    expect(screen.getByText('Referencia')).toBeTruthy();
    expect(screen.getByText(/0 sesiones forward · último dato/)).toBeTruthy();
    expect(screen.getByText(/No se ejecutó ningún backtest de validación/)).toBeTruthy();
    expect(screen.queryByText('Validado')).toBeNull();
  });

  it('no oculta el error si el informe no está disponible', () => {
    render(<ValidationCard report={null} error="HTTP 503" />);
    expect(screen.getByText('No se pudo cargar el informe')).toBeTruthy();
    expect(screen.getByText('HTTP 503')).toBeTruthy();
  });
});
