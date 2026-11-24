# Validación pre-registrada — filtro stop/ORB en la variante `full`

**Versión:** 1.0  
**Fecha:** 2026-11-22  
**Estado:** pre-registrado y **no ejecutado**. No se ha leído ninguna barra nueva, no se ha ejecutado ningún backtest ni paper, y el holdout `2026-07-01 → 2026-10-30` sigue sellado.  
**Lock:** [`filtro_stop_or_forward.lock.json`](filtro_stop_or_forward.lock.json) — contiene el SHA-256 de este documento, la configuración congelada, la muestra permitida y las puertas.  
**Hipótesis:** `H-FILTER-STOP-OR-025`.

> Este documento no demuestra que el filtro sea rentable. Fija de antemano qué muestra se usará, qué se medirá y qué condiciones deben cumplirse para aceptarlo, rechazarlo o declararlo inconcluso. No modifica `data/config.json`, `profiles/backtest_real/config.json`, el protocolo v1.2, sus locks ni el holdout. Tampoco autoriza paper en tiempo real ni LIVE.

---

## 1. Resultado que motiva la validación

El filtro `risk.min_stop_or_ratio = 0.25` se aplicó a la variante `full` sobre W1–W6 (`2025-01-10 → 2026-06-30`, 362 sesiones evaluadas). El resultado oficial está en `reports/backtest/min_stop_or_ratio_protocol.json`.

| Métrica | Baseline sin filtro | Filtro 0,25 | Diferencia |
|---|---:|---:|---:|
| Operaciones | 38 | 14 | −24 |
| P&L neto | +661,44 USD | +3.026,88 USD | +2.365,44 USD |
| Profit factor | 1,13 | 3,57 | +2,44 |
| Expectativa media | +0,13 R | +1,04 R | +0,91 R |
| Drawdown máximo | 1.967,82 USD | 839,90 USD | −1.127,92 USD |
| Win rate | 31,58 % | 57,14 % | +25,56 pp |

El filtro **no añadió operaciones**: las 14 aceptadas son un subconjunto estricto de las 38 del baseline. Las 24 eliminadas tienen una media de **−0,398 R** y un total de **−9,55 R**; las 14 aceptadas tienen una media de **+1,038 R**. La diferencia de selección observada es **+1,436 R**.

### 1.1 Por qué este resultado todavía no es una validación

1. **Es in-sample.** W1–W6 se usaron para descubrir y elegir el umbral. Reutilizar esas fechas para confirmarlo sería circular.
2. **La muestra es pequeña.** 14 operaciones no permiten sostener una promesa de rentabilidad. El resultado no cumple G4 del protocolo v1.2 (≥80 operaciones) ni G10 (top 5 ≤50 % del beneficio bruto y mejor mes ≤50 % del neto): las cinco mejores operaciones concentran el **77,8 %** del beneficio bruto y W4 concentra el **67,2 %** del neto.
3. **La mejora es desigual.** En W1 el filtro gana 292,52 USD pero el baseline gana 364,82 USD: el filtro empeora ese bloque en 72,30 USD. La mejora agregada depende de evitar pérdidas en W5–W6, no de seleccionar mejores entradas en 2026.
4. **En 2026 el filtro dejó cero operaciones.** Las 17 operaciones de 2026 de `orb_retest` tienen ratio <0,25; el filtro no demuestra selección en ese régimen, solo ausencia de exposición.
5. **El resultado es frágil a concentración.** Un solo trimestre y cinco operaciones explican la mayor parte del P&L. La validación forward debe exigir consistencia por bloque y participación, no solo un agregado favorable.

Por estas razones, el filtro queda en la categoría **candidato no validado**. La validación que sigue no intenta “confirmar” el resultado de W1–W6: intenta comprobarlo en una muestra nueva, con reglas que puedan fallar.

---

## 2. Hipótesis y estimando

### 2.1 Hipótesis

**H1 (alternativa):** en una muestra forward independiente, las operaciones `full` con `stop_ticks / orb_width_ticks >= 0,25` tienen una esperanza en R mayor que las operaciones con ratio `< 0,25`, y eliminar el segundo grupo mejora el R total y el drawdown sin reducir la actividad a un nivel inutilizable.

