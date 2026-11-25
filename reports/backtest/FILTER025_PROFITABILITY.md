# Rentabilidad comparada — filtro 0,25, P2, manual 8765 y original

**Estado:** histórico in-sample. **No es promoción.**
**Ámbito:** W1–W6, 2025-01-10 → 2026-06-30, 362 sesiones. Holdout H1
2026-07-01 → 2026-10-30 **sellado y no leído**.
**Backtests nuevos:** cero. Este informe agrega artefactos existentes y consulta
la configuración viva en modo lectura.
**Veredicto de gates:** `INCONCLUSO`; ver `FILTER025_GATES.md` y
`filter025_gates.json`.

## 0. Veredicto de rentabilidad

**Manual 8765 (M, `10/300/210/24`) frente al original establecido (O,
`5/200/150/12`), en el lote W1–W6:**

| Fuente | Ops | Neto USD | PF | DD USD | RDD | Uso |
|---|---:|---:|---:|---:|---:|---|
| M, W1–W6 | 72 | +2.022,94 | 1,22 | 2.891,66 | 0,6996 | referencia histórica |
| O, W1–W6 | 38 | +661,44 | 1,13 | 1.967,82 | 0,3361 | benchmark |
| 8765 replay, snapshot 06:26Z | 45 | +2.720,04 | 1,46 | 2.366,76 | — | runtime paper; no validación |

M supera a O en **+1.361,50 USD** y **+0,3635 RDD** (neto/DD), pero con
**+923,84 USD más DD**. Es una mejora histórica de rentabilidad absoluta y
ajustada por DD, **no validada forward**. El replay de 45 trades es otra
muestra: no reconstruye las 72 operaciones W1–W6, no sustituye la evidencia y
sigue avanzando. El lote manual 72 no tiene listado trade-by-trade, duraciones,
dirección ni fees; ésas celdas siguen `n/d`.

**Mejor mejora pendiente con respaldo:** M-SL200 (bajar `max_sl_ticks` 300→200
en M), **+448,84 USD** y **−587,20 DD** frente a M. La cifra viene de P2 46 vs
M 72 —P2 solo como comparador de la palanca—, no de una validación de M-SL200.
No hay una segunda mejora de rentabilidad **directa sobre M** con respaldo; la
alternativa P2+BE baja el neto frente a P2 y solo suma +13,58 frente a M con dos
cambios, así que no se prioriza. El filtro 0,25 y P2 no son caminos activos. La
propuesta requiere `H-M-SL200` y su propio lock; no se ejecuta aquí.

> **Nota de vigencia.** `docs/FORWARD_ORIGINAL_VS_P1.md` (2026-11-24),
> posterior a este informe, **descarta el filtro 0,25** y **excluye P2 y el
> 8765** del forward; el challenger vigente es **P1 (5/200/210/24, sin filtro)**
> frente al original. Esa nota no es un lock y no autoriza ejecución; los locks
> de filtro y P2+BE siguen `can_execute=false`. Este informe se conserva como
> análisis histórico in-sample y no reabre ninguna de esas hipótesis.

## 1. Chequeo de la instancia 8765

En la captura original de este informe (2026-11-24T03:20Z), el servidor HTTP de
8765 respondía pero el motor estaba **detenido**: `GET /api/status` devolvía
`status="stopped"`, modo paper y feed CSV conectado. No había P&L live nuevo
que valorar.

> **Actualización de vigencia (2026-11-24T06:26Z):** una comprobación posterior
> read-only vio el motor `running` en paper (PID 15108) y 45 trades de replay
> en la instantánea; el replay sigue avanzando.
> El estado actual está en `reports/backtest/live_8765_decision_check.json` y en
> `docs/MANUAL_8765_DECISION_MEMO.md`. Esta sección conserva el estado de la
> captura original.

La configuración viva leída en `/api/config` y en
`profiles/live_8765/config.json` —sin cambios entre la captura original y la
comprobación de cierre— es:

| Parámetro | 8765 vivo | Original 38 | P2 | Filtro 0,25 |
|---|---:|---:|---:|---:|
| `max_contracts` | 10 | 5 | 10 | 10 (aceptadas con qty ≤5) |
| `max_sl_ticks` | **300** | 200 | 200 | 200 |
| `setup_validity_minutes` | 210 | 150 | 210 | 210 |
| `retest_tolerance_ticks` | 24 | 12 | 24 | 24 |
| `min_stop_or_ratio` | **0,00** | 0,00 | 0,00 | **0,25** |

