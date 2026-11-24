# Continuación tendencial sin retesteo — revisión W1–W6

> **Estado (2026-11-21): opción retirada.** La condición, su preset, sus controles
> de UI y sus tests se eliminaron del código. Este informe se conserva como
> evidencia histórica de la comparación que motivó la retirada.

**Fecha:** 2026-11-21  
**Datos:** desarrollo W1–W6, 2025-01-10 → 2026-06-30, 362 sesiones evaluadas.  
**Holdout:** no ejecutado.  
**Configuración:** `profiles/backtest_real/config.json` (raw, sin cambios en la configuración activa).  
**Preset comparado:** `continuation_no_retest` (retirado; baseline incluido automáticamente).

## 1. Qué se implementó

La opción `strategy.allow_trend_continuation` estaba apagada por defecto y ya no
existe en el código. Cuando se activaba, solo podía entrar si se cumplían **todas**
estas condiciones:

1. la ruptura sigue vigente y el setup expiró sin retesteo (no hubo toque de la referencia);
2. la SMT sigue vigente, confirmada, recuperada y alineada con la dirección de la ruptura;
3. las tres últimas velas de confirmación ya cerradas tienen cierres y extremos
   consecutivos a favor, y el último cierre está más allá del nivel roto;
4. el stop se ancla al extremo de la última vela de confirmación o al swing confirmado
   más cercano, con buffer, y nunca supera `continuation_max_sl_ticks` (80 por defecto).

El preset usaba `continuation_max_sl_ticks=80`. La configuración activa y los
presets por defecto nunca activaron la opción, por lo que el baseline no cambia.

## 2. Resultado por bloque

| Bloque | Baseline ops / PF / neto | Continuación ops / PF / neto | DD peor baseline → continuación | SL baseline → continuación |
|---|---:|---:|---:|---:|
| W1 | 8 / 1,35 / +364,82 | 25 / 1,04 / +161,92 | 619,42 → 1.210,32 | 50,0% → 68,0% |
| W2 | 4 / 1,71 / +268,40 | 20 / 1,33 / +779,20 | 378,88 → 914,88 | 50,0% → 60,0% |
| W3 | 9 / 0,92 / −110,46 | 29 / 0,38 / −2.809,46 | 1.084,80 → 3.290,20 | 77,8% → 86,2% |
| W4 | 4 / sin pérdidas / +2.034,12 | 24 / 2,23 / +2.927,62 | 0,00 → 1.315,80 | 0,0% → 50,0% |
| W5 | 5 / 0,00 / −1.036,52 | 19 / 0,18 / −2.671,08 | 1.036,52 → 3.063,68 | 100,0% → 89,5% |
| W6 | 8 / 0,27 / −858,92 | 30 / 0,94 / −242,82 | 931,30 → 1.898,06 | 75,0% → 70,0% |

W4 mejora en neto (+893,50), pero no sale gratis: pasa de 4 a 24 operaciones,
de 0 a 12 Stop Loss y de 0 a 1.315,80 de drawdown. No es una mejora de estabilidad;
es un aumento grande de actividad con más riesgo realizado.

## 3. Agregado y resultado ex-W4

| Métrica | Baseline | Continuación | Cambio |
|---|---:|---:|---:|
| Operaciones | 38 | 147 | +109 |
| Profit factor | 1,13 | 0,91 | −0,22 |
| Neto | +661,44 | −1.854,62 | −2.516,06 |
| Peor drawdown | 1.084,80 | 3.290,20 | +2.205,40 |
| Stop Loss | 24 (63,2%) | 104 (70,8%) | +80 stops |
| Ticks medios de stop | 124,2 | 86,5 | −37,7 |
| Sesiones con `stop_cap` | 50 | 50 | 0 |

**Ex-W4** (W1+W2+W3+W5+W6):

| Métrica | Baseline | Continuación |
|---|---:|---:|
| Operaciones | 34 | 123 |
| Neto | −1.372,68 | −4.782,24 |
| Profit factor | 0,72 | 0,74 |
| Stop Loss | 24 / 34 (70,6%) | 92 / 123 (74,8%) |
| Peor drawdown | 1.084,80 | 3.290,20 |

El PF ex-W4 sube marginalmente (0,72 → 0,74), pero el neto empeora en 3.409,56,
el drawdown se triplica y la tasa de Stop Loss sube. No compensa.

## 4. Caso 2025-12-17

En una ventana de cinco sesiones alrededor de la fecha, el baseline no opera y la
continuación “rescata” dos entradas, ambas perdedoras:

| Fecha | Hora | Dirección | Entrada | Stop | Salida | P&L | R |
|---|---:|---|---:|---:|---|---:|---:|
| 2025-12-15 | 14:45 | short | 25.365,75 | 25.387,00 | stop_loss | −221,20 | −1,01 |
| **2025-12-17** | **13:45** | **short** | **24.964,50** | **24.985,50** | **stop_loss** | **−218,70** | **−1,01** |

No es un caso aislado: la condición añade 109 operaciones netas en W1–W6 y 80
Stop Loss adicionales. La lectura correcta es que “ruptura + SMT + tres velas de
15m a favor al expirar” no identifica una continuación de calidad; muchas entradas
llegan tarde, después de que el impulso ya se agotó.

## 5. Decisión

- **Retirar** `allow_trend_continuation`, `continuation_max_sl_ticks`, el preset
  `continuation_no_retest`, sus controles de UI y sus tests. La opción no se
  mantiene oculta ni desactivada.
- Los resultados de este informe quedan como evidencia histórica. No se reintroduce
  la condición sin un pre-registro nuevo y una comparación independiente.
- El holdout permanece sellado.

## 6. Verificación de esta comparación (histórica)

- `pytest`: **266 passed, 1 warning** (`StarletteDeprecationWarning`).
- `frontend`: `tsc --noEmit && vite build` correcto.
- Comparación W1–W6: `reports/backtest/continuation_w1_w6.json` y
  `reports/backtest/continuation_w1_w6.log`.
