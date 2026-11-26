# Cierre de misión — 8765: configuración servida vs original

**Fecha:** 2026-11-26 (America/Mexico_City)  
**Periodo:** W1–W6, 2025-01-10 → 2026-06-30, 362 sesiones, capital inicial 25.000 USD.  
**Holdout:** 2026-07-01 → 2026-10-30 **no usado**.  
**Naturaleza:** análisis de solo lectura sobre el 8765; sin reinicio, sin escritura de configuración, sin reejecutar el reprecio. El único commit es el final, limitado a este informe, al runner R3 y a su salida.

> **Hallazgo de vigencia:** el 8765 **no** sirve la config `9bf4…` que comparó el informe previo. Sirve `profiles/live_8765/config.json` con hash **`1b98…`**: `8/300/210/24`, TP 2,0, `or_retracement` + `touch` y fill `signal_price`. `data/config.json` sigue siendo `9bf4…` (10/300) y es el snapshot histórico de S1, no la config actual. El perfil fue modificado externamente a las **18:37:37 -0600** del 25/11, 23 minutos después de S1; este análisis no lo escribió ni lo restauró.

---

## Entregable central — estado vivo, comparación y veredicto (R3, 2026-11-26)

Esta sección es la respuesta central y se apoya en una corrida nueva (**R3**) que releyó el proceso vivo, congeló el perfil servido y backtesteó las cuatro variantes en las mismas seis ventanas y el mismo `bars.csv` que la referencia. Las secciones siguientes conservan el análisis de soporte (R1/R2/S1); cuando hay una cifra nueva, esta sección manda.

### E1. Proceso y configuración efectiva del 8765

| Elemento | Valor observado | Evidencia |
|---|---|---|
| Proceso | **PID 16016**, `127.0.0.1:8765` **LISTENING**, `status=running` | `netstat -ano` + API; sin reinicio |
| Comando | `python.exe -m uvicorn server.main:app --host 127.0.0.1 --port 8765 --log-level info` | `Win32_Process` |
| Perfil servido | `profiles/live_8765/config.json`; SHA-256 **`1b981d247b6ca6e828a73782ce016fcfd78a4332bcc932b89e5a17c7d945f81c`** | El proceso no recibe `--profile`; la API coincide con este perfil y la DB viva está en `profiles/live_8765/yedbot.db` |
| API `/api/config` | `logs/8765_config_live_20261126.json`; SHA-256 **`ca7629296abf3ee42a18af64d36103d21e8be2178d3c1a1808ce0199df68c6a3`** | Valores efectivos (`settings`), no `defaults` |
| API `/api/status` | `logs/8765_status_live_20261126.json`; SHA-256 **`48dae518757c2081e9b646a5fbf4cf9e192dea98cb42045e3d3e636172b5ea3f`** | Estado de cuenta y sesión |
| API `/api/stats` | `logs/8765_stats_live_20261126.json`; SHA-256 **`9f13c75760e80d4d2243a32feb850c0c1c3abdfe481e813b9394e9c0de9692b7`** | Métricas de la cuenta paper |
| Modo | **paper**, `live_enabled=false`; no es una cuenta brokerage | `/api/config` y `/api/status` |
| `data/config.json` | SHA-256 **`9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f`** | Snapshot antiguo; **no** es la config servida |

Parámetros efectivos relevantes (todos leídos de `settings`):

| Bloque | Valor efectivo |
|---|---|
| Mercado / referencias | **MNQ**, referencia **NQ**, comparación **ES**; `mode=paper`; `live_enabled=false` |
| Datos / timeframe | `data/bars.csv`; señal **1m**; confirmación **15m**; ORB **09:00–10:00 NY**; ancho ORB máx. **1,2 %**; replay **8×** |
| Filtros | **SMT activo** (pivote 5, ventana 60, tolerancia 8, ruptura mín. 2, validez 120 min, 1m, recuperación requerida); `min_range_ticks=10`; `min_stop_or_ratio=0`; `require_close_breakout=true`; `require_recovery_close=true`; `allow_reentry_after_false_breakout=false` |
| Entrada | `entry_reference=or_retracement`; `entry_trigger=touch`; `setup_validity_minutes=210`; `retest_tolerance_ticks=24`; `tp_rr=2,0` |
| Riesgo / sizing | **1 %** por trade; **3 %** pérdida diaria; **0** objetivo diario; **3** trades/día; **1** concurrente; **8** contratos máx.; **300** ticks SL máx.; ventana **09:00–15:30**; cierre **15:55**; cooldown **5** min |
| Ejecución | Tick **0,25**; tick value **0,50**; point value **2,00**; slippage **1 tick**; comisión **0,62/lado**; fill **`signal_price`**; `simulate_partial_fills=false`; max slip **4 ticks** |
| Cuenta | Capital inicial **25.000**; equity **26.902,18**; **12** trades; neto **+1.902,18**; DD **438,96** (**1,686 %**); sin posición; `trades_today=0`; `daily_pnl=0` |

**Lectura de la cuenta:** el estado observado es un **paper parcial** con `session_date=2025-02-28`, no la curva W1–W6. Sirve para acreditar que el proceso está vivo y qué cuenta usa, **no** para comparar equity contra el backtest de 362 sesiones.

### E2. Protocolo: mismas ventanas y mismo dataset

- **Ventanas:** W1–W6 de `reports/backtest/_windows.py`; 362 sesiones; `2025-01-10 09:00` → `2026-06-30 15:59`; capital inicial **25.000**.
- **Dataset:** `data/bars.csv`; SHA-256 **`1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a`**.
- **Referencia:** `reports/autoloop/resultados_original.jsonl`; SHA-256 antes/después **`bee126582f5ec13c2dd8f014dca275408676195bcbf873ee9cb05ab436029214`**; fila `original_5_200_150_12`; **no reescrita**.
- **Variantes R3:** `original` (5/200/150/12, TP 3, `or_mid`/`close`, `next_open`); `manual_live` (perfil vivo, `signal_price`); `manual_next_open` (misma config, solo fill `next_open`); `p1_5_200_210_24` (P1, `next_open`).
- **Holdout:** **no usado** (`holdout_used=false`).
- **Fidelidad:** `signal_price` sí es expresable y se corrió. No son parámetros económicos del harness `mode=paper`, `feed.replay_speed=8` ni `loop_sessions`; `replay_speed` no cambia la secuencia (S1: 8× vs 1×, Δneto 0). `simulate_partial_fills=false`, así que no hay fills parciales que modelar. La cuenta/equity paper no forma parte del backtest; se reporta aparte.

### E3. Comprobación de la original fija