**H0 (nula):** la diferencia de selección es menor o igual a cero, o el cohorte eliminado tiene R total positivo, o el filtro no supera las puertas de cartera, consistencia, costes o participación.

### 2.2 Estimando primario

Sea `B` el conjunto de operaciones `full` ejecutadas por el brazo de control (sin filtro) en la muestra forward. Para cada operación `i ∈ B` se registra:

```text
ratio_i = stop_ticks_i / orb_width_ticks_i
A = { i ∈ B : ratio_i >= 0,25 }      (aceptadas)
Rj = { i ∈ B : ratio_i < 0,25 }      (rechazadas)
```

El endpoint primario es:

```text
Δ_sel = media(R_i para i ∈ A) − media(R_i para i ∈ Rj)
```

- Unidad de observación: operación.
- Unidad de remuestreo: sesión (hasta 3 operaciones por día).
- Bloques de consistencia: 6 bloques consecutivos de 6 meses.
- `R_i` es el múltiplo de riesgo neto de comisiones y slippage, calculado por el motor; no se recalcula a mano ni se normaliza después de ver el resultado.
- El umbral `0,25` está fijado. No se prueban `0,20`, `0,30` ni ninguna otra rejilla.

### 2.3 Endpoint secundario de cartera

El filtro también debe mejorar la cartera, no solo la media por operación. Se reporta y se gatea:

```text
Δ_total_R = suma(R_i para i ∈ A) − suma(R_i para i ∈ B)
          = −suma(R_i para i ∈ Rj)
```

Por tanto, exigir que el filtro no empeore el R total es equivalente a exigir que **el cohorte rechazado tenga R total ≤ 0**. Es una prueba directa y transparente: si las operaciones eliminadas ganan en conjunto, el filtro reduce el R total aunque suba la media.

También se ejecuta el brazo de tratamiento real (`min_stop_or_ratio=0,25`) sobre los mismos datos, para medir el efecto completo —incluida la interacción con el límite de pérdida diaria y el cooldown—. Ese brazo es una **puerta de cartera**, no el endpoint primario: la selección se mide sobre `B`, porque así se evita confundir el filtro con cambios de tamaño o de trayectoria de capital.

---

## 3. Muestra

### 3.1 Diseño: forward de captura prospectiva

La muestra primaria es un **paper forward de captura prospectiva con replay ciego**:

1. Cada sesión se captura después del cierre (16:05 ET o más tarde) desde el proveedor, se valida y se sella.
2. No se ejecuta la estrategia durante la captura. No hay P&L visible ni decisiones operativas diarias.
3. Al final del periodo, se ejecuta **una sola vez** el replay de ambos brazos sobre el CSV forward sellado.
4. El replay solo puede leer sesiones capturadas y selladas; no puede descargar datos futuros ni completar sesiones pasadas.

Esto no es ejecución en tiempo real ni genera órdenes. Es la forma más limpia de obtener una muestra forward sin un adaptador live y sin introducir decisiones humanas durante el estudio. La limitación se documenta en §10.

### 3.2 Ventana y bloques

| Bloque | Desde | Hasta | Sesiones de calendario | Rolls excluidos | Sesiones evaluadas |
|---|---|---|---:|---:|---:|
| F1 | 2026-12-01 | 2027-05-31 | 124 | 2 | 122 |
| F2 | 2027-06-01 | 2027-11-30 | 127 | 2 | 125 |
| F3 | 2027-12-01 | 2028-05-31 | 125 | 2 | 123 |
| F4 | 2028-06-01 | 2028-11-30 | 127 | 2 | 125 |
| F5 | 2028-12-01 | 2029-05-31 | 124 | 2 | 122 |
| F6 | 2029-06-01 | 2029-11-30 | 127 | 2 | 125 |
| **Total** | **2026-12-01** | **2029-11-30** | **754** | **12** | **742** |

