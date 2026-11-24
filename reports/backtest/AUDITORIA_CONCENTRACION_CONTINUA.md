# Auditoría de concentración por bloque y por operación — curva continua

**Fecha:** 2026-11-21.  
**Fuente:** `reports/backtest/equity_continuous_dev.json` (curva continua de 362 sesiones, capital arrastrado).  
**Presets:** los 11 defaults con curva continua.  
**Holdout:** sellado; no ejecutado ni inspeccionado.  
**Protocolo/configuración activa:** no modificados.

> Esta auditoría usa la curva continua, no los resultados por bloque con capital reiniciado. Por eso algunos P&L difieren de los informes anteriores: aquí el sizing de cada operación depende del capital acumulado. No se mezclan ambas bases.

## 1. Método

- `net`: P&L neto de la curva continua de 362 sesiones.
- `W4`: P&L del bloque W4.
- `exW4`: P&L de W1+W2+W3+W5+W6.
- `W4 % neto`: `W4 / net`; si el neto total es ≤ 0 se muestra `—` porque el porcentaje no es interpretable.
- `W4 % positivos`: `W4 / suma de bloques positivos`; mide cuánto del beneficio bruto por bloque viene de W4.
- `DD`: máximo drawdown de la curva continua completa.
- `DD sin W4`: drawdown máximo al eliminar todas las operaciones de W4 y reconstruir la curva desde 25.000 USD.
- `Δ DD W4`: `DD completo − DD sin W4`. **Negativo** significa que W4 reduce el DD (actúa de colchón); positivo significaría que lo aumenta. No es una suma aditiva: el DD es dependiente de la trayectoria.
- `Top`: la operación individual con mayor P&L.
- `Δ DD top`: efecto de eliminar esa operación sobre el DD máximo.
- `Peor op DD`: la operación cuya eliminación reduce más el DD; no es necesariamente la mayor pérdida, sino la que más alivia la trayectoria.
- `DD tras`: DD máximo al eliminar esa operación.

## 2. Titulares

1. **W4 concentra el P&L, no el DD.** Es el bloque más rentable en 9/11 presets; el P&L ex-W4 es negativo en 8/11. Pero quitar W4 **empeora** el DD en 8/11 y no lo cambia en 3/11. Nunca lo mejora.
2. **W4 es un colchón, no la fuente del drawdown.** En 6/11 el pico del DD está en W4 y el valle en W6; en los otros 5, el DD se realiza en W3/W1. W4 aporta el capital que amortigua las pérdidas posteriores. Sin W4, el DD sube entre 616,86 y 1.394,52 USD en los 8 presets afectados.
3. **La mejor operación es crítica para el P&L y neutra para el DD.** En 5/11 su P&L supera el 100 % del neto total; en 6/11, quitarla deja el neto negativo. Sin embargo, quitarla **no cambia el DD máximo en ninguno de los 11**. No genera el drawdown: o cae fuera de la ventana del pico/valle, o desplaza ambos niveles en la misma cuantía.
4. **Ninguna operación explica la mayor parte del DD en muestras normales.** En los 9 presets con ≥15 operaciones, eliminar la peor operación para el DD solo reduce el DD entre 5,2 % y 27,1 %. Solo en los presets de 4 operaciones una sola pérdida explica 50–63 % del DD.
5. **Los “top trades” no son 11 observaciones independientes.** Los 11 mejores trades caen en solo **4 fechas**: seis presets tienen su mejor operación el **2025-12-24 (W4)**, dos el **2025-06-25 (W2)**, dos el **2025-09-23 (W3)** y uno el **2025-01-29 (W1)**. La concentración efectiva es mayor que la que sugiere el número de presets.

## 3. Concentración por bloque

