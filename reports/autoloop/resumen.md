# Informe consolidado — config viva del 8765 vs original, y mejoras

**Generado:** 2026-11-25T01:41:54+00:00  
**Alcance:** W1, W2, W3, W4, W5, W6 · 362 sesiones · `2025-01-10 09:00` → `2026-06-30 15:59` · CSV `adjusted` · capital inicial 25.000 USD.  
**Naturaleza:** backtest in-sample reproducible. Holdout no leído. Ningún cambio aplicado al 8765.

## Resumen

- La viva gana **+1.361,50 USD** y +0,09 de PF frente a la original, pero con **+923,84 USD más de drawdown**; el IC95 % del bootstrap incluye cero (p=0,6544).
- Las **4** ventanas de exclusión de fase 3: **4** mejoran neto y DD; el efecto no depende del encuadre exacto.
- **Candidato a forward:** `excl_1130_1330` (36 ops, RDD 2,327).
- **Concentración:** el candidato debe 104,6 % del neto a 5 operaciones; sin ellas, -146,74. Confianza baja-media.
- **Nada aplicado al 8765**: mismo PID, mismos hashes, misma config.

## 1. Config viva vs original establecida

Mismas ventanas y misma contabilidad para las dos. La original es `5/200/150/12`; la viva es `10/300/210/24`.

| Métrica | Viva 8765 | Original | Δ (viva − original) |
|---|---:|---:|---:|
| Operaciones | 72 | 38 | +34 |
| Neto USD | 2.022,94 | 661,44 | **+1.361,50** |
| RDD (neto/DD) | 0,6996 | 0,3361 | +0,3634 |
| Drawdown USD | 2.891,66 | 1.967,82 | +923,84 |
| Drawdown % | 9,79 | 7,14 | +2,65 |
| Profit factor | 1,22 | 1,13 | +0,09 |
| Expectancy R | 0,180 | 0,130 | +0,050 |
| Acierto % | 36,11 | 31,58 | +4,53 |
| Expectancy USD/op | 28,10 | 17,41 | +10,69 |

**Lectura:** la viva gana +1.361,50 USD más en la muestra, pero con +923,84 USD más de drawdown; el RDD pasa de 0,3361 a 0,6996. La diferencia agregada es de escala: +34 operaciones y hasta 10 contratos, no una mejora de la expectancy por operación (0,180 vs 0,130 R). El bootstrap por 6 bloques da IC95 % [-3.056,32; +6.965,66] y p=0,6544: incluye cero.

**Trazabilidad de la comparación:** ambas patas son filas reales del JSONL. Viva: `reports/autoloop/resultados.jsonl#manual_base` (72 ops, 2.022,94 USD, RDD 0,6996, DD 2.891,66). Original: `reports/autoloop/resultados_original.jsonl#original_5_200_150_12` (38 ops, 661,44 USD, RDD 0,3361, DD 1.967,82). **Ventana común verificada:** W1, W2, W3, W4, W5, W6, 362 sesiones, `2025-01-10 09:00` → `2026-06-30 15:59`; mismas fechas, sesiones y dataset en las dos filas.

### Parámetros que difieren

| Parámetro | Original | Viva |
|---|---:|---:|
| `feed.replay_speed` (no afecta al backtest) | 4.5 | 8.0 |
| `risk.max_contracts` | 5 | 10 |
| `risk.max_sl_ticks` | 200 | 300 |
| `strategy.retest_tolerance_ticks` | 12 | 24 |
| `strategy.setup_validity_minutes` | 150 | 210 |

El resto de parámetros es idéntico: `risk_per_trade_pct=1.0`, `max_trades_per_day=3`, `max_concurrent_positions=1`, `tp_rr=3.0`, `min_stop_or_ratio=0.0`, rango mínimo 10 ticks, comisión 0.62/lado y slippage 1 tick/lado. La única diferencia no económica es `feed.replay_speed`.

**Config viva:** `data/config.json` y `profiles/live_8765/config.json` tienen SHA-256 idéntico: `9bf4f9c7…5e29479f` y `9bf4f9c7…5e29479f`. **Original:** `profiles/backtest_real/config.json` con el patch original de la misión (`5/200/150/12`). Todo en solo lectura; no se escribió en el 8765.

