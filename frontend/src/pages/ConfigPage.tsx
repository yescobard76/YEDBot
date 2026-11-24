import React, { useEffect, useState } from 'react';
import { api } from '../api';
import { Card, Modal, Pill, Toggle } from '../components/ui';
import { Icon } from '../icons';
import { useApp } from '../store';

type Tab = 'estrategia' | 'riesgo' | 'horarios' | 'instrumentos' | 'avanzado';

function Num({
  label,
  value,
  onChange,
  hint,
  step = 1,
  min,
  max,
}: {
  label: string;
  value: any;
  onChange: (v: number) => void;
  hint?: string;
  step?: number;
  min?: number;
  max?: number;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <input
        className="input"
        type="number"
        value={value ?? 0}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(e.target.value === '' ? 0 : Number(e.target.value))}
      />
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

function Text({ label, value, onChange, hint, placeholder }: { label: string; value: any; onChange: (v: string) => void; hint?: string; placeholder?: string }) {
  return (
    <div className="field">
      <label>{label}</label>
      <input className="input" value={value ?? ''} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

function Time({ label, value, onChange, hint }: { label: string; value: any; onChange: (v: string) => void; hint?: string }) {
  return (
    <div className="field">
      <label>{label}</label>
      <input className="input" type="time" value={value ?? ''} onChange={(e) => onChange(e.target.value)} />
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

function Select({
  label,
  value,
  options,
  onChange,
  hint,
}: {
  label: string;
  value: any;
  options: Array<{ value: string; label: string }>;
  onChange: (v: string) => void;
  hint?: string;
}) {
  return (
    <div className="field">
      <label>{label}</label>
      <select className="select" value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
      {hint && <span className="hint">{hint}</span>}
    </div>
  );
}

export default function ConfigPage() {
  const { snap, act } = useApp();
  const [settings, setSettings] = useState<any>(null);
  const [tab, setTab] = useState<Tab>('estrategia');
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [forceNeeded, setForceNeeded] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [statsResetOpen, setStatsResetOpen] = useState(false);
  const [resettingStats, setResettingStats] = useState(false);
  const [deleteBacktests, setDeleteBacktests] = useState(false);
  const [confirmDeleteBacktests, setConfirmDeleteBacktests] = useState(false);
  const [archiveBackup, setArchiveBackup] = useState(true);
  const [statsPreview, setStatsPreview] = useState<any | null>(null);
  const [statsPreviewError, setStatsPreviewError] = useState<string | null>(null);
  const [csvReport, setCsvReport] = useState<any>(null);
  const [csvError, setCsvError] = useState<string | null>(null);
  const [csvChecking, setCsvChecking] = useState(false);

  useEffect(() => {
    api.config().then((res) => setSettings(res.settings)).catch((e) => setError(e.message));
  }, []);

  useEffect(() => {
    if (!statsResetOpen) return;
    let cancelled = false;
    setStatsPreview(null);
    setStatsPreviewError(null);
    api
      .previewResetStats(deleteBacktests, archiveBackup)
      .then((preview) => {
        if (!cancelled) setStatsPreview(preview);
      })
      .catch((e) => {
        if (!cancelled) setStatsPreviewError(e?.message || 'No se pudieron calcular los conteos');
      });
    return () => {
      cancelled = true;
    };
  }, [statsResetOpen, deleteBacktests, archiveBackup]);

  if (!settings) return null;

  const set = (section: string, key: string, value: any) => {
    setSettings((prev: any) => ({ ...prev, [section]: { ...prev[section], [key]: value } }));
    setDirty(true);
    setMessage(null);
  };
  const setTop = (key: string, value: any) => {
    setSettings((prev: any) => ({ ...prev, [key]: value }));
    setDirty(true);
    setMessage(null);
  };

  const save = async (force = false) => {
    setSaving(true);
    setError(null);
    setMessage(null);
    try {
      const res = await api.saveConfig(settings, force);
      setSettings(res.settings);
      setDirty(false);
      setForceNeeded(false);
      setMessage(res.message || 'Configuración guardada');
    } catch (e: any) {
      setError(e.message || 'No se pudo guardar');
      if (String(e.message || '').toLowerCase().includes('posición abierta')) setForceNeeded(true);
    } finally {
      setSaving(false);
    }
  };

  const checkCsv = async () => {
    setCsvChecking(true);
    setCsvError(null);
    setCsvReport(null);
    try {
      setCsvReport(
        await api.validateCsv(
          settings.feed.csv_path,
          settings.feed.series_mode || 'adjusted',
          settings.feed.exclude_roll_sessions !== false,
        ),
      );
    } catch (e: any) {
      setCsvError(e?.message || 'No se pudo validar el CSV');
    } finally {
      setCsvChecking(false);
    }
  };

  const doReset = async () => {
    setResetOpen(false);
    await act(async () => {
      const res = await api.resetConfig();
      setSettings(res.settings);
      setDirty(false);
      return res;
    });
  };

  const openStatsReset = () => {
    setDeleteBacktests(false);
    setConfirmDeleteBacktests(false);
    setArchiveBackup(true);
    setStatsPreview(null);
    setStatsPreviewError(null);
    setStatsResetOpen(true);
  };

  const doResetStats = async () => {
    if (deleteBacktests && !confirmDeleteBacktests) return;
    setStatsResetOpen(false);
    setResettingStats(true);
    setError(null);
    try {
      const res = await api.resetStats(deleteBacktests, {
        confirmDeleteBacktests,
        archive: archiveBackup,
      });
      const suffix = res.archive_path ? ` · copia previa en ${res.archive_path}` : '';
      setMessage((res.message || 'Estadísticas reiniciadas') + suffix);
      await act(async () => res, res.message);
    } catch (e: any) {
      setError(e?.message || 'No se pudieron reiniciar las estadísticas');
    } finally {
      setResettingStats(false);
    }
  };

  const liveConfigured =
    settings.live.broker !== 'none' &&
    settings.live.live_enabled &&
    String(settings.live.live_confirmation || '').trim().toUpperCase() === 'HABILITAR LIVE';
  // Un backend todavía no reiniciado no devuelve el campo nuevo; en ese caso
  // no se muestra una opción que ese proceso no sabría validar.
  const supportsRetrace = settings.strategy?.or_retracement_pct !== undefined;
  const exclusionEnabled = Boolean(
    settings.risk.entry_exclusion_start && settings.risk.entry_exclusion_end,
  );

  return (
    <div>
      <div className="page-head">
        <div>
          <h1 className="page-title">Configuración</h1>
          <p className="page-sub">Parámetros de estrategia, riesgo, horarios, instrumentos y modo de ejecución.</p>
        </div>
        <div className="page-actions">
          {dirty ? <Pill tone="warn" dot>Cambios sin guardar</Pill> : <Pill tone="muted">Sin cambios</Pill>}
          <button className="btn" onClick={() => setResetOpen(true)}><Icon name="refresh" size={13} /> Restaurar valores</button>
          <button
            className="btn"
            onClick={openStatsReset}
            disabled={resettingStats || !!snap?.position}
            title="Reinicia operaciones, equidad y eventos; permite conservar o borrar los backtests"
          >
            <Icon name="refresh" size={13} /> {resettingStats ? 'Reiniciando…' : 'Reiniciar estadísticas'}
          </button>
          <button className="btn primary" onClick={() => save(false)} disabled={saving || !dirty}>
            <Icon name="check" size={13} /> {saving ? 'Guardando…' : 'Guardar cambios'}
          </button>
        </div>
      </div>

      {message && <div className="banner success" style={{ marginBottom: 12 }}><Icon name="check" size={15} /><div>{message}</div></div>}
      {error && (
        <div className="banner danger" style={{ marginBottom: 12 }}>
          <Icon name="alert" size={15} />
          <div>
            {error}
            {forceNeeded && (
              <div style={{ marginTop: 8 }}>
                <button className="btn danger sm" onClick={() => save(true)}>Forzar guardado (aplica a la operación en curso)</button>
              </div>
            )}
          </div>
        </div>
      )}

      <Card noBody>
        <div className="tab-row">
          {[
            ['estrategia', 'Estrategia'],
            ['riesgo', 'Riesgo'],
            ['horarios', 'Horarios'],
            ['instrumentos', 'Instrumentos'],
            ['avanzado', 'Avanzado'],
          ].map(([key, label]) => (
            <button key={key} className={`tab ${tab === key ? 'active' : ''}`} onClick={() => setTab(key as Tab)}>{label}</button>
          ))}
        </div>

        <div style={{ padding: 16 }}>
          {tab === 'estrategia' && (
            <div className="vstack" style={{ gap: 18 }}>
              <div>
                <div className="section-title">Ruptura y entrada</div>
                <div className="form-grid cols-3">
                  <Select label="Temporalidad de confirmación" value={settings.strategy.confirm_tf}
                    options={[{ value: '1m', label: '1 minuto' }, { value: '5m', label: '5 minutos' }, { value: '15m', label: '15 minutos' }, { value: '30m', label: '30 minutos' }]}
                    onChange={(v) => set('strategy', 'confirm_tf', v)} hint="La ruptura se evalúa al cierre de esta vela." />
                  <Num label="Colchón de ruptura (ticks)" value={settings.strategy.breakout_buffer_ticks} onChange={(v) => set('strategy', 'breakout_buffer_ticks', v)} min={0} hint="Margen mínimo más allá del ORH/ORL." />
                  <Num label="Rango mínimo (ticks)" value={settings.strategy.min_range_ticks} onChange={(v) => set('strategy', 'min_range_ticks', v)} min={0} hint="Descarta Opening Ranges degenerados." />
                  <Num label="Validez del setup (min)" value={settings.strategy.setup_validity_minutes} onChange={(v) => set('strategy', 'setup_validity_minutes', v)} min={15} />
                  <Select label="Referencia de entrada" value={settings.strategy.entry_reference}
                    options={[
                      { value: 'or_mid', label: '50% del Opening Range' },
                      ...(supportsRetrace ? [{ value: 'or_retracement', label: 'Retroceso superficial (30–38.2%)' }] : []),
                      { value: 'breakout_level', label: 'Nivel de ruptura' },
                      { value: 'half_leg', label: '50% de la pierna' },
                      { value: 'none', label: 'Entrada directa (sin retesteo)' },
                    ]}
                    onChange={(v) => set('strategy', 'entry_reference', v)}
                    hint="Mid = (OR High + OR Low) / 2. Ver docs/ESTRATEGIA.md." />
                  {supportsRetrace && settings.strategy.entry_reference === 'or_retracement' && (
                    <Num label="Retroceso del Opening Range (%)" value={Math.round((settings.strategy.or_retracement_pct ?? 0.382) * 1000) / 10}
                      onChange={(v) => set('strategy', 'or_retracement_pct', v / 100)} min={10} max={49} step={0.1}
                      hint="30–38.2% desde ORH/ORL; 50% equivale a or_mid." />
                  )}
                  <Num label="Tolerancia de retesteo (ticks)" value={settings.strategy.retest_tolerance_ticks} onChange={(v) => set('strategy', 'retest_tolerance_ticks', v)} min={0} />
                  <Select label="Disparador de entrada" value={settings.strategy.entry_trigger}
                    options={[{ value: 'close', label: 'Cierre de vela' }, { value: 'touch', label: 'Toque del nivel' }]}
                    onChange={(v) => set('strategy', 'entry_trigger', v)} />
                  <Select label="Stop Loss" value={settings.strategy.sl_mode}
                    options={[
                      { value: 'structural', label: 'Estructural (swing confirmado)' },
                      { value: 'or_mid', label: 'Relativo al 50% del rango' },
                      { value: 'atr', label: 'ATR' },
                    ]}
                    onChange={(v) => set('strategy', 'sl_mode', v)} />
                  <Num label="Buffer del SL (ticks)" value={settings.strategy.sl_buffer_ticks} onChange={(v) => set('strategy', 'sl_buffer_ticks', v)} min={0} />
                  <Num label="Profundidad estructural" value={settings.strategy.structural_depth} onChange={(v) => set('strategy', 'structural_depth', v)} min={1} />
                  <Num label="Relación Riesgo/Beneficio" value={settings.strategy.tp_rr} onChange={(v) => set('strategy', 'tp_rr', v)} step={0.1} min={0.5} hint="3.0 = Take Profit a 3R del riesgo real." />
                  <Num label="Periodo ATR" value={settings.strategy.atr_period} onChange={(v) => set('strategy', 'atr_period', v)} min={2} />
                  <Num label="Multiplicador ATR" value={settings.strategy.atr_sl_mult} onChange={(v) => set('strategy', 'atr_sl_mult', v)} step={0.1} />
                </div>
                <div style={{ marginTop: 6 }}>
                  <Toggle label="Exigir cierre de vela para confirmar ruptura" checked={settings.strategy.require_close_breakout} onChange={(v) => set('strategy', 'require_close_breakout', v)} hint="Si se desactiva, una ruptura por mecha también se acepta." />
                  <Toggle label="Exigir cierre de recuperación tras el retesteo" checked={settings.strategy.require_recovery_close} onChange={(v) => set('strategy', 'require_recovery_close', v)} hint="Independiente del disparador: si se desactiva, basta el rechazo dentro de la tolerancia." />
                  <Toggle label="Permitir reentrada tras falso rompimiento" checked={settings.strategy.allow_reentry_after_false_breakout} onChange={(v) => set('strategy', 'allow_reentry_after_false_breakout', v)} />
                </div>
              </div>

              <div>
                <div className="section-title">Divergencia SMT (NQ vs ES)</div>
                <div className="form-grid cols-3">
                  <Select label="Temporalidad de detección" value={settings.smt.detect_tf}
                    options={[{ value: '1m', label: '1 minuto' }, { value: '5m', label: '5 minutos' }, { value: '15m', label: '15 minutos' }]}
                    onChange={(v) => set('smt', 'detect_tf', v)} />
                  <Num label="Profundidad de pivotes" value={settings.smt.pivot_depth} onChange={(v) => set('smt', 'pivot_depth', v)} min={2} hint="Velas a cada lado para confirmar el pivote." />
                  <Num label="Ventana entre movimientos (min)" value={settings.smt.window_minutes} onChange={(v) => set('smt', 'window_minutes', v)} min={5} />
                  <Num label="Tolerancia de precios (ticks)" value={settings.smt.tolerance_ticks} onChange={(v) => set('smt', 'tolerance_ticks', v)} min={0} hint="Cuánto puede penetrar el ES sin invalidar la divergencia." />
                  <Num label="Ruptura mínima (ticks)" value={settings.smt.min_break_ticks} onChange={(v) => set('smt', 'min_break_ticks', v)} min={0} />
                  <Num label="Validez de la divergencia (min)" value={settings.smt.validity_minutes} onChange={(v) => set('smt', 'validity_minutes', v)} min={10} />
                </div>
                <Toggle label="Divergencia SMT activa" checked={settings.smt.enabled} onChange={(v) => set('smt', 'enabled', v)} />
                <Toggle label="Exigir recuperación del nivel barrido" checked={settings.smt.require_recovery} onChange={(v) => set('smt', 'require_recovery', v)} />
              </div>
            </div>
          )}

          {tab === 'riesgo' && (
            <div>
              <div className="section-title">Gestión de riesgo</div>
              <div className="form-grid cols-3">
                <Num label="Capital inicial (USD)" value={settings.risk.initial_capital} onChange={(v) => set('risk', 'initial_capital', v)} min={100} step={100} />
                <Num label="Riesgo por operación (%)" value={settings.risk.risk_per_trade_pct} onChange={(v) => set('risk', 'risk_per_trade_pct', v)} min={0.1} step={0.1} />
                <Num label="Pérdida diaria máxima (%)" value={settings.risk.max_daily_loss_pct} onChange={(v) => set('risk', 'max_daily_loss_pct', v)} min={0.1} step={0.1} />
                <Num label="Objetivo diario (%)" value={settings.risk.max_daily_profit_pct} onChange={(v) => set('risk', 'max_daily_profit_pct', v)} min={0} step={0.1} hint="0 = sin límite de beneficio." />
                <Num label="Máx. operaciones / día" value={settings.risk.max_trades_per_day} onChange={(v) => set('risk', 'max_trades_per_day', v)} min={1} />
                <Num label="Máx. posiciones simultáneas" value={settings.risk.max_concurrent_positions} onChange={(v) => set('risk', 'max_concurrent_positions', v)} min={1} />
                <Num label="Máx. contratos" value={settings.risk.max_contracts} onChange={(v) => set('risk', 'max_contracts', v)} min={1} />
                <Num label="Stop Loss máximo (ticks)" value={settings.risk.max_sl_ticks} onChange={(v) => set('risk', 'max_sl_ticks', v)} min={5} hint="Rechaza señales con stops más amplios." />
                <Num label="Cooldown tras salida (min)" value={settings.risk.cooldown_minutes} onChange={(v) => set('risk', 'cooldown_minutes', v)} min={0} />
                <Num label="Bloqueo tras N pérdidas" value={settings.risk.no_trade_after_consecutive_losses} onChange={(v) => set('risk', 'no_trade_after_consecutive_losses', v)} min={0} hint="0 = desactivado." />
              </div>
              <div className="banner info" style={{ marginTop: 14 }}>
                <Icon name="shield" size={15} />
                <div>
                  El tamaño se calcula con: <strong>(equidad × riesgo %) / (ticks de stop × valor del tick)</strong>, limitado por contratos
                  máximos. Nunca se incrementa el riesgo para recuperar pérdidas.
                </div>
              </div>
            </div>
          )}

          {tab === 'horarios' && (
            <div>
              <div className="section-title">Opening Range (America/New_York)</div>
              <div className="form-grid cols-3">
                <Time label="Inicio del OR" value={settings.orb.start} onChange={(v) => set('orb', 'start', v)} hint="Por defecto 09:00 ET." />
                <Time label="Fin del OR" value={settings.orb.end} onChange={(v) => set('orb', 'end', v)} hint="El rango se congela aquí." />
                <Num label="Amplitud máxima del rango (%)" value={settings.orb.max_width_pct} onChange={(v) => set('orb', 'max_width_pct', v)} step={0.1} hint="Filtro de volatilidad." />
              </div>
              <div className="section-title" style={{ marginTop: 18 }}>Ventana de operación</div>
              <div className="form-grid cols-3">
                <Time label="Inicio permitido" value={settings.risk.trade_window_start} onChange={(v) => set('risk', 'trade_window_start', v)} />
                <Time label="Fin permitido" value={settings.risk.trade_window_end} onChange={(v) => set('risk', 'trade_window_end', v)} />
                <Time label="Cierre forzado de sesión" value={settings.risk.session_close_time} onChange={(v) => set('risk', 'session_close_time', v)} />
              </div>
              <Toggle label="Cerrar posiciones al finalizar la sesión" checked={settings.risk.close_at_session_end} onChange={(v) => set('risk', 'close_at_session_end', v)} hint="Cierra la posición abierta en el horario de cierre configurado." />
              <div className="section-title" style={{ marginTop: 18 }}>Exclusión de entradas (opcional)</div>
              <Toggle
                label="Bloquear nuevas entradas en una franja horaria"
                checked={exclusionEnabled}
                onChange={(v) => {
                  if (v) {
                    set('risk', 'entry_exclusion_start', settings.risk.entry_exclusion_start || '11:00');
                    set('risk', 'entry_exclusion_end', settings.risk.entry_exclusion_end || '13:00');
                  } else {
                    set('risk', 'entry_exclusion_start', '');
                    set('risk', 'entry_exclusion_end', '');
                  }
                }}
                hint="Al activarlo se propone 11:00–13:00 ET. Rango semiabierto [inicio, fin): con 11:00–13:00 se bloquea 11:00:00–12:59:59 y se reanuda a las 13:00:00. Solo afecta entradas nuevas."
              />
              <div className="form-grid cols-3">
                <Time
                  label="Inicio de exclusión"
                  value={settings.risk.entry_exclusion_start}
                  onChange={(v) => set('risk', 'entry_exclusion_start', v)}
                  hint="Incluido en el bloqueo. Vacío = sin exclusión; debe indicarse junto con el fin."
                />
                <Time
                  label="Fin de exclusión"
                  value={settings.risk.entry_exclusion_end}
                  onChange={(v) => set('risk', 'entry_exclusion_end', v)}
                  hint="Excluido del bloqueo: a esta hora ya se permiten entradas. No cierra posiciones abiertas."
                />
              </div>
              <div className="banner info">
                <Icon name="clock" size={15} />
                <div>Los cambios de horario de verano/invierno se resuelven automáticamente con la zona IANA {settings.orb.timezone}, no con offsets fijos.</div>
              </div>
            </div>
          )}

          {tab === 'instrumentos' && (
            <div>
              <div className="section-title">Instrumentos</div>
              <div className="form-grid cols-3">
                <Text label="Instrumento de ejecución" value={settings.instrument} onChange={(v) => setTop('instrument', v.toUpperCase())} hint="MNQ recomendado." />
                <Text label="Referencia Nasdaq" value={settings.reference_symbol} onChange={(v) => setTop('reference_symbol', v.toUpperCase())} />
                <Text label="Comparación (SMT)" value={settings.comparison_symbol} onChange={(v) => setTop('comparison_symbol', v.toUpperCase())} />
                <Num label="Tamaño del tick" value={settings.execution.tick_size} onChange={(v) => set('execution', 'tick_size', v)} step={0.01} />
                <Num label="Valor del tick (USD)" value={settings.execution.tick_value} onChange={(v) => set('execution', 'tick_value', v)} step={0.01} hint="MNQ: 0.25 pts = 0.50 USD." />
                <Num label="Valor del punto (USD)" value={settings.execution.point_value} onChange={(v) => set('execution', 'point_value', v)} step={0.5} hint="MNQ: 2.00 USD por punto." />
                <Num label="Comisión por contrato y lado" value={settings.execution.commission_per_contract_side} onChange={(v) => set('execution', 'commission_per_contract_side', v)} step={0.01} />
                <Num label="Slippage (ticks)" value={settings.execution.slippage_ticks} onChange={(v) => set('execution', 'slippage_ticks', v)} min={0} />
                <Num label="Slippage máximo (ticks)" value={settings.execution.max_slippage_ticks} onChange={(v) => set('execution', 'max_slippage_ticks', v)} min={0} />
                <Select label="Modelo de ejecución" value={settings.execution.fill_model}
                  options={[{ value: 'next_open', label: 'Apertura de la vela siguiente' }, { value: 'signal_price', label: 'Precio de la señal' }]}
                  onChange={(v) => set('execution', 'fill_model', v)} />
                <Num label="Ratio de llenado parcial" value={settings.execution.partial_fill_ratio} onChange={(v) => set('execution', 'partial_fill_ratio', v)} step={0.1} min={0.1} max={1} />
              </div>
              <Toggle label="Simular ejecuciones parciales" checked={settings.execution.simulate_partial_fills} onChange={(v) => set('execution', 'simulate_partial_fills', v)} />
            </div>
          )}

          {tab === 'avanzado' && (
            <div className="vstack" style={{ gap: 18 }}>
              <div>
                <div className="section-title">Modo de ejecución</div>
                <div className="form-grid cols-3">
                  <Select label="Modo" value={settings.mode}
                    options={[{ value: 'paper', label: 'Paper trading' }, { value: 'live', label: 'Live (adaptador pendiente)' }]}
                    onChange={(v) => setTop('mode', v)} hint="LIVE no está disponible: falta el adaptador del broker." />
                  <Select label="Proveedor de datos" value={settings.feed.provider}
                    options={[{ value: 'simulated', label: 'Replay simulado (demo)' }, { value: 'csv', label: 'CSV histórico' }, { value: 'live', label: 'Proveedor en vivo' }]}
                    onChange={(v) => set('feed', 'provider', v)} hint="Cambiar de proveedor reinicia la sesión del motor." />
                  <Num label="Velocidad de replay (velas/s)" value={settings.feed.replay_speed} onChange={(v) => set('feed', 'replay_speed', v)} step={0.5} min={0.1} />
                  <Text label="Ruta del CSV" value={settings.feed.csv_path} onChange={(v) => set('feed', 'csv_path', v)} hint="Columnas: timestamp,symbol,open,high,low,close,volume[,contract][,expiry]" />
                  <Select label="Serie de contratos" value={settings.feed.series_mode || 'adjusted'}
                    options={[{ value: 'adjusted', label: 'Ajustada (continua, recomendada)' }, { value: 'raw', label: 'Raw (precios del proveedor)' }]}
                    onChange={(v) => set('feed', 'series_mode', v)} hint="La serie ajustada desplaza el histórico por el spread de cada roll." />
                  <Text label="Fecha de inicio (YYYY-MM-DD)" value={settings.feed.start_date} onChange={(v) => set('feed', 'start_date', v)} hint="Vacío = inicio del replay: primera sesión del CSV o sesión actual en simulado." />
                  <Num label="Latencia simulada (ms)" value={settings.feed.latency_ms} onChange={(v) => set('feed', 'latency_ms', v)} min={0} />
                </div>
                <Toggle
                  label="Repetir sesiones en bucle (replay)"
                  checked={settings.feed.loop_sessions}
                  onChange={(v) => set('feed', 'loop_sessions', v)}
                  disabled={settings.feed.provider !== 'simulated'}
                  hint={settings.feed.provider === 'simulated' ? undefined : 'Solo aplica al replay simulado; el CSV se reproduce una vez.'}
                />
                <Toggle label="Excluir sesiones de roll" checked={settings.feed.exclude_roll_sessions !== false} onChange={(v) => set('feed', 'exclude_roll_sessions', v)} />
                <div className="hstack" style={{ marginTop: 8 }}>
                  <Pill tone={settings.feed.provider === 'simulated' ? 'warn' : settings.feed.provider === 'csv' ? 'info' : 'success'}>
                    {settings.feed.provider === 'simulated'
                      ? 'Datos simulados: no son mercado real'
                      : settings.feed.provider === 'csv'
                        ? 'Datos históricos reales (CSV)'
                        : 'Datos en vivo'}
                  </Pill>
                </div>
              </div>

              <div>
                <div className="section-title">Validación del CSV histórico</div>
                <div className="banner info">
                  <Icon name="chart" size={15} />
                  <div>
                    Formato: <code>timestamp,symbol,open,high,low,close,volume[,contract][,expiry]</code> · velas de <strong>1 minuto</strong> · una fila
                    por símbolo y minuto. <code>timestamp</code> en ISO-8601 con zona horaria (o epoch en segundos). Las series
                    <strong> MNQ, NQ y ES deben compartir exactamente los mismos timestamps</strong>; el validador rechaza duplicados,
                    OHLC incoherente y desalineaciones. Si declaras contratos, se selecciona el vencimiento más próximo y se
                    excluye la sesión de roll (la última del contrato saliente; configurable arriba).
                  </div>
                </div>
                <div className="hstack" style={{ marginTop: 10, flexWrap: 'wrap' }}>
                  <button className="btn" onClick={checkCsv} disabled={csvChecking}>
                    <Icon name="check" size={13} /> {csvChecking ? 'Validando…' : 'Validar CSV'}
                  </button>
                  <span className="muted" style={{ fontSize: 10.5 }}>
                    Valida la ruta indicada arriba aunque no esté guardada. No arranca ni modifica el motor.
                  </span>
                </div>
                {csvError && (
                  <div className="banner danger" style={{ marginTop: 10 }}>
                    <Icon name="alert" size={15} />
                    <div>{csvError}</div>
                  </div>
                )}
                {csvReport && (
                  <div className={`banner ${csvReport.ok ? 'success' : 'danger'}`} style={{ marginTop: 10, alignItems: 'flex-start' }}>
                    <Icon name={csvReport.ok ? 'check' : 'alert'} size={15} />
                    <div style={{ width: '100%' }}>
                      <strong>{csvReport.ok ? 'CSV válido: series alineadas' : 'CSV rechazado'}</strong>{' '}
                      <span className="muted">{csvReport.path}</span>
                      <div className="kv" style={{ marginTop: 6 }}>
                        <div className="kv-row"><span className="kv-label">Velas comunes</span><span className="kv-value">{csvReport.common_bars}</span></div>
                        <div className="kv-row"><span className="kv-label">Rango temporal</span><span className="kv-value mono">{csvReport.first_et || '—'} → {csvReport.last_et || '—'}</span></div>
                        <div className="kv-row"><span className="kv-label">Series</span><span className="kv-value">{Object.entries(csvReport.counts || {}).map(([s, n]) => `${s}: ${n}`).join(' · ') || '—'}</span></div>
                        {csvReport.dataset_id && (
                          <div className="kv-row"><span className="kv-label">Dataset ID</span><span className="kv-value mono">{String(csvReport.dataset_id).slice(0, 16)}…</span></div>
                        )}
                        {csvReport.contracts && (
                          <div className="kv-row"><span className="kv-label">Contratos</span><span className="kv-value">
                            {Object.entries(csvReport.contracts).flatMap(([s, list]) => (list as string[]).map((c) => `${s}:${c}`)).join(' · ') || 'sin contrato declarado'}
                          </span></div>
                        )}
                        {csvReport.series_mode && (
                          <div className="kv-row"><span className="kv-label">Serie / rolls</span><span className="kv-value">
                            {csvReport.series_mode === 'adjusted' ? 'ajustada' : 'raw'}
                            {' · '}{csvReport.roll_sessions?.length || 0} roll(s)
                            {csvReport.excluded_sessions?.length ? ` · ${csvReport.excluded_sessions.length} excluida(s)` : ''}
                          </span></div>
                        )}
                        <div className="kv-row"><span className="kv-label">Alineado al minuto</span><span className={`kv-value ${csvReport.aligned ? 'pos' : 'neg'}`}>{csvReport.aligned ? 'Sí' : 'No'}</span></div>
                        {csvReport.session_validation && (
                          <div className="kv-row">
                            <span className="kv-label">Sesiones RTH</span>
                            <span className={`kv-value ${csvReport.session_validation.ok ? 'pos' : 'neg'}`}>
                              {csvReport.session_validation.ok
                                ? 'Completas (09:00–16:00 ET)'
                                : `${csvReport.session_validation.invalid_sessions} inválidas`}
                            </span>
                          </div>
                        )}
                        {csvReport.gap_count > 0 && (
                          <div className="kv-row"><span className="kv-label">Huecos</span><span className="kv-value">{csvReport.gap_count} · máx {Math.round((csvReport.max_gap_seconds || 0) / 60)} min</span></div>
                        )}
                      </div>
                      {csvReport.errors?.length > 0 && (
                        <div style={{ marginTop: 6 }} className="neg">{csvReport.errors.join(' · ')}</div>
                      )}
                      {csvReport.warnings?.length > 0 && (
                        <div style={{ marginTop: 6 }} className="muted">{csvReport.warnings.join(' · ')}</div>
                      )}
                    </div>
                  </div>
                )}
              </div>

              <div>
                <div className="section-title">Broker y autorizaciones (solo LIVE)</div>
                <div className="banner info">
                  <Icon name="lock" size={15} />
                  <div>
                    El paper trading no necesita broker, credenciales ni confirmación. Estos campos solo se aplican si se
                    habilita LIVE.
                  </div>
                </div>
                <div className="form-grid cols-3" style={{ marginTop: 10 }}>
                  <Select label="Broker" value={settings.live.broker}
                    options={[{ value: 'none', label: 'Ninguno' }, { value: 'tradovate', label: 'Tradovate' }, { value: 'ibkr', label: 'Interactive Brokers' }, { value: 'rithmic', label: 'Rithmic' }]}
                    onChange={(v) => set('live', 'broker', v)} hint="Solo se usa en LIVE; en paper puede quedar en Ninguno." />
                  <Select label="Entorno" value={settings.live.environment}
                    options={[{ value: 'demo', label: 'Demo / simulación' }, { value: 'live', label: 'Producción' }]}
                    onChange={(v) => set('live', 'environment', v)} />
                  <Text label="Referencia de cuenta" value={settings.live.account_ref} onChange={(v) => set('live', 'account_ref', v)} hint="No introduzcas credenciales aquí: usa variables de entorno." />
                  <Text label="Feed de datos" value={settings.live.data_feed} onChange={(v) => set('live', 'data_feed', v)} hint="Ej. CME data bundle / API del bróker." />
                  <Text label="Confirmación explícita" value={settings.live.live_confirmation} onChange={(v) => set('live', 'live_confirmation', v)} placeholder="HABILITAR LIVE" hint="Solo se exige en LIVE; el paper no requiere confirmación. Escribe exactamente HABILITAR LIVE." />
                </div>
                <Toggle label="Live habilitado" checked={settings.live.live_enabled} onChange={(v) => set('live', 'live_enabled', v)} hint="Solo marca la intención; el adaptador del broker aún no está implementado." />
                <div className={`banner ${settings.mode === 'live' ? 'danger' : 'info'}`} style={{ marginTop: 10 }}>
                  <Icon name={settings.mode === 'live' ? 'alert' : 'lock'} size={15} />
                  <div>
                    {settings.mode === 'live' ? (
                      <>
                        <strong>Modo LIVE seleccionado.</strong> El motor rechazará el arranque porque el adaptador del broker no está
                        implementado. No se envía dinero real.
                      </>
                    ) : (
                      <>
                        En LIVE, las credenciales se leen de variables de entorno (<code>TRADOVATE_*</code>, <code>IBKR_*</code>, <code>RITHMIC_*</code>).
                        Este proyecto no incluye credenciales ni conexiones reales; consulta <code>docs/PROVEEDORES.md</code>.
                      </>
                    )}
                  </div>
                </div>
                <div className="hstack" style={{ marginTop: 10 }}>
                  <Pill tone={settings.live.broker !== 'none' ? 'success' : 'muted'}>{settings.live.broker !== 'none' ? 'Broker definido' : 'Broker sin definir'}</Pill>
                  <Pill tone={settings.live.live_enabled ? 'warn' : 'muted'}>{settings.live.live_enabled ? 'Live armado' : 'Live desarmado'}</Pill>
                  <Pill tone={settings.mode === 'live' ? 'danger' : liveConfigured ? 'warn' : 'muted'}>
                    {liveConfigured ? 'LIVE: adaptador pendiente' : 'LIVE: requisitos incompletos'}
                  </Pill>
                </div>
              </div>

              <div className="banner warn">
                <Icon name="alert" size={15} />
                <div>
                  Guardar cambios de proveedor o de estrategia reinicia el estado de la estrategia de la sesión. Si hay una posición
                  abierta, el backend bloquea los cambios sensibles salvo confirmación forzada.
                </div>
              </div>
            </div>
          )}
        </div>
      </Card>

      <div className="hstack" style={{ justifyContent: 'flex-end', marginTop: 12 }}>
        <span className="muted" style={{ fontSize: 10.5 }}>
          Motor: {snap?.status === 'running' ? 'activo' : snap?.status === 'paused' ? 'pausado' : 'detenido'} · modo {snap?.mode}
        </span>
        <button
          className="btn"
          onClick={openStatsReset}
          disabled={resettingStats || !!snap?.position}
          title="Reinicia operaciones, equidad y eventos; permite conservar o borrar los backtests"
        >
          {resettingStats ? 'Reiniciando…' : 'Reiniciar estadísticas'}
        </button>
        <button className="btn" onClick={() => setResetOpen(true)}>Restaurar por defecto</button>
        <button className="btn primary" onClick={() => save(false)} disabled={saving || !dirty}>Guardar cambios</button>
      </div>

      <Modal
        open={statsResetOpen}
        title="Reiniciar estadísticas"
        onClose={() => setStatsResetOpen(false)}
        footer={
          <>
            <button className="btn ghost" onClick={() => setStatsResetOpen(false)}>Cancelar</button>
            <button
              className="btn danger"
              onClick={doResetStats}
              disabled={
                resettingStats ||
                !!snap?.position ||
                !statsPreview ||
                (deleteBacktests && !confirmDeleteBacktests)
              }
            >
              {resettingStats
                ? 'Reiniciando…'
                : deleteBacktests
                  ? 'Eliminar historial y backtests'
                  : 'Reiniciar y empezar de cero'}
            </button>
          </>
        }
      >
        <p style={{ margin: 0, color: '#9aa9bd', lineHeight: 1.5 }}>
          Se borrarán las operaciones, la curva de equidad y los eventos. La equidad
          volverá al capital inicial configurado; los parámetros no cambian. Los
          backtests guardados se conservan salvo que actives la opción de abajo. Si el
          motor está activo, se detendrá.
        </p>
        <div
          style={{
            marginTop: 14,
            padding: '10px 12px',
            border: '1px solid #243041',
            borderRadius: 8,
            background: '#0d141d',
            color: '#9aa9bd',
            fontSize: 12,
          }}
        >
          <div style={{ marginBottom: 8, color: '#d6deea', fontWeight: 600 }}>
            Conteos antes de borrar
          </div>
          {statsPreview ? (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 } as React.CSSProperties}>
              <span>Operaciones: <strong>{statsPreview.counts.trades}</strong></span>
              <span>Eventos: <strong>{statsPreview.counts.events}</strong></span>
              <span>Equidad: <strong>{statsPreview.counts.equity}</strong></span>
              <span>Estado del motor: <strong>{statsPreview.counts.kv}</strong></span>
              <span>
                Backtests {deleteBacktests ? 'a eliminar' : 'conservados'}:{' '}
                <strong>{statsPreview.counts.backtests}</strong>
              </span>
              <span>
                Copia previa: <strong>{statsPreview.archive ? 'sí' : 'no'}</strong>
              </span>
            </div>
          ) : statsPreviewError ? (
            <div className="banner danger" style={{ margin: 0 }}>
              <Icon name="alert" size={15} />
              <div>{statsPreviewError}</div>
            </div>
          ) : (
            <span>Calculando conteos…</span>
          )}
        </div>
        <div style={{ marginTop: 14 }}>
          <Toggle
            label="Borrar también los backtests guardados"
            checked={deleteBacktests}
            onChange={(v) => {
              setDeleteBacktests(v);
              if (!v) setConfirmDeleteBacktests(false);
            }}
            hint="Desmarcado, los resultados de backtesting se conservan. Esta acción no se puede deshacer."
          />
        </div>
        {deleteBacktests && (
          <div style={{ marginTop: 10 }}>
            <Toggle
              label="Confirmo que quiero eliminar los backtests"
              checked={confirmDeleteBacktests}
              onChange={setConfirmDeleteBacktests}
              hint="La eliminación de backtests exige esta confirmación explícita."
            />
          </div>
        )}
        <div style={{ marginTop: 10 }}>
          <Toggle
            label="Guardar una copia previa de la base"
            checked={archiveBackup}
            onChange={setArchiveBackup}
            hint="Se archiva en backups/ antes de borrar; si el archivo falla, no se borra nada."
          />
        </div>
        {snap?.position && (
          <div className="banner danger" style={{ marginTop: 12 }}>
            <Icon name="alert" size={15} />
            <div>Cierra la posición abierta antes de reiniciar las estadísticas.</div>
          </div>
        )}
      </Modal>

      <Modal
        open={resetOpen}
        title="Restaurar configuración predeterminada"
        onClose={() => setResetOpen(false)}
        footer={
          <>
            <button className="btn ghost" onClick={() => setResetOpen(false)}>Cancelar</button>
            <button className="btn danger" onClick={doReset}>Restaurar todo</button>
          </>
        }
      >
        <p style={{ margin: 0, color: '#9aa9bd', lineHeight: 1.5 }}>
          Se reemplazarán todos los parámetros (estrategia, SMT, riesgo, horarios, ejecución y proveedor) por los valores de fábrica.
          Las operaciones y el historial no se eliminan.
        </p>
      </Modal>
    </div>
  );
}
