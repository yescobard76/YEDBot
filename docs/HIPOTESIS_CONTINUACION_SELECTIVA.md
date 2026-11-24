# Hipótesis pre-registrada — continuación selectiva

**Versión:** 1.1  
**Fecha:** 2026-11-21  
**Estado:** pre-registrada, **no ejecutada**. No se ha inspeccionado ninguna barra 2024.  
**Lock:** [`hipotesis_continuacion_selectiva.lock.json`](hipotesis_continuacion_selectiva.lock.json)  
**SHA-256 del payload congelado:** `73e84071f0a62a10f90f5812a164760d26eb65caf55c3c962990c10fb50dba47`

**Revisión 1.1:** aclara la independencia de 2024, fija el universo de contratos y
simplifica C2; no cambia la regla ni sus umbrales.

> Esta hipótesis es una investigación nueva. No reabre la opción retirada, no modifica
> la configuración activa, no reincorpora controles a la UI y **no usa el holdout sellado
> 2026-07-01 → 2026-10-30**. La continuación selectiva no se considerará parte del bot
> hasta que supere todas las puertas definidas aquí.

---

## 1. Hipótesis

La continuación sin retesteo falló porque entraba demasiado tarde: esperaba la expiración
del setup (240 minutos en el perfil de desarrollo) y compraba un impulso ya agotado. La hipótesis
es que una continuación puede ser viable si se exige que la ruptura sea **joven**, que el
precio haya **extendido lo suficiente** y que la entrada ocurra en la **ventana líquida de
la mañana**.

**H1 (alternativa):** una entrada de continuación que cumpla las tres condiciones nuevas
tendrá esperanza positiva y no degradará el baseline:

- edad de la ruptura entre **45 y 90 minutos** en el cierre de la vela de señal;
- extensión mínima de **0,75 × ATR(14) de 15m** más allá del nivel de ruptura;
- señal entre **10:30 y 13:00 ET**;
- manteniendo SMT alineada/recuperada, tres velas de 15m a favor y ausencia de retesteo;
- stop estructural con tope de 80 ticks y objetivo 3R, igual que la versión retirada.

**H0 (nula):** la continuación selectiva no mejora el baseline: su esperanza incremental
es menor o igual a cero, o el portfolio empeora en PF, neto o drawdown.

La predicción operativa es **menos operaciones, pero de mejor calidad**: PF de la cohorte
de continuación ≥ 1,25, expectativa ≥ +0,10 R y una mejora del portfolio sin aumentar el
drawdown más de 500 USD.

## 2. Por qué esto no es un reajuste de W1–W6

- La única información tomada de W1–W6 es el diagnóstico ya publicado: la versión anterior
  entraba tarde y añadía 109 operaciones con PF 0,91. Ese diagnóstico no es B y no entra
  en ninguna puerta; B se recalcula sobre 2024.
- Los umbrales 45/90 minutos, 0,75 ATR y 10:30–13:00 se fijan por estructura, no por una
  búsqueda de rejilla: 45 min son tres velas de 15m; 90 min son seis velas y el límite de
  frescura; 0,75 ATR exige seguimiento sin pedir un movimiento extremo; 10:30 deja pasar
  la primera media hora del OR y 13:00 evita la tarde.
- La regla selectiva **no se ha ejecutado sobre W1–W6**. No se usarán esos resultados para
  elegir umbrales ni para decidir si la hipótesis se acepta.
- Cualquier cambio de umbral, ventana o definición invalida este lock y exige una versión
  nueva con una muestra de validación nueva.

## 3. Regla congelada

### 3.1 Control

El control es la variante `full` con la configuración del lock v1.2:

| Parámetro | Valor |
|---|---:|
| `entry_reference` | `or_mid` |
| `use_smt` | `true` |
| `setup_validity_minutes` | 150 |
| `retest_tolerance_ticks` | 12 |
| `max_sl_ticks` | 200 |

El resto (riesgo 1 %, 5 contratos, TP 3R) se hereda del lock v1.2. El perfil de backtest
`profiles/backtest_real/config.json` está en 240/24/300 y **no es el control**; la
configuración activa `data/config.json` coincide en 150/12/200. El harness rechaza
cualquier Settings que no sea 150/12/200. B se calcula sobre 2024; no se importan
métricas de W1–W6.

### 3.2 Condiciones heredadas

La continuación selectiva solo puede evaluarse cuando ya existe una ruptura confirmada
por cierre de 15m y se cumplen **todas** estas condiciones, calculadas únicamente con
barras cerradas hasta la vela de señal:

1. no hubo retesteo de la referencia desde la confirmación hasta la señal;
2. la SMT está vigente, confirmada, recuperada y alineada con la dirección;
3. las tres últimas velas de 15m cerradas tienen cierres y extremos consecutivos a favor;
4. el último cierre está más allá del nivel de ruptura más el buffer.

Si hubo retesteo, la continuación se cancela y el camino normal de retesteo del baseline
sigue intacto.

### 3.3 Condiciones nuevas

| Condición | Regla concreta |
|---|---|
| Edad | `45 <= edad_min <= 90`, con `edad_min = señal_ts - breakout_confirm_ts` |
| Extensión | `(cierre_15m - nivel_ruptura) × signo / ATR14_15m >= 0.75` |
| ATR | ATR(14) sobre velas de 15m cerradas hasta la vela de señal inclusive; si ATR = 0, no hay entrada |
| Ventana | `10:30 <= hora_ET(signal_ts) < 13:00` |
| Entrada | señal al cierre de la vela de 15m; fill en el siguiente open de 1m |
| Stop | estructura cercana + buffer, tope 80 ticks; si no hay estructura, mínimo de 4 ticks |
| Objetivo | 3R |
| Frecuencia | máximo una continuación por ruptura; sin reentrada; sin overnight |

La edad empieza en `breakout_confirm_ts` (cierre de la vela de 15m que confirma la
ruptura). Se evalúa en cada cierre de 15m dentro de la ventana; se toma la primera señal
que cumpla todo. Si no hay señal antes de los 90 minutos o de las 13:00 ET, no se opera
continuación.

### 3.4 Qué no cambia

- ORB, SMT, confirmación de ruptura, referencia `or_mid`, retesteo, riesgo, tamaño,
  comisiones, slippage, cierre de sesión y salidas.
- La configuración activa y el camino por defecto: sin continuación, el bot sigue
  exactamente igual.
- No se añade nada a la UI ni a los presets. La implementación, si se autoriza, será
  exclusivamente de investigación y no se activará en paper/live con esta validación.

## 4. Datos de validación

### 4.1 Muestra primaria: 2024 externo

| Campo | Valor |
|---|---|
| Fuente | Databento `GLBX.MDP3` |
| Símbolos | MNQ, NQ, ES |
| Inicio ET | 2024-01-02 |
| Fin ET | 2024-12-30 |
| Series | raw, 1m |
| Rolls | regla del proyecto, 4 sesiones de roll excluidas |
| Contratos | H24, M24, U24, Z24, H25 (por raíz) |
| Sesiones de calendario | 251 |
| Sesiones evaluadas | 247 |
| Zona | America/New_York |

2024 es anterior a W1–W6 y no se usó en el desarrollo. Es una **muestra externa no
utilizada**, no un holdout forward del protocolo v1.2.

Auditoría de independencia: el raw `raw_mnq_nq_es_1m.jsonl.gz` declara `start=2025-01-10`;
el CSV resume 368 sesiones desde 2025-01-10; el piloto empieza 2025-01-16. No hay barras
2024 en el workspace. La ventana de definiciones puede incluir fechas 2024, pero no es
una muestra de precios.

### 4.2 Datos prohibidos

- **W1–W6 (2025-01-10 → 2026-06-30):** no se usan para validar, elegir umbrales ni
  rescatar la hipótesis.
- **Holdout 2026-07-01 → 2026-10-30:** sigue sellado. No se descarga, no se abre, no se
  ejecuta. El protocolo v1.2 exige un holdout nuevo para un cambio sustantivo; reutilizar
  el anterior invalidaría la comparación.
- **Pilot de 10 sesiones:** solapa al 100% con W1–W6; no es una muestra independiente.

Si 2024 no está disponible o no supera integridad, **no se sustituye por otro periodo**.
Se redacta una pre-registración nueva con otra muestra y otro lock.

### 4.3 Descarga

La clave se lee de `DATABENTO_API_KEY`; nunca se escribe en el repositorio, la config o
los logs. El comando previsto, una vez adaptado el fetcher, es:

```bash
python -m server.market.databento_fetch \
  --start 2024-01-02 --end 2024-12-30 \
  --out data/real/validation_2024/bars_mnq_nq_es_1m.csv \
  --fills-out data/real/validation_2024/bars_mnq_nq_es_1m_fills.csv \
  --summary data/real/validation_2024/bars_mnq_nq_es_1m_summary.json
```

