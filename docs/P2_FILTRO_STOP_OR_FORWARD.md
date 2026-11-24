# Plan forward pre-registrado — filtro stop/ORB 0,25 sobre P2

**Versión:** 1.1  
**Fecha:** 2026-11-23  
**Revisión:** 2026-11-24 — corrige el alcance contractual: el forward necesita el universo Z26–Z29 (39 contratos, 36 rolls); no basta con extender QUARTERS (H25–Z26), porque exigiría 60. Sin cambios de hipótesis, muestra, perfil ni puertas.  
**Estado:** pre-registrado y **no ejecutado**. No se ha leído ninguna barra nueva, no se ha ejecutado ningún paper forward y el holdout `2026-07-01 → 2026-10-30` sigue sellado.  
**Lock:** [`p2_filtro_stop_or_forward.lock.json`](p2_filtro_stop_or_forward.lock.json).  
**Hipótesis:** `H-P2-FILTER-STOP-OR-025`.  
**Perfil base:** [`profiles/p2_freq/config.json`](../profiles/p2_freq/config.json).

> Este documento no modifica `data/config.json`, `profiles/backtest_real/config.json`, la DB, el protocolo v1.2, sus locks ni el holdout. No autoriza LIVE ni paper en tiempo real. No reutiliza W1–W6 como validación: las usa solo como motivación in-sample.

---

## 1. Hipótesis y endpoints

### 1.1 Hipótesis

**H1 (alternativa):** en una muestra forward independiente, las operaciones de P2 con `stop_ticks / orb_width_ticks >= 0,25` tienen una esperanza en R mayor que las operaciones con ratio `< 0,25`; eliminar el cohorte inferior mejora el R total y el drawdown sin reducir la actividad a un nivel inutilizable.

**H0 (nula):** la diferencia de selección es menor o igual a cero, o el cohorte eliminado tiene R total positivo, o el filtro no supera las puertas de cartera, consistencia, costes o participación.

### 1.2 Estimando primario

Sea `B` el conjunto de operaciones del brazo control (P2 sin filtro) en la muestra forward. Para cada operación `i ∈ B`:

```text
ratio_i = stop_ticks_i / orb_width_ticks_i
A  = { i ∈ B : ratio_i >= 0,25 }   (aceptadas)
Rj = { i ∈ B : ratio_i < 0,25 }    (rechazadas)

Δ_sel = media(R_i para i ∈ A) − media(R_i para i ∈ Rj)
```

- Unidad de observación: operación.
- Unidad de remuestreo: sesión (hasta 3 operaciones por día).
- `R_i` es el múltiplo de riesgo neto de comisiones y slippage, calculado por el motor; no se recalcula a mano.
- El umbral **0,25 está fijado**. No se prueban 0,20, 0,30 ni ninguna otra rejilla.

### 1.3 Endpoint secundario de cartera

```text
Δ_total_R = suma(R_i para i ∈ A) − suma(R_i para i ∈ B)
          = −suma(R_i para i ∈ Rj)
```

Exigir que el filtro no empeore el R total equivale a exigir que **el cohorte rechazado tenga R total ≤ 0**. También se ejecuta el brazo de tratamiento real (`min_stop_or_ratio=0,25`) sobre el mismo dataset, para medir la interacción con el límite de pérdida diaria, el cooldown y el dimensionamiento. Ese brazo es una **puerta de cartera**, no el endpoint primario.

---

## 2. Brazos y configuración congelada

| Elemento | Control C | Tratamiento T |
|---|---|---|
| Perfil base | `profiles/p2_freq/config.json` | `profiles/p2_freq/config.json` |
| `risk.min_stop_or_ratio` | 0,00 | **0,25** |
| `risk.max_sl_ticks` | 200 | 200 |
| `risk.max_contracts` | 10 | 10 |
| `strategy.setup_validity_minutes` | 210 | 210 |
| `strategy.retest_tolerance_ticks` | 24 | 24 |
| `risk.risk_per_trade_pct` | 1,0 | 1,0 |
| `feed.series_mode` forward | `raw` | `raw` |
| `feed.exclude_roll_sessions` | `true` | `true` |
| `live.live_enabled` | `false` | `false` |

