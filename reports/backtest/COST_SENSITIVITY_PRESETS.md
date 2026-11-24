# Sensibilidad de presets a costes peores

Escenarios deterministas sobre los mismos bloques W1–W6 y el mismo dataset de desarrollo. No se usa el holdout ni se cambia la configuración activa. El baseline de cada escenario se reejecuta para comparar mejoras relativas en igualdad de costes.

## Escenarios

| Escenario | Slippage | Comisión/lado |
|---|---:|---:|
| `slippage_plus_1` | 2 ticks | 0.62 USD |
| `commission_double` | 1 ticks | 1.24 USD |
| `combined` | 2 ticks | 1.24 USD |

Base: `presets_default_dev.json`, dataset `f2e9a2c5dff56b79195dcc19cc79b2dd9b2245ebfde6e7956471967a31f3f2b3`, 675.9 s. Los escenarios se reejecutaron porque el artefacto base solo guarda agregados, no contratos/comisiones por operación.

## Resultado por preset

`Mejora base` y `Mejora escenario` son el neto del preset menos el neto del baseline en la misma corrida. `Δ` es el cambio de esa mejora; negativo significa que el shock se llevó parte de la ventaja.

| Preset | Neto base | Mejora base | Neto slippage | Mejora slippage | Neto comisión | Mejora comisión | Neto combinado | Mejora combinado |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline` | 661.44 | 0.00 | 525.94 | 0.00 | 482.88 | 0.00 | 347.38 | 0.00 |
| `entry_breakout_direct` | 390.84 | -270.60 | 385.34 | -140.60 | 379.68 | -103.20 | 374.18 | 26.80 |
| `entry_or_level` | 482.34 | -179.10 | 476.84 | -49.10 | 471.18 | -11.70 | 465.68 | 118.30 |
| `entry_retrace_382` | -28.76 | -690.20 | -118.26 | -644.20 | -151.52 | -634.40 | -241.02 | -588.40 |
| `smt_window_120` | 1.005.98 | 344.54 | 866.48 | 340.54 | 822.46 | 339.58 | 682.96 | 335.58 |
| `smt_tolerance_16` | 1.091.64 | 430.20 | 908.64 | 382.70 | 857.28 | 374.40 | 674.28 | 326.90 |
| `setup_validity_240` | 1.695.96 | 1.034.52 | 1.510.46 | 984.52 | 1.452.92 | 970.04 | 1.267.42 | 920.04 |
| `sl_depth_6` | 1.539.64 | 878.20 | 1.503.64 | 977.70 | 1.491.28 | 1.008.40 | 1.455.28 | 1.107.90 |
| `sl_buffer_12` | 139.86 | -521.58 | 14.86 | -511.08 | -28.78 | -511.66 | -153.78 | -501.16 |
| `recovery_off` | 428.10 | -233.34 | 326.34 | -199.60 | 283.68 | -199.20 | 129.18 | -218.20 |
| `rr_2_5` | 742.94 | 81.50 | 603.44 | 77.50 | 564.38 | 81.50 | 424.88 | 77.50 |

## Mejoras que desaparecen

Se marca una mejora como desaparecida cuando el preset supera al baseline con costes base pero deja de superarlo en el escenario.

**Ninguna mejora agregada desaparece.** Los cinco presets que superaban al baseline con costes base (`smt_window_120`, `smt_tolerance_16`, `setup_validity_240`, `sl_depth_6` y `rr_2_5`) siguen superándolo en los tres escenarios. La ventaja se comprime, sobre todo en `smt_tolerance_16`, pero no cambia de signo.

## Mejoras que aparecen con el shock

Presets que no superaban al baseline con costes base pero sí lo superan en algún escenario. **No son una mejora de la estrategia**: son artefactos de exposición; el shock penaliza mucho más al baseline de 38 operaciones que a un preset de 4.

| Escenario | Preset | Mejora base | Mejora escenario | Neto base | Neto escenario |
|---|---|---:|---:|---:|---:|
| `combined` | `entry_breakout_direct` | -270.60 | 26.80 | 390.84 | 374.18 |
| `combined` | `entry_or_level` | -179.10 | 118.30 | 482.34 | 465.68 |

## Mejoras que resisten

Presets con mejora positiva en los tres escenarios, ordenados por la mejora del escenario combinado.

| Preset | Mejora slippage | Mejora comisión | Mejora combinada |
|---|---:|---:|---:|
| `sl_depth_6` | 977.70 | 1.008.40 | 1.107.90 |
| `setup_validity_240` | 984.52 | 970.04 | 920.04 |
| `smt_window_120` | 340.54 | 339.58 | 335.58 |
| `smt_tolerance_16` | 382.70 | 374.40 | 326.90 |
| `rr_2_5` | 77.50 | 81.50 | 77.50 |

## Efecto en drawdown y profit factor

El coste no solo reduce el neto: también aumenta el drawdown y baja el profit factor. Se muestra el peor drawdown de bloque y el PF agregado bajo costes combinados.

| Preset | DD base | DD slippage | DD comisión | DD combinado | PF base | PF combinado |
|---|---:|---:|---:|---:|---:|---:|
| `baseline` | 1.084.80 | 1.104.80 | 1.109.60 | 1.129.60 | 1.13 | 1.07 |
| `entry_breakout_direct` | 305.20 | 307.70 | 311.40 | 313.90 | 2.28 | 2.19 |
| `entry_or_level` | 207.96 | 209.96 | 212.92 | 214.92 | 3.32 | 3.17 |
| `entry_retrace_382` | 1.007.58 | 1.024.58 | 1.028.66 | 1.045.66 | 0.99 | 0.95 |
| `smt_window_120` | 1.187.80 | 1.207.80 | 1.212.60 | 1.232.60 | 1.19 | 1.12 |
| `smt_tolerance_16` | 1.423.92 | 1.456.92 | 1.464.84 | 1.497.84 | 1.18 | 1.10 |
| `setup_validity_240` | 1.583.44 | 1.612.44 | 1.621.88 | 1.650.88 | 1.28 | 1.20 |
| `sl_depth_6` | 1.199.86 | 1.213.86 | 1.217.22 | 1.231.22 | 2.02 | 1.94 |
| `sl_buffer_12` | 1.101.06 | 1.120.06 | 1.124.62 | 1.143.62 | 1.03 | 0.97 |
| `recovery_off` | 1.181.00 | 1.164.04 | 1.169.08 | 1.190.08 | 1.08 | 1.02 |
| `rr_2_5` | 1.084.80 | 1.104.80 | 1.109.60 | 1.129.60 | 1.15 | 1.08 |

## Coste absoluto del shock

Diferencia de neto contra la corrida base del mismo preset; un valor negativo es el coste. El combinado coincide al céntimo con la suma de los dos shocks en esta muestra, pero no se fuerza esa aditividad: el motor puede cambiar sizing y fills.

| Preset | Δ slippage | Δ comisión | Δ combinado |
|---|---:|---:|---:|
| `baseline` | -135.50 | -178.56 | -314.06 |
| `entry_breakout_direct` | -5.50 | -11.16 | -16.66 |
| `entry_or_level` | -5.50 | -11.16 | -16.66 |
| `entry_retrace_382` | -89.50 | -122.76 | -212.26 |
| `smt_window_120` | -139.50 | -183.52 | -323.02 |
| `smt_tolerance_16` | -183.00 | -234.36 | -417.36 |
| `setup_validity_240` | -185.50 | -243.04 | -428.54 |
| `sl_depth_6` | -36.00 | -48.36 | -84.36 |
| `sl_buffer_12` | -125.00 | -168.64 | -293.64 |
| `recovery_off` | -101.76 | -144.42 | -298.92 |
| `rr_2_5` | -139.50 | -178.56 | -318.06 |

## Validación

El baseline combinado da **347,38 USD**, exactamente el mismo neto que `stress_costs.json` (38 operaciones, comisión 1,24 y slippage 2). Los 18 bloques declaran el mismo `dataset_id` y `holdout_executed=false`.

## Límites

- Los escenarios son shocks fijos, no intervalos de confianza; no cuantifican probabilidad de que el coste real sea ese.
- El baseline de cada escenario se reejecuta, pero la comparación sigue siendo sobre 362 sesiones de desarrollo y seis bloques.
- Los presets con 4 operaciones siguen siendo muestras pequeñas; un neto positivo después del shock no es evidencia suficiente.
- No se abre el holdout. Cualquier promoción sigue requiriendo el protocolo confirmatorio.

