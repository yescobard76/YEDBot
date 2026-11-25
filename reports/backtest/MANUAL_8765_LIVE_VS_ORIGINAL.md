# Veredicto medido: config viva 8765 frente a la original

**Generado:** 2026-11-24T17:26:04.604870+00:00  
**Alcance:** W1–W6, 362 sesiones, 2025-01-10 → 2026-06-30.  
**Datos:** `data/bars.csv` (adjusted), el mismo CSV que usa el 8765; no se abrió 2024, no se abrió H1 y no se capturó nada nuevo.  
**Naturaleza:** backtest in-sample reproducible; no es forward.

## 1. Configuración viva comprobada

La configuración viva se leyó de `data/config.json`; su SHA-256 es `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f`. `profiles/live_8765/config.json` tiene el mismo SHA-256 (`9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f`). Ambos ficheros conservan su hash antes y después de la simulación; el runner no consulta ni reinicia el proceso 8765.

| Parámetro | Viva 8765 | Original |
|---|---:|---:|
| `risk.max_contracts` | 10 | 5 |
| `risk.max_sl_ticks` | 300 | 200 |
| `strategy.setup_validity_minutes` | 210 | 150 |
| `strategy.retest_tolerance_ticks` | 24 | 12 |
| `feed.replay_speed` | 8.0 | 4.5 |

## 2. Comparación cara a cara

### 2.1 Misma muestra y misma contabilidad (trades nativos de cada config)

| Perfil | Trades | Neto USD | Expectancy R | Expectancy USD | PF | Max DD USD | Max DD % | Peor racha | USD/sesión | Retorno/sesión |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Original 5/200/150/12 | 38 | 661.44 | 0.130 | 17.41 | 1.13 | 1,967.82 | 7.14% | 10 | 1.83 | 0.0073% |
| P1 5/200/210/24 | 46 | 1,992.26 | 0.250 | 43.31 | 1.37 | 1,947.82 | 6.75% | 10 | 5.50 | 0.0220% |
| P2 10/200/210/24 | 46 | 2,471.78 | 0.250 | 53.73 | 1.39 | 2,304.46 | 7.84% | 10 | 6.83 | 0.0273% |
| Viva 8765 10/300/210/24 | 72 | 2,022.94 | 0.180 | 28.10 | 1.22 | 2,891.66 | 9.79% | 13 | 5.59 | 0.0224% |
| 10/300/150/12 | 60 | -608.06 | 0.020 | -10.13 | 0.93 | 2,870.66 | 10.68% | 13 | -1.68 | -0.0067% |
| P2 + filtro 0,25 | 17 | 4,202.20 | 1.110 | 247.19 | 4.25 | 946.38 | 3.36% | 5 | 11.61 | 0.0464% |

`Expectancy R` es la media de `r_multiple`; `Retorno/sesión` es neto / capital inicial / sesiones, no compuesto. `DD` es la curva de trades concatenados con capital inicial 25,000, la misma convención que W1–W6.

### 2.2 Mismo conjunto de señales (intersección literal)

Las configuraciones con frecuencia distinta no generan exactamente las mismas señales. La comparación literal posible es la intersección por `signal_id`; la tabla siguiente no mezcla trades de una config con los de otra.

| Par | Señales comunes | Cobertura A | Cobertura B | Neto A | Neto B | Δ Neto | Δ Expectancy R |
|---|---:|---:|---:|---:|---:|---:|---:|
| Viva vs original | 37 | 51.4% | 97.4% | 752.02 | 910.14 | -158.12 | -0.060 |
| P2 vs P1 (sizing) | 46 | 100.0% | 100.0% | 2,471.78 | 1,992.26 | 479.52 | 0.000 |
| Viva vs P2 (stop) | 46 | 63.9% | 100.0% | 2,415.54 | 2,471.78 | -56.24 | 0.000 |
| P1 vs original (frecuencia) | 35 | 76.1% | 92.1% | 908.34 | 933.82 | -25.48 | -0.060 |
| Viva vs 10/300/150/12 (frecuencia) | 56 | 77.8% | 93.3% | -274.94 | -203.90 | -71.04 | -0.040 |
| Filtro 0,25 vs P2 (selección) | 17 | 100.0% | 37.0% | 4,202.20 | 4,202.20 | 0.00 | 0.000 |

#### 2.2.1 Métricas completas sobre las 37 señales comunes

| Perfil | Trades | Neto USD | Expectancy R | Expectancy USD | PF | Max DD USD | Max DD % | Peor racha | USD/sesión |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Viva, señales comunes | 37 | 752.02 | 0.100 | 20.32 | 1.14 | 2,026.58 | 7.40% | 9 | 2.08 | 0.0083% |
| Original, señales comunes | 37 | 910.14 | 0.160 | 24.60 | 1.19 | 1,719.12 | 6.24% | 9 | 2.51 | 0.0101% |

Mismos `signal_id` y misma contabilidad, pero la qty puede diferir por `max_contracts` y por la secuencia de equity. No son fills idénticos: son el mismo conjunto de señales, no el mismo tamaño de posición.

