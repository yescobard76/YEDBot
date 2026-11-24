# Rentabilidad del bot manual 8765 frente al original y los perfiles P1 congelados

**Fecha de cierre:** 2026-11-24
**Estado:** informe de solo lectura; no se ejecutaron backtests nuevos ni se modificó ninguna configuración, DB o holdout.
**Alcance:** instancia HTTP `127.0.0.1:8765`, configuración original establecida por el protocolo y perfiles P1 congelados `control` y `filtro 0,25`.
**Veredicto corto:** en la muestra histórica W1–W6 el bot manual gana más dinero absoluto que el original, pero tiene peor drawdown y peor profit factor que P1; el filtro 0,25 es el mejor resultado histórico, pero tiene solo 17 operaciones, es in-sample y **no tiene validación forward**. No se promociona ni se cambia la configuración viva.

La evidencia viva completa está congelada en [`manual_8765_live_snapshot.json`](manual_8765_live_snapshot.json).

---

## 1. Identificación de la configuración viva del 8765

### 1.1 Proceso, puerto y archivo

Lectura realizada el 2026-11-24:

| Elemento | Valor observado |
|---|---|
| Listener | `127.0.0.1:8765` |
| PID que escucha | `15108` (`python.exe`) |
| Comando del proceso | `python.exe -u run.py` |
| Lanzador | `YED_PORT=8765 YED_PROFILE_DIR="$PWD/profiles/live_8765" YED_OPEN=0 python -u run.py` |
| Configuración activa | `profiles/live_8765/config.json` |
| DB del perfil | `profiles/live_8765/yedbot.db` |
| Estado del motor | `stopped` (el servidor HTTP responde; el motor no está operando) |
| Modo | `paper` |
| Feed | CSV histórico `data/bars.csv`, serie ajustada, 151.530 velas 1m |

La ruta se deduce directamente del entorno: `YED_PROFILE_DIR` apunta a `profiles/live_8765`; `server/config.py` define `CONFIG_PATH = PROFILE_DIR / "config.json"` y `DB_PATH = CONFIG_PATH.parent / "yedbot.db"`. La API `GET /api/config` devuelve exactamente los mismos `settings` que ese archivo. **No hay discrepancia entre la configuración viva y un archivo del repo.**

`data/config.json` tiene el mismo contenido y hash que `profiles/live_8765/config.json`, pero el proceso vivo está usando explícitamente la copia de `profiles/live_8765` por el `YED_PROFILE_DIR` del lanzador. La copia es la que debe considerarse configuración activa.

### 1.2 Hashes

| Objeto | SHA-256 |
|---|---|
| Archivo vivo `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `config_sha256` canónico de la configuración viva | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` |
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| Original: archivo `profiles/backtest_real/config.json` | `8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f` |
| Original: configuración canónica 150/12 en memoria | `87b8b9f18dbce9e4739112cf734850fe75de7e82e7548425d246027d2234e708` |
| P1 control: archivo | `8058b7d7002de547a535a349dbe7f3557e4aaea1e92d392b064dd51b0b8b624b` |
| P1 control: `config_sha256` | `5527b32cd54353c52968a47fb84471b7012846cefa06413349bcba7085e7e087` |
| P1 filtro 0,25: archivo | `9bdde4dbc58d980419399e10c07b851765a66102cb52c0c4af727bfb0cecb27c` |
| P1 filtro 0,25: `config_sha256` | `061f87b8548ab53229e50455e1004bd189c5ef356521d3cf99e084f63b80e32c` |

El hash de archivo identifica los bytes exactos; el `config_sha256` es el hash canónico de la configuración de trading y excluye `feed`, `live` y `mode` (`server/experiments.py::config_sha256`). Por eso no son iguales.

### 1.3 Configuración viva resumida

| Campo | Valor vivo |
|---|---:|
| `risk.max_contracts` | **10** |
| `risk.max_sl_ticks` | **300** |
| `risk.min_stop_or_ratio` | **0,00** |
| `strategy.setup_validity_minutes` | **210** |
| `strategy.retest_tolerance_ticks` | **24** |
| `risk.risk_per_trade_pct` | 1,0 |
| `risk.max_trades_per_day` | 3 |
| `risk.max_concurrent_positions` | 1 |
| `risk.max_daily_loss_pct` | 3,0 |
| `strategy.entry_reference` | `or_mid` |
| `strategy.tp_rr` | 3,0 |
| `feed.series_mode` | `adjusted` |
| `feed.loop_sessions` | `true` |
| `feed.replay_speed` | 8,0 |
| `live.live_enabled` | `false` |