`profiles/live_8765/config.json` y `data/config.json` tienen el mismo SHA-256
(`9bf4f9c7…`). **8765 no está aplicando el filtro 0,25**: su ratio mínimo es
0,00 y su perfil es el manual `10/300/210/24`. Tampoco es exactamente P2, porque
P2 usa `max_sl_ticks=200`.

El artefacto existente `forward_validation.json` contiene ese perfil como
candidato `baseline_manual`, con 72 operaciones W1–W6, +2.022,94 USD, PF 1,22 y
DD 2.891,66. Es una ficha `dev_metrics` histórica, no una validación forward ni
un listado de operaciones.

## 2. Muestras y composición

| Perfil | Configuración | Ops | Largas / cortas | Max qty / ops>5 / stop caps (log) | Ops / sesiones | Meses activos | Fee base |
|---|---|---:|---:|---:|---:|---:|---:|
| Original | 5/200/150/12 | 38 | 21 / 17 | 5 / 0 / 50 | 38 ops / 38 sesiones (10,5 %) | 17 / 18 | 178,56 |
| Manual 8765 | 10/300/210/24 | 72 | n/d en artefacto | 10 / 17 / 37 | 72 ops; únicas n/d (19,9 % de densidad) | n/d | n/d |
| P2 | 10/200/210/24 | 46 | 26 / 20 | 10 / 17 / 63 | 46 ops / 46 sesiones (12,7 %) | 17 / 18 | 282,72 |
| P2 + filtro 0,25 | 10/200/210/24 + ratio 0,25 | 17 | 9 / 8 | ≤5 / 0 / n/d | 17 ops / 17 sesiones (4,7 %) | 10 / 18 | 55,80 |
| Rechazados por el filtro | P2 con ratio <0,25 | 29 | 17 / 12 | n/d / n/d / n/d | 29 ops / 29 sesiones (8,0 %) | 13 / 18 | 226,92 |

En los listados de original, P2, filtro y rechazados hay una entrada por
sesión: por eso `ops = sesiones únicas`. En el manual 72 solo
existe el agregado; no se afirma que 72 sean sesiones únicas. Los `stop caps`
son un conteo interno del log, no el número de operaciones.

La fila manual 72 conserva los agregados de `_manual_w1_w6_analysis.log`
(72 operaciones, 37 stop caps, 17 operaciones con qty>5 y max qty10) y la ficha
`baseline_manual` de `forward_validation.json` (72 ops, +2.022,94, PF 1,22, DD
2.891,66). **No conserva** el listado trade-by-trade, `duration_sec`,
`by_direction` ni fees. En la captura original el SQLite de
`profiles/live_8765` no tenía trades; la instantánea de cierre (06:26Z) registra
45 trades de replay, pero no es el lote W1–W6 ni permite reconstruir esas
celdas. Por eso se marcan `n/d` en lugar de inventarlas. Completarlas exigiría
una corrida nueva, prohibida por este encargo.

La comparación de selección correcta es **P2 46 → filtro 17**. El original 38
no es el contrafactual del filtro: tiene otra frecuencia (150/12 vs 210/24),
otro tamaño máximo (5 vs 10) y otro conjunto de señales; el cap de stop es 200
en ambos. La comparación original → filtro sirve para valorar la política
completa, pero mezcla perfil y selección.

## 3. Resultado económico

Cifras de los artefactos, sin reejecutar estrategia:

La **expectativa por trade** se mide de dos formas: dinero (neto/op) y R medio.
El **profit factor** es USD (no el PF-R del gate), y la **tasa de acierto** es el
porcentaje de operaciones con P&L positivo. El drawdown es el de la curva de
trades concatenados desde 25.000 USD.