### 2.3 Puente de P&L: ¿de dónde sale la diferencia?

La comparación literal de señales comunes responde a la pregunta clave: la ventaja agregada no implica que la viva sea mejor en los trades que ambas toman. El puente siguiente separa el efecto común del efecto de tomar señales que la otra configuración no toma.

| Comparación | Δ Total | Δ en señales comunes | Solo A: neto (n) | Solo B: neto (n) |
|---|---:|---:|---:|---:|
| Viva vs original | +1,361.50 | -158.12 | +1,270.92 (35) | -248.70 (1) |
| P2 vs P1 (sizing) | +479.52 | +479.52 | +0.00 (0) | +0.00 (0) |
| Viva vs P2 (stop) | -448.84 | -56.24 | -392.60 (26) | +0.00 (0) |
| P1 vs original (frecuencia) | +1,330.82 | -25.48 | +1,083.92 (11) | -272.38 (3) |
| Viva vs 10/300/150/12 (frecuencia) | +2,631.00 | -71.04 | +2,297.88 (16) | -404.16 (4) |
| Filtro 0,25 vs P2 (selección) | +1,730.42 | +0.00 | +0.00 (0) | -1,730.42 (29) |

Ejemplo: en **Viva vs original**, la viva gana 1,361.50 USD en total, pero pierde 158.12 USD en las 37 señales comunes; la diferencia agregada se reparte entre 35 señales que solo toma la viva (+1,270.92 USD) y 1 que solo toma la original (-248.70 USD). Es una diferencia de **cobertura de señales**, no de mejor ejecución en los trades compartidos.

### 2.4 Neto por bloque

| Bloque | Original | P1 | P2 | Viva | Filtro P2 |
|---|---:|---:|---:|---:|---:|
| W1 | 364.82 | 1,700.06 | 2,245.50 | 2,735.34 | 1,622.84 |
| W2 | 268.40 | 445.44 | 642.76 | 418.30 | 554.80 |
| W3 | -110.46 | -238.40 | -460.32 | -1,088.22 | 63.96 |
| W4 | 2,034.12 | 1,960.60 | 1,960.60 | 2,461.48 | 1,960.60 |
| W5 | -1,036.52 | -1,240.22 | -1,497.14 | -1,497.14 | 0.00 |
| W6 | -858.92 | -635.22 | -419.62 | -1,006.82 | 0.00 |

### 2.5 Significación aproximada del delta de neto

Bootstrap por bloques W1–W6 (6 bloques, 10,000 remuestreos): Δ medio +1,390.94 USD, IC95% [-3,056.32, +6,965.66], p bilateral aproximado 0.6544. El intervalo incluye cero; con solo seis bloques es una prueba débil y no sustituye un forward.

## 3. Atribución por palanca

Descomposición secuencial exacta: original → P1 (frecuencia) → P2 (sizing) → viva (stop). El residuo debe ser cero; se comprueba en el script.

| Palanca | Desde → hasta | Δ Neto USD | Δ DD USD | Δ Peor racha | Δ PF | Veredicto |
|---|---|---:|---:|---:|---:|---|
| Frecuencia 210/24 | original → p1 | +1,330.82 | -20.00 | +0 | +0.24 | Aumenta oportunidades; el neto sube y el DD baja en esta base. |
| Max contratos 5 → 10 | p1 → p2 | +479.52 | +356.64 | +0 | +0.02 | Añade USD y DD; no añade edge por trade. |
| Stop 200 → 300 | p2 → live | -448.84 | +587.20 | +3 | -0.17 | Acepta stops profundos; en W1–W6 destruye neto y DD. |

**Total viva − original:** +1,361.50 USD, DD +923.84 USD, peor racha +3. Residuo de la descomposición: +0.00 USD.

### 3.1 Qué trades explican cada palanca

- **Stop 300 vs 200:** la viva tiene 26 trades con stop >200 ticks; suman -392.60 USD. P2 los rechaza. El delta de stop es -448.84 USD y DD +587.20 USD.
- **Sizing 10 vs 5:** P2 tiene 17 trades con qty >5; el cambio de sizing aporta +479.52 USD y DD +356.64 USD.
- **Frecuencia 210/24 vs 150/12:** con riesgo original aporta +1,330.82 USD; con riesgo viva aporta +2,631.00 USD. No es aditivo: la interacción frecuencia × riesgo es +1,300.18 USD.
- **Replay 8× vs 1×:** +0.00 USD y +0.00 USD de DD; la secuencia de trades es idéntica. El replay solo cambia el reloj de pared, no el edge.

## 4. Robustez in-sample del filtro 0,25

El filtro se prueba sobre **P2 (10/200/210/24)**, el candidato pre-registrado. El brazo real `p2_filter025` se simuló aparte; la sensibilidad de umbral y el placebo usan el ledger P2 de 46 trades.

