import React from 'react';
import type {
  ForwardValidationCandidate,
  ForwardValidationReport,
  ForwardValidationStatus,
} from '../types';
import { Card, Empty, Pill } from './ui';
import { contractLimitText, money, moneySigned, num } from '../utils';

const STATUS_META: Record<
  ForwardValidationStatus,
  { label: string; tone: 'muted' | 'success' | 'danger' | 'warn' }
> = {
  reference: { label: 'Referencia', tone: 'muted' },
  validated: { label: 'Validado', tone: 'success' },
  rejected: { label: 'Rechazado', tone: 'danger' },
  insufficient_data: { label: 'Sin validar', tone: 'warn' },
};

const FORWARD_STATUS_META: Record<
  string,
  { label: string; tone: 'muted' | 'success' | 'danger' | 'warn' }
> = {
  validated: { label: 'Forward disponible', tone: 'success' },
  rejected: { label: 'Forward rechazado', tone: 'danger' },
  insufficient_data: { label: 'Forward insuficiente', tone: 'warn' },
};

function statusMeta(candidate: ForwardValidationCandidate) {
  return STATUS_META[candidate.forward_status] ?? { label: 'Sin validar', tone: 'warn' as const };
}

function MetaNote({
  label,
  testId,
  children,
}: {
  label: string;
  testId?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="muted" data-testid={testId} style={{ fontSize: 10.5, marginBottom: 8 }}>
      <strong>{label}:</strong> {children}
    </div>
  );
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
  const forwardMeta = FORWARD_STATUS_META[forward.status] ?? {
    label: 'Forward sin estado',
    tone: 'warn' as const,
  };
  const historicalReference = report.historical_reference;
  const contractLimit = report.manual_8765?.contract_limit;
  const contractLabel = contractLimitText(contractLimit?.value);
  return (
    <Card
      title="Validación fuera de muestra"
      sub="Métricas históricas in-sample (contexto) frente a forward independiente"
      actions={<Pill tone={forwardMeta.tone}>{forwardMeta.label}</Pill>}
      className="validation-card"
    >
      <div className="validation-meta">
        <Pill tone="muted">Holdout {holdout.id} sellado</Pill>
        <span className="muted">
          {forward.available_sessions} sesiones forward · último dato {forward.dataset_last_session}
        </span>
      </div>

      {contractLimit && (
        <MetaNote label="Límite histórico" testId="historical-contract-limit">
          {contractLabel ?? 'no registrado'} ·{' '}
          {contractLimit.status === 'configured'
            ? contractLimit.source
            : `${contractLimit.status}: ${contractLimit.source}`}
        </MetaNote>
      )}

      {historicalReference && (
        <MetaNote label="Referencia histórica">
          {historicalReference.label} · {historicalReference.dev_metrics.ops} ops ·{' '}
          {moneySigned(historicalReference.dev_metrics.net_usd)} · PF{' '}
          {num(historicalReference.dev_metrics.profit_factor)} · DD{' '}
          {money(historicalReference.dev_metrics.max_drawdown_usd)}
        </MetaNote>
      )}

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
              <th className="right">Ops hist.</th>
              <th className="right">Neto hist.</th>
              <th className="right">PF hist.</th>
              <th className="right">DD hist.</th>
              <th className="right">R medio hist.</th>
              <th>Forward</th>
              <th>Estado</th>
            </tr>
          </thead>
          <tbody>
            {report.candidates.map((candidate) => {
              const status = statusMeta(candidate);
              return (
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
                    <Pill tone={status.tone}>{status.label}</Pill>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="validation-note">
        <strong>Histórico in-sample:</strong> {report.development.window}, {report.development.sessions} sesiones,{' '}
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
