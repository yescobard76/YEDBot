# Cierre del análisis — rentabilidad de la config manual del 8765 frente a la original

**Fecha:** 2026-11-25
**Naturaleza:** análisis de solo lectura sobre configuración, locks y artefactos ya existentes. **No se re-ejecutó ningún backtest**, no se cambió ninguna configuración, no se modificaron locks, no se ejecutó código del holdout y no se hizo ningún commit.
**Proceso:** el 8765 está arrancado con el perfil `profiles/live_8765`, PID **16016**, escuchando en `127.0.0.1:8765`; el motor sigue en `stopped` (inicio manual). En este turno no se llamó a la API para no alterar su log.

---

## 0. Resumen ejecutivo

- **Config efectiva:** manual `10 contratos / SL 300 ticks / validez 210 min / retest 24 ticks / filtro stop-ORB 0,00`, `paper`, `live_enabled=false`; archivo `9bf4f9c7…e29479f`, idéntico en `profiles/live_8765/config.json` y `data/config.json`.
- **Original establecida:** `5 / 200 / 150 / 12 / filtro 0,00`, congelada en `docs/protocolo_backtest.lock.json` y reconstruida en memoria desde `profiles/backtest_real/config.json` + parche `150/12`. No existe como fichero materializado.
- **En la muestra W1–W6 (362 sesiones, in-sample):** la manual hace **+2.022,94 USD** frente a **+661,44 USD** de la original (**+1.361,50; +205,8 %**), con PF **1,22 vs 1,13**, expectancy **28,10 vs 17,41 USD/op** y win rate **36,11 % vs 31,58 %**.
- **El precio es riesgo:** DD **2.891,66 vs 1.967,82 USD** (**+923,84; +46,9 %**) y peor DD %. A coste estresado (1,24/lado + 2 ticks) la ventaja baja a **+1.089,50** y **ninguna de las dos cumple PM5** (DD 3.023,82 y 2.064,14).
- **No es una ventaja demostrada:** bootstrap del delta `p=0,4730` a 1x y `0,5662` a 2x; IC 95 % incluye cero; quitar la mejor ventana invierte el signo (LOO −2.339,26). La ventaja viene de **más señales y más tamaño**, no de ejecutar mejor las compartidas: en las 37 señales comunes la manual hace **752,02** y la original **910,14**.
- **Veredicto:** la manual es **más rentable en la muestra** (neto, PF, expectancy, RDD) y **peor en riesgo absoluto**; no hay evidencia de que sea más rentable hacia adelante. Ninguna mejora propuesta está validada fuera de muestra; las tres primeras ya tienen backtest 1x/2x y solo les falta forward.

---

## 1. Configuración efectiva del 8765

### 1.1 Proceso y perfil

| Elemento | Valor | Fuente |
|---|---|---|
| Listener | `127.0.0.1:8765` | `netstat -ano` (PID 16016) |
| PID | **16016** | `logs/server_8765.pid`, `tasklist` |
| Arranque | 2026-11-25 17:16:56 local (23:16:56Z) | `Win32_Process.CreationDate` |
| Comando | `python -m uvicorn server.main:app --host 127.0.0.1 --port 8765` | lanzador (proceso desacoplado) |
| Perfil | `YED_PROFILE_DIR=profiles/live_8765` → config y DB del perfil | entorno del lanzador |
| Log | `logs/server_8765_20261125.log` (580 B al cierre, sin peticiones en este turno) | disco |
| Motor | `stopped` (arranque manual; no se llamó a `/api/start`) | `/api/status` capturado al arrancar |
| Modo / broker | `paper` / `none`; `live_enabled=false` | `/api/config` capturado en `logs/8765_config_20261125.json` |

El perfil no se deduce del `CommandLine` (uvicorn no expone `YED_PROFILE_DIR`): se identifica por el lanzador registrado y porque la configuración servida por `/api/config` coincide con `profiles/live_8765/config.json`.