- P2 baseline: **46 trades, 2,471.78 USD, PF 1.39, DD 2,304.46**.
- Filtro 0,25 real: **17 trades, 4,202.20 USD, PF 4.25, DD 946.38**.

### 4.1 Sensibilidad del umbral

| Umbral | Aceptadas | Rechazadas | Δ selección R | Neto seleccionado | PF | DD |
|---:|---:|---:|---:|---:|---:|---:|
| 0.15 | 26 | 20 | 0.368 | 2,453.84 | 1.81 | 1,221.00 |
| 0.20 | 23 | 23 | 0.691 | 3,166.22 | 2.36 | 1,221.00 |
| 0.25 | 17 | 29 | 1.360 | 4,202.20 | 4.25 | 946.38 |
| 0.30 | 15 | 31 | 1.246 | 3,701.40 | 4.08 | 946.38 |
| 0.35 | 14 | 32 | 1.005 | 2,960.36 | 3.47 | 1,200.60 |

### 4.2 Placebo de subconjuntos aleatorios

Se sortearon 10,000 subconjuntos de 17 trades de los 46 del baseline, con semilla 20251124. El Δ real es **1.3602 R**.

- Media placebo: 0.0020 R; p95: 0.9021 R; máximo: 2.0003 R.
- Percentil del resultado real: **99.36**; p-valor one-sided: **0.0065**.

### 4.3 Leave-one-block-out (W1–W6)

| Bloque excluido | Aceptadas restantes | Δ selección R | ¿Positivo? |
|---|---:|---:|---:|
| W1 | 13 | 1.3911 | sí |
| W2 | 15 | 1.3987 | sí |
| W3 | 9 | 2.2967 | sí |
| W4 | 14 | 0.9542 | sí |
| W5 | 17 | 1.1614 | sí |
| W6 | 17 | 1.3406 | sí |

**Conclusión de robustez:** El edge de selección sobrevive a las tres pruebas in-sample: placebo significativo, todos los LOBO positivos y umbrales 0,15–0,35 positivos. Eso descarta un artefacto trivial de esta muestra, pero **no es validación forward**: el filtro sigue necesitando la muestra prospectiva P1/P2.

## 5. Mejoras ordenadas por rentabilidad esperada

| # | Mejora | Δ Neto esperado | Δ Expectancy R | Δ DD | Δ Peor racha | Evidencia | ¿Cambia 8765? | ¿Adoptable ya? |
|---:|---|---:|---:|---:|---:|---|---|---|
| 1 | Filtro min_stop_or_ratio 0,25 sobre P2 | +1,730.42 | +0.860 | -1,358.08 | -5 | 17 trades; Δ selección 1.360R; placebo p=0.0065; LOBO positivo | Sí (filtro + SL200) | No: forward P1/P2 |
| 2 | Mantener frecuencia 210/24 | +1,330.82 | +0.120 | -20.00 | +0 | P1 vs original con 5/200; no es aditivo con el stop | No: ya está | Sí, ya vigente |
| 3 | max_contracts 5 → 10 | +479.52 | +0.000 | +356.64 | +0 | P2 vs P1; es apalancamiento, no edge | No: ya está | Solo asignación de riesgo |
| 4 | max_sl_ticks 300 → 200 | +448.84 | +0.070 | -587.20 | -3 | P2 vs viva; en W1–W6 el stop 300 destruye neto y DD | Sí | No: forward; la muestra viva es demasiado pequeña |
| 5 | Replay 8× → 1× | +0.00 | +0.000 | +0.00 | 0 | W1 con 8× y 1×: secuencia idéntica | No: operativo | Sí, sin efecto económico |

## 6. Veredicto

En la muestra idéntica W1–W6 (362 sesiones), la config viva hizo **2,022.94 USD** frente a **661.44 USD** de la original: **+1,361.50 USD** (+205.8%), con expectancy R **0.180 vs 0.130** y PF **1.22 vs 1.13**. Pero el DD empeora: **2,891.66 vs 1,967.82 USD** (+923.84). En la intersección literal de 37 señales comunes, el neto es 752.02 vs 910.14 USD: la viva **pierde 158.12 USD en los trades que ambas toman**. La diferencia agregada procede de 35 señales que solo toma la viva (+1,270.92 USD) y de 1 señal(es) que solo toma la original (-248.70 USD). Es cobertura de señales, no mejor ejecución. La config viva es **mejor en neto bruto, pero peor en riesgo y no estadísticamente distinguible** con 72/38 trades in-sample. No es una demostración forward.

## 7. Límites y garantías

- Es un backtest **in-sample** de W1–W6; no es forward y no autoriza a declarar que la config viva sea superior hacia adelante.
- Los trades nativos de cada config no son idénticos porque la frecuencia cambia las señales; por eso se reporta también la intersección literal.
- El filtro se evalúa sobre P2; no se extrapola a la config viva con SL 300 sin una corrida específica.
- No se modificó configuración, DB, holdout, 2024 ni artefactos de validación. Solo se escribieron este informe y su JSON.

### Reproducir

```bash
python reports/backtest/run_live_vs_original_mission.py
```