Fuente numérica: `reports/autoloop/resultados.jsonl#manual_base` para la viva y `reports/autoloop/resultados_original.jsonl#original_5_200_150_12` para la original; ambas patas se re-ejecutaron con el runner W1–W6 y el dataset `data/bars.csv`, y la fila original se agregó al JSONL en esta sesión.

## 1b. Atribución por palanca y hechos vs inferencias

Descomposición secuencial exacta (original → P1 frecuencia → P2 sizing → viva stop), con residuo 0,00. Fuente: `reports/backtest/live_vs_original_mission.json` (`attribution`, `paired`, `diagnostics`) y `MANUAL_8765_LIVE_VS_ORIGINAL.md`.

| Paso | Cambio | Δ neto | Δ expect. R | Δ DD | Δ PF | Δ peor racha |
|---|---|---:|---:|---:|---:|---:|
| Original → P1 | `Frecuencia 210/24` | +1.330,82 | +0,120 | -20,00 | +0,24 | +0 |
| P1 → P2 | `Max contratos 5 → 10` | +479,52 | 0,000 | +356,64 | +0,02 | +0 |
| P2 → viva | `Stop 200 → 300` | -448,84 | -0,070 | +587,20 | -0,17 | +3 |
| **Original → viva** | **total** | **+1.361,50** | **+0,050** | **+923,84** | **+0,09** | **+3** |

**Hechos medidos:**

- La frecuencia aporta +1.330,82 y -20,00 de DD con riesgo original; no es aditiva: en la variante que combina frecuencia con riesgo viva aporta +2.631,00 (interacción +1.300,18).
- El sizing aporta +479,52 y +356,64 de DD; no cambia la expectancy R por operación (0,250 en P1 y P2).
- El Stop 200 → 300 resta -448,84 y añade +587,20 de DD; los 26 trades con stop >200 suman -392,60 y explican casi todo el lastre.
- En las 37 señales comunes la manual hace 752,02 y la original 910,14: -158,12. La diferencia agregada son 35 señales solo-manual (+1.270,92) y 1 solo-original que la manual no toma y pierde -248,70 (evita esa pérdida).
- Bootstrap por 6 bloques: media +1.390,94; IC95 % [-3.056,32; +6.965,66]; p=0,6544; incluye cero.
- `feed.replay_speed` 4,5→8,0 no cambia la secuencia: en W1, 8× y 1× dan 19 ops, 2.735,34, PF 2,42, DD 901,04; Δ 0,00. Es operativo, no edge.

**Inferencias (plausibles, no demostradas):**

- La ventaja agregada es cobertura de señales y apalancamiento, no mejor ejecución en los trades compartidos. El pareo lo sostiene en la muestra; no prueba causalidad fuera de ella.
- El Stop 200 → 300 es un lastre en W1–W6; no implica que lo sea en forward. El cohorte de 26 trades es una comparación de carteras, no un experimento aleatorio.
- La frecuencia 210/24 captura señales extra de calidad media inferior: en las comunes la manual rinde menos; el agregado gana por las 35 extra.
- La diferencia entre la DB viva y el backtest no es atribuible a la config: son contabilidad, feed y ejecución distintos; no hay reconciliación trade a trade.

**Datos que faltan / no permiten concluir:**

- Que la manual sea superior en forward: no hay muestra prospectiva, el holdout está sellado y el IC95 % incluye cero.
- Que la original sea mejor: tampoco tiene forward; solo se midió en el mismo histórico.
- Que la mejor variante primaria funcione hacia adelante: sus cifras son in-sample; el candidato tiene 36 ops y top-5 104,6 %.
- Cuantificar el efecto de régimen o de un broker real: 6 bloques, 72/38 trades, un solo instrumento (MNQ) y ejecución paper.

## 2. Ranking autónomo por RDD (W1–W6, in-sample)

RDD = neto / drawdown máximo. Todas las filas usan la misma muestra; **es una selección in-sample y no autoriza adopción**.