| Perfil | Ops | Neto USD | Expectativa/op USD | Expectativa/op R | Profit factor | DD USD | DD % | Tasa de acierto | R total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Original | 38 | +661,44 | +17,41 | +0,1311 | 1,13 | 1.967,82 | 7,14 % | 31,58 % | +4,98 |
| Manual 8765 | 72 | +2.022,94 | +28,10 | +0,18 | 1,22 | 2.891,66 | 9,79 % | 36,1 % | +13,19 |
| P2 | 46 | +2.471,78 | +53,73 | +0,2513 | 1,39 | 2.304,46 | 7,84 % | 32,61 % | +11,56 |
| **Filtro 0,25** | **17** | **+4.202,20** | **+247,19** | **+1,1088** | **4,25** | **946,38** | **3,36 %** | **58,82 %** | **+18,85** |
| Rechazados | 29 | −1.730,42 | −59,67 | −0,2514 | 0,65 | 2.828,74 | — | 17,24 % | −7,29 |

Lectura directa:

- El filtro es el mejor de la muestra en **neto, neto por operación, R medio,
  PF, drawdown y acierto**. Duplica con creces el neto del original
  (+4.202,20 vs +661,44; +535,3 %) y reduce el DD un 51,9 %.
- Pero lo hace con **17 operaciones**, no con 38. El PF de 4,25 no es comparable
  en precisión con el 1,13 de una muestra de 38; la diferencia de tamaño es
  parte del problema, no un detalle.
- El perfil vivo 8765 gana más que el original en absoluto (+1.361,50), pero
  tiene **peor DD** (+923,84) y un PF de 1,22, inferior al 1,39 de P2.
- El filtro elimina un cohorte que pierde −1.730,42. Esa es exactamente la
  mejora bruta frente a P2: 2.471,78 + 1.730,42 = 4.202,20.

## 4. Exposición temporal y concentración trimestral

W1 = 2025-Q1, W2 = 2025-Q2, W3 = 2025-Q3, W4 = 2025-Q4, W5 = 2026-Q1,
W6 = 2026-Q2. Neto en USD:

| Perfil | W1 | W2 | W3 | W4 | W5 | W6 | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Original | +364,82 | +268,40 | −110,46 | +2.034,12 | −1.036,52 | −858,92 | +661,44 |
| Manual 8765 | +2.735,34 | +418,30 | −1.088,22 | +2.461,48 | −1.497,14 | −1.006,82 | +2.022,94 |
| P2 | +2.245,50 | +642,76 | −460,32 | +1.960,60 | −1.497,14 | −419,62 | +2.471,78 |
| Filtro 0,25 | +1.622,84 | +554,80 | +63,96 | +1.960,60 | 0,00 | 0,00 | +4.202,20 |
| Rechazados | +622,66 | +87,96 | −524,28 | 0,00 | −1.497,14 | −419,62 | −1.730,42 |

### Tiempo en mercado

La duración sale de `duration_sec` de cada trade en
`p2_w1_w6_confirm.json` y `_manual_filter025_w1_w6.json`. La exposición se
calcula sobre 362 sesiones × 6,5 horas de ventana operable (09:00–15:30) =
2.353 horas; `max_concurrent_positions=1`, así que los tiempos no se solapan.

| Perfil | Tiempo total | Media por op | Mediana por op | Exposición de la ventana |
|---|---:|---:|---:|---:|
| Original 38 | 44,50 h | 70,26 min | 16,50 min | 1,891 % |
| P2 46 | 47,10 h | 61,43 min | 14,50 min | 2,002 % |
| Filtro 17 | 39,97 h | 141,06 min | 132,00 min | 1,699 % |
| Rechazados 29 | 7,13 h | 14,76 min | 5,00 min | 0,303 % |
| Manual 72 | **n/d** | **n/d** | **n/d** | **n/d**; solo 72 ops / 362 = 19,9 % de densidad |

El filtro tiene **menos** tiempo total en mercado que el original y que P2
(39,97 h vs 44,50/47,10 h), pero sus operaciones duran más del doble en media
(141,06 min vs 70,26/61,43 min). No es un perfil de alta exposición: su ventaja
no proviene de estar más tiempo expuesto. El manual 72 no permite calcular esta
dimensión sin una corrida nueva; su densidad de operaciones no es tiempo en
mercado y se deja explícitamente separada.

Concentración:

| Perfil | Trimestres activos | Mejor trimestre / positivo bruto | Top-2 / positivo bruto | Top-2 / neto | Top-5 trades / bruto |
|---|---:|---:|---:|---:|---:|
| Original | 6 / 6 | 76,26 % | 89,94 % | 362,68 % | 57,94 % |
| Manual 8765 | 6 / 6 | 48,71 % | 92,55 % | 256,89 % | n/d |
| P2 | 6 / 6 | 46,31 % | 86,74 % | 170,16 % | 41,17 % |
| Filtro 0,25 | **4 / 6** | 46,66 % | **85,28 %** | **85,28 %** | 61,23 % |

