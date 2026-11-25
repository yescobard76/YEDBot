# Cierre de misión — configuración manual del 8765

**Veredicto de rentabilidad y mejoras priorizadas**

| Campo | Valor |
|---|---|
| Fecha de cierre | 2026-11-24 (UTC) |
| Última lectura del 8765 | `2026-11-24T10:10:38Z` (`server_time` de `/api/status`) |
| Tipo de pase | Read-only: sin backtest nuevo, sin cambio de config, sin escritura en DB, sin acceso al holdout, sin reinicio del 8765 |
| Muestra | W1–W6: 2025-01-10 → 2026-06-30; 362 sesiones; 72 operaciones vivas y 38 originales |
| Holdout | H1 2026-07-01 → 2026-10-30, 85 sesiones, `sealed_not_executed`; `holdout_used=false` |
| Estado del 8765 | Proceso vivo, PID **15108**, `/api/health` **200**; motor en `paper`, `status=stopped`, `live_enabled=false` en la lectura |
| Config viva efectiva | `10 contratos / SL 300 / validez 210 / retest 24 / replay 8× / min_stop_or_ratio 0,00` |
| Original establecida | `5 contratos / SL 200 / validez 150 / retest 12 / replay 4,5× / min_stop_or_ratio 0,00` |

## 0. Veredicto en una frase

> **En W1–W6 (in-sample), la configuración viva del 8765 es mejor en neto bruto, expectancy R y profit factor que la original, pero peor en drawdown; la diferencia de neto no es estadísticamente distinguible de cero. No es evidencia forward y no autoriza a cambiar la configuración ni a declarar que la viva sea superior.**

La lectura completa es: **mejor rentabilidad histórica observada, peor riesgo absoluto, confianza predictiva insuficiente**. No es una configuración “ganadora” validada; es una configuración que en esta muestra produjo más dinero asumiendo más drawdown y tomando más señales.

### 0.1 Recomendación en tres líneas

1. **No cambiar el 8765 hoy.** Se mantiene `10/300/210/24`, `min_stop_or_ratio=0,00`, en paper y con `live_enabled=false`.
2. **Promover a un pre-registro nuevo solo el brazo “viva + filtro 0,25”**: es el de mayor mejora con muestra utilizable (43 operaciones, +1.786,66 USD y −1.231,62 USD de DD frente a la viva), pero sigue siendo exploratorio y tiene un confusor de sizing.
3. **No promover** el filtro 0,25 sobre P2 (17 operaciones, gates `INCONCLUSO`), ni P2+BE, ni P1/5 contratos, ni replay 1×, ni subir el tamaño por encima de 10. La mejora M-SL200 ya tiene un forward pre-registrado; se ejecuta cuando su lock lo permita, no se re-promociona.

## 1. Qué configuración está viva ahora en el 8765

### 1.1 Proceso y servicio

La configuración se leyó del proceso que escucha en el puerto 8765, no de memoria ni de una copia del archivo:

| Comprobación | Resultado |
|---|---|
| `GET http://127.0.0.1:8765/api/health` | **200** |
| `GET http://127.0.0.1:8765/api/config` | 200; `settings` de la tabla 1.2 |
| `GET http://127.0.0.1:8765/api/status` | 200; `mode=paper`, `status=stopped`, `session_date=null` en la lectura final |
| Proceso | PID **15108**; `StartTime=2026-11-23T20:12:49-06:00` (11/23/2026 8:12:49 PM) |
| `live.live_enabled` | **false** (`/api/config.settings.live`) |
| `/api/health` después del cierre | **200**, mismo PID 15108 |

**Matiz importante:** el proceso está vivo, pero el motor no está ejecutando una sesión en el momento de la lectura (`status=stopped`). No se reinició, no se alteró y no se le envió ninguna orden de arranque o parada. Las cifras de rentabilidad de este informe no salen de esa lectura de runtime: salen de los artefactos W1–W6 ya producidos.

### 1.2 Parámetros efectivos de la viva

| Parámetro | Valor efectivo | Fuente |
|---|---:|---|
| `mode` | `paper` | `/api/status` |
| `live.live_enabled` | `false` | `/api/config.settings` |
| `risk.max_contracts` | **10** | `/api/config.settings` |
| `risk.max_sl_ticks` | **300** | `/api/config.settings` |
| `risk.min_stop_or_ratio` | **0,00** | `/api/config.settings` |
| `risk.risk_per_trade_pct` | **1,0** | `/api/config.settings` |
| `risk.max_trades_per_day` | **3** | `/api/config.settings` |
| `strategy.setup_validity_minutes` | **210** | `/api/config.settings` |
| `strategy.retest_tolerance_ticks` | **24** | `/api/config.settings` |
| `strategy.tp_rr` | **3,0** | `/api/config.settings` |
| `feed.replay_speed` | **8,0** | `/api/config.settings` |
| `feed.csv_path` | `data/bars.csv` | `/api/config.settings` |
| `feed.series_mode` | `adjusted` | `/api/config.settings` |

La configuración efectiva de `/api/config.settings` coincide con `data/config.json` y con `profiles/live_8765/config.json`: ambos archivos tienen el mismo SHA-256, `9bf4f9c7…`. No hay una discrepancia entre “lo que dice el archivo” y “lo que cargó el proceso”.

### 1.3 Original establecida

La original del protocolo es la configuración de control `5/200/150/12`:

