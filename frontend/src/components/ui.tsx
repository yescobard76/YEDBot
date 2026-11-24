import React, { useId } from 'react';
import { Icon, IconName } from '../icons';
import { money, num } from '../utils';

export function Card({
  title,
  sub,
  actions,
  children,
  className = '',
  bodyClass = '',
  noBody = false,
}: {
  title?: React.ReactNode;
  sub?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  bodyClass?: string;
  noBody?: boolean;
}) {
  return (
    <section className={`card ${className}`}>
      {(title || actions) && (
        <header className="card-head">
          <div>
            <div className="card-title">{title}</div>
            {sub && <div className="card-sub">{sub}</div>}
          </div>
          {actions && <div className="card-actions">{actions}</div>}
        </header>
      )}
      {noBody ? children : <div className={`card-body ${bodyClass}`}>{children}</div>}
    </section>
  );
}

export function Metric({
  label,
  value,
  sub,
  tone,
  size,
}: {
  label: string;
  value: React.ReactNode;
  sub?: React.ReactNode;
  tone?: 'pos' | 'neg' | 'neutral' | '';
  size?: 'sm' | 'lg';
}) {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className={`metric-value ${size || ''} ${tone || ''}`}>{value}</span>
      {sub !== undefined && <span className="metric-sub">{sub}</span>}
    </div>
  );
}

