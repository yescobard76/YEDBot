# Auditoría W2/W3: JSON existentes vs replay actual

**Fecha:** 2026-11-23  
**Alcance:** W2 (2025-04-01 → 2025-06-30) y W3 (2025-07-01 → 2025-09-30).  
**Holdout:** no ejecutado. Los replays terminan el 2025-06-30 y el 2025-09-30.

## Veredicto

- Los `W2.json` y `W3.json` existentes **no están obsoletos por el código**.
- Reproducen exactamente el lock v1.2 con el código actual: mismas operaciones, mismo P&L y mismas métricas.
- No coinciden con el replay paper de 56 operaciones porque **son experimentos distintos**: distinto perfil, distinto tope de stop y distinta ventana de exclusión.
- **No hay que regenerar los W2/W3 oficiales** para usarlos como referencia del protocolo congelado.
- Si se quieren usar como referencia del replay de 56 operaciones, **no se deben reemplazar los oficiales**: hay que crear artefactos separados con el perfil exacto del replay. Ese perfil ya no está en disco, así que primero hay que recuperarlo o congelar uno nuevo.

## Reproducción con el lock actual

Ejecutado con `reports/backtest/audit_w2_w3_current.py`:

| Fuente | W2 ops | W2 neto | W2 PF | W3 ops | W3 neto | W3 PF |
|---|---:|---:|---:|---:|---:|---:|
| `W2.json` / `W3.json` (19-nov) | 4 | +268,40 | 1,71 | 9 | −110,46 | 0,92 |
| `regenerated/W2.json` / `W3.json` (20-nov) | 4 | +268,40 | 1,71 | 9 | −110,46 | 0,92 |
| Lock v1.2 + código actual (auditoría) | 4 | +268,40 | 1,71 | 9 | −110,46 | 0,92 |
| Replay paper de 56 ops | 7 | +377,64 | 1,48 | 14 | −684,66 | 0,71 |

La auditoría actual reproduce **todos** los IDs de operación y los campos de entrada/salida de los JSON. Los hashes de código son distintos (`22c68a13…` en los JSON, `dd9c8826…` en los regenerados y `14d2c9f9…` en el código actual), pero el comportamiento de W2/W3 no cambió.

También se ejecutó el mismo lock en modo **adjusted**: W2 dio 4 ops / +268,40 / PF 1,71 y W3 9 ops / −110,46 / PF 0,92, idénticos a raw. Por tanto, el cambio raw → adjusted **no explica** la diferencia con el replay de 56.

- Lock: `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c`.
- Dataset raw: `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a`.
- Dataset adjusted: `1c80da8b312f06a329caf30dc3a1505949f31e0bacd72bc14349282dffed3e5f`.
- Última sesión auditada: W2 `2025-06-30`; W3 `2025-09-30`.

## Por qué difieren W2/W3 del replay

El replay de 56 operaciones no es el baseline del lock. Estas son las diferencias comprobables:

1. **Tope de stop.** El lock corta en `max_sl_ticks=200`. El replay contiene entradas con stops de 211 a 345 ticks. De las 12 operaciones que aparecen en el replay y no en los JSON, **11 tienen stop > 200**.
2. **Exclusión horaria.** El reporte del replay conserva una exclusión `12:01–12:59`. Las tres operaciones del lock que no aparecen en el replay entran a las **12:39, 12:28 y 12:20**, dentro de esa ventana.
3. **Perfil distinto y ya modificado.** El replay se generó con el perfil cuyo hash era `acff3138…`; el archivo actual `profiles/backtest_real/config.json` tiene hash `f9cb1316…` y fue modificado después del replay. Por tanto, el perfil exacto del replay **no está disponible** en el estado actual.
4. **Cambios residuales.** No todo se explica por el cap y la exclusión. La operación 2025-05-16 cambia de stop 51 → 101 ticks; 2025-07-15 de 119 → 124; 2025-08-11 de 145 → 173; y 2025-07-07 cambia de qty 2 → 3. Hay además una operación extra con stop 146 (2025-07-30) y una operación del lock que no aparece (2025-05-22, 13:04). Eso confirma que el perfil del replay también cambió otras reglas, no solo el cap.

La diferencia es sistémica, no un problema aislado de W2/W3:

| Bloque | Lock v1.2 | Replay 56 |
|---|---:|---:|
| W1 | 8 ops / +364,82 | 12 ops / +1.803,10 |
| W2 | 4 ops / +268,40 | 7 ops / +377,64 |
| W3 | 9 ops / −110,46 | 14 ops / −684,66 |
| W4 | 4 ops / +2.034,12 | 11 ops / +2.519,48 |
| W5 | 5 ops / −1.036,52 | 7 ops / −275,04 |
| W6 | 8 ops / −858,92 | 5 ops / −423,36 |
| **Total** | **38 ops / +661,44** | **56 ops / +3.317,16** |

El replay incluye 56 operaciones y el lock 38; no son comparables como si fueran el mismo backtest. El total del replay en la DB es +3.318,66, con una diferencia de 1,50 USD en la operación 2025-11-28 respecto al reporte de perfil.

## Configuración y datos

- `data/config.json` actual: hash `a7c7fb3e…`.
- `profiles/backtest_real/config.json` actual: hash `f9cb1316…`.
- El reporte `profile_filter_replay.json` registra `active_sha256=0f907ba7…` y `profile_sha256=acff3138…`.
- El lock no cambió: `55d89872…`.
- La auditoría no escribió configuración: cargó el lock y cambió solo `feed` en memoria. No se abrió el holdout.

## Recomendación

1. **Mantener `reports/backtest/W2.json` y `W3.json` como están** para las métricas del protocolo congelado. Son válidos y reproducibles con el código actual, tanto en raw como en adjusted.
2. **No mezclar** esas métricas con las del replay de 56 operaciones. El agregado correcto del lock es 38 ops / +661,44; el del replay es 56 ops / +3.317,16.
3. Si el replay de 56 es la referencia operativa, usar sus métricas por bloque directamente desde la DB o desde `profile_filter_replay.json` y etiquetarlas como **paper replay / perfil**, no como baseline.
4. Si se necesitan artefactos W2/W3 regenerados para ese replay, crear archivos nuevos (por ejemplo `W2_replay.json` y `W3_replay.json`) después de **recuperar o congelar el perfil exacto**. Regenerar ahora con el perfil actual produciría un tercer conjunto de resultados y no reproduciría el replay de 56.

## Artefactos de esta auditoría

- `reports/backtest/audit_w2_w3_current.py`
- `reports/backtest/_audit_w2_w3/current_W2.json`
- `reports/backtest/_audit_w2_w3/current_W3.json`
- `reports/backtest/_audit_w2_w3/summary.json`
- `reports/backtest/_audit_w2_w3/adjusted_W2.json`
- `reports/backtest/_audit_w2_w3/adjusted_W3.json`
- `reports/backtest/_audit_w2_w3/summary_adjusted.json`

Todas las cifras de W2/W3 corresponden a la variante `full`.