La configuración viva es el perfil **manual 10/300/210/24**, sin filtro. No es P2 (que usa SL 200) ni P1 (que usa 5 contratos).

---

## 2. Comparación campo a campo

### 2.1 Referencias comparadas

- **Vivo:** `profiles/live_8765/config.json`, idéntico a `data/config.json`, cargado por el proceso del 8765.
- **Original establecido:** configuración canónica del protocolo, `5/200/150/12`, definida en `docs/protocolo_backtest.lock.json` y en `reports/backtest/_manual_common.py` (`ORIGINAL_FREQUENCY_PATCH`). El archivo `profiles/backtest_real/config.json` contiene actualmente 210/24; por eso el original se fija en memoria a 150/12 sin modificar el archivo. El `README` de backtests documenta esta discrepancia.
- **P1 control:** `profiles/p1_forward_control/config.json`, P2 con `max_contracts=5`, `max_sl_ticks=200`, frecuencia 210/24 y ratio 0,00.
- **P1 filtro 0,25:** `profiles/p1_forward_filter025/config.json`, exactamente P1 control con `min_stop_or_ratio=0,25`.

### 2.2 Tabla de parámetros relevantes

| Parámetro | Vivo 8765 | Original 5/200/150/12 | P1 control | P1 filtro 0,25 |
|---|---:|---:|---:|---:|
| `risk.max_contracts` | **10** | 5 | 5 | 5 |
| `risk.max_sl_ticks` | **300** | 200 | 200 | 200 |
| `strategy.setup_validity_minutes` | **210** | 150 | 210 | 210 |
| `strategy.retest_tolerance_ticks` | **24** | 12 | 24 | 24 |
| `risk.min_stop_or_ratio` | **0,00** | 0,00 | 0,00 | **0,25** |
| `risk.risk_per_trade_pct` | 1,0 | 1,0 | 1,0 | 1,0 |
| `risk.max_trades_per_day` | 3 | 3 | 3 | 3 |
| `risk.max_concurrent_positions` | 1 | 1 | 1 | 1 |
| `risk.max_daily_loss_pct` | 3,0 | 3,0 | 3,0 | 3,0 |
| `strategy.entry_reference` | `or_mid` | `or_mid` | `or_mid` | `or_mid` |
| `strategy.tp_rr` | 3,0 | 3,0 | 3,0 | 3,0 |
| `feed.provider` | `csv` | `csv` | `csv` | `csv` |
| `feed.csv_path` | `data/bars.csv` | `data/bars.csv`* | `data/forward/2026-12-01_p1_filter025/bars_forward.csv` | igual que P1 control |
| `feed.series_mode` | `adjusted` | `adjusted`* | `raw` | `raw` |
| `feed.loop_sessions` | `true` | `true`* | `false` | `false` |
| `feed.replay_speed` | 8,0 | 4,5* | 1,0 | 1,0 |
| `live.live_enabled` | `false` | `false` | `false` | `false` |

\* El original canónico del lock usa un feed raw de protocolo; los artefactos W1–W6 se calcularon sobre el dataset común `data/bars.csv` en modo ajustado. El feed es operativo y no forma parte de `config_sha256`; la comparación de edge se hace por estrategia y riesgo.

### 2.3 Diff exacto: vivo contra original

El diff recursivo de la configuración de trading devuelve exactamente **5 rutas**:

```text
feed.replay_speed:                 8.0  -> 4.5
risk.max_contracts:               10    -> 5
risk.max_sl_ticks:               300    -> 200
strategy.retest_tolerance_ticks:  24    -> 12
strategy.setup_validity_minutes:  210   -> 150
```

Todo lo demás es idéntico: `orb`, `smt`, geometría de entrada, `tp_rr`, límites diarios, ejecución, comisiones, capital inicial, ventana de trading y `live`.

**Efecto histórico observado (no forward):** la frecuencia 210/24 y el SL 200 de P1, frente al original 150/12, producen +1.330,82 USD y −20,00 USD de DD en W1–W6 (`_manual_w1_w6_analysis.log`). El cambio de SL 300→200, comparado con el manual de 10 contratos, produce +448,84 USD y −587,20 USD de DD (misma fuente). El cambio de 10→5 contratos reduce el neto en 479,52 USD y el DD en 356,64 USD (P2→P1).

### 2.4 Diff exacto: vivo contra P1 control

**6 rutas:**