export function Pill({
  tone = 'muted',
  children,
  dot = false,
  className = '',
}: {
  tone?: 'success' | 'danger' | 'warn' | 'info' | 'muted' | 'purple';
  children: React.ReactNode;
  dot?: boolean;
  className?: string;
}) {
  return (
    <span className={`pill ${tone} ${className}`}>
      {dot && <span className={`dot ${tone === 'success' ? 'green' : tone === 'danger' ? 'red' : tone === 'warn' ? 'amber' : 'blue'}`} />}
      {children}
    </span>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: React.ReactNode;
  hint?: string;
  disabled?: boolean;
}) {
  return (
    <div className="switch-row">
      <div>
        <div className="switch-label">{label}</div>
        {hint && <div className="hint">{hint}</div>}
      </div>
      <label className="switch">
        <input type="checkbox" checked={checked} disabled={disabled} onChange={(e) => onChange(e.target.checked)} />
        <span className="track" />
      </label>
    </div>
  );
}

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
  width,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  width?: number;
}) {
  if (!open) return null;
  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <div className="modal" style={width ? { width: `min(${width}px, 100%)` } : undefined} onMouseDown={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <div className="modal-title">{title}</div>
          <button className="btn ghost icon" onClick={onClose} aria-label="Cerrar">
            <Icon name="close" size={15} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Empty({
  title,
  text,
  icon = 'chart',
}: {
  title: string;
  text?: string;
  icon?: IconName;
}) {
  return (
    <div className="empty">
      <Icon name={icon} size={22} />
      <strong>{title}</strong>
      {text && <span>{text}</span>}
    </div>
  );
}

export function Loading({ text = 'Conectando con el motor…' }: { text?: string }) {
  return (
    <div className="loading-screen">
      <div className="spinner" />
      <span>{text}</span>
    </div>
  );
}

export function AreaChart({
  points,
  height = 120,
  color,
  fill = true,
  formatValue,
}: {
  points: Array<{ ts: number; value: number }>;
  height?: number;
  color?: string;
  fill?: boolean;
  formatValue?: (v: number) => string;
}) {
  const id = useId().replace(/:/g, '');
  if (!points.length) return <Empty title="Sin datos todavía" text="La curva se dibuja con operaciones cerradas." />;
  const values = points.map((p) => p.value);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || Math.abs(max) || 1;
  const upward = points[points.length - 1].value >= points[0].value;
  const stroke = color || (upward ? '#18c37e' : '#f6465d');
  const pad = 6;
  const w = 100;
  const h = 40;
  const coords = points.map((p, i) => {
    const x = points.length === 1 ? w : (i / (points.length - 1)) * w;
    const y = h - pad - ((p.value - min) / span) * (h - pad * 2);
    return [x, y] as const;
  });
  const line = coords.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const area = `${line} L${w},${h} L0,${h} Z`;
  return (
    <div style={{ position: 'relative' }}>
      <svg className="sparkline" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height }}>
        <defs>
          <linearGradient id={`grad-${id}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((ratio) => (
          <line key={ratio} x1="0" y1={h * ratio} x2={w} y2={h * ratio} stroke="rgba(255,255,255,0.045)" strokeWidth="0.35" />
        ))}
        {fill && <path d={area} fill={`url(#grad-${id})`} />}
        <path d={line} fill="none" stroke={stroke} strokeWidth="0.9" vectorEffect="non-scaling-stroke" />
      </svg>
      {formatValue && (
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#637389', marginTop: 4 }}>
          <span>{formatValue(min)}</span>
          <span style={{ color: stroke }}>{formatValue(points[points.length - 1].value)}</span>
        </div>
      )}
    </div>
  );
}

export function BarsChart({
  items,
  height = 140,
  format = (v: number) => money(v, 0, true),
  showEvery = 1,
}: {
  items: Array<{ label: string; value: number }>;
  height?: number;
  format?: (v: number) => string;
  showEvery?: number;
}) {
  if (!items.length) return <Empty title="Sin operaciones en el periodo" />;
  const maxAbs = Math.max(...items.map((i) => Math.abs(i.value)), 1);
  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'flex-end', gap: 3, height, borderBottom: '1px solid #16212d', paddingBottom: 2 }}>
        {items.map((item, idx) => {
          const ratio = Math.abs(item.value) / maxAbs;
          const barHeight = Math.max(2, ratio * (height - 22));
          return (
            <div
              key={`${item.label}-${idx}`}
              title={`${item.label}: ${format(item.value)}`}
              style={{ flex: 1, minWidth: 3, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', height: '100%' }}
            >
              <div
                style={{
                  height: barHeight,
                  background: item.value >= 0 ? 'linear-gradient(180deg,#1fd68c,#0f8f5c)' : 'linear-gradient(180deg,#ff6b7f,#b5293e)',
                  borderRadius: 2,
                  opacity: 0.9,
                }}
              />
            </div>
          );
        })}
      </div>
      <div style={{ display: 'flex', gap: 3, marginTop: 4 }}>
        {items.map((item, idx) => (
          <div key={`lbl-${item.label}-${idx}`} style={{ flex: 1, minWidth: 3, fontSize: 8, color: '#637389', textAlign: 'center', overflow: 'hidden', whiteSpace: 'nowrap' }}>
            {idx % showEvery === 0 ? item.label : ''}
          </div>
        ))}
      </div>
    </div>
  );
}

export function Donut({
  segments,
  size = 132,
  centerLabel,
  centerSub,
}: {
  segments: Array<{ label: string; value: number; color: string }>;
  size?: number;
  centerLabel: string;
  centerSub?: string;
}) {
  const total = segments.reduce((a, s) => a + s.value, 0);
  const radius = 46;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="hstack" style={{ gap: 18 }}>
      <svg width={size} height={size} viewBox="0 0 120 120">
        <circle cx="60" cy="60" r={radius} fill="none" stroke="#131d27" strokeWidth="13" />
        {total > 0 &&
          segments.map((seg) => {
            const fraction = seg.value / total;
            const dash = fraction * circumference;
            const circle = (
              <circle
                key={seg.label}
                cx="60"
                cy="60"
                r={radius}
                fill="none"
                stroke={seg.color}
                strokeWidth="13"
                strokeDasharray={`${dash} ${circumference - dash}`}
                strokeDashoffset={-offset}
                transform="rotate(-90 60 60)"
                strokeLinecap="butt"
              />
            );
            offset += dash;
            return circle;
          })}
        <text x="60" y="57" textAnchor="middle" fill="#e9eff8" fontSize="16" fontWeight="700">
          {centerLabel}
        </text>
        {centerSub && (
          <text x="60" y="72" textAnchor="middle" fill="#637389" fontSize="8.5" letterSpacing="0.5">
            {centerSub}
          </text>
        )}
      </svg>
      <div className="vstack" style={{ gap: 7 }}>
        {segments.map((seg) => (
          <div key={`legend-${seg.label}`} className="legend-item" style={{ fontSize: 10.5, color: '#9aa9bd' }}>
            <span style={{ width: 8, height: 8, borderRadius: 2, background: seg.color, display: 'inline-block' }} />
            <span>{seg.label}</span>
            <strong style={{ color: '#e9eff8', marginLeft: 4 }}>{seg.value}</strong>
            <span style={{ color: '#637389' }}>{total ? `${((seg.value / total) * 100).toFixed(0)}%` : ''}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export function Gauge({
  value,
  max = 100,
  label,
  color = '#18c37e',
  caption,
}: {
  value: number;
  max?: number;
  label: string;
  color?: string;
  caption?: string;
}) {
  const ratio = Math.max(0, Math.min(1, max > 0 ? value / max : 0));
  const r = 52;
  const cx = 66;
  const cy = 66;
  const endX = cx - r * Math.cos(Math.PI * ratio);
  const endY = cy - r * Math.sin(Math.PI * ratio);
  return (
    <div className="gauge-wrap">
      <svg width="120" height="72" viewBox="0 0 132 76">
        <path d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`} fill="none" stroke="#15202b" strokeWidth="10" strokeLinecap="round" />
        {ratio > 0 && (
          <path
            d={`M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${endX} ${endY}`}
            fill="none"
            stroke={color}
            strokeWidth="10"
            strokeLinecap="round"
          />
        )}
        <text x={cx} y={cy - 12} textAnchor="middle" fill="#e9eff8" fontSize="18" fontWeight="700">
          {num(value, 2)}%
        </text>
        <text x={cx} y={cy + 4} textAnchor="middle" fill="#637389" fontSize="8.5" letterSpacing="0.6">
          {label}
        </text>
      </svg>
      {caption && <div className="gauge-meta"><span className="muted" style={{ fontSize: 10.5 }}>{caption}</span></div>}
    </div>
  );
}

export function StatusRow({
  label,
  status,
  detail,
  tone,
}: {
  label: string;
  status: string;
  detail?: string;
  tone: 'green' | 'red' | 'amber' | 'blue';
}) {
  return (
    <div className="status-item">
      <span className={`dot ${tone}`} style={{ marginTop: 5 }} />
      <div className="status-item-main">
        <div className="status-item-title">
          {label} <span className="muted" style={{ fontWeight: 500 }}>· {status}</span>
        </div>
        {detail && <div className="status-item-sub">{detail}</div>}
      </div>
    </div>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div className="section-title">{children}</div>;
}
