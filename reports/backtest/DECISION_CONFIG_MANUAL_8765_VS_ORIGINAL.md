# Decisión única — configuración manual del 8765 frente a la original

**Fecha de cierre:** 2026-11-24

**Objeto:** instancia paper que escucha en `127.0.0.1:8765`.

**Decisión vigente:** **mantener la configuración manual actual (`10/300/210/24`, filtro 0,00) y no adoptar ninguna mejora todavía.**

**Naturaleza:** revisión read-only de configuración, artefactos y gates ya existentes. No se ejecutó reprecio, backtest, captura ni escritura en DB durante este cierre. Las cifras históricas son in-sample; el holdout permanece sellado.

---

## 0. Resumen ejecutivo

- **Lo que corre ahora:** perfil manual `10 contratos / SL 300 / validez 210 / retest 24`, `min_stop_or_ratio=0,00`, modo `paper`, `live_enabled=false`, PID 15108, listener `127.0.0.1:8765` **[S9]**. La API coincide con `data/config.json` y con `profiles/live_8765/config.json`; estos dos archivos son idénticos byte a byte **[S9, S12, S13]**.
- **Rentabilidad histórica:** en W1–W6 (362 sesiones), la manual gana **+2.022,94 USD** frente a **+661,44 USD** de la original (**+1.361,50 USD, +205,8 %**), con PF **1,22 vs 1,13** y expectancy R **0,183 vs 0,131**. Pero el drawdown empeora **+923,84 USD** (**2.891,66 vs 1.967,82**) **[S1]**.
- **La ventaja no es una mejora de ejecución:** en las 37 señales comunes la manual hace **752,02 USD** y la original **910,14 USD**; la manual pierde **−158,12 USD** en los trades que ambas toman. La diferencia agregada procede de 35 señales que solo toma la manual (**+1.270,92 USD**), no de ejecutar mejor las mismas señales **[S1]**.
- **No es estadísticamente distinguible:** bootstrap por 6 bloques, 10.000 remuestreos: media **+1.390,94 USD**, IC95 % **[-3.056,32, +6.965,66]**, `p=0,6544`; el intervalo incluye cero **[S1]**.
- **La única mejora directa con respaldo numérico es M-SL200** (`max_sl_ticks` 300→200): **+448,84 USD** y **−587,20 USD de DD** frente a la manual en la muestra histórica **[S1]**. No se adopta: el resultado es in-sample, no hay forward y la propuesta queda bloqueada por el reprecio exacto de costes `G-M-COST`, que no se ha ejecutado **[S10, S11]**.
- **El filtro 0,25 no es un camino activo.** Su resultado nominal es alto (17 ops, +4.202,20, PF 4,25, DD 946,38), pero sus gates están **INCONCLUSO**, con 4 fallos de cobertura/concentración y **P6_COST_STRESS = NO_EVALUABLE**; no hay forward y la nota de vigencia lo descarta **[S5, S10, S16]**.
- **Recomendación:** no cambiar el 8765 hoy. Dejar M-SL200 y el reprecio exacto en observación; no tocar el filtro, P2+BE, el límite de 10 contratos ni `live_enabled`. Cualquier cambio necesita lock propio, costes exactos y validación forward.

---

## 1. Configuración efectiva del 8765

### 1.1 Proceso y servicio

Comprobación hecha con consultas de proceso y lecturas HTTP, sin reiniciar ni modificar la instancia.

| Elemento | Valor observado | Fuente |
|---|---|---|
| Listener | `127.0.0.1:8765` | `netstat -ano`; **[S9]** |
| PID | `15108` (`python.exe`) | `Get-CimInstance Win32_Process`; **[S9]** |
| Comando | `python.exe -u run.py` | **[S9]** |
| Arranque | `2026-11-23T20:12:49-06:00` = `2026-11-24T02:12:49Z` | **[S9]** |
| Estado HTTP | `ok`, versión `1.0.0` | `GET /api/health`; **[S9]** |
| Motor | `running` | `GET /api/status`, 2026-11-24T07:15Z |
| Modo | `paper` | `GET /api/status` |
| Ejecución real | `live.live_enabled=false` | `GET /api/config`; **[S9]** |
| Feed | CSV `data/bars.csv`, serie `adjusted`, 151.530 velas 1m, 6 rolls, 6 sesiones de roll excluidas | `GET /api/status`; **[S9]** |
| DB del perfil | `profiles/live_8765/yedbot.db`; 54 trades en lectura read-only a las 07:16Z | Consulta SQLite `mode=ro` |

El proceso arrancó con los bytes de configuración ya presentes en disco. No hay un log de recarga que permita fechar una aplicación posterior; se afirma la fecha de arranque, no una recarga no documentada **[S9]**.

**Limitación de identidad del perfil:** el `CommandLine` del PID no expone `YED_PROFILE_DIR`. La ruta `profiles/live_8765` se apoya en el lanzador registrado y en la coincidencia exacta entre la API y esa copia. Como `data/config.json` y `profiles/live_8765/config.json` son idénticos, el perfil efectivo es el mismo manual en cualquiera de los dos casos; lo que no se puede distinguir desde el PID es cuál de los dos archivos idénticos se cargó **[S9]**.

### 1.2 Parámetros efectivos

La tabla siguiente sale de `GET /api/config` y coincide con `data/config.json` y `profiles/live_8765/config.json`. La API también devuelve un bloque `defaults` con `5/200/150/12`; **no son los valores activos**: los activos son los de `settings`.

| Parámetro | Valor vivo | `data/config.json` | `profiles/p2_freq/config.json` | Original canónico |
|---|---:|---:|---:|---:|
| `risk.max_contracts` | **10** | 10 | 10 | 5 |
| `risk.max_sl_ticks` | **300** | 300 | **200** | 200 |
| `strategy.setup_validity_minutes` | **210** | 210 | 210 | 150 |
| `strategy.retest_tolerance_ticks` | **24** | 24 | 24 | 12 |
| `risk.min_stop_or_ratio` | **0,00** | 0,00 | 0,00 | 0,00 |
| `risk.risk_per_trade_pct` | 1,00 | 1,00 | 1,00 | 1,00 |
| `risk.max_trades_per_day` | 3 | 3 | 3 | 3 |
| `risk.max_concurrent_positions` | 1 | 1 | 1 | 1 |
| `strategy.tp_rr` | 3,0 | 3,0 | 3,0 | 3,0 |
| `live.live_enabled` | false | false | false | false |