**Único cambio permitido:** `risk.min_stop_or_ratio`. Todo lo demás se hereda del perfil P2 y debe coincidir exactamente. El P2 de backtest usa `data/bars.csv` y `series_mode=adjusted`; para el forward se sustituye **solo el feed** por el CSV forward `raw`:

- `feed.provider=csv`
- `feed.csv_path=reports/backtest/p2_filtro_stop_or_forward/bars_forward.csv`
- `feed.series_mode=raw`
- `feed.exclude_roll_sessions=true`
- `feed.loop_sessions=false`
- `live.live_enabled=false`

Ese cambio de feed es idéntico en ambos brazos; no es una diferencia de tratamiento. Se usa `raw` para evitar que el ajuste de rolls contamine la base NQ/MNQ, igual que en el protocolo forward original. Cualquier cambio de código que afecte estrategia, filtro, salidas, riesgo o ejecución invalida este diseño y exige un lock nuevo.

### 2.1 Por qué P2 y no la configuración original

P2 conserva los cambios de frecuencia que sí aportaron neto con el riesgo original:

- `setup_validity_minutes=210` y `retest_tolerance_ticks=24`.
- `max_sl_ticks=200` (no 300): el 300 añadía 26 operaciones que en W1–W6 perdían 448,84 USD y subían el DD en 587,20.
- `max_contracts=10` (no 5): es una decisión de apalancamiento, no de edge; con el filtro 0,25 todas las aceptadas tienen qty ≤5, así que el filtro hace irrelevante el 10.

---

## 3. Muestra

### 3.1 Ventana y bloques

| Bloque | Desde | Hasta | Sesiones de calendario | Rolls excluidos | Sesiones evaluadas |
|---|---|---:|---:|---:|---:|
| F1 | 2026-12-01 | 2027-05-31 | 124 | 2 | 122 |
| F2 | 2027-06-01 | 2027-11-30 | 127 | 2 | 125 |
| F3 | 2027-12-01 | 2028-05-31 | 125 | 2 | 123 |
| F4 | 2028-06-01 | 2028-11-30 | 127 | 2 | 125 |
| F5 | 2028-12-01 | 2029-05-31 | 124 | 2 | 122 |
| F6 | 2029-06-01 | 2029-11-30 | 127 | 2 | 125 |
| **Total** | **2026-12-01** | **2029-11-30** | **754** | **12** | **742** |

- La ventana se fija antes de capturar. **No se desplaza** si la captura empieza tarde: si no se puede empezar el 2026-12-01, se redacta un lock nuevo con otra ventana y otra muestra.
- **Burn-in:** `2026-11-23 → 2026-11-30`, excluido del análisis. Solo sirve para probar captura, validación y sellado; no se usa para elegir nada.
- Las 12 fechas de roll previstas: `2026-12-10`, `2027-03-11`, `2027-06-09`, `2027-09-09`, `2027-12-09`, `2028-03-09`, `2028-06-08`, `2028-09-07`, `2028-12-07`, `2029-03-08`, `2029-06-07`, `2029-09-13`.

### 3.2 Muestras prohibidas

| Muestra | Fechas | Por qué está prohibida |
|---|---|---|
| W1–W6 | 2025-01-10 → 2026-06-30 | Usada para descubrir y elegir el filtro; es in-sample. |
| Holdout H1 | 2026-07-01 → 2026-10-30 | Sellado por el protocolo v1.2; no se abre para este filtro. |
| 2024 externo | 2024-01-02 → 2024-12-30 | Reservado por `H-CONT-SELECTIVA-2024`; no es independiente. |
| Pilot de 10 sesiones | 2025-01-16 → 2025-01-30 | Solapa W1–W6; no es independiente. |
| Burn-in | 2026-11-23 → 2026-11-30 | Solo plomería; excluido del análisis. |

