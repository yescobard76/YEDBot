# Scorecard continuo y criterios de promoción — 11 presets default

**Fecha:** 2026-11-21.  
**Fuente:** `reports/backtest/equity_continuous_dev.json` (362 sesiones, capital arrastrado).  
**Implementación:** `reports/backtest/continuous_scorecard.py`.  
**Holdout:** sellado; no ejecutado ni inspeccionado.  
**Protocolo/configuración activa:** no modificados.

> Este scorecard se calcula sobre la curva continua, no sobre bloques con capital reiniciado. Los criterios de la sección 1 se fijaron en el script antes de generar y ordenar la tabla de la sección 3. No se ajustaron después de ver los resultados.

## 1. Criterios de promoción (v1.0)

La promoción a la siguiente fase exige **seis puertas**. No es una media ponderada: todas deben pasar.

| Puerta | Criterio | Umbral | Razón |
|---|---|---:|---|
| **P1** | Neto positivo | `net > 0` | No promover un sistema perdedor. |
| **P2** | Concentración | `exW4 > 0` y `≥4/6` bloques positivos | Evita depender de W4 o de una sola ventana; coherencia con el criterio de estabilidad previo. |
| **P3** | DD agregado | `DD ≤ 2.000 USD` | Es el límite G6 ya usado en el protocolo. |
| **P4** | Tiempo bajo agua | `TUW ≤ 35 %` de las sesiones (≤126/362) | No más de un tercio de la muestra por debajo del máximo previo. |
| **P5** | Recuperación | DD máximo recuperado en `≤126 sesiones` | El drawdown principal debe recuperarse dentro de un horizonte comparable a P4; si nunca se recupera, falla. |
| **P6** | Eficiencia | `neto / DD ≥ 0,50` | Ganar al menos la mitad del peor drawdown asumido. |

**Reglas de clasificación:**

- **A — promoción:** pasan P1–P6.
- **B — solo ampliar muestra:** pasan P1, P2, P3 y P6, pero fallan P4 y/o P5. No es promoción.
- **C — no:** falla alguna de P1, P2, P3 o P6.

**G4 sigue fuera del scorecard:** la muestra mínima de 80 operaciones sigue siendo requisito para pasar a papel. El scorecard no la sustituye ni la rebaja; se reporta como diagnóstico aparte.

### Definiciones de las métricas

- **DD agregado:** máximo drawdown de cierre de la curva diaria continua, en USD y en % del pico de equity.
- **TUW:** número de sesiones con equity por debajo del máximo previo, dividido entre las 362 sesiones. La **racha** es la secuencia más larga en esa condición.
- **Recuperación:** desde el valle del DD máximo hasta la primera sesión que vuelve a igualar el pico de ese DD. Si no ocurre antes del final, `recuperado = no` y se muestran las sesiones valle→fin, que **no** son una recuperación.
- **DD fin / TUW fin:** drawdown y sesiones bajo agua al cierre de la muestra. Puede haber recuperado el DD máximo y seguir bajo agua por un pico posterior.
- **Neto/DD:** `neto agregado / DD máximo`. No es MAR, no está anualizado y no usa tasa libre de riesgo.
- **Score:** número de puertas P1–P6 que pasa (0–6). Es diagnóstico; la promoción exige las seis.

## 2. Cómo se genera

```bash
python reports/backtest/continuous_scorecard.py
```

El script lee la curva continua, valida que el DD diario coincide con el DD agregado, que la equity final coincide y que el neto es `final − inicial`, y escribe:

- `reports/backtest/continuous_scorecard.json`
- `reports/backtest/continuous_scorecard.csv`

No ejecuta backtests, no abre el holdout y no toca la configuración activa. Los 11 presets pasaron las comprobaciones de integridad.

## 3. Scorecard de los 11 presets

Orden de la fuente, no ranking. La tabla se genera después de fijar los criterios.