Top-5 se calcula como suma de los cinco P&L netos / `gross_profit` del
agregado, la misma definición de `gates.json`/`filter025_gates.json`.

El “top-2 / neto” supera 100 % en original, manual y P2 porque otros trimestres
pierden. Es una medida de dependencia, no un porcentaje de ganancia. El gate Q3
usa el neto y, con esa definición, el filtro falla: **85,28 % > 80 %**. El
filtro también falla cobertura: 4/6 trimestres activos, con W5 y W6 vacíos, y
solo 10/18 meses activos; su racha sin operar es de 6 meses (P7 falla).

### El filtro no mejora en todos los regímenes

La diferencia trimestral P2 → filtro es:

| Trimestre | P2 | Filtro | Diferencia |
|---|---:|---:|---:|
| W1 2025-Q1 | +2.245,50 | +1.622,84 | **−622,66** |
| W2 2025-Q2 | +642,76 | +554,80 | **−87,96** |
| W3 2025-Q3 | −460,32 | +63,96 | **+524,28** |
| W4 2025-Q4 | +1.960,60 | +1.960,60 | 0,00 |
| W5 2026-Q1 | −1.497,14 | 0,00 | **+1.497,14** |
| W6 2026-Q2 | −419,62 | 0,00 | **+419,62** |
| **Total** | **+2.471,78** | **+4.202,20** | **+1.730,42** |

La mejora no viene de elegir mejores ganadores en todos los trimestres. Viene
de **evitar pérdidas en W3/W5/W6** (+2.441,04) y de sacrificar parte de las
ganancias de W1/W2 (−710,62). En 2026 el filtro no opera: no pierde, pero
tampoco gana. Esa asimetría es clave para interpretar el resultado y para el
riesgo de sobreajuste.

## 5. Coste estimado

| Perfil | Fees base | Fees stress | Neto stress | PF stress | DD stress | Coste absorbido |
|---|---:|---:|---:|---:|---:|---:|
| Original 38 | 178,56 | 357,12 (comisión 1,24/lado; slippage 2) | 347,38 | 1,07 | 2.064,14 | **−314,06** |
| Filtro 17 | 55,80 | reprecio exacto no disponible | 4.101,40 estimado | 4,0811 estimado | n/d | **−100,80 estimado** |
| Manual 72 | n/d | no hay stress exacto | n/d | n/d | n/d | n/d |
| P2 46 | 282,72 | no hay stress exacto | n/d | n/d | n/d | n/d |

El filtro tiene fees base de 55,80 (3,28/op) y el original de 178,56 (4,70/op);
P2 tiene 282,72 (6,15/op). El manual 72 no permite separar fees del neto en el
log, así que no se presenta un coste inventado. El coste exacto del filtro
tampoco existe: la única cifra de estrés del filtro es la estimación uniforme.

El stress exacto del original reduce el neto un **47,5 %** y el PF de 1,13 a
1,07; el DD empeora 96,32. El filtro solo tiene una estimación uniforme, no un
reprecio exacto: su PF estimado 4,0811 sigue siendo alto, pero **P6 queda
NO_EVALUABLE**. No se usa `stress_costs.json` del original como si fuera el
filtro.

## 6. Qué explica la diferencia: perfil, selección y falta de muestra

### Descomposición exacta

La contabilidad existente permite separar tres pasos sin reejecutar nada:

| Paso | Neto | Δ neto | PF | DD | Δ DD |
|---|---:|---:|---:|---:|---:|
| Original 38 (5/200/150/12) | +661,44 | — | 1,13 | 1.967,82 | — |
| P1: frecuencia 210/24, max5/SL200 | +1.992,26 | **+1.330,82** | 1,37 | 1.947,82 | −20,00 |
| P2: max_contracts 10 (SL200) | +2.471,78 | **+479,52** | 1,39 | 2.304,46 | +356,64 |
| Filtro 0,25: selección de 17/46 | +4.202,20 | **+1.730,42** | 4,25 | 946,38 | −1.358,08 |
| **Original → filtro** | **+4.202,20** | **+3.540,76** | **4,25** | **946,38** | **−1.021,44** |

