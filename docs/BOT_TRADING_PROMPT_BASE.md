# YEDBot — Prompt técnico base

**Ruta:** `docs/BOT_TRADING_PROMPT_BASE.md`  
**Generado:** 2026-11-22  
**Alcance:** infraestructura, operación, persistencia, backtesting, evaluación, pruebas e interfaz.  
**Excluido deliberadamente:** reglas de entrada, salida, ruptura, divergencia, retesteo, señales y cualquier detalle interno de la estrategia.

> Este documento describe lo que el repositorio **hace y contiene**, no una estrategia rentable ni una recomendación de inversión. Los resultados citados son los artefactos reales del proyecto y conservan sus propias limitaciones. El bloque reservado del final es el único lugar para insertar la lógica de estrategia.

---

## 1. Identidad y estado del proyecto

YEDBot es una terminal local de trading algorítmico para **MNQ (Micro E-mini Nasdaq 100)**, con **NQ** como referencia y **ES** como comparación intermarket. El sistema incluye motor independiente, gestión de riesgo, ejecución paper, persistencia SQLite, backtesting histórico y dashboard web.

| Elemento | Estado real |
|---|---|
| Backend | FastAPI + asyncio |
| Frontend | React 18 + TypeScript + Vite + Lightweight Charts 4.2 |
| Persistencia | SQLite en modo WAL; esquema versionado |
| Arranque | `python run.py` |
| URL local | `http://127.0.0.1:8765` |
| Feed por defecto | `simulated` |
| Modo por defecto | `paper` |
| LIVE | **Bloqueado**: no hay adaptador de broker implementado |
| Autenticación | No existe; la terminal es local y de un solo operador |
| Multiusuario | No implementado |

El motor arranca detenido. El servidor sirve la API y los estáticos de `frontend/dist` en el mismo proceso. `run.py` permite cambiar host, puerto y perfil mediante `YED_HOST`, `YED_PORT`, `YED_OPEN`, `YED_PROFILE_DIR`, `YED_CONFIG_PATH` y `YED_DB_PATH`.

### Distinción importante entre configuración y perfil

- Los **defaults** descritos en este documento proceden de `Settings()` en `server/config.py`.
- La configuración viva se guarda en `data/config.json` y la base en `data/yedbot.db`, salvo que se use un perfil aislado.
- El protocolo de backtesting usa el perfil aislado `profiles/backtest_real/config.json`, no la configuración viva.
- No debe asumirse que `data/config.json` coincide con los defaults ni con el perfil del protocolo.

---

## 2. Estructura real del repositorio

```text
run.py                         arranque de API + motor + dashboard
server/
  main.py                      FastAPI, lifespan, estáticos
  api.py                       endpoints REST y WebSocket
  engine.py                    TradingEngine: orquestación, estado, control
  config.py                    Settings, validación Pydantic y persistencia atómica
  models.py                    Bar, Signal, Position, Order, TradeRecord
  risk.py                      RiskManager y RiskDecision
  execution.py                 ExecutionEngine: fills, brackets, SL/TP
  db.py                        Store SQLite
  migrations.py                migraciones y esquema versionado
  stats.py                     compute_stats y métricas
  backtest.py                  motor de backtesting, datasets y presets
  confirmatory.py              hashes, preflight y sello del holdout
  experiments.py               identidad de experimentos y ledger JSONL
  schemas.py                   contratos Pydantic del snapshot y backtest
  diagnostics.py               diagnóstico de solo lectura de SQLite
  reset.py                     reinicio operativo con archivo de backups
  timeutil.py                  utilidades de zona horaria y sesión
  funnel.py                    registro y resumen del embudo de evaluación
  strategy/                    evaluador de estrategia — RESERVADO, no documentado aquí
  market/
    feed.py                    MarketFeed, SimulatedFeed, CSVFeed, LiveFeed
    csv_data.py                carga, alineación y validación de CSV
    sessions.py                calendario, feriados y cierres anticipados
    contracts.py               contratos, vencimientos y rolls
    synthetic.py               generador sintético determinista
    massive_fetch.py           descarga desde Massive
    databento_fetch.py         descarga desde Databento
frontend/src/
  App.tsx                      rutas/páginas
  components/                  Sidebar, TopBar y UI compartida
  pages/                       siete pantallas
  api.ts, store.tsx, types.ts, utils.ts
frontend/dist/                 build servido por FastAPI
research/                      diseños de validación
tests/                         32 archivos pytest
docs/                          arquitectura, protocolo, proveedores y validación
profiles/                      perfiles aislados (`backtest_real`, `dryrun`)
reports/backtest/              ejecuciones, JSON, CSV, auditorías e informes
data/                          configuración y SQLite locales
backups/                       copias de seguridad operativas
```