| # | Variante | Ops | Neto USD | PF | DD USD | RDD | Δ neto vs base | Cambio |
|---:|---|---:|---:|---:|---:|---:|---:|---|
| 1 | excl_1130_1330 | 36 | 3.203,82 | 1,90 | 1.376,54 | 2,327 | +1.180,88 | `risk.entry_exclusion_start` → 11:30; `risk.entry_exclusion_end` → 13:30 |
| 2 | sl_200 | 46 | 2.471,78 | 1,39 | 2.304,46 | 1,073 | +448,84 | `risk.max_sl_ticks` → 200 |
| 3 | manual_base | 72 | 2.022,94 | 1,22 | 2.891,66 | 0,700 | 0,00 | sin cambios (control) |
| 4 | daily_loss_2 | 72 | 2.022,94 | 1,22 | 2.891,66 | 0,700 | 0,00 | `risk.max_daily_loss_pct` → 2.0 |
| 5 | range_min_15 | 72 | 2.022,94 | 1,22 | 2.891,66 | 0,700 | 0,00 | `strategy.min_range_ticks` → 15 |
| 6 | tol_18 | 70 | 1.960,38 | 1,22 | 2.887,88 | 0,679 | -62,56 | `strategy.retest_tolerance_ticks` → 18 |
| 7 | sl_buffer_8 | 71 | 1.822,38 | 1,20 | 2.847,92 | 0,640 | -200,56 | `strategy.sl_buffer_ticks` → 8 |
| 8 | contracts_7 | 72 | 1.669,48 | 1,19 | 2.781,20 | 0,600 | -353,46 | `risk.max_contracts` → 7 |
| 9 | rr_2_5 | 72 | 1.462,18 | 1,16 | 2.891,66 | 0,506 | -560,76 | `strategy.tp_rr` → 2.5 |
| 10 | validity_180 | 66 | 1.154,30 | 1,13 | 2.625,74 | 0,440 | -868,64 | `strategy.setup_validity_minutes` → 180 |
| 11 | rr_3_5 | 72 | 977,44 | 1,10 | 3.635,80 | 0,269 | -1.045,50 | `strategy.tp_rr` → 3.5 |
| 12 | sl_250 | 60 | 728,06 | 1,08 | 3.186,32 | 0,229 | -1.294,88 | `risk.max_sl_ticks` → 250 |

## 2b. Robustez de la exclusión horaria (fase 3)

Misma muestra; cambia solo la ventana de exclusión. Si el efecto es real, las ventanas vecinas también deben mejorar neto y DD frente a la base. Si solo funciona la ventana exacta, es sobreajuste.

| Variante | Ops | Neto | PF | DD | RDD | Δ neto vs base |
|---|---:|---:|---:|---:|---:|---:|
| excl_1100_1300 | 26 | 2.500,18 | 1,92 | 501,90 | 4,981 | +477,24 |
| excl_1200_1400 | 46 | 3.500,94 | 1,65 | 1.835,30 | 1,908 | +1.478,00 |
| excl_1130_1230 | 48 | 3.340,90 | 1,67 | 1.259,18 | 2,653 | +1.317,96 |
| excl_1130_1330+validity_180 | 31 | 2.025,98 | 1,62 | 1.351,58 | 1,499 | +3,04 |

**4 de 4** ventanas vecinas mejoran neto y DD frente a la base. La familia de exclusión es robusta al encuadre; el candidato sigue en pie.

`excl_1130_1330+validity_180` apenas mejora el neto (+3,04); su aporte es de riesgo (DD), no de rentabilidad.

La mejor de la extensión es `excl_1100_1300` (26 ops, RDD 4,981). No se re-selecciona como candidato: elegir el máximo de 4 ventanas después de ver el resultado es doble in-sample. Vale como confirmación de familia, no como nueva promesa.

## 2c. Sensibilidad a costes (estrés)

Base: comisión 0,62 USD/lado y slippage 1 tick/lado. Estrés: se duplican ambos (1,24/lado y 2 ticks/lado), que es el escenario adverso realista para un broker retail.

| Variante | Ops | Neto | PF | DD | RDD | Δ neto vs base |
|---|---:|---:|---:|---:|---:|---:|
| cost_x2 | 72 | 1.436,88 | 1,15 | 3.023,82 | 0,475 | -586,06 |
| excl_1130_1330+cost_x2 | 36 | 2.975,14 | 1,81 | 1.421,08 | 2,094 | +952,20 |
| excl_1130_1330+sl_200+cost_x2 | 17 | 2.638,54 | 2,56 | 843,22 | 3,129 | +615,60 |

