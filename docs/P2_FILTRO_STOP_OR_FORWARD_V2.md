# Pre-registro forward v2 — filtro stop/ORB 0,25 sobre P2

**Versión:** 2.0

**Fecha:** 2026-11-24

**Estado:** pre-registrado y **no ejecutado**. No se ha capturado ni leído ninguna barra forward, no se ha ejecutado ningún backtest nuevo y el holdout `2026-07-01 → 2026-10-30` sigue sellado.

**Hipótesis:** `H-P2-FILTER-STOP-OR-025`.

**Revisión de diseño:** 2.0; misma hipótesis, mismo umbral y misma muestra que la v1.1, con criterios de parada explícitos.

**Lock:** [`p2_filtro_stop_or_forward_v2.lock.json`](p2_filtro_stop_or_forward_v2.lock.json).

**Perfil base:** [`profiles/p2_freq/config.json`](../profiles/p2_freq/config.json).

**Ventana:** `2026-12-01 → 2029-11-30`, 742 sesiones evaluadas.

> **Origen de la propuesta.** La prioridad 2 de `reports/backtest/MANUAL_8765_LIVE_ASSESSMENT.md` es “validar el filtro `min_stop_or_ratio=0,25` sin tocar el umbral”. En `reports/backtest/DECISION_CONFIG_MANUAL_8765_VS_ORIGINAL.md` la misma idea aparece como propuesta #6; la #2 de ese informe es el reprecio de costes y **no** se convierte aquí. Este documento adapta la prioridad 2 al perfil P2, que es el candidato pre-registrado de 10 contratos.
>
> **No reabre producción.** El filtro sigue **descartado/INCONCLUSO** para promoción y el 8765 sigue sin aplicarlo. Pre-registrar un estudio no cambia la decisión de producción, no activa el filtro y no autoriza LIVE.
>
> **Relación con la v1.1.** `docs/P2_FILTRO_STOP_OR_FORWARD.md` y `docs/p2_filtro_stop_or_forward.lock.json` quedan intactos como artefactos históricos. Esta v2 los sustituye **solo para una eventual ejecución**, porque añade paradas explícitas y congela el modelo de costes; no crea una confirmación independiente. Solo una de las dos versiones puede ejecutarse sobre esta ventana.

---

## 1. Pregunta, hipótesis y endpoints

### 1.1 Pregunta

En una muestra forward independiente, ¿el filtro fijo `stop_ticks / orb_width_ticks >= 0,25` aplicado sobre P2 mejora la esperanza en R y el resultado de cartera frente a P2 sin filtro, sin reducir la actividad a un nivel inutilizable y sin depender de un régimen concreto?

### 1.2 Hipótesis

**H1:** en forward, el cohorte aceptado por el filtro tiene una esperanza en R mayor que el cohorte rechazado; el R total del tratamiento no empeora el de P2; y el tratamiento supera las puertas de muestra, concentración, costes y drawdown.

**H0:** `Δ_sel <= 0`; o el cohorte rechazado tiene R total positivo; o el tratamiento no supera las puertas de muestra, concentración, costes o drawdown; o el IC95 % no permite distinguir la mejora de cero con el resto de gates en verde.

### 1.3 Endpoint primario

Sea `B` el conjunto de operaciones del brazo control P2 en la muestra forward. Para cada operación `i ∈ B`:

```text
ratio_i = stop_ticks_i / orb_width_ticks_i
A  = { i ∈ B : ratio_i >= 0,25 }   (aceptadas)
Rj = { i ∈ B : ratio_i < 0,25 }    (rechazadas)

Δ_sel = media(R_i para i ∈ A) − media(R_i para i ∈ Rj)
```

- Unidad de observación: operación.
- Unidad de remuestreo: sesión.
- `R_i` es el múltiplo de riesgo neto de comisiones y slippage, calculado por el motor; no se recalcula a mano.
- El umbral **0,25 está fijado**. No se prueban 0,20, 0,30 ni ninguna otra rejilla.
- El brazo de tratamiento real (`min_stop_or_ratio=0,25`) se ejecuta sobre el mismo dataset para medir la interacción con el límite de pérdida diaria, el cooldown y el dimensionamiento.

