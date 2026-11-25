# Memo de decisión — bot manual del puerto 8765

**Fecha de cierre:** 2026-11-24 (instantánea `2026-11-24T06:26:30Z`).
**Objeto:** bot que escucha en `127.0.0.1:8765`.
**Decisión vigente:** **`KEEP_M` / `keep_current`**. No se cambia la configuración viva.
**Alcance:** comprobación read-only, agregación de artefactos existentes y propuestas. No se ejecutó ningún backtest forward, no se inició captura y no se leyó ni modificó el holdout.

## Resumen ejecutivo

- **Lo que corre ahora:** perfil manual `10/300/210/24`, `min_stop_or_ratio=0,00`, modo `paper`, `live_enabled=false`, PID 15108, listener `127.0.0.1:8765` **[S]**. La configuración de la API coincide con `data/config.json` y con `profiles/live_8765/config.json`; ambos archivos tienen el mismo SHA-256 **[S]**.
- **Rentabilidad histórica:** en W1–W6 el manual gana **+2.022,94 USD** frente a **+661,44 USD** del original (**+1.361,50 USD, +205,8 %**), con PF **1,22 vs 1,13** y expectancy R **0,183 vs 0,131**. Pero el drawdown empeora **+923,84 USD** (**2.891,66 vs 1.967,82**) y el RDD es **0,6996 vs 0,3361** **[M]**. La diferencia **no es estadísticamente distinguible**: bootstrap de 6 bloques, IC95 % `[-3.056,32, +6.965,66]`, `p=0,6544` **[M]**.
- **Comparación de riesgo:** P2 (`10/200/210/24`) obtiene **+2.471,78 USD**, PF **1,39**, DD **2.304,46** y RDD **1,0726**; el manual tiene más neto que el original pero peor RDD que P2 **[M][P2]**. El lastre identificado es el stop 300: el cohorte de 26 operaciones con `stop_ticks > 200` pierde **−392,60 USD** **[M]**.
- **Por qué no se promociona nada:** el forward de P2/P2+BE/manual está **pre-registrado pero no ejecutado**; el holdout sigue sellado; `execution_gate.can_execute=false`; el informe forward mantiene `insufficient_data` y `keep_current` **[V][L]**. Las cifras anteriores son in-sample.
- **Qué hacer primero:** no tocar el 8765. Cerrar la fase 0 y ejecutar el forward pre-registrado **M/C/T** con un lock de ejecución nuevo. Dentro de ese protocolo, **C** (bajar `max_sl_ticks` de 300 a 200) es la primera hipótesis por Δneto; **T** (P2 + BE 1R) es la segunda por RDD/DD; el filtro 0,25 es una hipótesis separada y queda tercero. Si C falla PM5, la regla es `KEEP_M`; T no es un rescate.

---

## 0. Fuentes y trazabilidad

Cada cifra del memo sale de uno de estos artefactos. Los hashes son SHA-256 del archivo completo; los valores canónicos de configuración usan `server.experiments.config_sha256` (excluye `feed`, `live` y `mode`).

| Ref. | Artefacto | SHA-256 | Uso |
|---|---|---|---|
| **[S]** | `reports/backtest/live_8765_decision_check.json` | `f017e17ef553864fddb6bc706374d36f520fe68f7547091d1b53f29743a00035` | Proceso, configuración API, stats de runtime y constraints de la comprobación |
| **[M]** | `reports/backtest/live_vs_original_mission.json` | `9fcc2d0fb1cb0b8c0d5b5bce62ec227b3d416d79819cfa0cffd9d58b8e9104e3` | Manual vs original, atribución, significancia, coste y veredicto |
| **[P2]** | `reports/backtest/p2_w1_w6_confirm.json` | `3b2d654a6298b181c0ad1161a038e7f8f95eaa70de26c211f2e3d2f82b9e9312` | Confirmación P2: 46 ops, neto, PF, DD |
| **[BE]** | `reports/backtest/p2_be_1r_experiment.json` | `eebefb261c4663992a65dbbe7687cb204184e89481d68ccd4dc85940d29c13c0` | P2 + BE 1R: 46 ops, neto, PF, DD |
| **[F]** | `reports/backtest/FILTER025_PROFITABILITY.md` | `f6ac32e396965b26df807ec857a407ac6c7c2543cf4572adfaa886cb88df6920` | Tabla manual/original/P2/filtro, trimestres, coste y confianza |
| **[FG]** | `reports/backtest/filter025_gates.json` | `66cf5ce0dabf1ab0b646a6809f8adee4c991d1f5e4f7211f79cdea0e07f6ee5b` | Gates históricos del filtro: `INCONCLUSO` |
| **[V]** | `reports/backtest/forward_validation.json` | `4cdd6e2333f2a5423b7abe516c3b4ed8caa6790402d09a9987758de3ab383b32` | `status=insufficient_data`; decisión `keep_current`; holdout |
| **[VMD]** | `reports/backtest/FORWARD_VALIDATION.md` | `0de53ef7d4d64cc37c9e366aa4dbd0d377f0957720fd337ffbdf0b089d810699` | Narrativa del informe forward |
| **[PR]** | `docs/P2_BE_1R_FORWARD.md` | `240246aace8dba9930ecec807169d58361d227dc4594ff2e5586d5ffb7564164` | Pre-registro M/C/T, gates, KILL y parada |
| **[L]** | `docs/p2_be_1r_forward.lock.json` | `ad72a200943febc2382e40372d199b8a7fda2d78fa67818e96c27be779735dd5` | Lock M/C/T; `can_execute=false`; holdout sellado |
| **[FL]** | `docs/p2_filtro_stop_or_forward.lock.json` | `d1a2c87b1a855d2040347dbc513711302fd3a4d667ffeb24ca4ae4861719fb01` | Lock separado `H-P2-FILTER-STOP-OR-025` |
| **[PL]** | `docs/protocolo_backtest.lock.json` | `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c` | Protocolo v1.2 y holdout H1 |
| **[PC]** | `docs/PROTOCOLO_BACKTEST.md` | `2419ec7e4d008e0007372b373c5e045428e7252fb62c4a43a6a7b6a63172d49f` | Protocolo congelado |
| **[C]** | `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | Configuración manual de referencia |
| **[LC]** | `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | Copia del perfil vivo (mismos bytes que `[C]`) |
| **[P2C]** | `profiles/p2_freq/config.json` | `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb` | Perfil P2 usado por C y T |