| Preset | Ops | Neto $ | DD $ | DD % | TUW sesiones | TUW % | Racha | Recuperación | DD fin $ | TUW fin | Neto/DD | Ex-W4 $ | Pos | Score | Tier |
|---|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|---:|---:|---|
| `baseline` | 38 | 661,44 | 1.967,82 | 7,14 | 290 | 80,11 | 120 | no (27 al final) | 1.895,44 | 120 | 0,336 | -1.372,68 | 3/6 | 2/6 | C |
| `entry_breakout_direct` | 4 | 390,84 | 305,20 | 1,22 | 40 | 11,05 | 40 | sí (39) | 0,00 | 0 | 1,281 | 248,32 | 2/6 | 5/6 | C |
| `entry_or_level` | 4 | 482,34 | 207,96 | 0,83 | 39 | 10,77 | 39 | sí (5) | 0,00 | 0 | 2,319 | 482,34 | 1/6 | 5/6 | C |
| `entry_retrace_382` | 31 | -28,76 | 2.053,10 | 7,69 | 328 | 90,61 | 321 | no (198 al final) | 1.715,48 | 321 | -0,014 | -1.514,12 | 2/6 | 0/6 | C |
| `smt_window_120` | 39 | 1.005,98 | 2.224,32 | 7,90 | 277 | 76,52 | 120 | no (27 al final) | 2.151,94 | 120 | 0,452 | -1.028,14 | 4/6 | 1/6 | C |
| `smt_tolerance_16` | 48 | 1.245,40 | 2.185,12 | 7,82 | 294 | 81,22 | 120 | no (27 al final) | 1.682,74 | 120 | 0,570 | -586,02 | 4/6 | 2/6 | C |
| `setup_validity_240` | 51 | 1.695,96 | 1.583,44 | 5,80 | 313 | 86,46 | 120 | sí (66) | 1.429,14 | 120 | 1,071 | -338,16 | 3/6 | 4/6 | C |
| `sl_depth_6` | 15 | 1.454,40 | 1.285,10 | 4,91 | 241 | 66,57 | 218 | sí (167) | 0,00 | 0 | 1,132 | 188,32 | 4/6 | 4/6 | **B** |
| `sl_buffer_12` | 37 | 84,90 | 2.005,08 | 7,42 | 290 | 80,11 | 120 | no (27 al final) | 1.944,70 | 120 | 0,042 | -1.525,94 | 3/6 | 1/6 | C |
| `recovery_off` | 41 | 468,62 | 2.105,64 | 7,64 | 294 | 81,22 | 120 | no (8 al final) | 2.105,64 | 120 | 0,223 | -1.796,26 | 3/6 | 1/6 | C |
| `rr_2_5` | 38 | 742,94 | 1.967,82 | 7,11 | 269 | 74,31 | 120 | no (27 al final) | 1.950,44 | 120 | 0,378 | -1.059,68 | 3/6 | 2/6 | C |

**Resultado:** **A 0 · B 1 · C 10.**

## 4. Matriz de puertas

`✔` pasa, `✘` falla.

| Preset | P1 Neto | P2 Concentración | P3 DD | P4 TUW | P5 Recuperación | P6 Neto/DD | Tier |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| `baseline` | ✔ | ✘ | ✔ | ✘ | ✘ | ✘ | C |
| `entry_breakout_direct` | ✔ | ✘ | ✔ | ✔ | ✔ | ✔ | C |
| `entry_or_level` | ✔ | ✘ | ✔ | ✔ | ✔ | ✔ | C |
| `entry_retrace_382` | ✘ | ✘ | ✘ | ✘ | ✘ | ✘ | C |
| `smt_window_120` | ✔ | ✘ | ✘ | ✘ | ✘ | ✘ | C |
| `smt_tolerance_16` | ✔ | ✘ | ✘ | ✘ | ✘ | ✔ | C |
| `setup_validity_240` | ✔ | ✘ | ✔ | ✘ | ✔ | ✔ | C |
| `sl_depth_6` | ✔ | ✔ | ✔ | ✘ | ✘ | ✔ | **B** |
| `sl_buffer_12` | ✔ | ✘ | ✘ | ✘ | ✘ | ✘ | C |
| `recovery_off` | ✔ | ✘ | ✘ | ✘ | ✘ | ✘ | C |
| `rr_2_5` | ✔ | ✘ | ✔ | ✘ | ✘ | ✘ | C |

## 5. Lectura

