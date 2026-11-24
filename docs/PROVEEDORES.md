# Datos y broker

## 1. Estado real de las integraciones

| Pieza | Estado |
|---|---|
| Replay simulado | Implementado. Etiquetado como **SIMULADO** en la UI. |
| CSV histórico | Implementado para replay y backtest. |
| Feed en vivo | **No implementado.** `LiveFeed` lanza un error explicativo. |
| Broker / órdenes reales | **No implementado.** LIVE está bloqueado. |
| Ejecución paper | Implementada con slippage, comisiones, brackets y parciales. |

No hay claves, endpoints ni conexiones simuladas presentadas como reales. Si falta una
suscripción o permiso, el sistema lo dice y no arranca en vivo.

## 2. Datos que la estrategia necesita

- Velas de **1 minuto** de MNQ (o NQ) y ES, con **timestamps sincronizados**.
- Sesión regular de EE. UU. y zona `America/New_York`, completa de 09:00 a 16:00 ET. En los cierres anticipados oficiales de CME para índices, la ventana termina a las 13:00 ET (3 de julio) o 13:15 ET (día después de Thanksgiving y Nochebuena).
- Volumen por vela (se usa en el gráfico; la señal no depende de él).
- Precios ajustados al tick de 0.25 en NQ/MNQ y ES.
- Sin huecos intra-sesión: una vela faltante en cualquier serie invalida el dataset y desplaza la comparación SMT.

Si el feed entrega NQ y no MNQ, usa NQ como referencia y mantén MNQ para ejecución; el
sistema asume que ambos siguen el mismo precio con un basis estable.

## 3. CSV histórico real

### 3.1 Formato exacto

CSV en formato largo con cabecera, separador coma y una fila por **símbolo, contrato y minuto**:

| Campo | Obligatorio | Formato |
|---|---|---|
| `timestamp` | Sí | ISO-8601 con zona (`2025-06-03T09:30:00-04:00`, `...Z`) o epoch en **segundos**. Debe caer en un minuto exacto (`:00`). |
| `symbol` | Sí | `MNQ`, `NQ` o `ES` (se normaliza a mayúsculas). |
| `open`, `high`, `low`, `close` | Sí | Números positivos y finitos; `high >= max(open, close)` y `low <= min(open, close)`. |
| `volume` | No | Número >= 0; si falta se usa 0. |
| `contract` | No | Contrato real (`NQZ26`, `MNQH27`, `ESU27`). Si la columna existe, no puede quedar vacía y debe corresponder al símbolo. |
| `expiry` | No | Vencimiento `YYYY-MM-DD`. Requiere `contract`. Si falta, se deriva el tercer viernes del mes del contrato (o el día hábil anterior si es feriado). Un contrato no puede tener dos vencimientos distintos ni aparecer con velas posteriores a su vencimiento. |

Ejemplo de formato (ilustrativo, no es historia real y **no es una sesión completa**: el validador estricto lo rechaza): `docs/ejemplo_bars.csv`.

```csv
timestamp,symbol,open,high,low,close,volume,contract,expiry
2025-06-03T09:30:00-04:00,MNQ,20838.25,20840.00,20836.50,20839.75,1200,MNQZ26,2026-12-18
2025-06-03T09:30:00-04:00,NQ,20841.00,20842.75,20839.25,20842.50,980,NQZ26,2026-12-18
2025-06-03T09:30:00-04:00,ES,5730.25,5731.00,5729.75,5730.75,2100,ESZ26,2026-12-18
```

Reglas que aplica el validador (`server/market/csv_data.py`):

- **Una fila por símbolo, contrato y timestamp.** Los duplicados del mismo contrato se rechazan indicando la línea; dos contratos distintos sí pueden coexistir en el mismo minuto para calcular el spread de roll.
- **Sin zona horaria no se acepta** para ISO-8601; se evita asumir UTC o ET por error.
- **Las tres series son obligatorias**: MNQ (ejecución), NQ (referencia) y ES (comparación).
  No se deriva MNQ desde NQ ni se rellena una serie ausente.
- **Alineación exacta:** los conjuntos de timestamps de MNQ, NQ y ES deben ser idénticos.
  No hay interpolación ni tolerancia; una vela desplazada invalidaría el SMT. Si falta un
  minuto en una serie, el informe indica cuántos faltan y las primeras marcas desalineadas.