Comandos de reproducción:

```bash
sha256sum data/config.json profiles/live_8765/config.json profiles/p2_freq/config.json \
  docs/protocolo_backtest.lock.json docs/P2_BE_1R_FORWARD.md docs/p2_be_1r_forward.lock.json \
  docs/p2_filtro_stop_or_forward.lock.json reports/backtest/live_vs_original_mission.json \
  reports/backtest/p2_w1_w6_confirm.json reports/backtest/p2_be_1r_experiment.json \
  reports/backtest/forward_validation.json reports/backtest/live_8765_decision_check.json
```

Para el hash canónico de la configuración:

```bash
python -c "from server.config import Settings; from server.experiments import config_sha256; import json; print(config_sha256(Settings.model_validate(json.load(open('profiles/live_8765/config.json')))))"
```

Para las fechas de archivo citadas en §1.1:

```bash
stat -c '%y %n' profiles/live_8765/config.json data/config.json
# 2026-11-23 19:59:39.851830200 -0600 profiles/live_8765/config.json
# 2026-11-22 20:36:50.479925700 -0600 data/config.json
```

---

## 1. Estado real de la configuración que está en marcha en 8765

### 1.1 Proceso y servicio

La comprobación se hizo con lecturas HTTP y consultas de proceso, sin reiniciar ni escribir en la instancia **[S]**.

| Elemento | Valor observado | Fuente |
|---|---|---|
| Listener | `127.0.0.1:8765` | `netstat -ano`, `[S].listener` |
| PID que escucha | `15108` (`python.exe`) | `[S].process` |
| Arranque del proceso | `2026-11-23T20:12:49-06:00` = `2026-11-24T02:12:49Z` | PowerShell `StartTime`/`CreationDate`, `[S].process` |
| Comando | `python.exe -u run.py` | `[S].process.command_line` |
| Salud HTTP | `status=ok`, versión `1.0.0` | `GET /api/health`, `[S].health` |
| Motor | `running` | `GET /api/status`, `[S].engine` |
| Modo | `paper` | `[S].engine.mode` |
| Ejecución real | `live.live_enabled=false` | `GET /api/config`, `[S].config.values` |
| Feed | CSV histórico `data/bars.csv`, serie `adjusted`, `loop_sessions=true`, replay 8× | `[S].engine.data`, `[S].config.values` |
| Sesión de replay en la captura | `2025-10-07` (avanza con el replay) | `[S].engine.session` |
| DB del perfil | 45 trades en lectura read-only | `[S].db` |

**Desde cuándo:** la fecha efectiva verificable es el arranque del proceso, `2026-11-23T20:12:49-06:00`. El archivo `profiles/live_8765/config.json` tiene mtime `2026-11-23 19:59:39 -06`, anterior al arranque, y `data/config.json` tiene mtime `2026-11-22 20:36:50 -06`. No hay un log de recarga que permita fechar una aplicación posterior; por tanto, lo que se puede afirmar es que el proceso arrancó con esos bytes ya en disco y que la API coincide con ellos ahora. No se atribuye una fecha de recarga que no esté documentada.

### 1.2 Configuración efectiva

La API y los archivos del repo dan los mismos valores:

| Parámetro | Valor vivo | `data/config.json` | `profiles/p2_freq/config.json` | Original canónico 150/12 |
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

Fuente: `[S].config.values`, `[C]`, `[P2C]`, `[M].config_diff`. El perfil vivo **no es el original**: el original establecido es `5/200/150/12` y el vivo es `10/300/210/24` **[M]**. Tampoco es P2: al comparar los JSON completos, **la única diferencia entre `profiles/live_8765/config.json` y `profiles/p2_freq/config.json` es `risk.max_sl_ticks` (300 vs 200)**; el resto de los campos coincide. Tampoco aplica el filtro 0,25: `min_stop_or_ratio=0,00` **[S]**.

### 1.3 Hashes: qué coincide y qué diverge

| Objeto | SHA-256 | Estado |
|---|---|---|
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | Coincide byte a byte con la copia viva |
| `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | Coincide byte a byte con `data/config.json` |
| Configuración canónica de la API | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` | Coincide con el canónico de ambos archivos |
| `profiles/p2_freq/config.json` | `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb` | Diverge por `max_sl_ticks=200`; canónico `54656561bf692731d71013c6655155a566c9b4b49fe53a88d61bf20814310f4f` |
| `profiles/backtest_real/config.json` | `8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f` | Referencia histórica; **no es la frecuencia original 150/12** (el original se fija en memoria por el protocolo) |
| Lock del protocolo v1.2 | `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c` | Sin cambios |
| Lock M/C/T | `ad72a200943febc2382e40372d199b8a7fda2d78fa67818e96c27be779735dd5` | Sin cambios |
| Lock del filtro 0,25 | `d1a2c87b1a855d2040347dbc513711302fd3a4d667ffeb24ca4ae4861719fb01` | Sin cambios |

El hash de archivo `9bf4…` no es igual al canónico `d3cf…` por diseño: el canónico excluye `feed`, `live` y `mode`; la coincidencia relevante es que la API produce el mismo canónico que ambos archivos y que los archivos son idénticos byte a byte.

### 1.4 Qué está confirmado y qué no

**Confirmado:**

- El proceso que escucha en 8765 es el PID 15108 y sigue vivo desde `2026-11-23T20:12:49-06:00` **[S]**.
- La API devuelve `running`, `paper`, el perfil manual `10/300/210/24`, filtro 0,00 y `live_enabled=false` **[S]**.
- La configuración de la API coincide con `data/config.json` y con `profiles/live_8765/config.json`; ambos tienen el mismo hash **[S]**.
- El perfil P2 difiere del vivo solo en `max_sl_ticks` **[S]**.
- El holdout sigue sellado y el forward no se ha ejecutado **[L][V]**.

**No confirmado desde el proceso actual, y por tanto no se asume:**

- El `CommandLine` del PID 15108 no expone `YED_PROFILE_DIR`; Windows no muestra el entorno en esa consulta. La ruta `profiles/live_8765` se apoya en el lanzador registrado en la captura anterior y en la coincidencia exacta de la API con esa copia. Como `data/config.json` y la copia viva son idénticos, el perfil efectivo es el mismo manual en cualquiera de los dos casos; lo que no se puede distinguir desde el PID actual es cuál de los dos archivos idénticos se cargó.
- No hay un log de recarga que pruebe una fecha efectiva distinta del arranque. La fecha que se afirma es la del proceso, no una recarga no documentada.
- Las métricas de `/api/stats` son de un replay en curso, no de la muestra W1–W6. En la instantánea son **45 trades, +2.720,04 USD, PF 1,46, avg R 0,35, DD 2.366,76 (8,02 %)** **[S]**, pero la sesión avanzó a `2025-10-07` y las cifras pueden cambiar después del timestamp. **No se usan para la comparación histórica ni para la decisión.** La DB tenía 45 trades en la lectura read-only, consistente con la API en ese instante **[S]**.
- No hay P&L forward, no hay captura nueva y no se ha ejecutado ningún backtest en este cierre. El artefacto **[M]** ya existía; su propio constraint `backtests_run=true` describe su generación, no una ejecución de este memo.

---

## 2. Rentabilidad del manual frente a la configuración original

### 2.1 Comparación principal

Muestra idéntica W1–W6: `2025-01-10` → `2026-06-30`, **362 sesiones**, serie ajustada, capital inicial 25.000 USD. Holdout no usado; 2024 no usado **[M]**. Cifras en USD:

| Métrica | Original 38 | Manual 72 | Diferencia |
|---|---:|---:|---:|
| Operaciones | 38 | 72 | +34 |
| Neto | **+661,44** | **+2.022,94** | **+1.361,50 (+205,8 %)** |
| Profit factor | 1,13 | 1,22 | +0,09 |
| Expectancy USD/op | 17,41 | 28,10 | +10,69 |
| Expectancy R/op | 0,131 | 0,183 | +0,052 |
| R total | +4,98 | +13,19 | +8,21 |
| Drawdown USD | **1.967,82** | **2.891,66** | **+923,84 (+46,9 %)** |
| Drawdown % | 7,141 | 9,793 | +2,652 pp |
| **RDD_USD** (`neto/DD`) | **0,3361** | **0,6996** | **+0,3634 (2,08×)** |
| Peor racha de pérdidas | 10 | 13 | +3 |
| Acierto | 31,58 % | 36,11 % | +4,53 pp |

Fuente: `[M].aggregate.original` y `[M].aggregate.live`; RDD calculado como `net_profit / max_drawdown`. La expectancy R se calcula como `total_r / trades` (`13,19/72=0,1832`; `4,98/38=0,1311`); el campo `avg_r` del artefacto se redondea a `0,18` y `0,13`.

**Lectura correcta:** el manual gana más dinero absoluto y tiene mejor PF y expectancy, pero **no es mejor en riesgo**: su DD es 923,84 USD mayor y su RDD solo mejora al original porque el neto sube más que el DD. Frente a P2, el manual pierde en RDD: P2 tiene **+2.471,78 USD**, PF **1,39**, DD **2.304,46**, RDD **1,0726** **[M][P2]**. Es decir, el manual supera al original en retorno absoluto, pero no domina la alternativa P2 en retorno ajustado a riesgo.

### 2.2 Evidencia existente y límites

| Bloque | Qué dice | Estado |
|---|---|---|
| In-sample W1–W6 | Manual +1.361,50 USD sobre original; DD +923,84; PF 1,22 vs 1,13 | **Existente**, pero in-sample **[M]** |
| Estabilidad trimestral | Manual: W1 +2.735,34; W2 +418,30; W3 −1.088,22; W4 +2.461,48; W5 −1.497,14; W6 −1.006,82 | **Existente**; 2026 pierde **−2.503,96** **[F]** |
| Original trimestral | W1 +364,82; W2 +268,40; W3 −110,46; W4 +2.034,12; W5 −1.036,52; W6 −858,92 | **Existente**; 2026 pierde **−1.895,44** **[F]** |
| P2 trimestral | W1 +2.245,50; W2 +642,76; W3 −460,32; W4 +1.960,60; W5 −1.497,14; W6 −419,62 | **Existente**; 2026 pierde **−1.916,76**, con mejor DD/PF que el manual **[F]** |
| Significancia | Bootstrap por 6 bloques, 10.000 remuestreos: media +1.390,94; IC95 % [−3.056,32, +6.965,66]; p=0,6544; incluye 0 | **Insuficiente para afirmar una ventaja** **[M]** |
| Coste | Original con comisión 1,24/lado y slippage 2: neto 347,38, PF 1,07; manual: **n/d** (no hay reprecio exacto) | **Insuficiente**; no se puede decir que el manual resista costes **[F]** |
| Forward | 0 sesiones; lock pre-registrado no ejecutado; holdout sellado | **No existe evidencia forward** **[V][L]** |

El manual también depende de dos trimestres: W1 y W4 explican la mayor parte del neto, mientras 2026 es negativo. La comparación no es un contraste pareado: el original usa `5/200/150/12`; el manual usa `10/300/210/24` y toma señales que el original no toma. Es una comparación de **carteras**, no de la misma operación ejecutada de dos formas.

### 2.3 Por qué la decisión es `keep_current`

El informe forward está en `status=insufficient_data` y su decisión es `keep_current`, con `adopted_candidate=null` y `live_config_updated=false` **[V]**. Las razones son verificables:

- No hay muestra forward independiente; el dataset de desarrollo termina el `2026-06-30` y el CSV forward no existe **[V]**.
- El holdout H1 (`2026-07-01` → `2026-10-30`) está **sellado, no ejecutado**: `executed=false`, `used_for_decision=false`, `bars_read=false` **[L]**. `[V]` lo registra como `sealed_not_executed`.
- El protocolo M/C/T está pre-registrado en `[PR]` y `[L]`, pero **no se ha ejecutado**: `status=pre_registered_not_executed`, `execution_gate.can_execute=false` **[L]**.
- P2 y P2+BE solo tienen métricas in-sample W1–W6; no son una validación forward **[V][P2][BE]**.
- El manual es el benchmark vivo, no una estrategia validada fuera de muestra. Cambiar la configuración con esta evidencia sería promocionar un resultado in-sample.

Por eso la decisión correcta hoy es **no cambiar el 8765**: mantener `10/300/210/24` y `min_stop_or_ratio=0,00`, y tratar cualquier cambio como una hipótesis que debe pasar el forward. La decisión `keep_current` no afirma que el manual sea óptimo; afirma que no hay evidencia suficiente para reemplazarlo.

