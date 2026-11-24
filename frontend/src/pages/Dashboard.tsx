import React, { useEffect, useMemo, useState } from 'react';
import CandleChart from '../components/CandleChart';
import ValidationCard from '../components/ValidationCard';
import { DaySnapshot, PositionPanel, StrategyPanel } from '../components/panels';
import { AreaChart, Card, Empty, Metric, Pill } from '../components/ui';
import { Icon } from '../icons';
import { api } from '../api';
import { useApp } from '../store';
import type { ForwardValidationReport } from '../types';
import { dateTimeET, elapsed, mergeBars, money, moneySigned, num, pct, exitReasonLabel } from '../utils';

export default function Dashboard() {
  const { snap, chartHistory } = useApp();
  const [validation, setValidation] = useState<ForwardValidationReport | null>(null);
  const [validationError, setValidationError] = useState<string | null>(null);
  const bars = useMemo(() => mergeBars(chartHistory, snap?.chart.bars ?? []), [chartHistory, snap?.chart.bars]);
  useEffect(() => {
    let alive = true;
    api
      .forwardValidation()
      .then((report) => {
        if (alive) setValidation(report);
      })
      .catch((e: any) => {
        if (alive) setValidationError(e?.message || 'No se pudo cargar el informe de validación');
      });
    return () => {
      alive = false;
    };
  }, []);
  if (!snap) return null;
  const q = snap.quotes.MNQ;
  const risk = snap.risk;
  const or = snap.opening_range;
  const change = q?.change || 0;
  const stats = snap.stats;
  const maxContracts = Number(snap.settings?.risk?.max_contracts ?? 0) || null;
  const contractsLabel = maxContracts
    ? `${maxContracts} contrato${maxContracts === 1 ? '' : 's'} máx.`
    : 'límite no disponible';
  const equityPoints = (snap.stats.equity_curve || []).map((p) => ({ ts: p.ts, value: p.equity }));
  const equityPeriod = equityPoints.length > 1
    ? `${dateTimeET(equityPoints[0].ts)} → ${dateTimeET(equityPoints[equityPoints.length - 1].ts)} · ${elapsed(equityPoints[equityPoints.length - 1].ts - equityPoints[0].ts)}`
    : null;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Inicio</h1>
          <p className="page-sub">
            Terminal MNQ · ORB + SMT · sesión {snap.session.date || 'sin iniciar'} · {snap.data?.label}
          </p>
        </div>
        <div className="page-actions">
          {or ? (
            <Pill tone={or.complete ? 'info' : 'warn'} dot>
              {or.complete ? `OR ${or.high.toFixed(2)} / ${or.low.toFixed(2)}` : 'OR en formación'}
            </Pill>
          ) : (
            <Pill tone="muted">OR pendiente</Pill>
          )}
          <Pill tone={snap.position ? 'success' : 'muted'} dot>
            {snap.position ? `Posición ${snap.position.direction === 'long' ? 'larga' : 'corta'}` : 'Sin posición'}
          </Pill>
          <Pill tone={risk.emergency ? 'danger' : 'muted'}>{risk.emergency ? 'Emergencia' : 'Riesgo normal'}</Pill>
        </div>
      </div>

      <div className="grid cols-4" style={{ marginBottom: 12 }}>
        <Card bodyClass="tight">
          <Metric label="Equidad" value={`$${num(risk.equity)}`} sub={`Inicial $${num(risk.initial_capital, 0)}`} />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="P&L del día"
            value={moneySigned(risk.daily_pnl)}
            tone={risk.daily_pnl > 0 ? 'pos' : risk.daily_pnl < 0 ? 'neg' : 'neutral'}
            sub={`${pct(risk.daily_pnl_pct, 2, true)} · ${risk.trades_today}/${risk.max_trades_per_day} operaciones`}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Riesgo por operación"
            value={`${num(risk.risk_per_trade_pct, 1)}%`}
            sub={`Abierto ${num(risk.risk_open_amount)} USD (${pct(risk.risk_open_pct, 2)})`}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Drawdown máximo"
            value={pct(risk.max_drawdown_pct, 2)}
            tone="neg"
            sub={`Abierto ${money(-(risk.open_drawdown || 0))} · Límite diario $${num(risk.daily_loss_limit, 0)}`}
          />
        </Card>
      </div>

      <div className="grid cols-4" style={{ marginBottom: 12 }}>
        <Card bodyClass="tight">
          <Metric
            label="Profit Factor"
            value={stats.trades ? (stats.profit_factor === null ? '∞' : num(stats.profit_factor)) : '—'}
            tone={stats.trades && stats.profit_factor !== null && stats.profit_factor >= 1 ? 'pos' : stats.trades ? 'neg' : 'neutral'}
            sub={`Neto ${moneySigned(stats.net_profit)} · ${stats.trades} ops`}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Win rate"
            value={pct(stats.win_rate, 1)}
            sub={`${stats.wins} ganadoras · ${stats.losses} perdedoras`}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Expectativa"
            value={moneySigned(stats.expectancy)}
            tone={stats.expectancy > 0 ? 'pos' : stats.expectancy < 0 ? 'neg' : 'neutral'}
            sub={`R medio ${num(stats.avg_r)} · Total ${num(stats.total_r)} R`}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Racha perdedora"
            value={`${stats.worst_loss_streak} ops`}
            tone={stats.worst_loss_streak >= 5 ? 'neg' : 'neutral'}
            sub={`DD máx. ${pct(stats.max_drawdown_pct, 2)}`}
          />
        </Card>
      </div>

      <ValidationCard report={validation} error={validationError} />

      <div className="dash">
        <div className="dash-main">
          <Card
            noBody
            title={
              <span className="hstack">
                <span className="symbol-tag"><span className="symbol-dot" /> MNQ</span>
                <span>{q && q.last ? num(q.last, 2) : '—'}</span>
                <span className={change >= 0 ? 'pos' : 'neg'} style={{ fontSize: 11 }}>
                  {change >= 0 ? '+' : ''}{num(change, 2)} ({pct(q?.change_pct || 0, 2, true)})
                </span>
              </span>
            }
            actions={
              <>
                <span className="chip">15m</span>
                <span className="chip">ORB + SMT</span>
                {snap.assessment.smt && (
                  <Pill tone="purple">{snap.assessment.smt.bias === 'bullish' ? 'SMT alcista' : 'SMT bajista'}</Pill>
                )}
              </>
            }
          >
            <div className="chart-toolbar">
              <div className="legend">
                <span className="legend-item" style={{ color: '#3f8cff' }}><span className="legend-line" /> OR High {or ? num(or.high) : '—'}</span>
                <span className="legend-item" style={{ color: '#8caacd' }}><span className="legend-line" /> Mid 50% {or ? num(or.mid) : '—'}</span>
                <span className="legend-item" style={{ color: '#3f8cff' }}><span className="legend-line" /> OR Low {or ? num(or.low) : '—'}</span>
                <span className="legend-item" style={{ color: '#a78bfa' }}>● SMT NQ/ES</span>
              </div>
              <span className="muted" style={{ fontSize: 10 }}>
                {snap.assessment.atr ? `ATR ${num(snap.assessment.atr)}` : ''}
              </span>
            </div>
            <div style={{ padding: '0 2px 6px' }}>
              <CandleChart
                bars={bars}
                focusStart={snap.chart.bars[0]?.t ?? null}
                timeframe={15}
                openingRange={or}
                markers={snap.chart.markers}
                position={snap.position}
                referenceLevel={snap.assessment.reference_level}
                height={382}
              />
            </div>
          </Card>

          <div className="dash-bottom">
            <Card
              noBody
              title={<>Posiciones <span className="muted">({snap.position ? 1 : 0})</span></>}
              actions={<span className="card-sub">MNQ · {contractsLabel}</span>}
            >
              {snap.position ? (
                <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>Fecha y hora entrada (ET)</th>
                      <th>Dirección</th>
                      <th>Cant.</th>
                      <th>Entrada</th>
                      <th>Actual</th>
                      <th>P&L</th>
                      <th>Estado</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td className="mono">{dateTimeET(snap.position.entry_ts)}</td>
                      <td><span className={`pill direction ${snap.position.direction === 'long' ? 'success' : 'danger'}`}>{snap.position.direction === 'long' ? 'Larga' : 'Corta'}</span></td>
                      <td className="strong">{snap.position.qty}</td>
                      <td className="mono">{num(snap.position.entry_price)}</td>
                      <td className="mono">{num(snap.position.current_price)}</td>
                      <td className={snap.position.unrealized >= 0 ? 'pos' : 'neg'}>{moneySigned(snap.position.unrealized)}</td>
                      <td><span className="pill success">Abierta</span></td>
                    </tr>
                  </tbody>
                </table>
                </div>
              ) : (
                <Empty title="Sin posiciones abiertas" text="La gestión de SL/TP se supervisa en tiempo real." icon="trades" />
              )}
            </Card>

            <Card noBody title="Historial reciente" actions={<span className="card-sub">últimas operaciones</span>}>
              {snap.recent_trades.length ? (
                <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr><th>Fecha y hora (ET)</th><th>Dir.</th><th>Resultado</th><th className="right">R</th><th>Salida</th></tr>
                  </thead>
                  <tbody>
                    {snap.recent_trades.slice(0, 5).map((t) => (
                      <tr key={t.id}>
                        <td className="mono">
                          <div>{dateTimeET(t.exit_ts)}</div>
                          <div className="muted" style={{ fontSize: 9.5, marginTop: 2 }}>Entrada {dateTimeET(t.entry_ts)}</div>
                        </td>
                        <td><span className={`pill direction ${t.direction === 'long' ? 'success' : 'danger'}`}>{t.direction === 'long' ? 'Larga' : 'Corta'}</span></td>
                        <td className={`result ${t.pnl >= 0 ? 'pos' : 'neg'}`}>{moneySigned(t.pnl)}</td>
                        <td className={`right ${t.r_multiple >= 0 ? 'pos' : 'neg'}`}>{num(t.r_multiple)}</td>
                        <td className="muted">{exitReasonLabel(t.exit_reason)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              ) : (
                <Empty title="Sin operaciones cerradas" text="El registro aparecerá aquí con P&L y R." icon="history" />
              )}
            </Card>

            <DaySnapshot snap={snap} />

            <Card title="Curva de equity" actions={<span className="card-sub">{snap.stats.trades} operaciones</span>}>
              {equityPoints.length > 1 ? (
                <>
                  <AreaChart points={equityPoints} height={104} formatValue={(v) => `$${num(v, 0)}`} />
                  {equityPeriod && <div className="chart-period mono">{equityPeriod}</div>}
                </>
              ) : (
                <Empty title="Curva vacía" text="Se dibuja al cerrar operaciones." />
              )}
            </Card>
          </div>
        </div>

        <div className="dash-side">
          <StrategyPanel snap={snap} />
          <PositionPanel snap={snap} />
          <Card title="Sesión y riesgo" actions={<Icon name="shield" size={14} />}>
            <div className="kv">
              <div className="kv-row"><span className="kv-label">Ventana de operación</span><span className="kv-value mono">{snap.session.trade_window_start}–{snap.session.trade_window_end} ET</span></div>
              <div className="kv-row"><span className="kv-label">Cierre de sesión</span><span className="kv-value mono">{snap.session.close_time} ET</span></div>
              <div className="kv-row"><span className="kv-label">Operaciones hoy</span><span className="kv-value">{risk.trades_today} / {risk.max_trades_per_day}</span></div>
              <div className="kv-row"><span className="kv-label">Bloqueo actual</span><span className={`kv-value ${risk.blocked_reason ? 'amber' : 'pos'}`}>{risk.blocked_reason || 'Ninguno'}</span></div>
              <div className="kv-row"><span className="kv-label">Última actualización</span><span className={`kv-value mono ${snap.data?.stale ? 'neg' : 'pos'}`}>{snap.data?.last_bar_ts ? dateTimeET(snap.data.last_bar_ts) : '—'} · {snap.data?.stale ? 'retrasada' : 'válida'}</span></div>
            </div>
          </Card>
        </div>
      </div>
    </div>
  );
}