```text
feed.csv_path:       data/bars.csv -> data/forward/2026-12-01_p1_filter025/bars_forward.csv
feed.loop_sessions:  true -> false
feed.replay_speed:   8.0 -> 1.0
feed.series_mode:    adjusted -> raw
risk.max_contracts:  10 -> 5
risk.max_sl_ticks:   300 -> 200
```

El resto de la configuración de trading es idéntico. La frecuencia 210/24 y la geometría de entrada no cambian. Los cambios de feed no son una ventaja de estrategia: son la preparación operativa del forward, y el CSV forward **no existe todavía**.

**Efecto histórico observado:** P1 control hace 46 operaciones, +1.992,26 USD, PF 1,37 y DD 1.947,82; el vivo hace 72 operaciones, +2.022,94 USD, PF 1,22 y DD 2.891,66. El vivo gana solo +30,68 USD más, pero asume +943,84 USD más de drawdown y baja el PF. En rentabilidad ajustada por riesgo, P1 control domina al vivo; en neto absoluto, el vivo gana por 30,68 USD, dentro de una muestra pequeña.

### 2.5 Diff exacto: vivo contra P1 filtro 0,25

**7 rutas:** las 6 anteriores más:

```text
risk.min_stop_or_ratio: 0.0 -> 0.25
```

El filtro no cambia nada más. P1 control y P1 filtro solo difieren en `risk.min_stop_or_ratio`; el verificador `scripts/verify_p1_forward_profiles.py` lo comprueba y devuelve `PASS`.

**Efecto histórico observado:** P1 filtro hace 17 operaciones, +4.202,20 USD, PF 4,25 y DD 946,38; frente a P1 control son +2.209,94 USD y −1.001,44 USD de DD. Es el mejor resultado de la muestra, pero también el de menor muestra y el más dependiente de una selección in-sample.

### 2.6 Resumen de diferencias

| Comparación | Nº de rutas distintas | Diferencia principal |
|---|---:|---|
| Vivo vs original | 5 | Contratos, SL, frecuencia y replay |
| Vivo vs P1 control | 6 | Contratos, SL y feed forward |
| Vivo vs P1 filtro | 7 | Lo anterior + filtro 0,25 |
| P1 control vs P1 filtro | 1 | Solo `risk.min_stop_or_ratio` |

---

## 3. Valoración de rentabilidad con datos existentes

### 3.1 Muestra y fuentes

Todos los datos económicos son **históricos in-sample W1–W6**, 2025-01-10 → 2026-06-30, 362 sesiones. No se ejecutó ningún backtest nuevo. El holdout H1 2026-07-01 → 2026-10-30 (85 sesiones) sigue **sellado y no ejecutado**. No hay P&L live: el motor del 8765 está detenido.

| Perfil | Configuración | Ops | Neto USD | PF | DD USD | DD % | Expectativa USD/op | R total |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Original | 5/200/150/12 | 38 | **+661,44** | 1,13 | 1.967,82 | 7,14 % | +17,41 | +4,98 |
| **Vivo 8765** | **10/300/210/24** | **72** | **+2.022,94** | **1,22** | **2.891,66** | **9,79 %** | **+28,10** | **+13,19** |
| P1 control | 5/200/210/24 | 46 | +1.992,26 | 1,37 | 1.947,82 | 6,75 % | +43,31 | +11,56 |
| **P1 filtro 0,25** | **5/200/210/24 + 0,25** | **17** | **+4.202,20** | **4,25** | **946,38** | **3,36 %** | **+247,19** | **+18,85** |
| P2 (contexto) | 10/200/210/24 | 46 | +2.471,78 | 1,39 | 2.304,46 | 7,84 % | +53,73 | +11,56 |
| P2 filtro 0,25 (contexto) | 10/200/210/24 + 0,25 | 17 | +4.202,20 | 4,25 | 946,38 | 3,36 % | +247,19 | +18,85 |

Fuentes exactas:

- Original 38 y P2 46: `reports/backtest/p2_w1_w6_confirm.json`, claves `aggregate.original` y `aggregate.p2`.
- Vivo 72 y P1 46: `reports/backtest/_manual_w1_w6_analysis.log`, tabla `AGREGADO W1-W6`; el vivo también aparece en `reports/backtest/forward_validation.json` (`manual_8765`).
- P1 filtro 17: `reports/backtest/_manual_filter025_w1_w6.json`, `aggregate.filter025_max5`. El artefacto declara `invariant_max10_eq_max5: true`; su `config_sha256` de trading es `061f87b8…`, idéntico al perfil P1 filtro congelado. No es una extrapolación: es la variante max5 ya ejecutada en W1–W6.
- Gates y veredicto: `reports/backtest/filter025_gates.json` y `reports/backtest/FILTER025_GATES.md`.

