# Protocolo pre-registrado — backtest con datos reales

**Versión:** 1.2
**Fecha de congelación:** 2026-11-20
**Estado:** congelado y **no ejecutado**. Este documento se escribe antes de descargar datos
y antes de calcular cualquier resultado.
**Revisión 1.2 (pre-ejecución, regla de roll):** el contrato saliente sigue activo en la
sesión de roll y el entrante pasa a serlo la sesión siguiente. La sesión de roll se sigue
excluyendo; no cambian ventanas, configuración, dataset ni umbrales. El holdout sigue sellado
y no observado.
**Instrumento:** MNQ (ejecución), NQ (referencia) y ES (comparación SMT).
**Estrategia:** ORB + SMT + retesteo del 50 % del Opening Range (variante `full`).

> Este protocolo no demuestra que la estrategia sea rentable. Fija de antemano qué se va a
> medir, sobre qué fechas y con qué umbrales se aceptará o rechazará el resultado. Su valor
> es que impide cambiar las reglas después de ver el backtest.

---

## 0. Reglas de pre-registro

1. Todo lo fijado aquí (ventana, contratos, configuración, métricas y umbrales) se decide
   antes de mirar el primer resultado.
2. El documento se congela con el hash SHA-256 registrado en
   `docs/protocolo_backtest.lock.json`. Cualquier cambio **sustantivo** posterior exige
   **versión nueva** y un **holdout nuevo**; no se puede reutilizar el holdout de la versión
   anterior. Las correcciones editoriales pre-ejecución que no alteren endpoint, ventanas,
   configuración, dataset ni umbrales se registran como revisión de versión, regeneran el hash
   y no requieren holdout nuevo mientras este siga sin observarse.
3. No se ejecuta el holdout hasta que la fase de desarrollo supere todas las puertas duras.
   Si el desarrollo falla, el holdout queda sellado y no se inspecciona.
4. El holdout se ejecuta **una sola vez**. Solo se admite una segunda ejecución si la primera
   falló por un defecto técnico documentado (archivo corrupto, excepción), nunca para cambiar
   parámetros ni para "repetir por si acaso". Ambas ejecuciones se reportan.
5. No se optimizan parámetros en esta versión. Las cuatro variantes del motor son las únicas
   comparaciones y solo `full` es confirmatoria.
6. Los datos, la configuración efectiva, los hashes y los resultados crudos se archivan con
   cada ejecución. El CSV del proveedor no se versiona ni se redistribuye.

---

## 1. Pregunta y endpoint confirmatorio

**Pregunta:** ¿la regla completa (ORB + SMT + retesteo) tiene una esperanza positiva después
de comisiones y slippage, estable entre trimestres y confirmada en una muestra que no se usó
para tomar ninguna decisión?

**Endpoint primario único:** variante `full` (`use_smt=true`, `entry_reference="or_mid"`).

Las variantes `orb`, `orb_smt` y `orb_retest` se reportan como **ablaciones descriptivas**.
No se usan para aprobar ni rechazar, y no se corrige por comparaciones múltiples porque solo
hay un endpoint confirmatorio. Si se quisiera promover otra variante, sería un protocolo
nuevo con su propio holdout.

**Hipótesis nula:** la esperanza neta en R de `full` es menor o igual que cero.
**Hipótesis alternativa:** es mayor que cero.

---

## 2. Datos

### 2.1 Ventana pre-registrada

| Bloque | Desde | Hasta | Sesiones de calendario | Sesiones evaluadas (sin rolls) |
|---|---|---|---|---|
| Desarrollo completo | 2025-01-10 | 2026-06-30 | **368** | **362** |
| — W1 | 2025-01-10 | 2025-03-31 | 55 | 54 |
| — W2 | 2025-04-01 | 2025-06-30 | 62 | 61 |
| — W3 | 2025-07-01 | 2025-09-30 | 64 | 63 |
| — W4 | 2025-10-01 | 2025-12-31 | 64 | 63 |
| — W5 | 2026-01-01 | 2026-03-31 | 61 | 60 |
| — W6 | 2026-04-01 | 2026-06-30 | 62 | 61 |
| **Holdout** | 2026-07-01 | 2026-10-30 | **86** | **85** |
| **Total** | 2025-01-10 | 2026-10-30 | **454** | **447** |

W5 empieza el 2026-01-01, que es feriado; la primera sesión efectiva es el **2026-01-02**.
El conteo de 61 ya excluye el 1 de enero.

Las cuentas de calendario usan el calendario del propio proyecto
(`server/market/sessions.py`), que ya excluye feriados de mercado y contempla los cierres
anticipados oficiales de CME (3 de julio a las 13:00 ET; día siguiente a Thanksgiving y
Nochebuena a las 13:15 ET). En 2026 el 3 de julio es el feriado observado del 4 de julio
(sábado) y se excluye por completo; por eso el holdout no tiene cierre anticipado.

