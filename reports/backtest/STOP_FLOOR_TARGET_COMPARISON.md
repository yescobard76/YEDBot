# Comparación stop mínimo — target original vs target recalculado a 3R

**Fecha:** 2026-11-22  
**Alcance:** W1–W6, 362 sesiones de desarrollo. Holdout no usado.  
**Naturaleza:** comparación descriptiva in-sample; no es una validación forward.  
**Fuente nueva:** `reports\backtest\stop_floor_protocol_original_target.json`  
**Comparación estructurada:** `reports\backtest\stop_floor_target_comparison.json`

## 1. Qué se comparó

La rama `stop_floor` amplía el stop a `0,25 × ORB` cuando el stop original es más estrecho, sin rechazar por ratio. Se compararon dos políticas de target:

| Política | Stop | Target |
|---|---|---|
| `floor_recalc` | `0,25 × ORB` | `3R` del stop ampliado |
| `floor_original` | `0,25 × ORB` | target original calculado con el stop original, sin recalcular |

Las dos ramas usan el mismo conjunto de señales y el mismo tope `max_sl_ticks=200`. En ambas, 4 señales de bajo ratio son rechazadas por el tope, no por el ratio; quedan 20 señales de bajo ratio y 14 de alto ratio.

## 2. Resultado agregado

| Brazo | Ops | Neto USD | PF | Expectativa USD | R medio | DD USD | DD % | Peor racha | Neto ex-W4 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 38 | 661,44 | 1,13 | 17,41 | 0,13 | 1.967,82 | 7,14% | 10 | -1.372,68 |
| Rechazo ratio | 14 | 3.026,88 | 3,57 | 216,21 | 1,04 | 839,90 | 3,13% | 4 | 992,76 |
| Floor + target 3R | 34 | 1.724,96 | 1,39 | 50,73 | 0,17 | 1.534,04 | 5,44% | 8 | -309,16 |
| Floor + target original | 34 | 1.363,20 | 1,34 | 40,09 | 0,17 | 1.440,00 | 5,18% | 7 | -670,92 |

El target original **mejora al baseline en USD** (+701,76) y reduce el drawdown (1.440,00 vs 1.967,82), pero **no supera al target recalculado en USD**: queda 361,76 por debajo. El rechazo por ratio sigue siendo muy superior (+3.026,88).

## 2b. La misma comparación en R

La diferencia en USD no es una medida limpia de selección: el tamaño de posición depende de la trayectoria de capital. En R, el target original es ligeramente superior al 3R, aunque ambos floor empeoran a baseline en las 34 operaciones retenidas.

| Cohorte | Baseline R | Floor original R | Floor 3R R | Baseline R-PF | Floor original R-PF | Floor 3R R-PF |
|---|---:|---:|---:|---:|---:|---:|
| 34 comunes | 9,01 | 5,88 | 5,79 | 1,43 | 1,30 | 1,27 |
| 20 bajo ratio | -5,52 | -8,65 | -8,74 | 0,64 | 0,39 | 0,46 |
| 14 alto ratio | 14,53 | 14,53 | 14,53 | 3,66 | 3,66 | 3,66 |

En las 34 operaciones comunes, el baseline suma 9,01R; el floor con target original, 5,88R; y el floor con target 3R, 5,79R. En las 20 de bajo ratio, el baseline suma -5,52R; el original, -8,65R; y el 3R, -8,74R. El target original no crea edge, pero tampoco lo empeora frente al 3R; la ventaja en USD del 3R es tamaño/trayectoria.

## 3. Descomposición stop vs target

| Componente | Neto USD | Lectura |
|---|---:|---|
| Baseline completo | 661,44 | 38 ops |
| 4 ops eliminadas por max_sl | -1.137,08 | Todas de bajo ratio; su exclusión explica la mejora del floor |
| Baseline sobre las 34 ops conservadas | 1.798,52 | Mismo conjunto que el floor |
| Floor + target original | 1.363,20 | 34 ops; 701,76 vs baseline |
| Floor + target 3R | 1.724,96 | 34 ops; 1.063,52 vs baseline |

**Efecto stop con target original:** +701,76 = +1.137,08 por eliminar las 4 ops que superan el tope, menos 435,32 por el peor resultado de las 20 ops de bajo ratio conservadas.

**Efecto target en USD (original → 3R):** +361,76 = +215,50 en las 20 ops de bajo ratio + 146,26 por un efecto de trayectoria/qty en una operación de alto ratio. **En R no hay esa mejora:** el target original suma 5,88R frente a 5,79R del 3R (+0,09R). La diferencia en USD es tamaño/trayectoria, no selección.