### 1.2 Los 10 valores clave del lock M y su origen

Los diez valores que `docs/pre_registro_sl200_10c_vs_p1.lock.json` fija para el brazo **M (manual 8765)** están todos en el perfil y se verificaron contra la captura de `/api/config`:

| # | Clave | Valor | Origen en el perfil | Lock M |
|---:|---|---:|---|---:|
| 1 | `risk.max_contracts` | **10** | `profiles/live_8765/config.json → risk.max_contracts` | 10 |
| 2 | `risk.max_sl_ticks` | **300** | `… → risk.max_sl_ticks` | 300 |
| 3 | `strategy.setup_validity_minutes` | **210** | `… → strategy.setup_validity_minutes` | 210 |
| 4 | `strategy.retest_tolerance_ticks` | **24** | `… → strategy.retest_tolerance_ticks` | 24 |
| 5 | `risk.min_stop_or_ratio` | **0,00** | `… → risk.min_stop_or_ratio` | 0,0 |
| 6 | `risk.risk_per_trade_pct` | **1,0 %** | `… → risk.risk_per_trade_pct` | 1,0 |
| 7 | `risk.max_trades_per_day` | **3** | `… → risk.max_trades_per_day` | 3 |
| 8 | `risk.max_concurrent_positions` | **1** | `… → risk.max_concurrent_positions` | 1 |
| 9 | `strategy.tp_rr` | **3,0** | `… → strategy.tp_rr` | 3,0 |
| 10 | `live.live_enabled` | **false** | `… → live.live_enabled` | false |

No hay presets aplicados: el 8765 usa el fichero completo. `data/config.json` es copia byte a byte, así que cualquiera de las dos rutas produce la misma configuración.

### 1.3 Identidad y hashes

| Objeto | SHA-256 |
|---|---|
| `profiles/live_8765/config.json` (bytes) | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `data/config.json` (bytes) | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| Settings completos (canónico, incluye feed/live/mode) | `3baf29e9f29c0dbae5cdd2a96bd7117f0b44ebd1cb1486d886fcc9764bc00d8b` |
| Settings de trading (canónico, excluye feed/live/mode) | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` |
| `config_sha256` del lock M | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` |

**El canónico de trading de la config viva coincide exactamente con el `config_sha256` del brazo M del lock**: la configuración efectiva es la que el lock documenta. Los dos hashes canónicos se calculan con `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)` + SHA-256; la diferencia entre ambos es que el de trading excluye `feed`, `live` y `mode`.

---

## 2. Configuración original establecida

### 2.1 Qué es "original" y de dónde sale

La original de referencia es **`5 contratos / SL 200 / validez 150 / retest 12 / filtro 0,00`**, con el resto de la estrategia idéntico a la manual.

1. **Definición congelada:** `docs/protocolo_backtest.lock.json` (SHA-256 `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c`) fija en su bloque `settings` los valores `risk.max_contracts=5`, `risk.max_sl_ticks=200`, `strategy.setup_validity_minutes=150` y `strategy.retest_tolerance_ticks=12`; estado `frozen-not-executed`.
2. **Reconstrucción operativa:** `reports/backtest/_manual_common.py` define `ORIGINAL_PATH = profiles/backtest_real/config.json` (SHA-256 `8fd7cfa2…`) y `ORIGINAL_FREQUENCY_PATCH = {setup_validity_minutes: 150, retest_tolerance_ticks: 12}`. El fichero base ya trae 5 contratos y SL 200, pero **en disco contiene 210/24**; por eso la original **no se obtiene abriendo el fichero**, sino aplicando el parche en memoria.
3. **Identidad reproducible:** el canónico de trading del perfil base + parche es `87b8b9f18dbce9e4739112cf734850fe75de7e82e7548425d246027d2234e708`, que es el hash que citan los documentos previos como "original canónica".

