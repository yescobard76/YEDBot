import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { Icon } from '../icons';
import { useApp } from '../store';
import { clockET, moneySigned, pct, num } from '../utils';
import { Pill } from './ui';

function FeedBadge({ data }: { data: any }) {
  if (!data) return <span className="feed-badge offline">SIN CONEXIÓN</span>;
  if (!data.connected || data.stale) return <span className="feed-badge offline">{data.stale ? 'DATOS RETRASADOS' : 'SIN CONEXIÓN'}</span>;
  if (data.quality === 'simulated')
    return <span className="feed-badge simulated" title={data.detail}>SIMULADO · NO ES MERCADO REAL</span>;
  if (data.quality === 'historical')
    return <span className="feed-badge historical" title={data.detail}>HISTÓRICO REAL · CSV</span>;
  if (data.quality === 'live') return <span className="feed-badge live" title={data.detail}>DATOS EN VIVO</span>;
  return <span className="feed-badge offline">CALIDAD DESCONOCIDA</span>;
}

export default function TopBar() {
  const { snap, act, refresh, wsState } = useApp();
  const [now, setNow] = useState(new Date());

  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 1000);
    return () => window.clearInterval(id);
  }, []);

  const clock = clockET(now);
  const quotes = snap?.quotes || {};
  const or = snap?.opening_range;
  const risk = snap?.risk;
  const status = snap?.status || 'stopped';
  const running = status === 'running';
  const paused = status === 'paused';
  const live = snap?.mode === 'live';

  const statusText = running ? 'BOT ACTIVO' : paused ? 'BOT PAUSADO' : 'BOT DETENIDO';
  const statusTone = running ? 'green' : paused ? 'amber' : 'red';

  return (
    <header className="topbar">
      <div className="tb-section tb-state">
        <div className="tb-status">
          <span className={`dot ${statusTone} ${running ? 'pulse' : ''}`} />
          <span className="tb-status-text">{statusText}</span>
          <Pill tone={live ? 'danger' : 'info'}>{live ? 'LIVE' : 'Paper Trading'}</Pill>
        </div>
        <div className="tb-controls">
          <button
            className="btn icon ghost"
            title={running ? 'Pausar motor' : paused ? 'Reanudar motor' : 'Iniciar motor'}
            onClick={() =>
              act(() => (running ? api.bot('pause') : paused ? api.bot('resume') : api.bot('start')))
            }
          >
            <Icon name={running ? 'pause' : 'play'} size={14} />
          </button>
          <button className="btn icon ghost" title="Detener motor" onClick={() => act(() => api.bot('stop'))}>
            <Icon name="stop" size={13} />
          </button>
          <button className="btn icon ghost" title="Actualizar estado" onClick={() => refresh()}>
            <Icon name="refresh" size={14} />
          </button>
          <span className={`dot ${wsState === 'open' ? 'green' : wsState === 'connecting' ? 'amber' : 'red'}`} style={{ marginLeft: 2 }} />
          <span className="muted" style={{ fontSize: 9 }}>{wsState === 'open' ? 'WS' : wsState === 'connecting' ? '…' : 'POLL'}</span>
        </div>
      </div>

      <div className="tb-quotes">
        {['MNQ', 'NQ', 'ES'].map((sym) => {
          const q = quotes[sym];
          const change = q?.change ?? 0;
          return (
            <div className="quote-block" key={sym}>
              <span className="quote-symbol">
                {sym} {sym === 'MNQ' && <span style={{ color: '#3f8cff' }}>·</span>}
              </span>
              <span className="quote-price">{q && q.last ? num(q.last, 2) : '—'}</span>
              <span className={`quote-change ${change > 0 ? 'pos' : change < 0 ? 'neg' : 'muted'}`}>
                {q && q.last ? `${change >= 0 ? '+' : ''}${num(change, 2)} (${pct(q.change_pct, 2, true)})` : 'sin datos'}
              </span>
            </div>
          );
        })}
      </div>

      <div className="tb-section tb-or">
        <span className="tb-label">Opening Range</span>
        <div style={{ display: 'flex', gap: 14 }}>
          <div>
            <div className="muted" style={{ fontSize: 9 }}>HIGH</div>
            <div className="tb-value sm">{or ? num(or.high, 2) : '—'}</div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 9 }}>LOW</div>
            <div className="tb-value sm">{or ? num(or.low, 2) : '—'}</div>
          </div>
          <div>
            <div className="muted" style={{ fontSize: 9 }}>MID</div>
            <div className="tb-value sm" style={{ color: '#9cc4ff' }}>{or ? num(or.mid, 2) : '—'}</div>
          </div>
        </div>
        <span className="tb-sub muted">{or ? `${or.width.toFixed(2)} pts · ${or.width_pct.toFixed(2)}%` : '9:00–10:00 ET'}</span>
      </div>

      <div className="tb-section tb-pnl">
        <span className="tb-label">P&L del día</span>
        <span className={`tb-value ${(risk?.daily_pnl || 0) > 0 ? 'pos' : (risk?.daily_pnl || 0) < 0 ? 'neg' : ''}`}>
          {moneySigned(risk?.daily_pnl || 0)}
        </span>
        <span className="tb-sub muted">Acumulado {moneySigned(risk?.cum_pnl || 0)}</span>
      </div>

      <div className="tb-section tb-dd">
        <span className="tb-label">Drawdown máx.</span>
        <span className="tb-value sm neg">{pct(risk?.max_drawdown_pct || 0, 2)}</span>
        <span className="tb-sub muted">Riesgo abierto {pct(risk?.risk_open_pct || 0, 2)}</span>
      </div>

      <div className="tb-section tb-clock" style={{ marginLeft: 'auto' }}>
        <span className="tb-label">Hora Nueva York</span>
        <span className="tb-clock-time">{clock.time}</span>
        <span className="tb-clock-date">{clock.date} ET</span>
      </div>

      <div className="tb-section tb-feed" style={{ borderLeft: '1px solid var(--line-soft)' }}>
        <FeedBadge data={snap?.data} />
        <span className="tb-sub muted">
          {snap?.data?.last_bar_ts ? `Última vela ${clockET(new Date(snap.data.last_bar_ts * 1000)).time}` : 'Esperando datos'}
        </span>
        <span className="tb-sub muted">{snap?.session?.date ? `Sesión ${snap.session.date}` : 'Sin sesión'}</span>
      </div>
    </header>
  );
}