**Combinado:** +1.063,52 USD vs baseline; en R, el floor 3R suma 5,79R frente a 9,01R del baseline en las 34 comunes. El rechazo por ratio mejora al floor original en 1.663,68 USD.

La lectura incómoda: el floor **no mejora las 20 operaciones de bajo ratio que conserva**. En R, esas 20 pasan de -5,52R en baseline a -8,65R con target original y -8,74R con target 3R. En USD pierden 1.663,68 y 1.448,18 respectivamente, frente a 1.228,36 del baseline. La mejora agregada del floor viene de que 4 operaciones de bajo ratio, mucho peores, superan el tope de 200 ticks y quedan fuera.

## 4. ¿Conserva los ganadores?

Sí, conserva **como rentables** los 4 ganadores de bajo ratio del baseline, pero con menos P&L. El target recalculado a 3R solo conserva 2 de esos 4.

| Señal | P&L baseline | Stop orig. → floor | Target original | Target 3R |
|---|---:|---:|---:|---:|
| `2025-03-21-long-1742568300` | 501,30 | 68,2 → 150,0 ticks | 300,78 (take_profit, 1,36R) | 668,28 (take_profit) |
| `2025-03-27-long-1743084900` | 456,30 | 61,6 → 153,8 ticks | 273,78 (take_profit, 1,20R) | -234,72 (stop_loss) |
| `2026-05-22-long-1779470100` | 318,80 | 44,0 → 167,0 ticks | 127,52 (take_profit, 0,79R) | -171,48 (stop_loss) |
| `2025-02-11-long-1739286900` | 162,78 | 127,0 → 136,5 ticks | 162,78 (session_close, 2,79R) | 162,78 (session_close) |

Los 4 ganadores suman **1.439,18** en baseline, **864,86** con target original y **424,86** con target 3R. El target original conserva los 4, pero deja de capturar la extensión a 3R; el target 3R conserva solo 2, aunque compensa con otras operaciones.

## 5. Operaciones que cambian entre las dos políticas

| Señal | Ratio | Baseline | Floor original | Floor 3R | 3R − original |
|---|---:|---:|---:|---:|---:|
| `2025-01-15-long-1736953200` | 0,108 | -168,70 | 309,78 (take_profit) | 713,28 (take_profit) | 403,50 |
| `2025-02-14-long-1739545200` | 0,830 | 292,52 | 292,52 (session_close) | 438,78 (session_close) | 146,26 |
| `2025-03-21-long-1742568300` | 0,114 | 501,30 | 300,78 (take_profit) | 668,28 (take_profit) | 367,50 |
| `2025-03-27-long-1743084900` | 0,100 | 456,30 | 273,78 (take_profit) | -234,72 (stop_loss) | -508,50 |
| `2026-05-22-long-1779470100` | 0,066 | 318,80 | 127,52 (take_profit) | -171,48 (stop_loss) | -299,00 |
| `2026-05-26-long-1779804000` | 0,086 | -8,70 | -3,48 (take_profit) | 248,52 (take_profit) | 252,00 |

La operación `2025-02-14` es de alto ratio y no recibe floor; su diferencia es un efecto de qty/trayectoria de capital, no del target. El efecto puro de target en el cohorte de bajo ratio es +215,50 USD; el resto (+146,26) es trayectoria.

## 6. Conclusión

- El target original **sí conserva a los 4 ganadores** de bajo ratio, pero su P&L agregado cae de 1.439,18 a 864,86 USD.
- El target recalculado a 3R **pierde 2 de esos 4 ganadores**, pero gana más en `2025-03-21` y convierte dos perdedores en ganadores; por eso su neto en USD es 361,76 mayor. **En R, en cambio, el original es ligeramente superior (5,88R vs 5,79R): la ventaja en USD del 3R es tamaño/trayectoria, no edge.**
- El floor, con cualquiera de las dos políticas, **sigue sin arreglar el cohorte de bajo ratio**: las 20 operaciones conservadas pasan de -5,52R en baseline a -8,65R/-8,74R, y pierden entre 1.448 y 1.664 USD. Su mejora sobre baseline depende de eliminar 4 operaciones por el tope de 200 ticks.
- Por tanto, separar stop y target no rescata la idea: el target original preserva los ganadores y no empeora el R, pero no mejora el agregado en R; el target 3R mejora el USD por tamaño/trayectoria, a costa de perder ganadores. El rechazo por ratio sigue siendo la alternativa claramente superior en W1–W6.
- Este resultado es **in-sample** y no valida el filtro ni el floor. No se abrió el holdout.
