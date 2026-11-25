import React, { useEffect, useMemo, useState } from 'react';
import { api } from '../api';
import { Icon } from '../icons';
import { useApp } from '../store';
import { useUIMode } from '../mode';
import { Card, Metric } from '../components/ui';
import SimpleTradeRow from '../components/SimpleTradeRow';
import type { Trade } from '../types';
import { moneySigned, pct } from '../utils';

const LIMIT = 50;
const MONTH = new Intl.DateTimeFormat('es-ES', { month: 'long', year: 'numeric', timeZone: 'America/New_York' });

function monthLabel(ts: number): string {
  const label = MONTH.format(new Date(ts * 1000));
  return label.charAt(0).toUpperCase() + label.slice(1);
}

export default function HistorialBasico() {
  const { snap } = useApp();
  const { setMode } = useUIMode();
  const [items, setItems] = useState<Trade[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [more, setMore] = useState(false);

  const cargar = (offset: number) => {
    const first = offset === 0;
    if (first) setLoading(true);
    else setMore(true);
    api
      .trades({ period: 'all', limit: LIMIT, offset })
      .then((res) => {
        setTotal(res.total);
        setItems((prev) => (first ? res.items : [...prev, ...res.items]));
      })
      .catch(() => {
        if (first) {
          setItems([]);
          setTotal(0);
        }
      })
      .finally(() => {
        setLoading(false);
        setMore(false);
      });
  };

  useEffect(() => {
    cargar(0);
  }, []);

  const grupos = useMemo(() => {
    const map = new Map<string, Trade[]>();
    for (const t of items) {
      const key = monthLabel(t.exit_ts);
      const list = map.get(key);
      if (list) list.push(t);
      else map.set(key, [t]);
    }
    return Array.from(map.entries());
  }, [items]);

  const stats = snap?.stats;
  const resumen = useMemo(() => {
    const neto = items.reduce((sum, t) => sum + t.pnl, 0);
    return { neto };
  }, [items]);

  return (
    <div className="basic">
      <div className="basic-head">
        <div>
          <span className="basic-kicker">Modo básico</span>
          <h1 className="page-title">Historial</h1>
          <p className="page-sub">Tus operaciones cerradas, contadas en simple y agrupadas por mes.</p>
        </div>
        <button className="btn ghost sm" onClick={() => setMode('avanzado')}>
          Ver historial detallado
        </button>
      </div>

      <div className="grid cols-3">
        <Card bodyClass="tight">
          <Metric label="Operaciones cerradas" value={stats ? stats.trades : '—'} sub="Desde el inicio de la cuenta" />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Resultado total"
            value={stats ? moneySigned(stats.net_profit) : '—'}
            tone={stats && stats.net_profit > 0 ? 'pos' : stats && stats.net_profit < 0 ? 'neg' : 'neutral'}
            sub={stats ? `Después de comisiones` : undefined}
          />
        </Card>
        <Card bodyClass="tight">
          <Metric
            label="Aciertos"
            value={stats ? pct(stats.win_rate, 1) : '—'}
            sub={stats ? `${stats.wins} ganadoras · ${stats.losses} perdedoras` : undefined}
          />
        </Card>
      </div>

      <Card
        title="Operaciones una a una"
        actions={<span className="card-sub">{loading ? 'Cargando…' : `${items.length} de ${total}`}</span>}
        noBody
      >
        {loading ? (
          <div className="basic-empty">
            <span className="spinner" />
            <span>Cargando tus operaciones…</span>
          </div>
        ) : grupos.length ? (
          <div className="history-months">
            {grupos.map(([mes, lista]) => {
              const totalMes = lista.reduce((sum, t) => sum + t.pnl, 0);
              return (
                <section className="history-month" key={mes}>
                  <header>
                    <span>{mes}</span>
                    <strong className={totalMes >= 0 ? 'pos' : 'neg'}>
                      {moneySigned(totalMes)} <small>· {lista.length} {lista.length === 1 ? 'op' : 'ops'}</small>
                    </strong>
                  </header>
                  <div className="trade-list">
                    {lista.map((t) => (
                      <SimpleTradeRow key={t.id} trade={t} />
                    ))}
                  </div>
                </section>
              );
            })}
          </div>
        ) : (
          <div className="basic-empty">
            <Icon name="history" size={20} />
            <strong>Sin operaciones todavía</strong>
            <span>El historial se llena cuando el bot cierra operaciones.</span>
          </div>
        )}

        {!loading && items.length < total && (
          <div className="basic-more">
            <button className="btn" disabled={more} onClick={() => cargar(items.length)}>
              {more ? 'Cargando…' : 'Ver más operaciones'}
            </button>
          </div>
        )}
      </Card>

      <div className="basic-summary-line">
        <span>
          En pantalla: <strong className={resumen.neto >= 0 ? 'pos' : 'neg'}>{moneySigned(resumen.neto)}</strong> sobre {items.length} operaciones.
        </span>
        <span className="muted">Los filtros, el detalle técnico y la exportación están en el modo avanzado.</span>
      </div>

      <div className="basic-cta">
        <div>
          <strong>¿Buscas una operación concreta?</strong>
          <span>En avanzado puedes filtrar por fecha, dirección, resultado y tipo de señal, y exportar a CSV.</span>
        </div>
        <button className="btn primary" onClick={() => setMode('avanzado')}>
          <Icon name="stats" size={14} /> Abrir historial avanzado
        </button>
      </div>
    </div>
  );
}