### 1.4 Endpoint de cartera

```text
Δ_total_R = suma(R_i para i ∈ A) − suma(R_i para i ∈ B)
          = −suma(R_i para i ∈ Rj)
```

Exigir que el filtro no empeore el R total equivale a exigir que **el cohorte rechazado tenga R total ≤ 0**. El neto en USD, el PF, el drawdown y el RDD se reportan como puertas de cartera, no como sustitutos del endpoint primario.

### 1.5 Costes

La medición principal usa el coste base del perfil P2: comisión `0,62/lado`, slippage `1 tick`, `max_slippage_ticks=4`, fill `next_open`, sin parciales. P6 exige un **reprecio exacto** de los mismos fills con comisión `1,24/lado` y slippage `2 ticks`; la estimación uniforme de `−100,80` no es P6 y no se usa. Si P6 no se puede ejecutar, el estudio no se inicia.

---

## 2. Brazos y configuración congelada

| Elemento | Control C | Tratamiento T |
|---|---|---|
| ID | `C` | `T` |
| Perfil | `profiles/p2_freq/config.json` | `profiles/p2_freq/config.json` |
| `risk.min_stop_or_ratio` | 0,00 | **0,25** |
| `risk.max_sl_ticks` | 200 | 200 |
| `risk.max_contracts` | 10 | 10 |
| `strategy.setup_validity_minutes` | 210 | 210 |
| `strategy.retest_tolerance_ticks` | 24 | 24 |
| `risk.risk_per_trade_pct` | 1,0 | 1,0 |
| `risk.max_trades_per_day` | 3 | 3 |
| `risk.max_concurrent_positions` | 1 | 1 |
| `strategy.tp_rr` | 3,0 | 3,0 |
| Gestión | ninguna | ninguna |
| `feed.series_mode` forward | `raw` | `raw` |
| `feed.exclude_roll_sessions` | `true` | `true` |
| `live.live_enabled` | `false` | `false` |

**Único cambio permitido:** `risk.min_stop_or_ratio: 0,00 → 0,25`. Todo lo demás se hereda del perfil P2 y debe coincidir exactamente. No se crea un perfil nuevo ni se modifica `profiles/p2_freq/config.json`; el tratamiento es un override de ejecución.

### 2.1 Feed común

El feed forward sustituye solo el feed de backtest y es idéntico en ambos brazos:

```text
feed.provider=csv
feed.csv_path=reports/backtest/p2_filtro_stop_or_forward_v2/bars_forward.csv
feed.series_mode=raw
feed.exclude_roll_sessions=true
feed.loop_sessions=false
feed.replay_speed=1.0
```

El CSV no existe todavía y **no se crea en este acto**. Cualquier cambio de código que afecte estrategia, filtro, salidas, riesgo o ejecución invalida este diseño y exige un lock nuevo.

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

- La ventana se fija antes de capturar. **No se desplaza** si la captura empieza tarde: si no se puede empezar el 2026-12-01, se necesita un lock nuevo con otra ventana y otra muestra.
- **Burn-in:** `2026-11-23 → 2026-11-30`, excluido del análisis. Solo sirve para probar captura, validación y sellado; no se usa para elegir nada.
- Rolls previstos: `2026-12-10`, `2027-03-11`, `2027-06-09`, `2027-09-09`, `2027-12-09`, `2028-03-09`, `2028-06-08`, `2028-09-07`, `2028-12-07`, `2029-03-08`, `2029-06-07`, `2029-09-13`.

### 3.2 Muestras prohibidas

| Muestra | Fechas | Por qué está prohibida |
|---|---|---|
| W1–W6 | 2025-01-10 → 2026-06-30 | Usada para descubrir y elegir el filtro; es in-sample. |
| Holdout H1 | 2026-07-01 → 2026-10-30 | Sellado por el protocolo v1.2; no se abre para este filtro. |
| 2024 externo | 2024-01-02 → 2024-12-30 | Reservado por `H-CONT-SELECTIVA-2024`; no es independiente. |
| Pilot de 10 sesiones | 2025-01-16 → 2025-01-30 | Solapa W1–W6; no es independiente. |
| Burn-in | 2026-11-23 → 2026-11-30 | Solo plomería; excluido del análisis. |
| Muestra compartida | la que use otro lock | Dos hipótesis sobre la misma muestra no son confirmaciones independientes. |