- La ventana se fija antes de capturar. **No se desplaza** si la captura empieza tarde: si no se puede empezar el 2026-12-01, se redacta un lock nuevo con otra ventana y otra muestra.
- Las sesiones de roll se excluyen con `feed.exclude_roll_sessions=true`, igual que en el protocolo v1.2. Las 12 fechas previstas son: `2026-12-10`, `2027-03-11`, `2027-06-09`, `2027-09-09`, `2027-12-09`, `2028-03-09`, `2028-06-08`, `2028-09-07`, `2028-12-07`, `2029-03-08`, `2029-06-07`, `2029-09-13`.
- **Burn-in:** `2026-11-23 → 2026-11-30`, excluido del análisis. Solo sirve para probar la plomería de captura, validación y sellado. No se usa para elegir nada.
- La ventana no solapa W1–W6, el holdout ni 2024.

### 3.3 Por qué 36 meses y no 12 o 24

La frecuencia observada es baja:

- baseline: 38 operaciones / 362 sesiones = **10,50 %** de sesiones con operación;
- filtro: 14 operaciones / 362 sesiones = **3,87 %** de sesiones con operación aceptada.

Con 742 sesiones evaluadas se esperan, si la frecuencia se mantiene:

- **~78 operaciones baseline**;
- **~29 operaciones aceptadas**;
- **~49 operaciones rechazadas**.

Doce meses (~247 sesiones) producirían ~26 baseline y ~10 aceptadas; 24 meses (~495) producirían ~52 y ~19. Ninguno alcanza con holgura el mínimo de 24 aceptadas / 60 baseline, y el intervalo de confianza sería demasiado ancho. **36 meses es el mínimo que permite una prueba con una potencia mínima aceptable para un efecto grande**; no es una garantía de que el efecto exista.

### 3.4 Mínimos de muestra

| ID | Mínimo | Si no se cumple |
|---|---|---|
| S1 | ≥ **720** de las 742 sesiones evaluadas; ningún mes con <80 % de sus sesiones; ningún hueco >5 sesiones consecutivas | `inconcluso` |
| S2 | ≥ **60** operaciones baseline ejecutadas | `inconcluso` |
| S3 | ≥ **24** aceptadas y ≥ **30** rechazadas | `inconcluso` |
| S4 | ≥ **5 de 6** bloques con baseline ≥6 y aceptadas ≥2 | `inconcluso` |
| S5 | ≥ **5** cortos aceptados | `inconcluso_short` |

Si no se cumplen S1–S4, el resultado es **INCONCLUSO**, no aprobado. No se baja el mínimo, no se agregan bloques, no se extiende la ventana y no se sustituye la muestra. Un `inconcluso` no autoriza promoción.

### 3.5 Muestras prohibidas

| Muestra | Fechas | Por qué está prohibida |
|---|---|---|
| W1–W6 | 2025-01-10 → 2026-06-30 | Usada para descubrir y elegir el filtro; es in-sample. |
| Holdout H1 | 2026-07-01 → 2026-10-30 | Sellado por el protocolo v1.2; abrirlo para este filtro lo contaminaría. |
| 2024 externo | 2024-01-02 → 2024-12-30 | Reservado por `H-CONT-SELECTIVA-2024`; no es independiente para esta hipótesis. |
| Pilot de 10 sesiones | Solapa W1–W6 | No es una muestra independiente. |
| Burn-in | 2026-11-23 → 2026-11-30 | Solo plomería; excluido del análisis. |

No se leen, descargan, ejecutan ni infieren datos de estas ventanas para tomar decisiones sobre este filtro. El holdout sigue sellado.

### 3.6 Fuente y captura