| Parámetro | Original establecida |
|---|---:|
| `risk.max_contracts` | **5** |
| `risk.max_sl_ticks` | **200** |
| `risk.min_stop_or_ratio` | **0,00** |
| `risk.risk_per_trade_pct` | **1,0** |
| `risk.max_trades_per_day` | **3** |
| `strategy.setup_validity_minutes` | **150** |
| `strategy.retest_tolerance_ticks` | **12** |
| `strategy.tp_rr` | **3,0** |
| `feed.replay_speed` | **4,5** |
| `feed.csv_path` | `data/bars.csv` |
| `feed.series_mode` | `adjusted` |

**Trazabilidad del “150/12”:** `profiles/backtest_real/config.json` conserva en disco `210/24`; el brazo original se fija en memoria con el parche de frecuencia `150/12` que aplica el arnés de comparación. El hash `8fd7cfa2…` es el del archivo con `210/24`, no el de la frecuencia efectiva original. Esta es una particularidad del artefacto, no un cambio de configuración: no se modificó el archivo.

La API también expone `defaults` con `5/200/150/12` y `feed.replay_speed=2,5`. No se usa para el brazo original: la original establecida de la comparación es `5/200/150/12` con replay `4,5`, según `config_diff` de [S1]. La diferencia de replay es operativa y no afecta al P&L.

### 1.4 Diff entre la viva y la original

El `config_diff` del artefacto principal contiene exactamente cinco diferencias:

| Parámetro | Viva 8765 | Original | Δ | Lectura |
|---|---:|---:|---:|---|
| `risk.max_contracts` | 10 | 5 | **+5** | Más tamaño por señal; añade neto y DD |
| `risk.max_sl_ticks` | 300 | 200 | **+100** | Acepta stops más profundos; en W1–W6 destruye neto y DD |
| `strategy.setup_validity_minutes` | 210 | 150 | **+60** | Más oportunidades; principal fuente de cobertura |
| `strategy.retest_tolerance_ticks` | 24 | 12 | **+12** | Más oportunidades; parte de la cobertura |
| `feed.replay_speed` | 8,0 | 4,5 | **+3,5** | Operativo; sin efecto económico medido |

No hay otras diferencias en `config_diff`. En particular:

- `risk.min_stop_or_ratio` es **0,00 en ambas**: la viva **no** tiene el filtro 0,25. El filtro es una hipótesis de este informe, no la configuración actual.
- `risk.max_trades_per_day=3`, `risk.risk_per_trade_pct=1,0` y `strategy.tp_rr=3,0` son iguales en ambas.
- `feed.replay_speed` es una palanca de ejecución, no de edge: el propio artefacto registra **0,00 USD** de diferencia entre 8× y 1× en W1. No se usa para explicar rentabilidad.

### 1.5 Hashes y mtime de la captura inicial

| Archivo | SHA-256 | mtime (local) | Tamaño |
|---|---|---|---:|
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | 2026-11-22 20:36:50.479925700 −0600 | 2.381 B |
| `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | 2026-11-23 19:59:39.851830200 −0600 | 2.381 B |
| `data/bars.csv` | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` | 2026-11-19 21:21:09.945922600 −0600 | 38.312.629 B |
| `data/yedbot.db` | `af5bce151fcace45367afa2351ebed9cf89c2fd0ddf75d3439d0f9d7a2a7fd7d` | 2026-11-23 19:53:07.418193100 −0600 | 225.280 B |
| `profiles/live_8765/yedbot.db` | `d99f115d3169f09bdaef1952420da1d1b05e8dd3e283af05c9311dcbbd801fce` | 2026-11-24 03:27:55.165943800 −0600 | 319.488 B |

La segunda DB es la DB del perfil vivo; la primera es la DB de `data/`. Ambas se leyeron solo para hash/mtime. La DB viva ya tenía su mtime antes de la lectura de la API y no se escribió en este pase.

## 2. Veredicto de rentabilidad viva vs original

### 2.1 Muestra y método

- Misma muestra idéntica W1–W6: **362 sesiones**, del **2025-01-10** al **2026-06-30**, `data/bars.csv`, serie `adjusted`, capital inicial 25.000 USD.
- No se usó 2024. No se usó el holdout H1. `holdout_used=false` y `holdout_accessed=false` en los artefactos.
- No se relanzó ninguna simulación: las cifras salen de `live_vs_original_mission.json` y de los artefactos de filtro ya existentes.
- No es un experimento aleatorizado: son dos ejecuciones sobre el mismo corpus. La comparación pareada se hace en la intersección de señales, no en el agregado.

### 2.2 Tabla principal

| Métrica | Viva `10/300/210/24` | Original `5/200/150/12` | Δ (viva − original) |
|---|---:|---:|---:|
| Operaciones | **72** | **38** | **+34** (+89,5 %) |
| Neto | **+2.022,94 USD** | **+661,44 USD** | **+1.361,50 USD** (+205,8 %) |
| Expectancy R | **0,180** | **0,130** | **+0,050** |
| Expectancy R exacta (`total_r/trades`) | 0,1832 | 0,1311 | +0,0521 |
| Profit factor | **1,22** | **1,13** | **+0,09** |
| Drawdown máximo | **2.891,66 USD** | **1.967,82 USD** | **+923,84 USD** (peor) |
| Drawdown % | **9,793 %** | **7,141 %** | **+2,652 pp** (peor) |
| Win rate | **36,11 %** | **31,58 %** | **+4,53 pp** |
| RDD (`neto/DD`) | **0,6996** | **0,3361** | **+0,3635** |