No hay `AGENTS.md` ni `CLAUDE.md` en la raíz. El repositorio se inspeccionó directamente desde el sistema de archivos.

---

## 3. Arquitectura y flujo de ejecución

### 3.1 Componentes

```text
Feed (simulado / CSV / adaptador live)
        │  Tick alineado {MNQ, NQ, ES}
        ▼
TradingEngine
   ├── evaluador de estrategia (módulo reservado)
   ├── RiskManager
   ├── ExecutionEngine
   ├── EventHub
   ├── Store SQLite
   └── WebSocket / REST
             │
             ▼
      React + TypeScript
```

Decisiones técnicas presentes en el código:

- **FastAPI + asyncio** para REST y WebSocket en el mismo proceso.
- **Motor separado de la UI**: el motor no importa React.
- **SQLite WAL** con interfaz `Store` aislada; el diseño contempla migrar a PostgreSQL.
- **Estrategia determinista** recalculada desde velas cerradas; no se persiste estado oculto de la estrategia.
- **Ejecución paper sustituible** mediante una interfaz estrecha: `arm`, `on_bar`, `close`, `cancel_all`.
- **Configuración validada en servidor**; el cliente no impone parámetros inválidos.

### 3.2 Flujo de una vela

1. `MarketFeed.next_tick()` entrega MNQ, NQ y ES alineados por timestamp.
2. `TradingEngine._process` detecta cambio de sesión, reinicia el estado diario y registra el evento.
3. `ExecutionEngine.on_bar()` procesa fills pendientes y gestiona la posición abierta.
4. Si el motor está en `running`, el evaluador de estrategia recalcula el estado de la sesión con velas cerradas y devuelve fases, señal y marcadores.
5. `RiskManager.evaluate()` autoriza o rechaza la señal y calcula cantidad y riesgo.
6. La orden se arma y se ejecuta según el modelo de fill configurado; al cerrar se persiste la operación.
7. Se guarda el estado en SQLite, se emite un evento y se difunde un snapshot por WebSocket.

El motor no permite una segunda entrada con posición abierta u orden pendiente. Una señal se identifica de forma estable y se ejecuta una sola vez.

### 3.3 Contrato del snapshot

El WebSocket envía `{type: "snapshot", data: {...}}` en cada vela y `{type: "event", data: {...}}` al registrar un evento. El snapshot incluye:

- `status`, `mode` y `data` (proveedor, calidad, última vela, staleness);
- `quotes` de MNQ, NQ y ES;
- `opening_range` y `assessment` (fases, señal y rechazo);
- `position`, `orders`, `risk`, `stats` y `day_stats`;
- `chart` con velas y series de comparación;
- `settings` y resumen de configuración.

La UI presenta y agrega visualmente velas, pero no calcula señales ni P&L real. El backend es la fuente de verdad.

---

## 4. Configuración del sistema

`server/config.py` define `Settings`, compuesta por:

- `ORBConfig`
- `SMTConfig`
- `StrategyConfig`
- `RiskConfig`
- `ExecutionConfig`
- `FeedConfig`
- `LiveConfig`

Los tres primeros grupos contienen parámetros de estrategia y **se omiten deliberadamente** en este documento. Los valores se validan con Pydantic antes de aplicarse.

### 4.1 Persistencia de configuración

- `load_settings()` crea `Settings()` si no existe configuración.
- `save_settings()` escribe de forma atómica.
- `apply_settings()` aplica un patch parcial validado.
- Una configuración corrupta se archiva como `.json.broken` y se restauran los defaults; no impide arrancar.
- Rutas configurables: `YED_PROFILE_DIR`, `YED_CONFIG_PATH`, `YED_DB_PATH`.
- La API expone `GET /api/config`, `PUT /api/config` y `POST /api/config/reset`.