El candidato `excl_1130_1330` **sigue ganando a la base incluso con el doble de costes**: el edge no depende de un reprecio optimista.
El estrés resta 228,68 USD al candidato (3.203,82 → 2.975,14), pero conserva +952,20 frente a la base.

## 2d. Concentración y estabilidad temporal (W1–W6)

Calculado sobre los trades de la re-ejecución limpia `reports/autoloop/repro_concentracion_20261125T004249Z`. Cabeceras reproducidas: sí. Detalle en `reports/autoloop/concentracion.json`.

| Métrica | Candidato | Base viva | Original |
|---|---:|---:|---:|
| Ops | 36 | 72 | 38 |
| Neto USD | 3.203,82 | 2.022,94 | 661,44 |
| Expectancy USD/op | 88,99 | 28,10 | 17,41 |
| Avg R | 0,470 | 0,180 | 0,130 |
| Ganadoras / perdedoras | 17 / 19 | 26 / 46 | 12 / 26 |
| Top-5 USD | 3.350,56 | 3.604,34 | 3.268,92 |
| Top-5 % del neto | 104,6 % | 178,2 % | 494,2 % |
| Neto sin top-5 | -146,74 | -1.581,40 | -2.607,48 |
| Mejor mes | 2025-06 (+1.091,66, 34,1 %) | 2025-10 (+1.120,32, 55,4 %) | 2025-12 (+886,32, 134,0 %) |
| Peor mes | 2025-07 (-703,14) | 2025-09 (-1.287,24) | 2025-01 (-619,42) |
| Mejor instrumento | MNQ (100,0 %) | MNQ (100,0 %) | MNQ (100,0 %) |
| Racha perdedora máx. | 7 | 13 | 10 |
| DD máx. USD | 1.376,54 | 2.891,66 | 1.967,82 |
| Duración DD máx. | 182,0 días | 172,9 días (sin recuperar) | 172,9 días (sin recuperar) |

**Cabeceras de la re-ejecución limpia:**

| Variante | Ops | Neto | PF | DD | RDD | ¿Coincide? |
|---|---:|---:|---:|---:|---:|---|
| candidate | 36 | 3.203,82 | 1,90 | 1.376,54 | 2,3274 | sí |
| base | 72 | 2.022,94 | 1,22 | 2.891,66 | 0,6996 | sí |
| original | 38 | 661,44 | 1,13 | 1.967,82 | 0,3361 | sí |

Run: `reports/autoloop/repro_concentracion_20261125T004249Z` · 745,5 s · checks: cabeceras=sí, meses=sí, DD=sí.

**Lectura:** el candidato concentra **104,6 %** del neto en 5 de 36 operaciones; las otras 31 suman **-146,74 USD**. Su mejor mes (2025-06) aporta 34,1 % y el mejor instrumento es MNQ (único, 100 %: no hay diversificación por instrumento). Racha perdedora máxima 7; el DD máximo (1.376,54) tardó 182,0 días en recuperarse. **Es un edge de pocos eventos, no una ventaja frecuente.**

La base está aún más concentrada (178,2 %; sin top-5, -1.581,40) y el original es extremo (494,2 %; sin top-5, -2.607,48). El candidato mejora la concentración relativa, pero no deja de depender de cinco operaciones.

### Otras variantes de la extensión

| Variante | Ops | Neto | PF | DD | RDD |
|---|---:|---:|---:|---:|---:|
| excl_1100_1300+sl_200 | 15 | 2.362,02 | 2,47 | 501,90 | 4,706 |
| excl_1130_1330+sl_200 | 17 | 2.805,52 | 2,74 | 813,86 | 3,447 |
| excl_1130_1330+daily_loss_2 | 36 | 3.203,82 | 1,90 | 1.376,54 | 2,327 |


## 3. Mejoras priorizadas por impacto en rentabilidad

Ordenadas por Δneto medido frente a la base. El RDD y el DD indican el coste en riesgo; ninguna está aplicada. **3** variantes superan a la base en neto; se listan las 3 mejores. `daily_loss_2`, `range_min_15` salen idénticas a la base en neto y DD: no llegaron a activarse en esta muestra, así que no son una palanca demostrada.

**Lectura desde la comparación viva vs original:**