Lectura: la viva gana en **neto, expectancy, PF, win rate y RDD**, pero pierde en **drawdown absoluto y porcentual**. El mayor neto no es gratis: se paga con **+923,84 USD** de DD, un **46,9 %** más de drawdown absoluto. Si el objetivo es solo rentabilidad bruta, la viva gana; si el objetivo es rentabilidad con control de riesgo, la respuesta es mixta.

### 2.3 De dónde viene la diferencia

La ventaja agregada **no** viene de ejecutar mejor las mismas señales. Viene de tomar más señales:

| Grupo | Operaciones | Neto | Lectura |
|---|---:|---:|---|
| Señales comunes | 37 | Viva **752,02** / Original **910,14** | En las señales que ambas toman, la viva **pierde 158,12 USD** |
| Solo viva | 35 | **+1.270,92** | Cobertura adicional; explica el grueso de la ventaja |
| Solo original | 1 | **−248,70** | La original toma una señal que la viva no toma |
| Total | 72 / 38 | **+2.022,94 / +661,44** | Cuadra con la tabla 2.2 |

Cobertura: la viva comparte **37/72 = 51,4 %** de sus señales con la original; la original comparte **37/38 = 97,4 %** de las suyas. La viva es, en la práctica, otro conjunto de señales más amplio, no una versión mejorada del mismo conjunto.

La atribución secuencial del artefacto lo descompone así:

| Palanca | De → a | Δ neto | Δ DD | Δ PF |
|---|---|---:|---:|---:|
| Frecuencia 210/24 | original → P1 | **+1.330,82** | −20,00 | +0,24 |
| `max_contracts` 5 → 10 | P1 → P2 | **+479,52** | +356,64 | +0,02 |
| Stop 200 → 300 | P2 → viva | **−448,84** | +587,20 | −0,17 |
| **Total** | original → viva | **+1.361,50** | **+923,84** | **+0,09** |

Dos conclusiones importantes:

1. **La frecuencia 210/24 es la principal fuente de neto** (+1.330,82), pero también amplía el conjunto de señales y, con ello, el riesgo.
2. **El stop 300 es un lastre**, no una ventaja: al pasar de SL200 a SL300 se pierden **448,84 USD** y se añaden **587,20 USD** de DD. La viva gana a la original *a pesar* del stop 300, no *gracias* a él.

### 2.4 Significancia y estabilidad

El bootstrap por bloques de ventana (6 bloques, 10.000 remuestreos) da:

| Estadístico | Valor |
|---|---:|
| Δ neto medio | **+1.390,94 USD** |
| IC 95 % | **[−3.056,32 ; +6.965,66]** |
| p bilateral | **0,6544** |
| ¿Incluye cero? | **Sí** |

Con solo 6 bloques, el test tiene poca potencia; el resultado correcto no es “la viva es mejor”, sino **“no se puede distinguir de cero con esta muestra”**. La ventaja puntual de +1.361,50 USD es compatible con azar de muestra y con una dependencia fuerte de pocas ventanas.

### 2.5 Qué es in-sample y qué no autoriza

**Es in-sample:** todo W1–W6, 2025-01-10 → 2026-06-30. Es la misma muestra que se usó para elegir y comparar las variantes; no es una muestra independiente.

**No autoriza:**

- No autoriza a declarar la viva superior a la original.
- No autoriza a cambiar la configuración del 8765.
- No autoriza a activar `live_enabled`.
- No autoriza a usar el holdout H1 para “confirmar” nada.
- No autoriza a presentar el +205,8 % de neto como expectativa forward.
- No autoriza a ignorar el peor DD: +923,84 USD es un coste de riesgo real, no un detalle.

### 2.6 La lectura de runtime no es esta muestra

La DB del perfil vivo contiene operaciones de runtime que **no** son las 72 operaciones de W1–W6. La lectura de `/api/status` devuelve `status=stopped` y `mode=paper`; esa lectura no se usa para el veredicto. Tampoco se usa la DB viva para calcular neto, PF o DD: esas métricas salen exclusivamente de los artefactos W1–W6.

En la comprobación final, `/api/status.stats` muestra **72 trades, 2.269,38 USD, PF 1,23 y DD 3.099,36 USD**. No coincide con el artefacto W1–W6 (**72, 2.022,94, PF 1,22, DD 2.891,66**) y no se usa: es la última lectura de runtime, no la comparación controlada. La diferencia refuerza que el veredicto debe salir del artefacto, no de la pantalla del bot.

### 2.7 Frase de veredicto

**La viva es mejor en rentabilidad bruta (+1.361,50 USD, PF 1,22 vs 1,13, expectancy 0,180 vs 0,130), pero peor en riesgo (+923,84 USD de DD) y la diferencia no es estadísticamente distinguible; en W1–W6 es una observación in-sample, no una validación forward.**

## 3. Mejoras propuestas, ordenadas por rentabilidad esperada

### 3.1 Ranking nominal

Orden por **Δ neto histórico frente a la viva** en W1–W6. La columna “¿Promover?” corrige por muestra, gates y riesgo; no coincide necesariamente con el orden nominal.