| Métrica | Fijada en `resultados_original.jsonl` | R3 observada | ¿Cuadra? |
|---|---:|---:|---|
| Trades | 38 | **38** | Sí |
| P&L neto | +661,44 | **+661,44** | Sí |
| DD máximo | 1.967,82 | **1.967,82** | Sí |
| Profit factor | 1,13 | **1,13** | Sí |

R3 también reprodujo los valores **por ventana** de la original; el runner falla si el agregado o alguna ventana no coincide (`matched_by_harness=true`).

### E4. Tabla por ventana: original vs manual

Retorno* = `neto / 25.000 × 100`; es contribución sobre capital inicial, no compuesto. El DD es el máximo de la curva de equity; el PF de la original en W4 es `∞` porque no tuvo pérdidas, y el de W5 es `0,00` porque no tuvo ganancias.

| Variante | Ventana | Trades | P&L neto | DD | PF | Retorno* |
|---|---:|---:|---:|---:|---:|---:|
| Original | W1 | 8 | 364,82 | 619,42 | 1,35 | 1,4593% |
| Manual viva | W1 | 19 | 1.486,16 | 940,38 | 1,64 | 5,9446% |
| Manual next_open | W1 | 19 | 359,88 | 1.391,80 | 1,13 | 1,4395% |
| Original | W2 | 4 | 268,40 | 378,88 | 1,71 | 1,0736% |
| Manual viva | W2 | 8 | 291,98 | 563,06 | 1,30 | 1,1679% |
| Manual next_open | W2 | 8 | 71,48 | 673,56 | 1,07 | 0,2859% |
| Original | W3 | 9 | -110,46 | 1.084,80 | 0,92 | -0,4418% |
| Manual viva | W3 | 18 | -166,72 | 1.330,82 | 0,93 | -0,6669% |
| Manual next_open | W3 | 18 | -883,72 | 1.816,06 | 0,65 | -3,5349% |
| Original | W4 | 4 | 2.034,12 | 0,00 | ∞ | 8,1365% |
| Manual viva | W4 | 10 | 2.687,98 | 0,96 | 2.800,98 | 10,7519% |
| Manual next_open | W4 | 10 | 2.601,98 | 120,96 | 22,51 | 10,4079% |
| Original | W5 | 5 | -1.036,52 | 1.036,52 | 0,00 | -4,1461% |
| Manual viva | W5 | 5 | -389,56 | 696,62 | 0,53 | -1,5582% |
| Manual next_open | W5 | 5 | -376,06 | 515,62 | 0,43 | -1,5042% |
| Original | W6 | 8 | -858,92 | 931,30 | 0,27 | -3,4357% |
| Manual viva | W6 | 12 | 640,82 | 557,86 | 1,48 | 2,5633% |
| Manual next_open | W6 | 12 | -291,94 | 787,36 | 0,82 | -1,1678% |
| **Original** | **Total** | **38** | **661,44** | **1.967,82** | **1,13** | **2,6458%** |
| **Manual viva** | **Total** | **72** | **4.550,66** | **1.330,82** | **1,58** | **18,2026%** |
| **Manual next_open** | **Total** | **72** | **1.481,62** | **2.054,46** | **1,17** | **5,9265%** |

### E5. Agregados y veredicto

| Variante | Trades | P&L neto | DD | DD % | PF | Retorno* | Fees | Win rate |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Original | 38 | 661,44 | 1.967,82 | 7,14% | 1,13 | 2,6458% | 178,56 | 31,58% |
| Manual viva | 72 | **4.550,66** | **1.330,82** | **4,80%** | **1,58** | **18,2026%** | 267,84 | 47,22% |
| Manual next_open | 72 | **1.481,62** | **2.054,46** | **7,78%** | **1,17** | **5,9265%** | 262,88 | 47,22% |
| P1 5/200/210/24 | 46 | **1.992,26** | **1.947,82** | **6,75%** | **1,37** | **7,9690%** | 218,24 | 32,61% |

**Veredicto explícito:** la config manual **no demuestra una mejora robusta de rentabilidad** respecto a la original.

1. **Tal como se sirve (`signal_price`)**: +4.550,66 vs +661,44 y DD 1.330,82 vs 1.967,82. Parece mejor, pero **no es una comparación limpia**: cambia el fill y ocho parámetros económicos a la vez, y el 79 % del delta aparente (3.069,04 / 3.889,22) es solo el fill. No es evidencia forward.
2. **Con `next_open`, el mismo supuesto que la original**: +1.481,62 vs +661,44 (**+820,18**), pero **DD 2.054,46 vs 1.967,82 (+86,64 peor)**, PF **1,17 vs 1,13** y p **0,501** en el bootstrap de R2-S (IC95 % [−1.865,60; +3.018,68]; no recalculado en R3, pero los deltas por ventana son idénticos). **Sube el neto, empeora el riesgo y no es significativo.**
3. **Frente a P1 con el mismo fill**: P1 gana **+510,64** de neto y mejora **−106,64** de DD; además supera a la original en **+1.330,82** de neto y **−20,00** de DD. P1 es la mejor variante medida, pero sigue siendo **in-sample**.

**Por qué falla la lectura optimista:** las 32 señales comunes pierden **−1.765,96** frente a la original con `signal_price`; la ventaja viene de **40 señales solo-actuales** (+4.297,44), es decir, cobertura de señales, no mejor ejecución. El TP 2,0 sube el win rate (47,22 % vs 31,58 %) pero baja el avg win; los 8 contratos y el stop 300 elevan el DD. El puente equivalente con `next_open` no se guardó, así que no se puede afirmar que esas 40 señales sigan aportando con el fill comparable.

### E6. P1 reejecutada: la única mejora validada en esta corrida

P1 se reconstruyó desde el perfil original y el patch canónico `setup_validity=210`, `retest_tolerance=24`; se ejecutó en R3 con el mismo dataset, las mismas ventanas y `next_open`. **Sí está respaldada por un backtest ejecutado hoy**, no solo por S1.

| P1 | Trades | P&L neto | DD | PF | Retorno* |
|---|---:|---:|---:|---:|---:|
| W1 | 14 | 1.700,06 | 602,86 | 2,41 | 6,8002% |
| W2 | 5 | 445,44 | 465,64 | 1,96 | 1,7818% |
| W3 | 11 | -238,40 | 1.248,74 | 0,84 | -0,9536% |
| W4 | 3 | 1.960,60 | 0,00 | ∞ | 7,8424% |
| W5 | 6 | -1.240,22 | 1.240,22 | 0,00 | -4,9609% |
| W6 | 7 | -635,22 | 707,60 | 0,33 | -2,5409% |
| **Total** | **46** | **1.992,26** | **1.947,82** | **1,37** | **7,9690%** |

P1 no es transversal: gana en W1/W2/W4 y pierde en W3/W5/W6. Su ventaja agregada es real en la muestra, pero **no es un edge validado fuera de muestra**; 46 trades y selección sobre W1–W6 son el límite principal.