### 4.2 Riesgo — `RiskConfig`

| Parámetro | Default | Función |
|---|---:|---|
| `initial_capital` | 25.000 USD | Capital de referencia |
| `risk_per_trade_pct` | 1,0 % | Riesgo objetivo por operación |
| `max_daily_loss_pct` | 3,0 % | Límite de pérdida diaria |
| `max_daily_profit_pct` | 0,0 | 0 = sin límite de beneficio diario |
| `max_trades_per_day` | 3 | Máximo de operaciones diarias |
| `max_concurrent_positions` | 1 | Posiciones simultáneas |
| `max_contracts` | 5 | Tope de contratos por operación |
| `max_sl_ticks` | 200 | Stop máximo admitido en ticks |
| `trade_window_start` | 09:00 | Inicio de ventana de entradas |
| `trade_window_end` | 15:30 | Fin de ventana de entradas |
| `entry_exclusion_start` / `entry_exclusion_end` | vacío / vacío | Ventana opcional de exclusión |
| `close_at_session_end` | `true` | Cierre al final de sesión |
| `session_close_time` | 15:55 | Hora de cierre |
| `cooldown_minutes` | 5 | Espera tras una salida |
| `no_trade_after_consecutive_losses` | 0 | 0 = desactivado |

`RiskManager` aplica, en este orden, comprobaciones de emergencia, orden pendiente, posiciones abiertas, operaciones del día, stop máximo, ventana horaria, exclusión opcional, pérdida diaria, beneficio diario, pérdidas consecutivas y cooldown. Después dimensiona la posición.

El sizing es:

```text
presupuesto = equity × risk_per_trade_pct / 100
riesgo_por_contrato = stop_ticks × tick_value
qty = floor(presupuesto / riesgo_por_contrato)
qty = min(qty, max_contracts)
```

Si `qty < 1`, la señal se rechaza con motivo explícito. La ventana de exclusión es semiabierta: bloquea desde el inicio inclusive hasta el fin exclusive, y solo afecta a entradas nuevas; una posición ya abierta se sigue gestionando.

### 4.3 Ejecución — `ExecutionConfig`

| Parámetro | Default |
|---|---:|
| `tick_size` | 0,25 |
| `tick_value` | 0,50 USD |
| `point_value` | 2,00 USD |
| `slippage_ticks` | 1 |
| `max_slippage_ticks` | 4 |
| `commission_per_contract_side` | 0,62 USD |
| `fill_model` | `next_open` |
| `simulate_partial_fills` | `false` |
| `partial_fill_ratio` | 0,6 |

`ExecutionEngine` calcula fills con slippage adverso acotado por `max_slippage_ticks`, aplica comisiones por lado, gestiona brackets SL/TP y registra el informe de velas ambiguas. La convención conservadora ante una vela ambigua es SL primero, con diagnóstico auditable. El modelo de fill también admite `signal_price`.

Con `simulate_partial_fills`, el remanente es la segunda tranche de la misma entrada ya aprobada, no una entrada nueva. Si el primer fill cae justo antes de `entry_exclusion_start` y el remanente toca llenarse dentro de la ventana, se llena: la posición conserva el tamaño planificado y se sigue gestionando por SL/TP. Si la posición ya se cerró (por ejemplo, SL en la vela del primer fill), el remanente abriría una posición nueva dentro de la ventana y se cancela como cualquier entrada pendiente. La ventana nunca cierra una posición abierta ni deja una entrada aprobada a media talla.

### 4.4 Feed — `FeedConfig`

| Parámetro | Default |
|---|---|
| `provider` | `simulated` |
| `csv_path` | `data/bars.csv` |
| `series_mode` | `adjusted` |
| `exclude_roll_sessions` | `true` |
| `replay_speed` | 2,5 velas de 1m por segundo |
| `loop_sessions` | `true` |
| `start_date` | vacío |
| `latency_ms` | 0 |