| # | Propuesta | Δ neto vs viva | Neto del brazo | DD | PF | Ops | ¿Promover? |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | **P2 + filtro 0,25** (`SL200`, `min_stop_or_ratio=0,25`) | **+2.179,26** | 4.202,20 | 946,38 | 4,25 | 17 | **No**: gates `INCONCLUSO`; 17 ops; P6 no evaluable |
| 2 | **Viva SL300 + filtro 0,25** (solo cambia el filtro) | **+1.786,66** | 3.809,60 | 1.660,04 | 1,92 | 43 | **Sí, a lock nuevo**; exploratorio y con confusor de sizing |
| 3 | **M-SL200 / P2** (`max_sl_ticks 300→200`) | **+448,84** | 2.471,78 | 2.304,46 | 1,39 | 46 | **Sí, pero en el forward ya pre-registrado**; PM5 histórico falla |
| 4 | **P2 + BE 1R** | **+13,58** | 2.036,52 | 1.794,46 | 1,48 | 46 | **No**: mejora de riesgo, no de neto frente a P2 (−435,26) |
| 5 | **P1 / 5 contratos** (`5/200/210/24`) | **−30,68** | 1.992,26 | 1.947,82 | 1,37 | 46 | **No**: reduce riesgo, no sube neto |
| 6 | **Replay 8× → 1×** | **0,00** | — | — | — | — | **No**: operativo, sin efecto económico |

La lectura de prioridad es incómoda pero clara: **el mayor número nominal (P2 + filtro) no es el mejor candidato a promoción**, porque tiene 17 operaciones y gates que no pasan. El mejor candidato *promovible* es el **#2**, que conserva el SL300 actual y tiene 43 operaciones. El **#3** ya está dentro de un pre-registro existente y no necesita un lock nuevo.

### 3.2 #1 nominal — P2 + filtro 0,25: el número grande, poca credibilidad

**Cambio concreto:** mantener P2 (`max_contracts=10`, `max_sl_ticks=200`, `setup_validity=210`, `retest=24`) y añadir `risk.min_stop_or_ratio=0,25`. Es un cambio de un solo parámetro respecto de P2, pero **no** es la configuración viva: la viva tiene SL300.

**Mecanismo:** el filtro exige que la distancia al stop, normalizada por el rango ORB, sea al menos 0,25. Rechaza entradas con stops estrechos, que en la muestra son las de peor R realizado. Sobre P2 acepta 17 de 46 operaciones y rechaza 29; el neto sube de 2.471,78 a 4.202,20, el PF de 1,39 a 4,25 y el DD baja de 2.304,46 a 946,38. La selección aporta **1,3602 R** y el placebo de selección da **p=0,0065**; los LOBO son positivos y los umbrales 0,15–0,35 son positivos.

**Evidencia:**

- 17 operaciones; **+4.202,20 USD**; expectancy **1,11 R**; PF **4,25**; DD **946,38**; win rate **58,82 %** [S1, S3].
- Frente a la viva: **+2.179,26 USD** de neto y **−1.945,28 USD** de DD; frente a P2: **+1.730,42 USD** y **−1.358,08 USD** de DD [S1].
- Gates: **INCONCLUSO** global; **13 PASS / 4 FAIL / 5 INCONCLUSO / 1 NO_EVALUABLE**; P6_COST_STRESS **NO_EVALUABLE**; promoción **NO** [S4, S5].
- Cobertura: 4/6 trimestres activos, W5/W6 sin aceptadas; top-2 trimestres = **85,28 %** del neto; top-5 trades = **61,23 %** del bruto; 10/18 meses activos; racha de 6 meses sin operar [S5, §4.6].

**Riesgo/coste:** es una selección post hoc sobre **17 operaciones**, con concentración extrema y sin reprecio exacto de costes. El PF 4,25 no es una expectativa forward; es el resultado de una muestra pequeña y muy concentrada. Los gates ya la declararon no promocionable; no se debe “arreglar” bajando el umbral ni cambiando la ventana.

**Test exacto:** el lock existente **`H-P2-FILTER-STOP-OR-025`** [S8], one-shot, con sus gates E1/E2/E3, P1–P9 y P6 de costes. Ese lock ya está en **INCONCLUSO** y no puede promocionar; no se reabre en este cierre. Para reabrirla haría falta un lock nuevo con P6 exacto y una muestra que supere las precondiciones de cobertura; no se propone ahora.

**Por qué no se promueve:** aunque el Δ neto sea el mayor, la evidencia es demasiado delgada y los gates ya la rechazaron para promoción. Sería el error clásico de elegir el número más alto ignorando la muestra.

### 3.3 #2 — Viva SL300 + filtro 0,25: el candidato promovible

**Cambio concreto:** mantener exactamente la viva (`10/300/210/24`, `replay 8×`, `min_stop_or_ratio=0,00`) y cambiar **solo** `risk.min_stop_or_ratio` de **0,00 a 0,25**. No se cambia el stop, ni el sizing, ni la frecuencia, ni el feed.

**Mecanismo:** el filtro exige stops no demasiado estrechos respecto del ORB. En la muestra viva rechaza **29 de 72** operaciones; ese cohorte rechazado pierde **−1.786,66 USD**, tiene expectancy **−0,250 R**, PF **0,65** y win rate **17,24 %**. Al evitarlo, el brazo aceptado hace **+3.809,60 USD**, PF **1,92**, DD **1.660,04** y win rate **48,84 %**. El mecanismo es selección de entradas, no mejores salidas.

**Evidencia:**

