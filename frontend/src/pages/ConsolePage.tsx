import React, { useMemo, useState } from 'react';
import { Card, Empty, Pill, StatusRow } from '../components/ui';
import { Icon } from '../icons';
import { useApp } from '../store';
import { dateTimeET, timeET } from '../utils';

type Filter = 'all' | 'alerts' | 'errors';

const CATEGORY_LABEL: Record<string, string> = {
  system: 'Sistema',
  data: 'Datos',
  session: 'Sesión',
  signal: 'Señal',
  risk: 'Riesgo',
  order: 'Órdenes',
  execution: 'Ejecución',
  trade: 'Operación',
  config: 'Configuración',
  engine: 'Motor',
};

export default function ConsolePage() {
  const { snap, events, wsState } = useApp();
  const [filter, setFilter] = useState<Filter>('all');
  const [onlyCategory, setOnlyCategory] = useState('all');

  const filtered = useMemo(() => {
    return events.filter((e) => {
      if (filter === 'alerts' && !['WARNING', 'ERROR'].includes(e.level)) return false;
      if (filter === 'errors' && e.level !== 'ERROR') return false;
      if (onlyCategory !== 'all' && e.category !== onlyCategory) return false;
      return true;
    });
  }, [events, filter, onlyCategory]);

  if (!snap) return null;
  const counts = {
    all: events.length,
    alerts: events.filter((e) => ['WARNING', 'ERROR'].includes(e.level)).length,
    errors: events.filter((e) => e.level === 'ERROR').length,
  };
  const categories = Array.from(new Set(events.map((e) => e.category)));
  const dataConnected = snap.data?.connected && !snap.data?.stale;
  const brokerLabel =
    snap.mode === 'paper'
      ? 'Paper interno (sin broker)'
      : snap.config.broker === 'none'
        ? 'Sin broker configurado'
        : String(snap.config.broker);

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Consola y eventos</h1>
          <p className="page-sub">Trazabilidad en tiempo real del motor, los datos, las órdenes y los errores.</p>
        </div>
        <div className="page-actions">
          <Pill tone={wsState === 'open' ? 'success' : 'warn'} dot>{wsState === 'open' ? 'Stream conectado' : 'Reconectando'}</Pill>
          <Pill tone={snap.status === 'running' ? 'success' : snap.status === 'paused' ? 'warn' : 'danger'} dot>
            Motor {snap.status === 'running' ? 'activo' : snap.status === 'paused' ? 'pausado' : 'detenido'}
          </Pill>
        </div>
      </div>

      <div className="console-layout">
        <Card noBody>
          <div className="chart-toolbar">
            <div className="segmented">
              <button className={`seg-btn ${filter === 'all' ? 'active' : ''}`} onClick={() => setFilter('all')}>Eventos ({counts.all})</button>
              <button className={`seg-btn ${filter === 'alerts' ? 'active' : ''}`} onClick={() => setFilter('alerts')}>Alertas ({counts.alerts})</button>
              <button className={`seg-btn ${filter === 'errors' ? 'active' : ''}`} onClick={() => setFilter('errors')}>Errores ({counts.errors})</button>
            </div>
            <select className="select" style={{ width: 160 }} value={onlyCategory} onChange={(e) => setOnlyCategory(e.target.value)}>
              <option value="all">Todas las categorías</option>
              {categories.map((c) => (
                <option key={c} value={c}>{CATEGORY_LABEL[c] || c}</option>
              ))}
            </select>
          </div>
          <div className="console-feed">
            {filtered.length ? (
              <table className="table">
                <thead>
                  <tr><th>Hora</th><th>Nivel</th><th>Categoría</th><th>Mensaje</th></tr>
                </thead>
                <tbody>
                  {filtered.map((e) => (
                    <tr key={e.id}>
                      <td className="mono" title={dateTimeET(Math.floor(e.ts / 1000))}>{timeET(Math.floor(e.ts / 1000))}</td>
                      <td><span className={`event-level ${e.level}`}>● {e.level}</span></td>
                      <td className="muted">{CATEGORY_LABEL[e.category] || e.category}</td>
                      <td className="event-message" title={e.message} style={{ color: e.level === 'ERROR' ? '#ff9aaa' : undefined }}>{e.message}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty title="Sin eventos para este filtro" text="El motor registra cada conexión, señal y orden en la base de datos." icon="console" />
            )}
          </div>
        </Card>

        <div className="vstack" style={{ gap: 12 }}>
          <Card title={<><Icon name="wifi" size={14} /> Estado del sistema</>} noBody>
            <div className="status-list">
              <StatusRow
                label="Motor de trading"
                status={snap.status === 'running' ? 'Operativo' : snap.status === 'paused' ? 'Pausado' : 'Detenido'}
                tone={snap.status === 'running' ? 'green' : snap.status === 'paused' ? 'amber' : 'red'}
                detail={`Modo ${snap.mode === 'paper' ? 'paper' : 'live'} · instrumento ${snap.instrument}`}
              />
              <StatusRow
                label="Datos de mercado"
                status={dataConnected ? 'Conectado' : snap.data?.stale ? 'Retrasados' : 'Desconectado'}
                tone={dataConnected ? 'green' : 'red'}
                detail={`${snap.data?.label || 'Sin proveedor'} · ${snap.data?.detail || ''}`}
              />
              <StatusRow
                label="Broker / ejecución"
                status={snap.mode === 'paper' ? 'Paper' : 'Live'}
                tone={snap.mode === 'paper' ? 'blue' : 'amber'}
                detail={brokerLabel}
              />
              <StatusRow
                label="Estrategia"
                status={snap.status === 'running' ? 'Activa' : 'En espera'}
                tone={snap.status === 'running' ? 'green' : 'amber'}
                detail={`OR ${snap.session.or_start}–${snap.session.or_end} ET · confirmación ${String(snap.config.confirm_tf)}`}
              />
              <StatusRow
                label="Gestión de riesgo"
                status={snap.risk.emergency ? 'Emergencia' : snap.risk.blocked_reason ? 'Bloqueada' : 'Normal'}
                tone={snap.risk.emergency ? 'red' : snap.risk.blocked_reason ? 'amber' : 'green'}
                detail={snap.risk.emergency ? snap.risk.emergency_reason || '' : `Riesgo ${snap.risk.risk_per_trade_pct}% · ${snap.risk.trades_today}/${snap.risk.max_trades_per_day} operaciones`}
              />
              <StatusRow
                label="Base de datos"
                status="SQLite"
                tone="green"
                detail="Persistencia de operaciones, eventos y estado del motor."
              />
            </div>
          </Card>

          <Card title="Sesión y mercado">
            <div className="kv">
              <div className="kv-row"><span className="kv-label">Sesión</span><span className="kv-value">{snap.session.date || 'Sin iniciar'}</span></div>
              <div className="kv-row"><span className="kv-label">Última vela</span><span className="kv-value mono">{snap.data?.last_bar_ts ? timeET(snap.data.last_bar_ts) : '—'}</span></div>
              <div className="kv-row"><span className="kv-label">Velas cargadas</span><span className="kv-value">{snap.chart.bars.length}</span></div>
              <div className="kv-row"><span className="kv-label">Calidad de datos</span><span className="kv-value">{snap.data?.quality === 'simulated' ? 'Simulada (no real)' : snap.data?.quality === 'live' ? 'Real en vivo' : snap.data?.quality === 'historical' ? 'Histórico real (CSV)' : 'Desconocida'}</span></div>
              <div className="kv-row"><span className="kv-label">Eventos en memoria</span><span className="kv-value">{events.length}</span></div>
            </div>
            {snap.data?.quality === 'simulated' && (
              <div className="banner warn" style={{ marginTop: 10 }}>
                <Icon name="alert" size={14} />
                <div>Los precios mostrados son simulados y no representan el mercado real.</div>
              </div>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