Cada trimestre tiene **una** sesión de roll, que se excluye con
`feed.exclude_roll_sessions=true`: 7 en total. Por eso las ventanas se ejecutan con las
sesiones **evaluadas** (54, 61, 63, 63, 60, 61) y no con las de calendario. El parámetro
`days` de `run_variants` debe ser el número evaluado; de lo contrario la ventana se
desplazaría al trimestre siguiente al saltar la sesión de roll.

**Exclusión documentada:** el **2025-01-09** los futuros de índices de CME cerraron a las
09:30 ET por el Día Nacional de Luto (Jimmy Carter). Es una sesión truncada que el calendario
del proyecto no contempla y que no se rellena con datos inventados. Por eso la ventana empieza
el **2025-01-10**. Es la única exclusión adicional fuera del calendario habitual; no se
descarta ninguna otra sesión completa.

**Feriados con sesión abreviada:** el calendario del proyecto trata MLK, Presidents,
Memorial, Juneteenth y Labor como cierres completos, igual que Good Friday. CME abre algunas
de esas fechas (no Good Friday) con horario reducido; esas barras se descartan y la sesión no
se modela. Es una decisión conservadora y pre-registrada, no un hueco de datos: no se inventa
la parte faltante ni se opera una media sesión de feriado.

**Por qué esta ventana:** cubre casi 22 meses, desde enero de 2025 hasta octubre de 2026,
incluye regímenes de volatilidad distintos y deja 86 sesiones de calendario intactas (85
evaluadas) para el holdout. Se fija ahora para que no se pueda "elegir" un periodo favorable
después de ver los resultados. Si el proveedor no entrega exactamente este rango, **no se
sustituye por otro**: el protocolo se aborta y se redacta una versión nueva.

**No hay rango alternativo:** un rango más corto reduce la potencia y cambiaría los bloques;
no se admite como sustituto silencioso.

### 2.2 Contratos y rolls

- Solo contratos **trimestrales** de CME: `H` (marzo), `M` (junio), `U` (septiembre) y
  `Z` (diciembre). Nada de seriales mensuales.
- **Vencimiento:** el que declare el proveedor en el campo `expiration` de su esquema de
  definiciones. Si no está disponible, se usa el tercer viernes del mes con el ajuste de
  feriados de `server/market/contracts.py`.
- **Regla de roll pre-registrada:** el contrato **saliente** sigue siendo el activo en la
  primera sesión hábil con fecha **mayor o igual que `expiry − 8 días naturales`**; el
  **entrante** pasa a serlo la sesión siguiente. Es una regla de calendario, determinista y no
  depende del volumen observado. Esa primera sesión es la **sesión de roll** y se excluye
  (`feed.exclude_roll_sessions=true`); el entrante se evalúa desde su primera sesión completa.
- El CSV contiene **un solo contrato por símbolo y minuto**: el activo según esa regla. No se
  incluyen dos contratos solapados en el mismo minuto, porque el cargador elegiría el de
  vencimiento más próximo y alteraría el roll.
- Contratos esperados por símbolo: `H25, M25, U25, Z25, H26, M26, U26, Z26` → **8 por
  símbolo, 24 en total**. Transiciones: **7 por símbolo, 21 en total**, que caen en las
  mismas 7 fechas para MNQ, NQ y ES. El cambio de contrato se materializa en la sesión
  siguiente a cada roll. Sesiones efectivas tras excluir rolls: **447**.
- El CSV debe llevar las columnas `contract` y `expiry`. El código de contrato se normaliza
  a raíz + mes + **dos dígitos de año** (`NQZ25`, `MNQH26`, `ESU26`), aunque el proveedor use
  un solo dígito (`NQZ5`).

Con el calendario del proyecto, las 7 sesiones de roll esperadas son **2025-03-13**,
**2025-06-12**, **2025-09-11**, **2025-12-11**, **2026-03-12**, **2026-06-10** y
**2026-09-10**. La de junio de 2026 sale de un vencimiento el 2026-06-18, adelantado por
Juneteenth; si `definition.expiration` del proveedor declara otra fecha, manda el proveedor y
se documenta la diferencia.

### 2.3 Adquisición (fuente recomendada: Databento)

