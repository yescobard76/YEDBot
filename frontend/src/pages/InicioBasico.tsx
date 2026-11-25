import React, { useMemo } from 'react';
import { api } from '../api';
import { Icon } from '../icons';
import { useApp } from '../store';
import { useUIMode } from '../mode';
import { AreaChart, Card, Empty, Metric, Pill } from '../components/ui';
import SimpleTradeRow from '../components/SimpleTradeRow';
import { moneySigned, num, pct } from '../utils';
import type { Snapshot } from '../types';

function estadoActual(
  running: boolean,
  paused: boolean,
  position: Snapshot['position'],
): { titulo: string; texto: string; tono: 'success' | 'danger' | 'warn' | 'muted' } {
  if (position) {
    const lado = position.direction === 'long' ? 'compra' : 'venta';
    const resultado = position.unrealized >= 0 ? 'ganando' : 'perdiendo';
    return {
      titulo: `Posición abierta: ${position.qty} contrato${position.qty === 1 ? '' : 's'} de ${lado}`,
      texto: `Ahora mismo está ${resultado} ${moneySigned(position.unrealized)}. El bot cerrará solo cuando toque el stop (${num(position.stop)}) o el objetivo (${num(position.target)}).`,
      tono: 'success',
    };
  }
  if (running) {
    return {
      titulo: 'El bot está vigilando el mercado',
      texto: 'Busca una ruptura del rango de la primera hora con confirmación. Si no se cumplen todas las condiciones, no hace nada.',
      tono: 'success',
    };
  }
  if (paused) {
    return {
      titulo: 'El bot está en pausa',
      texto: 'No abrirá operaciones nuevas hasta que lo reanudes. Una posición abierta se seguiría gestionando.',
      tono: 'warn',
    };
  }
  return {
    titulo: 'El bot está detenido',
    texto: 'Pulsa «Empezar» para que empiece a buscar operaciones en modo simulado (paper). No se envía dinero real.',
    tono: 'muted',
  };
}