No existe un `config.json` separado con `150/12`. Cualquier reproducción debe usar `_manual_common.load_original()` o el mismo parche.

### 2.2 Diff exacto manual vs original

| Parámetro | Manual 8765 | Original | Δ |
|---|---:|---:|---:|
| `risk.max_contracts` | 10 | 5 | ×2 |
| `risk.max_sl_ticks` | 300 | 200 | +100 |
| `strategy.setup_validity_minutes` | 210 | 150 | +60 |
| `strategy.retest_tolerance_ticks` | 24 | 12 | ×2 |

Todo lo demás es idéntico: ORB 09:00–10:00, SMT, geometría de entrada, `tp_rr=3,0`, riesgo 1 %, 3 trades/día, una posición, comisión 0,62/lado, slippage 1 tick, ventana 09:00–15:30 y cierre 15:55. `min_stop_or_ratio` es 0,00 en ambas.

---

## 3. Comparación de rentabilidad

### 3.1 Muestra, costes y método

- **Ventana:** W1–W6, **362 sesiones**, 2025-01-10 → 2026-06-30; `data/bars.csv` serie `adjusted`; capital inicial 25.000 USD.
- **Costes base:** 0,62 USD por contrato y lado; 1 tick de slippage por lado; `next_open`; sin fills parciales.
- **Coste estresado:** 1,24 USD/lado y 2 ticks (el preset del repo), aplicado en memoria.
- **Comparación:** carteras completas (72 vs 38 operaciones), no las mismas operaciones; la intersección por señal se analiza aparte.
- **Holdout:** H1 (`2026-07-01` → `2026-10-30`, 85 sesiones) **no se usó**.

### 3.2 Tabla principal (coste base 1x)

| Métrica | Original `5/200/150/12` | Manual `10/300/210/24` | Δ manual − original | Fuente |
|---|---:|---:|---:|---|
| Operaciones | 38 | 72 | +34 (+89,5 %) | S1 |
| PnL neto (USD) | +661,44 | +2.022,94 | **+1.361,50 (+205,8 %)** | S1 |
| Expectancy (USD/op) | 17,41 | 28,10 | +10,69 | S1 |
| Expectancy (R/op) | 0,13 | 0,18 | +0,05 | S1 |
| Win rate | 31,58 % | 36,11 % | +4,53 pp | S1 |
| Profit factor | 1,13 | 1,22 | +0,09 | S1 |
| Max drawdown (USD) | 1.967,82 | 2.891,66 | **+923,84 (+46,9 %)** | S1 |
| Max drawdown (%) | 7,141 % | 9,793 % | +2,652 pp | S1 |
| RDD (neto/DD) | 0,3361 | 0,6996 | +0,3635 | S1 |
| Comisiones (USD) | 178,56 | 333,56 | +155,00 | S1 |
| R total | +4,98 | +13,19 | +8,21 | S1 |

La RDD mejora porque el neto sube más que el DD; **no** porque el riesgo absoluto baje.

### 3.3 Coste estresado (2x)

| Métrica | Original | Manual | Δ |
|---|---:|---:|---:|
| Operaciones | 38 | 72 | +34 |
| PnL neto (USD) | +347,38 | +1.436,88 | **+1.089,50** |
| Profit factor | 1,07 | 1,15 | +0,08 |
| Expectancy (USD/op) | 9,14 | 19,96 | +10,82 |
| Win rate | 31,58 % | 36,11 % | +4,53 pp |
| Max drawdown (USD) | 2.064,14 | 3.023,82 | **+959,68** |
| Max drawdown (%) | 7,543 % | 10,386 % | +2,843 pp |
| RDD | 0,1683 | 0,4752 | +0,3069 |
| Comisiones (USD) | 357,12 | 667,12 | +310,00 |

