import React from 'react';
import type { ForwardValidationCandidate, ForwardValidationReport } from '../types';
import { Card, Empty, Pill } from './ui';
import { money, moneySigned, num } from '../utils';

function statusLabel(candidate: ForwardValidationCandidate): string {
  if (candidate.forward_status === 'reference') return 'Referencia';
  if (candidate.forward_status === 'validated') return 'Validado';
  if (candidate.forward_status === 'rejected') return 'Rechazado';
  return 'Sin validar';
}

function statusTone(candidate: ForwardValidationCandidate): 'muted' | 'success' | 'danger' | 'warn' {
  if (candidate.forward_status === 'reference') return 'muted';
  if (candidate.forward_status === 'validated') return 'success';
  if (candidate.forward_status === 'rejected') return 'danger';
  return 'warn';
}

function forwardCell(candidate: ForwardValidationCandidate) {
  const forward = candidate.forward_metrics;
  if (!forward) return <span className="muted">—</span>;
  return (
    <span>
      {forward.ops} ops · {moneySigned(forward.net_usd)} · PF {num(forward.profit_factor)}
    </span>
  );
}

export default function ValidationCard({
  report,
  error,
}: {
  report: ForwardValidationReport | null;
  error?: string | null;
}) {
  if (error) {
    return (
      <Card title="Validación fuera de muestra" actions={<Pill tone="danger">Error</Pill>}>
        <Empty
          title="No se pudo cargar el informe"
          text={error}
          icon="alert"
        />
      </Card>
    );
  }
  if (!report) {
    return (
      <Card title="Validación fuera de muestra">
        <Empty
          title="Cargando informe…"
          text="Leyendo la decisión y las métricas de desarrollo/forward."
          icon="shield"
        />
      </Card>
    );
  }

  const decision = report.decision;
  const forward = report.forward;
  const holdout = report.holdout;
  const insufficient = forward.status !== 'validated';
  return (
    <Card
      title="Validación fuera de muestra"
      sub="Desarrollo (in-sample) frente a forward independiente"
      actions={
        <Pill tone={insufficient ? 'warn' : 'success'}>
          {insufficient ? 'Forward insuficiente' : 'Forward disponible'}
        </Pill>
      }
      className="validation-card"
    >
      <div className="validation-meta">
        <Pill tone="muted">Holdout {holdout.id} sellado</Pill>
        <span className="muted">
          {forward.available_sessions} sesiones forward · último dato {forward.dataset_last_session}
        </span>
      </div>

      <div className={`validation-banner ${decision.kind === 'keep_current' ? 'keep' : 'adopt'}`}>
        <strong>Decisión: {decision.label}.</strong>{' '}
        {decision.kind === 'keep_current'
          ? 'No se modificó la configuración viva.'
          : 'La configuración viva fue actualizada al candidato validado.'}{' '}
        {decision.summary}
      </div>

      <div className="table-wrap">
        <table className="table validation-table">
          <thead>
            <tr>
              <th>Candidato</th>
              <th className="right">Ops dev</th>
              <th className="right">Neto dev</th>
              <th className="right">PF dev</th>
              <th className="right">DD dev</th>
              <th className="right">R medio dev</th>
              <th>Forward</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {report.candidates.map((candidate) => (
              <tr key={candidate.id}>
                <td>
                  <div className="strong">{candidate.short_label || candidate.label}</div>
                  <div className="muted" style={{ fontSize: 9.5, marginTop: 2 }}>
                    {candidate.role === 'baseline' ? 'Línea base' : 'Candidato'} ·{' '}
                    {candidate.production_available === false ? 'experimental' : 'backtest'}
                  </div>
                </td>
                <td className="right mono">{candidate.dev_metrics.ops}</td>
                <td className={`right mono ${candidate.dev_metrics.net_usd >= 0 ? 'pos' : 'neg'}`}>
                  {moneySigned(candidate.dev_metrics.net_usd)}
                </td>
                <td className="right mono">{num(candidate.dev_metrics.profit_factor)}</td>
                <td className="right mono">{money(candidate.dev_metrics.max_drawdown_usd)}</td>
                <td className="right mono">{num(candidate.dev_metrics.expectancy_r)}</td>
                <td>{forwardCell(candidate)}</td>
                <td>
                  <Pill tone={statusTone(candidate)}>{statusLabel(candidate)}</Pill>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="validation-note">
        <strong>Desarrollo:</strong> {report.development.window}, {report.development.sessions} sesiones,{' '}
        {report.development.status === 'in_sample' ? 'in-sample' : report.development.status}.{' '}
        {forward.summary}{' '}
        {forward.attempts === 0 && 'No se ejecutó ningún backtest de validación.'}
      </div>
      <div className="validation-foot">
        <span>
          Holdout: {holdout.start} → {holdout.end} · hash{' '}
          <code>{holdout.lock_sha256.slice(0, 12)}…</code>
        </span>
        <span>Candidato forward: {forward.candidate_forward_protocol ? 'sí' : 'ninguno registrado'}</span>
      </div>
    </Card>
  );
}
