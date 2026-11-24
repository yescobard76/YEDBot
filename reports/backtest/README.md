# Backtests de desarrollo

Esta carpeta contiene los reportes y scripts de desarrollo. El holdout no se
usa. Las conclusiones manual-vs-original y P2 están congeladas en los scripts y
JSON que se indican abajo.

## Ventanas canónicas: una sola definición

La única definición de W1-W6 está en `_windows.py`:

| Ventana | Inicio solicitado | Primera sesión real | Fin | Sesiones |
|---|---|---|---:|---:|
| W1 | 2025-01-10 | 2025-01-10 | 2025-03-31 | 54 |
| W2 | 2025-04-01 | 2025-04-01 | 2025-06-30 | 61 |
| W3 | 2025-07-01 | 2025-07-01 | 2025-09-30 | 63 |
| W4 | 2025-10-01 | 2025-10-01 | 2025-12-31 | 63 |
| W5 | 2026-01-01 | **2026-01-02** | 2026-03-31 | 60 |
| W6 | 2026-04-01 | 2026-04-01 | 2026-06-30 | 61 |

`WINDOW_FIRST` fija la primera sesión real; W5 abre el 2026-01-02 porque el
2026-01-01 no tiene sesión. Los runners validan sesiones, primera y última
sesión. `run_presets_dev.py`, `run_continuous_equity_dev.py`,
`audit_w2_w3_current.py` y `_manual_common.py` importan `_windows.py`; no
redeclaran las ventanas.

## Dónde vive cada conclusión

| Conclusión | Fuente |
|---|---|
| original: 38 ops, +661,44, PF 1,13, DD 1.967,82 | `_manual_w1_w6_analysis.py`; también `p2_w1_w6_confirm.json` (`aggregate.original`) |
| manual: 72 ops, +2.022,94, PF 1,22, DD 2.891,66 | `_manual_w1_w6_analysis.py` |
| P2: 46 ops, +2.471,78, PF 1,39, DD 2.304,46 | `_manual_w1_w6_analysis.py` y `p2_w1_w6_confirm.json` |
| P1: 46 ops, +1.992,26, PF 1,37, DD 1.947,82 | `_manual_w1_w6_analysis.py` |
| manual con frecuencia original: 60 ops, −608,06, PF 0,93, DD 2.870,66 | `_manual_w1_w6_analysis.py` |
| filtro 0,25: 17 ops, +4.202,20, PF 4,25, DD 946,38 | `_manual_filter025_w1_w6.py` y `_manual_filter025_w1_w6.json` |
| atribución con residual 0,00 | salida de `_manual_w1_w6_analysis.py` |
| rentabilidad comparada y propuestas priorizadas | `FILTER025_PROFITABILITY.md` |

`_p2_w1_w6_confirm.py` es la confirmación independiente de original/P2 y
escribe `p2_w1_w6_confirm.json`. `_manual_filter025_w1_w6.py` escribe
`_manual_filter025_w1_w6.json` e incluye `invariant_max10_eq_max5`.

## Gates históricos del filtro 0,25

La evaluación de las puertas históricas del filtro está en
`filter025_gates.py` y `filter025_gates.config.json`. Consume exclusivamente
los dos artefactos anteriores; no ejecuta backtests, no lee el holdout y no
toca la estrategia ni el filtro. La salida es `filter025_gates.json`.

Las reglas recalibradas separan cobertura de consistencia: los trimestres
vacíos no pasan, el bootstrap exige muestra y cobertura mínimas, y el umbral
de bloque se calcula con el tamaño real de la muestra. El resultado actual es
`INCONCLUSO`; los detalles están en `FILTER025_GATES.md`.

```bash
python reports/backtest/filter025_gates.py
python -m pytest tests/test_filter025_gates.py -q
```

## Rentabilidad comparada del filtro 0,25

