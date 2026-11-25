import React, { createContext, useContext, useState } from 'react';

export type UIMode = 'basico' | 'avanzado';

const STORAGE_KEY = 'yed.ui.mode';

/** Páginas visibles en el modo Básico. El resto solo existe en Avanzado. */
export const BASIC_PAGES = ['inicio', 'operaciones', 'historial'] as const;

type ModeContextValue = {
  mode: UIMode;
  setMode: (mode: UIMode) => void;
};

const ModeContext = createContext<ModeContextValue>({
  mode: 'basico',
  setMode: () => undefined,
});

function readStoredMode(): UIMode {
  try {
    return window.localStorage.getItem(STORAGE_KEY) === 'avanzado' ? 'avanzado' : 'basico';
  } catch {
    return 'basico';
  }
}

export function UIModeProvider({ children }: { children: React.ReactNode }) {
  const [mode, setModeState] = useState<UIMode>(readStoredMode);

  const setMode = (next: UIMode) => {
    setModeState(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch {
      /* almacenamiento no disponible: el modo dura la sesión */
    }
  };

  return <ModeContext.Provider value={{ mode, setMode }}>{children}</ModeContext.Provider>;
}

export function useUIMode() {
  return useContext(ModeContext);
}

export function ModeSwitch({ vertical = false }: { vertical?: boolean }) {
  const { mode, setMode } = useUIMode();
  return (
    <div
      className={`mode-switch ${vertical ? 'vertical' : ''}`}
      role="group"
      aria-label="Nivel de detalle de la interfaz"
    >
      <button
        type="button"
        className={mode === 'basico' ? 'active' : ''}
        aria-pressed={mode === 'basico'}
        title="Solo lo esencial: estado, dinero y operaciones"
        onClick={() => setMode('basico')}
      >
        Básico
      </button>
      <button
        type="button"
        className={mode === 'avanzado' ? 'active' : ''}
        aria-pressed={mode === 'avanzado'}
        title="Gráfico, fases de la estrategia, estadísticas y configuración"
        onClick={() => setMode('avanzado')}
      >
        Avanzado
      </button>
    </div>
  );
}