### E7. Mejoras priorizadas por impacto en rentabilidad

La tabla completa con rationale, riesgo/efecto secundario y plan de validación está en **§5**. Este es el orden de decisión y el marcado de validación:

| Prioridad | Cambio | Impacto observado / esperado | ¿Validada con backtest ejecutado? |
|---:|---|---|---|
| **1** | **P1**: `8→5` contratos, `300→200` SL, `TP 2→3`, entrada `or_retracement/touch→or_mid/close`; mantener `210/24` y `next_open` | **+510,64** neto y **−106,64** DD vs la manual con el mismo fill; **+1.330,82** y **−20,00** vs original | **Sí — R3, W1–W6, 2026-11-26**; in-sample; forward pendiente |
| **2** | `max_sl_ticks 300→200` sobre la manual, dejando lo demás igual | S1 histórico: **+448,84** neto y **−587,20** DD al bajar 300→200 en la antigua viva; no medido en la actual | **No en esta corrida**; evidencia histórica de otra config |
| **3** | `tp_rr 2,0→3,0` sobre la manual, con entrada/sizing fijos | Esperado subir avg win/neto; P1 lo incluye, pero confundido con entrada/sizing | **No aislada en esta corrida**; P1 validada como bundle |
| **4** | Revertir entrada a `or_mid` + `close` | P1/P2 usan la entrada original; la manual genera 72 trades y 40 solo-actuales | **No aislada en esta corrida**; P1 validada como bundle |
| **5** | `max_contracts 8→5` | Menos neto y menos DD; es apalancamiento, no fuente de edge | **No en esta corrida**; P1 validada como bundle |
| **6** | `min_stop_or_ratio 0→0,25` | S1 P2: +1.730,42 neto / −1.358,08 DD, pero 17 trades; **no adoptable** | **No**; muy sobreajustada y de config antigua |

**Marcado:** solo **P1** está respaldada por un backtest ejecutado en esta corrida. Las propuestas 2–5 son mecanismos plausibles, pero **no están aisladas en la config actual**; la 6 no se recomienda. No se toca el holdout 2026-07-01 → 2026-10-30.

### E8. Reproducibilidad e integridad de R3

- **Runner:** `reports/autoloop/run_live_manual_vs_original.py`; SHA-256 **`2032aca4d56710a5b25e01d211a1924e4a16a0d44984248880c1ab8455ccd936`**.
- **Salida:** `reports/autoloop/live_manual_vs_original_20261126.json`; SHA-256 **`41012333ab9beac69f515f52b66e7e4d9ab4d8fd05861fa5a508771b82efa340`**; 492,2 s.
- **Snapshot usado:** `logs/live_manual_profile_1b981d247b6c.json`; SHA-256 **`1b981d247b6ca6e828a73782ce016fcfd78a4332bcc932b89e5a17c7d945f81c`**; el runner verifica que el perfil no cambió antes/después.
- **Constraints de R3:** `config_written=false`, `db_written=false`, `holdout_accessed=false`, `original_results_written=false`, `process_touched=false`, `reprice_rerun=false`, `tracked_artifacts_written=false`.
- **Proceso:** PID 16016 sigue escuchando; no se reinició. `resultados_original.jsonl` conserva `bee12658…`; `data/config.json` conserva `9bf4…`; el perfil vivo conserva `1b98…`.
- La corrida se hizo en background por el límite de 295 s del terminal; el log completo está en `logs/live_manual_vs_original_run.log` (SHA-256 `9fe3e6d882b70433edcb3c9f3957b2290d0a0f05750ad622da9cc615d7e2dac8`).

---

## Resumen ejecutivo

| Caso | Neto | DD máx. | PF | Win rate | Trades | p (bloques) | Lectura |
|---|---:|---:|---:|---:|---:|---:|---|
| Original `5/200/150/12`, TP 3, `or_mid`/`close`, `next_open` | **+661,44** | **1.967,82** | 1,13 | 31,58 % | 38 | — | Base |
| Actual **tal como se sirve**, `signal_price` | **+4.550,66** | **1.330,82** | 1,58 | 47,22 % | 72 | 0,0022 | Mejor en muestra, pero no comparable |
| Actual con **`next_open`** (mismo fill que la original) | **+1.481,62** | **2.054,46** | 1,17 | 47,22 % | 72 | 0,501 | +820,18 neto, pero **peor DD** y no significativo |
| P1 reejecutada `5/200/210/24`, TP 3, `or_mid`/`close`, `next_open` | **+1.992,26** | **1.947,82** | 1,37 | 32,61 % | 46 | — | Mejor que la actual con el mismo fill; **validada en R3** |

- El cambio de fill `signal_price` frente a `next_open` aporta **+3.069,04 USD** de neto y **−723,64 USD** de DD. Es el **79 %** del +3.889,22 aparente frente a la original.
- Con el mismo fill que la original, la actual gana **+820,18 USD** (+124,00 %), pero el DD **empeora +86,64 USD** y el intervalo de confianza del delta incluye cero: **p = 0,501**, IC95 % **[−1.865,60; +3.018,68]**.
- **Veredicto:** la config actual **mejora el PnL reportado solo bajo `signal_price`**; **no demuestra una mejora robusta de rentabilidad/riesgo**. En la comparación justa el neto sube, pero el riesgo también y la muestra no lo distingue de cero. Además, la P1 reejecutada con el mismo fill la supera en neto y DD (+510,64 y −106,64 respectivamente). No la promovería; primero hay que corregir el fill y validar P1/ablaciones fuera de la muestra.

---

## 1. Qué configuración corre y qué cambió

### 1.1 Fuente de verdad

| Elemento | Valor actual | Papel |
|---|---|---|
| `profiles/live_8765/config.json` | SHA-256 **`1b981d247b6ca6e828a73782ce016fcfd78a4332bcc932b89e5a17c7d945f81c`**; mtime local `2026-11-25 18:37:37 -0600` | Config **servida** por el 8765 |
| `logs/current_profile_20261126.json` | SHA-256 **`1b98…f81c`** | Copia exacta usada por las corridas R1/R2 |
| `data/config.json` | SHA-256 **`9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f`** | Snapshot histórico S1; **no** es la config servida |
| `GET /api/config` | Guardado en `logs/8765_api_config_20261126.json`; SHA-256 **`ca7629296abf3ee42a18af64d36103d21e8be2178d3c1a1808ce0199df68c6a3`** | Confirma los valores que sirve el proceso |
| Proceso 8765 | PID **16016**, escuchando en `127.0.0.1:8765`, `status=running` | Sin reinicio; solo lecturas |