export default function InicioBasico() {
  const { snap, act } = useApp();
  const { setMode } = useUIMode();

  const equityPoints = useMemo(
    () => (snap?.stats.equity_curve || []).map((p) => ({ ts: p.ts, value: p.equity })),
    [snap?.stats.equity_curve],
  );

  if (!snap) return null;

  const { risk, stats, position, session, data } = snap;
  const running = snap.status === 'running';
  const paused = snap.status === 'paused';
  const estado = estadoActual(running, paused, position);
  const enPositivo = risk.daily_pnl > 0;
  const enNegativo = risk.daily_pnl < 0;
  const limiteContratos = snap.settings?.risk?.max_contracts;

  return (
    <div className="basic">
      <div className="basic-head">
        <div>
          <span className="basic-kicker">Modo básico</span>
          <h1 className="page-title">Tu bot, en simple</h1>
          <p className="page-sub">
            Sesión {session.date || 'sin iniciar'} · {data?.label || 'sin datos'} · modo simulado
          </p>
        </div>
        <div className="basic-head-actions">
          {running ? (
            <button className="btn" onClick={() => act(() => api.bot('pause'), 'Bot pausado')}>
              <Icon name="pause" size={14} /> Pausar
            </button>
          ) : (
            <button
              className="btn primary"
              onClick={() => act(() => api.bot(paused ? 'resume' : 'start'), paused ? 'Bot reanudado' : 'Bot iniciado')}
            >
              <Icon name="play" size={14} /> {paused ? 'Reanudar' : 'Empezar'}
            </button>
          )}
          <button className="btn danger" onClick={() => act(() => api.bot('stop'), 'Bot detenido')} disabled={!running && !paused}>
            <Icon name="stop" size={13} /> Detener
          </button>
        </div>
      </div>

      <section className={`basic-hero ${estado.tono}`}>
        <div className="basic-hero-main">
          <span className={`basic-hero-dot ${running ? 'on' : ''}`} />
          <div>
            <h2>{estado.titulo}</h2>
            <p>{estado.texto}</p>
          </div>
        </div>
        <div className="basic-hero-tags">
          <Pill tone={snap.mode === 'live' ? 'danger' : 'info'}>{snap.mode === 'live' ? 'DINERO REAL' : 'Simulado (paper)'}</Pill>
          <Pill tone={running ? 'success' : paused ? 'warn' : 'muted'} dot>
            {running ? 'En marcha' : paused ? 'Pausado' : 'Detenido'}
          </Pill>
          {risk.emergency && <Pill tone="danger">Emergencia activa</Pill>}
        </div>
      </section>

      <div className="grid cols-3 basic-metrics">
        <Card bodyClass="tight">
          <Metric label="Tu dinero" value={`$${num(risk.equity)}`} size="lg" sub={`Empezaste con $${num(risk.initial_capital, 0)}`} />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Resultado de hoy"
            value={moneySigned(risk.daily_pnl)}
            size="lg"
            tone={enPositivo ? 'pos' : enNegativo ? 'neg' : 'neutral'}
            sub={`${pct(risk.daily_pnl_pct, 2, true)} · ${risk.trades_today} de ${risk.max_trades_per_day} operaciones`}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Resultado total"
            value={moneySigned(stats.net_profit)}
            size="lg"
            tone={stats.net_profit > 0 ? 'pos' : stats.net_profit < 0 ? 'neg' : 'neutral'}
            sub={`${stats.trades} operaciones · ${pct(stats.win_rate, 1)} ganadoras`}
          />
        </Card>
      </div>

      {position && (
        <Card
          className="basic-position"
          title="Lo que tiene abierto ahora"
          actions={<Pill tone={position.direction === 'long' ? 'success' : 'danger'} dot>{position.direction === 'long' ? 'Compra' : 'Venta'}</Pill>}
        >
          <div className="basic-position-grid">
            <div>
              <span className="metric-label">Cantidad</span>
              <strong>{position.qty} contrato{position.qty === 1 ? '' : 's'}</strong>
            </div>
            <div>
              <span className="metric-label">Precio de entrada</span>
              <strong className="mono">{num(position.entry_price)}</strong>
            </div>
            <div>
              <span className="metric-label">Precio ahora</span>
              <strong className="mono">{num(position.current_price)}</strong>
            </div>
            <div>
              <span className="metric-label">Ganancia / pérdida</span>
              <strong className={position.unrealized >= 0 ? 'pos' : 'neg'}>{moneySigned(position.unrealized)}</strong>
            </div>
            <div>
              <span className="metric-label">Si baja hasta</span>
              <strong className="mono neg">{num(position.stop)}</strong>
            </div>
            <div>
              <span className="metric-label">Objetivo</span>
              <strong className="mono pos">{num(position.target)}</strong>
            </div>
          </div>
        </Card>
      )}

      <div className="basic-columns">
        <Card
          title="Tus últimas operaciones"
          actions={<button className="btn ghost sm" onClick={() => setMode('avanzado')}>Ver detalle</button>}
          noBody
        >
          {snap.recent_trades.length ? (
            <div className="trade-list">
              {snap.recent_trades.slice(0, 6).map((t) => (
                <SimpleTradeRow key={t.id} trade={t} />
              ))}
            </div>
          ) : (
            <Empty title="Todavía no hay operaciones" text="Cuando el bot cierre la primera, aparecerá aquí." icon="history" />
          )}
        </Card>

        <Card title="Cómo va la cuenta" actions={<span className="card-sub">{stats.trades} operaciones cerradas</span>}>
          {equityPoints.length > 1 ? (
            <AreaChart points={equityPoints} height={120} formatValue={(v) => `$${num(v, 0)}`} />
          ) : (
            <Empty title="Aún sin curva" text="Se dibuja al cerrar operaciones." />
          )}
          <div className="basic-note">
            <Icon name="shield" size={13} />
            <span>
              Cada operación arriesga el <strong>{num(snap.settings?.risk?.risk_per_trade_pct ?? 0, 1)}%</strong> de la cuenta y
              nunca hay más de una posición abierta. Límite de {limiteContratos ?? '—'} contratos.
            </span>
          </div>
        </Card>
      </div>

      <Card className="basic-explain" title="¿Qué hace este bot?" actions={<span className="card-sub">en 3 pasos</span>}>
        <ol className="basic-steps">
          <li>
            <span className="basic-step">1</span>
            <div>
              <strong>Mide la primera hora</strong>
              <p>Guarda el máximo y el mínimo de 09:00 a 10:00 de Nueva York. Ese es su rango de referencia.</p>
            </div>
          </li>
          <li>
            <span className="basic-step">2</span>
            <div>
              <strong>Espera una ruptura con confirmación</strong>
              <p>No entra con la primera chispa: exige cierre fuera del rango y que el patrón SMT acompañe.</p>
            </div>
          </li>
          <li>
            <span className="basic-step">3</span>
            <div>
              <strong>Gestiona el riesgo por ti</strong>
              <p>Coloca stop y objetivo (3 veces el riesgo) y cierra la posición al final de la sesión.</p>
            </div>
          </li>
        </ol>
        <div className="basic-cta">
          <div>
            <strong>¿Quieres ver el gráfico, las fases y la configuración?</strong>
            <span>Eso está en el modo avanzado. Puedes volver aquí cuando quieras.</span>
          </div>
          <button className="btn primary" onClick={() => setMode('avanzado')}>
            <Icon name="chart" size={14} /> Ver modo avanzado
          </button>
        </div>
      </Card>

      <p className="basic-foot">
        Modo simulado: el bot no envía órdenes a ningún broker. Los resultados pasados no garantizan resultados futuros.
      </p>
    </div>
  );
}