Por tanto:

- **Perfil/frecuencia/contratos:** +1.810,34 USD (51,1 % de la diferencia total).
  No es efecto del filtro.
- **Selección del filtro:** +1.730,42 USD (48,9 % de la diferencia total).
  Es exactamente el resultado del cohorte rechazado.
- **Sobreajuste o falta de muestra:** no es un componente aditivo que se pueda
  cuantificar con estos datos. Lo que sí se puede afirmar es que **todo el
  +1.730,42 es in-sample**; el umbral se eligió en W1–W6 y no hay muestra
  forward. Por eso no se puede certificar que sea selección repetible en vez de
  sobreajuste.

### Señales de que el edge es frágil

- El filtro **empeora** W1 y W2 frente a P2; su ventaja agregada depende de
  evitar las pérdidas de W3/W5/W6, sobre todo de no operar en 2026 (W5/W6).
- Muestra del filtro: **17 ops** (mínimo 80), **9 largos / 8 cortos** (mínimo
  20 por dirección), **46 baseline** (mínimo 60), **17 aceptadas / 29
  rechazadas** (mínimos 24/30) y **2/6 bloques** con muestra suficiente
  (mínimo 5/6).
- 4/6 trimestres activos; W5/W6 vacíos; 10/18 meses activos; racha de 6 meses
  sin operar (P7 exige ≤4).
- Top-2 trimestres = 85,28 % del neto (Q3 exige ≤80 %); top-5 trades = 61,23 %
  del bruto.
- El bootstrap de selección es positivo, IC95 % [+0,3312, +2,3548] R, p≈0,006,
  con 10.000 réplicas válidas, pero **E2 no puede dar PASS** porque la muestra
  17/29 y la cobertura 4/6 no alcanzan sus precondiciones.
- El perfil vivo 8765 tampoco es una validación: es `10/300/210/24`, con SL
  300. En la captura original estaba detenido; la comprobación de cierre lo vio
  `running` en paper (ver la nota de vigencia y el memo de decisión).

### Confianza

- **Confianza descriptiva: alta para las cifras con fuente.** Se reconstruyen
  desde los JSON y el log; los hashes solo confirman que la configuración no
  cambió. Las celdas `n/d` no se rellenan.
- **Confianza en que el filtro sea más rentable hacia adelante: baja /
  indeterminada.** Los gates globales son `INCONCLUSO`; no hay forward; el
  holdout está sellado. No se debe asignar capital por el PF 4,25 histórico.
- **Confianza en la comparación contra el original: media para el perfil
  (46 operaciones), baja para el filtro (17).** El original y P2 son más
  comparables entre sí; el filtro es una selección post hoc sobre P2.

## 7. Lectura histórica del filtro (no es el veredicto del manual)

**Veredicto del manual vs original: §0.** Esta sección solo cierra el análisis
histórico del filtro y no es una recomendación.

**En la muestra histórica W1–W6, el filtro 0,25 es más rentable que el original
y que P2 en términos absolutos y ajustados por riesgo.** El original gana
+661,44 con PF 1,13 y DD 1.967,82; el filtro gana +4.202,20 con PF 4,25 y DD
946,38. El perfil vivo 8765 gana +2.022,94 con PF 1,22 y DD 2.891,66: más que
el original en absoluto, pero por debajo de P2 y con más drawdown.

**Eso no demuestra que el filtro sea una mejora promocionable.** La diferencia
frente al original es 51,1 % perfil y 48,9 % selección; la selección es
in-sample, con 17 operaciones y cuatro trimestres activos. El veredicto de
gates sigue siendo **INCONCLUSO**, no PASS, y la decisión es **no promocionar**.
La formulación correcta es: “mejor rentabilidad histórica observada, con
confianza predictiva insuficiente”.

## 8. Mejoras priorizadas por rentabilidad

**Regla de vigencia.** El forward vigente es original vs P1 y no incluye el
8765, P2 ni el filtro 0,25. Ninguna propuesta de este informe está implementada
o autorizada. Cada propuesta tendría su propio lock y no hereda los gates
S0–Q5 del filtro; las cifras son in-sample y sirven para priorizar, no para
promocionar.