- **Sesión RTH completa:** cada día hábil presente debe cubrir 09:00–16:00 ET con una vela de
  1m por minuto (420 velas). La ventana incluye el Opening Range 09:00–10:00. Un minuto faltante
  dentro de la sesión es error y bloquea replay y backtest; no se rellena ni se interpola.
- **Cierre anticipado oficial de CME:** el 3 de julio (cuando es día hábil) la sesión termina a las
  13:00 ET (240 velas) y el día después de Thanksgiving y Nochebuena a las 13:15 ET (255 velas).
  Se exige cada minuto de esa ventana corta; si falta uno, el dataset se rechaza. Cualquier otro
  corte antes de las 16:00 ET se considera truncamiento y también se rechaza.
- **Sesión completa ausente:** entre la primera y la última sesión del CSV no puede faltar un día
  hábil completo. El validador recorre el calendario, no solo los días que aparecen en el archivo.
  Un día de cierre anticipado oficial omitido es opcional y no cuenta como sesión ausente.
- **Premarket opcional:** las velas anteriores a 09:00 se permiten y se informan, pero no cuentan
  para completar la sesión. Un CSV solo con premarket se rechaza; no se inventa el RTH faltante.
- **Opening Range completo:** se exigen las 60 velas de 09:00–10:00. Un OR parcial no genera señal.
  Como la sesión completa contiene todos los minutos, las agregaciones de 5/15/30m también quedan
  completas; si falta un minuto, falla la sesión antes de agregar.
- **Calendario:** sábados, domingos y feriados de mercado no deben traer barras. Si un CSV incluye
  una sesión en día no hábil, se rechaza. Los huecos entre sesiones (overnight, fin de semana,
  feriado) son normales y no cuentan como huecos intra-sesión. Los cierres anticipados oficiales
  se reconocen por fecha y hora ET y no se confunden con feriados.
- **OHLC incoherente, precios no positivos, volumen negativo o epoch en milisegundos** se rechazan.
- **Contrato activo:** para cada sesión se elige, entre los contratos con barras, el vencimiento más próximo que aún no ha vencido. La última sesión del contrato saliente se marca como **sesión de roll**; el cambio al entrante se materializa al día siguiente.
- **Rolls:** la sesión de roll se excluye del replay y del backtest por defecto (`feed.exclude_roll_sessions`). La validación de sesión completa se aplica antes de excluirla, de modo que un CSV truncado en el roll también se rechaza.
- **Serie raw/ajustada:** `feed.series_mode=raw` conserva los precios tal como vienen. `adjusted` desplaza el histórico del contrato saliente por el spread del roll: último cierre solapado entre ambos contratos o, si no hay solape, apertura del contrato nuevo menos cierre del anterior. La serie efectiva tiene su propio `series_id`.
- Si se incluye `contract`, se registra en el manifiesto junto con `expiry`, `contracts_by_session`, `rolls`, `roll_sessions` y `excluded_sessions`. Sin esa columna, el dataset se marca como `contract_column: false` y no se le atribuye ningún contrato.

### 3.2 Validar antes de cargar

Desde la terminal, sin arrancar el motor:

```bash
python -m server.market.csv_data ruta/al/bars.csv
# Variantes:
python -m server.market.csv_data ruta/al/bars.csv --series raw --include-roll-sessions
```

Devuelve JSON con `ok`, número de velas comunes, rango temporal, conteo por serie, huecos,
estado por sesión (`session_validation`), errores y avisos; sale con código 1 si el archivo no
es válido o si alguna sesión está incompleta.

Desde la interfaz: **Configuración → Avanzado → Validar CSV**. Valida la ruta escrita en el
formulario (aunque aún no esté guardada) y muestra el mismo informe. El botón no modifica la
configuración ni reinicia el motor.

### 3.3 Activar el replay histórico

1. Exporta las velas de 1m de MNQ, NQ y ES de tu proveedor y valida el archivo.
2. En **Configuración → Avanzado**, elige `Proveedor de datos = CSV histórico` y escribe la ruta
   (por ejemplo `data/bars.csv`; relativa al proyecto o absoluta).