Fuente: `GET /api/config`; **[S12, S13, S14]**; diferencias original: **[S1]**. El original establecido es `5/200/150/12`; el vivo es `10/300/210/24`. **El 8765 no aplica el filtro 0,25**: su `min_stop_or_ratio` es `0,00`. Tampoco es P2: la única diferencia entre el perfil vivo y `profiles/p2_freq/config.json` es `risk.max_sl_ticks` (300 vs 200) **[S9, S14]**.

### 1.3 ORB, SMT, ejecución y feed

| Bloque | Valores activos | Fuente |
|---|---|---|
| ORB | `09:00–10:00` America/New_York; `max_width_pct=1,2` | `GET /api/config` |
| SMT | activo; `pivot_depth=5`, `window_minutes=60`, `tolerance_ticks=8`, `min_break_ticks=2`, `validity_minutes=120`, `detect_tf=1m`, `require_recovery=true` | `GET /api/config` |
| Estrategia | `confirm_tf=15m`; cierre de ruptura obligatorio; buffer 2 ticks; rango mínimo 10 ticks; `entry_reference=or_mid`; retesteo 0,382; `retest_depth=1,0`; `entry_trigger=close`; stop estructural con buffer 4 ticks; ATR 14 × 1,2; TP 3R | `GET /api/config` |
| Ejecución | `tick_size=0,25`; `tick_value=0,50`; `point_value=2,0`; `commission_per_contract_side=0,62`; `slippage_ticks=1`; `max_slippage_ticks=4`; `fill_model=next_open`; parciales desactivados | `GET /api/config`; **[S12]** |
| Feed | `provider=csv`; `csv_path=data/bars.csv`; `series_mode=adjusted`; `exclude_roll_sessions=true`; `replay_speed=8,0`; `loop_sessions=true` | `GET /api/config`; **[S9]** |
| Riesgo de sesión | ventana 09:00–15:30; cierre 15:55; pérdida diaria máxima 3 %; sin límite de beneficio diario; 3 operaciones/día; 1 posición concurrente | `GET /api/config` |
| Broker | `broker=none`; `environment=demo`; `live_enabled=false` | `GET /api/config` |

El `replay_speed=8,0` es una diferencia operativa frente al original (`4,5`), no una palanca de estrategia **[S1]**. El artefacto de replay existente prueba 8× frente a 1× con secuencia idéntica; no prueba 4,5× **[S1]**. No se le atribuye efecto económico.

### 1.4 Divergencias y hashes