**Efecto de costes:** la manual pierde **586,06 USD** al doblar costes (2.022,94 → 1.436,88) y la original **314,06** (661,44 → 347,38). La ventaja relativa incluso sube (+1.361,50 → +1.089,50 en absoluto, pero el neto de la manual cae −28,97 % y el de la original −47,48 %). El DD empeora en ambas: la manual pasa de 2.891,66 a 3.023,82 y la original de 1.967,82 a 2.064,14.

**Gate PM5 (`DD ≤ 2.000`):** a 1x la original cumple por **32,18** y la manual incumple por **891,66**; a 2x **ninguna cumple** (original −64,14; manual −1.023,82).

### 3.4 Significación y tamaño de muestra

| Régimen | Δ neto (original − manual) | p dos colas | IC 95 % | LOO mínimo |
|---|---:|---:|---|---:|
| 1x | −1.361,50 | 0,4730 | [−5.361,29; +2.162,64] | −2.339,26 |
| 2x | −1.089,50 | 0,5662 | [−5.047,60; +2.410,84] | −2.118,02 |

Bootstrap de bloques por sesión, 10.000 remuestreos, semilla 20250102, calendario completo de 362 sesiones (S7). El bootstrap previo por 6 bloques de ventana daba `p=0,6544` e IC [−3.056,32; +6.965,66] (S1). **Los dos métodos coinciden en lo esencial: el intervalo contiene cero.** Con 38 vs 72 operaciones, el diseño no tiene potencia para separar un delta de 1.300–1.400 USD de la variabilidad por bloques.

### 3.5 De dónde viene la diferencia

Atribución secuencial (S1, `attribution`):

| Paso | Cambio | Δ neto | Δ DD |
|---|---|---:|---:|
| Original → P1 | frecuencia `150/12 → 210/24`, 5 contratos, SL 200 | +1.330,82 | −20,00 |
| P1 → P2 | `max_contracts 5 → 10` | +479,52 | +356,64 |
| P2 → manual | `max_sl_ticks 200 → 300` | **−448,84** | **+587,20** |
| **Total** | Original → manual | **+1.361,50** | **+923,84** |

En las **37 señales comunes** la manual hace **752,02 USD** y la original **910,14 USD**: la manual pierde **−158,12** en lo que ambas operan. Su ventaja agregada son **35 señales solo-manual (+1.270,92)** menos **1 señal solo-original (−248,70)**. Es cobertura + tamaño, no mejor selección ni mejor ejecución.

### 3.6 Runtime paper vs backtest controlado

| Fuente | Ops | Neto | PF | DD | Fees |
|---|---:|---:|---:|---:|---:|
| DB del perfil, replay anterior (read-only) | 72 | **+2.269,38** | 1,23 | 3.099,36 (10,337 %) | 357,12 |
| W1–W6 controlado, manual | 72 | +2.022,94 | 1,22 | 2.891,66 | 333,56 |
| W1–W6 controlado, original | 38 | +661,44 | 1,13 | 1.967,82 | 178,56 |

El runtime supera al controlado en **+246,44** de neto, **+207,70** de DD y **+23,56** de fees. No se reconstruyó trade a trade; es una diferencia de contabilidad/ejecución del replay y **no se usa para el veredicto**. El proceso actual no ha generado PnL nuevo: el motor está detenido desde el 2026-06-30.

### 3.7 Huecos explícitos: "no medido"

| Comparación / métrica | Estado |
|---|---|
| PnL del proceso actual tras el reinicio | **No medido**: motor `stopped`, 0 trades nuevos. |
| Original o manual en el holdout H1 / forward | **No medido**: H1 sellado, sin ejecutar. |
| Manual con BE/trailing o gestión activa | **No medido**: el motor no tiene management. |
| Combinación `min_stop_or_ratio=0,25` + exclusión 12:00–14:00 | **No medido**: interacción no simulada. |
| `max_sl_ticks=200` (M-SL200) a coste 2x | **No medido**: solo hay 1x. |
| Desglose por símbolo | **No aplica**: solo se opera MNQ; NQ/ES son referencias SMT. |
| Costes reales de broker, latencia y fills | **No medido**: solo modelo 0,62/1 tick y estrés 1,24/2. |
| Original con más de 5 contratos | **No medido**. |

