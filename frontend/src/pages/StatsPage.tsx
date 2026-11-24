import React, { useEffect, useMemo, useRef, useState } from 'react';
import { api } from '../api';
import { AreaChart, BarsChart, Card, Donut, Empty, Metric, Pill } from '../components/ui';
import { Icon } from '../icons';
import { useApp } from '../store';
import {
  BacktestResult,
  PresetCatalogEntry,
  PresetCatalogResponse,
  PresetCatalogSample,
  PresetComparisonResponse,
  Stats,
} from '../types';
import { dateTimeET, drawdownSeries, elapsed, money, moneySigned, num, pct } from '../utils';

const PERIODS = [
  { value: 'all', label: 'Todo' },
  { value: '30d', label: '30 días' },
  { value: 'month', label: 'Este mes' },
  { value: 'week', label: 'Esta semana' },
];

type Tab = 'resumen' | 'rendimiento' | 'direccion' | 'hora' | 'mes';

const ACTIVE_WINDOW_SEARCH_LIMIT = 3;

const SAMPLE_TITLES: Record<string, string> = {
  activity: 'Muestra con actividad',
  no_trades: 'Muestra sin operaciones',
  insufficient: 'Muestra insuficiente',
};

function sampleOrigin(sample: PresetCatalogSample): string {
  const kind = sample.kind === 'csv' ? 'CSV real' : 'sintético';
  const file =
    sample.file_name ||
    sample.path ||
    (sample.kind === 'csv' ? 'CSV configurado' : 'generador sintético');
  const series = sample.series_mode === 'adjusted' ? 'serie ajustada' : 'serie raw';
  return `${kind} · ${file} · ${series}${sample.exclude_roll_sessions ? ' · rolls excluidos' : ''}`;
}

function daysDetailFromTrades(result: BacktestResult): BacktestResult['days_detail'] {
  if (result.days_detail?.length) return result.days_detail;
  const byDate = new Map<string, { date: string; pnl: number; trades: number }>();
  for (const trade of result.trades || []) {
    const date = dateTimeET(trade.exit_ts).slice(0, 10);
    const row = byDate.get(date) ?? { date, pnl: 0, trades: 0 };
    row.pnl += Number(trade.pnl) || 0;
    row.trades += 1;
    byDate.set(date, row);
  }
  let equity = Number(result.config?.risk?.initial_capital ?? 0);
  return Array.from(byDate.values())
    .sort((a, b) => a.date.localeCompare(b.date))
    .map((row) => {
      equity += row.pnl;
      return {
        date: row.date,
        pnl: Math.round(row.pnl * 100) / 100,
        trades: row.trades,
        equity: Math.round(equity * 100) / 100,
      };
    });
}

function normalizeSavedBacktest(result: BacktestResult): BacktestResult {
  return {
    ...result,
    data_quality: result.data_quality ?? (result.data_source === 'csv' ? 'historical' : 'simulated'),
    is_synthetic: result.is_synthetic ?? result.data_source !== 'csv',
    days_detail: daysDetailFromTrades(result),
  };
}

