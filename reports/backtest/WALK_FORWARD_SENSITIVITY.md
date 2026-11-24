# Sensibilidad del walk-forward a la regla de selección

Variantes deterministas sobre los P&L de W1–W6 ya ejecutados. No se abrió el holdout, no se ejecutaron backtests nuevos y no se modificó la configuración activa.

## Variantes

| Variante | Entrenamiento | Mínimo ops | Selecciones |
|---|---|---:|---|
| `expanding_min5` | expansivo W1..Wt | 5 | W2:setup_validity_240 → W3:rr_2_5 → W4:smt_window_120 → W5:smt_window_120 → W6:smt_window_120 |
| `expanding_min3` | expansivo W1..Wt | 3 | W2:setup_validity_240 → W3:sl_depth_6 → W4:entry_or_level → W5:smt_window_120 → W6:entry_or_level |
| `rolling2_min5` | rodante últimos 2 bloques | 5 | W2:setup_validity_240 → W3:rr_2_5 → W4:smt_tolerance_16 → W5:smt_window_120 → W6:entry_retrace_382 |

## Resultado

`Δ vs baseline` es la diferencia de neto de los 5 tests. `Retorno compuesto` usa los P&L de bloque con capital inicial 25.000 USD; no es una curva intradía.

| Variante | Tests+ | Ops | Neto $ | PF | Peor DD $ | Δ vs baseline $ | Compuesto % |
|---|---:|---:|---:|---:|---:|---:|---:|
| `expanding_min5` | 2/5 | 33 | -7.00 | 0.998 | 1.187.80 | -303.62 | -0.554 |
| `expanding_min3` | 1/5 | 19 | -1.283.58 | 0.528 | 1.199.86 | -1.580.20 | -5.138 |
| `rolling2_min5` | 2/5 | 31 | 106.60 | 1.027 | 1.084.80 | -190.02 | 0.066 |

## Lectura

- Baseline: **296.62 USD**. La regla original (`expanding_min5`) obtiene **-7.00 USD**, **-303.62 USD** frente a baseline, y **-0.554 %** compuesto.
- **Ninguna variante supera a baseline.** La mejor es `rolling2_min5`, con **106.60 USD**, todavía **-190.02 USD** por debajo de baseline.
- Bajar el mínimo a 3 operaciones empeora el resultado: **-1.283.58 USD** y **-1.580.20 USD** frente a baseline.
- Las variantes de sensibilidad no se eligen por su resultado: la regla original sigue siendo la pre-registrada. Ninguna mejora en esta muestra sería evidencia suficiente: 5 folds, un bloque de test por fold y sin intervalos de confianza.

## Límites

- No se remuestrean sesiones; se reutilizan los P&L de bloque. No sustituye al bootstrap ni al scorecard.
- El mínimo de operaciones bajo puede seleccionar presets de pocas operaciones; un resultado positivo no es evidencia de edge.
- El holdout sigue sellado; no hay promoción ni se abre el protocolo confirmatorio.
