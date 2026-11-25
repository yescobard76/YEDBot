# Validación forward pre-registrada — P2, P2 + BE 1R y manual 8765

**Versión:** 2.0  
**Fecha:** 2026-11-24  
**Estado:** pre-registrado y **no ejecutado**. No se ha capturado ni leído ninguna barra forward, no se ha ejecutado ningún backtest nuevo y el holdout `2026-07-01 → 2026-10-30` sigue sellado.  
**Lock:** [`p2_be_1r_forward.lock.json`](p2_be_1r_forward.lock.json).  
**Hipótesis principal:** `H-P2-BE1R-MANUAL-FORWARD`.  
**Ventana:** `2026-12-01 → 2029-11-30`.  
**Brazos:** manual 8765 (`M`), P2 (`C`) y P2 + break-even 1R (`T`).

> Este documento no demuestra que P2 ni P2+BE sean rentables. Fija de antemano qué se medirá, con qué se comparará, qué mejora se exigirá y cuándo el candidato se considera muerto. No modifica `data/config.json`, `profiles/live_8765`, el perfil P2, el protocolo v1.2, sus locks ni el holdout. No autoriza paper en tiempo real ni LIVE.

---

## 1. Pregunta, hipótesis y jerarquía

### 1.1 Pregunta

En una muestra forward independiente:

1. ¿P2 mejora la rentabilidad y el riesgo frente a la configuración manual viva del 8765?
2. ¿P2 + break-even 1R mejora el riesgo ajustado frente a P2 sin destruir demasiado neto?
3. ¿P2 o P2+BE superan a la configuración manual como candidatos de promoción?

La configuración manual es el **benchmark de promoción** del 8765: `max_contracts=10`, `max_sl_ticks=300`, `setup_validity_minutes=210`, `retest_tolerance_ticks=24`, `min_stop_or_ratio=0,00`. No es la configuración original `5/200/150/12`; esa referencia histórica pertenece a otro estudio y no se mezcla aquí.

### 1.2 Hipótesis

**H1 — P2 frente al manual.** En forward, P2 (`C`) mejora `RDD_USD` frente al manual (`M`) al menos un 5 %, con un neto no inferior al 90 % del manual, drawdown absoluto no mayor y profit factor/expectancy que superen las puertas de rentabilidad.

**H2 — BE frente a P2.** En forward, P2+BE (`T`) mejora `RDD_USD` frente a P2 (`C`) al menos un 5 %, con drawdown menor y conservando al menos el 80 % del neto y del R total de P2.

**H3 — P2+BE frente al manual.** En forward, P2+BE (`T`) supera al manual (`M`) en `RDD_USD` al menos un 5 %, con neto no inferior al 90 % del manual, drawdown no mayor y profit factor/expectancy que superen las puertas de rentabilidad.

La hipótesis nula de cada contraste es que la mejora no existe, o que el coste en neto/R o el riesgo absoluto incumplen las puertas. No se promociona “el que menos pierde”: la comparación con el manual exige una mejora de rentabilidad ajustada al riesgo y un límite de give-up.

### 1.3 Endpoint primario y endpoint de rentabilidad

El endpoint primario de promoción es:

```text
RDD_USD = net_profit_usd / max_drawdown_usd
ΔRDD_USD = RDD_USD(candidato) - RDD_USD(manual)
```

- `max_drawdown_usd` es el drawdown máximo de la curva de P&L cerrado, neto de comisiones y slippage.
- `RDD_USD` es la métrica de rentabilidad ajustada por riesgo; un drawdown menor con un neto destruido no es una mejora.
- El **guardián de rentabilidad** es el neto: el candidato debe conservar al menos el 90 % del neto del manual (`PM1`). No se acepta una mejora de RDD que sacrifique más del 10 % del neto.
- Profit factor, expectancy, R total y drawdown son puertas obligatorias, no adornos.
- El endpoint secundario pareado es `ΔR_i = R_i(T) - R_i(C)` por señal común, con bootstrap por sesión. Es diagnóstico y no sustituye al endpoint de cartera.

No hay un endpoint de “mejor neto a cualquier drawdown” ni un endpoint de “menor drawdown a cualquier neto”. La promoción requiere ambas dimensiones.

### 1.4 Por qué el manual no es el control del BE

El manual y P2 no tienen las mismas entradas: `max_sl_ticks=200` rechaza señales cuyo stop supera 200 ticks, mientras el manual (`max_sl_ticks=300`) las acepta. En W1–W6 el manual tuvo 72 operaciones y P2 46; la diferencia incluye operaciones con stops anchos que P2 no puede tomar. Por tanto:

- **M → C** es una comparación de política de riesgo/cartera, no un contraste pareado.
- **C → T** sí es pareado: mismas señales, mismos timestamps y misma configuración; solo cambia la gestión BE.
- **M → T** es una comparación de promoción de cartera; el subconjunto de señales comunes se reporta como atribución, no como endpoint principal.

El cohorte de señales aceptadas por M y rechazadas por C (`stop_ticks > 200`) se reporta con su P&L y R. No se usa para aprobar ni para justificar una promoción; sirve para explicar de dónde viene la diferencia.

### 1.5 Jerarquía de decisión

La secuencia es fija y no se reordena después de ver resultados:

1. **C frente a M:** si C no supera las puertas `PM`, no se promociona ningún candidato; se mantiene M.
2. **T frente a C:** si C pasa `PM` y T no supera las puertas `B`, se puede promover C, no T.
3. **T frente a M:** T solo se promociona si C pasa `PM`, T pasa `B` y T pasa `PM` frente al manual.
4. Si C pasa `PM` y T también, pero T falla `PM` frente al manual, se mantiene C; si C no pasa, se mantiene M.

No hay ajuste por comparaciones múltiples porque la secuencia es jerárquica y cada paso tiene una única decisión. Los análisis por bloque, dirección, mes o régimen son descriptivos y no pueden cambiar la decisión.

---

## 2. Brazos y configuración congelada

### 2.1 Los tres brazos

| Elemento | Manual M | P2 C | P2 + BE 1R T |
|---|---|---|---|
| ID | `M` | `C` | `T` |
| Rol | Benchmark vivo | Candidato P2 | Candidato P2 + BE |
| Perfil | `data/config.json` (copia `profiles/live_8765/config.json`) | `profiles/p2_freq/config.json` | `profiles/p2_freq/config.json` |
| `config_sha256` canónico | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` | `54656561bf692731d71013c6655155a566c9b4b49fe53a88d61bf20814310f4f` | el mismo que C |
| `risk.max_contracts` | 10 | 10 | 10 |
| `risk.max_sl_ticks` | **300** | **200** | 200 |
| `strategy.setup_validity_minutes` | 210 | 210 | 210 |
| `strategy.retest_tolerance_ticks` | 24 | 24 | 24 |
| `risk.min_stop_or_ratio` | 0,00 | 0,00 | 0,00 |
| `risk.risk_per_trade_pct` | 1,0 | 1,0 | 1,0 |
| `risk.max_trades_per_day` | 3 | 3 | 3 |
| `risk.max_concurrent_positions` | 1 | 1 | 1 |
| `strategy.tp_rr` | 3,0 | 3,0 | 3,0 |
| Gestión | ninguna | ninguna | **BE 1R, vela siguiente** |
| `live.live_enabled` | false | false | false |

Hashes de archivo:

- `data/config.json` y `profiles/live_8765/config.json`: `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f`.
- `profiles/p2_freq/config.json`: `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb`.

Los hashes canónicos excluyen `feed`, `live` y `mode`; los hashes de archivo identifican los bytes exactos. Ambos se registran en el lock. El perfil manual es **de solo lectura**: si cambia antes o durante la captura, el estudio se aborta; no se actualiza el benchmark silenciosamente.

### 2.2 Diferencias exactas

El diff permitido es:

```text
M -> C:
  risk.max_sl_ticks: 300 -> 200

C -> T:
  execution management: none -> be_1r_next_bar