> **Bloqueo:** `server/market/databento_fetch.py` fija hoy `QUARTERS` en H25..Z26.
> No contiene H24/M24/U24/Z24, así que no puede producir la muestra 2024: seleccionaría
> H25 como activo o fallaría por definiciones faltantes. Antes de descargar hay que añadir
> el universo H24/M24/U24/Z24/H25 (o usar un CSV externo equivalente). Hasta entonces no
> se ejecuta esta validación.

Antes de ejecutar la regla se valida: 251 sesiones de calendario, 247 evaluadas, 4 rolls
excluidos, contratos 2024 completos, cero huecos sin justificar, `fills` vacío o
justificado, y fechas estrictamente fuera de 2025-01-10 → 2026-06-30 y del holdout.

## 5. Endpoints y puertas

Sean:

- **B:** baseline `full` sobre 2024;
- **C:** operaciones de continuación selectiva;
- **V:** portfolio con B + C, respetando una posición y los límites de riesgo.

Todas las puertas se evalúan solo después de una preflight de muestra:
`dataset_id=external_2024`, ventana 2024-01-02 → 2024-12-30, 251 sesiones de
calendario, 247 evaluadas, series raw, rolls excluidos y contratos H24/M24/U24/Z24/H25.
Si la muestra no es 2024, el evaluador se detiene antes de C1; no lee métricas de W1–W6.

### 5.1 Puertas duras

| ID | Criterio | Umbral |
|---|---|---|
| C1 | Integridad | 251 sesiones de calendario, 247 evaluadas, 4 rolls excluidos, contratos 2024 completos, 0 huecos sin justificar |
| C2 | Muestra | ≥ 20 operaciones C; cualquier muestra menor = **INCONCLUSO** |
| C3 | Edge de C | PF ≥ 1,25 y expectativa ≥ +0,10 R |
| C4 | Portfolio | PF(V) ≥ PF(B), neto(V) > neto(B) |
| C5 | Drawdown | DD(V) ≤ DD(B) + 500 USD y DD(V) ≤ 2.500 USD |
| C6 | Consistencia | ≥ 3 de 4 trimestres con neto C ≥ 0; ningún trimestre con ≥ 10 C y PF < 0,80 |
| C7 | Costes | Con comisión 1,24/lado y slippage 2 ticks, PF(C) ≥ 1,10 |
| C8 | Determinismo | B repetido produce operaciones idénticas; sin look-ahead; señal anterior al fill |

### 5.2 Decisión

- **Todas las puertas:** candidato a 20 sesiones de paper, nunca a live.
- **Cualquier puerta falla:** hipótesis rechazada.
- **Muestra insuficiente o inconclusa:** no se promueve y no se rebajan umbrales.
- **Una sola variante primaria:** no hay búsqueda de parámetros. Las sensibilidades
  (0,5/1,0 ATR, 60/120 minutos) son descriptivas y no pueden cambiar la decisión.

## 6. Análisis previsto

- Agregar operaciones, no promediar métricas de bloques.
- Reportar B, C y V por separado; PF, expectativa en R, neto, drawdown, tasa de SL,
  duración, MFE/MAE y desglose largo/corto.
- Registrar el SHA-256 canónico de Settings del control junto a B, C y V.
- Reportar por trimestre y por mes.
- Comparar V contra B en las mismas sesiones; C nunca se mezcla con trades del baseline.
- Reportar el coste de las operaciones C y el efecto de bloquear retesteos posteriores.
- Reportar el IC bootstrap al 80% de la expectativa de C como análisis secundario.
- No seleccionar el mejor subconjunto ni eliminar outliers para aprobar.

## 7. Estado de ejecución

**No ejecutada.** A fecha 2026-11-21:

- el CSV disponible empieza en 2025-01-10 y termina en 2026-06-30;
- el piloto de 10 sesiones solapa con W1–W6;
- no hay barras 2024 en el workspace; solo definiciones de contratos;
- el fetcher actual no selecciona el universo de contratos 2024;
- `DATABENTO_API_KEY` no está configurada;
- el holdout 2026-07-01 → 2026-10-30 sigue sellado y no se ha tocado.

Para ejecutar la validación hace falta una de estas dos cosas, decidida antes de ver
resultados:

1. adaptar el fetcher al universo 2024, autorizar la descarga y configurar
   `DATABENTO_API_KEY` en el entorno;
2. proporcionar un CSV 2024 equivalente, sin modificaciones, para validarlo con este lock.

Hasta entonces la hipótesis queda pre-registrada y la validación, bloqueada. No se
declara apta ni se reincorpora la continuación al bot.
