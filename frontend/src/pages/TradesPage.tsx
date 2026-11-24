import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { Card, Empty, Gauge, Metric, Modal, Pill } from '../components/ui';
import { Icon } from '../icons';
import { useApp } from '../store';
import { Trade } from '../types';
import { dateTimeET, duration, elapsed, exitReasonLabel, moneySigned, num, pct } from '../utils';

export default function TradesPage() {
  const { snap, act } = useApp();
  const [tab, setTab] = useState<'positions' | 'orders' | 'closed'>('positions');
  const [closed, setClosed] = useState<Trade[]>([]);
  const [confirm, setConfirm] = useState<null | 'close' | 'cancel'>(null);
  const [emergencyOpen, setEmergencyOpen] = useState(false);
  const [reason, setReason] = useState('Intervención manual del operador');
  const [closeOnEmergency, setCloseOnEmergency] = useState(true);

  useEffect(() => {
    api.trades({ period: 'today', limit: 100 })
      .then((res) => setClosed(res.items || []))
      .catch(() => setClosed([]));
  }, [snap?.recent_trades.length, snap?.position?.id]);

  if (!snap) return null;
  const pos = snap.position;
  const orders = snap.orders;
  const risk = snap.risk;
  const running = snap.status === 'running';
  const curve = snap.stats.equity_curve || [];
  const firstEquityTs = curve[0]?.ts;
  const lastEquityTs = curve[curve.length - 1]?.ts;
  const accumulationPeriod = firstEquityTs && lastEquityTs
    ? `${dateTimeET(firstEquityTs)} → ${dateTimeET(lastEquityTs)} · ${elapsed(lastEquityTs - firstEquityTs)}`
    : null;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Operaciones</h1>
          <p className="page-sub">Posiciones, órdenes y controles de riesgo del motor.</p>
        </div>
        <div className="page-actions">
          <button className="btn" onClick={() => act(() => api.bot(running ? 'pause' : 'resume'))}>
            <Icon name={running ? 'pause' : 'play'} size={13} />
            {running ? 'Pausar bot' : 'Reanudar bot'}
          </button>
          <button className="btn" onClick={() => setConfirm('cancel')}>
            <Icon name="close" size={13} /> Cancelar órdenes
          </button>
          <button className="btn success" disabled={!pos} onClick={() => setConfirm('close')}>
            <Icon name="check" size={13} /> Cerrar posición
          </button>
          <button className="btn danger" onClick={() => setEmergencyOpen(true)}>
            <Icon name="shield" size={13} /> Parada de emergencia
          </button>
        </div>
      </div>

      <div className="grid cols-4" style={{ marginBottom: 12 }}>
        <Card bodyClass="tight">
          <Metric
            label="Posición actual"
            size="sm"
            value={pos ? `${pos.qty} contrato${pos.qty > 1 ? 's' : ''} ${pos.direction === 'long' ? 'largo' : 'corto'}` : 'Sin posición'}
            sub={pos ? `${pos.symbol} · ${pos.signal_type}` : 'Sin exposición abierta'}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Precio medio / actual"
            size="sm"
            value={pos ? `${num(pos.entry_price)} → ${num(pos.current_price)}` : '—'}
            sub={pos ? `SL ${num(pos.stop)} · TP ${num(pos.target)}` : 'Sin órdenes activas'}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="P&L no realizado"
            tone={pos && pos.unrealized > 0 ? 'pos' : pos && pos.unrealized < 0 ? 'neg' : ''}
            value={pos ? moneySigned(pos.unrealized) : '—'}
            sub={pos ? `${pos.r_multiple >= 0 ? '+' : ''}${num(pos.r_multiple)} R · riesgo $${num(pos.risk_amount)}` : 'Sin P&L abierto'}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="P&L del día / acumulado"
            size="sm"
            tone={risk.daily_pnl >= 0 ? 'pos' : 'neg'}
            value={moneySigned(risk.daily_pnl)}
            sub={
              <span className="vstack" style={{ gap: 2, alignItems: 'flex-start' }}>
                <span>Acumulado {moneySigned(risk.cum_pnl)} · {pct(risk.daily_pnl_pct, 2, true)}</span>
                <span className="mono" style={{ fontSize: 9.5 }}>{accumulationPeriod || 'Sin periodo acumulado'}</span>
              </span>
            }
          />
        </Card>
      </div>

      <div className="grid cols-3" style={{ marginBottom: 12 }}>
        <Card title="Riesgo actual" actions={<Icon name="shield" size={14} />}>
          <div className="hstack" style={{ justifyContent: 'space-between', alignItems: 'center' }}>
            <Gauge value={risk.risk_open_pct} max={Math.max(risk.risk_per_trade_pct, 0.5)} label="ABIERTO" color={risk.risk_open_pct > risk.risk_per_trade_pct ? '#f6465d' : '#18c37e'} />
            <div className="kv" style={{ flex: 1 }}>
              <div className="kv-row"><span className="kv-label">Riesgo por operación</span><span className="kv-value">{num(risk.risk_per_trade_pct, 2)}%</span></div>
              <div className="kv-row"><span className="kv-label">Riesgo abierto</span><span className="kv-value">${num(risk.risk_open_amount)}</span></div>
              <div className="kv-row"><span className="kv-label">Límite pérdida diaria</span><span className="kv-value neg">${num(risk.daily_loss_limit)}</span></div>
            </div>
          </div>
        </Card>
        <Card title="Límites de sesión" actions={<Icon name="clock" size={14} />}>
          <div className="kv">
            <div className="kv-row"><span className="kv-label">Operaciones hoy</span><span className="kv-value">{risk.trades_today} / {risk.max_trades_per_day}</span></div>
            <div className="kv-row"><span className="kv-label">Ventana permitida</span><span className="kv-value mono">{snap.session.trade_window_start}–{snap.session.trade_window_end} ET</span></div>
            <div className="kv-row"><span className="kv-label">Cierre de sesión</span><span className="kv-value mono">{snap.session.close_time} ET</span></div>
            <div className="kv-row"><span className="kv-label">Estado</span><span className={`kv-value ${risk.blocked_reason ? 'amber' : 'pos'}`}>{risk.blocked_reason || 'Operativo'}</span></div>
          </div>
        </Card>
        <Card title="Controles" actions={<Icon name="config" size={14} />}>
          <div className="vstack" style={{ gap: 8 }}>
            {risk.emergency ? (
              <>
                <div className="banner danger"><Icon name="shield" size={14} /><div>Emergencia activa: {risk.emergency_reason}</div></div>
                <button className="btn success block" onClick={() => act(() => api.clearEmergency())}>Desactivar parada de emergencia</button>
              </>
            ) : (
              <div className="banner info"><Icon name="shield" size={14} /><div>La parada de emergencia bloquea entradas, cancela órdenes y permite cerrar posiciones.</div></div>
            )}
            <button className="btn block" disabled={!pos} onClick={() => setConfirm('close')}><Icon name="close" size={13} /> Cerrar posición al mercado</button>
            <button className="btn block" onClick={() => setConfirm('cancel')}><Icon name="x" size={13} /> Cancelar órdenes pendientes</button>
          </div>
        </Card>
      </div>

      <Card noBody>
        <div className="tab-row">
          <button className={`tab ${tab === 'positions' ? 'active' : ''}`} onClick={() => setTab('positions')}>
            Posiciones abiertas <span className="count">{pos ? 1 : 0}</span>
          </button>
          <button className={`tab ${tab === 'orders' ? 'active' : ''}`} onClick={() => setTab('orders')}>
            Órdenes pendientes <span className="count">{orders.filter((o) => o.status === 'pending').length}</span>
          </button>
          <button className={`tab ${tab === 'closed' ? 'active' : ''}`} onClick={() => setTab('closed')}>
            Operaciones cerradas <span className="count">{closed.length}</span>
          </button>
        </div>

        {tab === 'positions' && (
          <div className="table-wrap">
            {pos ? (
              <table className="table">
                <thead>
                  <tr>
                    <th>Fecha y hora entrada (ET)</th><th>Instrumento</th><th>Dirección</th><th>Cantidad</th><th>Entrada</th><th>Actual</th>
                    <th>SL</th><th>TP</th><th>Riesgo</th><th>Benef. potencial</th><th>P&L no realizado</th><th>Estado</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="mono">{dateTimeET(pos.entry_ts)}</td>
                    <td className="strong">{pos.symbol}</td>
                    <td><Pill tone={pos.direction === 'long' ? 'success' : 'danger'} className="direction">{pos.direction === 'long' ? 'Larga' : 'Corta'}</Pill></td>
                    <td className="strong">{pos.qty}</td>
                    <td className="mono">{num(pos.entry_price)}</td>
                    <td className="mono">{num(pos.current_price)}</td>
                    <td className="mono neg">{num(pos.stop)}</td>
                    <td className="mono pos">{num(pos.target)}</td>
                    <td className="mono">${num(pos.risk_amount)}</td>
                    <td className="mono pos">${num(Math.abs(pos.target - pos.entry_price) * Number(snap.config.point_value || 2) * pos.qty)}</td>
                    <td className={pos.unrealized >= 0 ? 'pos' : 'neg'}>{moneySigned(pos.unrealized)}</td>
                    <td><Pill tone="success" dot>Abierta</Pill></td>
                  </tr>
                </tbody>
              </table>
            ) : (
              <Empty title="Sin posiciones abiertas" text="El motor no tiene exposición al mercado en este momento." icon="trades" />
            )}
          </div>
        )}

        {tab === 'orders' && (
          <div className="table-wrap">
            {orders.length ? (
              <table className="table">
                <thead>
                  <tr><th>Fecha y hora (ET)</th><th>Rol</th><th>Tipo</th><th>Lado</th><th>Cantidad</th><th>Precio</th><th>Estado</th><th>Origen</th></tr>
                </thead>
                <tbody>
                  {orders.map((o) => (
                    <tr key={o.id}>
                      <td className="mono">{dateTimeET(o.created_ts)}</td>
                      <td className="strong">{o.role === 'entry' ? 'Entrada' : o.role === 'stop' ? 'Stop Loss' : 'Take Profit'}</td>
                      <td>{o.order_type === 'market' ? 'Mercado' : o.order_type === 'stop' ? 'Stop' : 'Límite'}</td>
                      <td className={o.side === 'buy' ? 'pos' : 'neg'}>{o.side === 'buy' ? 'Compra' : 'Venta'}</td>
                      <td>{o.qty}</td>
                      <td className="mono">{o.limit_price ? num(o.limit_price) : 'Mercado'}</td>
                      <td><Pill tone={o.status === 'pending' ? 'warn' : o.status === 'filled' ? 'success' : 'muted'}>{o.status === 'pending' ? 'Pendiente' : o.status === 'filled' ? 'Ejecutada' : 'Cancelada'}</Pill></td>
                      <td className="muted">{o.role === 'entry' ? 'Señal ORB' : 'Bracket protector'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty title="Sin órdenes" text="Las órdenes de entrada y los brackets SL/TP aparecerán aquí." icon="trades" />
            )}
          </div>
        )}

        {tab === 'closed' && (
          <div className="table-wrap">
            {closed.length ? (
              <table className="table">
                <thead>
                  <tr><th>Fecha y hora (ET)</th><th>Dirección</th><th>Cantidad</th><th>Entrada</th><th>Salida</th><th>SL</th><th>TP</th><th>Resultado</th><th>R</th><th>Motivo</th><th>Duración</th></tr>
                </thead>
                <tbody>
                  {closed.map((t) => (
                    <tr key={t.id}>
                      <td className="mono">
                        <div>{dateTimeET(t.exit_ts)}</div>
                        <div className="muted" style={{ fontSize: 9.5, marginTop: 2 }}>Entrada {dateTimeET(t.entry_ts)}</div>
                      </td>
                      <td><Pill tone={t.direction === 'long' ? 'success' : 'danger'} className="direction">{t.direction === 'long' ? 'Larga' : 'Corta'}</Pill></td>
                      <td>{t.qty}</td>
                      <td className="mono">{num(t.entry_price)}</td>
                      <td className="mono">{num(t.exit_price)}</td>
                      <td className="mono neg">{num(t.stop)}</td>
                      <td className="mono pos">{num(t.target)}</td>
                      <td className={`result ${t.pnl >= 0 ? 'pos' : 'neg'}`}>{moneySigned(t.pnl)}</td>
                      <td className={t.r_multiple >= 0 ? 'pos' : 'neg'}>{num(t.r_multiple)}</td>
                      <td className="muted">{exitReasonLabel(t.exit_reason)}</td>
                      <td className="mono">{duration(t.duration_sec)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <Empty title="Sin operaciones cerradas hoy" text="Las operaciones del día aparecerán aquí al ejecutarse." icon="history" />
            )}
          </div>
        )}
      </Card>

      <Modal
        open={confirm !== null}
        title={confirm === 'close' ? 'Cerrar posición al mercado' : 'Cancelar órdenes pendientes'}
        onClose={() => setConfirm(null)}
        footer={
          <>
            <button className="btn ghost" onClick={() => setConfirm(null)}>Cancelar</button>
            <button
              className="btn danger"
              onClick={async () => {
                const action = confirm;
                setConfirm(null);
                if (action === 'close') await act(() => api.closePosition());
                if (action === 'cancel') await act(() => api.cancelOrders());
              }}
            >
              Confirmar
            </button>
          </>
        }
      >
        <p style={{ margin: 0, color: '#9aa9bd', lineHeight: 1.5 }}>
          {confirm === 'close'
            ? 'Se enviará una orden de mercado para cerrar la posición abierta. El P&L se registrará en el historial y en la base de datos.'
            : 'Se cancelarán la orden de entrada pendiente y cualquier bracket sin ejecutar. La posición abierta no se modifica.'}
        </p>
      </Modal>

      <Modal
        open={emergencyOpen}
        title="Parada de emergencia"
        onClose={() => setEmergencyOpen(false)}
        footer={
          <>
            <button className="btn ghost" onClick={() => setEmergencyOpen(false)}>Cancelar</button>
            <button
              className="btn danger"
              onClick={async () => {
                setEmergencyOpen(false);
                await act(() => api.emergency(reason, closeOnEmergency));
              }}
            >
              Activar emergencia
            </button>
          </>
        }
      >
        <div className="banner danger">
          <Icon name="alert" size={15} />
          <div>Bloquea nuevas entradas, cancela órdenes pendientes y registra el motivo en la consola de eventos.</div>
        </div>
        <div className="field">
          <label>Motivo de la intervención</label>
          <input className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Describe el motivo" />
        </div>
        <label className="hstack" style={{ fontSize: 11.5, color: '#9aa9bd' }}>
          <input type="checkbox" checked={closeOnEmergency} onChange={(e) => setCloseOnEmergency(e.target.checked)} />
          Cerrar también la posición abierta
        </label>
      </Modal>
    </div>
  );
}
