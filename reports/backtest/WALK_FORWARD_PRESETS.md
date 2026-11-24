# Walk-forward de presets dentro de W1–W6

**Fecha:** 2026-11-21.  
**Fuente:** `reports/backtest/presets_default_dev.json` (11 presets default, seis ventanas W1–W6).  
**Implementación:** `reports/backtest/walk_forward_presets.py`.  
**Holdout:** sellado; no ejecutado ni inspeccionado.  
**Protocolo/configuración activa:** no modificados.

> Este walk-forward usa los P&L por bloque con capital inicial de 25.000 USD, no la curva continua. Cada bloque se ejecutó de forma independiente, así que los P&L son comparables entre presets y no dependen de la trayectoria de capital de otro preset. No se mezcla esta base con el scorecard continuo.

## 1. Regla pre-registrada

La selección se fija antes de mirar el resultado de test:

- **Entrenamiento expansivo:** W1..Wt.
- **Test:** W(t+1), para t = 1..5. Por tanto, hay cinco folds y se evalúan W2, W3, W4, W5 y W6. W1 solo se usa para entrenar en el primer fold.
- **Elegibilidad:** al menos **5 operaciones** en entrenamiento y neto de entrenamiento **> 0**. El mínimo de 5 evita seleccionar presets de 1–4 operaciones; no es el G4 de 80.
- **Score:** `neto de entrenamiento / max(peor DD de bloque de entrenamiento, 1 USD)`.
- **Desempate:** mayor neto, después menor peor DD y después nombre.
- **Fallback:** si ningún preset es elegible, cash con retorno 0. No se activó en ningún fold.
- **Sin fuga:** la ventana de test no participa en la selección. El JSON lo declara con `test_used_for_selection: false`.

El score usa el **peor DD de bloque**, no un DD agregado, para no inventar una curva entre bloques. La evaluación reporta el P&L y el DD del bloque de test; el resumen usa la suma de P&L de bloques y, como sensibilidad, el retorno compuesto de esos bloques.

## 2. Folds

| Fold | Entrena | Test | Seleccionado | Ops train | Neto train $ | Peor DD train $ | Score train | Neto test $ | DD test $ | PF test | Baseline test $ | Δ vs baseline $ |
|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | W1 | W2 | `setup_validity_240` | 13 | 894,50 | 1.015,36 | 0,881 | +429,28 | 385,60 | 1,89 | +268,40 | **+160,88** |
| 2 | W1–W2 | W3 | `rr_2_5` | 12 | 1.209,22 | 619,42 | 1,952 | −318,46 | 1.084,80 | 0,76 | −110,46 | **−208,00** |
| 3 | W1–W3 | W4 | `smt_window_120` | 22 | 1.123,80 | 619,42 | 1,814 | +2.034,12 | 0,00 | n/d¹ | +2.034,12 | 0,00 |
| 4 | W1–W4 | W5 | `smt_window_120` | 26 | 3.157,92 | 619,42 | 5,098 | −1.036,52 | 1.036,52 | 0,00 | −1.036,52 | 0,00 |
| 5 | W1–W5 | W6 | `smt_window_120` | 31 | 2.121,40 | 1.036,52 | 2,047 | −1.115,42 | 1.187,80 | 0,22 | −858,92 | **−256,50** |

¹ W4 no tuvo pérdidas para `smt_window_120`; el PF de bloque queda no definido (`n/d`), no se fuerza a un número finito.

**Selecciones:** `setup_validity_240` una vez, `rr_2_5` una vez y `smt_window_120` tres veces. Ningún fold selecciona `sl_depth_6`, `entry_or_level` ni `entry_breakout_direct`.

## 3. Resultado agregado de los cinco tests

| Cartera | Tests | Tests positivos | Ops | Neto $ | PF | Peor DD test $ | DD de fronteras $ | Retorno compuesto | Equity final $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **Selección walk-forward** | 5 | 2/5 | 33 | **−7,00** | 0,998 | 1.187,80 | 2.286,62 | **−0,554 %** | 24.861,42 |
| **Baseline siempre** | 5 | 2/5 | 30 | **+296,62** | 1,075 | 1.084,80 | 2.023,76 | +0,719 % | 25.179,87 |
| **Oracle (hindsight)** | 5 | 4/5 | 20 | +3.661,70 | 3,238 | 616,86 | 0,00 | +15,305 % | 28.826,22 |