| Métrica | Viva sin filtro | Viva + filtro 0,25 | Δ |
|---|---:|---:|---:|
| Operaciones | 72 | **43** | **−29** |
| Neto | 2.022,94 | **3.809,60** | **+1.786,66** |
| Expectancy R | 0,180 | **0,480** | **+0,300** |
| PF | 1,22 | **1,92** | **+0,70** |
| DD | 2.891,66 | **1.660,04** | **−1.231,62** |
| DD % | 9,793 % | **5,805 %** | **−3,988 pp** |
| Win rate | 36,11 % | **48,84 %** | **+12,73 pp** |

- Cohorte rechazado: 29 operaciones, **−1.786,66 USD**, expectancy **−0,250 R**, PF **0,65**, win rate **17,24 %** [S2].
- Todos los **17** trades con `qty > 5` fueron rechazados; el máximo observado baja de 10 a **5**. El SL300 queda intacto [S2].
- Por ventana: W1 **−566,42**; W2 **−87,96**; W3 **+524,28**; W4 **0,00**; W5 **+1.497,14**; W6 **+419,62**. El DD baja o queda igual en todas las ventanas; el neto solo sube en 3/6 [S2].
- `hashes.unchanged=true`; `holdout_used=false`; última barra `2026-06-30 15:59` [S2].

**Riesgo/coste:**

- **Es exploratorio, no pre-registrado.** El pre-registro existente del filtro 0,25 es sobre P2/SL200, no sobre SL300; no se puede heredar su validez.
- **Confusor de sizing:** el filtro rechaza todos los `qty > 5`; parte de la mejora de DD es menor exposición, no solo mejor selección. Para separar selección de sizing, el forward debe comparar con el mismo `max_contracts=10` y reportar el efecto del tamaño; si el edge desaparece al igualar tamaño, no es un edge de selección.
- **Dependencia de W5:** W5 aporta **1.497,14 / 1.786,66 = 83,8 %** del Δ neto; W1 y W2 son negativas. Es una señal de concentración, no de robustez.
- **Sin P6 exacto:** no hay reprecio estresado de este brazo; el coste base está en el neto, pero el estrés de comisión/slippage sigue pendiente.
- **Umbral elegido en una muestra:** 0,25 se fijó mirando datos; el lock nuevo debe congelarlo antes del forward, sin probar 0,20/0,30 después.

**Test exacto:** un lock nuevo, **`H-LIVE-FILTER-STOP-OR-025`**, one-shot y sin mirada intermedia:

- **Control C:** viva actual `10/300/210/24`, `min_stop_or_ratio=0,00`, `replay 8×`.
- **Tratamiento T:** idéntico, solo `min_stop_or_ratio=0,25`.
- Misma ventana prospectiva, mismo feed, mismo modelo de fills, mismo sizing, mismas comisiones/slippage; **solo** cambia el filtro.
- **Criterios de aceptación, congelados antes de ver el forward:**
  1. **Δ neto (T−C) ≥ +500 USD** (referencia: +1.786,66 histórico; se exige ~28 % para no promover por ruido).
  2. **IC 95 % del Δ neto > 0** por bootstrap de bloques.
  3. **PF_T ≥ 1,30** (por encima de la viva 1,22; por debajo del 1,92 histórico).
  4. **DD_T ≤ 2.500 USD y ≤ DD_C** (protege el riesgo; la viva está en 2.891,66).
  5. **≥ 30 operaciones T** (la muestra histórica tiene 43; 30 es el mínimo de utilidad).
  6. **Δ neto > 0 en ≥ 3/6 bloques**; si un solo bloque concentra **> 80 %** del Δ, se considera no robusto y no se promueve.
  7. **Cost stress** con comisión 1,24/lado y slippage 2 ticks: Δ neto > 0. Si no se puede repreciar, no se promueve.
- **Falsificación:** si falla cualquiera de 1–7, se mantiene la viva y no se cambian umbral, ventana ni métrica.

**Por qué se promueve:** es la mayor mejora con una muestra utilizable (43 ops), conserva el SL300 actual (evita el problema PM5 de SL200) y el cambio es de un solo parámetro. No es una promesa: es la hipótesis que merece un forward.

### 3.4 #3 — M-SL200 / P2: ya está pre-registrada, no se re-promociona

**Cambio concreto:** `risk.max_sl_ticks` de **300 a 200**; todo lo demás igual (`10/210/24`, `min_stop_or_ratio=0,00`). Es el brazo **P2** de la comparación.

**Mecanismo:** rechaza las señales con stop superior a 200 ticks. En W1–W6 pasa de 72 a 46 operaciones; evita el cohorte de 26 operaciones con stop >200 que pierde **−392,60 USD** [S1]. El neto sube a **2.471,78**, el PF a **1,39**, la expectancy a **0,25 R** y el DD baja a **2.304,46**.

**Evidencia:**

- 46 operaciones; **+2.471,78**; expectancy **0,25 R**; PF **1,39**; DD **2.304,46**; win rate **32,61 %** [S1].
- Frente a la viva: **+448,84 USD**, **−587,20 USD** de DD, **+0,07 R**, **+0,17 PF**, **−26 operaciones** [S1].
- PM5 histórico: **falla** porque el DD **2.304,46 > 2.000**; el límite de DD del lock no se cumple [S5, S6, S7].
- La comparación no es pareada: P2 no ejecuta las 26 señales que la viva sí toma; la ventaja se apoya en evitar ese cohorte, no en ejecutar mejor las mismas entradas [S5, §4.2].