| Preset | Ops | Neto $ | W4 $ | W4 % neto | W4 % positivos | Ex-W4 $ | Pos | DD $ | DD sin W4 $ | Δ DD W4 $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline` | 38 | 661,44 | 2.034,12 | 307,5 % | 76,3 % | -1.372,68 | 3/6 | 1.967,82 | 3.052,62 | -1.084,80 |
| `entry_breakout_direct` | 4 | 390,84 | 142,52 | 36,5 % | 36,5 % | 248,32 | 2/6 | 305,20 | 305,20 | 0,00 |
| `entry_or_level` | 4 | 482,34 | 0,00 | 0,0 % | 0,0 % | 482,34 | 1/6 | 207,96 | 207,96 | 0,00 |
| `entry_retrace_382` | 31 | -28,76 | 1.485,36 | — | 68,6 % | -1.514,12 | 2/6 | 2.053,10 | 3.447,62 | -1.394,52 |
| `smt_window_120` | 39 | 1.005,98 | 2.034,12 | 202,2 % | 64,4 % | -1.028,14 | 4/6 | 2.224,32 | 2.841,18 | -616,86 |
| `smt_tolerance_16` | 48 | 1.245,40 | 1.831,42 | 147,1 % | 62,5 % | -586,02 | 4/6 | 2.185,12 | 2.801,98 | -616,86 |
| `setup_validity_240` | 51 | 1.695,96 | 2.034,12 | 119,9 % | 60,6 % | -338,16 | 3/6 | 1.583,44 | 2.708,66 | -1.125,22 |
| `sl_depth_6` | 15 | 1.454,40 | 1.266,08 | 87,1 % | 57,1 % | 188,32 | 4/6 | 1.285,10 | 1.285,10 | 0,00 |
| `sl_buffer_12` | 37 | 84,90 | 1.610,84 | 1.897,3 % | 71,7 % | -1.525,94 | 3/6 | 2.005,08 | 3.149,88 | -1.144,80 |
| `recovery_off` | 41 | 468,62 | 2.264,88 | 483,3 % | 81,8 % | -1.796,26 | 3/6 | 2.105,64 | 3.364,92 | -1.259,28 |
| `rr_2_5` | 38 | 742,94 | 1.802,62 | 242,6 % | 59,9 % | -1.059,68 | 3/6 | 1.967,82 | 3.052,62 | -1.084,80 |

**Lectura de la tabla:**

- W4 es el bloque más rentable en 9/11. Las excepciones son `entry_breakout_direct` y `entry_or_level`, donde manda W3.
- W4 aporta más de la mitad del P&L positivo en 9/11. En `sl_buffer_12` y `recovery_off` el W4 es casi todo el resultado.
- `exW4` solo es positivo en 3/11: `entry_breakout_direct` (+248,32), `entry_or_level` (+482,34) y `sl_depth_6` (+188,32).
- `entry_retrace_382` tiene neto negativo: W4 (+1.485,36) está compensando pérdidas de otros bloques; no es un caso de concentración de beneficio sino de W4 enmascarando un sistema perdedor.
- En los 8 presets con `Δ DD W4` negativo, quitar W4 **aumenta** el DD. W4 no es la causa del drawdown; es el capital que lo amortigua.

## 4. Concentración por operación

| Preset | Top $ | Bloque/fecha | Top % neto | Neto sin top $ | DD $ | Δ DD top $ | Peor op DD $ | Bloque/fecha | DD tras $ | Reducción $ | % DD |
|---|---:|---|---:|---:|---:|---:|---:|---|---:|---:|---:|
| `baseline` | 768,80 | W4 2025-12-24 | 116,2 % | -107,36 | 1.967,82 | 0,00 | -248,96 | W6 2026-05-19 | 1.718,86 | 248,96 | 12,7 % |
| `entry_breakout_direct` | 553,52 | W3 2025-09-23 | 141,6 % | -162,68 | 305,20 | 0,00 | -192,72 | W3 2025-07-25 | 112,48 | 192,72 | 63,1 % |
| `entry_or_level` | 527,52 | W3 2025-09-23 | 109,4 % | -45,18 | 207,96 | 0,00 | -104,48 | W3 2025-09-16 | 103,48 | 104,48 | 50,2 % |
| `entry_retrace_382` | 613,80 | W1 2025-01-29 | — | -642,56 | 2.053,10 | 0,00 | -266,20 | W1 2025-03-27 | 1.786,90 | 266,20 | 13,0 % |
| `smt_window_120` | 768,80 | W4 2025-12-24 | 76,4 % | 237,18 | 2.224,32 | 0,00 | -318,72 | W6 2026-04-06 | 1.905,60 | 318,72 | 14,3 % |
| `smt_tolerance_16` | 768,80 | W4 2025-12-24 | 61,7 % | 476,60 | 2.185,12 | 0,00 | -248,96 | W6 2026-05-19 | 1.936,16 | 248,96 | 11,4 % |
| `setup_validity_240` | 768,80 | W4 2025-12-24 | 45,3 % | 927,16 | 1.583,44 | 0,00 | -119,22 | W3 2025-07-24 | 1.501,52 | 81,92 | 5,2 % |
| `sl_depth_6` | 647,28 | W2 2025-06-25 | 44,5 % | 807,12 | 1.285,10 | 0,00 | -348,72 | W3 2025-08-11 | 936,38 | 348,72 | 27,1 % |
| `sl_buffer_12` | 683,28 | W2 2025-06-25 | 804,8 % | -598,38 | 2.005,08 | 0,00 | -251,22 | W5 2026-03-19 | 1.753,86 | 251,22 | 12,5 % |
| `recovery_off` | 783,80 | W4 2025-12-24 | 167,3 % | -315,18 | 2.105,64 | 0,00 | -368,70 | W5 2026-01-21 | 1.736,94 | 368,70 | 17,5 % |
| `rr_2_5` | 638,80 | W4 2025-12-24 | 86,0 % | 104,14 | 1.967,82 | 0,00 | -248,96 | W6 2026-05-19 | 1.718,86 | 248,96 | 12,7 % |

**Lectura de la tabla:**

- La mejor operación supera el 100 % del neto en `baseline`, `entry_breakout_direct`, `entry_or_level`, `sl_buffer_12` y `recovery_off`. En `baseline`, quitarla deja el neto en **-107,36**; en `sl_buffer_12`, en **-598,38**.
- `sl_depth_6` es el caso menos dependiente de una sola operación: su top trade es el 44,5 % del neto y, sin él, todavía quedan **+807,12**. Aun así, W4 explica el 87,1 % del neto.
- El **top trade no cambia el DD en ninguno de los 11**. El DD máximo es una diferencia entre un pico y un valle; quitar un ganador fuera de esa ventana no lo toca, y si está dentro desplaza ambos niveles de forma similar.
- La peor operación para el DD no es la mayor pérdida en todos los casos; es la que más reduce el drawdown al eliminarla. En los presets con ≥15 operaciones, esa eliminación solo recorta el DD un **5,2–27,1 %**. El DD es una secuencia de pérdidas, no una sola operación.
- En los presets de 4 operaciones, una sola pérdida sí explica 50–63 % del DD, pero la muestra es demasiado pequeña para concluir estabilidad.

## 5. Los top trades se repiten en cuatro fechas

| Fecha | Bloque | Presets cuyo top trade cae ahí | P&L del top |
|---|---|---|---|
| 2025-12-24 | W4 | `baseline`, `smt_window_120`, `smt_tolerance_16`, `setup_validity_240`, `rr_2_5`, `recovery_off` | 638,80–783,80 |
| 2025-06-25 | W2 | `sl_depth_6`, `sl_buffer_12` | 647,28–683,28 |
| 2025-09-23 | W3 | `entry_breakout_direct`, `entry_or_level` | 527,52–553,52 |
| 2025-01-29 | W1 | `entry_retrace_382` | 613,80 |

Los 11 top trades caen en **4 fechas**. No hay `signal_id` en la curva continua, así que no se afirma que sean el mismo fill; sí son el mismo **episodio de mercado**. Esto implica que la aparente consistencia entre presets no es independiente: varias variantes están ganando con la misma Operación de W4 del 2025-12-24. La muestra efectiva de “mejores operaciones” es de 4 episodios, no de 11.

## 6. Qué significa para W4 y para una sola operación

- **P&L:** W4 es el principal riesgo de concentración. En 8/11 presets el resultado desaparece sin W4; en 7/11 W4 supera el 100 % del neto porque los demás bloques pierden. La mejor operación también es crítica en varios presets, y seis de esos top trades son el mismo episodio de W4.
- **DD:** W4 no es la fuente del drawdown. Quitar W4 empeora el DD en 8/11 (entre 616,86 y 1.394,52 USD) y no lo cambia en los otros 3. La mejor operación no altera el DD en ningún caso. La peor operación individual solo explica una fracción minoritaria del DD en muestras de ≥15 operaciones.
- **Conclusión operativa:** no se puede usar “W4 es el mejor bloque” como prueba de robustez; tampoco se puede decir que el DD esté causado por W4 o por una sola operación. Son dos problemas distintos: concentración de beneficio en W4 y una secuencia de pérdidas posterior (W5–W6 en 6/11, W3/W1 en el resto) que W4 amortigua.
- **Para la siguiente fase:** hay que ampliar la muestra fuera del holdout y analizar por episodios/fechas, no solo por preset. `sl_depth_6` sigue siendo el único candidato de estabilidad, pero su P&L depende de W4 en un 87,1 %; su DD está en W3 y no depende de W4. Eso no lo convierte en promocionable: sigue con 15 operaciones.

## 7. Límites

- La curva continua solo incluye los 11 defaults. Los opt-in `sl_cap_600`, `direct_sl_cap_600`, `deep_stop_sl_cap_600` y `entry_or_level_sl_cap_600` no tienen curva continua propia; su auditoría por operación queda pendiente y no se mezcla aquí con datos de bloque con capital reiniciado.
- El DD contrafactual no es aditivo. “DD sin W4” o “DD sin top” son curvas reconstruidas, no contribuciones que sumen el DD total.
- Los porcentajes de W4 sobre el neto pueden superar 100 % cuando los demás bloques pierden; miden dependencia, no un peso de cartera.
- No hay `signal_id` en `trade_equity`; las fechas identifican episodios, no fills idénticos entre presets.
- No se ejecutó ningún backtest nuevo ni el holdout. `holdout_executed=false` en la fuente y no hay artefactos de holdout.
- No se modificaron protocolo, lock, configuración activa ni código.

## 8. Artefactos

- `reports/backtest/equity_continuous_dev.json` — curva continua de origen.
- `reports/backtest/equity_continuous_dev.csv` — curva diaria.
- `reports/backtest/concentration_continuous_audit.json` — métricas calculadas de esta auditoría.
- `reports/backtest/AUDITORIA_CONCENTRACION_CONTINUA.md` — este documento.