- **La selección walk-forward pierde 303,62 USD frente a baseline** en la suma de los cinco bloques de test.
- El retorno compuesto es **−0,554 %** para la selección y **+0,719 %** para baseline: **−1,273 puntos porcentuales**.
- El peor DD de test es **1.187,80 USD** para la selección y **1.084,80 USD** para baseline; la selección es peor en DD.
- El **DD de fronteras** (solo puntos de bloque, no intradía) es 2.286,62 frente a 2.023,76; se reporta como sensibilidad, no como DD agregado completo.
- El **oracle** elige el mejor preset de cada test con hindsight y no es una estrategia ejecutable; sirve solo para mostrar que la selección no captura la rotación.

## 4. Lectura

1. **El walk-forward no mejora a baseline.** El selector gana el primer fold con `setup_validity_240`, pero después elige `rr_2_5` (pierde en W3) y se queda con `smt_window_120` durante W4–W6. El resultado agregado es plano-negativo y peor que no seleccionar nada.
2. **La selección se concentra en W4.** `smt_window_120` se elige después de W3 porque su score de entrenamiento se dispara al incluir W4. En W4 empata con baseline (+2.034,12), en W5 también empata y en W6 pierde más que baseline. El selector está comprando el bloque que ya pasó.
3. **Ningún fold elige `sl_depth_6`.** En W1 solo tiene 1 operación y no cumple el mínimo de 5; en W1–W2 tiene 4 y tampoco; en W1–W3 su neto es negativo. No es una validación del candidato B del scorecard, sino una consecuencia de la regla y de la muestra.
4. **Los presets de 4 operaciones quedan fuera por diseño.** `entry_or_level` y `entry_breakout_direct` no alcanzan 5 operaciones en ningún entrenamiento. Es coherente con no seleccionar configuraciones cuya muestra es demasiado pequeña, pero también significa que este walk-forward no los valida.
5. **La muestra de test es corta.** Cinco bloques, un test por fold, sin intervalos de confianza. Un fold positivo y dos negativos no permiten afirmar que el selector sea mejor o peor de forma estable; solo muestran que esta regla no supera a baseline en W1–W6.
6. **La conclusión no cambia:** no hay promoción. El scorecard sigue en **A 0, B 1, C 10** y `sl_depth_6` sigue siendo el único B, pendiente de ampliación de muestra. Este walk-forward no aporta evidencia para abrir el holdout.

## 5. Límites

- **Cinco folds, un bloque de test cada uno.** Es un walk-forward de bloques, no una curva diaria con reentrenamiento; la potencia es baja.
- **Entrenamiento expansivo.** Los primeros folds usan una o dos ventanas; la selección es inestable por construcción. No se probó una ventana rodante fija.
- **Mínimo de 5 operaciones.** Excluye presets de baja frecuencia y puede cambiar las selecciones si se modifica. La regla se fijó antes y no se ajustó después de ver los resultados.
- **Score neto/peor DD.** Favorece configuraciones con DD bajo en entrenamiento y no incorpora PF, concentración ni estabilidad entre bloques. Es una regla simple, no el scorecard completo.
- **P&L de bloque con capital reiniciado.** La suma de bloques es comparable, pero no es una curva de capital real; el retorno compuesto se reporta como sensibilidad.
- **DD de fronteras.** El DD calculado solo con los cinco puntos de bloque no captura el drawdown intradía; el peor DD de test sí es el DD del bloque, pero no el DD agregado de una cartera continua.
- **Sin holdout.** No se ejecutó el holdout, no se ejecutó un backtest nuevo y no se modificó la configuración activa.
- **Sin corrección múltiple.** Este informe no añade pruebas de significancia; el bootstrap y Holm están en `BOOTSTRAP_BLOQUES.md`.

## 6. Artefactos

- `reports/backtest/walk_forward_presets.py` — cálculo reproducible.
- `reports/backtest/walk_forward_presets.json` — folds, selección y resumen.
- `reports/backtest/walk_forward_presets.csv` — tabla plana.
- `reports/backtest/WALK_FORWARD_PRESETS.md` — este documento.
- `reports/backtest/presets_default_dev.json` — fuente de bloques.

Comando:

```bash
python reports/backtest/walk_forward_presets.py
```
