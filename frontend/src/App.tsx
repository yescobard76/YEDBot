import React, { useState } from 'react';
import Sidebar from './components/Sidebar';
import TopBar from './components/TopBar';
import { useApp } from './store';
import { Icon } from './icons';
import Dashboard from './pages/Dashboard';
import ChartPage from './pages/ChartPage';
import TradesPage from './pages/TradesPage';
import HistoryPage from './pages/HistoryPage';
import StatsPage from './pages/StatsPage';
import ConfigPage from './pages/ConfigPage';
import ConsolePage from './pages/ConsolePage';
import { Loading } from './components/ui';

export type PageKey = 'inicio' | 'grafico' | 'operaciones' | 'historial' | 'estadisticas' | 'configuracion' | 'consola';

const PAGES: Record<PageKey, React.ComponentType> = {
  inicio: Dashboard,
  grafico: ChartPage,
  operaciones: TradesPage,
  historial: HistoryPage,
  estadisticas: StatsPage,
  configuracion: ConfigPage,
  consola: ConsolePage,
};

export default function App() {
  const [page, setPage] = useState<PageKey>('inicio');
  const { snap, toast, dismissToast } = useApp();

  if (!snap) return <Loading />;
  const Page = PAGES[page];
  const emergency = snap.risk.emergency;

  return (
    <div className="app">
      <Sidebar page={page} onNavigate={setPage} />
      <div className="main">
        <TopBar />
        {snap.mode === 'live' && (
          <div className="banner danger" style={{ margin: '10px 16px 0', borderRadius: 8 }}>
            <Icon name="alert" size={15} />
            <div>
              <strong>MODO LIVE — DINERO REAL.</strong> Cada orden se envía al broker configurado. Verifica límites de riesgo y
              que el adaptador esté validado. Este proyecto no garantiza resultados.
            </div>
          </div>
        )}
        {emergency && (
          <div className="banner danger" style={{ margin: '10px 16px 0', borderRadius: 8 }}>
            <Icon name="shield" size={15} />
            <div>
              <strong>PARADA DE EMERGENCIA ACTIVA.</strong> {snap.risk.emergency_reason || 'Intervención manual'} — nuevas entradas
              bloqueadas. Desactívala explícitamente desde Operaciones.
            </div>
          </div>
        )}
        <main className="content">
          <Page />
        </main>
      </div>
      {toast && (
        <div className={`toast ${toast.kind}`} onClick={dismissToast}>
          <Icon name={toast.kind === 'error' ? 'alert' : toast.kind === 'success' ? 'check' : 'alert'} size={15} />
          <div>{toast.text}</div>
          <button className="btn ghost icon" style={{ padding: 2, width: 20, height: 20 }} onClick={dismissToast}>
            <Icon name="close" size={12} />
          </button>
        </div>
      )}
    </div>
  );
}