1. **Ningún preset pasa a promoción.** El único B es `sl_depth_6`: cumple P1, P2, P3 y P6, pero falla P4 (66,57 % bajo agua) y P5 (167 sesiones para recuperar el DD máximo). B significa “ampliar muestra”, no “promover”.
2. **Los dos presets de entrada tienen el mejor perfil de riesgo, pero no son promocionables.** `entry_or_level` y `entry_breakout_direct` tienen TUW de 10,8–11,1 %, recuperan en 5–39 sesiones y neto/DD de 1,28–2,32. Fallan P2: solo 1/6 y 2/6 bloques positivos, con 4 operaciones. El score 5/6 no compensa la falta de muestra ni la concentración.
3. **El DD no es el único problema; el tiempo bajo agua es peor de lo que sugería el DD.** 8/11 terminan bajo agua y 7/11 no recuperan nunca su DD máximo. Cinco presets superan los 2.000 USD de DD: `smt_window_120` (2.224,32), `smt_tolerance_16` (2.185,12), `recovery_off` (2.105,64), `entry_retrace_382` (2.053,10) y `sl_buffer_12` (2.005,08). `baseline` y `rr_2_5` pasan el DD por poco, pero fallan eficiencia y recuperación.
4. **La recuperación del DD máximo no equivale a estar recuperado.** `setup_validity_240` recupera su DD máximo en 66 sesiones, pero sigue con 1.429,14 USD de DD y 120 sesiones bajo agua al final por el pico posterior de W4. `sl_depth_6` es el único con DD final cero y 0 sesiones bajo agua al cierre.
5. **El patrón de 120 sesiones bajo agua al final se repite.** Siete presets terminan exactamente con 120 sesiones desde el pico de W4 hasta el final; no es un problema de una operación, sino de la secuencia posterior al pico. `entry_retrace_382` es el extremo: 321 sesiones de racha y 90,61 % del tiempo bajo agua.
6. **La eficiencia separa a los candidatos.** Solo cinco presets superan neto/DD de 0,50: los dos de entrada, `smt_tolerance_16` (0,570), `setup_validity_240` (1,071) y `sl_depth_6` (1,132). De ellos, solo `sl_depth_6` pasa también concentración y DD; por eso es el único B.

## 6. Decisión

- **No se promueve ningún preset.** No se abre el holdout ni se pasa a papel con esta muestra.
- **`sl_depth_6` queda en B:** es el único que combina P&L ex-W4 positivo, ≥4/6 bloques positivos, DD ≤2.000 y neto/DD ≥0,50. Antes de cualquier promoción necesita ampliar muestra (G4: ≥80 operaciones) y mejorar o justificar TUW/recuperación; con 15 operaciones no alcanza.
- **Los presets de 4 operaciones no se promueven** aunque su DD/TUW sea bajo: la muestra no permite distinguir habilidad de suerte y su concentración por bloque es peor que la de `sl_depth_6`.
- **No se sigue comparando como si hubiera un ganador.** El scorecard fija el resultado: A 0, B 1, C 10. La siguiente comparación debe ser una ampliación de muestra o una nueva hipótesis, no otro ranking sobre los mismos 362 días.

## 7. Límites

- Solo cubre los **11 presets default** con curva continua. Los opt-in `sl_cap_600`, `direct_sl_cap_600`, `deep_stop_sl_cap_600` y `entry_or_level_sl_cap_600` no tienen curva continua propia y no se puntúan aquí.
- TUW y DD se miden con **cierres diarios**; no capturan drawdown intradía. La curva continua es la base disponible.
- La recuperación se mide solo para el **DD máximo**, no para todos los episodios; TUW total y racha cubren la exposición agregada.
- Neto/DD no está anualizado ni ajustado por riesgo; no debe presentarse como MAR.
- El score de 0–6 es un conteo de puertas, no una puntuación ponderada ni una probabilidad.
- No se ejecutó ningún backtest nuevo ni el holdout. `holdout_executed=false` en la fuente y el script rechaza una fuente con holdout ejecutado.
- No se modificaron protocolo, lock, configuración activa ni código de estrategia.

## 8. Artefactos

- `reports/backtest/continuous_scorecard.py` — cálculo y criterios v1.0.
- `reports/backtest/continuous_scorecard.json` — métricas, puertas y tiers.
- `reports/backtest/continuous_scorecard.csv` — tabla plana.
- `reports/backtest/SCORECARD_CONTINUO.md` — este documento.
- `reports/backtest/equity_continuous_dev.json` — curva de origen.
