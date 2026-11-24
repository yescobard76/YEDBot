import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { Card, Empty, Modal, Pill } from '../components/ui';
import { Icon } from '../icons';
import { useApp } from '../store';
import { Trade, TradesResponse } from '../types';
import { dateTimeET, duration, exitReasonLabel, money, moneySigned, num } from '../utils';

const PERIODS = [
  { value: 'today', label: 'Hoy' },
  { value: 'week', label: 'Esta semana' },
  { value: 'month', label: 'Este mes' },
  { value: '30d', label: 'Últimos 30 días' },
  { value: 'all', label: 'Todo el historial' },
];

const SIGNALS = ['all', 'ORB', 'ORB+SMT', 'ORB+Retest', 'ORB+SMT+Retest'];

export default function HistoryPage() {
  const { snap } = useApp();
  const [period, setPeriod] = useState('30d');
  const [direction, setDirection] = useState('all');
  const [result, setResult] = useState('all');
  const [signal, setSignal] = useState('all');
  const [page, setPage] = useState(0);
  const [data, setData] = useState<TradesResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [detail, setDetail] = useState<Trade | null>(null);
  const limit = 25;

  useEffect(() => {
    setPage(0);
  }, [period, direction, result, signal]);

  const filters = useMemo(() => {
    const f: Record<string, string | number> = { period };
    if (direction !== 'all') f.direction = direction;
    if (result !== 'all') f.result = result;
    if (signal !== 'all') f.signal_type = signal;
    return f;
  }, [period, direction, result, signal]);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    api
      .trades({ ...filters, limit, offset: page * limit })
      .then((res) => {
        if (alive) setData(res);
      })
      .catch(() => alive && setData({ items: [], total: 0, limit, offset: 0 }))
      .finally(() => alive && setLoading(false));
    return () => {
      alive = false;
    };
  }, [filters, page, limit, snap?.stats.trades]);

  const query = useMemo(
    () => new URLSearchParams(Object.entries(filters).map(([k, v]) => [k, String(v)])).toString(),
    [filters],
  );

  const items = data?.items || [];
  const total = data?.total || 0;
  const pages = Math.max(1, Math.ceil(total / limit));

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Historial de operaciones</h1>
          <p className="page-sub">Registro persistente en SQLite de todas las ejecuciones del motor.</p>
        </div>
        <div className="page-actions">
          <a className="btn primary" href={`/api/trades/export.csv?${query}`}>
            <Icon name="download" size={13} /> Exportar CSV
          </a>
        </div>
      </div>

      <Card noBody>
        <div className="chart-toolbar">
          <div className="chart-toolbar-left">
            <select className="select" value={period} onChange={(e) => setPeriod(e.target.value)} style={{ width: 160 }}>
              {PERIODS.map((p) => (
                <option key={p.value} value={p.value}>{p.label}</option>
              ))}
            </select>
            <select className="select" value={direction} onChange={(e) => setDirection(e.target.value)} style={{ width: 140 }}>
              <option value="all">Todas las direcciones</option>
              <option value="long">Largas</option>
              <option value="short">Cortas</option>
            </select>
            <select className="select" value={result} onChange={(e) => setResult(e.target.value)} style={{ width: 130 }}>
              <option value="all">Todos los resultados</option>
              <option value="win">Ganadoras</option>
              <option value="loss">Perdedoras</option>
              <option value="be">Breakeven</option>
            </select>
            <select className="select" value={signal} onChange={(e) => setSignal(e.target.value)} style={{ width: 180 }}>
              <option value="all">Todos los tipos de señal</option>
              {SIGNALS.filter((s) => s !== 'all').map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <span className="card-sub">{loading ? 'Cargando…' : `${total} operaciones`}</span>
        </div>

        <div className="table-wrap">
          {items.length ? (
            <table className="table">
              <thead>
                <tr>
                  <th>Fecha y hora (ET)</th><th>Instrumento</th><th>Dirección</th><th>Cant.</th>
                  <th>Entrada</th><th>Salida</th><th>SL</th><th>TP</th><th>Resultado</th><th>R</th>
                  <th>Duración</th><th>Tipo de señal</th><th>Motivo salida</th>
                </tr>
              </thead>
              <tbody>
                {items.map((t) => (
                  <tr key={t.id} className="clickable" onClick={() => setDetail(t)}>
                    <td className="mono">
                      <div>{dateTimeET(t.exit_ts)}</div>
                      <div className="muted" style={{ fontSize: 9.5, marginTop: 2 }}>Entrada {dateTimeET(t.entry_ts)}</div>
                    </td>
                    <td className="strong">{t.symbol}</td>
                    <td><Pill tone={t.direction === 'long' ? 'success' : 'danger'} className="direction">{t.direction === 'long' ? 'Larga' : 'Corta'}</Pill></td>
                    <td>{t.qty}</td>
                    <td className="mono">{num(t.entry_price)}</td>
                    <td className="mono">{num(t.exit_price)}</td>
                    <td className="mono neg">{num(t.stop)}</td>
                    <td className="mono pos">{num(t.target)}</td>
                    <td className={`result ${t.pnl >= 0 ? 'pos' : 'neg'}`}>{moneySigned(t.pnl)}</td>
                    <td className={t.r_multiple >= 0 ? 'pos' : 'neg'}>{num(t.r_multiple)}</td>
                    <td className="mono">{duration(t.duration_sec)}</td>
                    <td><span className="chip">{t.signal_type}</span></td>
                    <td className="muted">{exitReasonLabel(t.exit_reason)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <Empty
              title={loading ? 'Cargando operaciones…' : 'Sin operaciones en el periodo'}
              text="Ajusta los filtros o espera a que el motor cierre su primera operación. No se inventan resultados."
              icon="history"
            />
          )}
        </div>

        <div className="pagination">
          <span>Mostrando {items.length ? page * limit + 1 : 0}–{page * limit + items.length} de {total}</span>
          <div className="hstack">
            <button className="btn sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
              <Icon name="chevronLeft" size={12} /> Anterior
            </button>
            <span>Página {page + 1} / {pages}</span>
            <button className="btn sm" disabled={page + 1 >= pages} onClick={() => setPage((p) => p + 1)}>
              Siguiente <Icon name="chevronRight" size={12} />
            </button>
          </div>
        </div>
      </Card>

      <Modal open={!!detail} title="Detalle de la operación" onClose={() => setDetail(null)} width={640}>
        {detail && (
          <>
            <div className="hstack" style={{ justifyContent: 'space-between' }}>
              <div>
                <span className={`pill direction ${detail.direction === 'long' ? 'success' : 'danger'}`}>{detail.direction === 'long' ? 'Larga' : 'Corta'}</span>{' '}
                <span className="chip">{detail.signal_type}</span>
              </div>
              <div className={detail.pnl >= 0 ? 'pos' : 'neg'} style={{ fontSize: 20, fontWeight: 700 }}>
                {moneySigned(detail.pnl)} <span style={{ fontSize: 12 }}>({num(detail.r_multiple)} R)</span>
              </div>
            </div>
            <div className="grid cols-2">
              <div className="kv">
                <div className="kv-row"><span className="kv-label">Instrumento</span><span className="kv-value">{detail.symbol}</span></div>
                <div className="kv-row"><span className="kv-label">Cantidad</span><span className="kv-value">{detail.qty} contratos</span></div>
                <div className="kv-row"><span className="kv-label">Entrada</span><span className="kv-value mono">{num(detail.entry_price)} · {dateTimeET(detail.entry_ts)}</span></div>
                <div className="kv-row"><span className="kv-label">Salida</span><span className="kv-value mono">{num(detail.exit_price)} · {dateTimeET(detail.exit_ts)}</span></div>
                <div className="kv-row"><span className="kv-label">Duración</span><span className="kv-value mono">{duration(detail.duration_sec)}</span></div>
              </div>
              <div className="kv">
                <div className="kv-row"><span className="kv-label">Stop Loss</span><span className="kv-value mono neg">{num(detail.stop)}</span></div>
                <div className="kv-row"><span className="kv-label">Take Profit</span><span className="kv-value mono pos">{num(detail.target)}</span></div>
                <div className="kv-row"><span className="kv-label">Bruto / comisiones</span><span className="kv-value mono">{moneySigned(detail.gross_pnl)} / -${num(detail.fees)}</span></div>
                <div className="kv-row"><span className="kv-label">Riesgo</span><span className="kv-value mono">${num(detail.risk_amount)}</span></div>
                <div className="kv-row"><span className="kv-label">MFE / MAE</span><span className="kv-value mono">{num(detail.mfe_r ?? 0)} R / {num(detail.mae_r ?? 0)} R</span></div>
                <div className="kv-row"><span className="kv-label">Drawdown abierto</span><span className="kv-value mono neg">{money(-(detail.open_drawdown ?? 0))}</span></div>
                <div className="kv-row"><span className="kv-label">Modo</span><span className="kv-value">{detail.mode === 'paper' ? 'Paper' : detail.mode}</span></div>
              </div>
            </div>
            <div>
              <div className="section-title">Motivo de entrada</div>
              <p style={{ margin: 0, fontSize: 11.5, color: '#9aa9bd', lineHeight: 1.5 }}>{detail.entry_reason}</p>
            </div>
            <div>
              <div className="section-title">Motivo de salida</div>
              <p style={{ margin: 0, fontSize: 11.5, color: '#9aa9bd' }}>{exitReasonLabel(detail.exit_reason)} ({detail.exit_reason})</p>
            </div>
            <div className="card-sub">ID {detail.id} · señal {String((detail.meta as any)?.signal_id || '—')}</div>
          </>
        )}
      </Modal>
    </div>
  );
}
