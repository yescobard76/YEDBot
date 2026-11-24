# Filtro de entrada para las pérdidas que salen en la hora 11:00

**Fuente:** replay paper de 56 operaciones, 44 tras el filtro `stop/ORB >= 0,25`.  
**Pérdidas objetivo:** 8 operaciones con salida entre 11:00 y 11:59 ET, todas con MFE < 1R.  
**Naturaleza:** medición sobre entradas fijas; no re-simula señales ni toca el holdout.

## Las 8 pérdidas

| Señal | Entrada | Salida | Dir | P&L | MFE R | ret3/ORB | ret20/ORB | VWAP/ORB |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| `2025-02-19-short-1739977200` | 10:33 | 11:11 | short | -220,48 | 0,40 | -0,097 | -0,472 | 0,004 |
| `2025-07-23-short-1753279200` | 11:02 | 11:54 | short | -232,48 | 0,53 | -0,028 | -0,204 | -0,172 |
| `2025-09-04-short-1756994400` | 11:13 | 11:22 | short | -176,48 | 0,32 | 0,327 | 0,203 | -0,238 |
| `2025-09-29-long-1759155300` | 11:12 | 11:36 | long | -239,48 | 0,00 | -0,220 | -0,516 | -0,195 |
| `2025-10-15-long-1760536800` | 11:43 | 11:50 | long | -268,48 | 0,05 | -0,233 | -0,921 | -0,502 |
| `2025-11-20-long-1763652600` | 10:52 | 11:00 | long | -150,24 | 0,10 | -0,125 | -0,380 | -0,072 |
| `2026-04-09-short-1775744100` | 11:02 | 11:32 | short | -153,74 | 0,30 | 0,045 | -0,462 | -0,088 |
| `2026-04-21-long-1776780000` | 10:49 | 11:00 | long | -288,48 | 0,16 | -0,091 | -0,410 | -0,111 |

Las 8 son `stop_loss`, con MFE entre 0,00R y 0,53R. No llegan a +1R: BE, lock o trailing no pueden mejorarlas.

## Reglas y resultado

| Regla | Ops quitadas | H11 evitadas | Ganadoras quitadas | Otras pérdidas | Neto delta | DD después | PF después | Racha |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `core` | 8 | 4/8 | 0 | 4 | 1.841,08 | 1.294,12 | 3,35 | 6 |
| `extended` | 13 | 7/8 | 0 | 6 | 2.787,50 | 1.061,64 | 5,13 | 5 |
| `wide` | 19 | 8/8 | 4 | 7 | 1.678,38 | 885,16 | 5,63 | 4 |
| `time_only` | 5 | 3/8 | 0 | 2 | 946,42 | 1.895,80 | 2,52 | 9 |

## Comparación contra el BE 1R

| Regla | Neto base | Neto BE | DD base | DD BE | Ganadoras base | Ganadoras BE |
|---|---:|---:|---:|---:|---:|---:|
| original | 4.543,62 | 3.670,12 | 2.128,28 | 1.501,44 | 22 | 16 |
| `core` | 6.384,70 | 5.100,20 | 1.294,12 | 852,28 | 22 | 16 |
| `extended` | 7.331,12 | 5.643,62 | 1.061,64 | 619,80 | 22 | 16 |

## Detalle

### Core (recomendado como base robusta)

- Evita **4/8** pérdidas H11 y **4** pérdidas adicionales; **0 ganadoras**.
- Neto: **+1.841,08**; DD: 2.128,28 → **1.294,12**; PF: 2,00 → **3,35**.
- No atrapa las 4 H11 restantes: 07-23, 09-04, 11-20 y 04-09.

### Extended (más agresivo, 10:50–11:05 + VWAP)

- Evita **7/8** pérdidas H11 y **6** adicionales; **0 ganadoras**.
- Neto: **+2.787,50**; DD: 2.128,28 → **1.061,64**; PF: 2,00 → **5,13**.
- Solo queda `2025-09-04-short-1756994400` (−176,48), que entra con momento positivo y no lo atrapa ninguna regla estudiada.
- La rama 10:50–11:05 es una ventana de 15 minutos elegida in-sample; es la parte frágil.

### Wide (atrapar las 8)

- Evita **8/8** H11, pero quita **4 ganadoras** por **1.539,82** USD.
- Neto: +1.678,38; DD 885,16. No cumple “sin quitar ganadores”.

## Split temporal

| Regla | 2025 quitadas | H11 2025 | Ganadoras 2025 | 2026 quitadas | H11 2026 | Ganadoras 2026 |
|---|---:|---:|---:|---:|---:|---:|
| `core` | 7 | 3 | 0 | 1 | 1 | 0 |
| `extended` | 11 | 5 | 0 | 2 | 2 | 0 |
| `wide` | 16 | 6 | 3 | 3 | 2 | 1 |

El filtro conserva 0 ganadoras quitadas en ambos períodos para `core` y `extended`; no es una validación fuera de muestra porque los umbrales se eligieron mirando la muestra completa.

## Cross-check en el protocolo oficial de 14 operaciones

| Regla | Ops quitadas | Ganadoras quitadas | Pérdidas quitadas | Neto ahorrado |
|---|---:|---:|---:|---:|
| `core` | 2 | 0 | 2 | 371,96 |
| `extended` | 2 | 0 | 2 | 371,96 |
| `wide` | 5 | 2 | 3 | -138,62 |

En el protocolo oficial de 14 operaciones, `core` y `extended` solo quitan dos pérdidas (2025-09-03 y 2025-09-19) y **ninguna ganadora**.

## Conclusión

- **Sí existe un filtro que evita la mayoría de las 8 pérdidas sin quitar ganadoras en esta muestra.** `extended` evita 7/8 y 0 ganadoras; `core` evita 4/8 y 0 ganadoras.
- **No hay una regla simple que evite las 8 sin quitar ganadoras.** Para atrapar también 09-04 hay que ampliar la ventana y se pierden 4 ganadoras.
- La parte robusta es el momento adverso (`ret3`/`ret20`); la ventana 10:50–11:05/VWAP es la parte más frágil y necesita validación fuera de muestra.
- No se modificó el motor ni la configuración activa. El holdout sigue sin usarse.

JSON: `reports\backtest\hour11_entry_filter.json`