- El stop es la palanca que separa directamente la viva de la original. La fila `sl_200` aísla el cambio 300→200: +448,84 USD de neto y -587,20 USD de DD frente a la viva. Volver a 200 es la primera acción de parámetro; la exclusión horaria puede dar más Δneto, pero es una selección in-sample más frágil.
- El sizing de la viva (10 contratos) no se reduce: `contracts_7` mide -353,46 USD de neto y -110,46 USD de DD frente a la base. Menos contratos recorta algo de dolor, pero sacrifica más rentabilidad.

**Lectura de confianza:** el candidato `excl_1130_1330` debe 104,6 % del neto a 5 operaciones; sin ellas, -146,74. La mejora #1 es `excl_1130_1330` (+1.180,88 USD), con confianza baja-media; es la mayor de la muestra, pero frágil.

| # | Regla / parámetro | Valor propuesto | Δ neto esperado | Δ DD | Confianza | Riesgo | Verificación |
|---:|---|---|---:|---:|---|---|---|
| 1 | `excl_1130_1330` | `risk.entry_exclusion_start` → 11:30; `risk.entry_exclusion_end` → 13:30 | +1.180,88 | -1.515,12 | baja-media | Menos oportunidades y dependencia de un horario elegido in-sample. Top-5 = 104,6 % del neto; sin ellas, -146,74. | `verify_variant.py --id excl_1130_1330` + forward |
| 2 | `excl_1130_1330+sl_200` | `risk.entry_exclusion_start` → 11:30; `risk.entry_exclusion_end` → 13:30; `risk.max_sl_ticks` → 200 | +782,58 | -2.077,80 | muy baja (17 ops) | Menos oportunidades y dependencia de un horario elegido in-sample. Recorta stops profundos: menos operaciones y posible sesgo a stops que el mercado habría respetado. Muestra insuficiente (17 ops): no promover. | `verify_variant.py --id excl_1130_1330+sl_200`; no promover |
| 3 | `sl_200` | `risk.max_sl_ticks` → 200 | +448,84 | -587,20 | media | Recorta stops profundos: menos operaciones y posible sesgo a stops que el mercado habría respetado. | `verify_variant.py --id sl_200` + forward |

Detalle y verificación de cada una:

### 1. `excl_1130_1330` — 1.180,88 USD

- **Cambio exacto:** `risk.entry_exclusion_start` → 11:30; `risk.entry_exclusion_end` → 13:30.
- **Efecto medido:** 36 ops, neto 3.203,82 (Δ 1.180,88), PF 1,90, DD 1.376,54 (Δ -1.515,12), RDD 2,327.
- **Riesgo:** Menos oportunidades y dependencia de un horario elegido in-sample. Top-5 = 104,6 % del neto; sin ellas, -146,74.
- **Verificado:** re-ejecutado en un proceso aparte; ops, neto, PF y DD coinciden. La comprobación debe dar 36 ops, 3.203,82, PF 1,90 y DD 1.376,54. Después, forward mínimo con muestra prospectiva.

- **Confianza condicionada:** top-5 = 104,6 % del neto; sin esas cinco, -146,74. Edge de pocos eventos, no una ventaja frecuente.

### 2. `excl_1130_1330+sl_200` — 782,58 USD

- **Cambio exacto:** `risk.entry_exclusion_start` → 11:30; `risk.entry_exclusion_end` → 13:30; `risk.max_sl_ticks` → 200.
- **Efecto medido:** 17 ops, neto 2.805,52 (Δ 782,58), PF 2,74, DD 813,86 (Δ -2.077,80), RDD 3,447.
- **Riesgo:** Menos oportunidades y dependencia de un horario elegido in-sample. Recorta stops profundos: menos operaciones y posible sesgo a stops que el mercado habría respetado. Muestra insuficiente (17 ops): no promover.
- **Verificado:** re-ejecutado en un proceso aparte; ops, neto, PF y DD coinciden. La comprobación debe dar 17 ops, 2.805,52, PF 2,74 y DD 813,86. Con 17 ops no se promueve: primero ampliar muestra.

### 3. `sl_200` — 448,84 USD