**Riesgo/coste:** PM5 ya falla en la muestra; el DD absoluto sigue por encima de la original (1.967,82) y de 2.000; la lectura viva de runtime no tiene la potencia ni el diseño para confirmar la mejora y no se usa. No hay forward ejecutado. El beneficio es menor que el de los dos filtros y no compensa el riesgo de promoverlo solo.

**Test exacto:** el lock **M/C/T** ya existente, `docs/p2_be_1r_forward.lock.json` [S7]. Para C (M-SL200) los gates son PM5 (`DD_C ≤ DD_M` y `DD_C ≤ 2.000`), K2 (`net_C ≥ 0,70 × net_M`, `DD_C ≤ 1,25 × DD_M`, `DD_C ≤ 2.500`) y K5 (`net > 0`, `PF ≥ 1,00`, `expectancy_r ≥ 0`). Si C falla PM5 o K2/K5, la decisión es **`KEEP_M`**; T no rescata a C. El lock está en `can_execute=false`; se ejecuta cuando pase a verdadero, no ahora.

**Por qué no es una promoción nueva:** ya está dentro de un pre-registro. Lo correcto es **ejecutarlo**, no crear otro lock ni cambiar sus umbrales.

### 3.5 Ideas descartadas explícitamente

| Idea | Evidencia | Por qué se descarta | Test que la reabriría |
|---|---|---|---|
| **P2 + BE 1R** | 46 ops, +2.036,52, PF 1,48, DD 1.794,46; vs viva +13,58 y −1.097,20 DD; vs P2 **−435,26** y −510,00 DD [S5, §4.4] | Es una mejora de **riesgo**, no de rentabilidad: pierde neto frente a P2 y el motor BE es experimental, no de producción | El brazo T del lock M/C/T [S7], solo si C pasa PM5; no es un rescate de C |
| **P1 / 5 contratos** | 46 ops, +1.992,26, PF 1,37, DD 1.947,82; vs viva **−30,68** y −943,84 DD [S1] | Reduce riesgo, pero **no sube neto**; no es una mejora de rentabilidad | El forward original vs P1, separado; no se propone aquí |
| **Replay 8× → 1×** | W1 con 8× y 1×: Δ neto **0,00**; secuencia idéntica [S1, S5] | Es una palanca operativa; no cambia el edge | Ya está refutada como mejora económica; no requiere más test |
| **Subir `max_contracts` por encima de 10** | P2 5→10: +479,52 de neto y **+356,64 de DD** [S1]; no hay brazo >10 | Es apalancamiento, no edge; el DD ya es el punto débil (+923,84 vs original). No hay evidencia de que >10 mejore la rentabilidad ajustada por riesgo | Un lock nuevo con `max_contracts > 10`, mismo stop/filtro y un DD cap; hoy no existe |
| **Umbral 0,20 / 0,30 sobre la viva SL300** | En P2/SL200: 0,20 → 3.166,22; 0,25 → 4.202,20; 0,30 → 3.701,40 [S1]; no hay datos sobre SL300 | La sensibilidad es de **P2/SL200**, no de la viva; elegir otro umbral ahora sería post hoc y añadiría otra dimensión de sobreajuste | Un lock nuevo, un solo umbral congelado; primero debe pasar el 0,25 |
| **Filtros de calendario / día / noticias** | No hay artefacto W1–W6 que los pruebe | No hay evidencia numérica; añadirlos sería otra hipótesis post hoc | Un pre-registro nuevo con hipótesis y muestra separadas; no ahora |
| **Activar `live_enabled`** | El forward no se ha ejecutado; 0 sesiones; holdout sellado; `keep_current` [S10] | No hay validación forward, ni costes exactos, ni P6 | Un forward validado, costes exactos y aprobación explícita; hoy no se cumple |
| **Cambiar `tp_rr` o `risk_per_trade_pct`** | No hay brazo W1–W6 que los varíe | No hay evidencia; cambiar dos parámetros a la vez rompería la atribución | Un lock nuevo con un solo parámetro; no ahora |
| **Volver a la original** | 38 ops, +661,44, PF 1,13, DD 1.967,82 [S1] | Tiene menos DD, pero también **mucho menos neto**; no es una mejora de rentabilidad | Solo si se prioriza DD estricto sobre neto; no es esta misión |

### 3.6 Lo que no se cambia en el 8765

- Se mantiene `max_contracts=10`, `max_sl_ticks=300`, `setup_validity=210`, `retest=24`, `replay=8×`, `min_stop_or_ratio=0,00`.
- No se activa `live_enabled`.
- No se toca el holdout.
- No se reinicia el proceso.
- No se escribe en ninguna DB.

## 4. Recomendación final

### 4.1 No cambiar el 8765 hoy

La configuración viva se queda como está. Razones:

1. La ventaja vs la original es **in-sample** y no estadísticamente distinguible (IC 95 % incluye cero).
2. El DD es peor (+923,84 USD) y el stop 300 es un lastre demostrado (−448,84 USD, +587,20 DD).
3. No hay forward ejecutado; el holdout sigue sellado; `live_enabled=false`.
4. El único candidato nuevo con muestra utilizable (viva + filtro) todavía necesita un pre-registro y un forward, no un cambio de producción.

### 4.2 Promover a pre-registro: `H-LIVE-FILTER-STOP-OR-025`

Es la **primera y única propuesta nueva** que merece promoverse. No se adopta: se pre-registra.

