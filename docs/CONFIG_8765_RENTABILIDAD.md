# Configuración manual del 8765: estado efectivo y rentabilidad

**Cierre de la comprobación:** 2026-11-25T02:01:30Z · **proceso:** PID `15108` · **escucha:** `127.0.0.1:8765`

**Naturaleza:** lectura y análisis. No se reinició, paró ni reconfiguró el 8765; no se escribió en su DB; no se abrió el holdout ni se ejecutó un backtest nuevo para este documento.

**Decisión:** no cambiar nada en el 8765. Las mejoras de §5 son hipótesis para validar fuera de esa instancia.

> **Lectura corta:** el proceso HTTP sigue vivo, pero el motor está **detenido** desde el final del replay (`2026-11-24T09:28:36Z`), sin posición abierta. La configuración efectiva es la manual `10/300/210/24`, `min_stop_or_ratio=0,00`, en `paper` y con `live_enabled=false`. El P&L observado es **paper**, no dinero real. En la muestra controlada W1–W6 la manual gana **+1.361,50 USD** a la original configurada, pero con **+923,84 USD** más de drawdown, sin significancia estadística y sin forward.

## 0. Resumen ejecutivo

| Dimensión | Resultado |
|---|---|
| Configuración efectiva | Manual `10 contratos / SL 300 ticks / validez 210 min / retest 24 ticks`, filtro 0,00; MNQ con NQ/ES como referencias; `paper`; sin broker. |
| Identidad de configuración | `data/config.json` y `profiles/live_8765/config.json` idénticos: SHA-256 `9bf4f9c7…e29479f`. Canónico de trading: `d3cff10d…6dcd10`. |
| Estado operativo | Servidor HTTP `200`; `/api/status` = `stopped`, posición `null`, `blocked_reason="Motor detenido"`. El replay terminó al agotar `2026-06-30`. |
| P&L observado (paper) | 72 operaciones, **+2.269,38 USD**, PF **1,23**, DD **3.099,36 USD (10,337 %)**, acierto **36,11 %**. Periodo de entradas: 2025-01-13 → 2026-06-17. |
| Comparación controlada W1–W6 | Manual **+2.022,94 USD** vs original **+661,44 USD**: **+1.361,50 USD**; DD **2.891,66 vs 1.967,82**; RDD **0,6996 vs 0,3361**. |
| Incertidumbre | 72/38 operaciones in-sample; bootstrap IC95 % del delta **[−3.056,32; +6.965,66]**, `p=0,6544`; 2026 negativo; no hay forward ni P&L real. |
| Mejora nominal mayor | `P2 + min_stop_or_ratio=0,25`: +2.179,26 USD, pero 17 operaciones y gates `INCONCLUSO`; **no promover**. |
| Mejora más defendible para probar primero | `max_sl_ticks 300→200`: +448,84 USD y −587,20 USD de DD, 46 operaciones. No aplicarla aún: DD 2.304,46 y sin forward. |

## 1. Configuración efectiva del proceso vivo

### 1.1 Proceso, servicio y estado

La comprobación se hizo con `Get-Process`/`Get-CimInstance`, `GET /api/health`, `GET /api/status`, `GET /api/config` y una lectura SQLite en modo `ro`. No se envió ninguna orden ni se cambió el estado del motor.

| Elemento | Valor | Fuente |
|---|---|---|
| Listener | `127.0.0.1:8765` | `Get-NetTCPConnection` |
| PID | **15108** | `Get-NetTCPConnection` |
| Proceso | `python.exe -u run.py` | `Get-CimInstance Win32_Process` |
| Arranque | `2026-11-23 20:12:49` local (`2026-11-24T02:12:49Z`) | `CreationDate` / `StartTime` |
| HTTP | **200**, `health=ok`, versión `1.0.0` | `GET /api/health` |
| Motor | **`stopped`** | `GET /api/status` |
| Posición | `null` | `GET /api/status` |
| Motivo de bloqueo | `Motor detenido` | `GET /api/status.risk.blocked_reason` |
| Último evento | `Fin de los datos disponibles; motor detenido` (2026-11-24T09:28:36Z) | DB `events`, ID 729 |
| Modo / broker | `paper` / `none` | `/api/config` |
| `live.live_enabled` | **`false`** | `/api/config` |
| DB del perfil | `profiles/live_8765/yedbot.db` | lanzador documentado; API coincide |
| Feed | CSV `data/bars.csv`, serie `adjusted`, 151.530 velas 1m, 362 sesiones, 6 rolls | `/api/status` |