### 3.2 Lectura económica

- **Vivo vs original:** +1.361,50 USD más de neto (+205,9 %), pero +923,84 USD más de drawdown y PF 1,22 frente a 1,13. Gana más en absoluto, no mejora la calidad por unidad de riesgo.
- **Vivo vs P1 control:** +30,68 USD de neto, pero +943,84 USD de DD y PF 1,22 frente a 1,37. El vivo está dominado por P1 en rentabilidad ajustada por riesgo.
- **P1 control vs original:** +1.330,82 USD y −20,00 USD de DD; el cambio de frecuencia 210/24 es el bloque histórico más consistente de la muestra.
- **P1 filtro vs P1 control:** +2.209,94 USD y −1.001,44 USD de DD, con 17 operaciones frente a 46. La mejora es real en la muestra, pero se apoya en evitar el cohorte perdedor y en no operar en 2026.
- **P2 vs P1:** +479,52 USD y +356,64 USD de DD por usar 10 contratos en lugar de 5. Es apalancamiento, no una mejora de edge.

No se extrapola ninguna de estas cifras a 2026-07-01 en adelante. La muestra es in-sample y el forward no existe.

### 3.3 Concentración, cobertura y gates

El filtro 0,25 tiene 17 operaciones y solo 4/6 trimestres activos; W5 y W6 de 2026 están vacíos. El top-2 de trimestres explica el 85,28 % del neto (el gate Q3 exige ≤80 %) y el top-5 de trades el 61,23 % del bruto. Los gates globales están **INCONCLUSO**: 13 PASS, 4 FALLA, 5 INCONCLUSO y 1 NO_EVALUABLE; la decisión es **NO promocionar** (`filter025_gates.json`).

### 3.4 Forward: pendiente, no una cifra

- `data/forward/2026-12-01_p1_filter025/bars_forward.csv` **no existe**.
- `reports/backtest/forward_validation.json` declara `status="insufficient_data"`, `available_sessions=0`, `available_bars=0`; el dataset termina el **2026-06-30**.
- La ventana pre-registrada empieza el **2026-12-01** y el holdout H1 sigue sellado.
- Por tanto, **no hay ninguna cifra forward de P1 control, P1 filtro, P2 ni del vivo**. No se estima ni se anualiza el resultado histórico.

### 3.5 Veredicto de rentabilidad

**En W1–W6, el vivo es más rentable en neto absoluto que el original, pero P1 control es superior en PF y DD, y P1 filtro es el mejor resultado histórico.** La afirmación correcta es:

> “Mejor neto histórico observado en el perfil manual, con peor drawdown y peor PF que P1; el filtro 0,25 tiene el mejor neto histórico, pero 17 operaciones, es in-sample y no tiene validación forward.”

No se puede afirmar que el vivo sea más rentable hacia adelante, ni que el filtro sea promocionable. La confianza predictiva es **baja/indeterminada**.

---

## 4. Mejoras priorizadas por impacto en rentabilidad

Ninguna mejora está implementada. No se modifican la configuración viva, los perfiles congelados, el filtro, los umbrales, la DB ni el holdout. El orden combina **Δ neto in-sample medido, robustez de la muestra y confianza**. El filtro tiene el mayor Δ bruto, pero se coloca #2 por sus 17 operaciones y gates INCONCLUSO.

| # | Mejora | Δ neto histórico | Δ DD | Evidencia | ¿Se puede medir con P1 congelado? |
|---|---|---:|---:|---|---|
| 1 | Bajar `max_sl_ticks` de 300 a 200 manteniendo 10 contratos (P2) | **+448,84 vs vivo**; +1.810,34 vs original | **−587,20** | `_manual_w1_w6_analysis.log` | No de forma aislada: P1 control es max5; haría falta un P2 forward o un control P1 con max10 |
| 2 | Validar el filtro `min_stop_or_ratio=0,25` en P1 | **+2.209,94 vs P1 control**; +1.730,42 vs P2 | **−1.001,44 vs P1** | `_manual_filter025_w1_w6.json` | Sí: P1 control vs P1 filtro, mismo feed, único diff |
| 3 | Reprecio exacto de comisiones y slippage | No aumenta el bruto; protege 100,80–314,06 | PF/DD exactos pendientes | `FILTER025_PROFITABILITY.md`, `stress_costs.json` | Sí: repreciar los trades P1; medir P6 |
| 4 | Añadir cobertura de regímenes sin bajar el 0,25 | No cuantificable | No cuantificable | `filter025_gates.json`; cero aceptadas en 2026 | No con dos perfiles; requiere sleeve/protocolo nuevo |
| 5 | Reducir concentración trimestral | No cuantificable | Objetivo: DD/PF | Q3 85,28 %; top-5 61,23 % | Parcial: medir Q2/Q3/P5 en P1 forward |