- **Proveedor:** Databento `GLBX.MDP3`, esquema `ohlcv-1m`, simbología `raw_symbol` para MNQ, NQ y ES.
- **Contratos:** 39 en total, 13 por raíz: `Z26, H27, M27, U27, Z27, H28, M28, U28, Z28, H29, M29, U29, Z29`.
- **Rolls:** 12 por raíz (36 en total), con la regla del protocolo v1.2: el saliente sigue activo en la sesión de roll y el entrante empieza la sesión siguiente; la sesión de roll se excluye.
- **Series:** `raw`, 1 minuto, `America/New_York`, RTH 09:00–15:59 (o cierre anticipado oficial 12:59/13:14).
- **Captura:** una sesión por archivo, después del cierre, con manifiesto `captured_at_et`, `source`, `sha256`, filas, símbolos, contratos, expiries y resultado de validación. Los archivos se agregan al CSV forward en orden; no se editan después del sellado.
- **Sin relleno:** no se interpolan precios, no se derivan símbolos, no se usan barras sintéticas y no se descargan sesiones pasadas para “completar” la muestra. Una sesión perdida se registra como perdida y cuenta para S1.
- **Reglas de integridad:** se heredan D1–D8 del protocolo v1.2: 3 símbolos alineados, 420 velas por sesión (240/255 en cierre anticipado), ORB 09:00–10:00 completo, cero huecos injustificados, contratos y rolls correctos, `series_mode=raw`, `exclude_roll_sessions=true`.

---

## 4. Brazos y configuración congelada

| Brazo | ID | `full` | `risk.min_stop_or_ratio` |
|---|---|---|---:|
| Control | C | Sí | 0,00 (filtro desactivado) |
| Tratamiento | T | Sí | 0,25 |

**Único cambio permitido:** `risk.min_stop_or_ratio`. Todo lo demás se hereda de `docs/protocolo_backtest.lock.json` (`settings`) y debe coincidir exactamente:

- `strategy.use_smt=true`, `entry_reference="or_mid"`, `confirm_tf="15m"`, `retest_tolerance_ticks=12`, `setup_validity_minutes=150`;
- `risk.max_sl_ticks=200`, `risk_per_trade_pct=1,0`, `max_contracts=5`, capital inicial 25.000 USD;
- `execution.tick_size=0,25`, `tick_value=0,50`, comisión 0,62/lado, slippage 1 tick, `fill_model="next_open"`;
- `feed.series_mode="raw"`, `feed.exclude_roll_sessions=true`, `live_enabled=false`.

Antes de capturar, un **lock de ejecución** verifica que el diff entre los dos brazos sea exactamente ese campo y que el código final coincida con la procedencia registrada. Si el diff incluye cualquier otro parámetro, el estudio se aborta.

### 4.1 Qué se registra por señal

Para cada señal que llega al módulo de riesgo se registra:

- `signal_id`, timestamp, dirección, variante;
- `orb_high`, `orb_low`, `orb_width_ticks`;
- `stop`, `stop_ticks`, `ratio`;
- decisión del filtro (`accepted`/`rejected`), motivo literal;
- decisión del resto del riesgo (stop cap, ventana, exclusión, pérdida diaria, cooldown, qty);
- fills, qty, comisiones, slippage, P&L, `r_multiple`, duración, exit reason;
- embudo por sesión: señales, ORB válido, SMT, retesteo, stop cap, ratio, daily loss, qty cero, operaciones.

El ratio se calcula con la misma fórmula y el mismo punto de decisión que `RiskManager._min_stop_or_reason`. No se redondea a dos decimales para decidir: se compara el valor completo con `0,25`. La banda `[0,24, 0,26]` se reporta como diagnóstico de frontera, pero no se usa para cambiar el umbral.

---

## 5. Métricas

### 5.1 Selección

| Métrica | Definición |
|---|---|
| `n_accepted`, `n_rejected` | Tamaño de A y Rj. |
| `mean_r_accepted`, `mean_r_rejected` | Media de `r_multiple` por grupo. |
| `delta_sel` | `mean_r_accepted − mean_r_rejected`. |
| `sum_r_rejected` | Suma de R del cohorte eliminado; debe ser ≤0. |
| `total_r_accepted`, `total_r_baseline` | Suma de R de A y de B. |
| `win_rate`, `median_r`, `sd_r` | Por grupo. |
| `r_profit_factor` | Beneficio bruto en R / |pérdida bruta en R| del grupo aceptado. |
| `acceptance_rate` | `n_accepted / n_baseline`. |

### 5.2 Cartera y riesgo

