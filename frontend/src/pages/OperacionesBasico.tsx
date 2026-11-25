import React from 'react';
import { Icon } from '../icons';
import { useApp } from '../store';
import { useUIMode } from '../mode';
import { Card, Metric, Pill } from '../components/ui';
import SimpleTradeRow from '../components/SimpleTradeRow';
import { moneySigned, num, pct } from '../utils';

export default function OperacionesBasico() {
  const { snap } = useApp();
  const { setMode } = useUIMode();
  if (!snap) return null;

  const { position, risk, session, recent_trades } = snap;
  const restantes = Math.max(0, risk.max_trades_per_day - risk.trades_today);

  return (
    <div className="basic">
      <div className="basic-head">
        <div>
          <span className="basic-kicker">Modo básico</span>
          <h1 className="page-title">Operaciones</h1>
          <p className="page-sub">Lo que el bot tiene abierto y lo que ha cerrado, sin tecnicismos.</p>
        </div>
        <button className="btn ghost sm" onClick={() => setMode('avanzado')}>
          Ver controles completos
        </button>
      </div>

      <section className={`basic-hero ${position ? 'success' : 'muted'}`}>
        <div className="basic-hero-main">
          <span className={`basic-hero-dot ${position ? 'on' : ''}`} />
          <div>
            <h2>
              {position
                ? `${position.qty} contrato${position.qty === 1 ? '' : 's'} de ${position.direction === 'long' ? 'compra' : 'venta'}`
                : 'Ahora mismo no hay ninguna operación abierta'}
            </h2>
            <p>
              {position
                ? `Entró en ${num(position.entry_price)} y ahora vale ${num(position.current_price)}. ${
                    position.unrealized >= 0 ? 'Va ganando' : 'Va perdiendo'
                  } ${moneySigned(position.unrealized)} (${num(position.r_multiple)} R).`
                : 'El bot solo abre una operación cuando se cumplen todas sus condiciones. Si no, se queda mirando.'}
            </p>
          </div>
        </div>
        <div className="basic-hero-tags">
          <Pill tone={position ? 'success' : 'muted'} dot>
            {position ? 'Operación abierta' : 'Sin exposición'}
          </Pill>
          <Pill tone="info">{snap.mode === 'live' ? 'Dinero real' : 'Simulado'}</Pill>
        </div>
      </section>

      {position && (
        <Card title="Los números de esta operación" actions={<Icon name="trades" size={14} />}>
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
          <div className="basic-note">
            <Icon name="shield" size={13} />
            <span>
              No tienes que hacer nada: el bot cierra sola al tocar el stop, al llegar al objetivo o al terminar la sesión
              ({session.close_time} ET).
            </span>
          </div>
        </Card>
      )}

      <div className="grid cols-3">
        <Card bodyClass="tight">
          <Metric
            label="Operaciones hoy"
            value={`${risk.trades_today} de ${risk.max_trades_per_day}`}
            sub={`Quedan ${restantes} como máximo`}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Resultado de hoy"
            value={moneySigned(risk.daily_pnl)}
            tone={risk.daily_pnl > 0 ? 'pos' : risk.daily_pnl < 0 ? 'neg' : 'neutral'}
            sub={pct(risk.daily_pnl_pct, 2, true)}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Límite de pérdida diaria"
            value={`$${num(risk.daily_loss_limit, 0)}`}
            tone="neutral"
            sub="Si se alcanza, el bot deja de operar ese día"
          />
        </Card>
      </div>

      <Card
        title="Últimas operaciones cerradas"
        actions={<span className="card-sub">{recent_trades.length} recientes</span>}
        noBody
      >
        {recent_trades.length ? (
          <div className="trade-list">
            {recent_trades.slice(0, 8).map((t) => (
              <SimpleTradeRow key={t.id} trade={t} withYear />
            ))}
          </div>
        ) : (
          <div className="basic-empty">
            <Icon name="history" size={20} />
            <strong>Todavía no hay operaciones cerradas</strong>
            <span>Cuando el bot cierre la primera, la verás aquí en una línea.</span>
          </div>
        )}
      </Card>

      <div className="basic-cta">
        <div>
          <strong>¿Necesitas cerrar una posición o parar el bot a mano?</strong>
          <span>Los botones de cierre, cancelación y parada de emergencia están en el modo avanzado.</span>
        </div>
        <button className="btn primary" onClick={() => setMode('avanzado')}>
          <Icon name="config" size={14} /> Abrir controles
        </button>
      </div>
    </div>
  );
}