export default function StatsPage() {
  const { snap } = useApp();
  const [period, setPeriod] = useState('all');
  const [stats, setStats] = useState<Stats | null>(snap?.stats || null);
  const [tab, setTab] = useState<Tab>('resumen');
  const [days, setDays] = useState(20);
  const [startDate, setStartDate] = useState('');
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bt, setBt] = useState<BacktestResult | null>(null);
  const [loadedSavedBacktest, setLoadedSavedBacktest] = useState(false);
  const [variants, setVariants] = useState<BacktestResult[]>([]);
  const savedBacktestRequest = useRef(0);
  const [presetDays, setPresetDays] = useState(20);
  const [presetStartDate, setPresetStartDate] = useState('');
  const [presetRunning, setPresetRunning] = useState(false);
  const [presetError, setPresetError] = useState<string | null>(null);
  const [presetComparison, setPresetComparison] = useState<PresetComparisonResponse | null>(null);
  const [presetCatalog, setPresetCatalog] = useState<PresetCatalogResponse | null>(null);
  const [presetSearching, setPresetSearching] = useState(false);
  const [presetSearchMessage, setPresetSearchMessage] = useState<string | null>(null);
  const [presetResultKey, setPresetResultKey] = useState<string | null>(null);
  const presetInputKey = `${presetDays}|${presetStartDate}`;
  const presetWindowStart =
    presetComparison?.dataset?.sessions?.dates?.[0] ??
    presetComparison?.dataset?.selected_range?.first_et?.slice(0, 10) ??
    null;
  const presetSessionList = presetComparison?.dataset?.all_sessions ?? [];
  const presetCurrentIndex = presetWindowStart
    ? presetSessionList.indexOf(presetWindowStart)
    : -1;
  const activeWindowCandidates =
    presetComparison?.sample.status === 'no_trades' && presetCurrentIndex > 0
      ? Array.from(
          { length: Math.min(ACTIVE_WINDOW_SEARCH_LIMIT, presetCurrentIndex) },
          (_, offset) => presetSessionList[presetCurrentIndex - 1 - offset],
        )
      : [];

  useEffect(() => {
    let alive = true;
    api
      .stats(period === 'all' ? undefined : period)
      .then((s) => alive && setStats(s))
      .catch(() => alive && setStats(null));
    return () => {
      alive = false;
    };
  }, [period, snap?.stats.trades]);

  useEffect(() => {
    let alive = true;
    api
      .presetCatalog()
      .then((catalog) => alive && setPresetCatalog(catalog))
      .catch(() => alive && setPresetCatalog(null));
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    const requestId = ++savedBacktestRequest.current;
    let alive = true;
    api
      .latestBacktest()
      .then(({ result }) => {
        if (!alive || requestId !== savedBacktestRequest.current || !result) return;
        setBt(normalizeSavedBacktest(result));
        setLoadedSavedBacktest(true);
        const savedDays = Number(result.config?.days);
        if (Number.isInteger(savedDays) && savedDays >= 3 && savedDays <= 250) setDays(savedDays);
        const savedStart = result.dataset?.requested_start;
        if (savedStart) setStartDate(savedStart);
      })
      .catch(() => {
        /* No hay backtest guardado o el endpoint no está disponible. */
      });
    return () => {
      alive = false;
    };
  }, []);

  const s = stats || snap?.stats;
  const equity = useMemo(() => (s?.equity_curve || []).map((p) => ({ ts: p.ts, value: p.equity })), [s]);
  const equityPeriod = equity.length > 1
    ? `${dateTimeET(equity[0].ts)} → ${dateTimeET(equity[equity.length - 1].ts)} · ${elapsed(equity[equity.length - 1].ts - equity[0].ts)}`
    : null;
  const dd = useMemo(() => drawdownSeries(s?.equity_curve || []).map((p) => ({ ts: p.ts, value: p.dd })), [s]);
  const backtestPeriod = bt?.equity && bt.equity.length > 1
    ? `${dateTimeET(bt.equity[0].ts)} → ${dateTimeET(bt.equity[bt.equity.length - 1].ts)} · ${elapsed(bt.equity[bt.equity.length - 1].ts - bt.equity[0].ts)}`
    : null;

  const weekly = useMemo(() => {
    if (!s?.daily?.length) return [];
    const buckets = new Map<string, number>();
    for (const day of s.daily) {
      const date = new Date(`${day.key}T12:00:00`);
      const monday = new Date(date);
      const dayIdx = (date.getDay() + 6) % 7;
      monday.setDate(date.getDate() - dayIdx);
      const key = monday.toISOString().slice(5, 10);
      buckets.set(key, (buckets.get(key) || 0) + day.pnl);
    }
    return Array.from(buckets.entries()).map(([label, value]) => ({ label, value }));
  }, [s]);

  const runBacktest = async (compare: boolean) => {
    savedBacktestRequest.current += 1;
    setLoadedSavedBacktest(false);
    setRunning(true);
    setError(null);
    setBt(null);
    setVariants([]);
    try {
      const result = await api.backtest({ days, compare, start_date: startDate || undefined });
      if (compare) setVariants(result.variants || []);
      else setBt(result);
    } catch (e: any) {
      setError(e?.message || 'El backtest falló');
    } finally {
      setRunning(false);
    }
  };

  const runPresetComparison = async () => {
    const resultKey = presetInputKey;
    setPresetRunning(true);
    setPresetError(null);
    setPresetSearchMessage(null);
    setPresetComparison(null);
    setPresetResultKey(null);
    try {
      const result = await api.presets({
        days: presetDays,
        start_date: presetStartDate || undefined,
      });
      setPresetComparison(result);
      setPresetResultKey(resultKey);
    } catch (e: any) {
      setPresetError(e?.message || 'La comparación de presets falló');
    } finally {
      setPresetRunning(false);
    }
  };

  const searchActiveWindow = async () => {
    if (presetSearching || !activeWindowCandidates.length) return;
    setPresetSearching(true);
    setPresetError(null);
    try {
      for (let index = 0; index < activeWindowCandidates.length; index += 1) {
        const start = activeWindowCandidates[index];
        setPresetSearchMessage(
          `Probando ventana ${index + 1}/${activeWindowCandidates.length}: ${start}…`,
        );
        const probe = await api.presets({
          days: 3,
          presets: ['baseline'],
          start_date: start,
        });
        if (probe.sample.status !== 'activity') continue;
        const result = await api.presets({ days: 3, start_date: start });
        setPresetDays(3);
        setPresetStartDate(start);
        setPresetComparison(result);
        setPresetResultKey(`3|${start}`);
        setPresetSearchMessage(`Ventana con actividad encontrada desde ${start}.`);
        return;
      }
      setPresetSearchMessage(
        `Sin actividad en las ${activeWindowCandidates.length} ventanas anteriores probadas.`,
      );
    } catch (e: any) {
      setPresetSearchMessage(e?.message || 'La búsqueda de ventana falló');
    } finally {
      setPresetSearching(false);
    }
  };

  if (!snap || !s) return null;
  const noTrades = s.trades === 0;
  const presetSample = presetComparison?.sample;
  const presetStale = Boolean(presetComparison && presetResultKey !== presetInputKey);
  const defaultPresets: PresetCatalogEntry[] = presetCatalog
    ? presetCatalog.default
        .map((key) => presetCatalog.presets.find((preset) => preset.key === key))
        .filter((preset): preset is PresetCatalogEntry => Boolean(preset))
    : [];
  const catalogOrigin = presetCatalog ? sampleOrigin(presetCatalog.sample) : null;
  const provenance = bt?.dataset?.id ? bt.dataset : variants[0]?.dataset;
  const contractText = provenance
    ? Object.entries(provenance.contracts || {})
        .flatMap(([symbol, contracts]) => (contracts || []).map((contract) => `${symbol}:${contract}`))
        .join(' · ') || 'sin contrato declarado'
    : '';
  const presetDataset = presetComparison?.dataset;
  const presetRange = presetDataset?.selected_range;

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Estadísticas y rendimiento</h1>
          <p className="page-sub">Métricas derivadas exclusivamente de operaciones registradas por el motor.</p>
        </div>
        <div className="page-actions">
          <div className="segmented">
            {PERIODS.map((p) => (
              <button key={p.value} className={`seg-btn ${period === p.value ? 'active' : ''}`} onClick={() => setPeriod(p.value)}>
                {p.label}
              </button>
            ))}
          </div>
          <a className="btn" href="/api/trades/export.csv?period=all"><Icon name="download" size={13} /> CSV</a>
        </div>
      </div>

      {noTrades && (
        <div className="banner info" style={{ marginBottom: 12 }}>
          <Icon name="alert" size={15} />
          <div>
            No hay operaciones registradas en este periodo, así que las métricas están a cero. No se generan resultados de ejemplo:
            ejecuta el motor o un backtest para obtener datos reales del sistema.
          </div>
        </div>
      )}

      <div className="grid cols-6" style={{ marginBottom: 12 }}>
        <Card bodyClass="tight"><Metric label="Win rate" value={pct(s.win_rate, 1)} sub={`${s.wins}G / ${s.losses}P`} /></Card>
        <Card bodyClass="tight"><Metric label="Profit factor" value={s.trades === 0 ? '—' : s.profit_factor === null ? '∞' : num(s.profit_factor)} sub="Bruto G / P" /></Card>
        <Card bodyClass="tight"><Metric label="Expectativa" value={moneySigned(s.expectancy)} tone={s.expectancy >= 0 ? 'pos' : 'neg'} sub="Por operación" /></Card>
        <Card bodyClass="tight"><Metric label="Beneficio neto" value={moneySigned(s.net_profit)} tone={s.net_profit >= 0 ? 'pos' : 'neg'} sub={`${s.trades} operaciones`} /></Card>
        <Card bodyClass="tight"><Metric label="Drawdown máx." value={pct(s.max_drawdown_pct, 2)} tone="neg" sub={money(-s.max_drawdown)} /></Card>
        <Card bodyClass="tight">
          <Metric label="Sharpe / Sortino" value={`${s.sharpe === null ? '—' : num(s.sharpe)} / ${s.sortino === null ? '—' : num(s.sortino)}`} sub="Anualizado (252)" />
        </Card>
        <Card bodyClass="tight"><Metric label="Promedio R" value={num(s.avg_r)} tone={s.avg_r >= 0 ? 'pos' : 'neg'} sub={`Total ${num(s.total_r)} R`} /></Card>
        <Card bodyClass="tight"><Metric label="MFE medio" value={`${num(s.avg_mfe_r ?? 0)} R`} tone="pos" sub="Excursión favorable" /></Card>
        <Card bodyClass="tight"><Metric label="MAE medio" value={`${num(s.avg_mae_r ?? 0)} R`} tone="neg" sub="Excursión adversa" /></Card>
        <Card bodyClass="tight"><Metric label="DD abierto máx." value={money(-(s.max_open_drawdown ?? 0))} tone="neg" sub="P&amp;L no realizado" /></Card>
        <Card bodyClass="tight"><Metric label="Ganancia media" value={moneySigned(s.avg_win)} tone="pos" sub={`Mejor ${moneySigned(s.best_trade)}`} /></Card>
        <Card bodyClass="tight"><Metric label="Pérdida media" value={moneySigned(s.avg_loss)} tone="neg" sub={`Peor ${moneySigned(s.worst_trade)}`} /></Card>
        <Card bodyClass="tight"><Metric label="Racha ganadora" value={s.best_win_streak} sub={`Perdedora ${s.worst_loss_streak}`} /></Card>
        <Card bodyClass="tight"><Metric label="Comisiones" value={money(s.fees)} sub="Acumuladas" /></Card>
        <Card bodyClass="tight"><Metric label="Duración media" value={`${Math.round(s.avg_duration_sec / 60)} min`} sub={`${s.trades} cerradas`} /></Card>
      </div>

      <Card noBody>
        <div className="tab-row">
          {[
            ['resumen', 'Resumen'],
            ['rendimiento', 'Rendimiento'],
            ['direccion', 'Por dirección'],
            ['hora', 'Por hora'],
            ['mes', 'Por mes'],
          ].map(([key, label]) => (
            <button key={key} className={`tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key as Tab)}>{label}</button>
          ))}
        </div>

        {tab === 'resumen' && (
          <div className="grid cols-2" style={{ padding: 14 }}>
            <Card title="Curva de equity" actions={<span className="card-sub">{money(s.equity_curve.length ? s.equity_curve[s.equity_curve.length - 1].equity : snap.risk.equity)}</span>}>
              {equity.length > 1 ? <><AreaChart points={equity} height={190} formatValue={(v) => `$${num(v, 0)}`} />{equityPeriod && <div className="chart-period mono">{equityPeriod}</div>}</> : <Empty title="Sin curva todavía" />}
            </Card>
            <Card title="Drawdown" actions={<span className="card-sub neg">{pct(s.max_drawdown_pct, 2)}</span>}>
              {dd.length > 1 ? <AreaChart points={dd} height={190} color="#f6465d" formatValue={(v) => `${num(v, 2)}%`} /> : <Empty title="Sin drawdown registrado" />}
            </Card>
            <Card title="Distribución de resultados">
              <Donut
                segments={[
                  { label: 'Ganadoras', value: s.wins, color: '#18c37e' },
                  { label: 'Perdedoras', value: s.losses, color: '#f6465d' },
                  { label: 'Breakeven', value: s.breakeven, color: '#637389' },
                ]}
                centerLabel={pct(s.win_rate, 1)}
                centerSub="WIN RATE"
              />
            </Card>
            <Card title="Resultados diarios" actions={<span className="card-sub">P&L por sesión</span>}>
              <BarsChart items={s.daily.map((d) => ({ label: d.label, value: d.pnl }))} height={150} showEvery={Math.max(1, Math.ceil(s.daily.length / 8))} />
            </Card>
          </div>
        )}

        {tab === 'rendimiento' && (
          <div className="grid cols-2" style={{ padding: 14 }}>
            <Card title="Resultado diario">
              <BarsChart items={s.daily.map((d) => ({ label: d.label, value: d.pnl }))} height={170} showEvery={Math.max(1, Math.ceil(s.daily.length / 8))} />
            </Card>
            <Card title="Resultado semanal">
              <BarsChart items={weekly} height={170} showEvery={Math.max(1, Math.ceil(weekly.length / 8))} />
            </Card>
            <Card title="Resultados por día de la semana">
              <BarsChart items={s.by_weekday.map((d) => ({ label: d.label, value: d.pnl }))} height={150} />
            </Card>
            <Card title="Tipos de señal">
              <BarsChart items={s.by_signal.map((d) => ({ label: d.label, value: d.pnl }))} height={150} />
            </Card>
            <Card title="Rachas" className="span-2">
              <div className="grid cols-4">
                <Metric label="Mejor racha ganadora" value={s.best_win_streak} tone="pos" sub="operaciones" />
                <Metric label="Peor racha perdedora" value={s.worst_loss_streak} tone="neg" sub="operaciones" />
                <Metric label="Ganancia media R" value={num(s.avg_win_r)} tone="pos" />
                <Metric label="Pérdida media R" value={num(s.avg_loss_r)} tone="neg" />
              </div>
            </Card>
          </div>
        )}

        {tab === 'direccion' && (
          <div className="grid cols-2" style={{ padding: 14 }}>
            <Card title="Resultado por dirección">
              {s.by_direction.length ? (
                <table className="table">
                  <thead><tr><th>Dirección</th><th>Operaciones</th><th>Win rate</th><th className="right">P&L</th></tr></thead>
                  <tbody>
                    {s.by_direction.map((d) => (
                      <tr key={d.key}>
                        <td><Pill tone={d.key === 'long' ? 'success' : 'danger'} className="direction">{d.label}</Pill></td>
                        <td>{d.trades}</td>
                        <td>{pct(d.win_rate, 1)}</td>
                        <td className={`right ${d.pnl >= 0 ? 'pos' : 'neg'}`}>{moneySigned(d.pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <Empty title="Sin operaciones" />}
            </Card>
            <Card title="Distribución de P&L">
              <BarsChart items={s.by_direction.map((d) => ({ label: d.label, value: d.pnl }))} height={180} />
            </Card>
          </div>
        )}

        {tab === 'hora' && (
          <div className="grid cols-2" style={{ padding: 14 }}>
            <Card title="P&L por hora (ET)">
              <BarsChart items={s.by_hour.map((h) => ({ label: h.label, value: h.pnl }))} height={200} />
            </Card>
            <Card title="Detalle por hora">
              {s.by_hour.length ? (
                <table className="table">
                  <thead><tr><th>Hora</th><th>Operaciones</th><th>Win rate</th><th className="right">P&L</th></tr></thead>
                  <tbody>
                    {s.by_hour.map((h) => (
                      <tr key={h.key}>
                        <td className="mono">{h.label}</td>
                        <td>{h.trades}</td>
                        <td>{pct(h.win_rate, 1)}</td>
                        <td className={`right ${h.pnl >= 0 ? 'pos' : 'neg'}`}>{moneySigned(h.pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <Empty title="Sin operaciones" />}
            </Card>
          </div>
        )}

        {tab === 'mes' && (
          <div style={{ padding: 14 }}>
            <Card title="Resultado mensual" noBody>
              {s.monthly.length ? (
                <table className="table">
                  <thead><tr><th>Mes</th><th>Operaciones</th><th>Ganadoras</th><th>Win rate</th><th className="right">P&L</th></tr></thead>
                  <tbody>
                    {s.monthly.map((m) => (
                      <tr key={m.key}>
                        <td className="strong">{m.label}</td>
                        <td>{m.trades}</td>
                        <td>{m.wins}</td>
                        <td>{pct(m.win_rate, 1)}</td>
                        <td className={`right ${m.pnl >= 0 ? 'pos' : 'neg'}`}>{moneySigned(m.pnl)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : <Empty title="Sin operaciones mensuales" />}
            </Card>
          </div>
        )}
      </Card>

      <Card
        title={<><Icon name="chart" size={14} /> Backtesting</>}
        sub="Motor independiente. Los backtests sintéticos se etiquetan como tales y no representan el mercado real."
        actions={<span className="card-sub">Datos del sistema · comisiones y slippage incluidos</span>}
      >
        <div className="hstack" style={{ marginBottom: 12 }}>
          <div className="field" style={{ width: 130 }}>
            <label>Sesiones</label>
            <input className="input" type="number" min={3} max={250} value={days} onChange={(e) => setDays(Number(e.target.value) || 20)} />
          </div>
          <button className="btn primary" disabled={running} onClick={() => runBacktest(false)}>
            <Icon name="play" size={12} /> {running ? 'Ejecutando…' : 'Ejecutar backtest'}
          </button>
          <button className="btn" disabled={running} onClick={() => runBacktest(true)}>
            <Icon name="stats" size={13} /> Comparar 4 variantes
          </button>
          <div className="field" style={{ width: 160 }}>
            <label>Muestra desde (opcional)</label>
            <input className="input" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
          </div>
          {running && <span className="spinner" style={{ width: 16, height: 16 }} />}
          <span className="muted" style={{ fontSize: 10.5 }}>
            ORB · ORB+SMT · ORB+retesteo · completa
          </span>
        </div>

        {error && <div className="banner danger" style={{ marginBottom: 12 }}><Icon name="alert" size={14} /><div>{error}</div></div>}

        {loadedSavedBacktest && bt && (
          <div className="banner info" style={{ marginBottom: 12 }} data-loaded-backtest="true">
            <Icon name="history" size={14} />
            <div>
              <strong>Último backtest guardado.</strong> {bt.label} · {dateTimeET(bt.created_ts / 1000)}
            </div>
          </div>
        )}

        {(bt?.is_synthetic || variants.some((v) => v.is_synthetic)) && (
          <div className="banner warn" style={{ marginBottom: 12 }}>
            <Icon name="alert" size={14} />
            <div>
              Resultado sobre <strong>datos sintéticos generados</strong> por el simulador de replay, no sobre historia real del MNQ.
              Sirve para validar la lógica, no para estimar rentabilidad. Importa un CSV real para un backtest válido.
            </div>
          </div>
        )}

        {provenance && (
          <div className="banner info" style={{ marginBottom: 12, alignItems: 'flex-start' }}>
            <Icon name="shield" size={15} />
            <div style={{ width: '100%' }}>
              <div>
                <strong>Procedencia del dataset</strong>{' '}
                <span className="mono">{provenance.id.slice(0, 12)}…</span>{' '}
                <span className="muted">
                  · {provenance.kind === 'csv' ? 'CSV' : 'sintético'}
                  {provenance.selection === 'start_date' && provenance.requested_start
                    ? ` · desde ${provenance.requested_start}`
                    : ` · ${provenance.sessions?.count ?? 0} sesiones`}
                </span>
              </div>
              <div className="muted" style={{ marginTop: 3 }}>
                {provenance.file_name || provenance.path || provenance.generator || '—'}
                {' · '}{provenance.sessions?.count ?? 0}/{provenance.sessions?.available ?? 0} sesiones
                {provenance.selected_range?.first_et && provenance.selected_range?.last_et
                  ? ` · ${provenance.selected_range.first_et} → ${provenance.selected_range.last_et}`
                  : ''}
                {' · '}{contractText}
                {provenance.series_mode ? ` · serie ${provenance.series_mode === 'adjusted' ? 'ajustada' : 'raw'}` : ''}
                {provenance.roll_sessions?.length ? ` · ${provenance.roll_sessions.length} roll(s)` : ''}
                {provenance.excluded_sessions?.length ? ` · ${provenance.excluded_sessions.length} sesión(es) de roll excluida(s)` : ''}
                {provenance.file_hash ? ` · hash ${provenance.file_hash.slice(0, 10)}…` : ''}
              </div>
            </div>
          </div>
        )}

        {bt && !variants.length && (
          <>
            <div className="grid cols-4" style={{ marginBottom: 12 }}>
              <Metric label="Operaciones" value={bt.metrics.trades} sub={`${bt.metrics.days_traded} sesiones`} />
              <Metric label="Win rate" value={pct(bt.metrics.win_rate, 1)} sub={`${bt.metrics.wins}G / ${bt.metrics.losses}P`} />
              <Metric label="Profit factor" value={bt.metrics.profit_factor === null ? '∞' : num(bt.metrics.profit_factor)} />
              <Metric label="Beneficio neto" value={moneySigned(bt.metrics.net_profit)} tone={bt.metrics.net_profit >= 0 ? 'pos' : 'neg'} />
              <Metric label="Drawdown máx." value={pct(bt.metrics.max_drawdown_pct, 2)} tone="neg" />
              <Metric label="MFE medio" value={`${num(bt.metrics.avg_mfe_r ?? 0)} R`} tone="pos" />
              <Metric label="MAE medio" value={`${num(bt.metrics.avg_mae_r ?? 0)} R`} tone="neg" />
              <Metric label="DD abierto" value={money(-(bt.metrics.max_open_drawdown ?? 0))} tone="neg" />
              <Metric label="Sharpe" value={bt.metrics.sharpe === null ? '—' : num(bt.metrics.sharpe)} />
              <Metric label="Sortino" value={bt.metrics.sortino === null ? '—' : num(bt.metrics.sortino)} />
              <Metric label="Expectativa" value={moneySigned(bt.metrics.expectancy)} tone={bt.metrics.expectancy >= 0 ? 'pos' : 'neg'} />
            </div>
            <div className="grid cols-2">
              <div>
                <div className="section-title">Curva de equity</div>
                <AreaChart points={(bt.equity || []).map((p) => ({ ts: p.ts, value: p.equity }))} height={180} formatValue={(v) => `$${num(v, 0)}`} />
                {backtestPeriod && <div className="chart-period mono">{backtestPeriod}</div>}
              </div>
              <div>
                <div className="section-title">Resultado por sesión</div>
                <BarsChart items={(bt.days_detail || []).map((d) => ({ label: d.date.slice(5), value: d.pnl }))} height={150} showEvery={2} />
              </div>
            </div>
          </>
        )}

        {bt?.diagnostics?.ambiguous_bars && bt.diagnostics.ambiguous_bars.count > 0 && (
          <div className="banner warn" style={{ marginTop: 12, alignItems: 'flex-start' }}>
            <Icon name="alert" size={15} />
            <div style={{ width: '100%' }}>
              <strong>Informe de velas ambiguas: {bt.diagnostics.ambiguous_bars.count}</strong>{' '}
              <span className="muted">Se tocaron SL y TP en la misma vela; se resolvió con SL primero.</span>
              <div className="table-wrap" style={{ marginTop: 8 }}>
                <table className="table">
                  <thead><tr><th>Hora ET</th><th>Dirección</th><th>Open</th><th>SL</th><th>TP</th><th>Gap SL</th><th>Resolución</th></tr></thead>
                  <tbody>
                    {bt.diagnostics.ambiguous_bars.items.slice(0, 12).map((item) => (
                      <tr key={`${item.ts}-${item.trade_id || item.direction}`}>
                        <td className="mono">{dateTimeET(item.ts)}</td>
                        <td>{item.direction === 'long' ? 'Larga' : 'Corta'}</td>
                        <td className="mono">{num(item.open)}</td>
                        <td className="mono neg">{num(item.stop)}</td>
                        <td className="mono pos">{num(item.target)}</td>
                        <td>{item.gap_stop ? 'Sí' : 'No'}</td>
                        <td>Stop Loss primero</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {bt.diagnostics.ambiguous_bars.count > 12 && (
                <div className="muted" style={{ marginTop: 5 }}>Mostrando las primeras 12; el JSON del backtest conserva el informe completo.</div>
              )}
            </div>
          </div>
        )}

        {variants.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr><th>Variante</th><th>Ops.</th><th>Win rate</th><th>PF</th><th>Expectativa</th><th>Neto</th><th>DD máx.</th><th>Amb.</th><th>Sharpe</th><th>Avg R</th><th>Días+</th></tr>
              </thead>
              <tbody>
                {variants.map((v) => (
                  <tr key={v.variant || v.id}>
                    <td className="strong">{v.label}</td>
                    <td>{v.metrics.trades}</td>
                    <td>{pct(v.metrics.win_rate, 1)}</td>
                    <td>{v.metrics.profit_factor === null ? '∞' : num(v.metrics.profit_factor)}</td>
                    <td className={v.metrics.expectancy >= 0 ? 'pos' : 'neg'}>{moneySigned(v.metrics.expectancy)}</td>
                    <td className={v.metrics.net_profit >= 0 ? 'pos' : 'neg'}>{moneySigned(v.metrics.net_profit)}</td>
                    <td className="neg">{pct(v.metrics.max_drawdown_pct, 2)}</td>
                    <td>{v.diagnostics?.ambiguous_bars?.count ?? 0}</td>
                    <td>{v.metrics.sharpe === null ? '—' : num(v.metrics.sharpe)}</td>
                    <td>{num(v.metrics.avg_r)}</td>
                    <td>{v.metrics.winning_days}/{v.metrics.days_traded}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {!bt && !variants.length && !running && (
          <Empty title="Sin backtest ejecutado" text="Ejecuta una simulación para comparar variantes con comisiones y slippage." icon="chart" />
        )}
      </Card>

      <div style={{ marginTop: 12 }}>
        <Card
          title={<><Icon name="stats" size={14} /> Comparación de presets</>}
          sub={
            presetCatalog
              ? `${presetCatalog.count} presets por defecto sobre el mismo dataset. Solo simulación: no altera la configuración activa.`
              : 'Catálogo de presets del backend. Solo simulación: no altera la configuración activa.'
          }
          actions={
            <span className="card-sub">
              {presetComparison
                ? `${presetComparison.comparison.length} presets · ${presetComparison.sessions} sesiones`
                : presetCatalog
                  ? `${presetCatalog.count} presets por defecto`
                  : 'Catálogo no disponible'}
            </span>
          }
        >
          <div className="banner info" style={{ marginBottom: 12 }}>
            <Icon name="shield" size={15} />
            <div>
              <strong>La configuración activa no cambia.</strong>{' '}
              {presetCatalog?.note ??
                'No se pudo cargar el aviso del catálogo; los presets se aplican solo a esta simulación.'}
            </div>
          </div>

          <div className="hstack" style={{ marginBottom: 12 }}>
            <div className="field" style={{ width: 130 }}>
              <label>Sesiones</label>
              <input
                className="input"
                type="number"
                min={3}
                max={250}
                value={presetDays}
                onChange={(e) => setPresetDays(Number(e.target.value) || 20)}
              />
            </div>
            <div className="field" style={{ width: 160 }}>
              <label>Muestra desde (opcional)</label>
              <input
                className="input"
                type="date"
                value={presetStartDate}
                onChange={(e) => setPresetStartDate(e.target.value)}
              />
            </div>
            <button className="btn primary" disabled={presetRunning} onClick={runPresetComparison}>
              <Icon name="stats" size={13} /> {presetRunning ? 'Comparando…' : 'Comparar presets'}
            </button>
            {presetComparison?.sample.status === 'no_trades' && activeWindowCandidates.length > 0 && (
              <button
                className="btn"
                disabled={presetSearching || presetRunning}
                onClick={searchActiveWindow}
                title="Prueba ventanas anteriores de 3 sesiones solo cuando pulses este botón"
              >
                <Icon name="search" size={13} />{' '}
                {presetSearching ? 'Buscando ventana…' : 'Buscar ventana con actividad'}
              </button>
            )}
            {presetRunning && <span className="spinner" style={{ width: 16, height: 16 }} />}
            <span className="muted" style={{ fontSize: 10.5 }}>
              {presetCatalog
                ? `Baseline + ${Math.max(presetCatalog.count - 1, 0)} ${
                    presetCatalog.count - 1 === 1 ? 'variante' : 'variantes'
                  }`
                : 'Catálogo no disponible'}
            </span>
          </div>

          {presetComparison?.sample.status === 'no_trades' && (
            <div className="muted" style={{ marginBottom: 8, fontSize: 10.5 }}>
              {activeWindowCandidates.length
                ? `La búsqueda no se ejecuta sola: probará hasta ${activeWindowCandidates.length} ventana(s) anteriores de 3 sesiones al pulsar el botón.`
                : 'No hay ventanas anteriores de 3 sesiones en este dataset para buscar.'}
            </div>
          )}

          {presetSearchMessage && (
            <div className="banner info" style={{ marginBottom: 12 }} data-search-message>
              <Icon name="search" size={14} />
              <div>{presetSearchMessage}</div>
            </div>
          )}

          {presetCatalog && (
            <div className="muted" style={{ marginBottom: 8, fontSize: 10.5, lineHeight: 1.6 }}>
              <strong>{presetCatalog.total} presets</strong> en el catálogo ·{' '}
              <strong>{presetCatalog.count} por defecto</strong>
              {defaultPresets.length
                ? `: ${defaultPresets.map((preset) => preset.label).join(' · ')}`
                : ''}
            </div>
          )}

          {presetError && (
            <div className="banner danger" style={{ marginBottom: 12 }}>
              <Icon name="alert" size={14} />
              <div>{presetError}</div>
            </div>
          )}

          {presetComparison && presetStale && (
            <div className="banner warn" style={{ marginBottom: 12 }}>
              <Icon name="alert" size={14} />
              <div>
                <strong>Resultado obsoleto.</strong> Cambiaste la fecha o las sesiones desde esta
                comparación. Vuelve a comparar para actualizar la tabla.
              </div>
            </div>
          )}

          {presetSample && (
            <div
              className={`banner ${presetSample.status === 'activity' ? 'success' : 'warn'}`}
              style={{ marginBottom: 12 }}
              data-sample-status={presetSample.status}
            >
              <Icon name={presetSample.status === 'activity' ? 'shield' : 'alert'} size={15} />
              <div>
                <strong>{SAMPLE_TITLES[presetSample.status] ?? presetSample.status}.</strong>{' '}
                {presetSample.detail}
              </div>
            </div>
          )}

          {presetComparison?.is_synthetic && (
            <div className="banner warn" style={{ marginBottom: 12 }}>
              <Icon name="alert" size={14} />
              <div>
                Resultado sobre <strong>datos sintéticos</strong> generados por el simulador. No representa
                historia real del MNQ ni sirve para estimar rentabilidad.
              </div>
            </div>
          )}

          {!presetComparison && catalogOrigin && (
            <div className="muted" style={{ marginBottom: 8, fontSize: 10.5 }}>
              <strong>Procedencia de la muestra configurada:</strong> {catalogOrigin}
            </div>
          )}

          {presetComparison && (
            <>
              <div className="muted" style={{ marginBottom: 8, fontSize: 10.5 }}>
                <strong>Procedencia de la muestra:</strong>{' '}
                {presetComparison.sessions} sesiones · {presetComparison.data_source === 'csv' ? 'CSV real' : 'sintético'}
                {presetDataset?.file_name
                  ? ` · ${presetDataset.file_name}`
                  : presetDataset?.path
                    ? ` · ${presetDataset.path}`
                    : ''}
                {presetRange && presetRange.first_et && presetRange.last_et
                  ? ` · ${presetRange.first_et} → ${presetRange.last_et}`
                  : ''}
              </div>

              <div className="table-wrap" style={presetStale ? { opacity: 0.55 } : undefined}>
                <table className="table">
                  <thead>
                    <tr>
                      <th>Preset</th>
                      <th className="right">Ops.</th>
                      <th className="right">Señales</th>
                      <th className="right">WR</th>
                      <th className="right">PF</th>
                      <th className="right">Expectativa</th>
                      <th className="right">Neto</th>
                      <th className="right">DD</th>
                      <th className="right">SL</th>
                      <th className="right">ST ticks</th>
                      <th className="right">Caps</th>
                      <th className="right">Qty0</th>
                    </tr>
                  </thead>
                  <tbody>
                    {presetComparison.comparison.map((row) => (
                      <tr key={row.preset} title={row.description}>
                        <td>
                          <strong>{row.label}</strong>
                          <div className="card-sub mono">{row.preset}</div>
                        </td>
                        <td className="right">{row.trades}</td>
                        <td className="right">{row.signals}</td>
                        <td className="right">{pct(row.win_rate, 1)}</td>
                        <td className="right">
                          {row.trades === 0 ? '—' : row.profit_factor === null ? '∞' : num(row.profit_factor)}
                        </td>
                        <td className={`right ${row.expectancy >= 0 ? 'pos' : 'neg'}`}>
                          {moneySigned(row.expectancy)}
                        </td>
                        <td className={`right ${row.net_profit >= 0 ? 'pos' : 'neg'}`}>
                          {moneySigned(row.net_profit)}
                        </td>
                        <td className="right neg">{money(row.max_drawdown)}</td>
                        <td className="right">{row.stop_losses}</td>
                        <td className="right">{num(row.avg_stop_ticks, 1)}</td>
                        <td className="right">{row.stop_cap_sessions}</td>
                        <td className="right">{row.qty_zero_sessions}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <div className="muted" style={{ marginTop: 8, fontSize: 10.5, lineHeight: 1.5 }}>
                Mismas métricas que el CLI. <strong>Caps</strong>: sesiones con al menos un rechazo por
                stop &gt; <code>max_sl_ticks</code>; <strong>Qty0</strong>: sesiones sin contratos por sizing.
                No son operaciones.
              </div>
            </>
          )}

          {!presetComparison && !presetRunning && (
            <Empty
              title="Sin comparación de presets"
              text={
                presetCatalog
                  ? `Ejecuta la comparación para ver los ${presetCatalog.count} presets default sobre el mismo dataset, sin tocar la configuración activa.`
                  : 'Ejecuta la comparación para ver los presets default sobre el mismo dataset, sin tocar la configuración activa.'
              }
              icon="stats"
            />
          )}
        </Card>
      </div>
    </div>
  );
}