`SimulatedFeed` es determinista por fecha. `CSVFeed` usa el CSV configurado y el validador del proyecto. `LiveFeed` existe como punto de extensión, pero no hay conexión real a broker.

Con `provider=simulated`, el motor rechaza el arranque salvo que se exporte `YED_ALLOW_SIMULATED=1`; esto no afecta a los backtests sintéticos.

### 4.5 LIVE — `LiveConfig`

`LiveConfig` contiene `broker`, `environment`, `account_ref`, `data_feed`, `live_enabled` y `live_confirmation`. Los defaults son `broker="none"`, `environment="demo"`, `live_enabled=false` y confirmación vacía.

El modo LIVE exige broker configurado, `live_enabled`, confirmación explícita y un adaptador implementado. Sin adaptador, el motor rechaza el arranque. No hay credenciales reales ni conexión a broker en el repositorio.

---

## 5. Persistencia, sesiones y recuperación

### 5.1 SQLite

`server/db.py` implementa `Store` sobre SQLite en WAL. El esquema actual es la **versión 5** e incluye:

- `trades`: operaciones cerradas;
- `events`: log de eventos, con retención máxima de 5.000 filas;
- `equity`: puntos de equidad;
- `kv`: estado del motor y posición abierta;
- `backtests`: resultados completos de backtesting;
- `backtest_runs` y `backtest_results`: índice y resultados normalizados;
- `backtest_ledger_outbox`: cola de publicación al ledger de experimentos;
- `schema_migrations`: control de migraciones.

La base por defecto es `data/yedbot.db`. `server/migrations.py` aplica migraciones y repara filas legacy válidas en el índice de backtests sin reescribir la tabla `backtests`.

### 5.2 Recuperación tras reinicio

Al reiniciar:

- se restauran la posición y su bracket SL/TP desde `kv`;
- se reconstruye la equidad desde las operaciones registradas;
- se conservan los contadores del día si la sesión coincide;
- el replay se reinicia, pero no se evalúan velas anteriores a la entrada de la posición restaurada.

### 5.3 Exportación y mantenimiento

- `GET /api/trades/export.csv` exporta el historial con los filtros aplicados.
- `GET /api/stats/reset/preview` previsualiza el borrado de estadísticas.
- `POST /api/stats/reset` reinicia operaciones, equidad y eventos; conserva backtests salvo solicitud explícita.
- `python -m server.reset --dry-run` muestra qué se archivaría.
- `python -m server.reset --yes` archiva base, configuración y log en `backups/`, y deja un perfil CSV.
- `python -m server.diagnostics --db data/yedbot.db` diagnostica en solo lectura, sin crear tablas ni backups.

La exportación CSV y el borrado de estadísticas son operaciones distintas del reinicio completo de consola.

---

## 6. Backtesting histórico y datasets

### 6.1 Motor

`server/backtest.py` contiene:

- `prepare_dataset`: prepara y valida el dataset;
- `run_backtest`: ejecuta una configuración;
- `run_variants`: ejecuta las variantes sobre el mismo dataset;
- `preset_catalog` y `preset_comparison`: catálogo y comparación de presets;
- `preset_sample`: evaluación de muestra para presets.

Los backtests incluyen comisiones, slippage acotado, modelo de fill y diagnóstico de barras ambiguas. El motor es determinista y comparte las mismas reglas de ejecución que el modo paper.

### 6.2 Datasets

El feed CSV exige:

- timestamps alineados entre MNQ, NQ y ES;
- sesión RTH completa;
- días hábiles según `server/market/sessions.py`;
- Opening Range completo;
- contratos y vencimientos declarados;
- consistencia de rolls;
- ausencia de huecos intra-sesión no justificados.

El validador se ejecuta con:

```bash
python -m server.market.csv_data ruta.csv
```

También está disponible desde **Configuración → Avanzado → Validar CSV** y mediante `POST /api/data/validate`.

Cada backtest guarda la identidad del dataset (`dataset_id`, hash del archivo), la identidad de la serie efectiva (`series_id`), el rango de sesiones, contratos, vencimientos, contrato activo por sesión, plan de rolls y configuración de feed/ejecución. Se admiten series `raw` y `adjusted`; la sesión de roll se excluye por defecto.