### 8.1 Ranking

| # | Propuesta | Entidad de la evidencia | Δ neto vs M | Δ DD vs M | Gate propio |
|---|---|---|---:|---:|---|
| 1 | **M-SL200**: bajar `max_sl_ticks` 300→200, sin tocar nada más | M 72 vs P2 46 (P2 solo como comparador de la palanca) | **+448,84** | **−587,20** | `H-M-SL200` / `G1–G6` |
| — | Reprecio exacto de costes (precondición) | Original exacto y filtro estimado; M n/d | no cuantificado | no cuantificado | `G-M-COST` |

No hay una segunda propuesta **de rentabilidad directa sobre M** con respaldo
numérico. P2+BE tiene +13,58 vs M, pero son dos cambios y pierde −435,26 vs P2;
no se prioriza. Las demás palancas evaluadas empeoran el neto, ya están
incorporadas o están descartadas por la nota de vigencia; se listan abajo para
que no se confundan con recomendaciones.

### 8.2 Propuesta 1 — M-SL200

**Entidad y cifra.** Sobre el perfil M `10/300/210/24`, la variante M-SL200
cambia solo `max_sl_ticks` a 200. La evidencia es la comparación P2 46 vs M 72:
**+448,84 USD de neto**, **−587,20 USD de DD**, PF 1,22→1,39, R medio
0,18→0,25. La configuración resultante coincide con P2, pero la hipótesis es
una sola palanca sobre M; **no se adopta el paquete P2 ni su plan**.

**Mecanismo.** Un cap de 300 permite stops estructurales más amplios; al
bajarlo a 200 se rechazan las señales cuyo stop excede 200 ticks. El artefacto
muestra 26 operaciones menos (72→46), menos cola de pérdida y menos DD. No es
una nueva señal ni un edge de entrada: es poda de riesgo.

**Coste/riesgo.** Menos operaciones y menor frecuencia; la tasa de acierto baja
de 36,1 % a 32,61 % y el neto depende de ganadores grandes. La muestra de 46 es
in-sample y no tiene reprecio exacto de costes. El DD absoluto sigue siendo
2.304,46, por encima del original (1.967,82). No es ejecutable con W1–W6.

**Hipótesis y gate propio.** `H-M-SL200` (lock nuevo; no es P2, no es el
filtro):

- `G1` integridad: único diff `risk.max_sl_ticks 300→200`; mismo feed, 10
  contratos, 210/24, filtro 0,00 y ejecución. Hash de config y del lock.
- `G2` muestra: forward independiente, sin W1–W6, H1, 2024 ni la muestra del
  forward original/P1; mínimo **60 operaciones cerradas por brazo**, fijado en
  este lock (no es S2).
- `G3` rentabilidad: Δneto(M-SL200 − M) > 0; bootstrap por sesión, IC95 %
  inferior > 0; PF y RDD de M-SL200 ≥ M.
- `G4` riesgo: DD USD(M-SL200) ≤ DD USD(M).
- `G5` costes: reprecio exacto con comisión 1,24/lado y slippage 2 ticks;
  Δneto después de costes > 0. No se traslada la estimación del filtro.
- `G6` ejecución: one-shot, sin análisis intermedio de eficacia ni búsqueda de
  parámetros.

**Estado.** Propuesta, no cambio. No se toca el 8765 ni se crea el lock en este
informe.

### 8.3 Precondición — costes exactos

**No es una mejora de retorno.** El original tiene stress exacto: fees 357,12,
neto 347,38, PF 1,07 y coste absorbido −314,06. El filtro solo tiene una
estimación uniforme de −100,80; M no tiene reprecio exacto. No se usa el −100,80
del filtro como si fuera M ni se forma un rango con −314,06. El mecanismo es
frenar una sobreestimación: no sube el bruto, pero evita que un PF alto se
convierta en neto falso al repreciar.

**Gate `G-M-COST`.** Antes de ejecutar `H-M-SL200`, repreciar M y M-SL200 con
los mismos fills y exigencias de coste; publicar neto, PF, RDD y DD después de
costes. Si el Δneto después de costes no es positivo, la propuesta se descarta.
Esto protege la decisión; no se le atribuye un aumento de rentabilidad.

### 8.4 Candidatos evaluados y no propuestos