### 2.4 Atribución del cohorte de stops > 200 ticks

El manual y P2 no toman las mismas entradas. P2 rechaza señales con stop superior a 200 ticks; el manual, con límite 300, las acepta. En W1–W6 el manual tiene 72 operaciones y P2 46. El artefacto de atribución cuantifica el cohorte:

| Dato | Valor | Fuente |
|---|---:|---|
| Operaciones del manual con `stop_ticks > 200` | **26** | `[M].diagnostics.stop_gt_200` |
| Neto del cohorte | **−392,60 USD** | `[M].diagnostics.stop_gt_200.net` |
| Ganadoras / perdedoras | 11 / 15 | `[M].diagnostics.stop_gt_200` |
| Stop máximo del cohorte | 297 ticks | `[M].diagnostics.stop_gt_200.max_stop_ticks` |
| P2 neto en señales comunes | 2.471,78 | `[M].diagnostics.p2_shared_net` |
| Manual neto en señales comunes | 2.415,54 | `[M].diagnostics.live_shared_net` |
| Diferencia en comunes | +56,24 a favor de P2 | `[M].diagnostics.shared_delta` |
| Diferencia total P2 − manual | **+448,84** | `[M].attribution.stop.delta_net` |

La reconciliación exacta es:

```text
448,84 = 392,60 (cohorte >200 que P2 evita) + 56,24 (mejor neto de P2 en señales comunes)
```

El cohorte no es una prueba causal: P2 no ejecuta esas 26 señales y el manual sí; además, el stop 300 cambia el riesgo y la elegibilidad. Pero sí explica por qué **P2 supera al manual en neto y DD** sin que el manual tenga “mejor ejecución”. La ventaja del manual frente al original, en cambio, procede sobre todo de frecuencia y tamaño, no del stop 300:

| Paso de atribución | Δ neto | Δ DD | Fuente |
|---|---:|---:|---|
| Original → P1 (frecuencia 210/24, 5/200) | +1.330,82 | −20,00 | `[M].attribution.sequential` |
| P1 → P2 (`max_contracts` 5→10) | +479,52 | +356,64 | `[M].attribution.sequential` |
| P2 → manual (`max_sl_ticks` 200→300) | **−448,84** | **+587,20** | `[M].attribution.sequential` |
| **Original → manual** | **+1.361,50** | **+923,84** | `[M].attribution.total`; residual 0,00 |

Conclusión: el stop 300 **no** es la fuente de la ventaja del manual; es un lastre de −448,84 USD y +587,20 USD de DD frente a P2. La ventaja frente al original viene de tomar más señales (frecuencia 210/24) y de usar 10 contratos, no de una mejor selección por stop.

---

## 3. Mejoras propuestas, priorizadas por rentabilidad

**Regla de esta sección:** no se ha aplicado ningún cambio. Las tres propuestas son hipótesis; las dos primeras pertenecen al pre-registro M/C/T y la tercera a un lock separado. Ninguna se puede ejecutar hoy: `execution_gate.can_execute=false` **[L][FL]**. El orden es por **Δneto histórico dentro de los brazos ya pre-registrados**; el RDD y los gates se usan como corrección de riesgo, no como promesa. Las cifras son in-sample.

| Orden | Cambio | Brazo / hipótesis | Δ neto vs manual | PF | DD | RDD | Estado de gate |
|---:|---|---|---:|---:|---:|---:|---|
| 1 | `max_sl_ticks: 300 → 200`; resto igual | **C** de `[L]` | **+448,84** | 1,39 | 2.304,46 | 1,0726 | PM5 histórico falla (DD > 2.000) |
| 2 | P2 + BE 1R (`be_1r_next_bar`) | **T** de `[L]` | **+13,58** | 1,48 | 1.794,46 | 1,1349 | Mejor RDD/DD, pero solo si C pasa PM |
| 3 | `min_stop_or_ratio: 0,00 → 0,25` sobre P2 | **H-P2-FILTER-STOP-OR-025** (lock separado) | **+2.179,26** | 4,25 | 946,38 | 4,4403 | 17 ops; gates históricos `INCONCLUSO`; no promocionable |

Si se ordenara estrictamente por RDD histórico, T iría primero; el orden elegido prioriza **Δneto absoluto** porque el encargo pide rentabilidad, y usa el RDD/DD como corrección. El filtro, pese a su RDD nominal, queda tercero por su baja credibilidad in-sample y por pertenecer a otro lock.

### 3.1 Prioridad 1 — C: quitar el stop 300 y quedarse en P2 `10/200/210/24`