`/api/config` devolvió, entre otros: `max_contracts=8`, `max_sl_ticks=300`, `setup_validity_minutes=210`, `retest_tolerance_ticks=24`, `tp_rr=2.0`, `entry_reference=or_retracement`, `entry_trigger=touch`, `fill_model=signal_price`, `replay_speed=8.0`.

### 1.2 Por qué el informe anterior quedó desfasado

S1 se generó a las **18:14:49 -0600** con `data/config.json = 9bf4…` (10/300/210/24, TP 3, `or_mid`/`close`, `next_open`). A las **18:37:37** el perfil servido ya era `1b98…` (8/300, TP 2, `or_retracement`/`touch`, `signal_price`). Por eso:

- **S1 no es una comparación de la config actual**; es un snapshot histórico de `9bf4` y se usa aquí solo como evidencia histórica de P1/P2/stop, nunca como cifra actual.
- La afirmación anterior de que `data/config.json` y el perfil eran idénticos ya **no es cierta**.
- El perfil está marcado `M` en git por ese cambio externo. **No escribí ese archivo**; R1/R2 verifican el mismo hash `1b98…` antes y después. No lo restauré para no intervenir un proceso vivo.

---

## 2. Diferencias de parámetros: actual vs original

Hay **9 diferencias**, de las cuales **8 son económicas**; `replay_speed` es operativa y no altera la secuencia (S1 lo comprobó: 8× vs 1×, secuencia idéntica, Δneto 0).

| Parámetro | Original establecida | Actual servida | Tipo |
|---|---:|---:|---|
| `risk.max_contracts` | 5 | **8** | Tamaño |
| `risk.max_sl_ticks` | 200 | **300** | Stop |
| `strategy.setup_validity_minutes` | 150 | **210** | Frecuencia |
| `strategy.retest_tolerance_ticks` | 12 | **24** | Frecuencia |
| `strategy.tp_rr` | 3,0 | **2,0** | Objetivo |
| `strategy.entry_reference` | `or_mid` | **`or_retracement`** | Entrada |
| `strategy.entry_trigger` | `close` | **`touch`** | Entrada |
| `execution.fill_model` | `next_open` | **`signal_price`** | Supuesto de fill |
| `feed.replay_speed` | 4,5 | **8,0** | No económica |

La config actual es, por tanto, **una variante más agresiva en tamaño y stop**, **más frecuente** en validez/retest, **con TP más corto** y **entrada más anticipada**, y además **se mide con un fill más favorable**. Esa combinación es la que hay que separar: no es una sola mejora de estrategia.

---

## 3. Rentabilidad en las mismas ventanas

### 3.1 Actual tal como se sirve (`signal_price`) vs original

Fuente: R1 (`logs/current_vs_original_20261126.json`). Definiciones: neto = PnL bruto − fees; el slippage modelado ya está incorporado en el PnL bruto; DD en USD sobre la curva de equity; turnover y exposición son derivados de los trades, no métricas nativas de `server/stats.py`.

| Métrica | Original | Actual servida | Δ actual−original | Rel. |
|---|---:|---:|---:|---:|
| **PnL neto (USD)** | **661,44** | **4.550,66** | **+3.889,22** | **+587,99 %** |
| PnL bruto (USD) | 840,00 | 4.818,50 | +3.978,50 | +473,63 % |
| Fees (USD) | 178,56 | 267,84 | +89,28 | +50,00 % |
| Slippage modelado (USD) | 135,50 | 208,00 | +72,50 | +53,51 % |
| Trades | 38 | 72 | +34 | +89,47 % |
| Win rate | 31,58 % | 47,22 % | +15,64 pp | — |
| Profit factor | 1,13 | 1,58 | +0,45 | +39,82 % |
| Expectancy (USD/trade) | 17,41 | 63,20 | +45,79 | +263,01 % |
| Avg win (USD) | 470,14 | 364,71 | −105,43 | −22,43 % |
| Avg loss (USD) | −191,55 | −206,57 | −15,02 | −7,84 % |
| **Máx. drawdown (USD)** | **1.967,82** | **1.330,82** | **−637,00** | **−32,37 %** |
| Máx. drawdown (%) | 7,141 % | 4,799 % | −2,342 pp | −32,80 % |
| RDD (neto/DD) | 0,336 | 3,419 | +3,083 | — |
| Contratos (suma) | 144 | 216 | +72 | +50,00 % |
| Turnover nocional (USD) | 14.482.932,00 | 21.463.016,50 | +6.980.084,50 | +48,20 % |
| Exposición media por entrada (USD) | 190.564,32 | 149.039,11 | −41.525,21 | −21,79 % |
| Exposición máxima por entrada (USD) | 305.597,50 | 402.396,00 | +96.798,50 | +31,68 % |
| Riesgo medio por trade (USD) | 212,29 | 207,75 | −4,54 | −2,14 % |
| Riesgo máximo por trade (USD) | 878,10 | 265,56 | −612,54 | −69,76 % |
| Riesgo suma (USD) | 8.066,96 | 14.958,24 | +6.891,28 | +85,43 % |
| Duración media (s) | 4.215,8 | 5.036,7 | +820,9 | +19,47 % |
| Concurrencia máxima | 1 | 1 | 0 | — |
| Sharpe | 0,82 | 3,33 | +2,51 | +306,10 % |
| Sortino | 1,58 | 6,46 | +4,88 | +308,86 % |
| Peor racha perdedora | 10 | 6 | −4 | −40,00 % |
| Total R | 4,98 | 22,17 | +17,19 | +345,18 % |

Comprobación: `4.818,50 − 267,84 = 4.550,66`; `840,00 − 178,56 = 661,44`; `4.550,66 − 661,44 = 3.889,22`.

**Lectura:** en esta comparación la actual gana en neto, PF, win rate, DD y RDD. Pero **no es una comparación limpia**: cambia el fill y varios parámetros a la vez, y la config actual fue elegida/probada en la misma muestra. El resultado no es evidencia de una ventaja forward.

### 3.2 Actual con `next_open` (comparación justa de fill) vs original

Fuente: R2 (`logs/current_next_open_20261126.json`). Es la misma config actual, mismo snapshot `1b98…`, cambiando solo el fill a `next_open` para igualar el supuesto de la original.