No se leen, descargan, ejecutan ni infieren datos de estas ventanas para tomar decisiones sobre este filtro. El holdout sigue sellado.

### 3.3 Frecuencia esperada y mínimos

Con las tasas in-sample de P2:

- P2: **46 operaciones / 362 sesiones = 12,7%** → ~94 operaciones baseline en 742 sesiones.
- P2 + filtro: **17 / 362 = 4,7%** → ~35 aceptadas; ~59 rechazadas.

| ID | Mínimo | Si no se cumple |
|---|---|---:|
| S1 | ≥720 de 742 sesiones; ningún mes <80%; ningún hueco >5 sesiones | `inconcluso` |
| S2 | ≥60 operaciones baseline | `inconcluso` |
| S3 | ≥24 aceptadas y ≥30 rechazadas | `inconcluso` |
| S4 | ≥5/6 bloques con baseline ≥6 y aceptadas ≥2 | `inconcluso` |
| S5 | ≥5 cortos aceptados | `inconcluso_short` |

Si no se cumplen S1–S4, el resultado es **INCONCLUSO**, no aprobado. No se baja el mínimo, no se agregan bloques, no se extiende la ventana y no se sustituye la muestra.

> **Riesgo explícito:** el filtro in-sample dejó **0 operaciones en 2026**. Si ese régimen continúa, F1 puede tener cero aceptadas y S4 puede quedar inconcluso. Los 36 meses cubren 2027–2029, pero no garantizan que el filtro opere en todos los regímenes. No se añade un filtro de calendario ni se cambia el umbral para “arreglarlo”.

### 3.4 Fuente y captura

- **Proveedor:** Databento `GLBX.MDP3`, esquema `ohlcv-1m`, simbología `raw_symbol` para MNQ, NQ y ES.
- **Contratos:** 39 en total, 13 por raíz: `Z26, H27, M27, U27, Z27, H28, M28, U28, Z28, H29, M29, U29, Z29`.
- **Rolls:** 12 por raíz (36 en total); el saliente sigue activo en la sesión de roll y el entrante empieza la siguiente; la sesión de roll se excluye.
- **Series:** `raw`, 1 minuto, `America/New_York`, RTH 09:00–15:59 (o cierre anticipado oficial 12:59/13:14).
- **Captura:** una sesión por archivo, después del cierre (16:05 ET o más tarde), con manifiesto `captured_at_et`, fuente, `sha256`, filas, símbolos, contratos, expiries y resultado de validación. Append-only; no se edita después del sellado.
- **Sin relleno:** no se interpolan precios, no se derivan símbolos, no se usan barras sintéticas y no se descargan sesiones pasadas para “completar”. Una sesión perdida se registra y cuenta para S1.
- **Integridad:** 3 símbolos alineados, 420 velas por sesión (240/255 en cierre anticipado), ORB 09:00–10:00 completo, cero huecos injustificados, contratos y rolls correctos, `series_mode=raw`, `exclude_roll_sessions=true`.

---

## 4. Métricas y puertas

Todas las puertas se evalúan **una sola vez**, al final, con la muestra sellada. Ninguna se relaja después de ver resultados.

### 4.1 Integridad (I)