| Objeto | SHA-256 | Estado |
|---|---|---|
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | Coincide con la copia viva |
| `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | Idéntico a `data/config.json` |
| Hash canónico de la API | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` | Coincide con el canónico de ambos archivos; excluye `feed`, `live` y `mode` |
| `profiles/p2_freq/config.json` | `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb` | Diverge solo en `max_sl_ticks=200` |
| `data/bars.csv` | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` | Coincide con `file_hash` de la API |

**Divergencias encontradas:** ninguna entre API, `data/config.json` y `profiles/live_8765/config.json`. Las únicas diferencias son las ya conocidas frente al original (`max_contracts`, `max_sl_ticks`, `setup_validity_minutes`, `retest_tolerance_ticks`) y frente a P2 (`max_sl_ticks`) **[S1, S9]**. `profiles/backtest_real/config.json` no se usa como prueba de la original `150/12`: su archivo actual no materializa necesariamente esa frecuencia; la referencia original sale del protocolo y de `live_vs_original_mission.json` **[S1, S17]**.

---

## 2. Rentabilidad: manual 8765 frente a la original

### 2.1 Muestra y método

Muestra idéntica W1–W6: `2025-01-10` → `2026-06-30`, **362 sesiones**, serie ajustada, capital inicial 25.000 USD, holdout no usado y 2024 no usado **[S1]**. Comparación de **carteras**, no de las mismas operaciones ejecutadas de dos formas: la manual toma señales que la original no toma.

### 2.2 Tabla principal

Cada fila procede de `live_vs_original_mission.json` **[S1]**, SHA-256 `9fcc2d0fb1cb0b8c0d5b5bce62ec227b3d416d79819cfa0cffd9d58b8e9104e3`; la exposición usa además el denominador de 2.353 h de **[S10]**. La ficha `baseline_manual` de `forward_validation.json` **[S2]** repite los valores de M y O.

| Métrica | Original 38 | Manual 72 | Diferencia | Fuente |
|---|---:|---:|---:|---|
| Operaciones | 38 | 72 | +34 | **[S1]** |
| Neto USD | **+661,44** | **+2.022,94** | **+1.361,50 (+205,8 %)** | **[S1]** |
| Profit factor | 1,13 | 1,22 | +0,09 | **[S1]** |
| Expectancy USD/op | 17,41 | 28,10 | +10,69 | **[S1]** |
| Expectancy R/op | 0,131 | 0,183 | +0,052 | **[S1]**; calculado como `total_r/trades` |
| R total | +4,98 | +13,19 | +8,21 | **[S1]** |
| Drawdown USD | **1.967,82** | **2.891,66** | **+923,84 (+46,9 %)** | **[S1]** |
| Drawdown % | 7,141 | 9,793 | +2,652 pp | **[S1]** |
| **RDD USD** (`neto/DD`) | **0,3361** | **0,6996** | **+0,3635 (2,08×)** | **[S1]**; calculado |
| Peor racha de pérdidas | 10 | 13 | +3 | **[S1]** |
| Acierto | 31,58 % | 36,11 % | +4,53 pp | **[S1]** |
| Fees base | 178,56 | 333,56 | +155,00 | **[S1]** |
| Fees/op | 4,70 | 4,63 | −0,07 | **[S1]**; calculado |
| Duración media (s) | 4.215 | 4.945 | +730 (+17,3 %) | **[S1]** |
| Tiempo en mercado (h) | 44,49 | 98,90 | +54,41 (+122,3 %) | **[S1]**; derivado |
| Exposición (% de 2.353 h) | 1,89 % | 4,20 % | +2,31 pp | **[S1, S10]**; derivado |
| Largo: ops / neto | 21 / +335,36 | 44 / +1.614,94 | +23 / +1.279,58 | **[S1]** |
| Corto: ops / neto | 17 / +326,08 | 28 / +408,00 | +11 / +81,92 | **[S1]** |

**Lectura de tiempo y dirección:** el manual dura un 17,3 % más por operación y acumula 98,90 h de exposición (4,20 % de las 2.353 h de la muestra), frente a 44,49 h (1,89 %) del original. La diferencia de 72 vs 38 operaciones explica que el tiempo agregado suba un 122,3 %, no que cada operación dure el doble. En dirección, el manual gana en ambos lados: 44 largos (+1.614,94) y 28 cortos (+408,00); el largo aporta el 79,8 % del neto y el corto el 20,2 %, sin un lado perdedor. Los fees base son 333,56 USD (4,63 USD/op); el neto ya está después de fees, pero no es un reprecio estresado.

**Lectura:** la manual gana más en absoluto, tiene mejor PF, expectancy y RDD, pero **no domina en riesgo**: su DD es 923,84 USD mayor y su peor racha pasa de 10 a 13 pérdidas. La mejora de RDD se debe a que el neto sube más que el DD, no a que el DD sea menor.

### 2.3 De dónde viene la diferencia

| Paso de atribución | Δ neto USD | Δ DD USD | Fuente |
|---|---:|---:|---|
| Original → P1: frecuencia `150/12 → 210/24` con 5 contratos y SL 200 | **+1.330,82** | −20,00 | **[S1]**, `attribution.sequential` |
| P1 → P2: `max_contracts 5 → 10` | **+479,52** | +356,64 | **[S1]**, `attribution.sequential` |
| P2 → manual: `max_sl_ticks 200 → 300` | **−448,84** | **+587,20** | **[S1]**, `attribution.sequential` |
| **Original → manual** | **+1.361,50** | **+923,84** | **[S1]**, `attribution.total`; residual 0,00 |

La ventaja del manual frente a la original viene de **tomar más señales** y de **usar 10 contratos**, no de una mejor selección por stop. El stop 300 es, de hecho, el lastre: el cohorte de 26 operaciones con `stop_ticks > 200` pierde **−392,60 USD** y explica casi toda la diferencia frente a P2 **[S1]**, `diagnostics.stop_gt_200`. La reconciliación es `448,84 = 392,60` (cohorte que P2 evita) `+ 56,24` (mejor neto de P2 en las señales comunes); no es una comparación pareada, pero sí identifica de dónde sale la ventaja de P2.

### 2.4 La ventaja desaparece en las señales comunes

En la intersección literal de **37 señales comunes**, la manual hace **752,02 USD** y la original **910,14 USD**: la manual pierde **−158,12 USD** en los trades que ambas toman. La diferencia agregada procede de **35 señales que solo toma la manual (+1.270,92 USD)** y de **1 señal que solo toma la original (−248,70 USD)** **[S1]**, `paired`.

**Conclusión:** es cobertura de señales, no mejor ejecución. Una cartera con más señales y más contratos puede ganar más en bruto y, al mismo tiempo, ser peor en las operaciones que comparte.

### 2.5 Significancia y estabilidad

| Comprobación | Resultado | Fuente |
|---|---|---|
| Bootstrap por 6 bloques, 10.000 remuestreos | Media **+1.390,94 USD**; IC95 % **[-3.056,32, +6.965,66]**; `p=0,6544`; incluye cero | **[S1]**, `significance` |
| W1 | Manual +2.735,34; original +364,82 | **[S1]**, `windows` |
| W2 | Manual +418,30; original +268,40 | **[S1]** |
| W3 | Manual −1.088,22; original −110,46 | **[S1]** |
| W4 | Manual +2.461,48; original +2.034,12 | **[S1]** |
| W5 | Manual −1.497,14; original −1.036,52 | **[S1]** |
| W6 | Manual −1.006,82; original −858,92 | **[S1]** |
| 2026 (W5+W6) | Manual **−2.503,96**; original **−1.895,44** | **[S10]** |

La manual gana en W1, W2 y W4; pierde en W3, W5 y W6. La ventaja agregada depende de dos trimestres fuertes y no se sostiene en 2026. El bootstrap no permite afirmar una ventaja estadística con 72/38 operaciones in-sample.

### 2.6 Runtime paper: no es la muestra histórica

| Captura | Ops | Neto USD | PF | DD USD | avg R | Uso |
|---|---:|---:|---:|---:|---:|---|
| Snapshot 06:26Z **[S9]** | 45 | +2.720,04 | 1,46 | 2.366,76 | 0,35 | runtime paper congelado; no es W1–W6 ni forward |
| API `/api/stats`, 07:15Z | 53 | +4.325,94 | 1,68 | 2.366,76 | 0,41 | replay en curso; sigue avanzando |

El replay actual no reconstruye las 72 operaciones W1–W6, no sustituye la comparación histórica y no es una validación forward. La DB se leyó read-only a las 07:16Z con 54 trades; el conteo cambió por el propio replay, no por una escritura de este análisis. **No se usa ninguna de estas cifras para el veredicto.**

### 2.7 Qué está medido, qué es inferencia y qué falta

| Estado | Contenido |
|---|---|
| **Medido** | M 72 vs O 38 en W1–W6: neto, PF, expectancy, DD, RDD, operaciones, acierto, rachas; duración media y exposición agregada; composición por dirección; fees base; atribución por frecuencia/tamaño/stop; 37 señales comunes; bootstrap; ventanas; P2 46; P2+BE 46; filtro 17; stress exacto del original; runtime paper. |
| **Inferido** | La ventaja de M frente a O es cobertura de señales y tamaño, no mejor ejecución (se deduce de la intersección y de la atribución). El stop 300 es un lastre (26 ops con stop >200 y −392,60 USD). M-SL200 reduce el DD y, en la muestra, aumenta el neto; no está validado fuera de muestra. |
| **Pendiente** | Reprecio exacto de M y M-SL200; stress exacto de P2, P2+BE y filtro; distribución/mediana de duración y lista trade-by-trade del manual; forward independiente; P6; holdout. No hay ninguna cifra forward. |

### 2.8 Huecos del manual 72: resolución y registro formal

La revisión del agregado `aggregate.live` de **[S1]** corrige la lectura inicial: el manual 72 **sí** tiene duración media, fees y composición por dirección. **[S10]** todavía muestra Manual 72 **n/d** en su tabla de exposición; no se usa esa fila, se usa `aggregate.live` de S1, que sí contiene `avg_duration_sec`. No se reconstruyó nada ni se ejecutó un backtest; son campos del artefacto ya existente. La lista trade-by-trade del manual no está en S1, así que la duración solo se resuelve como media y la distribución/mediana queda fuera.

| ID | Hueco | Estado | Evidencia existente | Resolución | Límite |
|---|---|---|---|---|---|
| **G-M-TIME** | Tiempo en mercado | **ABIERTO (parcial)** | `S1.aggregate.live.avg_duration_sec=4.945` y `trades=72`; **[S10]** da 2.353 h (362 × 6,5 h) y deja Manual n/d | **4.945 s/op** es el campo `avg_duration_sec`; no hay campo de tiempo total ni de exposición, así que el total no se presenta como medido | No hay campo de tiempo total ni de exposición; la media no sustituye el total. La mediana/distribución queda en G-M-TRADE-LIST |
| **G-M-DIR** | Composición por dirección | **RESUELTO** | `S1.aggregate.live.by_direction` | **Largo:** 44 ops, +1.614,94, 17G/27P, 38,6 %; **corto:** 28 ops, +408,00, 9G/19P, 32,1 % | Los valores son campos; la suma 72/+2.022,94 es comprobación aritmética; no hay lista por trade |
| **G-M-COST-BASE** | Coste base | **RESUELTO (fee base)** | `S1.aggregate.live.fees=333,56` | **333,56 USD** es el campo `fees`; el fee por operación no es campo y no se usa como medida; `net_profit` es el neto reportado, no se recalcula | No separa comisión por contrato ni por lado; no es estrés |
| **G-M-COST-STRESS** | Reprecio estresado exacto | **ABIERTO** | **[S5]** `gates` (objeto `P6_COST_STRESS`): `values.artifact=null`; P6 NO_EVALUABLE; **[S7]** solo original; **[S11]** diseño no ejecutado | No hay artefacto de reprecio de M | No se puede cerrar sin reejecutar fills; **no se ejecutó** y no se imputa el coste de O/P2 |
| **G-M-TRADE-LIST** | Lista trade-by-trade / distribución de duración | **ABIERTO** | S1 solo agregados; **[S3]** tiene listas de O/P2, no de M | No se puede calcular mediana, percentiles ni duración por trade | No se reconstruye desde agregados; requeriría una ejecución nueva, no autorizada aquí |

**Resultado:** **dirección** queda resuelta con campos; **tiempo** queda resuelto solo en la media (`avg_duration_sec`) y abierto en total/exposición; **coste** queda resuelto en el fee base y abierto en el estrés exacto. Los abiertos no bloquean la decisión de mantener M, pero impiden afirmar que M resista un coste más alto o que su exposición total sea un dato medido. No se usó P2 como proxy de M ni se inventó una comisión media.

---

## 3. Robustez y gates

### 3.1 Estado actual

`filter025_gates.json` **[S5]** es la capa de gates del **filtro 0,25 sobre P2**, no de la configuración manual. Su estado actual es:

| Estado | Gates | Número |
|---|---|---:|
| **PASS** | I1, I2, S5, E1, E3, P1, P2, P3, Q2, Q5, P5, P8, P9 | **13** |
| **FALLA** | Q1 cobertura trimestral, Q3 concentración, Q4 consistencia de rechazados, P7 cobertura mensual | **4** |
| **INCONCLUSO** | S0 muestra total, S2 baseline, S3 cohorte, S4 muestra por bloque, E2 bootstrap | **5** |
| **NO_EVALUABLE** | **P6_COST_STRESS** | **1** |
| **Global** | **INCONCLUSO**; promoción **NO**; holdout **sealed** | — |

Fuente: **[S5]**, `summary` y `decision`; `backtest_executed=false`, `holdout_read=false`. El detalle de los fallos:

- **Q1:** 4/6 trimestres activos; W5 y W6 vacíos.
- **Q3:** top-2 trimestres = **85,28 %** del neto; el umbral es 80 %.
- **Q4:** solo 3/6 trimestres con rechazados consistentes; W4 no tiene rechazados.
- **P7:** 10/18 meses activos; racha máxima sin operar de 6 meses; el umbral es 4.
- **S0/S2/S3/S4:** muestra insuficiente para 17 aceptadas / 29 rechazadas / 46 baseline; solo 2/6 bloques con muestra.
- **E2:** el bootstrap de selección es positivo (IC95 % [+0,3312, +2,3548] R; `p≈0,006`), pero no puede dar PASS porque no alcanza las precondiciones de muestra y cobertura.

### 3.2 P6_COST_STRESS, hoy

| Campo | Valor | Fuente |
|---|---|---|
| Estado | **NO_EVALUABLE** | **[S5]** |
| Artefacto de reprecio | **null** | **[S5]**, `values.artifact` |
| Gate usado | **false** | **[S5]**, `values.gate_used` |
| Estimación uniforme | neto 4.101,40; PF 4,0811; R medio 1,1233 | **[S5]**, solo diagnóstico |
| Umbral que exigiría | `mean_r_accepted > 0` y `r_profit_factor_accepted >= 1,10`, con fills repreciados | **[S11]** |

**P6 no está evaluado y la estimación uniforme no es evidencia P6.** P6 evalúa el filtro 0,25, no P2: P2 es el control del reprecio. El reprecio exacto requiere reejecutar el motor con comisión `1,24/lado`, slippage `2 ticks` y `max_slippage_ticks=4`; no se puede obtener restando una cantidad fija al P&L histórico **[S11]**. El diseño existe, pero no se ejecutó. `stress_costs.json` es del perfil original de 38 trades y no se reutiliza como si fuera el filtro **[S5, S11]**.

### 3.3 Qué condiciona el veredicto

- **La comparación manual/original no está condicionada por los gates del filtro.** Esos gates evalúan otra hipótesis (filtro 0,25 sobre P2) y no se heredan para la manual. La manual no tiene un P6 propio; su coste base sí está medido (333,56 USD), pero su reprecio estresado es **n/d**.
- **El filtro no se puede promocionar:** el global es INCONCLUSO, con 4 fallos y P6 NO_EVALUABLE. Su PF 4,25 es un resultado in-sample de 17 operaciones, no una expectativa forward.
- **La manual tampoco está validada:** su ventaja histórica no es estadísticamente distinguible de cero, no tiene coste estresado y no tiene forward. El veredicto correcto es “mejor rentabilidad histórica observada, con confianza predictiva insuficiente”, no “configuración ganadora”.
- **El coste es un riesgo material:** el original, con costes exactos más altos, cae de 661,44 a **347,38 USD** (PF 1,13→1,07; DD 2.064,14) y absorbe **−314,06 USD** **[S7]**. Para la manual y P2 no existe esa medición estresada; no se puede afirmar que resistan.

---

## 4. Mejoras propuestas, ordenadas por impacto esperado en rentabilidad

**Regla:** ninguna propuesta está implementada. Las cifras son in-sample y sirven para priorizar, no para promocionar. No se atribuye a ninguna propuesta una mejora que no esté medida.

### 4.1 Ranking

| # | Palanca y parámetro | Δ neto vs M | Δ DD vs M | Evidencia | Estado |
|---:|---|---:|---:|---|---|
| 1 | **M-SL200:** `risk.max_sl_ticks 300 → 200`; nada más | **+448,84** | **−587,20** | P2 46 vs M 72; PF 1,22→1,39; R medio 0,18→0,25 **[S1, S3]** | **Bloqueada** por `G-M-COST` y forward |
| 2 | **Reprecio exacto de costes** (precondición, no palanca de retorno) | No cuantificado | No cuantificado | Original exacto: 347,38 / PF 1,07; M base 333,56 y P2 base 282,72; estrés n/d **[S7, S10]** | **No ejecutado**; diseño **[S11]** |
| 3 | **P2 + BE 1R** sobre SL200 | **+13,58** vs M; **−435,26** vs P2 | **−1.097,20** vs M | P2+BE 46: +2.036,52, PF 1,48, DD 1.794,46 **[S8]** | Experimental; no hay forward ni motor de producción |
| 4 | **P1 / 5 contratos:** `max_contracts 10 → 5`, SL200, 210/24 | **−30,68** | **−943,84** | P1 46: +1.992,26, PF 1,37, DD 1.947,82 **[S1]** | Reducción de riesgo, no mejora de neto; forward separado |
| 5 | **Más de 10 contratos** | Sin artefacto | Sin artefacto | Solo se midió 5→10: +479,52 neto y +356,64 DD **[S1]** | **No propuesta**; sin evidencia |
| 6 | **Filtro 0,25 sobre P2** | **+2.179,26** vs M; **+1.730,42** vs P2 | **−1.945,28** vs M | 17 ops, +4.202,20, PF 4,25, DD 946,38 **[S4, S5]** | **Descartado/INCONCLUSO**; P6 NO_EVALUABLE; sin forward |

La frecuencia `210/24` y los 10 contratos **ya están incorporados** en la manual; no son mejoras incrementales. Volver a contarlas sería doble conteo. La palanca de frecuencia aportó +1.330,82 frente al original en el paso original→P1, y el salto 5→10 aportó +479,52; ambas ya están dentro de M **[S1]**.

### 4.2 M-SL200 — la única mejora directa con respaldo

**Cambio exacto:** en el perfil manual, `risk.max_sl_ticks=200`; mantener 10 contratos, 210/24, filtro 0,00, TP 3R, ORB, SMT, feed y ejecución. La configuración resultante coincide con `profiles/p2_freq/config.json`, pero la hipótesis es una sola palanca sobre M; no se adopta el paquete P2 ni su plan **[S10]**.

**Por qué debería mejorar:** un cap de 300 permite stops estructurales más amplios; al bajarlo a 200 se rechazan las señales cuyo stop excede 200 ticks. En W1–W6 eso elimina 26 operaciones y reduce la cola de pérdida. El artefacto muestra **+448,84 USD** de neto y **−587,20 USD** de DD, con PF 1,39 y R medio 0,25 **[S1, S3]**.

**Evidencia disponible:** comparación P2 46 vs M 72; atribución del stop; cohorte de 26 ops con stop >200 que pierde −392,60 USD **[S1]**. **Evidencia faltante:** no es una comparación pareada; P2 no ejecuta las señales que M sí toma. No hay reprecio exacto de M-SL200, no hay forward y el DD absoluto de P2 (2.304,46) sigue por encima del original (1.967,82). El PM5 histórico de la propuesta falla porque el DD supera 2.000 **[S18]**.

**Riesgo:** menos operaciones y menor frecuencia; la tasa de acierto baja de 36,11 % a 32,61 %; el neto depende de ganadores grandes. **Bloqueo:** `G-M-COST` debe repreciar M y M-SL200 con comisión 1,24/lado y slippage 2 ticks; si el Δneto después de costes no es positivo, la propuesta se descarta. Después haría falta un forward con lock propio **[S10, S11]**.

### 4.3 Reprecio exacto — precondición, no mejora de retorno

No sube el bruto: evita que un PF histórico se convierta en neto falso al repreciar. El original tiene stress exacto (347,38 USD, PF 1,07, DD 2.064,14; coste absorbido −314,06) **[S7]**. Para M, P2 y el filtro no hay reprecio exacto: sus fees base están medidos (M 333,56; P2 282,72; filtro 55,80), pero el filtro solo tiene una estimación uniforme de −100,80, que **no es P6** **[S10]**. El diseño `COST_REPRICING_FILTER_P2.md` define los brazos, el modelo de fills y los hashes, pero está **no ejecutado** **[S11]**. Sin este paso, M-SL200 y cualquier otra optimización quedan bloqueadas.

### 4.4 P2 + BE 1R — mejora de riesgo, no de rentabilidad

**Cambio:** mantener P2 `10/200/210/24`, filtro 0,00, y añadir break-even cuando el MFE alcanza 1R, efectivo desde la vela siguiente, sin parciales ni trailing **[S8]**. **Resultado:** 46 ops, +2.036,52, PF 1,48, DD 1.794,46; frente a M **+13,58 USD** y **−1.097,20 DD**; frente a P2 **−435,26 USD** y **−510,00 DD** **[S8]**. **Por qué no se prioriza:** baja el neto frente a P2 y solo suma +13,58 frente a M con dos cambios; el motor BE es experimental (`FullManagementExecution`), no está versionado en producción y no tiene forward **[S2, S8]**. No es un rescate de M-SL200.

### 4.5 P1 / 5 contratos — alternativa de riesgo

P1 `5/200/210/24` hace +1.992,26, PF 1,37, DD 1.947,82; frente a M pierde **−30,68 USD** y reduce el DD **−943,84** **[S1]**. Es una reducción de riesgo, no una mejora de rentabilidad. El forward vigente original vs P1 es otra decisión y no incluye el 8765, P2 ni el filtro **[S16]**. No se adopta en este cierre.

### 4.6 Filtro 0,25 — mayor número nominal, menor credibilidad

El filtro acepta 17 de 46 operaciones y hace +4.202,20, PF 4,25, DD 946,38; frente a P2 +1.730,42 y −1.358,08 DD **[S4]**. Pero: 17 ops, 4/6 trimestres activos, W5/W6 vacíos, top-2 = 85,28 % del neto, 10/18 meses activos y racha de 6 meses sin operar. Los gates están **INCONCLUSO**, con 4 fallos y P6 **NO_EVALUABLE**; la estimación uniforme de −100,80 no es evidencia exacta **[S5, S10]**. La nota de vigencia descarta el filtro y excluye P2/8765 del forward **[S16]**. **No se reabre.**

### 4.7 Lo que no se propone

| Candidato | Por qué no |
|---|---|
| Subir `max_contracts` por encima de 10 | No hay artefacto; el 5→10 ya añadió +479,52 de neto pero también +356,64 de DD; es apalancamiento, no edge **[S1]** |
| Cambiar TP 3R, ORB o SMT sin estudio | No hay evidencia medida en los artefactos; sería una hipótesis nueva, no una mejora respaldada |
| Evitar 2026 o seleccionar ventanas | El filtro evita pérdidas W5/W6, pero es in-sample y no hay regla de calendario validada **[S10]** |
| Activar `live_enabled` | No hay forward, ni costes exactos, ni P6; la instancia sigue en paper **[S9]** |

---

## 5. Recomendación final

### 5.1 Qué adoptar ya

**Nada nuevo.** Mantener la configuración manual actual:

```text
max_contracts             = 10
max_sl_ticks              = 300
setup_validity_minutes    = 210
retest_tolerance_ticks    = 24
min_stop_or_ratio         = 0,00
tp_rr                     = 3,0
mode                      = paper
live_enabled              = false
```

La manual es el benchmark vivo y no hay evidencia suficiente para reemplazarla. **No se cambia el 8765, no se reinicia y no se toca la DB.**

### 5.2 Qué dejar en observación

1. **M-SL200 + reprecio exacto `G-M-COST`:** es la única mejora directa con cifra medida. Condición para pasar a forward: el reprecio exacto con comisión 1,24/lado y slippage 2 ticks debe mantener un Δneto positivo frente a M y un PF aceptable; después, un lock forward propio. Si el Δneto después de costes no es positivo, se descarta.
2. **P1 / 5 contratos:** observarla solo como alternativa de riesgo. Condición: que el forward original vs P1 muestre que la frecuencia 210/24 compensa la reducción de tamaño; hoy no hay forward.
3. **Runtime paper:** sirve para verificar que el motor sigue vivo y que la configuración no cambia; no para inferir rentabilidad. Condición de alarma: que la API deje de coincidir con los archivos o que `live_enabled` cambie sin autorización.

### 5.3 Qué no tocar

- **Filtro 0,25:** no activar; gates INCONCLUSO, P6 NO_EVALUABLE, sin forward.
- **P2+BE:** no implementar; baja el neto frente a P2, el motor es experimental y no hay forward.
- **Más de 10 contratos:** no subir; no hay evidencia y el DD ya es 9,79 % en la muestra manual.
- **`live_enabled`:** no activar; la instancia debe seguir en paper.
- **ORB, SMT, TP 3R y ejecución:** no cambiar sin un estudio propio; no hay evidencia en estos artefactos.

### 5.4 Condiciones observables que cambiarían la decisión

| Decisión | Condición para cambiarla |
|---|---|
| Mantener M y no adoptar M-SL200 | Si el reprecio exacto muestra Δneto(M-SL200−M) ≤ 0 después de costes, o si el forward no supera sus gates, se mantiene M. |
| Pasar M-SL200 a forward | Si `G-M-COST` deja Δneto positivo y el PF/DD no se degradan de forma inaceptable, se crea un lock forward; no se adopta por el resultado in-sample. |
| Reabrir P1 | Si el forward original vs P1 demuestra que la frecuencia compensa el menor tamaño; hoy `insufficient_data`. |
| Reabrir filtro 0,25 | Solo con un lock nuevo, P6 exacto y gates que pasen; hoy está descartado y el global es INCONCLUSO. |
| Reabrir P2+BE | Solo si existe motor de producción versionado y un forward que supere a M en neto, no solo en PF/DD. |
| Cambiar el original | Si se prioriza DD estricto sobre neto, la original o P1 tienen menor DD, pero también menor neto; no hay forward que lo justifique. |
| Activar live | Solo después de un forward validado, costes exactos y aprobación explícita; hoy no se cumple ninguna. |

### 5.5 Veredicto en una frase

**La configuración manual del 8765 es más rentable que la original en la muestra histórica W1–W6 (+1.361,50 USD), pero con más drawdown (+923,84 USD), sin ventaja en las señales comunes, sin significancia estadística y sin validación forward; la decisión correcta es mantenerla en paper y no adoptar ninguna mejora hasta completar el reprecio exacto y el forward.**

---

## 6. Verificación de integridad de este cierre

| Comprobación | Resultado |
|---|---|
| Reprecio ejecutado | **No.** `COST_REPRICING_FILTER_P2.md` sigue siendo diseño; no existe artefacto de reprecio |
| Backtest nuevo | **No.** Este cierre solo leyó artefactos y la API; el `backtests_run=true` de `live_vs_original_mission.json` describe su generación anterior, no este pase |
| Escritura en DB | **No por este análisis.** La DB se leyó en modo `ro`; el replay del bot puede seguir escribiendo por su cuenta |
| Captura iniciada | **No.** `live_8765_decision_check.json` registra `capture_started=false` |
| Configuraciones modificadas | **No.** Los hashes de `data/config.json`, `profiles/live_8765/config.json` y `profiles/p2_freq/config.json` no cambiaron |
| Dataset modificado | **No.** `data/bars.csv` conserva `1cc455e9…` |
| Holdout | **Sellado.** H1 `2026-07-01`→`2026-10-30`, 85 sesiones, `sealed_not_executed`; `holdout_read=false` |
| Forward | **No ejecutado.** `status=insufficient_data`; 0 sesiones; CSV forward inexistente; ventana pre-registrada desde `2026-12-01` |
| Placeholders | **Ninguno.** Las celdas no disponibles se marcan `n/d` y se explican; `G-M-TIME` (parcial), `G-M-COST-STRESS` y `G-M-TRADE-LIST` están registrados en §2.8 |

### 6.1 Hashes protegidos

```text
data/config.json                     9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f
profiles/live_8765/config.json      9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f
profiles/p2_freq/config.json        ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb
profiles/backtest_real/config.json  8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f
data/bars.csv                       1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a
```

### 6.2 Hashes de los artefactos citados

| Ref. | Artefacto | SHA-256 |
|---|---|---|
| **[S1]** | `reports/backtest/live_vs_original_mission.json` | `9fcc2d0fb1cb0b8c0d5b5bce62ec227b3d416d79819cfa0cffd9d58b8e9104e3` |
| **[S2]** | `reports/backtest/forward_validation.json` | `4cdd6e2333f2a5423b7abe516c3b4ed8caa6790402d09a9987758de3ab383b32` |
| **[S3]** | `reports/backtest/p2_w1_w6_confirm.json` | `3b2d654a6298b181c0ad1161a038e7f8f95eaa70de26c211f2e3d2f82b9e9312` |
| **[S4]** | `reports/backtest/_manual_filter025_w1_w6.json` | `193a2bc1ab9885eb55ee988ca082cf51ed2975ca15f6c1421605d379c723aca7` |
| **[S5]** | `reports/backtest/filter025_gates.json` | `66cf5ce0dabf1ab0b646a6809f8adee4c991d1f5e4f7211f79cdea0e07f6ee5b` |
| **[S6]** | `reports/backtest/filter025_gates.config.json` | `793911a4dc8b02794121f5b562faf207932d1628c155a309d51b18a9f6fbc852` |
| **[S7]** | `reports/backtest/stress_costs.json` | `bfd50c4e07b7649da4ac92a7969df54bcfccb40e91cb1039ec7b26a07405de6d` |
| **[S8]** | `reports/backtest/p2_be_1r_experiment.json` | `eebefb261c4663992a65dbbe7687cb204184e89481d68ccd4dc85940d29c13c0` |
| **[S9]** | `reports/backtest/live_8765_decision_check.json` | `f017e17ef553864fddb6bc706374d36f520fe68f7547091d1b53f29743a00035` |
| **[S10]** | `reports/backtest/FILTER025_PROFITABILITY.md` | `f3cbaf83943287c88fcfab6afbe561594edfc1e97f8863d4dfe5bcf1906a61f6` |
| **[S11]** | `reports/backtest/COST_REPRICING_FILTER_P2.md` | `64a75f9e6ec10be9a70a6d229de03fb5955a3b0e6c9db61e54ed495e8e50008f` |
| **[S12]** | `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| **[S13]** | `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| **[S14]** | `profiles/p2_freq/config.json` | `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb` |
| **[S15]** | `data/bars.csv` | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` |
| **[S16]** | `docs/FORWARD_ORIGINAL_VS_P1.md` | `0b43b6439b5922fad258b5ee7a616b2e654ebf98c5736fcc9fd919d7a204a77a`; documento de vigencia, no es lock ni autoriza ejecución |
| **[S17]** | `profiles/backtest_real/config.json` | `8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f` |
| **[S18]** | `docs/p2_be_1r_forward.lock.json` | `ad72a200943febc2382e40372d199b8a7fda2d78fa67818e96c27be779735dd5`; PM5 y `can_execute=false` |
| **[S19]** | `profiles/p1_forward_control/config.json` | `8058b7d7002de547a535a349dbe7f3557e4aaea1e92d392b064dd51b0b8b624b` |