No se leen, descargan, ejecutan ni infieren datos de estas ventanas para tomar decisiones sobre este filtro. El holdout sigue sellado.

### 3.3 Frecuencia esperada y mínimos

Con las tasas in-sample de P2:

- P2: **46 operaciones / 362 sesiones = 12,7 %** → ~94 operaciones baseline en 742 sesiones.
- P2 + filtro: **17 / 362 = 4,7 %** → ~35 aceptadas; ~59 rechazadas.

| ID | Mínimo | Si no se cumple |
|---|---|---:|
| S1 | ≥720 de 742 sesiones; ningún mes <80 %; ningún hueco >5 sesiones | `INCONCLUSO` |
| S2 | ≥60 operaciones baseline | `INCONCLUSO` |
| S3 | ≥24 aceptadas y ≥30 rechazadas | `INCONCLUSO` |
| S4 | ≥5/6 bloques con baseline ≥6 y aceptadas ≥2 | `INCONCLUSO` |
| S5 | ≥5 cortos aceptados | `INCONCLUSO_SHORT` |

Si no se cumplen S1–S4, el resultado es **INCONCLUSO**, no aprobado. No se baja el mínimo, no se agregan bloques, no se extiende la ventana y no se sustituye la muestra.

> **Riesgo explícito:** el filtro in-sample dejó **0 operaciones en 2026**. Si ese régimen continúa, F1 puede tener cero aceptadas y S4 puede quedar inconcluso. Los 36 meses cubren 2027–2029, pero no garantizan que el filtro opere en todos los regímenes. No se añade un filtro de calendario ni se cambia el umbral para “arreglarlo”.

---

## 4. Gates

Todas las puertas se evalúan **una sola vez**, al final, con la muestra sellada. Ninguna se relaja después de ver resultados. No hay análisis intermedio de eficacia.

### 4.1 Integridad (I)

| ID | Condición | Si falla |
|---|---|---|
| I1 | Hash del protocolo, lock, perfil P2 y procedencia del código verificados | abortar |
| I2 | Todas las sesiones dentro de 2026-12-01 → 2029-11-30; cero W1–W6, H1, 2024 o burn-in | abortar |
| I3 | Dataset válido: 39 contratos, 36 rolls, 12 sesiones de roll excluidas, 3 símbolos alineados, ORB completo, cero huecos injustificados | abortar |
| I4 | Captura prospective: manifiesto por sesión, `captured_at_et` del mismo día, sin backfill, sin datos sintéticos, SHA-256 por archivo | abortar |
| I5 | Simetría de brazos: mismo dataset, timestamps y configuración salvo `risk.min_stop_or_ratio` | abortar |
| I6 | Ratio válido en el 100 % de las operaciones baseline: `stop_ticks>0`, `orb_width_ticks>0`, finito; `A ∪ Rj = B`, `A ∩ Rj = ∅` | abortar |
| I7 | Sin lookahead: el ratio usa ORB y stop conocidos en la señal; ninguna barra posterior al `entry_ts` interviene | abortar |
| I8 | Determinismo: replay del 10 % de las sesiones dos veces produce los mismos `signal_id`, ratios y operaciones | abortar |
| I9 | One-shot: `analysis.json` no existe antes; una sola análisis de eficacia | abortar |
| I10 | `holdout_bars_read=false` y cero sesiones H1; cualquier lectura del holdout invalida el estudio | abortar |

### 4.2 Muestra (S)

Las puertas S1–S5 de §3.3.

### 4.3 Eficacia (E)

| ID | Condición | Si falla |
|---|---|---|
| E1 | `Δ_sel >= +0,25 R` | `FAIL` |
| E2 | IC95 % inferior del bootstrap por sesión > 0 | `INCONCLUSO` si incluye 0; `FAIL` si el IC95 % superior <0 |
| E3 | `media(R aceptadas) >= +0,20 R` | `FAIL` |

### 4.4 Cartera y robustez (P/R)