| ID | Condición | Si falla |
|---|---|---|
| I1 | Hash del protocolo y del lock coinciden; procedencia del código y perfil P2 verificadas | abortar |
| I2 | Todas las sesiones dentro de 2026-12-01 → 2029-11-30; cero sesiones de W1–W6, holdout, 2024 o burn-in | abortar |
| I3 | Dataset válido: 39 contratos, 36 rolls, 12 sesiones de roll excluidas, 3 símbolos alineados, ORB completo, cero huecos injustificados | abortar |
| I4 | Captura prospective: manifiesto por sesión, `captured_at_et` del mismo día, sin backfill, sin datos sintéticos, SHA-256 por archivo | abortar |
| I5 | Simetría de brazos: mismo dataset, mismos timestamps, misma configuración salvo `risk.min_stop_or_ratio` | abortar |
| I6 | Ratio válido en el 100% de las operaciones baseline: `stop_ticks>0`, `orb_width_ticks>0`, finito; `A ∪ Rj = B`, `A ∩ Rj = ∅` | abortar |
| I7 | Sin lookahead: el ratio usa ORB y stop conocidos en la señal; ninguna barra posterior al `entry_ts` interviene | abortar |
| I8 | Determinismo: replay del 10% de las sesiones dos veces produce los mismos `signal_id`, ratios y operaciones | abortar |
| I9 | One-shot: el archivo de análisis final no existe antes de ejecutar; una sola análisis de eficacia | abortar |

### 4.2 Muestra (S)

Las puertas S1–S5 de la sección 3.3.

### 4.3 Eficacia (E)

| ID | Condición | Si falla |
|---|---|---|
| E1 | `Δ_sel >= +0,25 R` | `fail` |
| E2 | IC95% inferior del bootstrap por sesión > 0 | `inconcluso` si incluye 0; `fail` si el IC95% superior <0 |
| E3 | `media(R aceptadas) >= +0,20 R` | `fail` |

### 4.4 Cartera y robustez (P)

| ID | Condición | Si falla |
|---|---|---|
| P1 | `suma(R rechazadas) <= 0` | `fail` |
| P2 | `profit_factor_R aceptadas >= 1,25` | `fail` |
| P3 | `DD_R aceptadas <= min(8 R, DD_R baseline)` y `DD_USD tratamiento <= min(2.000, DD_USD baseline)` | `fail` |
| P4 | `suma(R rechazadas) <= 0` en ≥5/6 bloques | `fail` |
| P5 | `drop_best_3_total_R > 0`, `drop_best_month_total_R > 0` y `top_trade_share_gross_R <= 50%` | `fail` |
| P6 | Cost stress: `media(R aceptadas) > 0` y `PF_R aceptadas >= 1,10` | `fail` |
| P7 | Aceptadas en ≥12 de 36 meses y `max_consecutive_zero_months <= 4` | `fail` |
| P8 | Si hay ≥5 cortos aceptados: media R de cortos ≥0 y R total de cortos ≥0 | `fail`; si <5, `inconcluso_short` |
| P9 | Brazo real: `total_R tratamiento >= total_R baseline` y `DD_USD tratamiento <= DD_USD baseline` | `fail` |

### 4.5 Regla de decisión

| Estado | Condición |
|---|---|
| **PASS** | Todas las puertas I, S, E y P pasan. |
| **FAIL** | I y S pasan, y alguna puerta E o P falla con evidencia clara en contra. |
| **INCONCLUSO** | I o S fallan; o E2 incluye 0 sin evidencia clara en contra y el resto no falla; o hay <5 cortos aceptados (`inconcluso_short`). |

- `PASS` **no autoriza LIVE**. Solo indica que el filtro superó este diseño y puede pasar a un protocolo nuevo de preparación operativa.
- `FAIL` e `INCONCLUSO` no se rescatan cambiando bloques, semilla, ventana, umbral, costes o subgrupos. Exigirían una hipótesis nueva y una muestra nueva.
- No hay análisis intermedio de eficacia. La captura diaria solo produce conteos de integridad (sesiones, filas, huecos, contratos), no P&L ni decisiones.

### 4.6 Bootstrap

- Unidad: sesión.
- Remuestras: 10.000.
- Semilla: `20261123`.
- IC: percentil 95%.
- Contraste: unilateral, `H0: Δ <= 0`.
- Mínimo de réplicas válidas: 9.500.
- Se reporta también el bootstrap por operación como diagnóstico, pero **E2 usa el bootstrap por sesión**.