### Prioridad 1 — Eliminar el lastre del SL 300

**Parámetro:** `risk.max_sl_ticks` 300 → 200. Mantener `max_contracts=10` si el objetivo es neto absoluto; pasar a P1 control (max5) si el objetivo es menor DD.

**Razonamiento:** el manual con SL 300 añade 26 operaciones frente a P2, pero resta 448,84 USD y suma 587,20 USD de DD. P2 es el mejor perfil de 46 operaciones: +2.471,78 USD, PF 1,39, DD 2.304,46. El vivo, con 10 contratos y SL 300, queda en +2.022,94, PF 1,22 y DD 2.891,66: el SL 300 se come casi todo el beneficio adicional de los 10 contratos.

**Riesgo:** el SL 200 puede aumentar los stops prematuros en regímenes de volatilidad alta; el DD absoluto de P2 sigue siendo 2.304,46 y la muestra es de 46 operaciones, por debajo de S2 (≥60). El cambio es in-sample.

**Medición forward:** el P1 congelado no aísla este cambio porque usa max5. Para medirlo haría falta un P2 forward (`10/200/210/24`) o un P1 con `max_contracts=10`; ninguno de los dos está entre los dos perfiles creados. Con P1 control se puede medir el efecto de SL200 a 5 contratos, no el de 10. No se crea ese perfil en este encargo.

### Prioridad 2 — Validar el filtro 0,25 sin tocar el umbral

**Parámetro/regla:** `risk.min_stop_or_ratio=0,25`, fijo. No probar 0,20/0,30 ni filtros de calendario.

**Razonamiento:** es la mayor mejora histórica: P1 filtro +4.202,20 frente a P1 +1.992,26, con DD 946,38 frente a 1.947,82. El artefacto `filter025_max5` ya es la configuración exacta del P1 filtro congelado (`config_sha256` `061f87b8…`). Pero la muestra es 17 operaciones, 4/6 trimestres activos y cero aceptadas en 2026; los gates están INCONCLUSO y la decisión es NO promocionar.

**Riesgo:** sobreajuste al cohorte W1–W6; el resultado puede ser “no operar en 2026” más que una selección repetible. La mejora de W1/W2 es negativa frente a P2; la mayor parte viene de evitar W3/W5/W6.

**Medición forward:** es la comparación directa que habilitan los dos perfiles congelados:

1. mismo CSV forward sellado;
2. P1 control vs P1 filtro;
3. único diff `risk.min_stop_or_ratio`;
4. mínimos S2 ≥60 baseline, S3 ≥24 aceptadas y ≥30 rechazadas, S4 ≥5/6 bloques, Q1 ≥5/6 trimestres, Q3 ≤80 %, Q4 ≥5/6, P7 racha ≤4 meses, P6 coste exacto;
5. sin análisis intermedio ni cambio de umbral.

Hoy no se puede ejecutar: `bars_forward.csv` no existe y hay 0 sesiones forward.

### Prioridad 3 — Reprecio exacto de costes

**Parámetro/regla:** comisión 1,24/lado y slippage 2 en el reprecio; no cambiar la estrategia.

**Razonamiento:** el original pierde 314,06 USD y baja de PF 1,13 a 1,07 con el stress exacto; el filtro solo tiene una estimación uniforme de −100,80 USD y PF 4,0811. P6 está NO_EVALUABLE. Un PF alto puede ocultar un coste por operación desproporcionado.

**Riesgo:** el filtro puede seguir siendo rentable, pero el PF bajará; no se debe promocionar con el PF base. No aumenta el neto bruto: evita sobreestimarlo.

**Medición forward:** repreciar los mismos fills de P1 control y P1 filtro con coste exacto; evaluar P6, E3 y P2 después de costes. Sin P6 no hay PASS de costes.

### Prioridad 4 — Cobertura para regímenes sin aceptadas

**Regla:** una segunda fuente de señal o sleeve independiente, no una relajación del 0,25.