| Métrica | Original | Actual `next_open` | Δ actual−original | Rel. |
|---|---:|---:|---:|---:|
| **PnL neto (USD)** | **661,44** | **1.481,62** | **+820,18** | **+124,00 %** |
| PnL bruto (USD) | 840,00 | 1.744,50 | +904,50 | +107,68 % |
| Fees (USD) | 178,56 | 262,88 | +84,32 | +47,22 % |
| Slippage modelado (USD) | 135,50 | 204,00 | +68,50 | +50,55 % |
| Trades | 38 | 72 | +34 | +89,47 % |
| Win rate | 31,58 % | 47,22 % | +15,64 pp | — |
| Profit factor | 1,13 | 1,17 | +0,04 | +3,54 % |
| Expectancy (USD/trade) | 17,41 | 20,58 | +3,17 | +18,21 % |
| Avg win (USD) | 470,14 | 301,22 | −168,92 | −35,93 % |
| Avg loss (USD) | −191,55 | −230,52 | −38,97 | −20,34 % |
| **Máx. drawdown (USD)** | **1.967,82** | **2.054,46** | **+86,64** | **+4,40 % (peor)** |
| Máx. drawdown (%) | 7,141 % | 7,784 % | +0,643 pp | +9,00 % |
| RDD (neto/DD) | 0,336 | 0,721 | +0,385 | — |
| Contratos (suma) | 144 | 212 | +68 | +47,22 % |
| Turnover nocional (USD) | 14.482.932,00 | 21.079.227,50 | +6.596.295,50 | +45,55 % |
| Exposición media por entrada (USD) | 190.564,32 | 146.381,98 | −44.182,34 | −23,19 % |
| Exposición máxima por entrada (USD) | 305.597,50 | 402.348,00 | +96.750,50 | +31,66 % |
| Riesgo medio por trade (USD) | 212,29 | 241,61 | +29,32 | +13,81 % |
| Riesgo máximo por trade (USD) | 878,10 | 656,20 | −221,90 | −25,27 % |
| Riesgo suma (USD) | 8.066,96 | 17.396,24 | +9.329,28 | +115,65 % |
| Duración media (s) | 4.215,8 | 5.036,7 | +820,9 | +19,47 % |
| Concurrencia máxima | 1 | 1 | 0 | — |
| Sharpe | 0,82 | 1,14 | +0,32 | +39,02 % |
| Sortino | 1,58 | 1,83 | +0,25 | +15,82 % |
| Peor racha perdedora | 10 | 6 | −4 | −40,00 % |
| Total R | 4,98 | 11,00 | +6,02 | +120,88 % |

Comprobación: `1.744,50 − 262,88 = 1.481,62`; `1.481,62 − 661,44 = 820,18`.

**Lectura:** con el mismo fill, la actual **sí gana más neto** (+820,18), pero **empeora el DD** (+86,64) y el PF casi no cambia (1,17 vs 1,13). La mejora de rentabilidad es modesta y no robusta; la de riesgo es negativa. El delta no es significativo: **p = 0,501**, IC95 % **[−1.865,60; +3.018,68]**, 6 bloques y 10.000 remuestreos. El bootstrap está en R2-S, con la misma semilla y método que R1; su media bootstrap es 799,53.

### 3.3 Resultado por ventana

| Ventana | Original | Actual `signal_price` | Δ signal | Actual `next_open` | Δ next |
|---|---:|---:|---:|---:|---:|
| W1 | +364,82 | +1.486,16 | **+1.121,34** | +359,88 | **−4,94** |
| W2 | +268,40 | +291,98 | **+23,58** | +71,48 | **−196,92** |
| W3 | −110,46 | −166,72 | **−56,26** | −883,72 | **−773,26** |
| W4 | +2.034,12 | +2.687,98 | **+653,86** | +2.601,98 | **+567,86** |
| W5 | −1.036,52 | −389,56 | **+646,96** | −376,06 | **+660,46** |
| W6 | −858,92 | +640,82 | **+1.499,74** | −291,94 | **+566,98** |
| **Suma** | **+661,44** | **+4.550,66** | **+3.889,22** | **+1.481,62** | **+820,18** |

La comparación justa tiene **3 ventanas negativas y 3 positivas**: W1, W2 y W3 restan; W4, W5 y W6 suman. La ganancia no es transversal. En `signal_price`, en cambio, casi todas son positivas, con W6 aportando +1.499,74; el fill vuelve a explicar buena parte del patrón.

### 3.4 Cuánto aporta el fill `signal_price`

| Concepto | `signal_price` | `next_open` | Efecto signal − next |
|---|---:|---:|---:|
| PnL neto | 4.550,66 | 1.481,62 | **+3.069,04** |
| PnL bruto | 4.818,50 | 1.744,50 | +3.074,00 |
| Fees | 267,84 | 262,88 | +4,96 |
| DD máximo | 1.330,82 | 2.054,46 | **−723,64** |
| Slippage modelado | 208,00 | 204,00 | +4,00 |
| Contratos | 216 | 212 | +4 |
| Turnover | 21.463.016,50 | 21.079.227,50 | +383.789,00 |
| Exposición media | 149.039,11 | 146.381,98 | +2.657,13 |
| Riesgo medio | 207,75 | 241,61 | −33,86 |

El fill no es un detalle: **3.069,04 de los 3.889,22** del delta aparente frente a la original son el cambio de `signal_price`; sin él, el delta cae a 820,18. Y el DD mejora 723,64 solo por el fill. Cualquier conclusión que use la config tal como se sirve está midiendo, en gran parte, un supuesto de ejecución.

### 3.5 Puente de señales con `signal_price`

| Grupo | Señales | Neto actual | Neto original | Delta |
|---|---:|---:|---:|---:|
| Comunes | 32 | 253,22 | 2.019,18 | **−1.765,96** |
| Solo actuales | 40 | 4.297,44 | — | **+4.297,44** |
| Solo originales | 6 | — | −1.357,74 | **−1.357,74** |
| **Total** | — | — | — | **+3.889,22** |

Comprobación: `−1.765,96 + 4.297,44 + 1.357,74 = 3.889,22`.

**Lectura:** en las 32 señales que ambas toman, la actual **pierde 1.765,96** frente a la original. La ventaja agregada viene de **40 señales que solo ella toma** (+4.297,44), no de ejecutar mejor las señales compartidas. Es **cobertura de señales**, no mejor ejecución. Además, ese puente es con `signal_price`; **no se guardó el puente equivalente con `next_open`**, así que no se puede afirmar que esas 40 señales sigan aportando con el fill comparable.

### 3.6 Evidencia histórica S1: la actual no es la mejor config con el mismo fill

S1 (`reports/backtest/live_vs_original_mission.json`) es el snapshot **9bf4** (10/300/210/24, TP 3, `or_mid`/`close`, `next_open`), generado antes del cambio externo. No es la config actual y **no se regeneró**; se usa solo como evidencia histórica de P1/P2/stop.

