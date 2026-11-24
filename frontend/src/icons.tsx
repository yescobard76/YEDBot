import React from 'react';

const paths: Record<string, React.ReactNode> = {
  dashboard: (
    <>
      <rect x="3" y="3" width="7" height="8" rx="1.6" />
      <rect x="14" y="3" width="7" height="5" rx="1.6" />
      <rect x="3" y="15" width="7" height="6" rx="1.6" />
      <rect x="14" y="12" width="7" height="9" rx="1.6" />
    </>
  ),
  chart: (
    <>
      <path d="M3 3v18h18" />
      <path d="M6 15l3.5-4 3 2.5L20 6" />
      <path d="M16.5 6H20v3.5" />
    </>
  ),
  trades: (
    <>
      <path d="M4 6h16M4 12h16M4 18h10" />
      <circle cx="18.5" cy="18" r="2.2" />
    </>
  ),
  history: (
    <>
      <path d="M3 12a9 9 0 1 0 3-6.7" />
      <path d="M3 4v5h5" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  stats: (
    <>
      <path d="M21 12a9 9 0 1 1-9-9v9z" />
      <path d="M12 3a9 9 0 0 1 9 9h-9z" opacity=".45" />
    </>
  ),
  config: (
    <>
      <path d="M4 7h10M18 7h2M4 17h4M12 17h8" />
      <circle cx="16" cy="7" r="2.2" />
      <circle cx="9" cy="17" r="2.2" />
    </>
  ),
  console: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M7 9l3 3-3 3M12.5 15H17" />
    </>
  ),
  play: <path d="M8 5l11 7-11 7z" />,
  pause: (
    <>
      <rect x="7" y="5" width="3.5" height="14" rx="1" />
      <rect x="13.5" y="5" width="3.5" height="14" rx="1" />
    </>
  ),
  stop: <rect x="6" y="6" width="12" height="12" rx="2" />,
  close: <path d="M6 6l12 12M18 6L6 18" />,
  check: <path d="M5 12l5 5L20 7" />,
  x: <path d="M6 6l12 12M18 6L6 18" />,
  alert: (
    <>
      <path d="M12 3l9.5 17H2.5z" />
      <path d="M12 9v5M12 17.2v.2" />
    </>
  ),
  shield: (
    <>
      <path d="M12 3l7 3v6c0 4.4-3 7.5-7 9-4-1.5-7-4.6-7-9V6z" />
      <path d="M9 12l2 2 4-4" />
    </>
  ),
  download: (
    <>
      <path d="M12 3v12M7 11l5 5 5-5" />
      <path d="M4 20h16" />
    </>
  ),
  refresh: (
    <>
      <path d="M20 11a8 8 0 1 0-2.3 6.3" />
      <path d="M20 4v7h-7" />
    </>
  ),
  arrowUp: <path d="M12 20V5M5 12l7-7 7 7" />,
  arrowDown: <path d="M12 4v15M5 12l7 7 7-7" />,
  wifi: (
    <>
      <path d="M2.5 9a15 15 0 0 1 19 0" />
      <path d="M6 12.5a10 10 0 0 1 12 0" />
      <path d="M9.5 16a5 5 0 0 1 5 0" />
      <circle cx="12" cy="19.5" r="1" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </>
  ),
  lock: (
    <>
      <rect x="4" y="10" width="16" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  chevronLeft: <path d="M15 6l-6 6 6 6" />,
  chevronRight: <path d="M9 6l6 6-6 6" />,
  search: (
    <>
      <circle cx="11" cy="11" r="7" />
      <path d="M16.5 16.5L21 21" />
    </>
  ),
  external: (
    <>
      <path d="M14 4h6v6" />
      <path d="M20 4l-9 9" />
      <path d="M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" />
    </>
  ),
};

export type IconName = keyof typeof paths;

export function Icon({ name, size = 17, strokeWidth = 1.7, className }: { name: IconName; size?: number; strokeWidth?: number; className?: string }) {
  const filled = ['play', 'stop', 'pause'].includes(name);
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? 'currentColor' : 'none'}
      stroke={filled ? 'none' : 'currentColor'}
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={className}
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