### 6.3 Historial de backtests y ledger

- `GET /api/backtest/runs` usa paginación estable por cursor (`has_more`, `next_cursor`) y filtros por fecha, dataset y etiqueta.
- `GET /api/backtest/runs/{run_id}`, `GET /api/backtest/latest` y los detalles de resultados exponen el bloque de ledger: `ledger_status`, `hypothesis_id`, `ledger_event_id`, `ledger_event_sha256`, `ledger_error`.
- `GET /api/backtest/ledger/{run_id}` muestra el estado operativo del outbox.
- `POST /api/backtest/ledger/reconcile` reconstruye vínculos de corridas antiguas sin duplicar entradas.
- Los backtests se pueden comparar mediante los endpoints de comparación y desde la pestaña **Backtesting**.

`server/experiments.py` define la identidad canónica de experimentos, el hash de configuración y el ledger JSONL. `server/confirmatory.py` contiene las comprobaciones criptográficas y el sello one-shot del holdout; `HoldoutAlreadySealed` impide repetirlo sin una incidencia técnica documentada.

### 6.4 Ejecución desde consola

```bash
python -m server.backtest --days 20 --preset <preset>
python -m server.backtest --days 20 --all --out reports/backtest/presets.json
```

El perfil aislado del protocolo se activa con:

```bash
YED_PROFILE_DIR=profiles/backtest_real
```

No se debe usar `data/` ni `profiles/dryrun/` para el protocolo confirmatorio.

---

## 7. Framework de evaluación y validación

### 7.1 Protocolo pre-registrado

Documento: `docs/PROTOCOLO_BACKTEST.md`  
Lock: `docs/protocolo_backtest.lock.json` (congelado; no modificar)  
Versión: 1.2  
Estado: congelado y **no ejecutado en su totalidad**.

Ventanas:

| Bloque | Desde | Hasta | Sesiones de calendario | Evaluadas |
|---|---|---|---:|---:|
| Desarrollo | 2025-01-10 | 2026-06-30 | 368 | 362 |
| W1 | 2025-01-10 | 2025-03-31 | 55 | 54 |
| W2 | 2025-04-01 | 2025-06-30 | 62 | 61 |
| W3 | 2025-07-01 | 2025-09-30 | 64 | 63 |
| W4 | 2025-10-01 | 2025-12-31 | 64 | 63 |
| W5 | 2026-01-01 | 2026-03-31 | 61 | 60 |
| W6 | 2026-04-01 | 2026-06-30 | 62 | 61 |
| Holdout | 2026-07-01 | 2026-10-30 | 86 | 85 |

Los conteos evaluados excluyen las sesiones de roll. El holdout está sellado y no se ha ejecutado.

### 7.2 Métricas

`server/stats.py` calcula, entre otras:

- operaciones, ganadoras, perdedoras y breakeven;
- win rate, Profit Factor, expectativa USD y expectativa R;
- P&L neto, comisiones, R total y duración media;
- drawdown máximo cerrado y drawdown abierto;
- Sharpe y Sortino diarios anualizados a 252;
- mejores y peores rachas;
- MFE/MAE;
- resultados por dirección, tipo de señal, hora, día de semana y mes;
- barras ambiguas y días operados.

Métricas derivadas del informe:

- IC bootstrap de la esperanza en R (10.000 remuestreos, semilla `20250102`);
- sensibilidad a costes;
- drop-best de las cinco mejores operaciones;
- concentración top-5 y del mejor mes;
- operaciones por sesión y porcentaje de sesiones operadas;
- impacto económico de barras ambiguas.

### 7.3 Puertas

**Desarrollo — G1 a G14:**

