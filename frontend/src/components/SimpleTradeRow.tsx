import React from 'react';
import type { Trade } from '../types';
import { exitReasonLabel, moneySigned, num } from '../utils';

const SHORT_DATE = new Intl.DateTimeFormat('es-ES', {
  day: '2-digit',
  month: 'short',
  timeZone: 'America/New_York',
});

const LONG_DATE = new Intl.DateTimeFormat('es-ES', {
  day: '2-digit',
  month: 'short',
  year: 'numeric',
  timeZone: 'America/New_York',
});

export default function SimpleTradeRow({ trade, withYear = false }: { trade: Trade; withYear?: boolean }) {
  const date = withYear ? LONG_DATE : SHORT_DATE;
  return (
    <div className="trade-row">
      <span className="trade-row-date">{date.format(new Date(trade.exit_ts * 1000))}</span>
      <span className={`pill direction ${trade.direction === 'long' ? 'success' : 'danger'}`}>
        {trade.direction === 'long' ? 'Compra' : 'Venta'}
      </span>
      <span className="trade-row-exit">
        {exitReasonLabel(trade.exit_reason)}
        {trade.qty > 1 ? ` · ${trade.qty} contratos` : ''}
      </span>
      <span className="trade-row-pnl">
        <strong className={trade.pnl >= 0 ? 'pos' : 'neg'}>{moneySigned(trade.pnl)}</strong>
        <small>{num(trade.r_multiple)} R</small>
      </span>
    </div>
  );
}