| ID | Condición | Si falla |
|---|---|---|
| P1 | `suma(R rechazadas) <= 0` | `FAIL` |
| P2 | `profit_factor_R aceptadas >= 1,25` | `FAIL` |
| P3 | `DD_R aceptadas <= min(8 R, DD_R baseline)` y `DD_USD tratamiento <= min(2.000, DD_USD baseline)` | `FAIL` |
| P4 | `suma(R rechazadas) <= 0` en ≥5/6 bloques | `FAIL` |
| P5 | `drop_best_3_total_R > 0`, `drop_best_month_total_R > 0` y `top_trade_share_gross_R <= 50 %` | `FAIL` |
| P6 | Coste estresado exacto: `media(R aceptadas) > 0` y `PF_R aceptadas >= 1,10`, con comisión `1,24/lado` y slippage `2 ticks` | `FAIL` |
| P7 | Aceptadas en ≥12 de 36 meses y `max_consecutive_zero_months <= 4` | `FAIL` |
| P8 | Si hay ≥5 cortos aceptados: media R de cortos ≥0 y R total de cortos ≥0 | `FAIL`; si <5, `INCONCLUSO_SHORT` |
| P9 | Brazo real: `total_R tratamiento >= total_R baseline` y `DD_USD tratamiento <= DD_USD baseline` | `FAIL` |
| R1 | Top-2 bloques ≤80 % del neto del tratamiento | `FAIL` |
| R2 | `PF_R` del bloque ≥0,70 en ≥5/6 bloques con ≥3 aceptadas | `FAIL` |

### 4.5 Regla de decisión

| Estado | Condición |
|---|---|
| **PASS** | Todas las puertas I, S, E, P y R pasan. |
| **FAIL** | I y S pasan, y alguna puerta E, P o R falla con evidencia clara en contra. |
| **INCONCLUSO** | I o S fallan; o E2 incluye 0 sin evidencia clara en contra y el resto no falla; o hay <5 cortos aceptados (`INCONCLUSO_SHORT`). |

- `PASS` **no autoriza LIVE**. Solo indica que el filtro superó este diseño y puede pasar a un protocolo nuevo de preparación operativa.
- `FAIL` e `INCONCLUSO` no se rescatan cambiando bloques, semilla, ventana, umbral, costes o subgrupos. Exigirían una hipótesis nueva y una muestra nueva.
- No se promociona “el que menos pierde”: si el tratamiento no supera las puertas de rentabilidad y riesgo, no pasa.

### 4.6 Bootstrap

- Unidad: sesión.
- Remuestras: 10.000.
- Semilla: `20261124`.
- IC: percentil 95 %.
- Contraste: unilateral, `H0: Δ <= 0`.
- Mínimo de réplicas válidas: 9.500.
- Se reporta también el bootstrap por operación como diagnóstico, pero **E2 usa el bootstrap por sesión**.
- No se usa placebo de timing: el filtro no elige el momento; elimina operaciones después de que la señal existe.

---

## 5. Criterios de parada

Los criterios se fijan antes de capturar. “Parar” significa detener el estudio o la captura, no detener ni reiniciar el 8765. No hay paradas por P&L intermedio.

