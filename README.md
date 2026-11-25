# YEDTradingBot — Terminal MNQ · ORB + SMT

Sistema de trading algorítmico para **Micro E-mini Nasdaq 100 (MNQ)** con estrategia
**Opening Range Breakout (ORB)** y confirmación por **divergencia intermarket NQ/ES (SMT)**.
Incluye motor independiente, gestión de riesgo, ejecución paper, base de datos SQLite,
backtesting y una terminal gráfica en tiempo real.

> **Aviso de honestidad:** el proyecto se entrega con un **replay simulado** porque no hay
> credenciales de un proveedor de datos contratadas. Esos datos están etiquetados como
> simulados en toda la interfaz y **no representan el mercado real**. El modo LIVE está
> bloqueado y no se ha inventado ninguna conexión a broker. Ningún resultado de este
> repositorio demuestra que la estrategia sea rentable.

---

## 1. Arranque rápido

Requisitos: **Python 3.11+** (probado en 3.12). Node 20+ solo si quieres recompilar la interfaz.

```bash
# 1) Dependencias del backend
python -m pip install -r requirements.txt

# 2) Arrancar todo (API + motor + dashboard)
python run.py
```

Se abre `http://127.0.0.1:8765`. El motor arranca **detenido** y rechaza feeds
sintéticos por defecto: no se ejecuta paper trading con datos inventados. Configura un
CSV histórico validado y pulsa **Iniciar**. Para una demo explícita, exporta
`YED_ALLOW_SIMULATED=1`; no lo uses para backtests ni para calibrar.

En Windows también puedes usar `start.bat` (crea `.venv` e instala dependencias).

Para recompilar el frontend (solo si modificas React):

```bash
cd frontend
npm install
npm run build
```

El backend sirve `frontend/dist`; no hace falta un segundo servidor.

## 2. Modos de funcionamiento

| Modo | Estado | Descripción |
|---|---|---|
| **Backtest** | Disponible | Motor independiente sobre datos sintéticos o un CSV propio. Comisiones y slippage incluidos. |
| **Paper trading** | Disponible | Ejecución simulada contra CSV histórico validado; rechaza el generador sintético salvo `YED_ALLOW_SIMULATED=1` explícito. |
| **Live trading** | **Bloqueado** | Exige broker configurado, `live_enabled`, confirmación `HABILITAR LIVE` y un adaptador implementado. Sin él, el motor rechaza el arranque. |

El motor nunca activa LIVE automáticamente ni envía órdenes a un broker.

## 3. Pantallas

1. **Inicio** — resumen operativo: equidad, P&L, riesgo abierto, gráfico con Opening Range,
   fases de la estrategia, posición, últimas operaciones y curva de equity.
2. **Gráfico** — velas 1/5/15/30 min, zoom y desplazamiento, volumen, VWAP y ATR opcionales,
   OR High/Low/50%, zona de retesteo, marcadores de ruptura/SMT/entrada/salida, SL/TP y
   panel sincronizado NQ vs ES normalizado.
3. **Operaciones** — posiciones, órdenes y brackets, riesgo actual, límites de sesión y
   controles reales (cerrar posición, cancelar órdenes, pausar, parada de emergencia).
4. **Historial** — registro persistente con filtros por periodo/dirección/resultado/tipo de
   señal, detalle de cada operación y exportación CSV.
5. **Estadísticas** — win rate, profit factor, expectativa, drawdown, Sharpe, Sortino,
   rachas, R medio, curvas de equity/drawdown, resultados diarios/semanales/mensuales,
   distribución y rendimiento por hora, dirección y tipo de señal.
6. **Configuración** — parámetros ORB, SMT, ruptura, entrada, SL/TP, riesgo, horarios,
   instrumentos y proveedor. Validación en servidor y restauración de valores por defecto.
7. **Consola** — eventos en tiempo real con nivel, categoría y estado de conexiones.

Cada control llama a un endpoint real del motor; no hay botones decorativos ni tablas
con datos inventados.

## 4. Arquitectura

```
Proveedor de datos (replay / CSV / adaptador live)
        │  Tick {MNQ, NQ, ES}
        ▼
TradingEngine ──► ORBStrategy (ORB → ruptura → SMT → retesteo → entrada)
   │                 │
   │                 ▼
   ├──► RiskManager (tamaño, límites diarios, ventana, emergencia)
   ├──► ExecutionEngine (paper: fills, slippage, SL/TP, parciales)
   ├──► SQLite (trades, eventos, equity, estado, backtests)
   └──► WebSocket / REST ──► React + TypeScript + Lightweight Charts
```

Decisiones y flujo detallado: [`docs/ARQUITECTURA.md`](docs/ARQUITECTURA.md).
Reglas matemáticas de la estrategia: [`docs/ESTRATEGIA.md`](docs/ESTRATEGIA.md).
Conexión de datos/broker y CSV: [`docs/PROVEEDORES.md`](docs/PROVEEDORES.md).

