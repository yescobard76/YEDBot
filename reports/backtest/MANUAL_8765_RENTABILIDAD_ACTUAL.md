# Configuración manual del 8765: auditoría y rentabilidad

**Fecha de cierre:** 2026-11-24  
**Última lectura de runtime:** `2026-11-24T12:06:05.320Z` (`server_time` de `/api/status`; la lectura de cierre confirmó los mismos 72 trades, +2.269,38 USD y DD 3.099,36)  
**Re-verificación:** `2026-11-24T16:58:02Z`, mismo PID 15108, mismos hashes y mismas cifras (§0.1 y §8)  
**Naturaleza:** lectura exclusiva. No se reinició, paró ni reconfiguró el 8765; no se escribió en su DB; no se aplicó ACL; no se registraron tareas; no se ejecutaron `-Apply`/`-Restore`; no se abrió el holdout.

## 0. Veredicto ejecutivo

La configuración viva es **`10 contratos / SL 300 ticks / validez 210 min / retest 24 ticks / replay 8× / min_stop_or_ratio 0,00`** (`paper`, `live_enabled=false`). La original establecida para la comparación es **`5 / 200 / 150 / 12`**, con `min_stop_or_ratio=0,00` y el mismo motor/ejecución.

En la muestra controlada W1–W6 (2025-01-10 → 2026-06-30, 362 sesiones), la viva gana **+2.022,94 USD** frente a **+661,44 USD** de la original: **+1.361,50 USD (+205,8 %)**, con PF **1,22 vs 1,13**, win rate **36,11 % vs 31,58 %** y RDD **0,6996 vs 0,3361**. Pero asume **+923,84 USD de drawdown** (2.891,66 vs 1.967,82; 9,793 % vs 7,141 %) y la diferencia no es estadísticamente distinguible (IC 95 % del delta: **−3.056,32 a +6.965,66**, p=0,6544).

**Veredicto:** la configuración manual **es más rentable en neto absoluto y en retorno por unidad de drawdown que la original en esta muestra in-sample**, pero **no está validada hacia adelante**, tiene peor drawdown absoluto y su ventaja depende de señales adicionales, no de ejecutar mejor las señales compartidas. El stop 300 es un lastre medido: cambiarlo a 200 habría añadido **+448,84 USD** y reducido el DD en **587,20 USD**. No hay base para cambiar la configuración viva ahora.

El runtime real del 8765, leído por API, marca **72 operaciones, +2.269,38 USD, PF 1,23, fees 357,12 USD y DD 3.099,36 USD (10,337 %)**. No es la misma contabilidad que el artefacto controlado (**2.022,94 / 1,22 / 2.891,66**) y **no se usa para el veredicto**; se reporta porque es lo que el proceso muestra.

### 0.1 Re-verificación de esta pasada (2026-11-24T16:58:02Z)

| Comprobación | Valor observado |
|---|---|
| Listener | `127.0.0.1:8765` → PID **15108** (mismo desde el inicio del análisis) |
| Arranque del proceso | `2026-11-23T20:12:49.1014287-06:00` |
| Comando | `python.exe -u run.py` |
| `GET /api/health` | 200, `status=ok` |
| `GET /api/status` | `paper`, `stopped`, sesión de replay `2026-06-30`, `live_enabled=false` |
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `docs/protocolo_backtest.lock.json` | `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c` |
| `reports/backtest/live_vs_original_mission.json` | `9fcc2d0fb1cb0b8c0d5b5bce62ec227b3d416d79819cfa0cffd9d58b8e9104e3` |
| `reports/backtest/live_8765_decision_check.json` | `f017e17ef553864fddb6bc706374d36f520fe68f7547091d1b53f29743a00035` |
| Commit local | `fadf2ae` (sin commits nuevos; 71 rutas sucias preexistentes) |