| ID | Criterio resumido |
|---|---|
| G1 | Integridad del dataset y rolls |
| G2 | Determinismo de W1 |
| G3 | Coherencia raw/adjusted en W1 |
| G4 | ≥ 80 operaciones y ≥ 20 por dirección |
| G5 | PF ≥ 1,25 y expectativa ≥ +0,10 R |
| G6 | Drawdown ≤ 2.000 USD y peor racha ≤ 8 |
| G7 | ≥ 4/6 bloques con PF > 1,0 |
| G8 | PF ≥ 1,10 con costes duplicados |
| G9 | P&L > 0 tras eliminar las 5 mejores operaciones |
| G10 | Top-5 ≤ 50 % del bruto y mejor mes ≤ 50 % del neto |
| G11 | Límite inferior del IC bootstrap al 80 % > 0 |
| G12 | Mínimo de cortos y PF/expectativa de cortos |
| G13 | Barras ambiguas ≤ 5 % |
| G14 | Integridad de resultados y ausencia de duplicados |

**Holdout — H1 a H5:**

| ID | Criterio resumido |
|---|---|
| H1 | Integridad del dataset del holdout |
| H2 | ≥ 18 operaciones |
| H3 | PF ≥ 1,00 y expectativa ≥ 0,00 R |
| H4 | Drawdown ≤ 2.500 USD |
| H5 | Configuración, dataset y código idénticos |

El holdout solo se ejecuta si todas las puertas duras de desarrollo pasan. Una muestra insuficiente produce `INCONCLUSO`, no aprobación. La promoción a paper no autoriza LIVE.

### 7.4 Resultado real de desarrollo

Informe: `reports/backtest/INFORME_DESARROLLO.md`  
Puertas: `reports/backtest/gates.json`

| Métrica | Valor |
|---|---:|
| Operaciones | 38 |
| Largos / cortos | 21 / 17 |
| Profit Factor | 1,1328 |
| Expectativa R | +0,1311 |
| P&L neto | +661,44 USD |
| Drawdown máximo | 1.967,82 USD (7,141 %) |
| Peor racha perdedora | 10 |
| Sharpe / Sortino | 0,82 / 1,58 |
| Barras ambiguas | 0 (0 %) |

Puertas que pasan: G1, G2, G3, G13, G14.  
Puertas que fallan: G4, G5, G6, G7, G8, G9, G10, G11, G12.  
**Decisión: INCONCLUSO.** El holdout no se ejecutó.

La muestra es insuficiente para distinguir el sistema de la nada. El PF agregado es descriptivo y depende de pocas operaciones. El bootstrap remuestrea operaciones, no sesiones.

### 7.5 Métricas ex-W4

Auditoría: `reports/backtest/AUDITORIA_CONCENTRACION_CONTINUA.md`  
Datos: `reports/backtest/concentration_continuous_audit.json`

La auditoría usa la curva continua de 362 sesiones con capital arrastrado, no los bloques con capital reiniciado. Para el baseline:

- P&L neto: +661,44 USD;
- P&L del bloque W4: +2.034,12 USD;
- P&L ex-W4: **−1.372,68 USD**;
- drawdown completo: 1.967,82 USD;
- drawdown sin W4: **3.052,62 USD**;
- delta de drawdown al quitar W4: −1.084,80 USD.

Lectura: W4 concentra el beneficio y actúa como colchón del drawdown. Quitar W4 empeora el drawdown en 8 de 11 presets. Los 11 mejores trades de los presets caen en solo 4 fechas, por lo que no son observaciones independientes. La mejor operación no cambia el drawdown máximo. En presets con al menos 15 operaciones, eliminar la peor operación para el drawdown solo lo reduce entre 5,2 % y 27,1 %.

Esta auditoría **no es una validación fuera de muestra** y no modifica la decisión del protocolo.

### 7.6 Validación por bloques

Diseño: `docs/VALIDACION_BLOQUES.md`  
Módulo: `research/validacion_bloques.py`  
Tests: `tests/test_validacion_bloques.py`

Es un diseño metodológico **no ejecutado**. Combina:

- 4 bloques consecutivos de igual duración;
- mínimo de 20 operaciones del candidato y 20 del baseline por bloque;
- mínimo total de 80 por brazo;
- bootstrap pareado por bloque con 10.000 remuestras y semilla `20261121`;
- gasto alfa secuencial O'Brien-Fleming con dos miradas (bloques 2 y 4);
- placebo de entradas aleatorias con la misma sesión y dirección;
- objetivo práctico de +0,10 R.