**Cambio exacto.** En el perfil P2 (`profiles/p2_freq/config.json`), usar `risk.max_sl_ticks=200`; mantener `risk.max_contracts=10`, `strategy.setup_validity_minutes=210`, `strategy.retest_tolerance_ticks=24`, `risk.min_stop_or_ratio=0,00`, `risk.risk_per_trade_pct=1,00`, `risk.max_trades_per_day=3`, `risk.max_concurrent_positions=1` y `strategy.tp_rr=3,0`. Es el brazo **C** de `[L]` (`profile_copy: profiles/p2_freq/config.json`, `management: none`). No es un cambio al 8765; es la configuración candidata.

**Efecto histórico esperado.** Frente al manual `[M]`:

- Neto: 2.022,94 → **2.471,78** (**+448,84 USD**; +22,2 % sobre el manual).
- PF: 1,22 → **1,39**.
- DD: 2.891,66 → **2.304,46** (**−587,20 USD**).
- RDD: 0,6996 → **1,0726** (+0,3730; 1,53×).
- Expectancy R: 0,183 → **0,251**.
- Frente al original: 661,44 → 2.471,78 (**+1.810,34 USD**), DD 1.967,82 → 2.304,46 (**+336,64**), RDD 0,3361 → 1,0726.

Fuente: `[M].aggregate.live`, `[M].aggregate.p2`, `[P2].aggregate.p2.stats`; RDD y deltas calculados de esos valores.

**Riesgo principal.** C **no cumple PM5 con la muestra histórica**: el gate exige `max_drawdown_usd_candidato <= max_drawdown_usd_M` **y** `<= 2.000,0` **[L]**, y el DD histórico de C es **2.304,46 > 2.000**. Además, C rechaza las 26 señales con stop >200; la comparación M/C **no es pareada** y la ventaja de C se apoya en evitar ese cohorte, no en ejecutar mejor las mismas señales. La muestra es de 46 operaciones y el coste stress de P2 no está calculado (**n/d** en `[F]`). No hay forward.

**Condición de descarte.** Si en el forward C falla PM5, o incumple K2 (`net_C < 0,70 × net_M`, `DD_C > 1,25 × DD_M` o `DD_C > 2.500`), o incumple K5 (`net <= 0`, `PF < 1,00` o `expectancy_r < 0`), C se descarta y la decisión es `KEEP_M` **[L]**. No se cambia el umbral, la ventana ni la métrica para “arreglarlo”.

**Criterio de parada.** Los de `[L]`: `STOP-T1` por fallo de integridad, sesión prohibida o lectura del holdout; `STOP-T2` si cambia el hash del protocolo/lock/perfil/política BE; `STOP-T3` si un mes completado tiene <80 % de sesiones o >5 sesiones consecutivas perdidas; `STOP-F1` al 2029-11-30 o 742 sesiones; `STOP-F2` si falla S1–S8; `STOP-F3` si se cumple K2–K5. **No hay parada por P&L, DD, RDD ni resultado prometedor** **[L]**.

**Por qué va primero.** Es el cambio con mayor Δneto entre los brazos ya pre-registrados, el más simple de implementar (solo un parámetro) y ataca directamente el lastre identificado: el stop 300. Pero **no se aplica ahora**: el PM5 histórico ya muestra que no es promocionable con estos datos; el forward es obligatorio.

### 3.2 Prioridad 2 — T: P2 + break-even 1R

**Cambio exacto.** Mantener el perfil P2 `10/200/210/24` con `min_stop_or_ratio=0,00` y añadir la política **`be_1r_next_bar`**:

- activación cuando una vela de 1 minuto completada alcanza `MFE_R >= 1,0`;
- stop al precio de entrada redondeado al tick, efectivo desde la apertura de la vela siguiente;
- sin ejecución en la misma vela, una sola activación por operación, sin parciales, sin trailing, sin cambiar el target;
- break-even **de precio**, no contable: no incluye comisiones ni slippage.

Es el brazo **T** de `[L]` (`management: be_1r_next_bar`; `config_path: profiles/p2_freq/config.json`). La regla exacta está en `[PR]` §2.3 y en `[L].be_policy`; el hash de la política es `ee785864b4245ffbbc91e6640cb2c8461a131fc08830a71224454c5e0520fbf3`.

**Efecto histórico esperado.** Frente al manual:

- Neto: 2.022,94 → **2.036,52** (**+13,58 USD**; prácticamente plano).
- PF: 1,22 → **1,48**.
- DD: 2.891,66 → **1.794,46** (**−1.097,20 USD**).
- RDD: 0,6996 → **1,1349** (+0,4353; 1,62×).
- Expectancy R: 0,183 → **0,217**.

Frente a C: neto **−435,26** (2.036,52 vs 2.471,78), DD **−510,00** (1.794,46 vs 2.304,46), RDD **+0,0623** (1,1349 vs 1,0726), PF **+0,09**. Fuente: `[BE].baseline`, `[BE].be_1r`; `[M].aggregate.live`; RDD calculado.