| Config (W1–W6, `next_open`) | Neto | DD máx. | PF | Win | Trades | Fees |
|---|---:|---:|---:|---:|---:|---:|
| Original 5/200/150/12, TP 3, `or_mid`/`close` | 661,44 | 1.967,82 | 1,13 | 31,58 % | 38 | 178,56 |
| **P1: 5/200/210/24, TP 3, `or_mid`/`close`** | **1.992,26** | **1.947,82** | **1,37** | 32,61 % | 46 | 218,24 |
| P2: 10/200/210/24, TP 3, `or_mid`/`close` | 2.471,78 | 2.304,46 | 1,39 | 32,61 % | 46 | 282,72 |
| Antigua viva 10/300/210/24, TP 3, `or_mid`/`close` | 2.022,94 | 2.891,66 | 1,22 | 36,11 % | 72 | 333,56 |
| **Actual 8/300/TP 2/`or_retracement`/`touch`, `next_open`** | **1.481,62** | **2.054,46** | **1,17** | 47,22 % | 72 | 262,88 |
| Actual tal como se sirve, `signal_price` | 4.550,66 | 1.330,82 | 1,58 | 47,22 % | 72 | 267,84 |

- **P1 domina a la actual con el mismo fill**: +510,64 de neto y −106,64 de DD. También domina a la original: +1.330,82 y −20,00 de DD.
- Para P1/P2/antigua viva no reporto turnover ni exposición: S1 no los derivó y no los estimo. Su slippage tampoco está desglosado; solo fees.
- **P2** gana más neto que la actual (+990,16), pero con +250,00 de DD; no la domina en riesgo.
- La actual tiene **más win rate que P1/P2** (47,22 % vs 32,61 %), pero **menos avg win** (301,22 vs 583,67 de P2) y **más DD** que P1. El TP 2,0 sube aciertos, no necesariamente expectancy.
- La actual, frente a la antigua viva 10/300, baja neto (−541,32) y baja DD (−837,20): es un **trade-off**, no una mejora dominante.
- S1 está marcado `M` en el árbol por trabajo externo; sus cifras se citan como snapshot histórico y no como estado actual.

---

## 4. Valoración: ¿mejora o empeora?

**No hay una mejora robusta demostrada.** La respuesta depende del fill:

1. **Como se sirve (`signal_price`)**: +4.550,66 vs +661,44, DD 1.330,82 vs 1.967,82. Parece mejor en todo, pero el 79 % del delta es el fill y la config se probó en la misma muestra. No es una comparación limpia.
2. **Con `next_open`, igual que la original**: +1.481,62 vs +661,44 (+820,18), pero DD 2.054,46 vs 1.967,82 (+86,64), PF 1,17 vs 1,13 y p = 0,501. **Gana neto, pierde riesgo y no es significativo.** No se sostiene como superior.
3. **Frente a la P1 reejecutada con el mismo fill**: la actual pierde 510,64 de neto y tiene 106,64 más de DD. Es decir, **ni siquiera es la mejor variante conocida con el mismo supuesto de ejecución**.

**Por qué, ligado a los parámetros:**

- **Fill `signal_price`**: aporta +3.069,04 y −723,64 de DD; es el factor dominante y no está validado con fills reales.
- **TP 2,0**: sube el win rate a 47,22 % (vs 31,58 % de la original), pero baja el avg win a 301,22 (vs 470,14) y deja el PF en 1,17 con `next_open`; no compensa el riesgo.
- **Entrada `or_retracement` + `touch`**: genera 72 trades vs 38 y 40 señales solo-actuales; el puente con `signal_price` muestra que las comunes pierden −1.765,96. La cobertura extra no equivale a mejor ejecución; con `next_open` no se midió el puente.
- **`max_contracts=8`**: sube contratos a 212 y fees a 262,88; el riesgo medio sube a 241,61 (+13,81 %) y el DD a 2.054,46. Es apalancamiento, no edge por trade (expectancy 20,58 vs 17,41; +3,17).
- **`max_sl_ticks=300`**: la evidencia S1 muestra que 300 destruye neto y DD frente a 200 (+448,84 y −587,20 al bajar a 200, en la antigua viva); la actual mantiene 300 y el DD supera a la original.
- **Frecuencia 210/24**: ya estaba en la config anterior y S1 la midió positiva frente a 150/12 (+1.330,82 y −20,00 DD); se mantiene, pero no es lo que explica la diferencia actual.
- **`replay_speed=8`**: no tiene efecto económico; S1 verificó secuencia idéntica a 1×.

**Conclusión operativa:** la config actual **no debe promoverse** con base en el +4.550,66. Si se quiere evaluar de verdad, hay que (a) medir con `next_open`, (b) comparar con P1 y (c) validar forward. El +820,18 con `next_open` es la única mejora neta defendible, y viene con peor DD y sin significación.

---

## 5. Mejoras priorizadas por rentabilidad

La prioridad es por **impacto esperado robusto**, no por el número más grande en la misma muestra. El primer punto no es una mejora de estrategia: es la condición para no engañarse con el fill.

