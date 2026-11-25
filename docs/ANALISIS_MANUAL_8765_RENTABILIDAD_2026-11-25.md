# Configuración manual del 8765: rentabilidad frente a la original y mejoras priorizadas

**Fecha:** 2026-11-25  
**Objeto:** configuración manual del bot en el puerto 8765 y comparación con la original establecida `5/200/150/12`.  
**Naturaleza:** análisis read-only sobre configuración y artefactos ya generados. No se arrancó, paró, reinició ni reconfiguró el 8765; no se escribió en su DB; no se abrió el holdout.  
**Estado actual del 8765:** **sin listener** en `127.0.0.1:8765` y sin proceso con PID `15108`. La configuración descrita es la última vigente en disco y la que aplicó la última instancia conocida; no es una lectura de un proceso vivo en este momento.

---

## 0. Resumen ejecutivo

- La configuración manual efectiva es **MNQ, `10 contratos / SL 300 ticks / validez 210 min / retest 24 ticks / filtro stop-ORB 0,00`**, en `paper`, con `live_enabled=false`.
- En la muestra W1–W6 (2025-01-10 → 2026-06-30, 362 sesiones, 25.000 USD iniciales), la manual hace **+2.022,94 USD** frente a **+661,44 USD** de la original: **+1.361,50 USD (+205,8 %)**, con PF **1,22 vs 1,13**, expectancy **28,10 vs 17,41 USD/op** y win rate **36,11 % vs 31,58 %**.
- La manual también tiene peor riesgo absoluto: **DD 2.891,66 vs 1.967,82 USD** (**+923,84 USD, +46,9 %**) y peor racha de pérdidas (**13 vs 10**). Su RDD (neto/DD) es mejor: **0,6996 vs 0,3361**.
- La ventaja **no viene de ejecutar mejor las mismas señales**: en las 37 señales comunes la manual hace **752,02 USD** y la original **910,14 USD**; la manual pierde **−158,12 USD** en lo compartido. La diferencia agregada procede de **35 señales que solo toma la manual (+1.270,92 USD)** y de **1 señal que solo toma la original (−248,70 USD)**.
- La diferencia **no es estadísticamente distinguible** con esta muestra: bootstrap por 6 bloques, 10.000 remuestreos, media **+1.390,94 USD**, IC 95 % **[-3.056,32; +6.965,66]**, `p=0,6544`, intervalo que incluye cero.
- **Veredicto:** la manual es más rentable en **neto histórico absoluto** y en **RDD**, pero asume más drawdown, no domina en las señales compartidas y no tiene validación forward. La confianza en la aritmética de la muestra es alta; la confianza en que la ventaja persista es **baja**.
- **No cambiar el 8765 hoy.** La única mejora con muestra utilizable es añadir `min_stop_or_ratio=0,25` a la manual (**+1.786,66 USD, −1.231,62 USD de DD, 43 ops**), pero es exploratoria, tiene confusor de sizing y, aunque ya tiene reprecio de coste 1x/2x (3.630,20 a 2x), **no supera el bootstrap del delta en ninguno de los dos regímenes** (p 0,3134 → 0,2238): debe ir a un lock forward nuevo, no a producción.
- La segunda mejora directa es **M-SL200** (`max_sl_ticks 300→200`): **+448,84 USD y −587,20 USD de DD** frente a la manual, pero es in-sample, no pareada y el PM5 histórico falla por DD > 2.000 USD. Ya tiene un forward pre-registrado; no se re-promociona.

---

## 1. Configuración manual efectiva

### 1.1 Ficheros, hashes y proceso