| Métrica | Definición |
|---|---|
| `net_profit_usd`, `profit_factor_usd`, `expectancy_usd` | Sobre operaciones cerradas, netas de costes. |
| `total_r`, `expectancy_r` | Suma y media de R. |
| `max_drawdown_r`, `max_drawdown_usd` | Curva de R acumulado y curva de P&L cerrado. |
| `max_open_drawdown_usd` | Drawdown abierto, separado. |
| `worst_loss_streak` | Peor racha perdedora. |
| `monthly`, `by_block`, `by_direction` | P&L, operaciones, media R, PF. |
| `sharpe`, `sortino` | Solo descriptivos; no son puerta. |

### 5.3 Robustez y operación

- `drop_best_3_total_r`: R total aceptado tras eliminar las 3 mejores operaciones.
- `drop_best_month_total_r`: R total aceptado tras eliminar el mejor mes.
- `top_trade_share_gross_r`: mejor operación aceptada / beneficio bruto en R.
- `cost_stress`: comisión 1,24/lado y slippage 2 ticks; media R, PF-R y R total.
- `months_with_accepted`, `max_consecutive_zero_months`.
- `missing_sessions`, `missing_by_month`, `max_missing_streak`, `fills_count`.
- `boundary_trades`: operaciones con ratio en `[0,24, 0,26]`, solo diagnóstico.
- `long_short`: operaciones, media R, R total y PF-R por dirección.
- `added_signals_actual_arm`: señales ejecutadas por T que no estén en B; se reportan, pero no se usan para el endpoint primario.

---

## 6. Puertas

Todas las puertas se evalúan una sola vez, al final, con la muestra sellada. Ninguna se relaja después de ver resultados.

### 6.1 Integridad (I)

| ID | Condición | Si falla |
|---|---|---|
| I1 | `protocol_sha256` del lock coincide con este documento; el lock de ejecución y la procedencia del código coinciden | abortar |
| I2 | Todas las sesiones están dentro de `2026-12-01 → 2029-11-30`; cero sesiones de W1–W6, holdout, 2024 o burn-in | abortar |
| I3 | Dataset válido: 39 contratos, 36 rolls, 12 sesiones de roll excluidas, 3 símbolos alineados, ORB completo, cero huecos injustificados | abortar |
| I4 | Captura prospective: manifiesto por sesión, `captured_at_et` del mismo día, sin backfill, sin datos sintéticos, SHA-256 por archivo | abortar |
| I5 | Simetría de brazos: mismo dataset, mismos timestamps, misma configuración salvo `risk.min_stop_or_ratio` | abortar |
| I6 | Ratio válido en el 100 % de las operaciones baseline: `stop_ticks>0`, `orb_width_ticks>0`, finito; `A ∪ Rj = B`, `A ∩ Rj = ∅` | abortar |
| I7 | Sin lookahead: el ratio usa el ORB y el stop conocidos en la señal; ninguna barra posterior al `entry_ts` interviene en la decisión | abortar |
| I8 | Determinismo: replay de una muestra aleatoria del 10 % de las sesiones dos veces produce los mismos `signal_id`, ratios y operaciones | abortar |
| I9 | One-shot: el archivo de análisis final no existe antes de ejecutar; una sola análisis de eficacia | abortar |

### 6.2 Muestra (S)

| ID | Condición | Si falla |
|---|---|---|
| S1 | ≥720/742 sesiones evaluadas; ningún mes <80 %; ningún hueco >5 sesiones consecutivas | `inconcluso` |
| S2 | ≥60 operaciones baseline | `inconcluso` |
| S3 | ≥24 aceptadas y ≥30 rechazadas | `inconcluso` |
| S4 | ≥5/6 bloques con baseline ≥6 y aceptadas ≥2 | `inconcluso` |
| S5 | ≥5 cortos aceptados | `inconcluso_short` |

### 6.3 Eficacia (E)

| ID | Condición | Si falla |
|---|---|---|
| E1 | `delta_sel >= +0,25 R` | `fail` |
| E2 | IC95 % inferior del bootstrap por sesión > 0 | `inconcluso` si el IC incluye 0; `fail` si el IC95 % superior < 0 |
| E3 | `mean_r_accepted >= +0,20 R` | `fail` |