**Importante:** que el puerto responda no significa que el bot esté operando. El servidor sigue vivo y la configuración sigue cargada, pero el motor está detenido porque el replay llegó al final del CSV. No hay órdenes ni P&L nuevo después de esa parada.

El `CommandLine` del PID no expone `YED_PROFILE_DIR`. El perfil se identifica por el lanzador registrado y, sobre todo, porque `GET /api/config.settings` coincide exactamente con `profiles/live_8765/config.json`. Como `data/config.json` es byte a byte idéntico, el perfil efectivo es el mismo aunque el entorno no sea visible desde el PID.

### 1.2 Hashes e identidad

| Objeto | SHA-256 / valor |
|---|---|
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| Hash canónico de trading de la viva | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` |
| `profiles/live_8765/yedbot.db` | `d99f115d3169f09bdaef1952420da1d1b05e8dd3e283af05c9311dcbbd801fce` |
| `data/bars.csv` | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` |
| Dataset `dataset_id` de la API | `f2e9a2c5dff56b79195dcc19cc79b2dd9b2245ebfde6e7956471967a31f3f2b3` |
| Perfil original base | `8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f` |
| Original canónica `5/200/150/12` | `87b8b9f18dbce9e4739112cf734850fe75de7e82e7548425d246027d2234e708` |
| Lock del protocolo | `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c` |

No hay divergencia entre la API y los dos archivos de configuración. La diferencia entre el hash de archivo y el canónico es deliberada: `config_sha256` excluye `feed`, `live` y `mode`; no es un bug.

### 1.3 Parámetros de estrategia y mercado

| Bloque | Valor efectivo |
|---|---|
| Instrumento | **MNQ**; referencia **NQ**; comparación **ES** |
| Modo | `paper`; broker `none`; entorno `demo`; LIVE desactivado |
| ORB | `09:00–10:00` America/New_York; `max_width_pct=1,2 %` |
| SMT | Activo; pivote 5; ventana 60 min; tolerancia 8 ticks; ruptura mínima 2 ticks; validez 120 min; detección 1m; recuperación obligatoria |
| Confirmación | 15m; cierre de ruptura obligatorio; buffer 2 ticks; rango mínimo 10 ticks |
| Entrada | Referencia `or_mid`; retroceso 0,382; `retest_depth=1,0`; tolerancia de retest **24 ticks**; recuperación de cierre obligatoria; entrada por cierre |
| Stop / target | Stop estructural; buffer 4 ticks; ATR 14 × 1,2; **TP 3R**; profundidad estructural 3 |
| Validez de setup | **210 minutos** |
| Reentrada | Desactivada tras falso breakout |
| Ventana operativa | 09:00–15:30 ET; cierre de sesión 15:55 ET |
| Exclusión horaria | **Ninguna** (`entry_exclusion_start/end` vacíos) |

### 1.4 Riesgo, sizing y ejecución