**Razonamiento:** el filtro no opera en 2026 y tiene una racha de 6 meses sin aceptadas. Bajar el umbral estaría prohibido y no está justificado por los datos. La cobertura es el problema estructural que los gates Q1/Q4/P7 detectan.

**Riesgo:** correlación con el mismo ORB, más operaciones y más DD; podría diluir el PF. No hay evidencia actual de que la señal adicional exista.

**Medición forward:** protocolo nuevo con su propio pre-registro; no se puede medir con los dos perfiles actuales. Exigiría una muestra forward independiente y gates S3/Q1/Q4/P7.

### Prioridad 5 — Reducir concentración sin recortar ganadores

**Regla:** diversificar la fuente de retorno o la asignación de riesgo; no añadir un stop/objetivo que recorte los ganadores solo para bajar el porcentaje.

**Razonamiento:** Q3 falla con 85,28 % del neto en dos trimestres; top-5 trades = 61,23 % del bruto. La concentración es un síntoma de falta de amplitud.

**Riesgo:** el efecto sobre el neto es incierto y podría ser negativo. Por eso queda por debajo de las propuestas con Δ positivo medido.

**Medición forward:** P1 filtro y P1 control por trimestre; Q2/Q3/P5; comparar neto, DD y PF. Si baja el neto sin mejorar DD/PF, se descarta.

### Alternativa de control de riesgo (no primera por neto)

**P1 control (5 contratos, SL200) frente al vivo:** −30,68 USD de neto, pero −943,84 USD de DD y PF 1,37 frente a 1,22. No es una mejora de rentabilidad absoluta; es una mejora de calidad de riesgo. Si la prioridad cambia de “máximo neto” a “menor drawdown”, P1 control es la referencia congelada adecuada.

---

## 5. Restricciones y verificación

- **Configs existentes:** no modificadas. `data/config.json`, `profiles/live_8765/config.json`, `profiles/backtest_real/config.json`, `profiles/p2_freq/config.json` y los perfiles operativos P1 conservan sus hashes.
- **DB:** no se escribió, migró ni reinició ninguna base. La DB viva es `profiles/live_8765/yedbot.db`; este informe no la consultó para leer trades ni modificó su contenido.
- **Holdout:** H1 2026-07-01 → 2026-10-30 sigue sellado; `forward_validation.json` lo registra como `sealed_not_executed`.
- **Backtests nuevos:** cero. Solo se leyeron artefactos JSON/log y la API viva en modo lectura.
- **Verificador P1:** `python scripts/verify_p1_forward_profiles.py` devuelve `PASS`; P1 control y P1 filtro solo difieren en `risk.min_stop_or_ratio`.

### Reproducir la evidencia viva

```bash
curl http://127.0.0.1:8765/api/config
curl http://127.0.0.1:8765/api/status
python scripts/verify_p1_forward_profiles.py
```

La instantánea [`manual_8765_live_snapshot.json`](manual_8765_live_snapshot.json) contiene los `settings` completos, los diffs exactos, los hashes y el estado de constraints.

### Fuentes principales

| Fuente | Uso |
|---|---|
| `profiles/live_8765/config.json` | Configuración viva real |
| `server/config.py` | Derivación de `CONFIG_PATH` y `DB_PATH` desde `YED_PROFILE_DIR` |
| `profiles/p1_forward_control/config.json` | P1 control congelado |
| `profiles/p1_forward_filter025/config.json` | P1 filtro congelado |
| `profiles/p1_forward.lock.json` | Hashes y diff de los P1 |
| `reports/backtest/p2_w1_w6_confirm.json` | Original 38 y P2 46 |
| `reports/backtest/_manual_w1_w6_analysis.log` | Vivo 72 y P1 46; atribución |
| `reports/backtest/_manual_filter025_w1_w6.json` | P1 filtro 17; `filter025_max5` |
| `reports/backtest/filter025_gates.json` | Gates: INCONCLUSO, promoción NO |
| `reports/backtest/forward_validation.json` | Forward 0 sesiones; holdout sellado |
| `reports/backtest/FILTER025_PROFITABILITY.md` | Análisis comparado y propuestas previas |
| `docs/protocolo_backtest.lock.json` | Original canónico 5/200/150/12 |

**Conclusión:** el bot manual del 8765 es más rentable en neto absoluto que el original en W1–W6, pero no es superior a P1 en PF/DD; el filtro 0,25 es el mejor resultado histórico, aunque in-sample y sin forward. La decisión operativa es **mantener la configuración viva sin cambios** y no promover nada hasta que exista muestra forward.