### 6.4 Cartera y robustez (P)

| ID | Condición | Si falla |
|---|---|---|
| P1 | `sum_r_rejected <= 0` | `fail` |
| P2 | `r_profit_factor_accepted >= 1,25` | `fail` |
| P3 | `max_drawdown_r_accepted <= min(8 R, max_drawdown_r_baseline)` y `max_drawdown_usd_treatment <= min(2.000 USD, max_drawdown_usd_baseline)` | `fail` |
| P4 | `sum_r_rejected <= 0` en ≥5/6 bloques | `fail` |
| P5 | `drop_best_3_total_r > 0`, `drop_best_month_total_r > 0` y `top_trade_share_gross_r <= 50 %` | `fail` |
| P6 | Cost stress: `mean_r_accepted > 0` y `r_profit_factor_accepted >= 1,10` | `fail` |
| P7 | Aceptadas en ≥12 de 36 meses y `max_consecutive_zero_months <= 4` | `fail` |
| P8 | Si hay ≥5 cortos aceptados: media R de cortos ≥0 y R total de cortos ≥0 | `fail`; si <5 cortos, `inconcluso_short` |
| P9 | Brazo de tratamiento real: `total_r_treatment >= total_r_baseline` y `max_drawdown_usd_treatment <= max_drawdown_usd_baseline` | `fail` |

### 6.5 Regla de decisión

| Estado | Condición |
|---|---|
| **PASS** | Todas las puertas I, S, E y P pasan. |
| **FAIL** | I y S pasan, y alguna puerta E o P falla con evidencia clara en contra: E1 <+0,25, E3 <+0,20, P1 >0, P2 <1,25, P3 excedido, P4–P9 incumplidas, o E2 con IC95 % superior <0. |
| **INCONCLUSO** | I o S fallan; o E2 incluye 0 sin evidencia clara en contra y el resto de gates no falla; o hay <5 cortos aceptados (`inconcluso_short`). |

- `PASS` no autoriza LIVE. Solo indica que el filtro superó este diseño y puede pasar a un protocolo nuevo de preparación operativa.
- `FAIL` e `INCONCLUSO` no se rescatan cambiando bloques, semilla, ventana, umbral, costes o subgrupos. Exigirían una hipótesis nueva y una muestra nueva.
- No hay análisis intermedio de eficacia. La captura diaria solo produce conteos de integridad (sesiones, filas, huecos, contratos), no P&L ni decisiones.

---

## 7. Análisis estadístico

### 7.1 Bootstrap por sesión

El endpoint primario se contrasta con un bootstrap de conglomerados por sesión:

1. Se parte de las sesiones que contienen al menos una operación baseline.
2. Para cada réplica `b = 1..10.000`, se remuestrean sesiones con reemplazo.
3. Se calcula `Δ*_b = media(R aceptadas en la réplica) − media(R rechazadas en la réplica)`.
4. Si una réplica no contiene aceptadas o no contiene rechazadas, se descarta y se registra; se exigen ≥9.500 réplicas válidas.
5. IC95 % percentil (2,5 / 97,5). p-valor unilateral `(1 + #{Δ*_b <= 0}) / (B_válidas + 1)`.

| Parámetro | Valor |
|---|---:|
| Unidad | Sesión |
| Remuestras | 10.000 |
| Semilla | `20261122` |
| IC | Percentil 95 % |
| Contraste | Unilateral, `H0: Δ <= 0` |
| Mínimo de réplicas válidas | 9.500 |

Se reporta también el bootstrap a nivel de operación como diagnóstico, pero **la puerta E2 usa el bootstrap por sesión**. El bootstrap por operación ignora que puede haber hasta tres operaciones por día y produce intervalos optimistas.

### 7.2 Sin placebo de timing

No se usa un placebo de entradas aleatorias. El filtro no elige el momento de entrada: elimina operaciones después de que la señal existe. El contraste relevante es **aceptadas vs rechazadas sobre el mismo conjunto de señales baseline**, no una entrada aleatoria en la misma sesión. Un placebo de timing respondería a otra pregunta y añadiría ruido sin mejorar la identificación.