| # | Cambio exacto | Evidencia | Impacto esperado | Riesgo de sobreajuste | Validación sin holdout |
|---:|---|---|---|---|---|
| **0** | `execution.fill_model: signal_price → next_open` (medir/operar con el fill comparable) | R1 vs R2: +3.069,04 del neto y −723,64 del DD son fill; P1 y original usan `next_open` | **No es ganancia**: reduce el neto reportado de 4.550,66 a 1.481,62 y sube el DD a 2.054,46. Es la cifra honesta | Ninguno; no es selección | Misma W1–W6 y forward; no usar H1 |
| **1** | Volver a **P1**: `max_contracts 8→5`, `max_sl_ticks 300→200`, `tp_rr 2,0→3,0`, `entry_reference or_retracement→or_mid`, `entry_trigger touch→close`; mantener `setup 210`, `retest 24`, `next_open` | S1 histórico y **R3 reejecutada 2026-11-26**: P1 +1.992,26 / DD 1.947,82 / PF 1,37 / 46 trades / fees 218,24; vs actual `next_open` +510,64 neto y −106,64 DD; vs original +1.330,82 y −20,00 DD | **+510,64 neto y −106,64 DD** frente a la actual con el mismo fill (R3, misma W1–W6) | **Alto**: P1 fue elegida en la misma muestra; 46 trades; R3 confirmó in-sample, no forward | **Sí, R3 2026-11-26** (mismo dataset/ventanas/`next_open`); pendiente 2× costes, 6 bloques/LOBO, forward posterior a 2026-06-30; **no H1** |
| **2** | `risk.max_sl_ticks: 300→200` sobre la config actual, dejando lo demás igual | S1: bajar 300→200 en la antigua viva dio **+448,84 neto y −587,20 DD**; 26 trades con stop >200 perdieron −392,60 (no todo es positivo) | No medido en la actual; esperado **mejor DD** y posible mejor neto; no garantizado | **Alto**: evidencia de otra config (10/300) y muestra pequeña | Correr actual `next_open` con SL 200; comparar W1–W6; 2×; LOBO/rolling; forward; **no H1** |
| **3** | `strategy.tp_rr: 2,0→3,0` sobre la config actual, dejando lo demás igual | P1 (TP 3) supera a la actual (TP 2) en neto/DD con el mismo fill, pero el cambio está confundido con entrada y sizing; el win rate actual 47,22 % vs 32,61 % de P1, y avg win 301,22 vs 583,67 de P2 | No aislado; esperado **subir avg win y neto**, a costa de win rate | **Alto**: TP y entrada están correlacionados; 72 trades; sin ablación | Ablación TP 2 vs 3 con entrada/sizing fijos; `next_open`; 2×; LOBO/rolling; forward; **no H1** |
| **4** | Revertir entrada a `or_mid` + `close` (desde `or_retracement` + `touch`), dejando TP/sizing/stop | P1/P2 usan entrada original y rinden +1.992,26/+2.471,78 con 46 trades; la actual genera 72 y 40 solo-actuales; las 32 comunes pierden −1.765,96 con `signal_price` | No aislado; esperado **menos trades, más calidad media**; no se puede cuantificar sin correrlo | **Alto**: la cobertura extra puede ser valiosa con otro fill; el puente es solo `signal_price` | Ablación 2×2 de `entry_reference`/`entry_trigger`; `next_open`; 2×; LOBO/rolling; forward; **no H1** |
| **5** | `risk.max_contracts: 8→5` (o presupuesto de riesgo equivalente) | S1: P1 5 vs P2 10 dio +479,52 neto y +356,64 DD al subir a 10; es apalancamiento, no edge; P1 5 tiene mejor RDD que la actual 8 | **Menos neto y menos DD**; no es una mejora de rentabilidad por sí sola | Bajo para el edge; alto para el tamaño de muestra | Validar como presupuesto de riesgo/DD, no como fuente de alfa; forward; **no H1** |
| **6** | `risk.min_stop_or_ratio: 0,0→0,25` (filtro de stop/OR), solo como hipótesis | S1 P2: +1.730,42 neto y −1.358,08 DD con 17 trades; placebo p=0,0065 y LOBO positivo, pero **17 trades** y config antigua | Alto en la muestra, **no adoptable** con esta evidencia | **Muy alto**: 17 trades, selección, config 10/200/TP3; no es la actual | Forward dedicado; no usar H1; no promover hasta replicar en la config actual y con `next_open` |

**Prioridad recomendada:** **0 → 1 → 2 → 3 → 4 → 5**. El filtro (6) no lo pondría por delante de P1: su +1.730,42 es llamativo, pero son 17 trades de una config que ya no corre y no está medido en la actual.

**Marcado de validación (R3, 2026-11-26):** solo **P1** está respaldada por un backtest ejecutado en esta corrida; las propuestas 2–5 son mecanismos plausibles pero **no se han aislado en la config actual**, y la 6 no se recomienda. El punto 0 (medir con `next_open`) es una condición de medición, no una mejora de estrategia.

**Lo que no propongo:**

- No cambiar el 8765 ahora ni reiniciarlo; el proceso sigue vivo y la config actual ya fue modificada externamente.
- No usar el +4.550,66 como prueba de estrategia: es `signal_price`.
- No trasladar el filtro 0,25 ni las conclusiones del snapshot `9bf4` a la config actual sin reejecutar.
- No tocar el holdout 2026-07-01 → 2026-10-30.

---

## 6. Incertidumbre y límites

- **Tamaño de muestra:** 72 trades de la actual y 38 de la original en 6 ventanas; P1/P2 tienen 46. Es una muestra pequeña para decidir parámetros.
- **Significación:** el delta de la actual con `next_open` tiene **p = 0,501** e IC95 % que cruza cero. El p = 0,0022 de `signal_price` **no es comparable**: cambia el fill y la config fue seleccionada en la misma muestra.
- **Selección:** la config actual y P1/P2 salen de experimentos sobre W1–W6; no hay pre-registro ni forward. Cualquier “mejor” es in-sample.
- **Fill:** `signal_price` no está validado con fills reales; `next_open` es una convención más conservadora, no una garantía. No hay latencia, impacto de mercado ni fills parciales medidos.
- **Costes:** no se corrieron costes 2× en la config actual; el 2× de P1/P2 es histórico y no se extrapola.
- **Turnover/exposición:** no son métricas nativas de `server/stats.py`; se derivaron de los trades. La duración media se reporta con decimal (5.036,7 s) porque el `stats` nativo la trunca a entero (5.036 s).
- **Puente:** el puente de 32/40/6 es solo `signal_price`; no se guardó el de `next_open`. No se afirma que las 40 señales solo-actuales sigan siendo rentables con el fill comparable.
- **Perfil externo:** el perfil cambió a las 18:37, después de S1; no fue escrito por este análisis. El árbol tiene cambios externos (`profiles/live_8765/config.json`, `server/engine.py`, datos forward, etc.); no los toqué ni hice commit.
- **S1:** es un snapshot `9bf4` y está marcado `M`; se usa como evidencia histórica, no como estado actual.
- **Conclusiones que no se sostienen:** “la actual es superior”, “el DD mejora”, “TP 2/entrada explican la ganancia”, “el filtro 0,25 funciona en la actual”, “hay ventaja forward”. Ninguna se puede afirmar con estos datos.

---

## 7. Verificación de integridad y aritmética

### 7.1 Comprobaciones