Funciones principales verificadas: `validate_blocks`, `paired_block_bootstrap`, `SequentialAlphaSpending`, `generate_placebo_entries`, `evaluate_validation` y `design_spec`.

El módulo es puro, no lee datos ni escribe configuración. Un `pass` no autoriza LIVE.

---

## 8. API y controles

La API se monta bajo `/api`. Los grupos verificados son:

- **Salud y estado:** `GET /api/health`, `GET /api/status`.
- **Configuración:** `GET /api/config`, `PUT /api/config`, `POST /api/config/reset`.
- **Motor:** `POST /api/bot/{action}`.
- **Posición y órdenes:** `POST /api/position/close`, `POST /api/orders/cancel`, `GET /api/orders`.
- **Emergencia:** `POST /api/emergency`, `DELETE /api/emergency`.
- **Historial:** `GET /api/trades`, `GET /api/trades/export.csv`, `GET /api/events`.
- **Estadísticas:** `GET /api/stats`, `GET /api/stats/reset/preview`, `POST /api/stats/reset`.
- **Gráfico:** `GET /api/chart/history`.
- **Backtesting:** `/api/backtest/*`, incluyendo ejecución, variantes, presets, historial, detalle, comparación, ledger y reparación legacy.
- **Datos:** `GET /api/datasets`, `POST /api/data/validate`.
- **Tiempo real:** `WS /api/ws`.

La parada de emergencia bloquea nuevas entradas, cancela órdenes y permite cerrar posiciones. Es persistente hasta que el operador la desactiva explícitamente.

---

## 9. Interfaz y terminal

El dashboard tiene siete pantallas, definidas en `frontend/src/App.tsx` y `Sidebar.tsx`:

1. **Inicio** — resumen operativo, equidad, P&L, riesgo abierto, gráfico, posición, últimas operaciones y curva de equidad.
2. **Gráfico** — velas de 1/5/15/30 minutos, zoom, desplazamiento, volumen, VWAP/ATR opcionales, panel NQ vs ES normalizado y marcadores de eventos.
3. **Operaciones** — posición, órdenes, brackets, riesgo actual, límites de sesión y controles de cierre, cancelación, pausa y emergencia.
4. **Historial** — registro persistente con filtros por periodo, dirección, resultado y tipo de señal; detalle y exportación CSV. Paginación de 25 filas.
5. **Estadísticas** — resumen, rendimiento, dirección, hora, mes y backtesting.
6. **Configuración** — estrategia, riesgo, horarios, instrumentos y avanzado.
7. **Consola** — eventos en tiempo real con nivel, categoría y estado de conexiones.

### Pestañas exactas

- **Operaciones:** `positions` (posiciones abiertas), `orders` (órdenes pendientes), `closed` (operaciones cerradas).
- **Estadísticas:** `resumen`, `rendimiento`, `direccion`, `hora`, `mes`.
- **Configuración:** `estrategia`, `riesgo`, `horarios`, `instrumentos`, `avanzado`.
- **Historial:** periodos `today`, `week`, `month`, `30d`, `all`.

La pestaña de estrategia y sus campos quedan fuera del alcance de este documento. La pestaña **Riesgo** expone los límites descritos en la sección 4.2; **Horarios** cubre ventana y cierre; **Instrumentos** cubre símbolos; **Avanzado** incluye validación CSV, reset de estadísticas y configuración.

### Estado del build frontend

Verificado el 2026-11-22 con:

```bash
cd frontend
npm run build
```

Resultado real:

```text
tsc --noEmit && vite build
vite v5.4.11 building for production...
✓ 54 modules transformed.
dist/index.html                   0.46 kB │ gzip:  0.30 kB
dist/assets/index-CIBhSyxJ.css   21.13 kB │ gzip:  5.26 kB
dist/assets/index-CLFkbSUT.js   448.50 kB │ gzip: 134.02 kB
✓ built in 4.13s
```

El build pasa. `frontend/package.json` define `dev`, `build`, `test` (`vitest run`) y `preview`. El backend sirve `frontend/dist`; no se necesita un segundo servidor para usar la terminal.

---

## 10. Pruebas

Comando:

```bash
python -m pytest -q
```

