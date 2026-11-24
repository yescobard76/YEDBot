import React from 'react';
import { Icon, IconName } from '../icons';
import { PageKey } from '../App';
import { useApp } from '../store';

const NAV: Array<{ key: PageKey; label: string; icon: IconName }> = [
  { key: 'inicio', label: 'Inicio', icon: 'dashboard' },
  { key: 'grafico', label: 'Gráfico', icon: 'chart' },
  { key: 'operaciones', label: 'Operaciones', icon: 'trades' },
  { key: 'historial', label: 'Historial', icon: 'history' },
  { key: 'estadisticas', label: 'Estadísticas', icon: 'stats' },
  { key: 'configuracion', label: 'Configuración', icon: 'config' },
  { key: 'consola', label: 'Consola', icon: 'console' },
];

export default function Sidebar({ page, onNavigate }: { page: PageKey; onNavigate: (p: PageKey) => void }) {
  const { snap, wsState } = useApp();
  const running = snap?.status === 'running';
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">YED</div>
        <div className="brand-name">Terminal</div>
      </div>
      <nav className="nav">
        {NAV.map((item) => (
          <button
            key={item.key}
            className={`nav-item ${page === item.key ? 'active' : ''}`}
            onClick={() => onNavigate(item.key)}
            title={item.label}
          >
            <Icon name={item.icon} size={18} />
            <span className="nav-label">{item.label}</span>
          </button>
        ))}
      </nav>
      <div className="sidebar-foot">
        <span className={`dot ${running ? 'green pulse' : 'red'}`} title={running ? 'Motor en marcha' : 'Motor detenido'} />
        <span className={`dot ${wsState === 'open' ? 'green' : 'amber'}`} title={`WebSocket: ${wsState}`} />
        <span className="sidebar-version">v1.0</span>
      </div>
    </aside>
  );
}