3. Guarda. El motor reinicia la sesión y carga el CSV; si la validación falla, el cambio se
   rechaza y verás el error del proveedor en la consola.
4. Ajusta `Velocidad de replay` (velas/s). No es un feed en vivo: reproducir histórico no envía
   órdenes reales y sigue siendo paper trading.

El backtest con CSV usa el mismo cargador y la misma validación de alineación, sesión completa y
calendario. Se etiqueta como `historical` y no muestra el aviso de datos sintéticos.

Cada backtest guarda:

- `dataset.id`: hash canónico del contenido del CSV, independiente de la ruta;
- `dataset.file_hash`: SHA-256 de los bytes del archivo;
- rango completo del archivo y rango efectivo de las sesiones usadas;
- contratos declarados, vencimientos, contrato activo por sesión, plan de rolls y `series_id` de la serie usada;
- configuración completa de `feed` y `execution` (comisiones, slippage, modelo de fill);
- `start_date` solicitado y criterio de selección (`start_date` o `last_n`).

`start_date` se aplica como fecha mínima de sesión en CSV. Si queda fuera del rango del archivo,
la petición se rechaza explícitamente; no se ignora ni se sustituye por las últimas N sesiones.

### 3.4 Cómo distingue la interfaz datos reales y simulados

| Origen | Insignia superior | Significado |
|---|---|---|
| `simulated` | **SIMULADO · NO ES MERCADO REAL** (ámbar) | Generador sintético de desarrollo; el gráfico muestra un aviso permanente. |
| `csv` | **HISTÓRICO REAL · CSV** (azul) | Velas históricas reales validadas y alineadas; se reproducen, no son cotización en vivo. |
| `live` | **DATOS EN VIVO** (verde) | Solo con un adaptador de proveedor real implementado; hoy no está disponible. |
| sin feed | **SIN CONEXIÓN / DATOS RETRASADOS** (rojo) | No hay datos o están vencidos. |

La consola muestra la calidad (`Simulada (no real)`, `Histórico real (CSV)`, `Real en vivo`), el
número de velas y el detalle del proveedor. El dashboard y el gráfico usan la etiqueta del feed,
no un texto fijo.

## 4. Proveedores a evaluar

| Proveedor | Datos | Ejecución | Requisitos típicos |
|---|---|---|---|
| **Interactive Brokers** | CME futuros, histórico y tiempo real | TWS/IB Gateway API | Cuenta con permisos de datos CME, TWS o Gateway abierto, `IBKR_*`. |
| **Tradovate** | Futuros CME | API REST/WebSocket | Cuenta, app registrada, credenciales de API, suscripción de datos. |
| **Rithmic** | Futuros CME | API propietaria | Cuenta Rithmic, gateway, credenciales y permisos. |

Los detalles concretos (endpoints, cuotas, permisos, horarios de datos) cambian y deben
verificarse en la documentación oficial del proveedor y del bróker antes de contratar.
Esta tabla no sustituye esa verificación.

### 4.1 Opciones concretas para 1m con contratos y rolls

Comprobado el **2026-11-19**. El protocolo de backtest exige una fila por contrato y minuto,
con `contract` y `expiry`, no una serie continua ya ajustada. Eso descarta parte de las
opciones baratas aunque vendan "datos de NQ".