**Reproducción mínima:**

```bash
sha256sum data/config.json profiles/live_8765/config.json profiles/p2_freq/config.json \
  profiles/p1_forward_control/config.json data/bars.csv \
  reports/backtest/live_vs_original_mission.json reports/backtest/forward_validation.json \
  reports/backtest/p2_w1_w6_confirm.json reports/backtest/_manual_filter025_w1_w6.json \
  reports/backtest/filter025_gates.json reports/backtest/filter025_gates.config.json \
  reports/backtest/stress_costs.json reports/backtest/p2_be_1r_experiment.json \
  reports/backtest/live_8765_decision_check.json
```

---

## 7. Matriz de trazabilidad dimensión × perfil × artefacto

**Regla de lectura:** cada celda es `valor [fuente]`; los `[S#]` remiten a §6.2. No se ejecutó ningún backtest para completar la matriz. `n/d` = no existe en el artefacto; `—` = no aplica. Las cifras son W1–W6 (362 sesiones, 2025-01-10 → 2026-06-30), salvo la fila de runtime, que se excluye de la comparación económica.

**Perfiles:** **O** = original canónico `5/200/150/12`; **M** = manual vivo `10/300/210/24`, filtro 0,00; **P1** = `5/200/210/24`; **P2** = `10/200/210/24`; **P2+BE** = P2 + break-even 1R; **F0,25** = P2 + `min_stop_or_ratio=0,25`.