| Elemento | Definición |
|---|---|
| Hipótesis | Añadir `min_stop_or_ratio=0,25` a la viva SL300 mejora el neto y reduce el DD, sin cambiar stop, sizing, frecuencia ni feed |
| Control C | Viva `10/300/210/24`, `min_stop_or_ratio=0,00`, `replay 8×` |
| Tratamiento T | Idéntico, solo `min_stop_or_ratio=0,25` |
| Diseño | One-shot, sin mirada intermedia, ventana prospectiva congelada, mismo feed y modelo de fills, holdout sellado |
| Δ neto mínimo | **≥ +500 USD** |
| Significancia | **IC 95 % del Δ neto > 0** (bootstrap de bloques) |
| PF | **PF_T ≥ 1,30** |
| DD | **DD_T ≤ 2.500 USD y ≤ DD_C** |
| Muestra | **≥ 30 operaciones T** |
| Consistencia | **Δ neto > 0 en ≥ 3/6 bloques**; si un bloque concentra >80 %, no robusto |
| Costes | **Cost stress 1,24/lado + 2 ticks: Δ neto > 0**; sin reprecio, no se promueve |
| Si falla | **`KEEP_LIVE`**; no se cambian umbral, ventana ni métrica |

**Antes de mirar el holdout:** estos criterios deben estar escritos y hasheados en el lock, con la ventana y el tamaño de muestra fijados. El holdout H1 no se usa para esta decisión; el forward es la muestra prospectiva. Si el lock no puede repreciar costes, no se promueve.

### 4.3 Ejecutar, no re-promover: M-SL200 dentro del lock M/C/T

La segunda propuesta que “merece” avanzar no es un lock nuevo: es **ejecutar el brazo C (M-SL200)** del lock M/C/T ya existente [S7], cuando `can_execute` pase a verdadero. Sus criterios ya están congelados:

- **PM5:** `DD_C ≤ DD_M` y `DD_C ≤ 2.000`.
- **K2:** `net_C ≥ 0,70 × net_M`, `DD_C ≤ 1,25 × DD_M`, `DD_C ≤ 2.500`.
- **K5:** `net_C > 0`, `PF_C ≥ 1,00`, `expectancy_r_C ≥ 0`.
- Si C falla PM5 o K2/K5: **`KEEP_M`**; T no rescata a C.

No se cambia el umbral, no se añade otro brazo y no se usa el resultado histórico para declararlo ganador. El PM5 histórico ya falla (DD 2.304,46 > 2.000); por eso necesita el forward, no una promoción directa.

### 4.4 Lo que no se promueve

- **P2 + filtro 0,25:** 17 operaciones, gates `INCONCLUSO`, P6 `NO_EVALUABLE`, concentración top-2 85,28 %. No se promueve. Solo se reabriría con un lock nuevo, P6 exacto y muestra/cobertura suficientes.
- **P2 + BE 1R:** no sube el neto frente a P2 (−435,26); es una mejora de riesgo con motor experimental. No se promueve por rentabilidad.
- **P1 / 5 contratos:** −30,68 USD frente a la viva; es una reducción de riesgo, no una mejora de rentabilidad.
- **Replay 1×:** 0,00 USD de efecto; es operativo.
- **Más de 10 contratos:** no hay evidencia; el DD ya es el problema.
- **Umbrales 0,20/0,30, filtros de calendario, cambios de TP/riesgo:** no hay artefacto que los soporte; serían post hoc.

### 4.5 Decisión final en una frase

**Mantener la viva en paper sin cambios, pre-registrar solo el filtro 0,25 sobre SL300 con los umbrales de §4.2, ejecutar M-SL200 en el forward M/C/T ya existente y no promover ninguna otra variante hasta que haya evidencia prospectiva; el resultado histórico de +1.361,50 USD no es una autorización para cambiar el bot.**

## 5. Verificación de integridad del cierre

### 5.1 Hashes y mtime: antes / después

| Archivo | SHA-256 (antes = después) | mtime (antes = después) | Estado |
|---|---|---|---|
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | 2026-11-22 20:36:50.479925700 −0600 | **Sin cambios** |
| `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | 2026-11-23 19:59:39.851830200 −0600 | **Sin cambios** |
| `data/bars.csv` | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` | 2026-11-19 21:21:09.945922600 −0600 | **Sin cambios** |
| `data/yedbot.db` | `af5bce151fcace45367afa2351ebed9cf89c2fd0ddf75d3439d0f9d7a2a7fd7d` | 2026-11-23 19:53:07.418193100 −0600 | **Sin cambios** |
| `profiles/live_8765/yedbot.db` | `d99f115d3169f09bdaef1952420da1d1b05e8dd3e283af05c9311dcbbd801fce` | 2026-11-24 03:27:55.165943800 −0600 | **Sin cambios** |

Los cinco archivos protegidos tienen el mismo SHA-256 y el mismo mtime antes y después del cierre. La comprobación se ejecutó después de escribir el cuerpo del informe; el informe no toca esos archivos. El propio `reports/backtest/MANUAL_8765_PROFITABILITY_CLOSURE.md` no es un archivo protegido y su hash cambia al editarse.

### 5.2 Holdout