| Parámetro | Valor efectivo | Lectura |
|---|---:|---|
| `risk.initial_capital` | 25.000 USD | Capital de referencia |
| `risk.risk_per_trade_pct` | **1,0 %** | Presupuesto por operación |
| `risk.max_contracts` | **10** | Tope de sizing; en la DB se usaron 1–10 contratos |
| `risk.max_sl_ticks` | **300** | Cap de stop más amplio que el original (200) |
| `risk.min_stop_or_ratio` | **0,00** | Sin filtro stop/ORB |
| `risk.max_trades_per_day` | 3 | Límite de actividad |
| `risk.max_concurrent_positions` | 1 | Sin solapamiento |
| `risk.max_daily_loss_pct` | 3,0 % | 750 USD sobre 25.000 |
| `risk.max_daily_profit_pct` | 0,0 % | Sin tope de beneficio diario |
| `risk.cooldown_minutes` | 5 | Espera tras operación |
| `risk.no_trade_after_consecutive_losses` | 0 | Sin bloqueo por racha |
| `execution.tick_size` / `tick_value` | 0,25 / 0,50 USD | MNQ |
| `execution.point_value` | 2,0 USD | MNQ |
| `execution.commission_per_contract_side` | **0,62 USD/lado** | Se paga por contrato y lado |
| `execution.slippage_ticks` | **1 tick/lado** | Coste asumido por el motor |
| `execution.fill_model` | `next_open` | Fill en apertura siguiente |
| `execution.simulate_partial_fills` | `false` | Sin fills parciales |
| `execution.max_slippage_ticks` | 4 | Tope de slippage |
| `feed.replay_speed` | 8,0× | Operativo; no cambia la secuencia medida |

### 1.5 Diff exacto contra la original establecida

La original de referencia es **`5 contratos / SL 200 / validez 150 / retest 12`**, con `min_stop_or_ratio=0,00`. No es un perfil inmutable en disco: se construye a partir de `profiles/backtest_real/config.json` y el parche determinista de `reports/backtest/_manual_common.py` (`ORIGINAL_FREQUENCY_PATCH` 150/12); las métricas W1–W6 usan la configuración efectiva resultante.

| Parámetro | Viva 8765 | Original | Efecto |
|---|---:|---:|---|
| `risk.max_contracts` | **10** | 5 | Más tamaño máximo |
| `risk.max_sl_ticks` | **300** | 200 | Acepta stops más profundos |
| `strategy.setup_validity_minutes` | **210** | 150 | Más tiempo para validar |
| `strategy.retest_tolerance_ticks` | **24** | 12 | Más señales de retest |
| `feed.replay_speed` | 8,0 | 4,5 | Operativo; 0,00 USD de efecto medido |

El resto —ORB, SMT, geometría de entrada, TP 3R, riesgo 1 %, 3 trades/día, una posición, comisiones, slippage y ventana— es idéntico.

## 2. Rentabilidad observada

### 2.1 P&L del proceso vivo: paper, no dinero real

Lectura de `GET /api/stats` a **2026-11-25T02:01:30Z**, contrastada con una consulta read-only a la DB del perfil:

| Métrica | Valor | Fuente |
|---|---:|---|
| Operaciones | **72** | `/api/stats`; `COUNT(trades)=72` |
| Periodo de entradas / última salida | 2025-01-13 11:28 ET → 2026-06-17 14:47 ET | DB, `entry_ts`/`exit_ts` |
| Sesiones con operaciones | 72 fechas distintas | DB |
| Neto después de fees | **+2.269,38 USD** | `/api/stats`; `SUM(pnl)` |
| Gross profit / gross loss / fees | +12.251,92 / −9.982,54 / **357,12** | `/api/stats`; `SUM(gross_pnl)` / `SUM(fees)` |
| Profit factor | **1,23** | `/api/stats` |
| Acierto | **36,11 %** (26 G / 46 P) | `/api/stats` |
| Expectancy | **31,52 USD/op**; **0,18 R** | `/api/stats` |
| Drawdown máximo | **3.099,36 USD**; **10,337 %** | `/api/stats` |
| Peor racha perdedora | **13** | `/api/stats` |
| Duración media | 8.332 s | `/api/stats` |
| Equity final | 27.269,38 USD | `/api/stats` |

