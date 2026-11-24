# Floor sobre el replay paper de 56 operaciones

**Alcance:** 2025-01-10 a 2026-06-30, 56 operaciones paper. Holdout no usado.  
**Naturaleza:** comparación descriptiva in-sample; no es validación forward.  
**Fuente:** `reports/backtest/profile_filter_replay.json` + `preset_card_8766.db`  
**Resultado estructurado:** `reports/backtest/floor_paper_replay.json`

## 1. Reglas

El replay paper tiene 56 operaciones; el rechazo `stop/ORB >= 0,25` deja 44 y elimina 12. El floor amplía el stop a `0,25 × ORB` sin rechazar por ratio. Se comparan las dos políticas de target ya usadas en W1–W6:

| Política | Stop | Target |
|---|---|---|
| `floor_original` | `0,25 × ORB` | target original del replay |
| `floor_recalc` | `0,25 × ORB` | `3R` del stop ampliado |

El tope `max_sl_ticks=200` se aplica **solo a las 12 señales de bajo ratio que el floor amplía**. Las 44 de alto ratio se dejan intactas: el replay paper ya las aceptó con sus stops originales, muchos >200 ticks. Imponer 200 a todas habría eliminado 29 operaciones de alto ratio y habría convertido esto en otro experimento.

De las 12 eliminadas, **2** superan el tope al ampliarse (`2025-01-27-long-1737990900`, `2026-03-23-long-1774278000`); quedan **10** señales de bajo ratio para el floor. La qty es la del replay y no se recalcula por equity.

## 2. Resultado agregado

| Brazo | Ops | Neto USD | PF | R medio (riesgo original) | DD USD | DD % | Peor racha |
|---|---:|---:|---:|---:|---:|---:|---:|
| Baseline paper | 56 | +3.317,16 | 1.5 | 0.35 | 2.128,28 | 8.51% | 10 |
| Rechazo ratio oficial (44) | 44 | +4.450,38 | 1.96 | 0.55 | 2.220,02 | 8.88% | 10 |
| Rechazo ratio, misma qty (44) | 44 | +4.543,62 | 2.0 | 0.55 | 2.128,28 | 8.51% | 10 |
| Floor + target original | 54 | +3.852,06 | 1.58 | 0.44 | 2.128,28 | 8.51% | 10 |
| Floor + target 3R | 54 | +4.384,56 | 1.62 | 0.46 | 2.128,28 | 8.51% | 10 |

El rechazo oficial deja **+4.450,38** con 44 operaciones; con la misma qty del replay, **+4.543,62**. La diferencia de +93,24 viene de una sola operación (`2025-09-19`), que el rechazo ejecuta con qty 3 y el baseline con qty 2. El floor original deja **+3.852,06** y el floor 3R **+4.384,56**. 
Frente al rechazo oficial, el floor original queda **-598,32** y el 3R **-65,82**. Frente al rechazo con la misma qty, quedan **-691,56** y **-159,06**.

El DD no debe leerse como una mejora del floor: el rechazo oficial usa otra qty. Con la misma qty, el rechazo también marca 2.128,28. El PF sí es comparable y favorece al rechazo: 1,96 oficial / 2,00 misma qty frente a 1,62 del floor 3R. El floor 3R genera más beneficio bruto, pero también más pérdida bruta; su neto casi empata, su perfil es de mayor varianza.

## 2b. La lectura en R

El P&L en USD usa la qty fija del replay. Al ampliar el stop, una pérdida cuesta más dólares aunque el R —normalizado por el riesgo original— no empeore. Por eso conviene mirar las dos métricas:

| Cohorte | Baseline R | Floor original R | Floor 3R R |
|---|---:|---:|---:|
| 54 ops (riesgo original) | 21.74 | 23.72 | 24.77 |
| 10 de bajo ratio | -2.30 | -0.30 | 0.75 |

El rechazo suma 24.04R. El floor 3R suma 24.77R, por encima del rechazo, y el floor original 23.72R, por debajo. Pero el R-PF sigue favoreciendo al rechazo: 2.09 vs 1.70 del 3R y 1.75 del original. En USD, en cambio, el 3R queda 65,82 por debajo del rechazo oficial y 159,06 por debajo con la misma qty. La divergencia es el efecto de la qty fija: el 3R gana más R en las 10 de bajo ratio (+0,75R) pero pierde 159,06 USD por el mayor tamaño en dólares de los stops ampliados. El floor original pierde frente al rechazo en ambas lecturas; el 3R gana en R total pero no en calidad del R.

## 3. Las 12 eliminadas y los ganadores

En el baseline paper hay **2 ganadores** entre las 12 eliminadas: `2025-03-21` (+501,30) y `2026-05-22` (+318,80). El dato de **tres ganadores** corresponde al floor original, no al rechazo: al ampliar el stop se suma `2025-01-15`, que pasa de -168,70 a +516,30. El target 3R conserva dos ganadores en el grupo (`2025-01-15` y `2025-03-21`) pero pierde `2026-05-22`.

| Señal | Ratio | Baseline | Floor original | Floor 3R |
|---|---:|---:|---:|---:|
| `2025-01-15-long-1736953200` | 0.108 | -168,70 | +516,30 | +1.178,80 |
| `2025-01-27-long-1737990900` | 0.094 | -236,20 | cap | cap |
| `2025-03-17-short-1742224500` | 0.110 | -203,70 | -421,20 | -421,20 |
| `2025-03-21-long-1742568300` | 0.114 | +501,30 | +501,30 | +1.116,30 |
| `2025-05-16-short-1747405800` | 0.217 | -258,70 | -301,20 | -301,20 |
| `2026-01-13-short-1768316400` | 0.170 | -203,70 | -288,70 | -288,70 |
| `2026-02-19-long-1771515900` | 0.136 | -231,20 | -401,20 | -401,20 |
| `2026-03-19-long-1773932400` | 0.201 | -239,22 | -296,22 | -296,22 |
| `2026-03-23-long-1774278000` | 0.091 | -203,70 | cap | cap |
| `2026-04-06-short-1775494800` | 0.213 | -62,22 | -20,22 | -20,22 |
| `2026-05-22-long-1779470100` | 0.066 | +318,80 | +318,80 | -426,20 |
| `2026-06-17-short-1781719200` | 0.195 | -237,72 | -299,22 | -299,22 |