No se usa placebo de timing: el filtro no elige el momento; elimina operaciones después de que la señal existe. El contraste es aceptadas vs rechazadas sobre el mismo conjunto de señales baseline.

---

## 5. Ejecución, congelación y one-shot

### 5.1 Prerrequisitos (fase 0, no es validación)

El lock nace con `execution_gate.can_execute=false`. Antes de capturar hay que resolver, como mínimo:

1. **Captura prospective:** un job que descargue una sesión después del cierre, la valide, la selle y la agregue al CSV forward. El `CSVFeed` actual reproduce un CSV estático; no basta por sí solo.
2. **Universo contractual:** `server/market/databento_fetch.py` fija `QUARTERS` y `EXPECTED_CODES` en H25–Z26 (24 contratos). El forward P2 necesita el universo `Z26–Z29`: 39 contratos y 36 rolls. No basta con añadir `H27–Z29` a la lista global, porque `EXPECTED_CODES` pasaría a exigir 60; hay que parametrizar el universo contractual (o crear un `FORWARD_QUARTERS`) sin tocar la lógica de la estrategia.
3. **Credencial:** `DATABENTO_API_KEY` configurada fuera del repositorio. Sin clave no hay captura y no se ejecuta nada.
4. **Preflight y análisis:** un verificador que compruebe hashes, ventana permitida, solapamientos prohibidos, sello del holdout, ausencia del directorio de salida y una única ejecución; y un runner que solo acepte el lock y el CSV forward sellado.
5. **Tests de plomería:** captura, append, sellado, rechazo de fechas prohibidas y reproducibilidad con fixtures sintéticos. No se usan W1–W6 ni el holdout para probar la plomería.

Mientras estos prerrequisitos no estén completos y verificados, **no se captura ni se ejecuta** la validación.

### 5.2 Secuencia de congelación

1. Este documento se hashea y su SHA-256 se registra en `docs/p2_filtro_stop_or_forward.lock.json`.
2. El lock fija la configuración, la muestra, las puertas, la semilla y el carácter one-shot.
3. Antes de la primera captura se crea un **lock de ejecución** que verifica la procedencia del código final. Cualquier cambio de código que afecte estrategia, filtro, salidas, riesgo o ejecución invalida el diseño.
4. Se ejecuta el burn-in `2026-11-23 → 2026-11-30` para probar captura y sellado. Sus datos no entran en el análisis.
5. La captura válida empieza el `2026-12-01`. No se desplaza la ventana.
6. Al cerrar `2029-11-30`, se ejecuta una sola vez el replay del análisis sobre el CSV forward sellado.
7. Se escriben `analysis.json`, `ANALISIS.md` y los hashes de salida. No se vuelve a ejecutar.

### 5.3 Reglas de una sola ejecución

- El archivo `reports/backtest/p2_filtro_stop_or_forward/analysis.json` debe **no existir** antes del análisis final. Si existe, el runner aborta.
- Se permite **una** análisis de eficacia. Si falla por un defecto técnico antes de producir métricas, se puede repetir una vez con el mismo lock y el mismo dataset, documentando el fallo. Si ya se produjeron métricas, no se repite: se reporta el resultado tal cual.
- Cualquier cambio sustantivo después de empezar la captura —umbral, ventana, gates, configuración, código de estrategia— invalida el estudio. No se “arregla” el resultado con una segunda muestra.

### 5.4 Auditoría

Se conserva, por sesión y por ejecución:

- archivo crudo capturado y su SHA-256;
- manifiesto de captura (`captured_at_et`, fuente, filas, símbolos, contratos, expiries, validación);
- configuración efectiva de ambos brazos y diff exacto;
- hashes de código, del protocolo, del lock y del perfil P2;
- salida del preflight;
- JSON/MD del análisis y hash de salida;
- registro de incidencias, sesiones perdidas y correcciones.