Detalle comparado de proveedores en
[`docs/PROVEEDORES.md`](PROVEEDORES.md#41-opciones-concretas-para-1m-con-contratos-y-rolls).

Procedimiento:

1. Crear cuenta en Databento y guardar la clave en la variable de entorno
   `DATABENTO_API_KEY`. Nunca en el repositorio, la configuración de la app ni el frontend.
2. Pedir el esquema `definition` del dataset `GLBX.MDP3` con simbología `parent`
   (`MNQ.FUT`, `NQ.FUT`, `ES.FUT`) para el rango completo. De ahí salen `raw_symbol`,
   `expiration` y el `instrument_id` de cada contrato.
3. Construir el calendario de contratos con la regla de 2.2 y pedir `ohlcv-1m` **solo para
   los 24 contratos necesarios**, con `stype_in="raw_symbol"` y `stype_out="raw_symbol"`.
4. Convertir `ts_event` (UTC, nanosegundos) a `America/New_York` y quedarse únicamente con
   las velas cuyo inicio esté entre **09:00 y 15:59 ET** en sesión regular, o hasta el cierre
   anticipado oficial (**12:59** o **13:14 ET**). Son **420**, **240** o **255** velas por
   símbolo y sesión.
5. Descartar cualquier barra en día no hábil según el calendario del proyecto.
6. Escribir el CSV largo con cabecera
   `timestamp,symbol,open,high,low,close,volume,contract,expiry`; antes de validar, aplicar
   el relleno de minutos aislados de 2.5 y guardar el CSV auxiliar de rellenos.
7. Validar con `python -m server.market.csv_data data/real/bars_mnq_nq_es_1m.csv --series raw`.
8. Archivar el SHA-256 del archivo y el `dataset_id`/`series_id` que devuelve el validador.

Estimación de coste: el esquema `ohlcv-1m` de CME cuesta 70 USD/GB y una sesión de un
contrato ocupa ~77 KB; 454 sesiones × 3 símbolos × ~2,5 contratos en circulación ≈ 0,25–0,35 GB,
es decir **~20–25 USD**, cubiertos por los 125 USD de crédito inicial. El coste no es la
barrera; la calidad y la alineación sí.

### 2.4 Reglas de aceptación del dataset

El dataset se rechaza entero si falla cualquiera de estas condiciones:

| ID | Condición |
|---|---|
| D1 | `ok=true` y `aligned=true` en el validador; `gaps.count=0`. |
| D2 | Las **454 sesiones del dataset completo** están presentes, completas y válidas; en desarrollo, **368/368** de calendario (**362** evaluadas); en holdout, **86/86** (**85** evaluadas). `invalid_sessions=0` y `missing_session_count=0`. |
| D3 | Cada sesión tiene 420 velas por símbolo (o 240/255 en cierre anticipado oficial) y el Opening Range 09:00–10:00 está completo. |
| D4 | `contracts_declared=true`; 24 contratos con `expiry`; 21 roll events; 7 sesiones de roll excluidas. |
| D5 | El contrato activo por sesión coincide con el calendario de 2.2 en los tres símbolos: saliente en la sesión de roll, entrante desde la sesión siguiente. |
| D6 | Huecos rellenados con barra plana (ver 2.5) ≤ **0,1 %** de los minutos de la ventana operativa (máximo **570** de **570 510** en el dataset completo, con los 3 cierres anticipados) y nunca dos minutos consecutivos. |
| D7 | Los timestamps están en ISO-8601 con zona (`-04:00`/`-05:00`) o epoch en segundos; ninguno en milisegundos. |
| D8 | El archivo se validó con `series_mode=raw` y `exclude_roll_sessions=true`, que es la configuración primaria. |

Si D1–D8 no se cumplen, no hay backtest: se corrige la adquisición o se cambia de proveedor.
No se "arregla" el CSV borrando sesiones ni rellenando precios.

### 2.5 Preprocesado permitido y prohibido

**Permitido**

- Convertir UTC → `America/New_York` conservando el instante.
- Filtrar a la ventana RTH 09:00–15:59 ET (o al cierre anticipado oficial: 12:59/13:14 ET).
- Eliminar barras de días no hábiles (el validador las rechaza).
- Normalizar el código de contrato a dos dígitos de año.
- Añadir `expiry` desde el esquema de definiciones del proveedor.
- Rellenar un minuto aislado sin operaciones con una barra plana
  (`open=high=low=close=cierre anterior`, `volume=0`). Es la convención documentada de
  Databento, Kibot y FirstRate: si no hubo operaciones, no imprimen barra. El relleno se
  registra en un CSV auxiliar con timestamp y símbolo, y se cuenta para D6.

**Prohibido**

- Interpolar precios entre minutos o entre sesiones.
- Derivar MNQ desde NQ, o rellenar una serie ausente.
- Usar una serie continua ajustada por el proveedor en lugar de contratos individuales.
- Reagregar desde velas de 5m o superiores.
- Descartar sesiones completas para "cuadrar" el rango.
- Retocar OHLC, volumen o expiraciones a mano.
- Elegir fechas, contratos o configuración después de ver los resultados.

### 2.6 Huella y congelación

Antes de la primera ejecución se registran:

- SHA-256 del CSV;
- `dataset_id`, `series_id` y `file_hash` del manifiesto del validador;
- rango efectivo (`selected_range`) y lista de sesiones usadas;
- plan de rolls y contrato activo por sesión;
- hash del protocolo y de la configuración congelada;
- versión del código (hash del árbol de trabajo; si no hay git, hash de los archivos
  `server/` y `tests/`).

Todo ello va en `reports/backtest/dataset_manifest.json`, común a todas las ventanas. El rango
efectivo de cada ventana se guarda en su JSON de resultados. Sin ese manifiesto, la ejecución
no cuenta.

---

## 3. Configuración congelada

Se usa un perfil aislado, nunca `data/` ni `profiles/dryrun/`. La configuración parte de los
**valores por defecto de `Settings()`**, no de la demo: los valores `min_range_ticks=5` y
`retest_tolerance_ticks=3` del perfil de demo se ajustaron para que el generador sintético
produjera operaciones y no se trasladan a datos reales.

| Grupo | Parámetro | Valor |
|---|---|---|
| Feed | `provider` | `csv` |
| Feed | `csv_path` | `data/real/bars_mnq_nq_es_1m.csv` |
| Feed | `series_mode` | `raw` |
| Feed | `exclude_roll_sessions` | `true` |
| ORB | `start` / `end` / `timezone` | 09:00 / 10:00 / America/New_York |
| ORB | `max_width_pct` | 1.2 |
| SMT | `pivot_depth` / `window_minutes` | 5 / 60 |
| SMT | `tolerance_ticks` / `min_break_ticks` | 8 / 2 |
| SMT | `validity_minutes` / `detect_tf` | 120 / 1m |
| Estrategia | `confirm_tf` | 15m |
| Estrategia | `breakout_buffer_ticks` | 2 |
| Estrategia | `min_range_ticks` | 10 |
| Estrategia | `setup_validity_minutes` | 150 |
| Estrategia | `use_smt` | true |
| Estrategia | `entry_reference` | or_mid |
| Estrategia | `retest_tolerance_ticks` | 12 |
| Estrategia | `entry_trigger` | close |
| Estrategia | `sl_mode` | structural |
| Estrategia | `sl_buffer_ticks` | 4 |
| Estrategia | `atr_period` / `atr_sl_mult` | 14 / 1.2 |
| Estrategia | `tp_rr` | 3.0 |
| Riesgo | `initial_capital` | 25 000 USD |
| Riesgo | `risk_per_trade_pct` | 1.0 % |
| Riesgo | `max_daily_loss_pct` | 3.0 % |
| Riesgo | `max_trades_per_day` | 3 |
| Riesgo | `max_contracts` | 5 |
| Riesgo | `max_sl_ticks` | 200 |
| Riesgo | `trade_window_end` | 15:30 |
| Riesgo | `session_close_time` | 15:55 |
| Ejecución | `fill_model` | next_open |
| Ejecución | `slippage_ticks` / `max_slippage_ticks` | 1 / 4 |
| Ejecución | `commission_per_contract_side` | 0.62 USD |
| Ejecución | `simulate_partial_fills` | false |

El volcado completo y verificado está en `docs/protocolo_backtest.lock.json` (`settings`).
Antes de ejecutar se comprueba que `load_settings().model_dump()` coincide exactamente con
ese objeto. Si no coincide, se aborta: el código cambió y el protocolo ya no aplica.

**Rangos de parámetros:** en esta versión **no se explora ninguno**. No hay búsqueda en
rejilla, ni optimización, ni selección de la mejor combinación. Eso evita el sobreajuste y
mantiene el holdout interpretable. Una fase de optimización posterior exigiría otro
protocolo, con rejilla fijada de antemano, selección solo dentro de desarrollo y un holdout
nuevo que no se haya mirado.

---

## 4. Diseño: walk-forward y holdout

### 4.1 Walk-forward sin reajuste

La estrategia no tiene parámetros que se entrenen en cada bloque, así que el "walk-forward"
aquí es una **evaluación rodante ciega**: los mismos parámetros se aplican a los seis
trimestres, uno detrás de otro, y se mide la estabilidad. No se recalibra nada entre bloques.

Cada bloque se ejecuta con las cuatro variantes sobre el **mismo** dataset y el mismo rango
efectivo. El bloque es la unidad de estabilidad; la aprobación se decide con el agregado de
los 362 días evaluados y con la consistencia entre bloques.

### 4.2 Holdout

- Se ejecuta solo si el desarrollo supera todas las puertas duras de la sección 6.1.
- Se ejecuta una vez, sobre 2026-07-01 → 2026-10-30, sin cambiar nada.
- No se usa para elegir variante ni parámetros. Solo confirma o desmiente.
- Si el holdout falla, el resultado global es **rechazado**, aunque el desarrollo haya sido
  bueno.

### 4.3 Comprobación de determinismo

Antes de aceptar los resultados, W1 se ejecuta dos veces. Las dos salidas deben tener
exactamente las mismas operaciones (`signal_id`, entrada, salida, P&L) y el mismo
`dataset.selected_id`. Si no coinciden, hay una fuente de no determinismo y el protocolo se
detiene.

### 4.4 Comprobación raw vs adjusted

Con esta estrategia, todas las decisiones son intradía y cada sesión se evalúa con sus
propias velas. Por tanto, `raw` y `adjusted` deben producir **las mismas operaciones**; solo
cambian los niveles absolutos. Se ejecuta W1 en `adjusted` como control de coherencia. Si las
operaciones difieren, hay un error de rolls o de ajuste y se investiga antes de seguir.

---

## 5. Métricas

Se calculan con `server/stats.py` sobre operaciones **cerradas**, netas de comisiones y
slippage. La curva de equity es de P&L cerrado; el drawdown abierto se reporta aparte.

| Métrica | Definición / campo |
|---|---|
| Operaciones | `trades` |
| Win rate | `win_rate` |
| Profit factor | `profit_factor` = beneficio bruto / \|pérdida bruta\| |
| Expectativa USD | `expectancy` = P&L neto / operaciones |
| Expectativa R | media de `r_multiple` |
| R total | `total_r` |
| P&L neto | `net_profit` |
| Comisiones | `fees` |
| Drawdown máximo | `max_drawdown` y `max_drawdown_pct` (cerrado) |
| Drawdown abierto | `max_open_drawdown` y `max_open_drawdown_pct` |
| Sharpe / Sortino | diarios, anualizados a 252 (`sharpe`, `sortino`) |
| Rachas | `best_win_streak`, `worst_loss_streak` |
| MFE / MAE | `avg_mfe_r`, `avg_mae_r` |
| Duración media | `avg_duration_sec` |
| Por dirección | `by_direction` (largos y cortos por separado) |
| Por tipo de señal | `by_signal` |
| Por mes | `monthly` |
| Por hora / día | `by_hour`, `by_weekday` |
| Barras ambiguas | `ambiguous_bars` y `diagnostics.ambiguous_bars` |
| Días operados | `days_traded` |

Métricas derivadas que se calculan en el informe (no están en `compute_stats`):

- **IC bootstrap** de la esperanza en R: 10 000 remuestreos con reemplazo de las operaciones
  (no de sesiones), semilla fija `20250102`, percentiles 2,5 / 10 / 90 / 97,5.
- **Sensibilidad a costes:** comisión 1,24 USD por lado y slippage 2 ticks (máximo 4).
- **Drop-best:** P&L neto tras eliminar las 5 mejores operaciones.
- **Concentración:** peso de las 5 mejores operaciones sobre el beneficio bruto y del mejor
  mes sobre el P&L neto.
- **Operaciones por sesión** y porcentaje de sesiones operadas.
- **Impacto de las barras ambiguas:** P&L de las operaciones afectadas y porcentaje sobre el
  total.

---

## 6. Criterios de aceptación

Los umbrales son **puertas de promoción a paper trading**, no una prueba de rentabilidad.
Se fijan antes de ver resultados y no se relajan después.

### 6.1 Puertas duras — desarrollo (368 sesiones de calendario, 362 evaluadas)

| ID | Criterio | Umbral |
|---|---|---|
| G1 | Integridad del dataset | D1, D2 y D3–D8 en desarrollo: **368/368** sesiones de calendario (**362** evaluadas); 0 huecos sin justificar; rolls correctos |
| G2 | Determinismo | W1 repetido produce operaciones idénticas |
| G3 | Coherencia raw/adjusted | Mismas operaciones en W1 con ambos modos |
| G4 | Muestra | ≥ **80** operaciones cerradas en `full`; ≥ **20** largos y ≥ **20** cortos |
| G5 | Edge neto | Profit factor ≥ **1,25** y expectativa ≥ **+0,10 R** |
| G6 | Riesgo | `max_drawdown` ≤ **2 000 USD** (8 % del capital inicial) y peor racha perdedora ≤ **8** |
| G7 | Consistencia | ≥ **4 de 6** bloques con PF > 1,0; ningún bloque con ≥ 15 operaciones y PF < 0,70 |
| G8 | Robustez a costes | Con comisión 1,24/lado y slippage 2 ticks: PF ≥ **1,10** |
| G9 | Robustez a outliers | P&L neto > 0 tras eliminar las 5 mejores operaciones |
| G10 | Concentración | Top 5 operaciones ≤ **50 %** del beneficio bruto; mejor mes ≤ **50 %** del P&L neto |
| G11 | Estadística | Límite inferior del IC bootstrap al **80 %** de la esperanza en R > **0** |
| G12 | Cortos | PF de cortos ≥ **0,95** y expectativa de cortos ≥ **−0,05 R** (con ≥ 20 cortos) |
| G13 | Ambigüedad | Barras ambiguas ≤ **5 %** de las operaciones; si están entre 5 % y 10 %, revisión con datos de trades antes de promover; > 10 %, fallo |
| G14 | Integridad de resultados | Cada operación tiene `signal_id`, contrato y `expiry`; sin duplicados; sin posiciones huérfanas |

Si G4 no se cumple por muestra insuficiente (menos de 80 operaciones, o menos de 20 en una
dirección), el resultado es **INCONCLUSO**, no aprobado: la muestra no permite distinguir la
estrategia de la nada.

### 6.2 Puertas del holdout (86 sesiones de calendario, 85 evaluadas)

| ID | Criterio | Umbral |
|---|---|---|
| H1 | Integridad | D1, D2 y D3–D8 en el holdout: **86/86** sesiones de calendario (**85** evaluadas); 0 huecos sin justificar |
| H2 | Muestra | ≥ **18** operaciones |
| H3 | Edge | PF ≥ **1,00** y expectativa ≥ **0,00 R** |
| H4 | Riesgo | `max_drawdown` ≤ **2 500 USD** (10 % del capital inicial) |
| H5 | Sin cambios | Configuración, dataset y código idénticos a los del desarrollo |

Si H2 queda entre 12 y 17 operaciones, el holdout es **INCONCLUSO**. Si queda por debajo de
12, también. En ambos casos no se promueve a paper con este protocolo.

### 6.3 Resultado global

| Desarrollo | Holdout | Resultado |
|---|---|---|
| Todas las G cumplidas | Todas las H cumplidas | **APTO para paper trading** (20 sesiones, misma configuración) |
| Todas las G cumplidas | H3 o H4 fallan | **RECHAZADO** |
| Todas las G cumplidas | Holdout inconcluso | **INCONCLUSO**; no se promueve |
| Alguna G falla | No se ejecuta | **RECHAZADO** o **INCONCLUSO** según G4 |

"Apto para paper" no significa apto para LIVE. El modo LIVE sigue bloqueado por falta de
adaptador de broker y no se habilita con este protocolo.

---

## 7. Análisis secundarios (descriptivos, no decisorios)

Se reportan siempre, pero no cambian la decisión:

- Las otras tres variantes (`orb`, `orb_smt`, `orb_retest`) en cada bloque y en el agregado.
- Largos frente a cortos: número, PF, expectativa, MFE/MAE.
- Resultado por mes y por trimestre.
- Distribución de R y de duración.
- Sensibilidad a incluir las sesiones de roll (`exclude_roll_sessions=false`).
- Sensibilidad a excluir las sesiones que contienen algún minuto rellenado.
- Comparación raw frente a adjusted en el agregado.
- Impacto económico de las barras ambiguas.
- Sharpe y Sortino, con la advertencia de que usan rendimientos diarios sobre capital
  inicial y no descuentan el riesgo abierto.

Estos análisis sirven para entender el resultado, no para rescatar un fallo. Si el endpoint
primario falla, no se busca una variante que pase.

---

## 8. Procedimiento de ejecución

### 8.1 Preparar el perfil aislado

```powershell
New-Item -ItemType Directory -Force profiles\backtest_real | Out-Null
python -c "import json,pathlib; lock=json.load(open('docs/protocolo_backtest.lock.json',encoding='utf-8')); pathlib.Path('profiles/backtest_real/config.json').write_text(json.dumps(lock['settings'],indent=2,ensure_ascii=False),encoding='utf-8')"
$env:YED_PROFILE_DIR = "$PWD\profiles\backtest_real"
```

No se arranca el motor, no se abre el dashboard y no se toca `data/` ni `profiles/dryrun/`.

### 8.2 Validar y congelar el dataset

```powershell
New-Item -ItemType Directory -Force reports\backtest | Out-Null
python -m server.market.csv_data data/real/bars_mnq_nq_es_1m.csv --series raw | Set-Content -Encoding utf8 reports\backtest\validator.json
if ($LASTEXITCODE -ne 0) { throw "CSV inválido: revisa reports/backtest/validator.json" }
python -c "import json; m=json.load(open('reports/backtest/validator.json',encoding='utf-8-sig')); man=m['manifest']; assert m['ok'] and man['aligned'] and man['gaps']['count']==0, (m['ok'], man['aligned'], man['gaps']); assert len(m['all_sessions'])==454, len(m['all_sessions']); assert m['session_count']==447, m['session_count']; assert m['session_validation']['invalid_sessions']==0; assert m['session_validation']['missing_session_count']==0; assert m['all_common_bars']==190170, m['all_common_bars']; assert man['contracts_declared'] and len(man['contract_expiries'])==24 and sum(len(v) for v in man['contracts'].values())==24, man['contracts']; assert len(man['rolls'])==21 and len(man['roll_sessions'])==7, (len(man['rolls']), len(man['roll_sessions'])); print('dataset OK: D1/D2/D4; 454 calendario / 447 evaluadas')"
python -c "import hashlib,pathlib; p=pathlib.Path('data/real/bars_mnq_nq_es_1m.csv'); print(hashlib.sha256(p.read_bytes()).hexdigest())" | Set-Content -Encoding utf8 reports\backtest\dataset_sha256.txt
```

La salida completa del validador queda en `reports/backtest/validator.json` y el hash en
`reports/backtest/dataset_sha256.txt`; ambos se incorporan a
`reports/backtest/dataset_manifest.json`. Si el validador sale con código 1, se detiene el
proceso.

### 8.3 Ejecutar el desarrollo

Con el perfil ya activo en la sesión de PowerShell:

```python
import json, pathlib
from datetime import date
from server.config import load_settings
from server.backtest import run_variants

lock = json.load(open("docs/protocolo_backtest.lock.json", encoding="utf-8"))
settings = load_settings()
assert settings.model_dump() == lock["settings"], "La configuración no coincide con el lock"
out = pathlib.Path("reports/backtest")
out.mkdir(parents=True, exist_ok=True)
for w in lock["windows"]:
    results = run_variants(settings, days=w["sessions"], start=date.fromisoformat(w["start"]))
    (out / f"{w['id']}.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    full = next(r for r in results if r["variant"] == "full")
    assert full["dataset"]["sessions"]["count"] == w["sessions"], (w["id"], full["dataset"]["sessions"])
    assert full["dataset"]["selected_range"]["last_et"].startswith(w["end"]), (w["id"], full["dataset"]["selected_range"])
    print(w["id"], full["dataset"]["selected_range"], full["metrics"]["trades"], full["metrics"]["profit_factor"])

# Agregado de desarrollo: concatenar operaciones, no promediar métricas de bloque.
from server.stats import compute_stats
trades = []
for w in lock["windows"]:
    results = json.loads((out / f"{w['id']}.json").read_text(encoding="utf-8"))
    trades.extend(next(r for r in results if r["variant"] == "full")["trades"])
aggregate = compute_stats(trades, settings.risk.initial_capital)
(out / "development_aggregate.json").write_text(json.dumps(aggregate, indent=2, ensure_ascii=False), encoding="utf-8")
```

Cada bloque debe reportar exactamente el rango esperado y el número de sesiones del lock:
las aserciones anteriores detienen la ejecución si `sessions.count` o el final de
`selected_range` no coinciden. `lock["windows"][i]["sessions"]` ya es el número **evaluado**,
no el de calendario. Las métricas derivadas (bootstrap, drop-best, concentración) se calculan
sobre la lista concatenada de operaciones, no sobre promedios de bloque.

### 8.4 Ejecutar el holdout

Solo después de que el informe de desarrollo esté completo, firmado y archivado, y solo si
todas las G pasan:

```python
import json
from datetime import date
from pathlib import Path

from server.backtest import run_variants
from server.config import load_settings

lock = json.load(open("docs/protocolo_backtest.lock.json", encoding="utf-8"))
settings = load_settings()
assert settings.model_dump() == lock["settings"]
out = Path("reports/backtest")
out.mkdir(parents=True, exist_ok=True)
target = out / "holdout.json"
if target.exists():
    raise SystemExit("El holdout ya se ejecutó; no se repite sin una incidencia técnica documentada")
results = run_variants(
    settings,
    days=lock["holdout"]["sessions"],  # 85 sesiones evaluadas; la de roll ya está excluida
    start=date.fromisoformat(lock["holdout"]["start"]),
)
full = next(r for r in results if r["variant"] == "full")
assert full["dataset"]["sessions"]["count"] == lock["holdout"]["sessions"]
assert full["dataset"]["selected_range"]["last_et"].startswith(lock["holdout"]["end"])
target.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
```

### 8.5 Archivar

Además del `dataset_manifest.json` común, por cada ventana se archivan: JSON crudo,
`validator.json`, `dataset_sha256.txt`, configuración, hash del protocolo, versión del código y
fecha. El informe final sigue la plantilla del anexo B.

---

## 9. Registro de cambios

| Versión | Fecha | Cambio | Motivo |
|---|---|---|---|
| 1.0 | 2026-11-19 | Versión inicial congelada | Primera definición antes de tener datos |
| 1.1 | 2026-11-19 | Corrección editorial pre-ejecución: G1/H1, D6, cierres anticipados, manifiesto y comprobaciones de comandos | Cuadrar conteos y referencias sin cambiar endpoint, ventanas, configuración ni umbrales |
| 1.2 | 2026-11-20 | Corrección pre-ejecución de la regla de roll: el contrato saliente sigue activo en la sesión de roll y el entrante empieza la sesión siguiente | Evitar huecos consecutivos reales del contrato entrante en el opening range de la sesión excluida; no cambia ventanas, configuración ni umbrales |

Reglas:

- Antes de ejecutar: cualquier corrección exige versión nueva y regenerar el lock.
- Después de ver resultados de desarrollo y antes del holdout: solo se admiten correcciones
  técnicas que no cambien la definición del endpoint; se documentan y se regenera la versión.
- Después de ver el holdout: no se admite ningún cambio dentro de esta versión. Cualquier
  mejora es una versión nueva con un holdout nuevo.

---

## 10. Limitaciones

- El backtest usa velas de 1 minuto y ejecución a la apertura siguiente; no modela libro de
  órdenes, cola ni latencia variable. El slippage es fijo y acotado.
- En velas ambiguas se asume el peor caso (SL primero). Es conservador, pero no sustituye a
  datos de tick.
- No hay parciales, ni órdenes nativas, ni rechazos de broker.
- La regla de roll es de calendario, no de volumen. Es determinista, pero puede diferir del
  momento en que el mercado real cambia de liquidez.
- La muestra esperada (~80–150 operaciones) da intervalos de confianza amplios. Un resultado
  positivo no prueba una ventaja duradera; uno negativo no descarta una variante mejor.
- El bootstrap remuestrea operaciones, no sesiones: no corrige la dependencia entre las hasta
  tres operaciones de un mismo día. El IC debe leerse como una cota optimista de la precisión.
- El tamaño se fija al 1 % del capital con un máximo de 5 contratos; cambios de capital
  cambian el tamaño y los resultados en USD.
- Los datos son para investigación personal; no se redistribuyen.
- Nada de esto valida el camino Short más allá de lo que muestre la muestra. La variante
  bajista de SMT sigue sin validación estadística independiente.

---

## Anexo A — Fuentes de datos

Resumen; el detalle y los enlaces están en
[`docs/PROVEEDORES.md`](PROVEEDORES.md#41-opciones-concretas-para-1m-con-contratos-y-rolls).

| Fuente | 1m | Contratos individuales | Rolls/vencimientos | Coste orientativo | Veredicto |
|---|---|---|---|---|---|
| **Databento** (`GLBX.MDP3`) | Sí (`ohlcv-1m`) | Sí (`raw_symbol`) | Sí (`definition` con `expiration`) | 70 USD/GB; ~20–25 USD el proyecto; 125 USD de crédito | **Recomendada** |
| **Kibot** | Sí | Sí | Contratos individuales; sin fichero de rolls explícito | 820 USD todo; 600 USD top-25 | Alternativa válida |
| **FirstRate Data** | Sí | Sí | Contratos + lista de rolls | Pago único (consultar); updates 59,95 USD/mes | Alternativa válida |
| **CME DataMine** | No hay dataset de barras 1m (habría que agregarlas) | — | — | Licencia por petición | No viable sin trabajo extra |
| **Interactive Brokers** | Sí, TWS API | Solo contratos vencidos < 2 años | Vencimiento por contrato | Permisos de datos CME | No recomendada |
| **Yahoo / Kaggle** | Parcial / incierta | No | No | Gratis | Rechazada |

## Anexo B — Plantilla del informe

1. **Identificación:** versión del protocolo, hash, fecha, código, configuración.
2. **Dataset:** proveedor, archivo, SHA-256, `dataset_id`, `series_id`, rango efectivo,
   sesiones, contratos, rolls, minutos rellenados, barridos de calidad.
3. **Desarrollo:** tabla por bloque (sesiones, operaciones, PF, expectativa, DD) y agregado.
4. **Puertas G1–G14:** una fila por puerta con valor, umbral y PASS/FAIL.
5. **Ablaciones:** las cuatro variantes, solo descriptivas.
6. **Robustez:** costes, drop-best, concentración, bootstrap, raw/adjusted, rolls, rellenos.
7. **Holdout:** ejecución única, métricas y puertas H1–H5.
8. **Decisión:** APTO / RECHAZADO / INCONCLUSO, con la frase literal del protocolo.
9. **Limitaciones y siguientes pasos.**
10. **Anexo:** rutas de los JSON crudos y del manifiesto.