---

## 4. Veredicto

**La config manual del 8765 es más rentable que la original en la muestra medidas, pero no es una mejora demostrada.**

- **A favor:** +1.361,50 USD (+205,8 %) de neto, PF 1,22 vs 1,13, expectancy 28,10 vs 17,41 USD/op, win rate 36,11 % vs 31,58 % y RDD 0,6996 vs 0,3361. La ventaja sobrevive al doble coste (+1.089,50) y crece en términos relativos.
- **En contra:** +923,84 USD (+46,9 %) de drawdown, DD % 9,793 vs 7,141 y peor racha. La manual **incumple PM5 en los dos regímenes**; la original cumple a 1x y falla a 2x. La ventaja agregada no viene de operar mejor las mismas señales (−158,12 en 37 comunes), sino de tomar 35 señales extra con más tamaño.
- **Incertidumbre:** `p=0,4730` (1x) y `0,5662` (2x); IC 95 % con cero; LOO −2.339,26. Con 38/72 operaciones y una sola muestra in-sample, la aritmética es sólida pero la persistencia futura no está demostrada. No hay forward ni PnL real.

**Uso práctico:** la manual es defendible como **más neta y más eficiente por unidad de DD**, pero no como **más segura** ni como **ventaja validada**. Cualquier promoción exige forward con el gate de DD aplicado a coste estresado.

---

## 5. Mejoras priorizadas por rentabilidad esperada

Orden por Δ neto medido frente a la manual. Ninguna está validada fuera de muestra. La columna "validación" distingue las que necesitan un backtest in-sample nuevo de las que ya están medidas y solo requieren forward, y marca las de pura gestión de riesgo.

| # | Cambio exacto | Δ neto vs manual (1x / 2x) | DD (1x / 2x) | Ops | Evidencia | Validación requerida | Riesgo / efecto secundario |
|---:|---|---:|---:|---:|---|---|---|
| 1 | `risk.min_stop_or_ratio: 0,00 → 0,25` | **+1.786,66 / +2.193,32** | 1.660,04 / 1.706,58 | 43 | S12, S13; p 0,3134 / 0,2238 | **Backtest in-sample nuevo** con sizing controlado + forward | W5 pasa de 6 a 0 ops; el filtro cambia el sizing (qty ≤5); el delta mezcla selección y tamaño |
| 2 | `risk.entry_exclusion_start="12:00"`, `entry_exclusion_end="14:00"` | **+1.478,00 / +1.749,50** | 1.835,30 / 1.880,10 | 46 | S8, S9; p 0,2656 / 0,1966 | Ya medido 1x/2x; **solo forward** | 99,6 % del delta es evitar W5+W6; W1 pierde −506,18; in-sample |
| 3 | `risk.entry_exclusion_start="11:30"`, `entry_exclusion_end="12:30"` | **+1.317,96 / +1.554,90** | **1.259,18 / 1.330,86** | 48 | S10, S11; p 0,4002 / 0,3272 | Ya medido 1x/2x; **solo forward** | W3 PF 0,18; 72,8 % del delta en W5; la más frágil |
| 4 | `risk.max_sl_ticks: 300 → 200` (mantener 10 contratos y 210/24) | +448,84 (1x); **2x no medido** | 2.304,46 (−587,20) | 46 | S2; PF 1,39 | Ya medido 1x; **falta 2x y forward** | Sigue por encima de PM5 (2.304,46); recorta 26 señales; no pareado |
| 5 | `risk.max_contracts: 10 → 5` y `risk.max_sl_ticks: 300 → 200` (P1) | −30,68 / **+170,14** | **1.947,82 / 2.044,14** | 46 | S14, S15; p 0,9986 / 0,8816 | Ya medido 1x/2x; **solo forward con gate DD** | Mejora de **riesgo**, no de neto; incumple PM5 a 2x por 44,14 |