| Proveedor | Qué entrega | Contratos y rolls | Precio orientativo | Veredicto |
|---|---|---|---|---|
| **Massive Futures Basic** | `GET /futures/v1/aggs/{ticker}` con `resolution=1min`; contratos individuales y `/contracts` con vencimientos | Ticker por contrato (`MNQH5`) y 2 años de histórico en el plan gratuito | Gratis; 5 llamadas/minuto | **Recomendada para desarrollo** |
| **Databento** (`GLBX.MDP3`) | `ohlcv-1m` desde 2010, CSV/JSON/DBN, timestamps UTC con inicio de barra | Símbolos crudos por contrato (`NQZ5`) y esquema `definition` con `expiration` | 70 USD/GB histórico; 125 USD de crédito al registrarse | **Recomendada para historia completa** |
| **Kibot** | 1m desde 2009, CSV en hora del Este, inicio de barra, contratos vencidos incluidos | Continuos y todos los contratos individuales; sin fichero de rolls explícito | 820 USD todo; 600 USD top-25; 520 USD solo continuos | Alternativa válida |
| **FirstRate Data** | 1m desde 2008 (MNQ desde 2019), CSV en hora del Este | Contratos individuales + 3 series continuas; lista de rolls en "Other Data" | Pago único (consultar en la ficha); actualizaciones 59,95 USD/mes tras el primer mes | Alternativa válida |
| **CME DataMine** | MBO, MBP, BBO, Time & Sales, resumen EOD y volumen/OI; **no hay dataset de barras 1m** (habría que agregarlas) | Por producto, todos los vencimientos | Licencia y precio por petición | No viable sin trabajo extra |
| **Interactive Brokers** | 1m vía TWS API; Web API no sirve contratos vencidos | Vencidos solo hasta 2 años después del vencimiento; límite de 60 peticiones/10 min | Permisos de datos CME + cuenta | No recomendada |
| **MarketParquet / HistoricalFuturesData / FinzData** | Parquet barato, continuo ratio-adjusted o por contrato | El continuo no trae columna de contrato; procedencia y licencia no verificadas | 59–79 USD | No apta para un backtest auditable |
| **Yahoo (`NQ=F`) / Kaggle** | 1m solo 30 días / procedencia desconocida | Sin contratos ni rolls verificables | Gratis | Rechazada |

#### Databento: por qué es la opción para historia completa

- Es distribuidor directo de CME y entrega el símbolo crudo de cada contrato, que es lo que
  necesita el cargador para construir el manifiesto de contratos, vencimientos y rolls.
- El esquema `definition` aporta `expiration` por instrumento; no hay que deducir el
  vencimiento del código.
- El coste real para este proyecto es pequeño: una sesión de un contrato en `ohlcv-1m` ocupa
  unos 77 KB; 454 sesiones × 3 símbolos × ~2,5 contratos en circulación ≈ 0,25–0,35 GB, es
  decir **20–25 USD**, cubiertos por el crédito inicial de 125 USD.
- Permite descargar por API y repetir la adquisición de forma determinista, que es lo que
  exige un protocolo pre-registrado.

#### Massive Futures Basic: dataset de desarrollo sin coste

El adaptador `server/market/massive_fetch.py` usa el plan gratuito de Massive. El plan
incluye dos años de barras de 1 minuto por contrato y el endpoint de contratos necesario
para obtener `settlement_date`; limita a cinco peticiones por minuto y el cliente espacia
las llamadas. El comando por defecto construye **solo desarrollo** y rechaza el holdout:

```bash
$env:MASSIVE_API_KEY="..."
python -m server.market.massive_fetch --activate
```

La descarga usa contratos individuales (no una serie continua), valida el CSV con el mismo
cargador del bot y solo activa la configuración si la validación es correcta. Para 2019–2024
o para el rango confirmatorio completo, Massive Basic no llega: usa Databento o una fuente
con cobertura verificable.

Petición tipo (la clave va en `DATABENTO_API_KEY`, nunca en el repositorio):

```python
import os
import databento as db

client = db.Historical(os.environ["DATABENTO_API_KEY"])
# 1) Metadatos de todos los contratos del producto
defs = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    schema="definition",
    stype_in="parent",
    symbols=["NQ.FUT", "MNQ.FUT", "ES.FUT"],
    start="2024-12-31T00:00:00Z",
    end="2026-10-31T00:00:00Z",
    stype_out="raw_symbol",
).to_df()
# 2) Velas 1m solo de los contratos que fija el calendario de rolls
bars = client.timeseries.get_range(
    dataset="GLBX.MDP3",
    schema="ohlcv-1m",
    stype_in="raw_symbol",
    symbols=["NQH5", "NQM5"],  # sustituir por los 24 contratos del protocolo
    start="2025-01-01T00:00:00Z",
    end="2026-10-31T00:00:00Z",
    stype_out="raw_symbol",
).to_df()
```

Normalización obligatoria antes de escribir el CSV:

- `ts_event` es UTC en nanosegundos y marca el **inicio** de la barra: convertir a
  `America/New_York` y filtrar 09:00–15:59 ET.