### Estructura de carpetas

```
server/
  main.py             FastAPI + estáticos + lifespan
  api.py              REST + WebSocket
  engine.py           orquestación, snapshot, control, persistencia
  config.py           Settings validados + config.json atómico
  models.py           Bar, Signal, Position, Order, TradeRecord
  risk.py             gestión de riesgo independiente
  execution.py        ejecución paper y brackets
  db.py               SQLite (WAL)
  stats.py            métricas de rendimiento
  backtest.py         motor de backtesting y variantes
  strategy/
    orb.py            Opening Range
    smt.py            pivotes y divergencias NQ/ES
    strategy.py       máquina de fases determinista
    indicators.py     agregación, ATR, VWAP, swings
  market/
    feed.py           MarketFeed, replay, CSV, adaptador live
    synthetic.py      generador determinista (SIMULADO)
frontend/src/         React + TS + CSS (7 pantallas)
tests/                pytest (estrategia, SMT, riesgo, ejecución, backtest, snapshot)
data/                 config.json y yedbot.db (generados, fuera de git)
docs/                 arquitectura, estrategia y proveedores
```

## 5. Persistencia y reinicio

SQLite en `data/yedbot.db` guarda operaciones cerradas, eventos, curva de equity, el
estado del motor y la posición abierta. Al reiniciar:

- se restauran la posición y su bracket SL/TP (guardados en `kv`);
- se reconstruye la equidad a partir de las operaciones reales registradas;
- se conservan los contadores del día si la sesión coincide;
- los datos de replay se reinician, pero no se evalúan velas anteriores a la entrada de
  la posición restaurada.

Para empezar de cero sin historial de demo:

```bash
python -m server.reset --yes
```

El comando archiva la base, la configuración y el log en `backups/`, borra operaciones,
eventos, equity, backtests y estado del motor, y deja el perfil en `feed.provider=csv`
apuntando a `data/real/bars_mnq_nq_es_1m.csv`. Si ese CSV no existe, el motor no arranca:
no se sustituye por datos sintéticos. `--yes` es la confirmación explícita del borrado.
Para ver primero los conteos y el directorio de archivo previsto, sin tocar nada:

```bash
python -m server.reset --dry-run
```

Este reinicio de consola es un borrado operativo completo y siempre elimina los backtests.
El botón **Reiniciar estadísticas** de la interfaz (y `POST /api/stats/reset`) reinicia
solo operaciones, equidad y eventos. La interfaz muestra la previsualización de
`GET /api/stats/reset/preview`, que recibe `delete_backtests` y `archive` y devuelve
`counts` (siempre con el total de backtests), `delete_backtests`,
`requires_confirmation` y `archive`. Para guardar una copia previa se envía
`archive=true`; el POST devuelve su ruta real en `archive_path` (o `null`). Los
backtests se conservan salvo que se envíe `delete_backtests=true` junto con
`confirm_delete_backtests=true`. No se acepta el alias `confirm`.

Si una fila legacy inválida impide abrir `Store` o completar la migración, el
diagnóstico de solo lectura puede ejecutarse **antes** de cualquier migración:

```bash
python -m server.diagnostics --db data/yedbot.db
```

Abre SQLite en modo de solo lectura, no crea tablas ni backups y señala en
`migration_blockers` las filas que harían abortar el backfill, con el problema
concreto (`metrics_invalid`, `dataset_invalid`, `created_ts_invalid`, etc.). Si
se detectan bloqueos, el comando termina con código 1.

Para reparar filas legacy **válidas pero no indexadas**, la API expone una
previsualización sin escrituras y una ejecución explícita:

```bash
# Dry-run: solo reporta qué se reindexaría
curl http://127.0.0.1:8765/api/backtest/runs/legacy-repair

# Reindexación real; hay que desactivar el dry-run de forma explícita
curl -X POST 'http://127.0.0.1:8765/api/backtest/runs/legacy-repair?dry_run=false'
```

El reporte incluye las filas válidas (`would_reindex` o `reindexed`) y las
inválidas con sus problemas. La reparación solo inserta en `backtest_runs` y
`backtest_results`; nunca escribe en `backtests` y no modifica estrategia ni
configuración.

### Dataset real con Massive

El plan **Futures Basic gratuito** de Massive cubre dos años de barras de 1 minuto por
contrato, suficiente para la ventana de desarrollo del protocolo. El adaptador está en
`server/market/massive_fetch.py` y no descarga el holdout:

```bash
# PowerShell
$env:MASSIVE_API_KEY="tu_clave"
python fetch_data.py --activate
```