### 5.1 Detalle

**#1 — Filtro `min_stop_or_ratio=0,25`.** Hipótesis: descartar stops cuyo riesgo es pequeño frente al rango de apertura evita operaciones con mala relación stop/recorrido. Métrica que la validaría: neto y RDD con el **mismo sizing** que la manual (hoy el filtro reduce qty), y DD ≤ 2.000 a 2x. Es la mayor ganancia nominal, pero también la de mayor confusor: sin un re-test que fije el tamaño, no se puede atribuir el delta a la selección.

**#2 — Exclusión 12:00–14:00.** Hipótesis: la franja media de la sesión concentra stops y falsas continuaciones. Métrica: neto, PF y DD por ventana W1–W6, con el delta sobreviviendo al doble coste. Ya está medida a 1x y 2x; lo que falta es forward. Riesgo: casi todo el delta es evitación de pérdidas de W5/W6 y W1 empeora −506,18.

**#3 — Exclusión 11:30–12:30.** Hipótesis: el bloque previo al mediodía ET es el más tóxico. Métrica: RDD y DD, que es donde mejor sale (1.259,18/1.330,86). Riesgo: W3 sigue con PF 0,18 y el 72,8 % del delta está en W5; concentración alta.

**#4 — `max_sl_ticks=200`.** Hipótesis: el stop de 300 acepta stops demasiado profundos que destruyen neto y DD; 26 operaciones con stop >200 pierden −392,60 USD. Métrica: neto y DD a 1x y 2x, con DD ≤ 2.000. Ya medido a 1x (+448,84, −587,20 de DD); falta el 2x y el forward. Riesgo: a 1x el DD 2.304,46 sigue incumpliendo PM5 y el corte no es pareado.

**#5 — P1 (5 contratos + SL 200).** No es una mejora de rentabilidad: a 1x pierde 30,68 y a 2x gana 170,14, pero reduce el DD 943,84/979,68. Métrica: DD y RDD, no neto. Ya medido en ambos regímenes; solo requiere forward con el gate `DD ≤ 2.000` a coste estresado, que a 2x no cumple por 44,14.

**No propuestas por falta de evidencia (hipótesis, no recomendaciones):** BE/trailing a 1R, parciales, órdenes limit en el retest en lugar de `next_open`, subir `risk_per_trade_pct` y combinar #1 con #2. Ninguna tiene corrida en el repo; no se les asigna delta ni orden.

---

## 6. Integridad de esta pasada

### 6.1 Ficheros y locks

Medido al inicio y al cierre del turno; sin cambios en hash ni en mtime:

| Objeto | SHA-256 | mtime | `git status` |
|---|---|---|---|
| `profiles/live_8765/config.json` | `9bf4f9c7…e29479f` | 2026-11-23 19:59:39.851830200 −0600 | limpio |
| `data/config.json` | `9bf4f9c7…e29479f` | 2026-11-22 20:36:50.479925700 −0600 | limpio |
| `docs/protocolo_backtest.lock.json` | `55d89872…9f353c` | 2026-11-19 20:35:22.866538400 −0600 | limpio |
| `docs/pre_registro_sl200_10c_vs_p1.lock.json` | `38e818f6…f0e666` | 2026-11-24 03:19:23.576432700 −0600 | limpio |

No se escribió en `profiles/live_8765/` ni en `data/`; no se modificaron los locks; no hay commits (`HEAD 8b9cd6a`). El único cambio de repositorio de este turno es este documento.

### 6.2 Proceso 8765