**Composición observada:** 43 salidas por `stop_loss` suman −9.851,18 USD; 14 por `take_profit` suman +8.515,52; 15 por `session_close` suman +3.605,04. Por dirección: 44 largos +1.432,06 y 28 cortos +837,32. El sizing efectivo fue 1–10 contratos; 7 operaciones usaron 10.

**Límite:** esto es una cuenta **paper** sobre un replay CSV. No hay broker, `live_enabled=false`, no hay dinero real y no hay forward. No se puede llamar "rentabilidad real" en el sentido de una cuenta financiada.

### 2.2 Comparación controlada con la original (W1–W6)

Para comparar de forma homogénea se usan las dos patas re-ejecutadas con el mismo motor, dataset y ventanas:

- **Muestra:** W1–W6, `2025-01-10` → `2026-06-30`, **362 sesiones**, `data/bars.csv` ajustado, capital inicial 25.000 USD.
- **Costes:** 0,62 USD por contrato y lado; 1 tick de slippage por lado; `next_open`; sin fills parciales.
- **Original:** `5/200/150/12` con `min_stop_or_ratio=0,00`.
- **Viva:** `10/300/210/24` con `min_stop_or_ratio=0,00`.

| Métrica | Original 5/200/150/12 | Viva 10/300/210/24 | Δ (viva − original) |
|---|---:|---:|---:|
| Operaciones | 38 | 72 | **+34** |
| Neto USD | **+661,44** | **+2.022,94** | **+1.361,50 (+205,8 %)** |
| Profit factor | 1,13 | 1,22 | +0,09 |
| Expectancy USD/op | 17,41 | 28,10 | +10,69 |
| Expectancy R/op | 0,131 | 0,183 | +0,052 |
| R total | +4,98 | +13,19 | +8,21 |
| Drawdown USD | **1.967,82** | **2.891,66** | **+923,84** |
| Drawdown % | 7,141 | 9,793 | +2,652 pp |
| RDD (neto/DD) | **0,3361** | **0,6996** | **+0,3634** |
| Acierto | 31,58 % | 36,11 % | +4,53 pp |
| Peor racha perdedora | 10 | 13 | +3 |
| Fees base | 178,56 | 333,56 | +155,00 |

**Fuentes:** `reports/backtest/live_vs_original_mission.json` (`aggregate.original`, `aggregate.live`, `paired`, `significance`), cuyos valores coinciden con `reports/autoloop/resultados.jsonl#manual_base` y `reports/autoloop/resultados_original.jsonl#original_5_200_150_12`. El artefacto de misión tiene SHA-256 `40377a5daf096444acdd46c69f3da9c5d57233430625b261aa2caa378f0dab37`.

La RDD mejora porque el neto sube más que el DD; **no** porque el riesgo sea menor. El DD absoluto es 923,84 USD mayor y la racha perdedora empeora de 10 a 13.

### 2.3 De dónde viene la diferencia

| Paso | Cambio | Δ neto | Δ DD |
|---|---|---:|---:|
| Original → P1 | Frecuencia `150/12 → 210/24` con 5 contratos y SL 200 | **+1.330,82** | −20,00 |
| P1 → P2 | `max_contracts 5 → 10` | **+479,52** | +356,64 |
| P2 → viva | `max_sl_ticks 200 → 300` | **−448,84** | **+587,20** |
| **Total** | Original → viva | **+1.361,50** | **+923,84** |

El stop 300 es el lastre identificado: 26 operaciones con `stop_ticks > 200` pierden **−392,60 USD** en la muestra. La reconciliación es `448,84 = 392,60` (cohorte que P2 evita) `+ 56,24` (mejor neto de P2 en señales comunes). No es una comparación pareada.

En las **37 señales comunes**, la viva hace **752,02 USD** y la original **910,14 USD**: la viva pierde **−158,12 USD** en los trades que ambas toman. La diferencia agregada procede de **35 señales solo-viva (+1.270,92)** y **1 solo-original (−248,70)**. Cada pata reconcilia con su propio total: `752,02 + 1.270,92 = 2.022,94` (viva) y `910,14 − 248,70 = 661,44` (original); no se deben sumar los dos "solo" como si fueran un único puente.