- `reports/backtest/live_vs_original_mission.json`: `scope.holdout_used=false`; `constraints.holdout_accessed=false`.
- `reports/backtest/_live_filter025_w1_w6.json`: `scope.holdout_used=false`; `constraints.holdout_accessed=false`.
- `reports/backtest/forward_validation.json`: holdout H1 `sealed_not_executed`, `executed=false`, `used_for_decision=false`; `status=insufficient_data`; decisión `keep_current`.
- No se leyó ni se ejecutó el holdout en este cierre.

### 5.3 Servicio 8765

- `/api/health`: **200**.
- PID: **15108**, mismo que al inicio de la lectura.
- `/api/status`: `mode=paper`, `status=stopped`; `/api/config.settings.live.live_enabled=false`.
- `/api/config.settings`: `10/300/210/24`, `min_stop_or_ratio=0,00`; coincide con el hash `9bf4…`.
- PID 15108, `StartTime=2026-11-23T20:12:49-06:00`.
- No se reinició, no se envió ninguna orden de arranque/parada y no se modificó la configuración cargada.

### 5.4 Qué no se hizo

- No se ejecutó ningún backtest nuevo; se reutilizaron los artefactos W1–W6.
- No se modificó `data/config.json`, `profiles/live_8765/config.json` ni `data/bars.csv`.
- No se escribió en `data/yedbot.db` ni en `profiles/live_8765/yedbot.db`.
- No se accedió al holdout.
- No se reinició ni se alteró el 8765.
- No se activó `live_enabled`.

### 5.5 Limitaciones

- La comparación viva/original es in-sample y no pareada; la intersección de señales muestra que la viva pierde en las señales comunes.
- El bootstrap tiene solo 6 bloques; el IC es ancho y el p=0,6544 no permite concluir superioridad.
- El filtro viva+SL300 es exploratorio y tiene confusor de sizing; el P2+filter tiene 17 ops y gates INCONCLUSO.
- El cost stress exacto del filtro viva+SL300 no está ejecutado; es una precondición del lock, no un resultado.
- La lectura del 8765 es de un proceso vivo con motor `stopped`; no es una muestra forward.
- Los stats de runtime (`2.269,38 / PF 1,23 / DD 3.099,36`) no coinciden con el artefacto W1–W6 (`2.022,94 / PF 1,22 / DD 2.891,66`) y no se usan para el veredicto; son otra lectura de ejecución.

## 6. Fuentes y trazabilidad

| Ref. | Artefacto | SHA-256 | Uso |
|---|---|---|---|
| [S1] | `reports/backtest/live_vs_original_mission.json` | `9fcc2d0fb1cb0b8c0d5b5bce62ec227b3d416d79819cfa0cffd9d58b8e9104e3` | Viva vs original, agregados, atribución, significancia, config_diff |
| [S2] | `reports/backtest/_live_filter025_w1_w6.json` | `adfa79a965b0f4345ac6a09d9faab630ab802756297b5b98e2ea2ce0b34d4cc6` | Viva SL300 + filtro 0,25; cohorte rechazado; ventanas |
| [S3] | `reports/backtest/_manual_filter025_w1_w6.json` | `193a2bc1ab9885eb55ee988ca082cf51ed2975ca15f6c1421605d379c723aca7` | P2/SL200 + filtro 0,25; 17 ops |
| [S4] | `reports/backtest/filter025_gates.json` | `66cf5ce0dabf1ab0b646a6809f8adee4c991d1f5e4f7211f79cdea0e07f6ee5b` | Gates del filtro P2: INCONCLUSO, P6 NO_EVALUABLE |
| [S5] | `reports/backtest/DECISION_CONFIG_MANUAL_8765_VS_ORIGINAL.md` | `6d4c94076783dbdb15a0847832055a7fda23c35b0e69b1a2a504e4751e4a832b` | Contexto, ranking previo, PM5, concentración, verificación |
| [S6] | `docs/MANUAL_8765_DECISION_MEMO.md` | `82e88e172b9e1e27da0cc27a41f599228c1bb922b5cb635926243a82167318ac` | Memo de decisión, gates M/C/T y fuentes |
| [S7] | `docs/p2_be_1r_forward.lock.json` | `ad72a200943febc2382e40372d199b8a7fda2d78fa67818e96c27be779735dd5` | Lock M/C/T; PM5, K2, K5; `can_execute=false` |
| [S8] | `docs/p2_filtro_stop_or_forward.lock.json` | `d1a2c87b1a855d2040347dbc513711302fd3a4d667ffeb24ca4ae4861719fb01` | Lock `H-P2-FILTER-STOP-OR-025` |
| [S9] | `reports/backtest/MANUAL_8765_LIVE_VS_ORIGINAL.md` | `92abe7748184531b314931f98d9ff88c134c94bad716007119f9a7483e28090b` | Narrativa viva vs original |
| [S10] | `reports/backtest/forward_validation.json` | `4cdd6e2333f2a5423b7abe516c3b4ed8caa6790402d09a9987758de3ab383b32` | Forward `insufficient_data`; holdout sellado; `keep_current` |
| [S11] | `profiles/backtest_real/config.json` | `8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f` | Archivo de la original; contiene 210/24, el brazo efectivo aplica 150/12 |
| [S12] | `data/config.json` / `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | Config viva efectiva |
| [S13] | `data/bars.csv` | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` | Dataset W1–W6 |

**Regla de lectura:** todas las cifras de rentabilidad de este informe son in-sample W1–W6 y proceden de [S1]–[S3]. Ninguna es forward. La única lectura de producción es la de configuración/servicio del §1; no se usa para P&L.