| Objeto | Valor / SHA-256 | Fuente |
|---|---|---|
| Configuración efectiva | `data/config.json` | Disco; `profiles/live_8765/config.json` es copia byte a byte |
| Hash de archivo | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | `data/config.json` y `profiles/live_8765/config.json` |
| Hash canónico | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` | `live_8765_decision_check.json`; coincide con API y ambos ficheros |
| Dataset | `data/bars.csv`, serie `adjusted` | Hash `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` |
| Última captura de proceso | PID `15108`, `python.exe -u run.py`, inicio `2026-11-23T20:12:49-06:00`, listener `127.0.0.1:8765` | `reports/backtest/live_8765_decision_check.json` (capturada `2026-11-24T06:26:30Z`) |
| Estado de esa captura | `paper`, motor `running`, `live_enabled=false`; API = `data/config.json` = perfil vivo | `live_8765_decision_check.json` |
| Estado actual (2026-11-25) | **sin listener y sin PID 15108** | `netstat -ano`, `tasklist` |
| DB del perfil | `profiles/live_8765/yedbot.db`; la captura la leyó read-only | `live_8765_decision_check.json` |

**Matiz de identidad:** el `CommandLine` del PID no exponía `YED_PROFILE_DIR`. La identificación del perfil se apoya en que la API, `data/config.json` y `profiles/live_8765/config.json` eran idénticos, y en el lanzador registrado (`YED_PROFILE_DIR=profiles/live_8765`). El proceso actual ya no existe; la configuración en disco permanece intacta con el hash `9bf4f9c7…`.

### 1.2 Parámetros, símbolos y timeframes

| Bloque | Valor efectivo |
|---|---|
| Instrumento | `MNQ` |
| Símbolo de referencia | `NQ` (usado por SMT) |
| Símbolo de comparación | `ES` (usado por SMT) |
| Modo | `paper`; `live.live_enabled=false`; broker `none`, entorno `demo` |
| Timezone | `America/New_York` |
| ORB | `09:00–10:00`; `max_width_pct=1,2` |
| Timeframe SMT | `detect_tf=1m`; `window_minutes=60`; `pivot_depth=5` |
| Timeframe de confirmación | `confirm_tf=15m`; `entry_trigger=close` |
| Datos | CSV `data/bars.csv`, 1 minuto, serie `adjusted`; rolls excluidos |
| Replay | `replay_speed=8,0`; `loop_sessions=true`; sin latencia |

### 1.3 Estrategia: entradas, filtros y gestión

| Parámetro | Valor | Efecto |
|---|---:|---|
| `strategy.name` | `YED ORB+SMT` | Estrategia base |
| `strategy.require_close_breakout` | `true` | Exige cierre de ruptura |
| `strategy.breakout_buffer_ticks` | `2` | Buffer de ruptura |
| `strategy.min_range_ticks` | `10` | Rango mínimo |
| `strategy.setup_validity_minutes` | **210** | Validez del setup |
| `strategy.use_smt` | `true` | SMT activo |
| `strategy.allow_reentry_after_false_breakout` | `false` | Sin reentrada tras falso breakout |
| `strategy.entry_reference` | `or_mid` | Entrada en el punto medio del ORB |
| `strategy.or_retracement_pct` | `0,382` | Retroceso exigido |
| `strategy.retest_depth` | `1,0` | Profundidad del retest |
| `strategy.retest_tolerance_ticks` | **24** | Tolerancia del retest |
| `strategy.require_recovery_close` | `true` | Exige cierre de recuperación |
| `strategy.sl_mode` | `structural` | Stop estructural |
| `strategy.sl_buffer_ticks` | `4` | Buffer del stop |
| `strategy.structural_depth` | `3` | Velas del swing estructural |
| `strategy.atr_period` | `14` | ATR |
| `strategy.atr_sl_mult` | `1,2` | Multiplicador ATR del stop |
| `strategy.tp_rr` | **3,0** | Objetivo 3R |
| `smt.enabled` | `true` | SMT activo |
| `smt.pivot_depth` | `5` | Pivotes SMT |
| `smt.window_minutes` | `60` | Ventana SMT |
| `smt.tolerance_ticks` | `8` | Tolerancia SMT |
| `smt.min_break_ticks` | `2` | Ruptura mínima SMT |
| `smt.validity_minutes` | `120` | Validez SMT |
| `smt.require_recovery` | `true` | Recuperación SMT |
| `risk.entry_exclusion_start/end` | vacíos | Sin exclusión horaria de entradas |
| `risk.min_stop_or_ratio` | **0,00** | **No aplica el filtro 0,25** |

### 1.4 Riesgo, sizing y gestión de posición

| Parámetro | Valor |
|---|---:|
| `risk.initial_capital` | 25.000 USD |
| `risk.risk_per_trade_pct` | 1,0 % |
| `risk.max_contracts` | **10** |
| `risk.max_sl_ticks` | **300** |
| `risk.max_daily_loss_pct` | 3,0 % |
| `risk.max_daily_profit_pct` | 0,0 % (sin tope) |
| `risk.max_trades_per_day` | 3 |
| `risk.max_concurrent_positions` | 1 |
| `risk.trade_window_start/end` | 09:00–15:30 ET |
| `risk.session_close_time` | 15:55 ET |
| `risk.close_at_session_end` | `true` |
| `risk.cooldown_minutes` | 5 |
| `risk.no_trade_after_consecutive_losses` | 0 (sin bloqueo por racha) |

**Gestión:** una sola posición concurrente, stop estructural o ATR, target 3R, cierre forzado al final de sesión, sin fills parciales y sin trailing. El tamaño se calcula con el 1 % del equity y se recorta por `max_contracts=10` y por el presupuesto de riesgo; el tope de stop es 300 ticks.

### 1.5 Ejecución y feed

| Parámetro | Valor |
|---|---:|
| `execution.tick_size` | 0,25 |
| `execution.tick_value` | 0,50 USD |
| `execution.point_value` | 2,0 USD |
| `execution.commission_per_contract_side` | 0,62 USD |
| `execution.slippage_ticks` | 1 |
| `execution.max_slippage_ticks` | 4 |
| `execution.fill_model` | `next_open` |
| `execution.simulate_partial_fills` | `false` |
| `execution.partial_fill_ratio` | 0,6 (no usado) |
| `feed.provider` | `csv` |
| `feed.csv_path` | `data/bars.csv` |
| `feed.series_mode` | `adjusted` |
| `feed.exclude_roll_sessions` | `true` |
| `feed.replay_speed` | 8,0 |
| `feed.loop_sessions` | `true` |

**No hay kwargs de un preset aplicado:** el 8765 usa el perfil completo `data/config.json` (copia en `profiles/live_8765/config.json`), no un preset de `DEFAULT_PRESETS`. El perfil P2 `profiles/p2_freq/config.json` es otro perfil y solo difiere de la manual en `max_sl_ticks=200`; el 8765 no lo usa.

---

## 2. Configuración original establecida y diff exacto

### 2.1 Procedencia

La original de la comparación es **`5 contratos / SL 200 / validez 150 / retest 12 / filtro 0,00`**, con el mismo motor y feed `data/bars.csv` ajustado. Su procedencia es importante:

1. `docs/protocolo_backtest.lock.json` congela el baseline `5/200/150/12` (SHA-256 del lock: `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c`).
2. El brazo que produjo las cifras se construye en `reports/backtest/_manual_common.py` a partir de `profiles/backtest_real/config.json` (**hash de archivo `8fd7cfa2…`**, que en disco contiene `210/24`) aplicando en memoria `ORIGINAL_FREQUENCY_PATCH = {setup_validity_minutes: 150, retest_tolerance_ticks: 12}`.
3. El hash canónico de la original efectiva es **`87b8b9f18dbce9e4739112cf734850fe75de7e82e7548425d246027d2234e708`**; el hash de archivo `8fd7…` **no** es el de la frecuencia 150/12.

No existe un fichero separado que materialice la original `150/12`; es perfil base + parche determinista. Cualquier reproducción debe usar `_manual_common.load_original()` o el mismo parche, no solo abrir `profiles/backtest_real/config.json`.

### 2.2 Diff manual vs original

| Parámetro | Manual 8765 | Original | Δ | Comentario |
|---|---:|---:|---:|---|
| `risk.max_contracts` | **10** | **5** | +5 (×2) | Más tamaño por señal |
| `risk.max_sl_ticks` | **300** | **200** | +100 (+50 %) | Acepta stops más profundos |
| `strategy.setup_validity_minutes` | **210** | **150** | +60 (+40 %) | Más tiempo para validar |
| `strategy.retest_tolerance_ticks` | **24** | **12** | +12 (×2) | Más tolerancia de retest |
| `feed.replay_speed` | 8,0 | 4,5 | +3,5 | Operativo; **0,00 USD** de efecto medido |

Todo lo demás es idéntico: ORB, SMT, geometría de entrada, `tp_rr=3,0`, riesgo 1 %, límites diarios, una posición, comisiones 0,62/lado, slippage 1 tick, ventana 09:00–15:30 y cierre 15:55. `min_stop_or_ratio` es **0,00 en ambas**: la manual **no** aplica el filtro 0,25.

---

## 3. Comparación cuantitativa de rentabilidad

### 3.1 Muestra y método

- W1–W6: **362 sesiones**, `2025-01-10` → `2026-06-30`.
- `data/bars.csv`, serie `adjusted`, 1 minuto, capital inicial **25.000 USD**.
- **No** se usó 2024; **no** se usó el holdout H1 (`2026-07-01` → `2026-10-30`, 85 sesiones, sellado).
- La comparación es de **carteras**, no de las mismas operaciones: la manual genera señales que la original no genera. La comparación pareada se hace en la intersección por `signal_id`.
- Es **in-sample**: la misma muestra se usó para construir y comparar las variantes. No es forward.

Fuentes principales:

| Ref. | Artefacto | SHA-256 | Papel |
|---|---|---|---|
| **[S1]** | `reports/backtest/live_vs_original_mission.json` | `40377a5daf096444acdd46c69f3da9c5d57233430625b261aa2caa378f0dab37` | Agregados original/manual/P1/P2, atribución, ventanas, bootstrap |
| **[S2]** | `reports/backtest/forward_validation.json` | `9635136f796f78fbef27eb9b809a0e3821ab8ea65bc24463615c9ea572eca870` | Fichas manual/P2/P2+BE y estado forward |
| **[S2b]** | `reports/backtest/forward_validation.sha256` | `c3c2c8df4e5c73f10e378f23ca1c7a164f15db822f4cf24467d594a74339d0a9` | Sidecar; contiene `9635136f…` y coincide |
| **[S3]** | `reports/backtest/live_8765_decision_check.json` | `f017e17ef553864fddb6bc706374d36f520fe68f7547091d1b53f29743a00035` | Captura read-only del proceso/config del 8765 |
| **[S4]** | `reports/backtest/_live_filter025_w1_w6.json` | `10e428a3fffab43f43f0790cf3e594275dc6ceb12ff447c119ea8a607dd85c12` | Brazo manual + filtro 0,25 |
| **[S5]** | `reports/backtest/p2_w1_w6_confirm.json` | `3b2d654a6298b181c0ad1161a038e7f8f95eaa70de26c211f2e3d2f82b9e9312` | Confirmación P2 |
| **[S6]** | `reports/backtest/p2_be_1r_experiment.json` | `eebefb261c4663992a65dbbe7687cb204184e89481d68ccd4dc85940d29c13c0` | P2 + break-even 1R |
| **[S7]** | `reports/backtest/presets_default_dev.json` | `d321ea0500341a4a94162c62a06dbcc17015dede356ab009da33540bff85ddbb` | Presets de un parámetro |
| **[S8]** | `reports/backtest/hour11_entry_filter.json` | `e774b8e5a76cca8fd485a1064835c1559abed114e6f03688b226df1fddee3ffd` | Filtro de entradas H11 |

**Nota de hashes:** `reports/backtest/DECISION_CONFIG_MANUAL_8765_VS_ORIGINAL.md` y otros documentos anteriores citan `9fcc2d0f…` para S1 y `4cdd6e23…` para S2. Esos hashes son históricos y **no** son los actuales. S1 fue regenerado el `2026-11-24T17:26:04Z` y S2 el `2026-11-25T02:43:43Z`; los hashes de esta tabla son los que corresponden a los artefactos usados aquí. No fue necesario reejecutar un backtest: S1 y S2 ya contienen los hashes internos de configuración/dataset correctos y el sidecar de S2 coincide.

### 3.2 Tabla principal manual vs original

| Métrica | Original `5/200/150/12` | Manual `10/300/210/24` | Δ manual − original | Fuente |
|---|---:|---:|---:|---|
| Operaciones | **38** | **72** | **+34 (+89,5 %)** | S1 `aggregate` |
| Neto USD | **+661,44** | **+2.022,94** | **+1.361,50 (+205,8 %)** | S1 `aggregate` |
| Retorno simple sobre 25.000 USD | **2,65 %** | **8,09 %** | **+5,45 pp** | Derivado de S1 |
| Profit factor | **1,13** | **1,22** | **+0,09** | S1 |
| Win rate | **31,58 %** | **36,11 %** | **+4,53 pp** | S1 |
| Expectancy USD/op | **17,41** | **28,10** | **+10,69 (+61,4 %)** | S1 |
| Expectancy R/op | **0,1311** | **0,1832** | **+0,0521** | S1 `total_r/trades` |
| Drawdown máximo USD | **1.967,82** | **2.891,66** | **+923,84 (+46,9 %)** | S1 |
| Drawdown % | **7,141 %** | **9,793 %** | **+2,652 pp** | S1 |
| RDD (neto/DD) | **0,3361** | **0,6996** | **+0,3635 (2,08×)** | Derivado de S1 |
| Fees base USD | 178,56 | 333,56 | +155,00 | S1 |
| Peor racha de pérdidas | 10 | 13 | +3 | S1 |
| Duración media | 4.215 s | 4.945 s | +730 s | S1 |

**Lectura:** la manual gana en neto, retorno simple, PF, win rate, expectancy y RDD; pierde en DD absoluto y porcentual y en peor racha. El mayor neto se paga con **+923,84 USD** de drawdown adicional.

**Por símbolo:** **no existe desglose por símbolo**. El único instrumento operado es **MNQ**; `NQ` es referencia SMT y `ES` es comparación SMT. Los artefactos S1/S2 no contienen un campo `by_symbol`; no se inventa ninguna cifra por símbolo. El desglose disponible es por dirección:

| Dirección | Original ops / neto | Manual ops / neto | Fuente |
|---|---:|---:|---|
| Largo | 21 / +335,36 | 44 / +1.614,94 | S1 `aggregate.*.by_direction` |
| Corto | 17 / +326,08 | 28 / +408,00 | S1 |

### 3.3 De dónde sale la diferencia

| Grupo | Operaciones | Neto | Fuente |
|---|---:|---:|---|
| Señales comunes | 37 | Manual **752,02** / Original **910,14** | S1 `paired` |
| Solo manual | 35 | **+1.270,92** | S1 |
| Solo original | 1 | **−248,70** | S1 |
| Total | 72 / 38 | **+2.022,94 / +661,44** | S1 |

La manual **pierde −158,12 USD** en las 37 señales que comparte. Su ventaja agregada es **cobertura de señales** (35 señales extra) y tamaño, no mejor selección o mejor ejecución de las mismas entradas.

Atribución secuencial:

| Palanca | Δ neto | Δ DD | Fuente |
|---|---:|---:|---|
| Original → P1: frecuencia `150/12 → 210/24`, 5 contratos, SL 200 | **+1.330,82** | −20,00 | S1 `attribution.sequential` |
| P1 → P2: `max_contracts 5 → 10` | **+479,52** | +356,64 | S1 |
| P2 → manual: `max_sl_ticks 200 → 300` | **−448,84** | **+587,20** | S1 |
| **Total** | **+1.361,50** | **+923,84** | S1; residuo 0,00 |

El stop 300 es un lastre medido: el cohorte de 26 operaciones con `stop_ticks > 200` pierde **−392,60 USD** y P2 las evita. La mejora de P2/M-SL200 no es pareada, pero la dirección es consistente con ese cohorte.

### 3.4 Estabilidad por ventana

| Ventana | Original | Manual | Diferencia |
|---|---:|---:|---:|
| W1 | +364,82 | +2.735,34 | +2.370,52 |
| W2 | +268,40 | +418,30 | +149,90 |
| W3 | −110,46 | −1.088,22 | −977,76 |
| W4 | +2.034,12 | +2.461,48 | +427,36 |
| W5 | −1.036,52 | −1.497,14 | −460,62 |
| W6 | −858,92 | −1.006,82 | −147,90 |
| **2026 (W5+W6)** | **−1.895,44** | **−2.503,96** | **−608,52** |

La manual gana en W1, W2 y W4; pierde en W3, W5 y W6. La ventaja agregada depende de dos trimestres fuertes y **no se sostiene en 2026**.

### 3.5 Significación y confianza

| Comprobación | Resultado | Fuente |
|---|---|---|
| Bootstrap por bloques (6 ventanas, 10.000 remuestreos) | Media **+1.390,94 USD**; IC 95 % **[-3.056,32; +6.965,66]**; `p=0,6544`; incluye cero | S1 `significance` |
| Muestra | 72 manual / 38 original; 362 sesiones; **un solo instrumento** | S1 |
| Naturaleza | **In-sample**, sin forward; holdout sellado | S1, S2 |
| Forward | `status=insufficient_data`; 0 sesiones; `forward_csv_exists=false`; H1 `sealed_not_executed` | S2 |
| Señales comunes | La manual pierde **−158,12 USD** en 37 señales compartidas | S1 |

**Confianza:** alta en que, **en esta muestra**, la manual produjo más neto; baja en que la diferencia sea un edge persistente. El IC incluye cero, la ventaja se concentra en señales extra y en dos trimestres, y 2026 es negativo para ambas. No hay forward que permita afirmar superioridad predictiva.

### 3.6 Runtime paper: contexto, no veredicto

| Captura | Ops | Neto | PF | DD | Win rate | Avg R | Uso |
|---|---:|---:|---:|---:|---:|---:|---|
| Snapshot S3, `2026-11-24T06:26Z` | 45 | +2.720,04 | 1,46 | 2.366,76 | 40,00 % | 0,35 | Replay paper congelado; **no** es W1–W6 ni forward (S3) |
| Última lectura reportada, `2026-11-24T12:02Z` | 72 | +2.269,38 | 1,23 | 3.099,36 | 36,11 % | 0,18 | API del proceso; contabilidad distinta al artefacto; **no** se usa para el veredicto (`MANUAL_8765_RENTABILIDAD_ACTUAL.md`) |

La diferencia entre runtime y artefacto controlado (mismos 72 trades y mismo R total, pero distinto neto/DD/fees) es contabilidad de replay/sizing; no se reconstruyó trade a trade y no se mezcla con la comparación. **El 8765 ya no está escuchando**; estas cifras son históricas.

### 3.7 Fichas de `forward_validation`

| Perfil | Ops | Neto | PF | DD USD | Expectancy USD | Fuente |
|---|---:|---:|---:|---:|---:|---|
| Manual 8765 | 72 | +2.022,94 | 1,22 | 2.891,66 | 28,10 | S2 `candidates[0]` |
| P2 `10/200/210/24` | 46 | +2.471,78 | 1,39 | 2.304,46 | 53,73 | S2 `candidates[1]` |
| P2 + BE 1R | 46 | +2.036,52 | 1,48 | 1.794,46 | 44,27 | S2 `candidates[2]` |
| Original `5/200/150/12` | 38 | +661,44 | 1,13 | 1.967,82 | 17,41 | S2 `historical_reference` |

`forward_validation` está en **`insufficient_data`**: no hay muestra forward independiente, el holdout sigue sellado y la ventana forward pre-registrada empieza el `2026-12-01`. No se puede promover ninguna configuración con estas fichas.

---

## 4. Veredicto

**La configuración manual del 8765 es más rentable que la original en la muestra histórica W1–W6**, con **+1.361,50 USD (+205,8 %)** de neto, PF **1,22 vs 1,13**, expectancy **28,10 vs 17,41 USD/op** y win rate **36,11 % vs 31,58 %**. También tiene mejor RDD (**0,6996 vs 0,3361**), pero **peor drawdown absoluto** (**+923,84 USD, +46,9 %**) y peor racha (**13 vs 10**).

La mejora **no es de calidad de ejecución**: en las 37 señales comunes la manual pierde **−158,12 USD**; gana por tomar 35 señales adicionales. La diferencia **no es estadísticamente distinguible de cero** (IC 95 % `[-3.056,32; +6.965,66]`, `p=0,6544`) y **no tiene validación forward**. La confianza en la superioridad futura es **baja**; la lectura correcta es “mejor rentabilidad histórica observada, con más riesgo y sin confirmación fuera de muestra”, no “configuración ganadora”.

Si el objetivo es **solo neto histórico**, la manual gana. Si el objetivo es **neto con riesgo controlado y evidencia predictiva**, no hay ganador claro: la original tiene menos DD y la manual no domina en las señales compartidas. **No se cambia el 8765 ni se activa `live_enabled` con esta evidencia.**

---

## 5. Mejoras priorizadas

**Regla:** ninguna se adopta en el 8765. Las cifras son in-sample y sirven para priorizar y diseñar validaciones, no para promocionar. No hay ninguna mejora de **alto impacto y bajo riesgo demostrada**: las que aumentan neto son in-sample; las que reducen riesgo no aumentan neto. Se separan por tipo.

### 5.1 Ranking

| # | Mejora | Cambio exacto | Base de comparación | Δ neto | DD del brazo | Ops | Evidencia | Categoría |
|---:|---|---|---|---:|---:|---:|---|---|
| 1 | Filtro stop/ORB 0,25 | `risk.min_stop_or_ratio 0,00 → 0,25`; nada más | Manual 72 | **+1.786,66** | 1.660,04 (−1.231,62) | 43 | S4; PF 1,92; WR 48,84 % | Alto impacto / cambio único; sobreajuste alto |
| 2 | M-SL200 | `risk.max_sl_ticks 300 → 200`; nada más | Manual 72 | **+448,84** | 2.304,46 (−587,20) | 46 | S1/S5; PF 1,39; WR 32,61 % | Alto impacto / cambio único; riesgo medio |
| 3 | Validez 240 | `strategy.setup_validity_minutes 210 → 240` | Original 38 | **+1.034,52** (no medido sobre la manual) | 1.583,44 | 51 | S7; PF 1,28; bootstrap incluye cero | Impacto medio / experimental |
| 4 | P1 / 5 contratos | `10/300/210/24 → 5/200/210/24` (paquete) | Manual 72 | **−30,68** | 1.947,82 (−943,84) | 46 | S1; PF 1,37; RDD 1,023 | Control de riesgo; **no sube neto** |
| 5 | P2 + BE 1R | P2 + break-even al tocar 1R | Manual / P2 | **+13,58 vs manual; −435,26 vs P2** | 1.794,46 (−1.097,20) | 46 | S2/S6; PF 1,48 | Control de riesgo; motor experimental |
| 6 | Filtro H11 | `ret3_dir ≤ −0,05` y `ret20_dir ≤ −0,40`; extended añade 10:50–11:05 + VWAP | Replay: 44 filtradas (56 originales) | **+1.841,08** core / **+2.787,50** extended | 1.294,12 / 1.061,64 | 44 base → 36/31 | S8; 0 ganadoras quitadas | Experimental alto impacto / alto riesgo |
| 7 | Swing estructural 6 | `strategy.structural_depth 3 → 6` | Original 38 | **+792,96** | 1.285,10 | 15 | S7/`BOOTSTRAP_BLOQUES.md`; PF 1,91; W4 87,1 % del neto | Experimental / muestra muy baja |

**Orden de lectura:** el #1 tiene el mayor Δ nominal, pero también el mayor riesgo de sobreajuste; el #2 es la mejora directa más defendible y ya tiene forward pre-registrado; el #3 es una hipótesis de frecuencia que necesita medirse sobre la manual; #4 y #5 son controles de riesgo, no mejoras de rentabilidad; #6 y #7 son experimentos. El Δ neto se interpreta contra la **base indicada**, no siempre contra la manual.

### 5.2 #1 — Filtro `min_stop_or_ratio=0,25` sobre la manual

**Regla:** mantener exactamente `10/300/210/24`, `replay 8×`, feed y ejecución; cambiar solo `risk.min_stop_or_ratio` de `0,00` a `0,25`. El filtro exige que el stop, normalizado por el ancho del ORB, no sea demasiado estrecho.

**Evidencia (S4):**

| Métrica | Manual sin filtro | Manual + filtro 0,25 | Δ |
|---|---:|---:|---:|
| Ops | 72 | **43** | −29 |
| Neto | 2.022,94 | **3.809,60** | **+1.786,66** |
| PF | 1,22 | **1,92** | +0,70 |
| Expectancy R | 0,180 | **0,480** | +0,300 |
| DD | 2.891,66 | **1.660,04** | **−1.231,62** |
| DD % | 9,793 % | **5,805 %** | −3,988 pp |
| Win rate | 36,11 % | **48,84 %** | +12,73 pp |

El cohorte rechazado son 29 operaciones con **−1.786,66 USD**, PF **0,65** y win rate **17,24 %**. Los 29 rechazos incluyen **todos los 17 trades con qty > 5**; el máximo observado baja de 10 a 5, así que parte de la mejora es **menor exposición**, no solo selección.

**Riesgos:** es exploratorio, no pre-registrado; el 0,25 se eligió mirando la muestra; W5 aporta **1.497,14 / 1.786,66 = 83,8 %** del Δ neto y W1/W2 son negativas; no hay P6/costes exactos para este brazo de 43 ops. No se puede heredar la validez de los gates del filtro sobre P2 (17 ops), que están **INCONCLUSO**.

**Validación propuesta:** lock nuevo `H-LIVE-FILTER-STOP-OR-025`, one-shot, control C = manual actual, tratamiento T = solo `min_stop_or_ratio=0,25`, mismo feed, sizing, fills y costes. Criterios congelados antes de mirar: Δ neto ≥ +500 USD; IC 95 % del Δ > 0; PF_T ≥ 1,30; DD_T ≤ 2.500 USD y ≤ DD_C; ≥30 ops T; Δ > 0 en ≥3/6 bloques; cost stress con comisión 1,24/lado y slippage 2 ticks con Δ > 0. Si falla cualquiera, `KEEP_MANUAL`.

### 5.3 #2 — M-SL200: bajar el tope de stop de 300 a 200

**Regla:** `risk.max_sl_ticks 300 → 200`; mantener 10 contratos, `210/24`, filtro 0, TP 3R y resto igual. La configuración resultante es P2 (`10/200/210/24`), pero la hipótesis es una sola palanca sobre la manual.

**Evidencia (S1/S5):** P2 hace **46 ops, +2.471,78 USD, PF 1,39, expectancy 53,73 USD/op, win rate 32,61 %, DD 2.304,46**. Frente a la manual: **+448,84 USD**, **−587,20 USD de DD**, **+0,17 PF**, **−26 ops**. El cohorte de 26 operaciones con stop >200 pierde **−392,60 USD**; P2 las evita. La comparación no es pareada y la mejora no viene de ejecutar mejor las señales comunes (P2 vs manual en 46 comunes: **−56,24 USD**).

**Riesgos:** PM5 histórico **falla** porque DD 2.304,46 > 2.000; el DD sigue por encima de la original (1.967,82); la win rate baja de 36,11 % a 32,61 %; no hay coste estresado exacto. Ya existe el lock `docs/p2_be_1r_forward.lock.json` (M/C/T) con `can_execute=false`; no se crea otro.

**Validación:** ejecutar el lock existente cuando pase a ejecutable; C = M-SL200; PM5 (`DD_C ≤ DD_M` y `DD_C ≤ 2.000`), K2/K5. Si C falla, `KEEP_MANUAL`; T (BE) no rescata a C. Antes, reprecio exacto de costes de M y M-SL200.

### 5.4 #3 — Extender la validez del setup de 210 a 240 minutos

**Regla:** `strategy.setup_validity_minutes 210 → 240`; una sola palanca.

**Evidencia (S7):** el preset `setup_validity_240` sobre el baseline original `5/200/150/12` da **51 ops, +1.695,96 USD, PF 1,28, DD 1.583,44**; frente al baseline original (+661,44) son **+1.034,52 USD** y **−384,38 USD de DD**. El bootstrap por bloques da IC 95 % del neto **[-3.073,54; +6.873,49]**, que incluye cero; no es significativo.

**Riesgos:** está medido sobre el perfil base 5/200, **no sobre la manual 10/300**; agregar 60 minutos puede añadir señales tardías y empeorar el DD; no hay forward. Es una hipótesis de frecuencia, no una mejora confirmada.

**Validación:** pre-registrar un brazo de una sola variable sobre la manual, con el mismo feed/ejecución; comparar contra la manual en W1–W6 con bootstrap de bloques y luego forward. Exigir Δ neto > 0, DD no mayor que la manual y ≥3/6 bloques positivos; si no, descartar. No cambiar 210 y 240 a la vez con otras palancas.

### 5.5 #4 — P1 / 5 contratos: control de riesgo, no mejora de neto

**Regla:** paquete P1 `5/200/210/24` (5 contratos y SL 200), no solo `max_contracts=5`; no hay artefacto de “5 contratos con SL 300”.

**Evidencia (S1):** P1 hace **46 ops, +1.992,26 USD, PF 1,37, expectancy 43,31, DD 1.947,82**. Frente a la manual: **−30,68 USD** de neto, pero **−943,84 USD de DD**; RDD **1,023 vs 0,700**. Es una mejora de rentabilidad ajustada por riesgo, no de rentabilidad absoluta. El forward original vs P1 es otra decisión y no incluye al 8765.

**Riesgos:** reduce tamaño y frecuencia; pierde neto absoluto; no hay forward ejecutado. No se propone si el objetivo es maximizar neto; se propone solo como control de DD.

**Validación:** forward separado original vs P1, con el lock vigente; comparar neto, DD y RDD; no mezclarlo con el 8765 ni con el filtro 0,25.

### 5.6 #5 — P2 + break-even 1R: mejora de riesgo, no de rentabilidad

**Regla:** sobre P2, mover el stop a la entrada cuando el MFE alcanza 1R, efectivo desde la vela siguiente, sin parciales ni trailing.

**Evidencia (S2/S6):** P2+BE hace **46 ops, +2.036,52 USD, PF 1,48, DD 1.794,46**; frente a la manual **+13,58 USD** y **−1.097,20 USD de DD**; frente a P2 **−435,26 USD** y **−510,00 USD de DD**. Mejora PF/DD, pero no el neto frente a P2; el motor BE es experimental (`FullManagementExecution`), no de producción.

**Riesgos:** baja el neto frente a P2; no hay forward; puede recortar ganadores. No se prioriza como mejora de rentabilidad.

**Validación:** brazo T del lock M/C/T, solo si C (M-SL200) pasa PM5; motor de producción versionado; forward con costes exactos.

### 5.7 #6 — Filtro de entradas H11 (experimental)

**Regla core:** no abrir una entrada nueva cuando `ret3_dir ≤ −0,05` **y** `ret20_dir ≤ −0,40`, con retornos normalizados por el ancho del ORB y firmados por dirección. **Extended:** añadir la ventana `10:50 ≤ entry_min < 11:05` y `vwap_dir ≤ 0` (minutos desde 09:30 ET).

**Evidencia (S8):** replay paper de 56 ops, 44 tras filtro; 8 pérdidas con salida en 11:00–11:59 y MFE < 1R. Core quita 8 ops: evita 4/8 H11, **0 ganadoras**, 4 otras pérdidas; **+1.841,08 USD**, DD 2.128,28→**1.294,12**, PF 2,00→**3,35**. Extended quita 13: evita 7/8 H11, **0 ganadoras**, 6 otras pérdidas; **+2.787,50 USD**, DD **1.061,64**, PF **5,13**. En el protocolo oficial de 14 ops, core/extended quitan 2 pérdidas, 0 ganadoras, **+371,96 USD**.

**Riesgos:** **no es la muestra manual de 72 ops** (es un replay paper de 56/44 de otra instancia); los umbrales y la ventana 10:50–11:05 se eligieron in-sample; la parte de VWAP/ventana es frágil; puede reducir frecuencia y eliminar señales buenas. Es experimental, no una regla para activar.

**Validación:** pre-registrar una sola regla (core o extended, no ambas), aplicarla a la manual W1–W6, comparar contra la manual con bootstrap y ventanas; luego forward. Exigir 0 ganadoras quitadas en la muestra de desarrollo, Δ neto > 0, DD ≤ manual y ≥3/6 bloques; si falla, descartar.

### 5.8 #7 — Swing estructural de 6 velas (experimental)

**Regla:** `strategy.structural_depth 3 → 6`; el stop estructural usa un swing de 6 velas de 15 m en lugar de 3.

**Evidencia (S7/`BOOTSTRAP_BLOQUES.md`):** el preset `sl_depth_6` sobre el baseline original da **15 ops, +1.454,40 USD, PF 1,91, DD 1.285,10**; frente al baseline original +661,44 son **+792,96 USD**. El bootstrap del neto da IC 95 % **[-2.919,90; +6.325,45]**, que incluye cero; W4 explica **87,1 %** del neto; solo 5/6 bloques tienen actividad; 15 ops es una muestra muy baja. Otra tabla de presets reporta 1.539,64/1.199,86 para el mismo preset, por lo que **no se usa un único número como definitivo**.

**Riesgos:** muestra insuficiente, concentración extrema en W4, cambia el stop y puede reducir entradas; no hay forward. No es promocionable.

**Validación:** ampliar la muestra, pre-registrar el cambio de una sola variable, costes exactos y forward; exigir ≥24 ops y ≥5/6 bloques con actividad antes de considerar promoción.

### 5.9 Lo que no se propone

| Idea | Por qué |
|---|---|
| Subir `max_contracts` por encima de 10 | No hay artefacto; el salto 5→10 ya añadió +479,52 USD y +356,64 USD de DD; es apalancamiento, no edge |
| Activar `live_enabled` | No hay forward, ni costes exactos, ni P6; el holdout sigue sellado |
| Cambiar TP 3R, ORB o SMT sin estudio | No hay evidencia de una mejora directa sobre la manual; sería otra hipótesis post hoc |
| Usar el holdout para “confirmar” | Viola el protocolo v1.2; H1 sigue `sealed_not_executed` |
| Replay 8× → 1× | Δ neto 0,00; solo cambia el reloj de pared |
| Reabrir filtro 0,25 sobre P2 (17 ops) | Gates INCONCLUSO, 4 fallos, P6 NO_EVALUABLE, 17 ops; no es la misma hipótesis que el filtro sobre la manual de 43 ops |

---

## 6. Integridad y verificación

| Comprobación | Resultado |
|---|---|
| Configuración viva en disco | `data/config.json` y `profiles/live_8765/config.json` con SHA-256 `9bf4f9c7…`; sin cambios |
| Hash canónico | `d3cff10d…`; coincide con la captura S3 |
| Dataset | `data/bars.csv` con SHA-256 `1cc455e9…` |
| S1 | SHA-256 `40377a5d…`; hashes internos de configs y dataset correctos |
| S2 | SHA-256 `9635136f…`; sidecar contiene el mismo hash; `status=insufficient_data` |
| S3 | SHA-256 `f017e17e…`; config de API = archivos; `configs_modified=false` |
| Coherencia S2/S1 | `forward_validation.candidates[0]` = manual de S1; `historical_reference` = original de S1; comprobado por script |
| Coherencia S4/S1 | El brazo base del filtro 0,25 = manual de S1; Δ neto aritmético comprobado |
| 8765 ahora | **sin listener** en `127.0.0.1:8765`; PID `15108` no existe; no se arrancó, paró, reinició ni reconfiguró |
| Escritura en DB | No por este análisis; S3 la leyó read-only |
| Holdout | Sellado; no usado |
| Forward | 0 sesiones; no ejecutado |
| Código/tests | No se modificaron código ni tests; no se requiere suite nueva. Los artefactos se validaron con comprobaciones de hashes y aritmética read-only |
| Commit/push | No realizados |

**Limitaciones explícitas:** no hay desglose por símbolo porque solo se opera MNQ; no hay lista trade-by-trade de la manual 72 en S1; no hay coste estresado exacto de la manual ni del filtro sobre la manual; el runtime 8765 no está disponible ahora y sus cifras no se usan para el veredicto; la comparación principal es in-sample y el forward está pendiente.

---

## 7. Recomendación final

1. **Mantener la configuración manual actual en paper**: `10/300/210/24`, `min_stop_or_ratio=0,00`, `live_enabled=false`. No hay evidencia suficiente para cambiarla.
2. **No añadir el filtro 0,25 a producción**: es el mayor Δ histórico, pero es post hoc, tiene confusor de sizing, W5 concentra el 83,8 % del Δ y no tiene P6. Solo a un lock forward nuevo.
3. **Ejecutar el forward ya pre-registrado de M-SL200** cuando su lock lo permita; no crear otro ni cambiar sus umbrales.
4. **Tratar P1/5 contratos y P2+BE como controles de riesgo**, no como mejoras de rentabilidad.
5. **No abrir el holdout ni activar live** hasta que exista un forward independiente, costes exactos y aprobación explícita.