- El símbolo crudo de CME usa un dígito de año (`NQZ5`); el cargador exige dos
  (`NQZ25`). Normalizar sin cambiar el mes ni la raíz.
- Añadir `expiry` desde `definition`; no inventar el tercer viernes si el proveedor da otra
  fecha.
- Descartar barras de días no hábiles y cualquier barra fuera de la ventana RTH.

#### Huecos: la trampa común de todos los proveedores

Databento, Kibot y FirstRate **omiten los minutos sin operaciones**. El validador del
proyecto exige 420 velas por sesión y rechaza cualquier minuto faltante, así que el
preprocesado debe rellenar solo los minutos aislados sin operaciones con una barra plana
(`open=high=low=close=cierre anterior`, `volume=0`) y registrar cada relleno. Nunca se
interpola entre minutos con operaciones ni se rellena una sesión entera. La regla completa
está en [`docs/PROTOCOLO_BACKTEST.md`](PROTOCOLO_BACKTEST.md#25-preprocesado-permitido-y-prohibido).

#### Licencia y archivo

Los datos se compran para investigación personal. El CSV no se redistribuye ni se sube al
repositorio; se guarda en `data/real/` (ignorado) y se archiva su SHA-256 junto al informe.

El procedimiento completo, las fechas, la configuración congelada y los criterios de
aceptación están en [`docs/PROTOCOLO_BACKTEST.md`](PROTOCOLO_BACKTEST.md).

## 5. Implementar un feed en vivo

1. Crea una subclase de `MarketFeed` en `server/market/feed.py` o un módulo nuevo:

```python
class TradovateFeed(MarketFeed):
    kind = "live"
    label = "TRADOVATE · LIVE"
    quality = "live"

    async def start(self) -> None: ...
    async def next_tick(self) -> Tick | None: ...
    def describe(self) -> dict: ...
```

2. `next_tick()` debe devolver `Tick(ts=..., bars={"MNQ": Bar, "NQ": Bar, "ES": Bar})`
   con velas **cerradas** de 1 minuto y timestamps alineados.
3. Registra la clase en `build_feed()` cuando `settings.feed.provider == "live"`.
4. Lee credenciales de variables de entorno (`TRADOVATE_*`, `IBKR_*`, `RITHMIC_*`), nunca
   de la configuración ni del frontend.
5. Prueba primero con `quality = "simulated"` o `"historical"`; solo después cambia a
   `"live"`, que es lo que la UI muestra como dato real.
6. Verifica reconexión, velas perdidas, duplicados y latencia antes de operar.

## 6. Implementar un broker

`ExecutionEngine` (`server/execution.py`) es el ejecutor paper. Su interfaz es deliberadamente
pequeña:

```python
arm(signal)                  # registra la orden de entrada
on_bar(bar)                # fills y gestión SL/TP (usa settings.execution)
close(price, ts, reason)     # cierre → TradeRecord
cancel_all(reason)           # cancela pendientes
orders_snapshot()            # órdenes visibles en la UI
```

Para un broker real:

1. Implementa un adaptador que cumpla esos métodos y traduzca a órdenes bracket nativas.
2. Maneja rechazos, ejecuciones parciales y reconexión; registra cada respuesta.
3. Reconcilia posiciones locales con las del broker antes de habilitar entradas.
4. Mantén los brackets en el broker, no solo en memoria.
5. No actives LIVE hasta superar una sesión completa en paper/demo con las mismas reglas.

## 7. Checklist antes de LIVE

- [ ] Cuenta demo validada con el proveedor y permisos de datos CME confirmados.
- [ ] Feed entrega NQ y ES sincronizados; reconexión probada.
- [ ] Backtest con CSV real y walk-forward aceptable en profit factor, drawdown y estabilidad.
- [ ] Paper trading durante varias sesiones sin órdenes duplicadas ni posiciones huérfanas.
- [ ] Límites de riesgo configurados y verificados.
- [ ] Adaptador de broker implementado con reconciliación y brackets nativos.
- [ ] `live_enabled = true`, broker definido y confirmación `HABILITAR LIVE`.
- [ ] Supervisión manual durante la primera sesión real.

Aun cumpliendo todo, **no hay garantía de rentabilidad**. El modo LIVE de este repositorio
seguirá rechazando el arranque mientras no exista un adaptador validado.