| Comprobación | Valor |
|---|---|
| Listener | `127.0.0.1:8765` **LISTENING**, PID **16016** |
| `logs/server_8765.pid` | `16016` |
| Log | `logs/server_8765_20261125.log`, 580 B, sin peticiones en este turno |
| `/api/start` | **no llamado**; motor `stopped` |
| Parada / reinicio | **no** |

### 6.3 Holdout

- `docs/protocolo_backtest.lock.json` declara H1 (`2026-07-01` → `2026-10-30`, 85 sesiones) con estado `frozen-not-executed`.
- No hay artefactos de holdout en el repo: los únicos ficheros que contienen "holdout" en el nombre son tests (`tests/test_api_holdout.py`) y su caché.
- `find . -iname "*holdout*" -newermt "2026-11-25 00:00"` → **0 ficheros**. **El holdout no se ejecutó ni se leyó.**

---

## 7. Fuentes

| Ref. | Artefacto | SHA-256 (16 primeros) | mtime |
|---|---|---|---|
| S1 | `reports/backtest/live_vs_original_mission.json` | `40377a5daf096444…` | 2026-11-24 11:38 |
| S2 | `reports/backtest/p2_w1_w6_confirm.json` | `3b2d654a6298b181…` | 2026-11-22 23:49 |
| S3 | `reports/autoloop/_fresh_manual_1x.json` | `23700e5602e58df6…` | 2026-11-25 17:08 |
| S4 | `reports/autoloop/_fresh_original_1x.json` | `c6092b31233dc67d…` | 2026-11-25 17:07 |
| S5 | `reports/autoloop/_fresh_manual_2x.json` | `391ee591879c63ed…` | 2026-11-25 17:08 |
| S6 | `reports/autoloop/_fresh_original_2x.json` | `a6886e452fd0cb11…` | 2026-11-25 17:07 |
| S7 | `reports/autoloop/_fresh_analysis.json` | `df20825a7700c7f0…` | 2026-11-25 17:10 |
| S8 | `reports/autoloop/_delta_dump_excl_1200_1400.json` | `615a7ca296aac211…` | 2026-11-25 15:41 |
| S9 | `reports/autoloop/_delta_x2_excl_1200_1400_rerun.json` | `98275f5753f6a7b3…` | 2026-11-25 16:48 |
| S10 | `reports/autoloop/_delta_dump_excl_1130_1230.json` | `b2c22a57f61a17bf…` | 2026-11-25 15:41 |
| S11 | `reports/autoloop/_delta_x2_excl_1130_1230_rerun.json` | `5c48d53a5f682a8d…` | 2026-11-25 16:48 |
| S12 | `reports/autoloop/_delta_dump_stop_or_025.json` | `3ea7be9ade7f8d09…` | 2026-11-25 15:41 |
| S13 | `reports/autoloop/_delta_x2_stop_or_025.json` | `f4b272ec7d8d0660…` | 2026-11-25 15:55 |
| S14 | `reports/autoloop/_delta_dump_p1_5_200.json` | `a0697b8e40274242…` | 2026-11-25 16:34 |
| S15 | `reports/autoloop/_delta_x2_p1_5_200.json` | `96c9d76e749a4319…` | 2026-11-25 16:34 |
| S16 | `logs/8765_config_20261125.json` (captura `/api/config`) | `9a1b4c137aa60d56…` | 2026-11-25 17:18 |
| S17 | `docs/CONFIG_8765_RENTABILIDAD.md` (contexto runtime y original canónica) | — | — |
| S18 | `docs/ANALISIS_MANUAL_8765_RENTABILIDAD_2026-11-25.md` (análisis previo) | — | — |

Los hashes de S1 y S2 coinciden con los publicados en S18; los de S3–S15 son los artefactos usados para las cifras 1x/2x de este documento. No se accedió a H1 en ningún momento.

**Limitación final:** todas las cifras son in-sample y de un replay paper. No son una garantía de rentabilidad futura ni una validación forward.