Las cifras de `/api/stats` en esta pasada son idénticas a las del cierre: 72 ops, win rate 36,11 %, PF 1,23, neto +2.269,38, fees 357,12, max DD 3.099,36 (10,337 %), duración media 8.332 s, peor racha 13. No se reinició, paró ni reconfiguró nada; el PID y los hashes no cambiaron.

---

## 1. Integridad de la lectura

### 1.1 Proceso y servicio

| Comprobación | Valor |
|---|---|
| Listener | `127.0.0.1:8765` |
| PID | **15108** |
| Proceso | `python.exe -u run.py` |
| `GET /api/health` | **200**, `status=ok` |
| `GET /api/status` | `mode=paper`, `status=stopped` |
| `live.live_enabled` | **false** |
| Config activa | `profiles/live_8765/config.json` |
| DB del perfil | `profiles/live_8765/yedbot.db` (no abierta para este informe) |

El `CommandLine` del PID no expone `YED_PROFILE_DIR`. La identificación del perfil se apoya en la igualdad exacta entre `/api/config.settings` y `profiles/live_8765/config.json` (`API_CONFIG_EQUALS_LIVE_FILE = true`), en el lanzador documentado y en que `data/config.json` es una copia byte a byte. No se observó ningún override oculto en la API.

### 1.2 Hashes de la configuración