| Dimensión | O | M | P1 | P2 | P2+BE | F0,25 |
|---|---|---|---|---|---|---|
| Configuración | `5/200/150/12` [S1] | `10/300/210/24` [S9, S13] | `5/200/210/24` [S19] | `10/200/210/24` [S14] | P2 + BE 1R [S8] | P2 + 0,25 [S4] |
| Operaciones | 38 [S1] | 72 [S1] | 46 [S1] | 46 [S1, S3] | 46 [S8] | 17 [S4, S5] |
| Neto USD | +661,44 [S1] | +2.022,94 [S1] | +1.992,26 [S1] | +2.471,78 [S1, S3] | +2.036,52 [S8] | +4.202,20 [S4, S5] |
| PF | 1,13 [S1] | 1,22 [S1] | 1,37 [S1] | 1,39 [S1, S3] | 1,48 [S8] | 4,25 [S4, S5] |
| Expectancy R | 0,13 [S1] | 0,18 [S1] | 0,25 [S1] | 0,25 [S1] | 0,22 [S8] | 1,11 [S1, S4] |
| DD USD / % | 1.967,82 / 7,14 % [S1] | 2.891,66 / 9,79 % [S1] | 1.947,82 / 6,75 % [S1] | 2.304,46 / 7,84 % [S1, S3] | 1.794,46 / 6,31 % [S8] | 946,38 / 3,36 % [S4] |
| Duración media | 4.215 s [S1] | 4.945 s [S1] | 3.686 s [S1] | 3.686 s [S1] | 2.782 s [S8] | 8.463 s [S1] |
| Largo: ops / neto | 21 / +335,36 [S1] | 44 / +1.614,94 [S1] | 26 / +1.318,30 [S1] | 26 / +1.756,18 [S1] | 26 / +1.010,68 [S8] | 9 / +1.937,24 [S4] |
| Corto: ops / neto | 17 / +326,08 [S1] | 28 / +408,00 [S1] | 20 / +673,96 [S1] | 20 / +715,60 [S1] | 20 / +1.025,84 [S8] | 8 / +2.264,96 [S4] |
| Fees base USD | 178,56 [S1] | 333,56 [S1] | 218,24 [S1] | 282,72 [S1] | 281,48 [S8] | 55,80 [S4, S5] |
| Coste estresado exacto | 347,38 / PF 1,07 / DD 2.064,14 [S7] | n/d [S7, S11] | n/d [S7, S11] | n/d [S7, S11] | n/d [S7, S11] | n/d; P6 NO_EVALUABLE [S5, S10] |
| Robustez / gates | n/a; baseline [S1] | bootstrap IC95 % incluye 0 [S1] | forward 0 sesiones [S2, S16] | forward 0 sesiones [S2] | experimental; sin forward [S2, S8] | INCONCLUSO: 13P/4F/5I/1NE [S5] |
| Forward / holdout | 0 sesiones; sellado [S2] | insufficient_data [S2] | no ejecutable; 0 sesiones [S2, S16] | insufficient_data [S2] | 0 sesiones; sin forward [S2, S8] | NO PROMOVER; P6 NO_EVALUABLE [S5] |