Última ejecución completa verificada en este estado:

```text
454 passed, 1 warning in 126.24s (0:02:06)
```

El warning es de FastAPI/Starlette por el uso de `httpx` en `TestClient`; no es un fallo del proyecto. No se midió cobertura.

Los **32 archivos** de `tests/` cubren, entre otras áreas:

- contratos REST y OpenAPI;
- configuración y mutaciones de API;
- holdout y presets;
- motor, snapshot y ejecución intrabar;
- riesgo, sizing, ventanas, DST y cooldown;
- stops, shorts, barras ambiguas y MFE/MAE;
- SQLite, migraciones, persistencia e historial;
- ledger, outbox, conciliación y procedencia;
- CSV, sesiones, feriados, contratos y rolls;
- Massive y Databento;
- reset y diagnóstico legacy;
- validación por bloques;
- experimentos y stop ATR.

Archivos relevantes incluyen `test_backtest_golden.py`, `test_confirmatory.py`, `test_validacion_bloques.py`, `test_entry_exclusion.py` y `test_api_contract.py`.

No se ejecutó `npm run test` durante esta verificación; el frontend se validó con `tsc --noEmit` y el build de Vite.

---

## 11. Comandos operativos

```bash
# Instalar backend
python -m pip install -r requirements.txt

# Arrancar API + motor + dashboard
python run.py

# Suite completa
python -m pytest -q

# Recompilar frontend
cd frontend
npm install
npm run build

# Validar CSV
python -m server.market.csv_data data/real/bars_mnq_nq_es_1m.csv --series raw

# Diagnóstico de SQLite en solo lectura
python -m server.diagnostics --db data/yedbot.db

# Reset operativo (previsualizar primero)
python -m server.reset --dry-run
python -m server.reset --yes
```

En Windows existe `start.bat`, que crea `.venv` e instala dependencias. Para una demo explícita con datos sintéticos se puede usar `YED_ALLOW_SIMULATED=1`; no debe usarse para calibrar ni para backtests.

---

## 12. Límites y advertencias

- No hay conexión real a broker ni feed en vivo; `LiveFeed` no implementa un adaptador.
- Los datos por defecto son simulados. Los resultados sintéticos validan lógica, no rentabilidad.
- El holdout 2026-07-01 → 2026-10-30 sigue sellado y no se ha ejecutado.
- El protocolo no optimiza parámetros; no hay búsqueda en rejilla ni selección automática.
- El backtest no modela libro de órdenes ni latencia variable; usa slippage fijo acotado.
- La interfaz es local, de un solo operador, sin autenticación remota.
- No hay multiusuario, alertas externas ni despliegue en nube.
- El informe de desarrollo es **INCONCLUSO** por muestra y edge; no demuestra rentabilidad.
- La auditoría ex-W4 es descriptiva y no sustituye una validación fuera de muestra.
- El diseño de validación por bloques no se ha ejecutado.
- No se debe modificar `docs/protocolo_backtest.lock.json`, el holdout, `data/config.json` ni `profiles/backtest_real/config.json` sin una decisión explícita y un protocolo nuevo.

---

## 13. Instrucciones para reutilizar este documento como contexto

Al usar este archivo como prompt o especificación base:

1. Trata las rutas, clases, campos y comandos como el contrato técnico existente.
2. No inventes módulos, endpoints, parámetros ni estados que no aparezcan aquí o en el código.
3. No deduzcas la lógica de estrategia a partir de los nombres de módulos o de los resultados.
4. Mantén la separación entre defaults, configuración viva y perfil del protocolo.
5. No alteres locks, holdout, configuración congelada ni datos históricos sin autorización.
6. Verifica cualquier cambio con la suite pytest correspondiente y, si toca React, con el build de `frontend`.
7. Si necesitas implementar o describir la estrategia, hazlo únicamente en el bloque reservado siguiente.

---

# Aquí va la estrategia

<!--
Bloque reservado. Insertar aquí la definición completa de la estrategia:
reglas de entrada, salida, ruptura, divergencia, retesteo y gestión de señales.
No se incluye ninguna de esas reglas en las secciones anteriores.
-->