**Conclusión:** la ventaja es cobertura de señales + tamaño, no mejor ejecución de las mismas señales.

### 2.4 Significación, estabilidad y límites

- Bootstrap por 6 bloques, 10.000 remuestreos: media **+1.390,94 USD**, IC95 % **[−3.056,32; +6.965,66]**, `p=0,6544`; incluye cero.
- La viva gana W1, W2 y W4; pierde W3, W5 y W6. En 2026 (W5+W6) la viva hace **−2.503,96 USD** y la original **−1.895,44**.
- La comparación es **in-sample** y de **carteras**, no de las mismas operaciones: 72 vs 38 operaciones.
- **No hay forward:** el CSV termina el 2026-06-30; el holdout H1 (`2026-07-01`→`2026-10-30`, 85 sesiones) sigue sellado y no ejecutado.
- **No hay P&L de broker:** la instancia está en `paper` y el motor está detenido.

### 2.5 Runtime vs backtest controlado: no son la misma cifra

| Fuente | Ops | Neto | PF | DD | Fees | Uso |
|---|---:|---:|---:|---:|---:|---|
| Runtime paper (`/api/stats`, DB) | 72 | **+2.269,38** | 1,23 | 3.099,36 | 357,12 | Fotografía del proceso; no forward |
| W1–W6 controlado (viva) | 72 | **+2.022,94** | 1,22 | 2.891,66 | 333,56 | Comparación homogénea |
| W1–W6 controlado (original) | 38 | **+661,44** | 1,13 | 1.967,82 | 178,56 | Referencia |

La diferencia runtime − controlado es **+246,44 USD** de neto, **+207,70 USD** de DD y **+23,56 USD** de fees. No se reconstruyó trade a trade; es una diferencia de contabilidad/ejecución del replay y queda abierta. Por eso **no se compara el runtime directamente con la original**: el delta bruto +1.607,94 USD sería una comparación no homogénea. El veredicto usa solo las dos patas controladas.

## 3. Discrepancias, trampas de lectura y estado abierto

No se encontró un bug de configuración ni una divergencia entre la API y los archivos vivos. Sí hay puntos que deben documentarse para no leer mal las cifras:

| Punto | Hecho | Impacto |
|---|---|---|
| Motor detenido | `/api/status=stopped`, `blocked_reason=Motor detenido`, sin posición; el proceso HTTP sigue vivo | No hay P&L nuevo; no confundir "puerto arriba" con "bot operando" |
| Runtime vs backtest | 72 ops en ambos, pero +2.269,38 vs +2.022,94; DD 3.099,36 vs 2.891,66 | No mezclar; el runtime no es la muestra W1–W6 |
| `defaults` en `/api/config` | La API puede exponer defaults `5/200/150/12`; los valores activos están en `settings` | Leer `settings`, no `defaults` |
| Original no materializada | `profiles/backtest_real/config.json` no contiene literalmente 150/12; el original se fija con `ORIGINAL_FREQUENCY_PATCH` en memoria | Reproducir la original exige el parche; no editar el archivo vivo |
| Hash de archivo vs canónico | `9bf4…` (bytes) ≠ `d3cf…` (trading canónico) | Es por diseño; no es una discrepancia |
| Perfil no visible en PID | `YED_PROFILE_DIR` no aparece en `CommandLine` | La identificación se apoya en la API y en la coincidencia byte a byte |
| Puente de señales | Los "solo-viva" y "solo-original" no son aditivos entre sí | Cada pata reconcilia con su total; no sumar ambos lados |
| `engine` en `/api/status` | En estado detenido puede venir `null` | Usar `status` y `risk.blocked_reason`, no asumir `running` |