**Cobertura de la muestra:** 362 sesiones en `S1.scope.sessions`; `S8.sessions=362`; las ventanas de S3 y S4 suman 362. No se incluye una celda de sesiones porque no es un campo de cada agregado.

**Límites de la matriz:** `Duración media` es `avg_duration_sec` (campo). El tiempo total y la exposición no son campos de S1/S8; se derivan en §2.2 y §2.8, pero no se presentan como celdas de matriz. RDD tampoco es un campo: queda como cálculo en §2.2. El runtime 8765 no se incluye: no es un perfil W1–W6 y sus cifras están en §2.6.

**Cobertura de los artefactos citados:**

| Artefacto | Perfiles | Dimensiones que cubre | Límite |
|---|---|---|---|
| **[S1]** `live_vs_original_mission.json` | O, M, P1, P2, F0,25 | neto, PF, expectancy, DD, duración media, fees base, dirección; ventanas, bootstrap, atribución | Solo agregados; no lista trade-by-trade de M |
| **[S3]** `p2_w1_w6_confirm.json` | O, P2 | listas de trades, fees, duración, dirección; corroboración | No incluye M ni P1 |
| **[S4]** `_manual_filter025_w1_w6.json` | F0,25 | agregados y trades del filtro | 17 ops; no es M |
| **[S5]** `filter025_gates.json` | F0,25 | gates, cobertura, P6 | P6 NO_EVALUABLE |
| **[S7]** `stress_costs.json` | O | reprecio exacto de costes | Solo O; no M/P2/filtro |
| **[S8]** `p2_be_1r_experiment.json` | P2, P2+BE | neto, PF, DD, duración, dirección, fees | Experimental; sin forward |
| **[S2]** `forward_validation.json` | M, P2, P2+BE | forward/holdout | 0 sesiones; `insufficient_data` |
| **[S9]** `live_8765_decision_check.json` | Runtime 8765 | proceso, API, config, stats | No es W1–W6 ni forward |
| **[S10]** `FILTER025_PROFITABILITY.md` | M, F0,25 | denominador de exposición 2.353 h; gates/P6 | Manual n/d en S10; el dato M sale de S1; no es artefacto de trades |
| **[S11]** `COST_REPRICING_FILTER_P2.md` | M, P2, F0,25 | diseño de reprecio | **No ejecutado** |
| **[S19]** `profiles/p1_forward_control/config.json` | P1 | configuración `5/200/210/24` | No es artefacto de resultados |

**Lectura de la matriz:** M no domina en riesgo (DD 2.891,66 y PF 1,22 frente a P1 1.947,82/1,37 y P2 2.304,46/1,39), pero sí supera a O en neto. P2+BE mejora el PF y el DD frente a P2, pero pierde neto; F0,25 tiene el mejor nominal, con 17 ops y gates INCONCLUSO. La matriz no cambia el veredicto: **mantener M en paper**.

---

**Estado final:** documento único de decisión; configuración viva identificada; comparación manual/original trazada; matriz de trazabilidad y huecos del manual 72 documentados; gates y P6 documentados; mejoras ordenadas con evidencia y bloqueos; holdout sellado; sin reprecio, sin backtest nuevo y sin escritura de este análisis en la DB.