```

No hay otras diferencias de estrategia, ejecución, sizing, riesgo, frecuencia, feed, contratos, comisiones o ventana. En particular:

- No se cambia `max_contracts`: 10 en los tres brazos.
- No se cambia `min_stop_or_ratio`: 0,00 en los tres brazos; este estudio no es el filtro 0,25.
- No se cambia `setup_validity_minutes` ni `retest_tolerance_ticks`.
- No se cambia `tp_rr`, `entry_reference`, ORB, SMT ni la geometría de entrada.
- No se cambia el feed entre brazos: el CSV forward es único.
- No se cambia `live.live_enabled`; el replay es aislado y no autoriza LIVE.

El manual conserva su feed operativo solo como referencia de configuración. Para el forward, los tres brazos usan el mismo CSV raw y los mismos overrides de feed; el feed no forma parte del `config_sha256`.

### 2.3 Regla exacta del BE 1R

1. Al entrar, el stop inicial y el target no cambian.
2. Se actualiza el MFE con los máximos/mínimos de las velas de 1 minuto completadas desde la entrada.
3. Cuando una vela completada alcanza `MFE_R >= 1,0`, el stop se mueve al **precio de entrada**, redondeado al tick, y se aplica al empezar la vela siguiente.
4. No se evalúa el nuevo stop dentro de la misma vela que activa el BE. Si esa vela también toca el stop inicial, el stop inicial tiene prioridad; si toca el target y no el stop inicial, se cobra el target y el BE no se aplica.
5. En la vela siguiente, el stop movido sigue la regla normal de fills: si hay gap a través del stop, se usa el precio de apertura y el modelo de slippage del motor.
6. El BE se activa una sola vez por operación. No hay trailing, no hay parcial, no se mueve el target y no se cambia el número de contratos.
7. Si la posición tiene un solo contrato, el BE también se aplica; no se fuerza un parcial imposible.

**Importante:** “break-even” aquí es **break-even de precio**, no contable. El stop se coloca en la entrada sin sumar comisiones ni slippage; una salida en ese stop puede cerrar con una pérdida neta pequeña. El forward debe reportar esas salidas como `be_stop` y no contarlas como ganadoras.

### 2.4 Lo que no es este experimento

- No es el filtro `min_stop_or_ratio=0,25`.
- No es un parcial del 50 % ni un trailing.
- No es una rejilla de umbrales de BE; el umbral es 1R exacto.
- No es una comparación contra la configuración original `5/200/150/12`; esa referencia es histórica y separada.
- No es una prueba de contratos: 10 en los tres brazos.
- No autoriza cambiar la configuración viva del 8765.

---

## 3. Muestra, captura y mínimos

### 3.1 Ventana

| Bloque | Desde | Hasta | Sesiones de calendario | Rolls excluidos | Sesiones evaluadas |
|---|---|---|---:|---:|---:|
| F1 | 2026-12-01 | 2027-05-31 | 124 | 2 | 122 |
| F2 | 2027-06-01 | 2027-11-30 | 127 | 2 | 125 |
| F3 | 2027-12-01 | 2028-05-31 | 125 | 2 | 123 |
| F4 | 2028-06-01 | 2028-11-30 | 127 | 2 | 125 |
| F5 | 2028-12-01 | 2029-05-31 | 124 | 2 | 122 |
| F6 | 2029-06-01 | 2029-11-30 | 127 | 2 | 125 |
| **Total** | **2026-12-01** | **2029-11-30** | **754** | **12** | **742** |

- La ventana se fija antes de capturar. **No se desplaza** si la captura empieza tarde: si no se puede empezar el 2026-12-01, se necesita un lock nuevo con otra ventana y otra muestra.
- **Burn-in:** `2026-11-23 → 2026-11-30`, excluido del análisis. Solo prueba captura, validación y sellado.
- Las 12 sesiones de roll previstas son `2026-12-10`, `2027-03-11`, `2027-06-09`, `2027-09-09`, `2027-12-09`, `2028-03-09`, `2028-06-08`, `2028-09-07`, `2028-12-07`, `2029-03-08`, `2029-06-07`, `2029-09-13`. La sesión de roll se excluye; el contrato saliente sigue activo en ella y el entrante empieza la siguiente.

### 3.2 Muestras prohibidas

| Muestra | Fechas | Por qué está prohibida |
|---|---|---|
| W1–W6 | 2025-01-10 → 2026-06-30 | Usada para descubrir y motivar P2 y BE; es in-sample. |
| Holdout H1 | 2026-07-01 → 2026-10-30 | Sellado por el protocolo v1.2; no se abre para este estudio. |
| 2024 externo | 2024-01-02 → 2024-12-30 | Reservado por otra hipótesis; no es independiente. |
| Burn-in | 2026-11-23 → 2026-11-30 | Solo plomería; excluido del análisis. |
| Muestra compartida | la que use otro lock | Dos hipótesis sobre la misma muestra no son confirmaciones independientes. |

No se leen, descargan, ejecutan ni infieren datos de estas ventanas. **El holdout no se toca.** Cualquier lectura del holdout invalida el estudio y obliga a abortar, no a reclasificar el resultado.

### 3.3 Frecuencia esperada

Con las tasas in-sample de W1–W6:

- Manual: 72 / 362 = 19,9 % → ~148 operaciones en 742 sesiones.
- P2: 46 / 362 = 12,7 % → ~94 operaciones.
- P2+BE: mismas entradas que P2 → ~94 operaciones.
- Pares C/T: ~94, porque C y T comparten entradas.
- Pares M/C y M/T: como máximo ~94; P2 rechaza señales con stop >200 que el manual sí acepta. El solapamiento esperado es alto, pero **no se exige que M y C tengan las mismas entradas**.

Son conteos esperados, no una promesa. La muestra se fija por calendario, no por número de operaciones; si el mercado no genera actividad suficiente, el resultado será `INCONCLUSO`.

### 3.4 Captura

- **Proveedor:** Databento `GLBX.MDP3`, esquema `ohlcv-1m`, simbología `raw_symbol` para MNQ, NQ y ES.
- **Contratos:** 39 en total, 13 por raíz: `Z26, H27, M27, U27, Z27, H28, M28, U28, Z28, H29, M29, U29, Z29`.
- **Rolls:** 12 por raíz (36 en total). El saliente sigue activo en la sesión de roll; el entrante empieza la siguiente; la sesión de roll se excluye.
- **Series:** raw, 1 minuto, `America/New_York`, RTH 09:00–15:59 ET (o cierre anticipado oficial 12:59/13:14).
- **Captura:** una sesión por archivo, después del cierre (16:05 ET o más tarde), con manifiesto, SHA-256 y validación; append-only; no se edita después del sellado.
- **Sin relleno:** no se interpolan precios, no se derivan símbolos, no se usan barras sintéticas y no se descargan sesiones pasadas para “completar”. Una sesión perdida se registra y cuenta para S1.
- **Un solo CSV forward para los tres brazos.** Las diferencias M/C/T se aplican en el replay, no en la captura. No se captura un feed distinto por brazo.

Cada archivo de sesión debe tener un manifiesto con, como mínimo:

```text
window_id, session_date, captured_at_et, provider, schema,
symbols, contracts, expiries, rows_per_symbol,
first_bar_et, last_bar_et, sha256,
validation {ok, aligned, gaps, opening_range_complete, roll_session},
holdout_bars_read=false, forbidden_session=false
```

El CSV agregado y cada archivo de sesión se sellan; el manifiesto se escribe antes de incorporar la sesión al CSV. Si una sesión falla la validación, no se rellena ni se sustituye: se registra como perdida y cuenta para S1. El holdout, W1–W6, 2024 y el burn-in nunca se descargan para este estudio.

### 3.5 Mínimos de muestra

| ID | Condición | Si falla |
|---|---|---|
| S1 | ≥720 de 742 sesiones evaluadas; ningún mes <80 %; ningún hueco >5 sesiones consecutivas | `INCONCLUSO` |
| S2 | ≥60 pares de señales comunes C/T | `INCONCLUSO` |
| S3 | ≥60 operaciones cerradas por brazo (M, C y T) | `INCONCLUSO` |
| S4 | ≥5 de 6 bloques con ≥6 pares C/T por brazo | `INCONCLUSO` |
| S5 | ≥5 cortos por brazo | `INCONCLUSO_SHORT` |
| S6 | ≥20 activaciones BE en T | `INCONCLUSO` |
| S7 | ≥85 % de las señales de C tienen pareja en T | `INCONCLUSO` |
| S8 | ≥60 pares M/C y ≥95 % de las operaciones de C tienen pareja en M | `INCONCLUSO` |

S8 no exige que M y C tengan el mismo número de operaciones: C puede rechazar stops >200. Exige que la comparación de promoción no se apoye en un subconjunto pequeño y que casi todas las operaciones de C estén contenidas en M. Si S8 falla, el problema es de simetría o de datos; no se baja el mínimo.

Si no se cumplen S1–S8, el resultado es `INCONCLUSO`, no aprobado. No se baja el mínimo, no se añaden bloques, no se extiende la ventana, no se rellena una sesión y no se sustituye la muestra.

---

## 4. Métricas y atribución

Todas las métricas se calculan sobre operaciones cerradas, netas de comisiones y slippage.

### 4.1 Rentabilidad

- `net_profit_usd`, `profit_factor`, `expectancy_usd`, `expectancy_r`, `total_r`, `win_rate`.
- `gross_profit`, `gross_loss`, `fees`.
- Por bloque, mes y dirección.

### 4.2 Riesgo y drawdown

- `max_drawdown_usd`, `max_drawdown_pct` (equity cerrada).
- `max_drawdown_r`.
- `max_open_drawdown_usd` y `max_open_drawdown_pct`, separados.
- `worst_loss_streak`.
- `stop_losses`, `be_stops`, `take_profits`, `session_closes`.
- `be_activations`, `be_exits`, `be_exit_net_pnl`.

### 4.3 Riesgo ajustado

```text
RDD_USD = net_profit_usd / max_drawdown_usd
RDD_R   = total_r / max_drawdown_r
```

Si `max_drawdown_usd == 0` o `max_drawdown_r == 0`, el brazo se marca `invalid_drawdown` y no puede aprobar; no se inventa un denominador.

### 4.4 Atribución manual vs P2 y BE

- **M → C:** diferencia de cartera entre M y C; cohorte de señales con `stop_ticks > 200` que M acepta y C rechaza, con su P&L y R. También se reporta el subconjunto de señales comunes M/C.
- **C → T:** operaciones donde el BE se activó y luego se cerró en BE; operaciones que llegaron a target después de activar BE; ganadoras recortadas; perdedoras evitadas; diferencia de qty por camino de equity.
- **M → T:** comparación de cartera y subconjunto común; no se presenta como si fuera un experimento pareado.
- La diferencia de qty entre brazos se reporta, no se corrige a mano.

### 4.5 Robustez

- `drop_best_3_net`: neto tras eliminar las 3 mejores operaciones.
- `top_trade_share_gross`: mejor operación / beneficio bruto.
- `best_month_share_net`: mejor mes / neto.
- Cost stress: comisión `1,24 USD/lado` y slippage `2 ticks` (máximo 4), para M, C y T.
- Resultados por bloque y por dirección.

### 4.6 Estadística

- **Endpoint primario:** `ΔRDD_USD` de cartera, por bloques de 6 meses (6 bloques), porque el drawdown depende del camino.
- **Bootstrap:** 10.000 remuestras de bloques, semilla `20261201`, IC percentil 95 %, mínimo 9.500 réplicas válidas; se concatenan los bloques remuestreados en el orden de sus fechas y se recalculan neto, drawdown y RDD para ambos brazos.
- **Endpoint secundario:** `ΔR_i` por señal común C/T, bootstrap por sesión, misma semilla, IC95 %. Es diagnóstico.
- **M vs C:** bootstrap de bloques para la diferencia de RDD de cartera; el pareado M/C es descriptivo porque las entradas no son idénticas.
- Si una réplica produce drawdown cero en un brazo, se descarta y se registra; no se imputa un denominador.
- No hay análisis intermedio de eficacia. La captura diaria produce solo conteos de integridad, nunca P&L, RDD ni decisiones.

---

## 5. Puertas

Todas se evalúan una sola vez, al final, con la muestra sellada. Ninguna se relaja después de ver resultados.

### 5.1 Integridad (I)

| ID | Condición | Si falla |
|---|---|---|
| I1 | Hash del protocolo, lock, perfiles M/C y política BE verificados; procedencia del código registrada | abortar |
| I2 | Todas las sesiones dentro de `2026-12-01 → 2029-11-30`; cero W1–W6, H1, 2024 o burn-in | abortar |
| I3 | Dataset válido: 39 contratos, 36 rolls, 12 rolls excluidos, 3 símbolos alineados, ORB completo, cero huecos injustificados | abortar |
| I4 | Captura prospective: manifiesto por sesión, `captured_at_et` del mismo día, sin backfill, sin datos sintéticos, SHA-256 por archivo | abortar |
| I5 | Simetría de brazos: M/C solo difieren en `max_sl_ticks`; C/T solo en la política BE; feed, timestamps y resto de configuración idénticos | abortar |
| I6 | BE determinista: MFE sobre velas completadas, activación desde la vela siguiente, una sola activación, sin lookahead | abortar |
| I7 | Sin parcial, trailing, cambio de target, qty o reentrada; la política BE es exactamente `be_1r_next_bar` | abortar |
| I8 | Determinismo: replay del 10 % de las sesiones dos veces produce los mismos `signal_id`, activaciones BE y operaciones | abortar |
| I9 | One-shot: `analysis.json` no existe antes; una sola análisis de eficacia | abortar |
| I10 | `holdout_bars_read=false` y cero sesiones H1; cualquier lectura del holdout invalida el estudio | abortar |
| I11 | `data/config.json` y `profiles/live_8765/config.json` conservan el hash pre-registrado; el benchmark M no cambió | abortar |
| I12 | El CSV forward y cada sesión tienen hash, manifiesto y cadena de custodia; no hay sesiones duplicadas ni fuera de orden | abortar |

### 5.2 Rentabilidad frente al manual (PM)

Aplican a C y a T. Para T, además, deben pasar las puertas B.

| ID | Condición | Si falla |
|---|---|---|
| PM1 | `net_profit_usd_candidato >= 0,90 × net_profit_usd_M` | `FAIL` |
| PM2 | `profit_factor_candidato >= 1,25` y `>= profit_factor_M` | `FAIL` |
| PM3 | `expectancy_r_candidato >= +0,10 R` y `>= expectancy_r_M` | `FAIL` |
| PM4 | `RDD_USD_candidato >= 1,05 × RDD_USD_M`; IC95 % de `ΔRDD_USD` con límite inferior > 0 | `FAIL` |
| PM5 | `max_drawdown_usd_candidato <= max_drawdown_usd_M` y `<= 2.000 USD` | `FAIL` |
| PM6 | `drop_best_3_net_candidato > 0`, `top_trade_share_gross <= 50 %`, `best_month_share_net <= 50 %` | `FAIL` |
| PM7 | Cost stress: `net_candidato > 0` y `profit_factor_candidato >= 1,10` con comisión 1,24/lado y slippage 2 ticks | `FAIL` |
| PM8 | `net_profit_usd_candidato > 0` y `expectancy_usd_candidato > 0` | `FAIL` |

`PM1` es la puerta de rentabilidad: no se acepta una mejora de RDD con más del 10 % de give-up. `PM4` exige una mejora de al menos 5 % en RDD y que el IC no cruce cero. Si el IC incluye cero, el resultado es `INCONCLUSO`, no PASS.

### 5.3 BE frente a P2 (B)

| ID | Condición | Si falla |
|---|---|---|
| B1 | `net_profit_usd_T >= 0,80 × net_profit_usd_C` | `FAIL` |
| B2 | `total_r_T >= 0,80 × total_r_C` | `FAIL` |
| B3 | `max_drawdown_usd_T <= 0,85 × max_drawdown_usd_C` | `FAIL` |
| B4 | `RDD_USD_T >= 1,05 × RDD_USD_C`; IC95 % de `ΔRDD_USD` con límite inferior > 0 | `FAIL` / `INCONCLUSO` si cruza 0 |
| B5 | `profit_factor_T >= 1,25` y `expectancy_r_T >= +0,10 R` | `FAIL` |
| B6 | `worst_loss_streak_T <= 12` y `<= worst_loss_streak_C + 2` | `FAIL` |
| B7 | ≥5/6 bloques con `net_T > 0`; ≥4/6 bloques con `RDD_T > RDD_C`; ningún bloque con DD_T > 1,50 × DD_C | `FAIL` |
| B8 | Cost stress: `net_T > 0` y `profit_factor_T >= 1,10` con comisión 1,24/lado y slippage 2 ticks | `FAIL` |

`B1`/`B2` impiden promover un BE que destruye demasiado neto o R; el límite es 20 %. `B3`/`B4` impiden promoverlo si no reduce el drawdown o no mejora el RDD. Si B4 cruza cero, no hay PASS.

### 5.4 Consistencia

| ID | Condición | Si falla |
|---|---|---|
| C1 | ≥5 de 6 bloques con `net_profit_usd > 0` en el candidato | `FAIL` |
| C2 | ≥4 de 6 bloques con `RDD_USD_candidato > RDD_USD_M` | `FAIL` |
| C3 | Ningún bloque con `max_drawdown_usd_candidato > 1,50 × max_drawdown_usd_M` | `FAIL` |

---

## 6. Decisión, KILL y criterios de parada

### 6.1 Regla de decisión

| Resultado | Condición |
|---|---|
| **ADOPT_T** | Pasan I, S, PM y consistencia para C, PM y consistencia para T, y B; T es el candidato promovido. |
| **ADOPT_C** | Pasan I, S, PM y consistencia para C; T no pasa B, PM o consistencia; C es el candidato promovido. |
| **KEEP_M** | C no pasa PM o consistencia; o C pasa pero T/C no permiten una promoción y C no supera el criterio de promoción elegido. |
| **FAIL (candidato)** | I y S pasan, pero el candidato evaluado falla PM/B/C con evidencia negativa clara. Un FAIL de C implica KEEP_M; un FAIL de T con C válido implica ADOPT_C. |
| **INCONCLUSO** | Fallan I o S; o el IC de RDD incluye 0 sin un fallo claro; o hay <5 cortos; o no se alcanzan los mínimos. |
| **KILL** | Se cumple K1–K5. |

- `ADOPT_*` **no autoriza LIVE**. Solo indica que el candidato superó este protocolo y puede pasar a un protocolo nuevo de preparación operativa.
- `ADOPT_*` no cambia automáticamente `data/config.json` ni el 8765; cualquier cambio de configuración viva es un acto separado, con su propio control de cambios.
- `FAIL`, `INCONCLUSO` y `KILL` no se rescatan cambiando gates, semilla, ventana, costes, subgrupos o el umbral de 1R.
- Si C no pasa PM, no se promociona T aunque T tenga un buen resultado agregado: la comparación de la palanca P2 sería contradictoria y el estudio no tendría una atribución limpia.

### 6.2 KILL

| ID | Condición | Efecto |
|---|---|---|
| K1 | Falla I1–I12, se lee el holdout o la captura no es prospective | abortar el estudio; no hay resultado |
| K2 | `net_profit_usd_C < 0,70 × net_profit_usd_M` o `max_drawdown_usd_C > 1,25 × max_drawdown_usd_M` o `> 2.500 USD` | KILL de C |
| K3 | `net_profit_usd_T < 0,70 × net_profit_usd_C` o `max_drawdown_usd_T > 1,25 × max_drawdown_usd_C` o `> 2.500 USD` | KILL de T frente a C |
| K4 | `net_profit_usd_T < 0,70 × net_profit_usd_M` o `max_drawdown_usd_T > 1,25 × max_drawdown_usd_M` o `> 2.500 USD` | KILL de T frente a M |
| K5 | Candidato con `net_profit_usd <= 0`, `profit_factor < 1,00` o `expectancy_r < 0` | KILL del candidato |

Un KILL cierra esa hipótesis para esta muestra. No se vuelve a ejecutar con otro umbral, no se cambia 1R por 0,75R o 1,25R, no se recorta la ventana y no se busca un subgrupo que pase. Si el problema es de integridad o de muestra, el resultado es `INCONCLUSO`, no KILL económico; para volver a intentarlo hace falta un lock nuevo y una muestra nueva.

### 6.3 Criterios de parada

| ID | Cuándo | Qué ocurre |
|---|---|---|
| STOP-T1 | Falla cualquier I, se detecta una sesión prohibida o se lee el holdout | Abortar de inmediato; no se calculan métricas de eficacia. |
| STOP-T2 | Cambia el hash del protocolo, lock, perfil M/C o política BE antes de ejecutar | Abortar; se necesita un lock nuevo. |
| STOP-T3 | La captura de un mes completado tiene <80 % de sesiones o >5 sesiones consecutivas perdidas | Detener la captura y declarar `INCONCLUSO`; no se rellena ni se extiende la muestra. |
| STOP-F1 | Se alcanza `2029-11-30` con la muestra sellada, o se completan las 742 sesiones evaluadas | Ejecutar una única análisis final. |
| STOP-F2 | Falla S1–S8 | Declarar `INCONCLUSO`; no hay análisis de eficacia. |
| STOP-F3 | Se cumple K2–K5 al final | Declarar `KILL`; no se rescata. |

No hay parada anticipada por P&L, drawdown, RDD, número de ganadoras ni “resultado prometedor”. Tampoco hay parada por futility económica: el diseño es ciego y one-shot. La única parada previa es técnica (STOP-T1/T2/T3) y no produce una decisión de promoción.

La captura diaria solo produce conteos de integridad: sesiones, filas, huecos, contratos, rolls y estado de sellado. **No produce P&L, ni RDD, ni decisiones.** No se mira el resultado de eficacia hasta cerrar la ventana.

---

## 7. Prerrequisitos de ejecución (fase 0)

El lock nace con `execution_gate.can_execute = false`. Antes de capturar o ejecutar hay que resolver, como mínimo:

1. **Política BE ejecutable y versionada.** El BE vive hoy en scripts de investigación (`reports/backtest/run_breakeven_1r_protocol.py`, `reports/backtest/run_partial_exit_1r_full.py`). `run_partial_exit_1r_full.py` fija `min_stop_or_ratio = 0,25` y no sirve tal cual para P2 sin filtro. Se necesita un adaptador/política determinista para el motor de replay, con tests, que:
   - use P2 con `min_stop_or_ratio=0.0`;
   - implemente exactamente la regla de §2.3;
   - registre `be_activated`, `be_activation_ts`, `be_exit`, `be_stop` y `be_mfe_r`;
   - no modifique el motor de producción ni la configuración viva.
2. **Brazo manual materializado sin tocar el 8765.** El runner debe cargar `data/config.json` en modo lectura, aplicar solo los overrides de feed comunes y abortar si el hash cambia. No se crea una copia que pueda divergir del benchmark sin registrarlo.
3. **Captura prospective:** job que descargue una sesión después del cierre, la valide, la selle y la agregue al CSV forward. `CSVFeed` sobre un CSV estático no basta.
4. **Universo contractual:** 39 contratos `Z26–Z29` y 36 rolls; no reutilizar la lista global H25–Z26.
5. **Credencial:** `DATABENTO_API_KEY` fuera del repositorio. Sin clave no hay captura y no se ejecuta.
6. **Preflight y runner one-shot:** verificación de hashes, ventana permitida, fechas prohibidas, holdout sellado, ausencia del directorio de salida y una única ejecución. El runner solo acepta el lock y el CSV forward sellado.
7. **Lock de ejecución:** hash del código final, de los perfiles M/C, de la política BE y del CSV. Cualquier cambio de código que afecte entradas, salidas, riesgo, sizing o BE invalida el lock.
8. **Tests de plomería:** captura, append, sellado, rechazo de fechas prohibidas y reproducibilidad con fixtures sintéticos. No se usan W1–W6 ni el holdout para probar la plomería.

Mientras estos prerrequisitos no estén completos y verificados, **no se captura ni se ejecuta** nada.

---

## 8. Qué no autoriza este documento

- No autoriza LIVE ni cambia `live_enabled`.
- No autoriza paper en tiempo real; el diseño es captura prospective + replay ciego.
- No modifica `data/config.json`, `profiles/live_8765`, `profiles/p2_freq/config.json`, la DB, el protocolo v1.2 ni el holdout.
- No reabre W1–W6, 2024, el holdout ni el burn-in.
- No reutiliza el plan P2 + filtro 0,25 ni sus gates; el filtro queda en 0,00.
- No convierte el resultado in-sample de BE en una validación.
- No autoriza una búsqueda de umbrales, una rejilla de BE/trailing/parciales ni una selección de subgrupos.
- No cambia la prioridad forward actual de `docs/FORWARD_ORIGINAL_VS_P1.md`; es una hipótesis separada y no ejecutable sin un lock de ejecución y una decisión explícita.

---

## 9. Limitaciones

1. **BE de precio, no contable.** Las salidas en BE pueden perder comisiones/slippage; el forward debe medir el neto, no asumir cero.
2. **Timing de vela siguiente.** El BE se aplica desde la vela siguiente a la que alcanza +1R. No se modela el orden intravela; la sensibilidad `be_1r_same_bar` existente no se usa como brazo.
3. **Entradas no idénticas M/C.** `max_sl_ticks=200` rechaza stops >200 que el manual acepta. La comparación M/C es de cartera; el pareado M/C es descriptivo y puede tener selección.
4. **Muestra y potencia.** ~94 pares C/T esperados; el IC puede ser ancho. Un resultado `INCONCLUSO` no se arregla ampliando la ventana después de ver datos.
5. **Dependencia de camino.** El BE cambia el equity y puede cambiar la qty de operaciones posteriores; se reporta la diferencia de qty y el endpoint primario se basa en métricas de cartera.
6. **Seis bloques.** El bootstrap por bloques es grueso; se reporta junto con el bootstrap por sesión, pero el endpoint primario usa bloques.
7. **Un solo endpoint de promoción.** No hay comparaciones múltiples ni subgrupos confirmatorios. Los análisis por dirección, mes o régimen son descriptivos.
8. **No es ejecución real.** El replay con velas de 1m no modela cola, latencia, rechazos de broker ni libro de órdenes.
9. **Muestra compartida.** Si otro forward usa la misma ventana, este estudio deja de ser una confirmación independiente de esa otra hipótesis.
10. **El manual es un benchmark vivo.** Si `data/config.json` o `profiles/live_8765/config.json` cambian, el benchmark pre-registrado deja de ser válido; el estudio se aborta o se rehace con un lock nuevo.

---

## 10. Artefactos y estado

- `docs/P2_BE_1R_FORWARD.md` — este protocolo.
- `docs/p2_be_1r_forward.lock.json` — lock de pre-registro con hashes, brazos, muestra, gates, parada, KILL y estado `can_execute=false`.
- `reports/backtest/p2_be_manual_forward/` — directorio futuro para captura, manifiestos y análisis; **no creado**.
- `reports/backtest/p2_be_manual_forward/analysis.json` — salida única futura; **no existe**.
- `reports/backtest/p2_be_manual_forward/ANALISIS.md` — informe futuro; **no existe**.

**Estado actual:** pre-registrado, no ejecutado. No se ha capturado ni analizado ninguna barra forward. No se ha tocado el holdout, la configuración viva, el 8765, el perfil P2 ni los locks existentes. `execution_gate.can_execute = false`.