### 7.3 Potencia y efecto mínimo detectable

Con 29 aceptadas / 49 rechazadas y una desviación típica de R de ~1,6 (la observada en W1–W6), el error estándar aproximado es 0,375 R y el efecto mínimo detectable al 80 % de potencia, unilateral 0,05, es **~0,93 R**. Con el mínimo de 24/30, sube a **~1,09 R**.

Esto significa:

- el estudio solo tiene potencia razonable para un efecto **grande**;
- si el efecto forward se atenúa a 0,25–0,50 R, el resultado probable será **INCONCLUSO**, no PASS;
- no se baja el umbral para “aprobar” un efecto pequeño; si se quisiera detectar 0,3 R con potencia aceptable haría falta una muestra mucho mayor (varios años más o una muestra histórica externa nueva).

Esta es una limitación estructural de un filtro que deja ~4 operaciones por cada 100 sesiones. Se declara antes de ver datos.

### 7.4 Sin comparaciones múltiples

Hay un solo endpoint confirmatorio (`Δ_sel`) y una sola mirada de eficacia. Los análisis por bloque, dirección, régimen, banda de frontera, costes y concentración son secundarios o puertas de robustez; no se corrige por multiplicidad porque no se usan para declarar eficacia por subgrupo. Si un subgrupo falla, no se busca otro que pase.

---

## 8. Ejecución, congelación y one-shot

### 8.1 Prerrequisitos (fase 0, no es validación)

El lock nace con `execution_gate.can_execute = false`. Antes de capturar hay que resolver, como mínimo:

1. **Captura prospective:** un job que descargue una sesión después del cierre, la valide, la selle y la agregue al CSV forward. El `CSVFeed` actual reproduce un CSV estático; no basta por sí solo.
2. **Universo contractual:** `server/market/databento_fetch.py` fija hoy `QUARTERS` en H25–Z26. Hay que extenderlo a `Z26…Z29` (39 contratos, 36 rolls) sin tocar la lógica de la estrategia.
3. **Credencial:** `DATABENTO_API_KEY` configurada fuera del repositorio. Sin clave no hay captura y no se ejecuta nada.
4. **Preflight y análisis:** un verificador que compruebe hashes, ventana permitida, solapamientos prohibidos, sello del holdout, ausencia del directorio de salida y una única ejecución; y un runner de análisis que solo acepte el lock y el CSV forward sellado.
5. **Tests de plomería:** validar captura, append, sellado, rechazo de fechas prohibidas y reproducibilidad con fixtures sintéticos. No se usan W1–W6 ni el holdout para probar la plomería.

Mientras estos prerrequisitos no estén completos y verificados, **no se captura ni se ejecuta** la validación.

### 8.2 Secuencia de congelación

1. Este documento se hashea y su SHA-256 se registra en `docs/filtro_stop_or_forward.lock.json`.
2. El lock fija la configuración, la muestra, las puertas, la semilla y el carácter one-shot.
3. Antes de la primera captura se crea un **lock de ejecución** que verifica la procedencia del código final. Cualquier cambio de código que afecte estrategia, filtro, salidas, riesgo o ejecución invalida el diseño y exige un lock nuevo; los cambios de plomería que no afecten esas reglas se documentan y se aceptan solo si el lock de ejecución los autoriza.
4. Se ejecuta el burn-in `2026-11-23 → 2026-11-30` para probar captura y sellado. Sus datos no entran en el análisis.
5. La captura válida empieza el `2026-12-01`. No se desplaza la ventana.
6. Al cerrar `2029-11-30`, se ejecuta una sola vez el replay del análisis sobre el CSV forward sellado.
7. Se escriben `analysis.json`, `ANALISIS.md` y los hashes de salida. No se vuelve a ejecutar.

### 8.3 Reglas de una sola ejecución