El comando descubre los contratos trimestrales MNQ/NQ/ES, descarga 2025-01-10 →
2026-06-30, rellena únicamente minutos aislados, valida el CSV con el mismo cargador del
bot y, si todo pasa, activa `feed.provider=csv` en `data/config.json`. El motor sigue
detenido hasta que pulses **Iniciar**. La clave se lee de `MASSIVE_API_KEY`; nunca se escribe
en el CSV ni en la configuración. Para más de dos años o para el dataset confirmatorio
completo, Databento sigue siendo la alternativa documentada.

## 6. Backtesting

Desde **Estadísticas → Backtesting**:

- ejecutar la estrategia completa (`ORB + SMT + retesteo`);
- comparar 4 variantes sobre el **mismo dataset**: ORB solo, ORB+SMT, ORB+retesteo y completa;
- comparar presets aislados de frecuencia y Stop Loss (retroceso 30/38.2%, nivel ORH/ORL,
  SMT 90/120 min, tolerancia 12/16 ticks, validez 180/240 min, swing 5/6, buffer 8/12,
  recuperación on/off, 2.0R/2.5R y tope de SL 600 con entrada directa/stop profundo)
  con baseline y deltas;
- elegir número de sesiones y fecha de inicio de la muestra (permite separar
  entrenamiento/validación/prueba de forma manual);
- resultados con comisiones, slippage acotado, profit factor, expectativa, drawdown, Sharpe,
  Sortino, R medio, MFE/MAE, drawdown abierto y curva de equity.

El historial `GET /api/backtest/runs` conserva `limit/offset` y añade paginación
estable por cursor: la respuesta incluye `has_more` y `next_cursor`; para la
siguiente página se envía `cursor=<next_cursor>`. Admite filtros `date_from`,
`date_to`, `dataset` (o `dataset_id`) y `label` (búsqueda sin distinguir
mayúsculas). El cursor se ancla a `(created_ts, id)`, por lo que insertar
corridas nuevas no desplaza ni duplica las páginas ya abiertas. El historial, el
detalle de la corrida, `/api/backtest/latest` y el detalle de cada resultado
exponen siempre el mismo bloque plano de cinco claves: `ledger_status`,
`hypothesis_id`, `ledger_event_id`, `ledger_event_sha256` y `ledger_error`.
`null` significa que la corrida no tiene outbox; `ledger_status` distingue
`pending` de `sent`, y `ledger_event_id`/`ledger_event_sha256` aparecen juntos
solo cuando el vínculo está confirmado. Un `sent` con ambos en `null` es una
corrida anterior a v5 pendiente de conciliación. El hash identifica la entrada
JSONL canónica que acredita el registro. El estado operativo del outbox
(`status`, `attempts`, `last_error`) se consulta en
`GET /api/backtest/ledger/{run_id}`.

Las corridas que quedaron en `sent` antes de la migración v5 no tienen vínculo
guardado. `POST /api/backtest/ledger/reconcile` lo reconstruye emparejando cada
outbox con una única entrada `experiment.completed` por `run_id` o `result_id`
(incluido el formato histórico que usaba el id del resultado como `run_id`),
sin cambiar el estado ni los intentos ni añadir entradas al ledger. La respuesta
informa `scanned`, `linked`, `updated` y `unresolved`: cada registro que no se
puede reconstruir aparece con su motivo (`ledger_entry_missing`,
`ledger_entry_ambiguous`, `ledger_entry_without_event_id`,
`ledger_event_already_linked` o `ledger_unreadable`) y, cuando corresponde, los
`candidate_event_ids`. Repetir la conciliación no duplica ni reescribe vínculos
ya resueltos.