| ID | Momento | Condición | Acción |
|---|---|---|---|
| STOP-0 | Antes de empezar | `execution_gate.can_execute=false`; falta captura prospective, universo Z26–Z29, credencial, preflight, runner o lock de ejecución | No iniciar; no se captura ni se analiza |
| STOP-1 | Preflight o durante la captura | Hash del protocolo, lock, perfil P2 o código no coincide; diff distinto de `min_stop_or_ratio`; cambia `data/config.json`, `profiles/live_8765` o el 8765 | Abortar; no reiniciar el 8765; no reutilizar la captura |
| STOP-2 | Preflight o cualquier lectura | Se lee una barra o sesión de W1–W6, H1, 2024 o burn-in; `holdout_bars_read=true` | Abortar y anular el estudio; no se sustituye la muestra |
| STOP-3 | Captura | Sesión duplicada, fuera de orden, backfill, barra sintética, manifiesto tardío, universo distinto de 39 contratos/36 rolls, o más de 5 sesiones consecutivas perdidas | Detener la captura y declarar `INCONCLUSO`; no se rellena ni se descargan sesiones pasadas |
| STOP-4 | Final, tras sellar | Falla S1, S2, S3 o S4 | `INCONCLUSO`; no se extiende la ventana ni se añaden bloques |
| STOP-5 | Final, tras sellar | I y S pasan y falla una puerta E, P o R con evidencia clara | `FAIL`; no se rescata cambiando umbral, semilla, costes o subgrupos |
| STOP-6 | Final, tras sellar | Todas las puertas I, S, E, P y R pasan | `PASS`; se detiene el estudio; no autoriza LIVE |
| STOP-7 | Después del análisis | Se produjo `analysis.json` con métricas | No se repite el análisis; una sola ejecución de eficacia |
| STOP-8 | Fallo técnico antes de métricas | El runner falla antes de producir métricas | Un solo reintento con el mismo lock, mismo dataset y causa documentada; después se para |
| STOP-9 | Calendario | Se alcanza `2029-11-30` | Cerrar y analizar una vez; no se prorroga la ventana |
| STOP-10 | Cualquier momento | Se pretende mirar P&L, PF, DD o `Δ_sel` antes del final para decidir continuación | No hacerlo; solo se permiten conteos de integridad y de sesiones |

### 5.1 Reglas de no rescate

- No se cambia el umbral 0,25, ni se prueba 0,20/0,30, ni se añade un filtro de calendario.
- No se cambia la ventana, la semilla, los bloques, el bootstrap ni la definición de R después de ver resultados.
- No se sustituye una sesión perdida, no se interpola, no se usan barras sintéticas y no se descargan sesiones pasadas.
- No se ejecuta este plan y la v1.1 a la vez; comparten hipótesis, ventana y muestra. La primera ejecución válida cancela la otra.
- No se usa el holdout para “completar” la muestra ni para decidir si el filtro sirve.

---

## 6. Ejecución, congelación y one-shot

### 6.1 Prerrequisitos (fase 0, no es validación)

El lock nace con `execution_gate.can_execute=false`. Antes de capturar hay que resolver, como mínimo:

1. **Captura prospective:** un job que descargue una sesión después del cierre, la valide, la selle y la agregue al CSV forward. El `CSVFeed` actual reproduce un CSV estático; no basta por sí solo.
2. **Universo contractual:** `server/market/databento_fetch.py` fija `QUARTERS` y `EXPECTED_CODES` en H25–Z26 (24 contratos). El forward P2 necesita el universo `Z26–Z29`: 39 contratos y 36 rolls. No basta con añadir `H27–Z29` a la lista global, porque `EXPECTED_CODES` pasaría a exigir 60; hay que parametrizar el universo contractual sin tocar la lógica de la estrategia.
3. **Credencial:** `DATABENTO_API_KEY` configurada fuera del repositorio. Sin clave no hay captura y no se ejecuta nada.
4. **Preflight y análisis:** un verificador que compruebe hashes, ventana permitida, solapamientos prohibidos, sello del holdout, ausencia del directorio de salida y una única ejecución; y un runner que solo acepte el lock y el CSV forward sellado.
5. **Coste estresado:** un runner que reprecie exactamente los mismos fills con comisión `1,24/lado` y slippage `2 ticks`; sin él, P6 no se evalúa y el estudio no arranca.
6. **Tests de plomería:** captura, append, sellado, rechazo de fechas prohibidas y reproducibilidad con fixtures sintéticos. No se usan W1–W6 ni el holdout para probar la plomería.

Mientras estos prerrequisitos no estén completos y verificados, **no se captura ni se ejecuta** la validación.

### 6.2 Secuencia de congelación

1. Este documento se hashea y su SHA-256 se registra en `docs/p2_filtro_stop_or_forward_v2.lock.json`.
2. El lock fija la configuración, la muestra, las puertas, las paradas, la semilla y el carácter one-shot.
3. Antes de la primera captura se crea un **lock de ejecución** que verifica la procedencia del código final. Cualquier cambio de código que afecte estrategia, filtro, salidas, riesgo o ejecución invalida el diseño.
4. Se ejecuta el burn-in `2026-11-23 → 2026-11-30` para probar captura y sellado. Sus datos no entran en el análisis.
5. La captura válida empieza el `2026-12-01`. No se desplaza la ventana.
6. Al cerrar `2029-11-30`, se ejecuta una sola vez el replay del análisis sobre el CSV forward sellado.
7. Se escriben `analysis.json`, `ANALISIS.md` y los hashes de salida. No se vuelve a ejecutar.