**No se corrigió nada en caliente.** Cualquier cambio de código o de configuración queda fuera de este cierre y requiere el protocolo de §5.

## 4. Qué se puede afirmar y qué no

**Afirmable con la evidencia actual:**

- La configuración efectiva es la manual `10/300/210/24`, filtro 0,00, paper, sin broker.
- En W1–W6, la manual tuvo más neto, PF, expectancy y RDD que la original.
- El drawdown absoluto y la racha perdedora empeoraron.
- El stop 300 es un lastre medido frente a SL 200 en esa muestra.
- La ventaja agregada depende de más señales y más contratos; en las señales comunes la manual rinde menos.

**No afirmable:**

- Que la manual sea más rentable hacia adelante.
- Que sea una estrategia rentable con dinero real.
- Que el resultado se sostenga en 2026 o en un régimen distinto.
- Que el runtime de +2.269,38 sea una validación forward o una cifra de broker.
- Que las mejoras de §5 estén listas para producción.

## 5. Mejoras priorizadas por rentabilidad

**Criterio:** la tabla está ordenada por **Δneto histórico medido frente a la viva** en W1–W6. La columna de credibilidad corrige ese orden para la acción: un Δneto grande con 17 operaciones y gates fallidos no es una mejora adoptable. Ninguna propuesta se aplica al 8765 en este cierre.

| # | Cambio propuesto | Δ neto vs viva | Δ DD | Ops | PF | Credibilidad / estado | Decisión |
|---:|---|---:|---:|---:|---:|---|---|
| 1 | P2 + `risk.min_stop_or_ratio=0,25` (`10/200/210/24` + filtro) | **+2.179,26** | −1.945,28 | 17 | 4,25 | Muy baja: 4/6 trimestres, 0 en 2026, top-2 85,28 %, gates `INCONCLUSO`, P6 `NO_EVALUABLE` | **No promover**; solo lock separado si se reabre |
| 2 | `risk.entry_exclusion_start=11:30`, `entry_exclusion_end=13:30` | **+1.180,88** | −1.515,12 | 36 | 1,90 | Baja-media: 4/4 ventanas vecinas mejoran, pero top-5 = 104,6 % del neto; reprecio exacto ya verificado | **Validar en shadow**; no aplicar al 8765 |
| 3 | Exclusión 11:30–13:30 + `max_sl_ticks=200` | **+782,58** | −2.077,80 | 17 | 2,74 | Muy baja: 17 operaciones; sin reprecio exacto dedicado | **No promover**; solo ampliar muestra |
| 4 | `risk.max_sl_ticks=300→200` (M-SL200/P2) | **+448,84** | −587,20 | 46 | 1,39 | Media: 46 ops, lastre de 26 stops >200; DD 2.304,46 > 2.000 y sin forward | **Primera a validar**; no aplicar aún |
| 5 | `risk.max_contracts=10→5` (P1) | −30,68 | −943,84 | 46 | 1,37 | Media; reduce riesgo, no aumenta neto | Alternativa de riesgo, no de rentabilidad |

Fuentes: fila 1 `_manual_filter025_w1_w6.json` / `filter025_gates.json`; filas 2 y 3 `reports/autoloop/resultados.jsonl`, `reports/autoloop/resumen.md` y `reports/autoloop/reprecio_excl_1130_1330.jsonl`; fila 4 `p2_w1_w6_confirm.json`; fila 5 `live_vs_original_mission.json`. Los costes base son 0,62/lado y 1 tick/lado; la fila 1 no tiene P6 exacto y la 3 no tiene un reprecio exacto dedicado, por lo que sus Δneto no son una promesa después de costes.

**Reprecio exacto:** `excl_1130_1330` fue re-ejecutado con la configuración exacta de `data/config.json` y dio 36 ops, +3.203,82, PF 1,90, DD 1.376,54 y RDD 2,3274; Δ vs viva +1.180,88 y −1.515,12 (fuente: `reports/autoloop/reprecio_excl_1130_1330.jsonl`, SHA-256 `10a29e24…df6c0`). No es un backtest forward.