- **Cambio exacto:** `risk.max_sl_ticks` → 200.
- **Efecto medido:** 46 ops, neto 2.471,78 (Δ 448,84), PF 1,39, DD 2.304,46 (Δ -587,20), RDD 1,073.
- **Riesgo:** Recorta stops profundos: menos operaciones y posible sesgo a stops que el mercado habría respetado.
- **Verificación exacta:** `python research/verify_variant.py --id sl_200` debe dar 46 ops, 2.471,78, PF 1,39 y DD 2.304,46. Después, forward mínimo con muestra prospectiva.

## 4. Candidato a forward

El mejor RDD absoluto de `resultados.jsonl` es `excl_1100_1300` (4,981; 26 ops); es una ventana de robustez de fase 3; elegirla como candidato sería doble in-sample.

**excl_1130_1330** — `risk.entry_exclusion_start` → 11:30; `risk.entry_exclusion_end` → 13:30.

- Muestra: 36 operaciones, neto 3.203,82 USD (Δ +1.180,88 vs base), PF 1,90, DD 1.376,54, RDD 2,327.
- **Concentración:** top-5 = 104,6 % del neto; sin esas cinco, -146,74; racha perdedora 7; el DD máximo tardó 182,0 días en recuperarse. Confianza baja-media.
- **Robustez:** 4/4 ventanas de exclusión mejoran neto y DD.
- **Qué falta:** un lock forward propio, muestra prospectiva y diluir la dependencia de 5 operaciones antes de subir tamaño. El holdout sigue sellado.
- **No hacer:** aplicarlo al 8765 ni promoverlo a tamaño pleno; solo forward mínimo con muestra prospectiva.

### Reproducción independiente

`excl_1130_1330+sl_200` re-ejecutado en un proceso aparte: 17 ops, neto 2.805,52, PF 2,74, DD 813,86.
Coincide con el bucle: ops=True, neto=True, PF=True, DD=True; Δneto=0,00.

`excl_1130_1330` re-ejecutado en un proceso aparte: 36 ops, neto 3.203,82, PF 1,90, DD 1.376,54.
Coincide con el bucle: ops=True, neto=True, PF=True, DD=True; Δneto=0,00.

## 5. Control del bucle

```bash
touch reports/autoloop/STOP    # termina en el siguiente punto seguro
touch reports/autoloop/PAUSA   # pausa sin perder progreso
rm reports/autoloop/PAUSA      # reanuda
```

**Estado actual: parado.** STOP detectado el 2026-11-25T00:28:45Z (ver `runner.log`), 25/25 tandas cerradas y sin proceso en RAM: 0 MB. No quedan hipótesis abiertas. Para reanudar:

```bash
rm reports/autoloop/STOP
python -u research/auto_loop.py
```

Al arrancar ocupa unos 240 MB; corre a prioridad idle y se autopausa si la RAM libre baja de 900 MB. La fase 3 probó ventanas vecinas de exclusión (11:00–13:00, 12:00–14:00, 11:30–12:30) y la exclusión con validez 180; su veredicto está en la sección 2b y el ranking crudo en `resumen_bucle.md`.

## 6. Garantías

- `data/config.json` y `profiles/live_8765/config.json` conservan el mismo SHA-256 (ver sección 1); el proceso del 8765 no se reinició ni se modificó.
- Sin escrituras en la DB del 8765; solo lectura.
- Holdout no leído; 2024 no usado.

## 7. Veredicto

- La manual gana **+1.361,50 USD** en la muestra (PF 1,22 vs 1,13; expectancy 0,180 vs 0,130 R; RDD 0,6996 vs 0,3361), pero **no domina en riesgo**: DD +923,84. El IC95 % del delta incluye cero.
- La ventaja es **cobertura de señales + sizing**, no una mejora de la expectancy por operación; la tabla agregada no aísla la ejecución por señal. El Stop 200 → 300 es el lastre (-448,84 de neto y +587,20 de DD).
- **No cambiar el 8765 hoy.** No hay forward de ninguna de las dos, el holdout está sellado y la muestra es de 72/38 ops in-sample.

- La mejora de mayor Δneto es `excl_1130_1330` (+1.180,88 USD; confianza baja-media).
- **Candidato a forward:** `excl_1130_1330` (36 ops, RDD 2,327).
- **Mejor RDD absoluto:** `excl_1100_1300` (4,981; es una ventana de robustez de fase 3; elegirla como candidato sería doble in-sample.)

Ninguna se despliega sin forward.
