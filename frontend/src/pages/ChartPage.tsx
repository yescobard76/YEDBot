import React, { useMemo, useState } from 'react';
import CandleChart from '../components/CandleChart';
import ComparisonChart from '../components/ComparisonChart';
import { PositionPanel, StrategyPanel } from '../components/panels';
import { Card, Empty, Pill } from '../components/ui';
import { Icon } from '../icons';
import { useApp } from '../store';
import { dateTimeET, mergeBars, num, pct } from '../utils';

const TFS = [1, 5, 15, 30];

export default function ChartPage() {
  const { snap, chartHistory } = useApp();
  const [tf, setTf] = useState(15);
  const [showVwap, setShowVwap] = useState(false);
  const [showAtr, setShowAtr] = useState(false);
  const bars = useMemo(() => mergeBars(chartHistory, snap?.chart.bars ?? []), [chartHistory, snap?.chart.bars]);
  if (!snap) return null;

  const q = snap.quotes.MNQ;
  const or = snap.opening_range;
  const smt = snap.assessment.smt;
  const change = q?.change || 0;
  const simulated = snap.data?.quality === 'simulated';

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Gráfico</h1>
          <p className="page-sub">Velas MNQ, Opening Range, divergencia SMT NQ/ES y niveles de la operación.</p>
        </div>
        <div className="page-actions">
          <Pill tone={snap.data?.connected ? 'success' : 'danger'} dot>
            {snap.data?.label || 'Sin datos'}
          </Pill>
          <span className="chip">Sesión {snap.session.date || '—'}</span>
          {smt && <Pill tone="purple">SMT {smt.bias === 'bullish' ? 'alcista' : 'bajista'}</Pill>}
        </div>
      </div>

      {simulated && (
        <div className="banner warn" style={{ marginBottom: 12 }}>
          <Icon name="alert" size={15} />
          <div>
            <strong>Datos simulados de replay.</strong> No son cotizaciones reales del mercado. El gráfico se alimenta del motor,
            no de una maqueta; carga un CSV histórico real en Configuración → Avanzado para sustituir el replay sintético.
          </div>
        </div>
      )}

      {snap.data?.quality === 'historical' && (
        <div className="banner info" style={{ marginBottom: 12 }}>
          <Icon name="chart" size={15} />
          <div>
            <strong>Histórico real cargado desde CSV.</strong> {snap.data.detail}. Es una reproducción de datos históricos,
            no una cotización en vivo (replay a {num(Number(snap.config.replay_speed) || 0, 1)} velas/s).
          </div>
        </div>
      )}

      <div className="chart-page">
        <div className="vstack" style={{ gap: 12 }}>
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
              <span className="hstack">
                <span className="chip">{or ? `OR ${or.width.toFixed(2)} pts` : 'OR pendiente'}</span>
                <span className="chip">{bars.length} velas 1m</span>
              </span>
            }
          >
            <div className="chart-toolbar">
              <div className="chart-toolbar-left">
                <div className="segmented">
                  {TFS.map((value) => (
                    <button key={value} className={`seg-btn ${tf === value ? 'active' : ''}`} onClick={() => setTf(value)}>
                      {value}m
                    </button>
                  ))}
                </div>
                <span className="divider" />
                <label className="hstack" style={{ fontSize: 10, color: showVwap ? '#e0b64a' : '#637389', cursor: 'pointer' }}>
                  <input type="checkbox" checked={showVwap} onChange={(e) => setShowVwap(e.target.checked)} style={{ accentColor: '#e0b64a' }} />
                  VWAP
                </label>
                <label className="hstack" style={{ fontSize: 10, color: showAtr ? '#a78bfa' : '#637389', cursor: 'pointer' }}>
                  <input type="checkbox" checked={showAtr} onChange={(e) => setShowAtr(e.target.checked)} style={{ accentColor: '#a78bfa' }} />
                  ATR
                </label>
              </div>
              <div className="legend">
                <span className="legend-item" style={{ color: '#3f8cff' }}><span className="legend-line" /> ORH {or ? num(or.high) : '—'}</span>
                <span className="legend-item" style={{ color: '#8caacd' }}><span className="legend-line" /> 50% {or ? num(or.mid) : '—'}</span>
                <span className="legend-item" style={{ color: '#3f8cff' }}><span className="legend-line" /> ORL {or ? num(or.low) : '—'}</span>
                {snap.position && (
                  <>
                    <span className="legend-item" style={{ color: '#f6465d' }}><span className="legend-line" /> SL {num(snap.position.stop)}</span>
                    <span className="legend-item" style={{ color: '#18c37e' }}><span className="legend-line" /> TP {num(snap.position.target)}</span>
                  </>
                )}
              </div>
            </div>
            <CandleChart
              bars={bars}
              focusStart={snap.chart.bars[0]?.t ?? null}
              timeframe={tf}
              openingRange={or}
              markers={snap.chart.markers}
              position={snap.position}
              referenceLevel={snap.assessment.reference_level}
              showVwap={showVwap}
              showAtr={showAtr}
              height={430}
            />
          </Card>

          <Card
            noBody
            title={<>NQ vs ES · SMT <span className="muted">(variación % desde la apertura)</span></>}
            actions={
              smt ? (
                <Pill tone="purple">Divergencia {smt.bias === 'bullish' ? 'alcista' : 'bajista'} confirmada</Pill>
              ) : (
                <span className="card-sub">Sin divergencia activa</span>
              )
            }
          >
            <div className="chart-toolbar">
              <div className="legend">
                <span className="legend-item" style={{ color: '#3f8cff' }}><span className="legend-line" /> NQ</span>
                <span className="legend-item" style={{ color: '#f3a83b' }}><span className="legend-line" /> ES</span>
              </div>
              {smt && (
                <span className="muted" style={{ fontSize: 10 }}>
                  NQ {num(smt.primary_prev)} → {num(smt.primary_last)} · ES {num(smt.reference_prev)} → {num(smt.reference_last)}
                </span>
              )}
            </div>
            {snap.chart.nq.length > 1 ? (
              <ComparisonChart nq={snap.chart.nq} es={snap.chart.es} height={170} />
            ) : (
              <Empty title="Sin datos intermarket" text="NQ y ES se sincronizan por timestamp." />
            )}
          </Card>
        </div>

        <div className="dash-side">
          <StrategyPanel snap={snap} />
          <PositionPanel snap={snap} />
          <Card
            title={<><Icon name="chart" size={14} /> Detalle de señal</>}
            actions={snap.assessment.signal ? <Pill tone="success">Validada</Pill> : <Pill tone="muted">Sin señal</Pill>}
          >
            {snap.assessment.signal ? (
              <>
                <div className="kv">
                  <div className="kv-row"><span className="kv-label">Tipo</span><span className="kv-value">{snap.assessment.signal.signal_type}</span></div>
                  <div className="kv-row"><span className="kv-label">Dirección</span><span className={`kv-value ${snap.assessment.signal.direction === 'long' ? 'pos' : 'neg'}`}>{snap.assessment.signal.direction === 'long' ? 'Larga' : 'Corta'}</span></div>
                  <div className="kv-row"><span className="kv-label">Activada</span><span className="kv-value mono">{dateTimeET(snap.assessment.signal.ts)}</span></div>
                  <div className="kv-row"><span className="kv-label">Entrada</span><span className="kv-value mono">{num(snap.assessment.signal.entry_price)}</span></div>
                  <div className="kv-row"><span className="kv-label">Stop / Target</span><span className="kv-value mono">{num(snap.assessment.signal.stop)} / {num(snap.assessment.signal.target)}</span></div>
                  <div className="kv-row"><span className="kv-label">Referencia</span><span className="kv-value mono">{num(snap.assessment.reference_level)}</span></div>
                </div>
                <p className="phase-detail" style={{ marginTop: 8 }}>{snap.assessment.signal.entry_reason}</p>
              </>
            ) : (
              <Empty title="Esperando confirmación" text="Revisa el panel de fases para ver qué condición falta." icon="clock" />
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