### 6.3 One-shot y auditoría

- El archivo `reports/backtest/p2_filtro_stop_or_forward_v2/analysis.json` debe **no existir** antes del análisis final. Si existe, el runner aborta.
- Se permite **una** análisis de eficacia. Si falla por un defecto técnico antes de producir métricas, se puede repetir una vez con el mismo lock y el mismo dataset, documentando el fallo. Si ya se produjeron métricas, no se repite: se reporta el resultado tal cual.
- Se conserva, por sesión y por ejecución: archivo crudo y SHA-256; manifiesto de captura; configuración efectiva de ambos brazos y diff exacto; hashes de código, protocolo, lock y perfil P2; salida del preflight; JSON/MD del análisis y hash de salida; registro de incidencias, sesiones perdidas y correcciones.

---

## 7. Qué no autoriza este documento

- No autoriza LIVE ni cambia `live_enabled`.
- No autoriza paper en tiempo real; el diseño es captura prospective + replay ciego.
- No modifica `data/config.json`, `profiles/live_8765/config.json`, `profiles/p2_freq/config.json`, la DB, `docs/protocolo_backtest.lock.json` ni el holdout.
- No reabre W1–W6, 2024 ni el holdout.
- No sustituye ni edita el plan y el lock v1.1; los conserva como históricos.
- No autoriza una búsqueda de umbrales, una rejilla de ratios ni una selección de subgrupos.
- No autoriza promoción a live si el resultado es PASS; solo abre un protocolo nuevo de preparación operativa.
- No convierte el resultado in-sample de 17 operaciones en una expectativa forward.

---

## 8. Motivación in-sample (no es validación)

Estos números se obtuvieron en W1–W6 con el mismo dataset de desarrollo. Sirven para justificar la hipótesis, **no** para aprobarla.

| Brazo | Ops | Neto | PF | DD | DD % | R medio |
|---|---:|---:|---:|---:|---:|---:|
| P2 sin filtro | 46 | +2.471,78 | 1,39 | 2.304,46 | 7,84 | 0,25 |
| P2 + filtro 0,25 | 17 | +4.202,20 | 4,25 | 946,38 | 3,36 | 1,11 |

Los gates históricos están **INCONCLUSO**, con 4 fallos y P6 **NO_EVALUABLE**. Los fallos son de cobertura y concentración: 4/6 bloques activos, top-2 = 85,28 % del neto, 10/18 meses activos y racha de 6 meses sin operar. La estimación uniforme de `−100,80` no es un reprecio exacto y no se usa como P6. El filtro no se promociona con estas cifras.

---

## 9. Estado actual y procedencia

- Perfil P2: `profiles/p2_freq/config.json`, SHA-256 `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb`.
- Plan v1.1: `docs/P2_FILTRO_STOP_OR_FORWARD.md`, SHA-256 `8061ddc92bf301494c88aa6b21c55dc4308807274fc5f223ad4ccff40f5a11ef`; no se modifica.
- Lock v1.1: `docs/p2_filtro_stop_or_forward.lock.json`, SHA-256 `d1a2c87b1a855d2040347dbc513711302fd3a4d667ffeb24ca4ae4861719fb01`; no se modifica.
- Artefactos in-sample: `p2_w1_w6_confirm.json` (`3b2d654a…`), `_manual_filter025_w1_w6.json` (`193a2bc1…`), `filter025_gates.json` (`66cf5ce0…`) y `filter025_gates.config.json` (`793911a4…`).
- No existe captura forward, no hay `DATABENTO_API_KEY`, no se ha creado el directorio de salida y el holdout sigue sellado.
- **No se ha ejecutado ningún backtest, no se ha modificado la configuración viva y no se ha escrito en la DB.**