| Candidato | Entidad / cifra auditada | Por qué no es propuesta activa |
|---|---|---|
| P2 como paquete `10/200/210/24` | P2 46 vs M: +448,84 neto, −587,20 DD | `FORWARD_ORIGINAL_VS_P1` excluye P2; no se adopta. La única palanca que sobrevive es M-SL200, con hipótesis y lock propios. |
| Filtro 0,25 | filtro 17 vs P2: +1.730,42 neto, −1.358,08 DD | Descartado por la nota de vigencia; no se reabre ni se heredan S0–Q5. |
| P2 + BE 1R | P2+BE 46: +2.036,52, PF 1,48, DD 1.794,46; vs P2 −435,26 neto; vs M +13,58 neto y −1.097,20 DD (dos cambios) | Mejora PF/DD, pero no la rentabilidad absoluta; BE es experimental y no hay artefacto M+BE. No es propuesta de este informe. |
| P1 / 5 contratos | P1 46: +1.992,26, PF 1,37, DD 1.947,82; vs M −30,68 neto, −943,84 DD | Es reducción de riesgo, no mejora de neto; el forward original/P1 es otra decisión. |
| Frecuencia 210/24 | M ya la tiene; P1 vs original +1.330,82 | No hay palanca incremental sobre M; contarla otra vez sería doble conteo. |
| Más contratos (>10) | P1→P2 5→10: +479,52 neto, +356,64 DD; >10 sin artefacto | M ya usa 10; no hay cifra que respalde subir más y el 5→10 es apalancamiento, no edge. Se descarta. |
| Selección de ventanas / evitar 2026 | filtro evita 1.916,76 de pérdidas W5/W6, pero es in-sample y el filtro está inactivo | No hay regla de calendario validada; sería post hoc. Se descarta. |

Los candidatos de esta tabla no son propuestas y no reciben un gate activo. Si
se reabriera alguno, necesitaría su propio lock; en este informe no se reabre
ninguno.

## 9. Gates del filtro (no de M-SL200)

Estos gates pertenecen al filtro 0,25 y no se heredan para M-SL200; este último
tiene `G1–G6` en §8.2.

| Grupo | Estado actual |
|---|---|
| Global | **INCONCLUSO** |
| PASS | 13 gates |
| FALLA | Q1 cobertura (4/6), Q3 concentración (85,28 %), Q4 rechazados (3/6), P7 mensual (racha 6) |
| INCONCLUSO | S0, S2, S3, S4, E2 |
| NO_EVALUABLE | P6 coste exacto |

El detalle y la justificación están en `FILTER025_GATES.md`. La capa de gates se
revisó antes de este informe: `filter025_gates.py --no-write` volvió a declarar
`GLOBAL INCONCLUSO` y los 8 tests de `tests/test_filter025_gates.py` pasaron.
No se modificó ningún umbral.

## 10. Reproducir y ficheros

```bash
python reports/backtest/filter025_gates.py --no-write
python -m pytest tests/test_filter025_gates.py -q
```

Este informe se apoya en:

- `reports/backtest/p2_w1_w6_confirm.json` — original 38 y P2 46.
- `reports/backtest/_manual_filter025_w1_w6.json` — listado y agregado del filtro 17.
- `reports/backtest/filter025_gates.json` — partición 17/29, gates y veredicto.
- `reports/backtest/live_vs_original_mission.json` — manual 72, atribución y ventanas.
- `reports/backtest/_manual_w1_w6_analysis.log` — agregados manual 72 y stop caps.
- `reports/backtest/forward_validation.json` — fichas `baseline_manual`, P2 y P2+BE; config 8765.
- `reports/backtest/p2_be_1r_experiment.json` — P2+BE 46.
- `reports/backtest/live_8765_decision_check.json` — snapshot de 45 trades de replay.
- `docs/FORWARD_ORIGINAL_VS_P1.md` — decisión posterior que descarta el filtro.
- `reports/backtest/stress_costs.json` — stress exacto del original.
- `profiles/live_8765/config.json`, `data/config.json` y API local 8765 —
  configuración viva, solo lectura.

**Ficheros de esta revisión:** solo `FILTER025_PROFITABILITY.md`. La entrada de
`reports/backtest/README.md` se añadió al crear el informe. No se modificó
ningún perfil, estrategia, filtro, umbral, lock ni archivo del holdout.