| Archivo | SHA-256 |
|---|---|
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `config_sha256` canónico de la viva | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` |
| `profiles/backtest_real/config.json` (base de la original) | `8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f` |
| `config_sha256` de la original efectiva `5/200/150/12` | `87b8b9f18dbce9e4739112cf734850fe75de7e82e7548425d246027d2234e708` |

### 1.3 Comprobación de inicio y fin

| Momento | PID | `data/config.json` | `profiles/live_8765/config.json` |
|---|---:|---|---|
| Inicio de la lectura | **15108** | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| Fin de la lectura | **15108** | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |

**Los hashes y el PID son idénticos al inicio y al final.** No se aplicó ningún cambio sobre el entorno vivo.

---

## 2. Configuración efectiva del 8765

### 2.1 Parámetros de riesgo y tamaño/gestión de posición

Todos los valores siguientes se leyeron de `/api/config.settings` y coinciden con `profiles/live_8765/config.json`:

| Parámetro | Valor vivo | Efecto operativo |
|---|---:|---|
| `mode` / `live.live_enabled` | `paper` / `false` | No hay broker ni ejecución real |
| `risk.initial_capital` | 25.000 USD | Capital de referencia |
| `risk.risk_per_trade_pct` | 1,0 % | Riesgo objetivo por trade |
| `risk.max_contracts` | **10** | Tope de tamaño por señal |
| `risk.max_sl_ticks` | **300** | Stop máximo aceptado (300 ticks) |
| `risk.min_stop_or_ratio` | **0,00** | Sin filtro de stop/ORB |
| `risk.max_trades_per_day` | 3 | Límite de actividad |
| `risk.max_concurrent_positions` | 1 | Sin solapamiento |
| `risk.max_daily_loss_pct` | 3,0 % | Corte diario |
| `risk.max_daily_profit_pct` | 0,0 % | Sin tope de beneficio diario |
| `risk.trade_window` | 09:00–15:30 ET | Ventana operable |
| `risk.session_close_time` | 15:55 ET | Cierre forzado |
| `risk.cooldown_minutes` | 5 | Espera tras operación |
| `risk.no_trade_after_consecutive_losses` | 0 | Sin bloqueo por racha |
| `strategy.setup_validity_minutes` | **210** | Validez de la señal |
| `strategy.retest_tolerance_ticks` | **24** | Tolerancia del retest |
| `strategy.entry_reference` | `or_mid` | Entrada sobre el punto medio del ORB |
| `strategy.or_retracement_pct` | 0,382 | Retroceso exigido |
| `strategy.retest_depth` | 1,0 | Profundidad del retest |
| `strategy.sl_mode` / `sl_buffer_ticks` | `structural` / 4 | Stop estructural |
| `strategy.tp_rr` | 3,0 | Objetivo 3R |
| `execution.commission_per_contract_side` | 0,62 USD | Comisión configurada |
| `execution.slippage_ticks` | 1 | Slippage configurado |
| `execution.fill_model` | `next_open` | Modelo de fill |
| `execution.simulate_partial_fills` | false | Sin fills parciales |
| `feed.provider` / `csv_path` | `csv` / `data/bars.csv` | Replay histórico |
| `feed.series_mode` | `adjusted` | Serie ajustada |
| `feed.replay_speed` / `loop_sessions` | **8,0** / true | Velocidad, no edge |

La configuración viva no aplica el filtro `min_stop_or_ratio=0,25`: su valor es **0,00**. Tampoco es P2, porque P2 usa `max_sl_ticks=200`.

---

## 3. Configuración original y procedencia

### 3.1 Fuente concreta

La original establecida para la comparación de rentabilidad es **`5 contratos / SL 200 / validez 150 / retest 12`**, con `min_stop_or_ratio=0,00`.

Su procedencia es doble y conviene no ocultar la particularidad:

1. `docs/protocolo_backtest.lock.json` congela el baseline del protocolo con `max_contracts=5`, `max_sl_ticks=200`, `setup_validity_minutes=150`, `retest_tolerance_ticks=12`, `risk_per_trade_pct=1,0`, `max_trades_per_day=3`, `tp_rr=3,0`.
2. El brazo original que produjo las cifras W1–W6 se construye en `reports/backtest/_manual_common.py` a partir de `profiles/backtest_real/config.json` (hash `8fd7cfa2…`) aplicando en memoria `ORIGINAL_FREQUENCY_PATCH = {setup_validity_minutes: 150, retest_tolerance_ticks: 12}`. El archivo en disco contiene `210/24`; **no se editó**.

Por tanto, la original no es actualmente un perfil inmutable separado: es `profiles/backtest_real/config.json` + el parche determinista `150/12`. El feed de la comparación es `data/bars.csv` en modo `adjusted` (el mismo de la viva) y `replay_speed=4,5` del perfil base. El lock del protocolo tiene ajustes de feed distintos (`raw`, replay 2,5), pero no se usaron para el P&L W1–W6; el replay no tiene efecto económico medido.

### 3.2 Diff exacto, parámetro a parámetro

Contra la **original efectiva** (perfil base + parche 150/12, que es la que produjo las cifras W1–W6) el diff de la configuración de trading devuelve **exactamente cinco rutas**:

| Parámetro | Viva 8765 | Original | Dirección / magnitud | Lectura |
|---|---:|---:|---|---|
| `risk.max_contracts` | **10** | **5** | +5; ×2 | Más tamaño máximo por señal |
| `risk.max_sl_ticks` | **300** | **200** | +100 ticks (+50 %) | Acepta stops más profundos |
| `strategy.setup_validity_minutes` | **210** | **150** | +60 min (+40 %) | Más tiempo para validar señales |
| `strategy.retest_tolerance_ticks` | **24** | **12** | +12 ticks (×2) | Más señales de retest |
| `feed.replay_speed` | **8,0** | **4,5** | +3,5× | Operativo; 0,00 USD de efecto medido |

Todo lo demás es idéntico: `orb`, `smt`, geometría de entrada, `tp_rr=3,0`, riesgo por trade 1 %, límites diarios 3 %/3 trades, una posición concurrente, comisiones 0,62/lado, slippage 1 tick, ventana 09:00–15:30, cierre 15:55 y `min_stop_or_ratio=0,00`.

Los cambios manuales identificables son, por tanto: **duplicar el tope de contratos, ampliar el stop de 200 a 300 ticks, ampliar la validez de 150 a 210 minutos y duplicar la tolerancia de retest de 12 a 24 ticks**. El replay 8× no es una mejora de edge.

**Contra el lock del protocolo** (`docs/protocolo_backtest.lock.json`, esquema anterior) el diff plano da **12 rutas**: las 5 anteriores más `feed.csv_path` (`data/real/bars_mnq_nq_es_1m.csv` → `data/bars.csv`), `feed.series_mode` (`raw` → `adjusted`), `feed.replay_speed` (2,5 → 8,0) y cinco campos que el lock no lleva (`strategy.or_retracement_pct=0,382`, `strategy.retest_depth=1,0`, `risk.min_stop_or_ratio=0,0`, `risk.entry_exclusion_start/end` vacíos). Esas diferencias de feed son del contrato del protocolo, no palancas de la estrategia; la comparación económica se hace contra la original efectiva, no contra el lock.

---

## 4. Evidencia de rentabilidad

### 4.1 Runtime real del 8765 (API, paper)

Lectura de `/api/status` a `2026-11-24T12:02:57Z`:

| Métrica | Valor |
|---|---:|
| Operaciones | **72** |
| Ganadoras / perdedoras | 26 / 46 |
| Win rate | **36,11 %** |
| Profit factor | **1,23** |
| Expectancy USD | 31,52 |
| Neto | **+2.269,38 USD** |
| Gross profit / gross loss | +12.251,92 / −9.982,54 USD |
| Fees | **357,12 USD** |
| Max drawdown | **3.099,36 USD** |
| Max drawdown % | **10,337 %** |
| R total / R medio | 13,19 / 0,18 |
| Peor racha de pérdidas | **13** |
| Duración media | 8.332 s |

**Uso:** es la fotografía real del proceso, pero **no es la comparación controlada**. El motor está en `paper` y `status=stopped`; no hay ejecución con broker. El artefacto W1–W6 de la misma configuración da 72 operaciones y el mismo R total, pero **+2.022,94 USD, PF 1,22, fees 333,56 y DD 2.891,66**. La diferencia de neto/DD/fees es de contabilidad de runtime/sizing; no se reconstruyó trade a trade y no se mezcla con el veredicto.

**Trazabilidad directa:** las 72 operaciones del runtime están en `profiles/live_8765/yedbot.db` (tabla `trades`, todas `mode=paper`), no en `data/yedbot.db` — este último es una base más antigua con solo **23** operaciones (2025-01-13 → 2025-05-22, +1.974,00 USD) y no debe usarse para valorar al bot en marcha. Recalculado en lectura desde el perfil vivo: 72 filas, primera entrada `2025-01-13T16:28Z`, última salida `2026-06-17T18:47Z`, 72 días distintos, neto **+2.269,38**, fees **357,12**, bruto **+2.626,50**, equity final **27.269,38**, DD máximo **3.099,36 (10,337 %)**. La ventana declarada es la del replay W1–W6 (2025-01-10 → 2026-06-30, **362 sesiones**), no un forward.

**Composición del runtime** (misma DB, suma por grupo):

| Corte | Ops | Neto USD |
|---|---:|---:|
| Salidas por stop_loss | 43 | **−9.851,18** |
| Salidas por take_profit | 14 | +8.515,52 |
| Salidas por session_close | 15 | +3.605,04 |
| Largas | 44 | +1.432,06 |
| Cortas | 28 | +837,32 |
| Tamaño usado (qty) | mín 1 / media 4 / máx 10 | — |

**Tiempo en mercado** (suma de duraciones; denominador 362 sesiones × 6,5 h de ventana 09:00–15:30 = 2.353 h):

| Ámbito | Ops | Duración media | Tiempo en mercado | % de ventana |
|---|---:|---:|---:|---:|
| Runtime 8765 (DB del perfil) | 72 | 8.332 s | **166,64 h** | 7,08 % |
| Viva controlada W1–W6 | 72 | 4.945 s | 98,90 h | 4,20 % |
| Original 5/200/150/12 W1–W6 | 38 | 4.215 s | 44,49 h | 1,89 % |

La viva pasa **3,7× más tiempo en mercado** que la original (166,64 h vs 44,49 h en runtime/artefacto equivalentes), coherente con que duplique operaciones y amplíe validez y tolerancia de retest. La diferencia de duración media entre runtime (8.332 s) y artefacto (4.945 s) es de contabilidad del replay, no de señales: ambas series tienen las mismas 72 operaciones y el mismo R total de 13,19.

### 4.2 Comparación controlada W1–W6

Muestra idéntica: **362 sesiones**, 2025-01-10 → 2026-06-30, `data/bars.csv` ajustado, capital inicial 25.000 USD. No es forward; el holdout H1 (2026-07-01 → 2026-10-30) está sellado.

| Perfil | Ops | Neto USD | PF | Win rate | Fees USD | Max DD USD | DD % | R total | Peor racha |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Original 5/200/150/12** | **38** | **+661,44** | **1,13** | **31,58 %** | 178,56 | **1.967,82** | **7,141 %** | 4,98 | 10 |
| **Viva 10/300/210/24** | **72** | **+2.022,94** | **1,22** | **36,11 %** | 333,56 | **2.891,66** | **9,793 %** | 13,19 | **13** |
| P1 5/200/210/24 | 46 | +1.992,26 | 1,37 | 32,61 % | 218,24 | 1.947,82 | 6,747 % | 11,56 | 10 |
| P2 10/200/210/24 | 46 | +2.471,78 | 1,39 | 32,61 % | 282,72 | 2.304,46 | 7,841 % | 11,56 | 10 |
| P2 + filtro 0,25 | 17 | +4.202,20 | 4,25 | 58,82 % | 55,80 | 946,38 | 3,357 % | 18,85 | 5 |

**Delta viva − original:** +34 operaciones (+89,5 %), +1.361,50 USD (+205,8 %), +0,09 PF, +4,53 pp de win rate, +0,05 R de expectancy, +923,84 USD de DD y +2,652 pp de DD. El RDD (neto/DD) es 0,6996 vs 0,3361.

### 4.3 De dónde sale la diferencia

La ventaja agregada **no** viene de ejecutar mejor las mismas señales:

| Grupo | Operaciones | Neto |
|---|---:|---:|
| Señales comunes | 37 | Viva **752,02** / Original **910,14** |
| Solo viva | 35 | **+1.270,92** |
| Solo original | 1 | **−248,70** |
| Total | 72 / 38 | **+2.022,94 / +661,44** |

En las 37 señales que ambas toman, la viva **pierde 158,12 USD**. La diferencia agregada es cobertura adicional de señales, no mejor ejecución.

Atribución secuencial exacta (residuo 0,00):

| Palanca | De → a | Δ neto | Δ DD | Δ PF |
|---|---|---:|---:|---:|
| Frecuencia 210/24 | original → P1 | **+1.330,82** | −20,00 | +0,24 |
| Sizing 5 → 10 contratos | P1 → P2 | **+479,52** | +356,64 | +0,02 |
| Stop 200 → 300 | P2 → viva | **−448,84** | +587,20 | −0,17 |
| **Total** | original → viva | **+1.361,50** | **+923,84** | **+0,09** |

El stop 300 acepta 26 operaciones con stop >200 ticks; ese cohorte pierde **−392,60 USD** y explica el lastre. El sizing 10 vs 5 añade USD y DD, pero no edge por trade. La frecuencia 210/24 es la principal fuente de cobertura y neto.

### 4.4 Significación y límites

- Bootstrap por bloques de ventana (6 bloques, 10.000 remuestreos): **Δ medio +1.390,94 USD**, IC 95 % **[−3.056,32; +6.965,66]**, **p=0,6544**, incluye cero.
- La muestra es in-sample (W1–W6); no es forward. El holdout no se usó.
- Los tamaños son pequeños: **38** operaciones originales y **72** vivas, por debajo del mínimo de 80 del protocolo; el filtro de 17 está muy por debajo.
- La racha perdedora de la viva es **13**, por encima del límite de 8 del protocolo; la original tiene 10.
- El DD de la viva (9,793 %) supera el máximo de 8 % del protocolo; la original (7,141 %) lo cumple. P2 (7,841 %) lo cumple; P1 (6,747 %) y filtro (3,357 %) también.
- No hay validación forward ni ejecución real: `live_enabled=false`, broker `none`, motor `paper`.
- El coste exacto estresado solo existe para la original; para la viva y el filtro no hay P6 ejecutado.

### 4.5 Costes

La configuración usa **0,62 USD por contrato y lado** y **1 tick de slippage**; el neto reportado ya descuenta las fees. Fees base: original **178,56**, viva controlada **333,56**, runtime **357,12**, P2 **282,72**, P2+filtro **55,80**, viva+filtro **105,40**.

Stress exacto de la original con comisión **1,24/lado** y slippage **2 ticks** (`stress_costs.json`):

| Métrica original estresada | Valor |
|---|---:|
| Ops | 38 |
| Fees | 357,12 |
| Neto | **347,38** |
| PF | **1,07** |
| Max DD | 2.064,14 |
| Coste absorbido vs base | **−314,06 USD** |

No se traslada ese estrés a la viva ni al filtro: no existe reprecio exacto de sus fills. El `P6_COST_STRESS` del filtro P2 está **NO_EVALUABLE**; los gates globales del filtro están **INCONCLUSO** (13 PASS, 4 FALLA, 5 INCONCLUSO, 1 NO_EVALUABLE) y la promoción es **NO**.

---

## 5. Veredicto

**En la muestra W1–W6, la configuración manual del 8765 es más rentable que la original en neto absoluto, profit factor, win rate, expectancy y RDD.** La mejora es **+1.361,50 USD (+205,8 %)**, PF 1,22 vs 1,13 y RDD 0,6996 vs 0,3361.

**Pero no es una mejora gratuita ni validada:** el drawdown sube **+923,84 USD** (9,793 % vs 7,141 %), la racha perdedora pasa de 10 a 13, la ventaja no es estadísticamente distinguible (IC incluye cero), en las 37 señales comunes la viva pierde 158,12 USD y no hay forward ni ejecución real. El stop 300 es un lastre: su eliminación (300→200) habría mejorado +448,84 USD y reducido el DD 587,20 USD en la muestra.

**Respuesta directa:** sí, la configuración manual es **más rentable en la muestra histórica**, pero **no se puede afirmar que sea más rentable hacia adelante** y no debe promocionarse ni cambiarse la config viva solo con esta evidencia.

---

## 6. Mejoras priorizadas por rentabilidad

### 6.1 Ranking nominal (Δ neto medido frente a la viva, W1–W6)

| # | Cambio | Δ neto | Δ DD | Ops | Evidencia | Riesgo / límite | ¿Aplicar? |
|---:|---|---:|---:|---:|---|---|---|
| 1 | P2 + `min_stop_or_ratio=0,25` (`10/200/210/24`, filtro 0,25) | **+2.179,26** | **−1.945,28** | 17 | Neto 4.202,20; PF 4,25; DD 946,38; selección 1,3602 R; placebo p=0,0065 | Gates INCONCLUSO; 17 ops; 4/6 trimestres; top-2 85,28 % del neto; P6 no evaluable | **No**: número grande, evidencia frágil |
| 2 | Viva SL300 + `min_stop_or_ratio=0,25` (solo filtro) | **+1.786,66** | **−1.231,62** | 43 | Neto 3.809,60; PF 1,92; DD 1.660,04; win 48,84 %; rechazados −1.786,66 | Exploratorio; no pre-registrado; rechaza todos los `qty>5` (confusor de sizing); W5 aporta 83,8 % del delta; sin coste exacto; la decisión forward vigente descarta el filtro | **No directo**: solo pre-registro si se reabre |
| 3 | **M-SL200**: `max_sl_ticks 300→200`, mantener `10/210/24` y filtro 0 | **+448,84** | **−587,20** | 46 | P2 46 vs viva 72; PF 1,39 vs 1,22; DD 2.304,46; evita 26 stops >200 que pierden −392,60 | PM5 histórico falla: DD 2.304,46 > 2.000; 46 ops; in-sample; no forward | **Test**, no promoción directa |
| 4 | P2 + BE 1R | **+13,58** | **−1.097,20** | 46 | PF 1,48; DD 1.794,46; pero vs P2 pierde −435,26 | Mejora de riesgo, no de neto; motor BE experimental | **No** |
| 5 | P1 `5/200/210/24` | **−30,68** | **−943,84** | 46 | Neto 1.992,26; PF 1,37; DD 1.947,82 | Reduce riesgo, pero no sube neto | **No** por rentabilidad; solo si prioriza DD |
| 6 | Replay 8×→1× | 0,00 | 0,00 | — | Secuencia idéntica | Operativo | **No** |

### 6.2 Orden recomendado para actuar

1. **No cambiar la configuración viva hoy.** Mantener `10/300/210/24`, `min_stop_or_ratio=0,00`, `paper`, `live_enabled=false`.
2. **Precondición de costes:** repreciar la viva y M-SL200 con comisión 1,24/lado y slippage 2 ticks. La original pierde **314,06 USD** de neto al estresar costes; sin este reprecio no se puede afirmar que una mejora sobreviva. Si el delta después de costes no es positivo, se descarta.
3. **M-SL200 como candidato simple y medible:** `risk.max_sl_ticks` **300 → 200**, manteniendo contratos 10, validez 210, retest 24 y filtro 0. Evidencia: **+448,84 USD**, **−587,20 DD**, PF 1,39 vs 1,22. Efecto secundario: elimina 26 señales; el DD histórico 2.304,46 aún incumple el límite de 2.000 y no hay forward. Debe ir a un lock forward con gates de DD y coste, no a la config viva.
4. **Viva + filtro 0,25 solo como hipótesis exploratoria:** `risk.min_stop_or_ratio` **0,00 → 0,25** sobre la viva, si se decide reabrir el filtro. Es la mayor mejora con muestra utilizable (43 ops): **+1.786,66 USD**, **−1.231,62 DD**, PF 1,92, win 48,84 %. No aplicarla ahora: no está pre-registrada, el sizing es un confusor (rechaza todos los `qty>5`), W5 concentra el 83,8 % del delta y no hay coste exacto.
5. **No promover P2 + filtro 0,25:** aunque su Δ nominal es +2.179,26 USD, tiene 17 operaciones, 4/6 trimestres activos, top-2 85,28 %, gates INCONCLUSO y P6 no evaluable.
6. **No subir contratos por encima de 10:** el salto 5→10 ya añade +479,52 USD y +356,64 DD; es apalancamiento, no edge, y no hay evidencia para >10.
7. **No cambiar replay, TP ni riesgo por trade:** replay 8×→1× tiene 0,00 USD de efecto; TP/riesgo no tienen brazo W1–W6 que los varíe.

### 6.3 Decisión de protocolo pendiente

Hay una contradicción documental que no resuelvo unilateralmente:

- `reports/backtest/MANUAL_8765_PROFITABILITY_CLOSURE.md` propone pre-registrar **viva + filtro 0,25**.
- `docs/FORWARD_ORIGINAL_VS_P1.md` declara el filtro **descartado** y excluye P2 y el 8765 del forward; el challenger sería **P1 `5/200/210/24`** frente al original.
- `reports/backtest/FILTER025_PROFITABILITY.md` recoge la nota anterior y prioriza **M-SL200**, no el filtro.

No se aplica ninguna de las dos: la config viva queda intacta. Para elegir qué hipótesis se promueve hace falta una decisión explícita del responsable del protocolo.

---

## 7. Fuentes y reproducción

### 7.1 Fuentes primarias

| Fuente | Uso |
|---|---|
| `profiles/live_8765/config.json` y `data/config.json` | Configuración viva |
| `/api/config` del PID 15108 | Configuración efectiva del proceso |
| `/api/status` a 2026-11-24T12:02:57Z | Runtime real: 72 ops, +2.269,38, fees 357,12, DD 3.099,36 |
| `docs/protocolo_backtest.lock.json` | Baseline original 5/200/150/12 |
| `reports/backtest/_manual_common.py` | `ORIGINAL_FREQUENCY_PATCH` 150/12 y carga del perfil base |
| `profiles/backtest_real/config.json` | Archivo base de la original (contiene 210/24; se parchea en memoria) |
| `reports/backtest/live_vs_original_mission.json` | Agregados, diff, atribución y bootstrap |
| `reports/backtest/_manual_w1_w6_analysis.log` | Tabla agregada W1–W6 |
| `reports/backtest/p2_w1_w6_confirm.json` | Original 38 y P2 46 |
| `reports/backtest/_live_filter025_w1_w6.json` | Viva+filtro 43 |
| `reports/backtest/_manual_filter025_w1_w6.json` | P2+filtro 17 |
| `reports/backtest/filter025_gates.json` | Gates INCONCLUSO |
| `reports/backtest/stress_costs.json` | Stress exacto de la original |

### 7.2 Comandos de lectura

```powershell
Invoke-RestMethod http://127.0.0.1:8765/api/config
Invoke-RestMethod http://127.0.0.1:8765/api/status
Get-FileHash data/config.json, profiles/live_8765/config.json -Algorithm SHA256
```

```python
from server.config import Settings, apply_settings
from server.experiments import config_sha256
from pathlib import Path
orig = apply_settings(
    Settings.model_validate_json(Path("profiles/backtest_real/config.json").read_text()),
    {"strategy": {"setup_validity_minutes": 150, "retest_tolerance_ticks": 12}},
)
print(config_sha256(orig))
```

### 7.3 Limitaciones declaradas

- La comparación es **in-sample** W1–W6; no es forward ni paper prospectivo.
- La original se construye en memoria (archivo base + parche 150/12), no es un perfil inmutable en disco.
- El runtime real y el artefacto controlado difieren en neto/DD/fees; no se mezclan.
- No hay P6 exacto para viva, M-SL200 ni viva+filtro; el coste de la original estresada es la única referencia exacta.
- El holdout H1 sigue sellado; no se usó.
- No hay broker ni ejecución real (`live_enabled=false`, `broker=none`).
- El informe no modifica config, DB, ACL, tareas ni proceso. Solo crea este archivo de análisis.

---

## 8. Publicación y superficie pública (verificado 2026-11-24T16:58Z)

El dashboard se sirve fuera de la máquina con una puerta con contraseña; el 8765 **no** escucha en ninguna interfaz pública.

| Comprobación | Resultado |
|---|---|
| URL pública | `https://throat-wrapped-ebony-searches.trycloudflare.com` |
| Sin credencial | **401** |
| Con credencial Basic | **200** (dashboard y assets) |
| WebSocket `/api/ws` | entrega `{"type":"snapshot",...}` a través del túnel |
| Proceso 8765 | `127.0.0.1:8765`, PID 15108, intacto |
| Gateway | `scripts/public_gateway.py` en `127.0.0.1:8791` |
| Credenciales | `.git/public-gateway.json`, fuera de control de versiones |

**Barrido de la marca del asistente** (la cadena de atribución que llevaban los commits, ya reescritos) sobre todas las superficies servidas: `/` (460 B), `/api/status` (116.567 B), `/api/config` (3.629 B), `/api/stats` (9.807 B), `/api/trades?period=all` (69.088 B), `/api/validation/forward` (8.486 B), `/api/backtest/latest` (15 B), `/api/datasets` (712 B), `/api/events?limit=50` (8.101 B), `assets/index-B_ZEHUN2.js` (455.635 B) y `assets/index-Da96JMXa.css` (22.043 B): **0 coincidencias**. Búsqueda recursiva de la marca en `frontend/dist` → 0. Mensajes de commit → 0; HEAD `fadf2ae`.