### 5.1 Prioridad práctica: qué probar primero

**1. M-SL200 — `risk.max_sl_ticks: 300 → 200`.**

**Por qué:** es el cambio más simple, conserva 46 operaciones y ataca el cohorte de 26 stops profundos que pierde −392,60 USD. Δneto +448,84 y ΔDD −587,20; PF 1,39.

**Riesgo:** recorta 26 señales, baja el acierto de 36,11 % a 32,61 %, el DD 2.304,46 sigue por encima de 2.000 y el resultado es in-sample. Un stop más ajustado puede sacar al mercado antes de que el precio se recupere.

**Validación fuera del 8765:** `python research/verify_variant.py --id sl_200` (re-ejecuta W1–W6 en un proceso aparte y no toca el 8765). Después, un perfil clonado en un puerto separado (por ejemplo 8766) con DB propia, en paper/shadow, y un lock forward con gates de DD y coste. No copiar la DB viva.

**2. Exclusión 11:30–13:30 — el mayor Δneto con evidencia algo más que anecdótica.**

**Por qué:** +1.180,88 de neto y −1.515,12 de DD; PF 1,90; 4/4 ventanas vecinas mejoran y el reprecio exacto reproduce 36 ops / 3.203,82.

**Riesgo:** el top-5 explica 104,6 % del neto; sin esas cinco operaciones el resultado es −146,74; W5 no opera y la ventana horaria es una elección in-sample. Es un edge de pocos eventos, no una ventaja frecuente.

**Validación:** `python research/verify_variant.py --id excl_1130_1330`; después shadow con perfil y DB separadas y un pre-registro que exija concentración, cobertura de 2026 y coste exacto. No aplicar al 8765.

**3. Exclusión + SL200 — no promover todavía.**

**Por qué:** +782,58 y DD 813,86 son atractivos, pero solo 17 operaciones. La combinación de dos decisiones in-sample multiplica el riesgo de sobreajuste.

**Validación:** solo después de ampliar la muestra; `python research/verify_variant.py --id excl_1130_1330+sl_200` y un forward propio. No usarla para rescatar M-SL200.

**4. Filtro 0,25 sobre P2 — el número más alto, la menor credibilidad.**

**Por qué no:** +2.179,26 nominal, pero 17 ops, 4/6 trimestres activos, cero en 2026, top-2 85,28 %, gates `INCONCLUSO` y P6 `NO_EVALUABLE`. El PF 4,25 no es una expectativa forward.

**Validación:** solo con un lock nuevo, reprecio exacto y gates completos; no se reabre en este cierre ni se toca el 8765.

### 5.2 Lo que no se propone

- **Subir por encima de 10 contratos:** el salto 5→10 ya añadió +479,52 de neto y +356,64 de DD; es apalancamiento, no edge. No hay artefacto para >10.
- **Cambiar TP 3R, ORB o SMT sin estudio:** no hay una comparación W1–W6 que aísle esos cambios.
- **Activar LIVE o `live_enabled`:** no hay forward, ni broker, ni costes exactos; la instancia debe seguir en paper.
- **Cambiar el 8765 ahora:** el motor está detenido y cualquier cambio invalidaría la comparación y el hash verificado.

### 5.3 Protocolo de validación sin tocar el 8765

1. Ejecutar la variante en un proceso de backtest/`verify_variant` que lea `data/bars.csv` y escriba solo en `reports/`, nunca en `data/config.json`, `profiles/live_8765/` ni la DB viva.
2. Para shadow, usar un **perfil clonado** y un **puerto distinto** (por ejemplo 8766) con DB separada; no reutilizar el puerto 8765 ni la DB `profiles/live_8765/yedbot.db`.
3. Fijar el lock antes de mirar resultados: configuración, dataset, costes, gates de DD/PF/concentración, periodo y regla de parada.
4. Repreciar con comisión y slippage exactos (0,62/lado y 1 tick/lado) y, además, el estrés 1,24/lado y 2 ticks/lado.
5. No promover ninguna variante con menos de 60 operaciones o sin periodo prospectivo; el holdout sigue sellado.