El generador sintético es determinista por fecha, así que un replay y su backtest son
comparables. **Los resultados sintéticos validan lógica, no rentabilidad.** Para un
backtest o replay con historia real, exporta un CSV de velas 1m de MNQ, NQ y ES y valídalo con
`python -m server.market.csv_data ruta.csv` o desde **Configuración → Avanzado → Validar CSV**.
El feed CSV exige timestamps idénticos entre las tres series, una sesión RTH completa de
09:00–16:00 ET y días hábiles: un hueco intra-sesión, un OR incompleto, una sesión completa
ausente, un cierre anticipado no oficial o barras en fin de semana se rechazan y bloquean
replay/backtest. Los cierres anticipados oficiales de CME para índices (3 de julio a las 13:00 ET;
día después de Thanksgiving y Nochebuena a las 13:15 ET) se validan contra su ventana corta.
El premarket opcional se permite, pero no cuenta como sesión RTH; un CSV con solo premarket
no es válido. La calidad se muestra como **HISTÓRICO REAL · CSV**; el
generador se muestra siempre como **SIMULADO · NO ES MERCADO REAL**.
Cada backtest guarda la identidad del dataset (`dataset_id` y hash del archivo), la identidad de la
serie efectiva (`series_id`), el rango real de sesiones usadas, los contratos declarados, sus
vencimientos, el contrato activo por sesión, el plan de rolls y la configuración completa de feed y
ejecución. Si se indica `start_date` con CSV, se aplica como fecha mínima o se rechaza si queda fuera
del rango. Con `contract`/`expiry`, el feed selecciona el vencimiento más próximo, permite elegir
serie `raw` o `adjusted` y excluye por defecto la sesión de roll (la última del contrato saliente).
Formato y reglas: [`docs/PROVEEDORES.md`](docs/PROVEEDORES.md#3-csv-histórico-real).

Los presets de investigación se ejecutan sin arrancar el servidor y sin tocar la
configuración activa:

```bash
python -m server.backtest --days 20 --preset entry_retrace_382 --preset sl_buffer_12
python -m server.backtest --days 20 --preset sl_cap_600 --preset direct_sl_cap_600 --preset deep_stop_sl_cap_600
python -m server.backtest --days 20 --all --out reports/backtest/presets.json
```

La comparación distingue `stop_cap_sessions` de `qty_zero_sessions`: el stop superó el
tope o, aun cabiendo, el presupuesto de riesgo no alcanza para un contrato.

Detalle de parámetros, fórmulas, presets y lectura de resultados en
[`docs/AJUSTES_FRECUENCIA_SL.md`](docs/AJUSTES_FRECUENCIA_SL.md).

Antes de ejecutar un backtest con historia real, el procedimiento está **pre-registrado**:
ventana 2025-01-10 → 2026-10-30, seis bloques trimestrales de desarrollo, holdout sellado de
86 sesiones, configuración congelada, métricas y puertas de aceptación. El documento y su
hash están en [`docs/PROTOCOLO_BACKTEST.md`](docs/PROTOCOLO_BACKTEST.md) y
`docs/protocolo_backtest.lock.json`. Las fuentes concretas para obtener 1m con contratos y
rolls, con costes y limitaciones, están en
[`docs/PROVEEDORES.md`](docs/PROVEEDORES.md#41-opciones-concretas-para-1m-con-contratos-y-rolls).

### Auditoría de la instancia 8765

Configuración efectiva, P&L paper y mejoras priorizadas de la instancia manual:
[`docs/CONFIG_8765_RENTABILIDAD.md`](docs/CONFIG_8765_RENTABILIDAD.md). Es un análisis
read-only; no modifica ni reinicia el 8765.

## 7. Pruebas

```bash
python -m pytest -q
```

Cubren: congelado del OR, pivotes sin repintado, SMT alcista/bajista, sizing por tick,
límites diarios, brackets SL/TP, barra ambigua (SL primero y su informe), gaps de stop al open,
slippage en target, tope `max_slippage_ticks`, MFE/MAE, drawdown abierto, generación de señal
completa, backtest, contrato del snapshot, validación CSV, calendario de vencimientos, contrato
activo, series raw/ajustadas y exclusión de sesiones de roll.

### Auto-push de commits

El hook está versionado en `.githooks/post-commit`, pero cada clon debe activarlo:

```bash
git config --local core.hooksPath .githooks
```

Solo empuja commits de `main` a `origin/main`; si falla, deja el commit local y lo
registra en `.git/auto-push.log`. Instrucciones completas y desactivación temporal en
[`docs/GIT_AUTO_PUSH.md`](docs/GIT_AUTO_PUSH.md).

## 8. Seguridad

- Sin credenciales en el código ni en la configuración de la app; `.env` está ignorado.
- El servidor escucha en `127.0.0.1` por defecto (terminal local, sin autenticación remota).
- LIVE desactivado por defecto y bloqueado hasta implementar el adaptador del broker.
- Órdenes duplicadas: bloqueo por señal ejecutada, posición abierta y orden pendiente.
- Parada de emergencia: bloquea entradas, cancela órdenes y permite cerrar posiciones,
  registrando el motivo.

## 9. Limitaciones conocidas

- No hay conexión real a broker ni feed en vivo; el adaptador lanza un error explicativo.
- Los datos por defecto son **simulados**; las métricas de la demo no son evidencia de nada.
- El backtest no incluye modelo de libro de órdenes ni latencia variable; usa slippage fijo
  acotado por `max_slippage_ticks` y una convención conservadora SL-primero en velas ambiguas.
- La variante bajista de SMT está implementada pero **no validada estadísticamente** con
  datos reales.
- El replay simulado está diseñado para ejercitar todas las fases; su win rate no es realista.
- No se incluye optimización automática de parámetros; se evita deliberadamente el
  sobreajuste seleccionando por profit factor, drawdown y estabilidad, no solo por beneficio.
- La interfaz es local y de un solo operador; no hay multiusuario ni autenticación remota.
