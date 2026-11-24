# Arquitectura

## 1. Componentes

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              NAVEGADOR (local)                               │
│  React 18 + TypeScript + Lightweight Charts                                  │
│  Inicio · Gráfico · Operaciones · Historial · Estadísticas · Config · Consola │
└───────────────▲───────────────────────────────┬──────────────────────────────┘
                │ WebSocket /api/ws             │ REST /api/*
                │ snapshots + eventos           │ comandos y consultas
┌───────────────┴───────────────────────────────▼──────────────────────────────┐
│                           FastAPI (server/main.py)                           │
│  API + estáticos de frontend/dist + lifespan del motor                       │
└───────────────┬──────────────────────────────────────────────────────────────┘
                │
┌───────────────▼──────────────────────────────────────────────────────────────┐
│                        TradingEngine (server/engine.py)                      │
│  estado · snapshot · control (start/pause/stop) · emergencia · config        │
│                                                                              │
│  ┌─────────────┐  ┌──────────────┐  ┌───────────────┐  ┌──────────────────┐  │
│  │ MarketFeed  │─►│ ORBStrategy  │─►│ RiskManager   │─►│ ExecutionEngine  │  │
│  │ replay/CSV  │  │ 7 fases      │  │ sizing/límites│  │ fills/SL/TP      │  │
│  └─────────────┘  └──────────────┘  └───────────────┘  └────────┬─────────┘  │
│                                                                  │            │
│  ┌───────────────────────────────┐   ┌───────────────────────────▼─────────┐  │
│  │ EventHub (colas por cliente)  │   │ Store SQLite (WAL)                  │  │
│  └───────────────────────────────┘   │ trades · events · equity · kv        │  │
│                                      │ backtests                          │  │
│                                      └────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────────────┘
```

## 2. Flujo de una vela

1. `MarketFeed.next_tick()` entrega `{MNQ, NQ, ES}` alineados por timestamp.
2. `engine._process` detecta cambio de sesión ET, reinicia estado y registra el evento.
3. `ExecutionEngine.on_bar()` llena la orden pendiente en la apertura y comprueba SL/TP.
4. Si el motor está `running`, `ORBStrategy.evaluate(nq, es)` recalcula el estado de la
   sesión con las velas cerradas y devuelve fases, señal y marcadores.
5. `RiskManager.evaluate()` autoriza o rechaza la señal y dimensiona la posición.
6. La orden se arma y se ejecuta en la vela siguiente; al cerrar se persiste el trade.
7. Se guarda el estado en `kv`, se emite un evento y se difunde el snapshot por WebSocket.

La reconstrucción determinista de la estrategia evita estado oculto y facilita que el
backtest use exactamente las mismas reglas.

## 3. Decisiones técnicas

| Decisión | Motivo |
|---|---|
| **FastAPI + asyncio** | WebSocket y REST en el mismo proceso, tipado con Pydantic, despliegue local sencillo. |
| **Motor separado de la UI** | La interfaz puede cerrarse sin detener la operativa; el motor no importa React. |
| **SQLite (WAL)** | Cero infraestructura en local, transacciones ACID y persistencia suficiente para una sesión. Interfaz `Store` aislada para migrar a PostgreSQL. |
| **React + TypeScript** | Componentes reutilizables, estado tipado y control estricto de la forma del snapshot. |
| **Lightweight Charts** | Librería financiera madura, rápida y con zoom/pan/crosshair nativos; canvas propio para zonas ORB. |
| **Estrategia sin estado persistente** | Se recalcula desde las velas cerradas: elimina repainting y divergencias entre live y backtest. |
| **Ejecución paper sustituible** | `arm / on_bar / close / cancel_all` es una interfaz estrecha que un adaptador de broker puede implementar. |
| **Configuración validada en servidor** | El cliente nunca impone parámetros inválidos; los cambios sensibles se bloquean con posición abierta. |

## 4. Contrato del snapshot

El WebSocket envía `{type: "snapshot", data: {...}}` en cada vela y
`{type: "event", data: {...}}` al registrar un evento. El snapshot incluye:

- `status`, `mode`, `data` (proveedor, calidad, última vela, staleness);
- `quotes` de MNQ/NQ/ES;
- `opening_range` y `assessment` (fases, ruptura, SMT, retesteo, señal, rechazo);
- `position`, `orders`, `risk`, `stats`, `day_stats`;
- `chart` (velas 1m MNQ, series NQ/ES, marcadores);
- `settings` y resumen de configuración.

La UI nunca calcula señales ni P&L de verdad: solo presenta y agrega visualmente velas para
las temporalidades del gráfico.

## 5. Persistencia

| Tabla | Contenido |
|---|---|
| `trades` | Operaciones cerradas con precios, SL, TP, P&L neto, R, fees, motivos y modo. |
| `events` | Log con nivel, categoría, mensaje y metadatos (máx. 5.000 filas). |
| `equity` | Puntos de equidad tras cada cierre. |
| `kv` | Estado del motor y posición abierta para recuperación tras reinicio. |
| `backtests` | Resultado completo, métricas y diagnósticos (incluido el informe de velas ambiguas). |

La restauración reconstruye la equidad desde las operaciones reales; no se guarda un saldo
inventado. Los brackets SL/TP se reconstruyen desde la posición guardada.

## 6. Riesgo y seguridad operativa

- Una señal se identifica por `fecha + dirección + breakout_ts`; se ejecuta una sola vez.
- No se permite una segunda entrada con posición abierta u orden pendiente.
- Los límites diarios se evalúan antes de cada entrada y también se muestran como estado.
- La parada de emergencia es persistente hasta que el operador la desactiva.
- LIVE exige tres condiciones y aun así se rechaza si el adaptador no está implementado.
- Los errores de feed se registran y se reintenta la conexión; nunca se ocultan.

## 7. Extensiones previstas

1. Adaptador real de datos (`MarketFeed`) para Tradovate/IBKR/Rithmic.
2. Adaptador de ejecución con reconciliación de posiciones del broker.
3. Migración de `Store` a PostgreSQL manteniendo la interfaz.
4. Walk-forward automático con ventanas de entrenamiento/validación/prueba.
5. Alertas externas y exportación de métricas.