## 6. Verificación de integridad de esta pasada

| Comprobación | Inicio | Cierre |
|---|---|---|
| PID que escucha | **15108** | **15108** |
| `data/config.json` SHA-256 | `9bf4f9c7…e29479f` | `9bf4f9c7…e29479f` |
| `profiles/live_8765/config.json` SHA-256 | `9bf4f9c7…e29479f` | `9bf4f9c7…e29479f` |
| Canónico de trading | `d3cff10d…6dcd10` | `d3cff10d…6dcd10` |
| HTTP `/api/health` | 200 | 200 |
| Motor | `stopped` | `stopped` |
| Posición | `null` | `null` |
| DB SHA-256 | `d99f115d…01fce` | `d99f115d…01fce` |

No se escribió en la DB del 8765 (solo `mode=ro`), no se modificó la configuración, no se reinició el proceso y no se leyó el holdout. El único cambio de repositorio de esta misión es este documento y su enlace en el README.

## 7. Fuentes y reproducción

| Fuente | Uso |
|---|---|
| `profiles/live_8765/config.json`, `data/config.json` | Configuración efectiva; hashes y diff |
| `GET /api/health`, `/api/status`, `/api/config`, `/api/stats` | Estado del proceso, configuración de la API y P&L paper actual |
| `profiles/live_8765/yedbot.db` (read-only) | 72 trades, periodo, suma de P&L, fees y eventos |
| `reports/backtest/live_vs_original_mission.json` | Agregados, atribución, señales comunes, bootstrap y veredicto W1–W6 |
| `reports/autoloop/resultados.jsonl#manual_base` | Fila control de la viva (72 ops, 2.022,94, DD 2.891,66) |
| `reports/autoloop/resultados_original.jsonl#original_5_200_150_12` | Fila original (38 ops, 661,44, DD 1.967,82) |
| `reports/autoloop/reprecio_excl_1130_1330.jsonl` | Reprecio exacto del candidato de exclusión |
| `reports/autoloop/resumen.md` / `resumen.json` | Ranking y concentración; sección 3.1 de reprecio |
| `reports/backtest/p2_w1_w6_confirm.json` | P2 46 ops, 2.471,78, PF 1,39, DD 2.304,46 |
| `reports/backtest/_manual_filter025_w1_w6.json`, `filter025_gates.json` | Filtro 17 ops y gates `INCONCLUSO` |
| `reports/backtest/_manual_common.py` | `ORIGINAL_FREQUENCY_PATCH` 150/12 |
| `docs/protocolo_backtest.lock.json` | Baseline original y holdout sellado |
| `reports/backtest/MANUAL_8765_DECISION_MEMO.md`, `DECISION_CONFIG_MANUAL_8765_VS_ORIGINAL.md` | Decisiones previas y antecedentes |

Comandos de lectura usados:

```bash
sha256sum data/config.json profiles/live_8765/config.json profiles/live_8765/yedbot.db data/bars.csv
curl -sS http://127.0.0.1:8765/api/health
curl -sS http://127.0.0.1:8765/api/status
curl -sS http://127.0.0.1:8765/api/config
curl -sS http://127.0.0.1:8765/api/stats
python - <<'PY'
import sqlite3
c = sqlite3.connect("file:profiles/live_8765/yedbot.db?mode=ro", uri=True)
print(c.execute("select count(*), round(sum(pnl),2), round(sum(fees),2) from trades").fetchone())
PY
```

**Limitación final:** las cifras históricas no son una garantía de rentabilidad futura. El holdout sigue sellado, no hay forward y el proceso está en paper. Cualquier promoción requiere el protocolo de §5.