---

## 6. Motivación in-sample (no es validación)

Estos números se obtuvieron en W1–W6 con el mismo dataset de desarrollo. Sirven para justificar la hipótesis, **no** para aprobarla.

| Brazo | Ops | Neto | PF | DD | DD % | R medio |
|---|---:|---:|---:|---:|---:|---:|
| P2 sin filtro | 46 | +2.471,78 | 1,39 | 2.304,46 | 7,84 | 0,25 |
| P2 + filtro 0,25 | 17 | +4.202,20 | 4,25 | 946,38 | 3,36 | 1,11 |

Por ventanas, el filtro no mejora todo:

- W1: **+1.622,84** vs P2 +2.245,50 (empeora; rechaza las tres mayores ganadoras de W1).
- W2: **+554,80** vs P2 +642,76 (empeora).
- W3: **+63,96** vs P2 −460,32 (mejora).
- W4: **+1.960,60** vs P2 +1.960,60 (igual).
- W5/W6: **0 operaciones** vs P2 −1.497,14/−419,62 (evita las pérdidas, no las gana).

La mejora agregada del filtro viene sobre todo de **no operar en 2026**, no de seleccionar mejores entradas en todos los regímenes. Por eso el forward debe exigir consistencia por bloques y participación, no solo un agregado favorable. El filtro es in-sample, tiene 17 operaciones y no cumple G4 (≥80). No se promueve.

---

## 7. Qué no autoriza este documento

- No autoriza LIVE ni cambia `live_enabled`.
- No autoriza paper en tiempo real; el diseño es captura prospective + replay ciego.
- No modifica `data/config.json`, `profiles/backtest_real/config.json`, la DB, `docs/protocolo_backtest.lock.json` ni el holdout.
- No reabre W1–W6, 2024 ni el holdout.
- No sustituye el lock existente `docs/filtro_stop_or_forward.lock.json` (que prueba el filtro sobre la configuración original). Esta es una hipótesis nueva sobre P2; si ambos estudios coexisten, son brazos separados y no se mezclan resultados.
- No autoriza una búsqueda de umbrales, una rejilla de ratios ni una selección de subgrupos.
- No autoriza promoción a live si el resultado es PASS; solo abre un protocolo nuevo de preparación operativa.

---

## 8. Estado actual

- Perfil P2 creado en `profiles/p2_freq/config.json`.
- Backtest W1–W6 de P2 confirmado en `reports/backtest/p2_w1_w6_confirm.json`: **46 ops, +2.471,78, PF 1,39, DD 2.304,46 (7,84%)**.
- Filtro 0,25 in-sample: **17 ops, +4.202,20, PF 4,25, DD 946,38 (3,36%)**, cero en 2026.
- No existe captura forward, no hay `DATABENTO_API_KEY`, no se ha creado el directorio de salida y el holdout sigue sellado.
- `execution_gate.can_execute = false`.

---

## 9. Artefactos

- `docs/P2_FILTRO_STOP_OR_FORWARD.md` — este plan.
- `docs/p2_filtro_stop_or_forward.lock.json` — lock de pre-registro con hashes, muestra, puertas y estado `can_execute=false`.
- `profiles/p2_freq/config.json` — perfil P2 congelado para el control.
- `reports/backtest/p2_w1_w6_confirm.json` — confirmación W1–W6.
- `reports/backtest/p2_filtro_stop_or_forward/` — directorio futuro para captura, manifiestos y análisis; **no creado**.
- `reports/backtest/p2_filtro_stop_or_forward/analysis.json` — salida única futura; no existe.
- `reports/backtest/p2_filtro_stop_or_forward/ANALISIS.md` — informe futuro; no existe.

**Estado:** pre-registrado, no ejecutado. No se ha capturado ni analizado ninguna barra forward. No se ha tocado el holdout.