**Recuperadas por el floor original:** 1. **Ganadores perdidos:** 0. **Recuperadas por el 3R:** 1; **ganadores perdidos:** 1.

## 4. Descomposición

| Componente | Neto USD | Lectura |
|---|---:|---|
| Rechazo oficial 44 | +4.450,38 | Las 44 de alto ratio, sin tocar |
| Rechazo misma qty 44 | +4.543,62 | Control con la qty del replay |
| Baseline 54 misma qty | +3.758,56 | 56 menos las 2 cap |
| 12 eliminadas, baseline | -1.224,96 | 2 ganadoras y 10 perdedoras |
| 2 eliminadas por cap | -439,90 | Se quedan fuera del floor |
| 10 de bajo ratio, baseline | -785,06 | Mismo subconjunto que el floor |
| 10 de bajo ratio, floor original | -691,56 | +93,50 vs baseline |
| 10 de bajo ratio, floor 3R | -159,06 | +626,00 vs baseline |

El floor original mejora al baseline de las 54 en **+93,50** y el 3R en **+626,00**. Frente al rechazo con la misma qty, el original queda **-691,56** y el 3R **-159,06**; frente al oficial, **-598,32** y **-65,82**. Con la misma qty, la diferencia con el rechazo es exactamente el resultado de las 10 señales de bajo ratio que el floor añade.

Si se conservan las 2 cap con su resultado baseline, el floor original de 56 queda en **+3.412,16** (+95,00 vs baseline 56) y el 3R en **+3.944,66** (+627,50). Excluir las 2 cap aporta **+439,90**, una parte relevante de la mejora aparente.

## 5. ¿Cambia respecto a W1–W6?

| Dato | W1–W6 | Replay paper |
|---|---:|---:|
| Ops baseline / rechazo | 38 / 14 | 56 / 44 |
| Rechazo: neto / PF / DD | +3.026,88 / 3,57 / 839,90 | +4.450,38 / 1,96 / 2.220,02 |
| Ops floor / cap | 34 / 4 | 54 / 2 |
| Floor original: neto / PF / DD | +1.363,20 / 1,34 / 1.440,00 | +3.852,06 / 1.58 / 2.128,28 |
| Floor 3R: neto / PF / DD | +1.724,96 / 1,39 / 1.534,04 | +4.384,56 / 1.62 / 2.128,28 |
| Gap rechazo − floor 3R | +1.301,92 USD | +65,82 oficial / +159,06 misma qty |
| R rechazo vs floor 3R | 14,53 vs 5,79 | 24,04 vs 24,77 |

El resultado **sí cambia**: en W1–W6 el rechazo superaba al floor 3R por 1.301,92 USD y por 8,74R; en el paper la ventaja en USD se reduce a 65,82 (o 159,06 con la misma qty), y en R el floor 3R supera al rechazo (24,77 vs 24,04). La razón principal es que el paper solo añade 10 operaciones de bajo ratio, 2 quedan fuera por el tope, la qty es fija y `2025-01-15` se recupera con fuerza. La muestra es pequeña y el replay ya contiene las 44 de alto ratio; no es una validación forward.

## 6. Conclusión

- El floor original conserva **los 2 ganadores originales de las eliminadas** y recupera **1 perdedora** (`2025-01-15`); el grupo pasa a 3 ganadores. El 3R conserva **1** de los 2 originales y pierde **1** (`2026-05-22`).
- En USD, el floor original queda **-598,32** por debajo del rechazo oficial; el 3R queda **-65,82** (o **-159,06** con la misma qty). En R, el 3R **supera** al rechazo (24,77 vs 24,04); el original queda por debajo (23,72).
- Por tanto, el resultado **sí cambia respecto a W1–W6**: el rechazo deja de ser claramente superior en neto y en R total. Sigue ganando en USD por un margen estrecho y conserva mejor PF (1,96/2,00 vs 1,62) y mejor R-PF (2,09 vs 1,70), pero pierde en R total frente al target 3R (24,04 vs 24,77); su DD oficial no es comparable por la qty. El floor original sigue por debajo en ambas lecturas.
- La causa hay que buscarla en la composición: solo 10 operaciones de bajo ratio, 2 cap, qty fija y una muestra paper pequeña. No es una validación forward ni autoriza promoción.
- El holdout sigue sin usarse.

## 7. Verificación

- IDs del replay y DB: coinciden (56).
- Simulación de control contra el baseline paper: 1 discrepancia > 0,01 USD; neto control +3.318,66 vs paper +3.317,16. La única diferencia es `2025-11-28` (+1,50 USD por redondeo de sesión).
- Las 44 de alto ratio no cambian con el floor: 0 discrepancias > 0,01 USD.
- Rechazo oficial 44: +4.450,38; misma qty: +4.543,62; diferencia +93,24 por `2025-09-19`.
- 12 eliminadas = 2 cap + 10 floor; 56 - 2 = 54 operaciones floor; 44 + 10 = 54.

JSON: `reports\backtest\floor_paper_replay.json`  
Markdown: `reports\backtest\FLOOR_PAPER_REPLAY.md`
