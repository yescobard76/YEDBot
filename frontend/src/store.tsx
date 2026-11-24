import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react';
import { api, wsUrl } from './api';
import { EventItem, OHLC, Snapshot } from './types';

interface Toast {
  id: number;
  kind: 'success' | 'error' | 'info';
  text: string;
}

interface AppState {
  snap: Snapshot | null;
  chartHistory: OHLC[];
  events: EventItem[];
  wsState: 'connecting' | 'open' | 'closed';
  error: string | null;
  refresh: () => Promise<void>;
  act: (fn: () => Promise<any>, success?: string) => Promise<boolean>;
  toast: Toast | null;
  dismissToast: () => void;
}

const Ctx = createContext<AppState>({
  snap: null,
  chartHistory: [],
  events: [],
  wsState: 'connecting',
  error: null,
  refresh: async () => {},
  act: async () => false,
  toast: null,
  dismissToast: () => {},
});

export function AppProvider({ children }: { children: React.ReactNode }) {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [chartHistory, setChartHistory] = useState<OHLC[]>([]);
  const [events, setEvents] = useState<EventItem[]>([]);
  const [wsState, setWsState] = useState<'connecting' | 'open' | 'closed'>('connecting');
  const [error, setError] = useState<string | null>(null);
  const [toast, setToast] = useState<Toast | null>(null);
  const toastTimer = useRef<number | null>(null);

  const mergeEvents = useCallback((incoming: EventItem[]) => {
    if (!incoming.length) return;
    setEvents((prev) => {
      const map = new Map<number, EventItem>();
      [...incoming, ...prev].forEach((e) => map.set(e.id, e));
      return Array.from(map.values()).sort((a, b) => b.id - a.id).slice(0, 400);
    });
  }, []);

  const refresh = useCallback(async () => {
    try {
      const data = (await api.status()) as Snapshot;
      setSnap(data);
      mergeEvents(data.events || []);
      setError(null);
    } catch (e: any) {
      setError(e?.message || 'No se pudo contactar con el motor');
    }
  }, [mergeEvents]);

  useEffect(() => {
    refresh();
    let socket: WebSocket | null = null;
    let retry: number | null = null;
    let poll: number | null = null;
    let closedByUs = false;

    const connect = () => {
      setWsState('connecting');
      try {
        socket = new WebSocket(wsUrl());
      } catch {
        setWsState('closed');
        retry = window.setTimeout(connect, 3000);
        return;
      }
      socket.onopen = () => {
        setWsState('open');
        setError(null);
      };
      socket.onmessage = (msg) => {
        try {
          const payload = JSON.parse(msg.data);
          if (payload.type === 'snapshot') {
            setSnap(payload.data);
            mergeEvents(payload.data.events || []);
          } else if (payload.type === 'event') {
            mergeEvents([payload.data]);
          }
        } catch {
          /* mensaje no válido */
        }
      };
      socket.onclose = () => {
        setWsState('closed');
        if (!closedByUs) retry = window.setTimeout(connect, 2500);
      };
      socket.onerror = () => socket?.close();
    };

    connect();
    poll = window.setInterval(() => {
      if (!socket || socket.readyState !== WebSocket.OPEN) refresh();
    }, 5000);

    return () => {
      closedByUs = true;
      if (retry) window.clearTimeout(retry);
      if (poll) window.clearInterval(poll);
      socket?.close();
    };
  }, [refresh, mergeEvents]);

  const sessionDate = snap?.session.date;
  useEffect(() => {
    // Un reinicio de estadísticas deja el motor sin sesión y con el feed
    // rebobinado. Hay que soltar también las velas cacheadas en el navegador;
    // si no, el gráfico seguiría mostrando el tramo anterior.
    if (!sessionDate) {
      setChartHistory([]);
      return;
    }
    let alive = true;
    api
      .chartHistory(6000)
      .then((data) => {
        if (alive) setChartHistory(data.bars || []);
      })
      .catch(() => {
        /* Si el endpoint no está disponible, el gráfico usa la sesión actual. */
      });
    return () => {
      alive = false;
    };
  }, [sessionDate, wsState]);

  const showToast = useCallback((kind: Toast['kind'], text: string) => {
    setToast({ id: Date.now(), kind, text });
    if (toastTimer.current) window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(null), 6500);
  }, []);

  const act = useCallback(
    async (fn: () => Promise<any>, success?: string) => {
      try {
        const res = await fn();
        showToast('success', res?.message || success || 'Acción completada');
        await refresh();
        return true;
      } catch (e: any) {
        showToast('error', e?.message || 'La acción falló');
        return false;
      }
    },
    [refresh, showToast],
  );

  return (
    <Ctx.Provider
      value={{
        snap,
        chartHistory,
        events,
        wsState,
        error,
        refresh,
        act,
        toast,
        dismissToast: () => setToast(null),
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useApp() {
  return useContext(Ctx);
}