| Comprobación | Resultado |
|---|---|
| Neto actual servida = bruto − fees | `4.818,50 − 267,84 = 4.550,66` ✔ |
| Neto actual `next_open` = bruto − fees | `1.744,50 − 262,88 = 1.481,62` ✔ |
| Neto original = bruto − fees | `840,00 − 178,56 = 661,44` ✔ |
| Delta actual servida − original | `4.550,66 − 661,44 = 3.889,22` ✔ |
| Delta actual `next_open` − original | `1.481,62 − 661,44 = 820,18` ✔ |
| Efecto fill | `4.550,66 − 1.481,62 = 3.069,04` ✔ |
| Sumas por ventana, servida | `1.486,16 + 291,98 − 166,72 + 2.687,98 − 389,56 + 640,82 = 4.550,66` ✔ |
| Sumas por ventana, `next_open` | `359,88 + 71,48 − 883,72 + 2.601,98 − 376,06 − 291,94 = 1.481,62` ✔ |
| Sumas por ventana, original | `364,82 + 268,40 − 110,46 + 2.034,12 − 1.036,52 − 858,92 = 661,44` ✔ |
| Puente servida | `−1.765,96 + 4.297,44 + 1.357,74 = 3.889,22` ✔ |
| P1 vs actual `next_open` | `1.992,26 − 1.481,62 = 510,64`; `1.947,82 − 2.054,46 = −106,64` ✔ |
| P1 vs original | `1.992,26 − 661,44 = 1.330,82`; `1.947,82 − 1.967,82 = −20,00` ✔ |
| Bootstrap actual `next_open` | R2-S: media 799,53; p = 0,501; IC95 % [−1.865,60; +3.018,68] ✔ |
| Config: 9 diferencias, 8 económicas | R1 `economic_diff_count=8`; `replay_speed` no económica ✔ |
| Hash del perfil antes/después R1 | `1b98…` = `1b98…` ✔ |
| Hash del snapshot R1/R2 | `1b98…` ✔ |
| `data/config.json` | `9bf4…` sin cambios ✔ |
| `resultados_original.jsonl` | SHA-256 **`bee126582f5ec13c2dd8f014dca275408676195bcbf873ee9cb05ab436029214`**; sin cambios ✔ |
| Reprecio tracked (`reprecio_excl...`) | SHA-256 **`10a29e24b9b3a532640ceeb266fa2eb2c1fc12804684e1d3f4d261e7823df6c0`**; sin cambios; no reejecutado ✔ |
| R3: original fija | 38 / +661,44 / DD 1.967,82 / PF 1,13; `matched_by_harness=true` ✔ |
| R3: perfil antes/después | `1b98…` = `1b98…` ✔ |
| R3: salida | `reports/autoloop/live_manual_vs_original_20261126.json`; SHA-256 `41012333ab9beac69f515f52b66e7e4d9ab4d8fd05861fa5a508771b82efa340` ✔ |
| Reprecio | **no reejecutado** (`reprice_rerun=false`) ✔ |
| Holdout | **no accedido** (`holdout_accessed=false`) ✔ |
| Config/DB escritas | **no** (`config_written=false`, `db_written=false`) ✔ |
| Proceso 8765 | PID **16016**, `127.0.0.1:8765` LISTENING, `status=running` ✔ |
| Commit | **sí, limitado a este informe + runner R3 + salida**; hash en la respuesta final |

### 7.2 Fuentes

| ID | Archivo | Hash / uso |
|---|---|---|
| R1 | `logs/current_vs_original_20261126.json` | SHA-256 `0b5c96beef78ac09b894adba0dea4cc12ed1d118dc6cd18b02ad4543c5c4b852`; actual `signal_price` vs original; 261,4 s |
| R2 | `logs/current_next_open_20261126.json` | SHA-256 `279187ebc6c2774f7d120c32dc2be3f6825ee3214e67457cd78e7a80ee82cba6`; actual `next_open`; 185,9 s |
| R2-S | `logs/current_next_open_significance_20261126.json` | SHA-256 `fe0986222863c2f8bb28974f8965b3708bf00761672c8866079e695505986fd9`; bootstrap del delta `next_open` vs original; p = 0,501; IC95 % [−1.865,60; +3.018,68] |
| API | `logs/8765_config_live_20261126.json` | SHA-256 `ca7629296abf3ee42a18af64d36103d21e8be2178d3c1a1808ce0199df68c6a3`; `GET /api/config`; también `logs/8765_api_config_20261126.json` |
| API-S | `logs/8765_status_live_20261126.json` | SHA-256 `48dae518757c2081e9b646a5fbf4cf9e192dea98cb42045e3d3e636172b5ea3f`; `GET /api/status` |
| API-T | `logs/8765_stats_live_20261126.json` | SHA-256 `9f13c75760e80d4d2243a32feb850c0c1c3abdfe481e813b9394e9c0de9692b7`; `GET /api/stats` |
| C1 | `profiles/live_8765/config.json` | SHA-256 `1b98…f81c`; config servida |
| C2 | `logs/current_profile_20261126.json` | SHA-256 `1b98…f81c`; copia usada por R1/R2 |
| C3 | `data/config.json` | SHA-256 `9bf4…e29479f`; snapshot histórico, no servido |
| S1 | `reports/backtest/live_vs_original_mission.json` | SHA-256 `d615e7a8b59ccf89419aa4d9604375c730a5a923e5981fdd769cfd0a62ff686c`; snapshot histórico `9bf4`, 10/300, generado 18:14; marcado `M` por trabajo externo; **no regenerado** |
| R3 | `reports/autoloop/live_manual_vs_original_20261126.json` | SHA-256 `410123…a340`; 4 variantes × W1–W6; 492,2 s; original cuadrada |
| R3-P | `logs/live_manual_profile_1b981d247b6c.json` | SHA-256 `1b98…f81c`; snapshot congelado del perfil vivo usado por R3 |
| S4 | `reports/autoloop/reprecio_excl_1130_1330.jsonl` | SHA-256 `10a29…df6c0`; tracked, intacto; no reejecutado |

R1/R2/R2-S y R3 declaran: `config_written=false`, `db_written=false`, `holdout_accessed=false`, `reprice_rerun=false`, `tracked_artifacts_written=false`.

### 7.3 Estado del proceso y del árbol

- El 8765 sigue en **PID 16016** y responde `status=running`; no se reinició.
- `profiles/live_8765/config.json` está `M` por el cambio externo de las 18:37; **no lo escribí**. R1/R2/R3 confirman hash `1b98…` antes y después.
- `data/config.json` sigue `9bf4…`; no se escribió.
- El árbol contiene otros cambios externos (datos forward, `server/engine.py`, reportes, etc.) y archivos untracked; hice un commit final limitado a este informe, al runner R3 y a su salida; **no incluí ni modifiqué los cambios externos**.
- **HEAD:** el commit de este entregable se reporta en la respuesta final; el padre es `cf3903e`.

---

## 8. Respuesta corta

- **¿La config manual del 8765 mejora la original?** **Solo si se acepta `signal_price` como fill.** Tal como se sirve: +4.550,66 vs +661,44 y menor DD. Con el mismo `next_open` que la original: +1.481,62 vs +661,44 (+820,18), pero **peor DD** (2.054,46 vs 1.967,82) y **p = 0,501**. No es una mejora robusta. **P1 sí está validada en R3** y supera a la manual con el mismo fill (+510,64 neto, −106,64 DD) y a la original (+1.330,82, −20,00 DD), pero sigue siendo in-sample.
- **¿Por qué?** El 79 % del delta aparente es el fill; las 32 señales comunes pierden −1.765,96 frente a la original; la ventaja viene de 40 señales solo-actuales. TP 2 sube el win rate pero baja el avg win; 8 contratos y stop 300 suben el riesgo; la P1 reejecutada con el mismo fill supera a la actual en neto y DD.
- **¿Qué hacer primero?** Medir con `next_open` (no confiar en `signal_price`), luego probar P1 (`5/200/210/24`, TP 3, `or_mid`/`close`) y las ablaciones de stop/TP/entrada; validar con 2×, bloques/LOBO y forward. **No tocar el holdout.**