`FILTER025_PROFITABILITY.md` compara el perfil original de 38 operaciones, el
manual vivo 8765 de 72 operaciones, P2 de 46 y el filtro de 17. Separa el
efecto de perfil/frecuencia del efecto de selección, documenta la exposición y
la concentración trimestral, el coste estimado y la confianza. El filtro es más
rentable en la muestra histórica, pero el veredicto sigue siendo `INCONCLUSO`:
no se promociona. El informe también incluye las mejoras priorizadas por
rentabilidad esperada y el gate que debería validar cada una; no se implementa
ninguna.

## Perfil original

El original canónico del protocolo es `max_contracts=5`, `max_sl_ticks=200`,
`setup_validity_minutes=150` y `retest_tolerance_ticks=12`.
`profiles/backtest_real/config.json` contiene actualmente 210/24 (hallazgo
previo, no se modifica). Los scripts fijan la frecuencia 150/12 en memoria con
`ORIGINAL_FREQUENCY_PATCH` de `_manual_common.py`; el archivo no se toca.

## Comprobación de equivalencia

`_verify_window_equivalence.py` contiene aserciones ejecutables contra
`blocks_summary.json` y los JSON de reportes generados, que actúan como
oráculo histórico. No compara `_windows.py` consigo mismo y no es una segunda
definición runtime: importa la estructura efectiva de cada consumidor y la
compara con el oráculo.

Cobertura explícita de los 13 archivos del alcance:

- `_windows.py`: tuplas, ids, inicio solicitado, fin, sesiones, primera/última
  sesión real, orden y longitud.
- `_manual_common.py`: ventanas, primera/última y `WINDOW_FIRST`.
- `run_presets_dev.py`: tuplas completas, `WINDOW_FIRST` y `DEVELOPMENT_END`.
- `run_continuous_equity_dev.py`: `BLOCK_RANGES`, `START`, `END`, `DAYS`.
- `audit_w2_w3_current.py`: `TASKS` W2/W3, orden y longitud.
- `run_breakeven_1r_protocol.py`: ids y `GROUPS`; fechas efectivas del lock.
- `run_entry_exclusion_compare.py`: ids, `GROUPS` y tuplas completas.
- `run_min_stop_or_ratio_protocol.py`: ids, `GROUPS`, tuplas y `DEVELOPMENT_END`.
- `run_stop_or_ratio_ablations.py`: ids, `GROUPS` y tuplas completas.
- `compare_raw_adjusted_w4_w6.py`: subconjunto W4–W6, orden y longitud; lock.
- `_p2_w1_w6_confirm.py`: `EFFECTIVE_WINDOWS` y `run_windows` común.
- `_manual_w1_w6_analysis.py`: `EFFECTIVE_WINDOWS` y `run_windows` común.
- `_manual_filter025_w1_w6.py`: `EFFECTIVE_WINDOWS` y `run_windows` común.

Los consumidores de solo ids usan las fechas del
`docs/protocolo_backtest.lock.json`; el verificador comprueba ese lock completo
contra el oráculo por cada consumidor, además de ids y agrupaciones.

```bash
python reports/backtest/_verify_window_equivalence.py
```

Se ejecuta completo el verificador. Los tres runners de conclusiones
(`_p2_w1_w6_confirm.py`, `_manual_w1_w6_analysis.py` y
`_manual_filter025_w1_w6.py`) tienen corridas completas registradas con exit 0
y se verifican sus JSON/logs; no se relanzan aquí para no reescribir
artefactos. Los runners largos (`run_presets_dev.py`,
`run_continuous_equity_dev.py`) solo se importan para leer sus definiciones,
sin ejecutar sus experimentos.

## Reproducir

```bash
python reports/backtest/_p2_w1_w6_confirm.py
python reports/backtest/_manual_w1_w6_analysis.py
python reports/backtest/_manual_filter025_w1_w6.py
```

La agregación usa trades concatenados desde 25.000 USD; el DD es el de esa
curva de trades, no una curva continua con sizing arrastrado.