- El archivo `reports/backtest/filtro_stop_or_forward/analysis.json` debe **no existir** antes del análisis final. Si existe, el runner aborta.
- Se permite **una** análisis de eficacia. Si falla por un defecto técnico antes de producir métricas (excepción, archivo corrupto, error de lectura), se puede repetir una vez con el mismo lock y el mismo dataset, documentando el fallo. Si ya se produjeron métricas, no se repite: se reporta el resultado tal cual.
- Cualquier cambio sustantivo después de empezar la captura —umbral, ventana, gates, configuración, código de estrategia— invalida el estudio. No se “arregla” el resultado con una segunda muestra.

### 8.4 Auditoría

Se conserva, por sesión y por ejecución:

- archivo crudo capturado y su SHA-256;
- manifiesto de captura (`captured_at_et`, fuente, filas, símbolos, contratos, expiries, validación);
- configuración efectiva de ambos brazos y diff exacto;
- hashes de código y del lock;
- salida del preflight;
- JSON/MD del análisis y hash de salida;
- registro de incidencias, sesiones perdidas y correcciones (si las hubiera).

---

## 9. Qué no autoriza este documento

- No autoriza LIVE ni cambia `live_enabled`.
- No autoriza paper en tiempo real; el diseño es captura prospective + replay ciego.
- No modifica `data/config.json`, `profiles/backtest_real/config.json`, `docs/protocolo_backtest.lock.json`, `docs/hipotesis_continuacion_selectiva.lock.json` ni el holdout.
- No reabre W1–W6, 2024 ni el holdout.
- No convierte el resultado de W1–W6 en una validación.
- No autoriza una búsqueda de umbrales, una rejilla de ratios ni una selección de subgrupos.
- No autoriza promoción a live si el resultado es PASS; solo abre un protocolo nuevo de preparación operativa.

---

## 10. Limitaciones

1. **Potencia baja.** El estudio solo detecta efectos grandes (~0,9–1,1 R). Un efecto real moderado puede quedar inconcluso. Es una consecuencia de la baja frecuencia, no un defecto que se corrija bajando el umbral.
2. **No es ejecución en tiempo real.** El replay usa velas de 1 minuto capturadas al cierre; no modela cola, latencia intravela, rechazos de broker ni libro de órdenes. La conclusión es sobre la regla de selección, no sobre la calidad de ejecución.
3. **Rolls y contratos.** La serie es raw, con contratos individuales y sesiones de roll excluidas. El ajuste `boundary` puede mezclar el spread de roll con el movimiento overnight; el diseño usa raw y no adjusted para evitar esa contaminación.
4. **Cambio de régimen.** 36 meses cubren varios regímenes, pero el filtro puede funcionar solo en algunos. La consistencia por bloques y la participación lo detectan; no se añade un régimen como variable post hoc.
5. **Muestra de cortos.** Aunque se esperan ~10–15 cortos aceptados, la muestra por dirección sigue siendo pequeña. P8 exige que los cortos no sean catastróficos, no que tengan una ventaja independiente.
6. **Dependencia intradía.** Hasta tres operaciones por día; el bootstrap por sesión lo corrige parcialmente, pero no modela dependencia entre sesiones.
7. **Datos del proveedor.** Si Databento no entrega el universo contractual completo o la captura falla, el estudio se declara inconcluso; no se sustituye por otro proveedor ni por otro periodo.
8. **Un PASS no es una promesa de rentabilidad.** Solo significa que el filtro superó esta prueba concreta; no garantiza que el edge persista ni que el sistema sea apto para live.

---

## 11. Artefactos

- `docs/VALIDACION_FILTRO_STOP_OR.md` — este protocolo.
- `docs/filtro_stop_or_forward.lock.json` — lock de pre-registro con hash, muestra, puertas y estado `can_execute=false`.
- `reports/backtest/filtro_stop_or_forward/` — directorio futuro para captura, manifiestos y análisis; **no creado** en esta fase.
- `reports/backtest/filtro_stop_or_forward/analysis.json` — salida única futura; no existe.
- `reports/backtest/filtro_stop_or_forward/ANALISIS.md` — informe futuro; no existe.

**Estado actual:** no se ha creado ningún dato, no se ha ejecutado ningún backtest, no se ha abierto el holdout y no se ha modificado la configuración activa.
