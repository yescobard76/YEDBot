import React from 'react';
import { Icon } from '../icons';
import { Snapshot } from '../types';
import { dateTimeET, moneySigned, num, pct, levelLabel } from '../utils';
import { Card, Empty, Pill } from './ui';

export function PhaseList({ phases }: { phases: Snapshot['assessment']['phases'] }) {
  return (
    <div className="phases">
      {phases.map((phase) => (
        <div className="phase" key={phase.key}>
          <span className={`phase-icon ${phase.status}`}>
            {phase.status === 'confirmed' ? (
              <Icon name="check" size={11} strokeWidth={3} />
            ) : phase.status === 'rejected' ? (
              <Icon name="close" size={10} strokeWidth={3} />
            ) : phase.status === 'expired' ? (
              <Icon name="clock" size={10} />
            ) : phase.status === 'in_progress' ? (
              <span className="dot blue pulse" style={{ width: 5, height: 5 }} />
            ) : (
              <span style={{ width: 4, height: 4, borderRadius: 9, background: '#46566b', display: 'inline-block' }} />
            )}
          </span>
          <div className="phase-main">
            <div className="phase-top">
              <span className="phase-label">{phase.label}</span>
              <span className="phase-time">{phase.ts ? dateTimeET(phase.ts) : ''}</span>
            </div>
            <div className="phase-detail">{phase.detail}</div>
          </div>
        </div>
      ))}
    </div>
  );
}

export function StrategyPanel({ snap }: { snap: Snapshot }) {
  const a = snap.assessment;
  const reject = a.reject;
  return (
    <Card
      title={
        <>
          <Icon name="shield" size={14} /> Estado de la estrategia
        </>
      }
      actions={<Pill tone={snap.status === 'running' ? 'success' : snap.status === 'paused' ? 'warn' : 'muted'} dot>{snap.status === 'running' ? 'Activa' : snap.status === 'paused' ? 'Pausada' : 'Detenida'}</Pill>}
      noBody
    >
      <PhaseList phases={a.phases} />
      {reject && (
        <div style={{ padding: '10px 12px' }}>
          <div className="banner warn">
            <Icon name="alert" size={14} />
            <div>{reject}</div>
          </div>
        </div>
      )}
      {a.signal && !snap.position && (
        <div style={{ padding: 12, borderTop: '1px solid var(--line-soft)' }}>
          <div className="section-title" style={{ marginTop: 0 }}>Señal vigente</div>
          <div className={`pill ${a.signal.direction === 'long' ? 'success' : 'danger'}`}>
            {a.signal.direction === 'long' ? 'Larga' : 'Corta'} · {a.signal.signal_type}
          </div>
          <div className="kv" style={{ marginTop: 8 }}>
            <div className="kv-row"><span className="kv-label">Entrada</span><span className="kv-value mono">{num(a.signal.entry_price)}</span></div>
            <div className="kv-row"><span className="kv-label">Stop Loss</span><span className="kv-value mono neg">{num(a.signal.stop)}</span></div>
            <div className="kv-row"><span className="kv-label">Take Profit</span><span className="kv-value mono pos">{num(a.signal.target)}</span></div>
          </div>
          <div className="phase-detail" style={{ marginTop: 8 }}>{a.signal.entry_reason}</div>
        </div>
      )}
    </Card>
  );
}

export function PositionPanel({ snap }: { snap: Snapshot }) {
  const pos = snap.position;
  return (
    <Card
      title={
        <>
          <Icon name="trades" size={14} /> Posición actual
        </>
      }
      actions={pos ? <Pill tone={pos.direction === 'long' ? 'success' : 'danger'} dot>{pos.direction === 'long' ? 'Larga' : 'Corta'}</Pill> : <Pill tone="muted">Sin posición</Pill>}
    >
      {!pos ? (
        <Empty title="Sin posición abierta" text="El motor abrirá una operación cuando se confirmen todas las fases." icon="trades" />
      ) : (
        <>
          <div className="hstack" style={{ justifyContent: 'space-between', marginBottom: 8 }}>
            <div>
              <div className="metric-label">Instrumento</div>
              <div style={{ fontSize: 14, fontWeight: 700 }}>{pos.symbol} <span className="muted" style={{ fontWeight: 500 }}>· {pos.qty} contrato{pos.qty > 1 ? 's' : ''}</span></div>
            </div>
            <div className="right">
              <div className="metric-label">P&L no realizado</div>
              <div className={`metric-value sm ${pos.unrealized > 0 ? 'pos' : pos.unrealized < 0 ? 'neg' : ''}`}>{moneySigned(pos.unrealized)}</div>
              <div className="metric-sub" style={{ justifyContent: 'flex-end' }}>{pos.r_multiple >= 0 ? '+' : ''}{num(pos.r_multiple)} R</div>
            </div>
          </div>
          <div className="kv">
            <div className="kv-row"><span className="kv-label">Entrada</span><span className="kv-value mono">{num(pos.entry_price)} · {dateTimeET(pos.entry_ts)}</span></div>
            <div className="kv-row"><span className="kv-label">Precio actual</span><span className="kv-value mono">{num(pos.current_price)}</span></div>
            <div className="kv-row"><span className="kv-label">Stop Loss</span><span className="kv-value mono neg">{num(pos.stop)}</span></div>
            <div className="kv-row"><span className="kv-label">Take Profit</span><span className="kv-value mono pos">{num(pos.target)}</span></div>
            <div className="kv-row"><span className="kv-label">Riesgo monetario</span><span className="kv-value mono">{num(pos.risk_amount)} USD</span></div>
            <div className="kv-row"><span className="kv-label">Tipo de señal</span><span className="kv-value">{pos.signal_type}</span></div>
          </div>
          <div className="phase-detail" style={{ marginTop: 8 }}>{pos.entry_reason}</div>
        </>
      )}
    </Card>
  );
}

export function DaySnapshot({ snap }: { snap: Snapshot }) {
  const s = snap.day_stats;
  return (
    <Card title="Estadísticas del día" actions={<span className="card-sub">{snap.session.date || '—'}</span>}>
      <div className="kv">
        <div className="kv-row"><span className="kv-label">Operaciones</span><span className="kv-value">{s.trades}</span></div>
        <div className="kv-row"><span className="kv-label">Ganadoras</span><span className="kv-value pos">{s.wins}</span></div>
        <div className="kv-row"><span className="kv-label">Win rate</span><span className="kv-value">{pct(s.win_rate, 1)}</span></div>
        <div className="kv-row"><span className="kv-label">Profit Factor</span><span className="kv-value">{s.trades === 0 ? '—' : s.profit_factor === null ? '∞' : num(s.profit_factor)}</span></div>
        <div className="kv-row"><span className="kv-label">Beneficio neto</span><span className={`kv-value ${s.net_profit >= 0 ? 'pos' : 'neg'}`}>{moneySigned(s.net_profit)}</span></div>
        <div className="kv-row"><span className="kv-label">Expectativa</span><span className={`kv-value ${s.expectancy >= 0 ? 'pos' : 'neg'}`}>{moneySigned(s.expectancy)}</span></div>
      </div>
    </Card>
  );
}