**Riesgo principal.** T gana menos neto que C y que el manual; el BE recorta ganadores y convierte algunas salidas en pérdidas netas pequeñas por comisiones/slippage. Su DD histórico es el único de los tres que queda por debajo de 2.000 USD, pero **T solo puede promocionarse si C pasa PM**; la jerarquía de `[L]` no permite usar T como rescate de un C fallido. Además, la política BE **no existe versionada en el runner de producción**: vive en scripts de investigación; `execution_gate.can_execute=false` y las razones incluyen que `run_partial_exit_1r_full.py` fija `min_stop_or_ratio=0,25` y no sirve para P2 sin filtro **[L]**. Implementarla es fase 0, no un cambio de configuración.

**Condición de descarte.** Si T falla B1–B8 (por ejemplo, `net_T < 0,80 × net_C`, `total_r_T < 0,80 × total_r_C`, `DD_T > 0,85 × DD_C`, `RDD_T < 1,05 × RDD_C`, PF/expectancy insuficientes, racha >12 o bloques inconsistentes) o K3/K4, T se descarta; si C sí pasa PM y consistencia, la decisión es `ADOPT_C`; si C falla, `KEEP_M` **[L]**. No se rebaja el umbral de 1R ni se prueba 0,75/1,25.

**Criterio de parada.** Los mismos `STOP-T1/T2/T3`, `STOP-F1/F2/F3` y K3/K4 de `[L]`; sin análisis intermedio de eficacia y sin parada por P&L **[L]**.

**Por qué va segunda.** Tiene el mejor RDD histórico y el menor DD, pero su Δneto frente al manual es casi nulo y su implementación BE es la parte más costosa de la fase 0. Es una mejora de **riesgo**, no de rentabilidad absoluta; por eso no desplaza a C en un encargo que prioriza rentabilidad.

### 3.3 Prioridad 3 — Filtro `min_stop_or_ratio=0,25` sobre P2

**Cambio exacto.** Sobre P2 `10/200/210/24`, fijar `risk.min_stop_or_ratio=0,25`. No es el brazo C ni T: es la hipótesis separada **`H-P2-FILTER-STOP-OR-025`**, con su propio lock `[FL]` y su propio protocolo `docs/P2_FILTRO_STOP_OR_FORWARD.md`. No se cambia el umbral a 0,20/0,30 ni se añaden filtros de calendario.

**Efecto histórico esperado.** Frente al manual: neto 2.022,94 → **4.202,20** (**+2.179,26 USD**), PF 1,22 → **4,25**, DD 2.891,66 → **946,38** (**−1.945,28**), RDD 0,6996 → **4,4403**. Frente a P2: **+1.730,42 USD**, DD **−1.358,08**, 17 operaciones aceptadas **[F]**. Es el mayor resultado nominal de la tabla.

**Riesgo principal.** Es una selección **post hoc** sobre 17 operaciones, con 4/6 trimestres activos, cero aceptadas en 2026, top-2 trimestres = **85,28 %** del neto y top-5 trades = **61,23 %** del bruto. El bootstrap de selección es positivo (IC95 % [+0,3312, +2,3548] R, p≈0,006) pero **E2 no puede dar PASS** porque la muestra y la cobertura no alcanzan las precondiciones; el veredicto de gates es `INCONCLUSO` **[F][FG]**. No hay reprecio exacto de costes: solo una estimación uniforme (−100,80 USD), y P6 queda no evaluable **[F]**. El `PF 4,25` no es una expectativa forward.

**Condición de descarte.** Si falla E1/E2/E3 o cualquier P1–P9 del lock `[FL]` (incluidos `P3` de DD, `P5` de concentración, `P6` de costes, `P7` de cobertura y `P9` de R total), o si el bootstrap incluye cero sin evidencia negativa clara, el resultado es `FAIL` o `INCONCLUSO`; **no se promociona**. No se rescata cambiando el umbral, la ventana, los gates ni los costes.

**Criterio de parada.** El lock `[FL]` es one-shot: `no_interim_efficacy_look=true`, una sola análisis de eficacia, salida en `reports/backtest/p2_filtro_stop_or_forward/analysis.json`, que no debe existir antes de empezar. La captura se detiene si falla integridad o muestra (S1–S5); al completar 742 sesiones se hace la única análisis final; cualquier cambio sustantivo invalida el estudio y exige un lock nuevo. `can_execute=false` **[FL]**.

**Por qué va tercera aunque tenga el mayor número.** El resultado es in-sample, con 17 operaciones y gates `INCONCLUSO`; no es un brazo del pre-registro M/C/T y no se puede mezclar con la comparación manual/P2. Su prioridad es tercera por **credibilidad**, no porque su retorno histórico sea menor.

### 3.4 Recomendación única

**No cambiar el 8765 hoy.** La primera acción es cerrar la fase 0 del pre-registro M/C/T (política BE versionada y testeada, captura prospective, hashes, preflight, runner one-shot y lock de ejecución) y ejecutar el forward cuando `can_execute` pase a verdadero con un lock nuevo. Dentro de ese protocolo:

1. **C** (`10/200/210/24`, `min_stop_or_ratio=0,00`) es la primera hipótesis por Δneto histórico.
2. **T** (P2 + `be_1r_next_bar`) es la segunda, por RDD y DD, y solo puede promocionarse si C pasa PM.
3. El **filtro 0,25** es una hipótesis separada, con su propio lock, y se evalúa después; no se usa para rescatar C ni T.

Si C falla PM5, la regla es **`KEEP_M`**: no se cambia el manual y no se promociona T como sustituto. La recomendación no promete ninguno de los resultados históricos; solo ordena qué hipótesis probar primero y con qué evidencia.

---

## 4. Integridad, holdout y verificación final

### 4.1 Estado sellado

| Comprobación | Valor | Fuente |
|---|---|---|
| Holdout H1 | `2026-07-01` → `2026-10-30`, 85 sesiones | `[V].holdout` |
| `executed` | **false** | `[L].holdout`; `[V].holdout` |
| `used_for_decision` | **false** | `[L].holdout`; `[V].holdout` |
| `bars_read` | **false** | `[L].holdout` |
| Estado | `sealed_not_executed` / `frozen-not-executed` | `[V].holdout`; `[PL]` |
| `execution_gate.can_execute` | **false** | `[L].execution_gate`; `[V].protocols.p2_be_manual_forward.can_execute` |
| Forward ejecutado | **no**; `status=pre_registered_not_executed` | `[L]`; snapshot `[S].constraints` |
| Captura iniciada | **no** | `[S].constraints`; `[M].constraints.capture_started=false` |
| Backtest en este cierre | **no** | `[S].constraints` |

### 4.2 Hashes protegidos y verificación

Los hashes de configuración y locks se comprobaron antes y después de escribir el memo; no cambiaron:

```text
data/config.json                    9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f
profiles/live_8765/config.json     9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f
profiles/p2_freq/config.json       ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb
docs/protocolo_backtest.lock.json  55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c
docs/p2_be_1r_forward.lock.json    ad72a200943febc2382e40372d199b8a7fda2d78fa67818e96c27be779735dd5
docs/p2_filtro_stop_or_forward.lock.json d1a2c87b1a855d2040347dbc513711302fd3a4d667ffeb24ca4ae4861719fb01
```

La configuración de la API (`d3cff10d…`) coincide con el canónico de `data/config.json` y de `profiles/live_8765/config.json`; el archivo `profiles/p2_freq/config.json` solo difiere en `max_sl_ticks=200` **[S]**. Los locks del protocolo no se modificaron.

### 4.3 Checks de cierre

| Check | Comando | Resultado |
|---|---|---|
| Backend focalizado | `python -m pytest tests/test_forward_validation.py -q` | Se ejecuta al cerrar; ver salida final |
| Frontend | `cd frontend && npm test -- --run` | Se ejecuta al cerrar; ver salida final |
| Build frontend | `cd frontend && npm run build` | Se ejecuta al cerrar; ver salida final |
| Whitespace del diff | `git diff --check` | Se ejecuta al cerrar; ver salida final |
| JSON del snapshot | `python -m json.tool reports/backtest/live_8765_decision_check.json > /dev/null` | Debe pasar |

### 4.4 Limitaciones que quedan abiertas

- **No hay forward:** el memo no puede afirmar que C, T o el filtro sean rentables hacia adelante; solo reporta la evidencia in-sample.
- **El coste del manual y de P2 no está repreciado:** el stress exacto del original es 347,38 USD neto y PF 1,07; para el manual y P2 es `n/d` **[F]**. No se presenta un PF neto de costes que no exista.
- **La significancia es insuficiente:** el IC95 % del delta manual-original incluye cero y p=0,6544; con 72/38 operaciones no se puede declarar una ventaja estadística **[M]**.
- **La ruta del perfil no es visible en el `CommandLine` actual:** se apoya en el lanzador registrado y en la coincidencia exacta de hashes; los dos archivos candidatos son idénticos, por lo que el perfil efectivo es el manual en cualquier caso.
- **Las métricas de runtime se mueven:** 45 trades a las 06:26:30Z; pueden cambiar. No son la muestra W1–W6 ni una validación.
- **El motor sigue corriendo en paper:** no se reinició ni se modificó; cualquier cambio de configuración sigue siendo un acto separado y no autorizado por este memo.

**Estado final del encargo:** memo único en `docs/MANUAL_8765_DECISION_MEMO.md`; configuración viva identificada; comparación manual/original trazada; tres mejoras priorizadas con brazo, parámetros, efecto, riesgo, descarte y parada; holdout sellado; `execution_gate.can_execute=false`. No se hizo commit ni push.
