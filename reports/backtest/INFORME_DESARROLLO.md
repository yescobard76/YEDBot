# Informe de desarrollo — Protocolo v1.2

**Alcance:** W1–W6 sobre las 362 sesiones evaluadas de desarrollo (2025-01-10 → 2026-06-30).
**Holdout:** sellado, no descargado y no inspeccionado.
**Fecha:** 2026-11-20.
**Revisión técnica:** 2026-11-20, corrección del modo `adjusted` (G3) y auditoría del evaluador de puertas. Sin cambios de protocolo, lock, estrategia, parámetros ni holdout.

## 1. Identificación

| Elemento | Valor |
|---|---|
| Protocolo | v1.2, `docs/PROTOCOLO_BACKTEST.md` |
| SHA-256 protocolo | `2419ec7e4d008e0007372b373c5e045428e7252fb62c4a43a6a7b6a63172d49f` |
| SHA-256 lock | `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c` |
| SHA-256 settings del lock | `09dc05923d81a1d61bead548d274fe6a9cecbf37f6e37473904c0603b1bdef99` |
| SHA-256 código (`server/` + `tests/`) | `648858d576d40b5fdb41f33cf8af9e88efa61225b59ca49ef97cfbe766f39a60` |
| Perfil aislado | `profiles/backtest_real/config.json` (idéntico al lock) |

Las ejecuciones de W1 usaron `profiles/backtest_real/config.json` y se verificó igualdad exacta con `lock["settings"]`. `data/config.json` es la configuración viva del servidor y puede diferir; no se usó para W1. `compute_gates.py` lee el lock directamente.

## 2. Dataset

| Elemento | Valor |
|---|---|
| Fuente | Databento `GLBX.MDP3`, esquema `ohlcv-1m` + `definition` |
| Archivo | `data/real/bars_mnq_nq_es_1m.csv` |
| SHA-256 | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` |
| `dataset_id` | `f2e9a2c5dff56b79195dcc19cc79b2dd9b2245ebfde6e7956471967a31f3f2b3` |
| `series_id` (raw) | `b844560f36b33c478c0e1e7caee18bb639488b0113d071d5369c640b865f07ff` |
| `series_id` (adjusted corregido) | `4d8e1c6a023ec3cba63bb70788459b85b252baca6e11a69cdd1e727344b50578` |
| Rango | 2025-01-10 09:00 → 2026-06-30 15:59 ET |
| Sesiones | 368 de calendario, 362 evaluadas (6 rolls excluidas) |
| Contratos declarados | 21 (H25, M25, U25, Z25, H26, M26, U26 por raíz) |
| Rolls | 6 eventos, 6 sesiones excluidas |
| Rellenos | 0 |
| Cierres anticipados | 2025-07-03 (240 velas), 2025-11-28 y 2025-12-24 (255) |
| Validación | `ok=true`, `aligned=true`, 0 sesiones inválidas, 0 ausentes, 0 huecos intra-sesión |

Los 21 contratos y 6 rolls son los correctos para desarrollo; el lock 24/21/7 corresponde al dataset completo con holdout.

**Observación técnica:** el validador cuenta 367 huecos, que son exactamente los 367 límites entre las 368 sesiones (cierres overnight), no minutos ausentes. La comprobación literal de §8.2 (`gaps.count == 0`) no encaja con esa definición; se verificó aparte que los huecos intra-sesión son 0.

## 3. Bloques

| Bloque | Sesiones | Ops | PF | Exp. R | P&L neto | DD máx | Peor racha |
|---|---|---:|---:|---:|---:|---:|---:|
| W1 | 54 | 8 | 1,35 | +0,56 | +364,82 | 619,42 | 2 |
| W2 | 61 | 4 | 1,71 | +0,11 | +268,40 | 378,88 | 3 |
| W3 | 63 | 9 | 0,92 | −0,13 | −110,46 | 1.084,80 | 6 |
| W4 | 63 | 4 | ∞ (sin pérdidas) | +2,36 | +2.034,12 | 0,00 | 0 |
| W5 | 60 | 5 | 0,00 | −1,01 | −1.036,52 | 1.036,52 | 5 |
| W6 | 61 | 8 | 0,27 | −0,40 | −858,92 | 931,30 | 5 |
| **Agregado** | **362** | **38** | **1,13** | **+0,131** | **+661,44** | **1.967,82 (7,14 %)** | **10** |

Largos: 21 ops, +335,36 USD. Cortos: 17 ops, +326,08 USD, PF 1,15, exp. R +0,033.
Sharpe 0,82 y Sortino 1,58 (calculados según §8.3 sobre días con operaciones).

## 4. Puertas de aceptación

| ID | Criterio | Valor | Umbral | Estado |
|---|---|---|---|---|
| G1 | Integridad del dataset | 368/368, 362 evaluadas, 362/362 sesiones en bloques, 0 huecos internos, rolls MNQ/NQ/ES OK | D1–D8 | **PASS** |
| G2 | Determinismo | W1 repetido con el mismo código: 8/8 ops idénticas y mismo `selected_id` | idénticas | **PASS** |
| G3 | Raw vs adjusted | W1: 8/8 ops, P&L y PF idénticos; base NQ/MNQ preservada | mismas ops | **PASS** |
| G4 | Muestra | 38 ops (21 largos, 17 cortos) | ≥80 y ≥20/dirección | **FAIL** |
| G5 | Edge neto | PF 1,1328; exp. R +0,1311 | PF ≥1,25 y R ≥+0,10 | **FAIL** |
| G6 | Riesgo | DD 1.967,82 USD; peor racha 10 | ≤2.000 USD y ≤8 | **FAIL** |
| G7 | Consistencia | 3/6 bloques con PF>1 (W1, W2, W4) | ≥4/6 | **FAIL** |
| G8 | Robustez a costes | PF 1,07 (comisión 1,24/lado, slippage 2) | PF ≥1,10 | **FAIL** |
| G9 | Robustez a outliers | P&L tras quitar 5 mejores: −2.607,48 | >0 | **FAIL** |
| G10 | Concentración | Top-5 57,94 % del bruto; mejor mes 134,0 % del neto | ≤50 % y ≤50 % | **FAIL** |
| G11 | Estadística | IC bootstrap 80 %: −0,2185 (p2,5 −0,3913) | >0 | **FAIL** |
| G12 | Cortos | 17 cortos, PF 1,148, exp. R +0,033 | ≥20 cortos | **FAIL** |
| G13 | Ambigüedad | 0 ops ambiguas (0 %) | ≤5 % | **PASS** |
| G14 | Integridad de resultados | 0 campos incompletos, 0 duplicados | completa | **PASS** |

**Fallan:** G4, G5, G6, G7, G8, G9, G10, G11, G12.

**Auditoría del evaluador (`compute_gates.py`):** G1 comprueba además que la suma de sesiones de W1–W6 sea 362 y que los rolls de MNQ, NQ y ES sean consistentes; G2 compara dos ejecuciones del mismo código; G8 queda `PENDING` si falta el stress, no FAIL; los PF infinitos se serializan como `"inf"` (nunca `NaN`/`Infinity`) y el bootstrap tiene guardia para `n=0`. `gates.json` contiene 14 puertas, 0 pendientes y la decisión se deriva de `failed`/`pending`.

## 5. Control raw vs adjusted (G3) — revisión técnica

**Estado:** **PASS**. W1 produce 8/8 operaciones idénticas, mismo P&L (+364,82), mismo PF (1,35) y misma cantidad con `raw` y `adjusted`.

**Causa raíz:** la estrategia calcula ORB, entrada y stop con barras de **NQ** y ejecuta en **MNQ**. En `adjusted`, cada raíz recibía su propio spread acumulado: MNQ +1725,25, NQ +1722,75 y ES +396,50. Esa diferencia de 2,5 puntos entre NQ y MNQ cambiaba la base relativa de los niveles NQ aplicados a MNQ y alteraba fills, stops y objetivos. No era un error del plan de rolls (G1 y G2 pasan), sino una incoherencia del modo `adjusted` para una estrategia multi-símbolo.

**Corrección aplicada (código, no protocolo):**

- En cada roll, **NQ y MNQ comparten un único offset**: el de MNQ, instrumento de ejecución. ES conserva su propio offset; el SMT compara pivotes dentro de cada instrumento y un desplazamiento constante no altera la divergencia.
- El redondeo de los niveles se ancla a la base sin ajustar: `round(precio − offset, 2) + offset`. Así `raw` conserva exactamente su comportamiento y `adjusted` es una traslación exacta, sin diferencias de un tick por redondeo de medio tick.
- `ORBStrategy` recibe los offsets por sesión desde el backtest. No cambia la definición de la estrategia ni sus parámetros.
- `reports/backtest/compute_gates.py` lee la configuración del **lock**, no del `data/config.json` vivo, para que la evaluación sea reproducible. El evaluador valida la cobertura de bloques, los rolls de las tres raíces, serializa los PF infinitos como `"inf"` y protege el bootstrap con `n=0`.

**Evidencia:**

- Base NQ–MNQ: `max |(adjNQ − adjMNQ) − (rawNQ − rawMNQ)| = 0` en **151.530 barras**; 0 barras con diferencia.
- W1 `raw`: 8 ops, PF 1,35, neto +364,82; idéntico al W1 previo a la corrección.
- W1 `adjusted`: 8 ops, PF 1,35, neto +364,82; 0 diferencias de operación, P&L o cantidad.
- `applied_cumulative_offsets`: MNQ +1725,25, NQ +1725,25, ES +396,50.
- `basis_residual_cumulative`: MNQ 0, NQ −2,50, ES 0. Es el residuo de continuidad de NQ (su spread de roll difiere del de MNQ); se acepta para preservar la base del par. Las sesiones de roll se excluyen y la estrategia evalúa intradía, por lo que el salto entre sesiones no afecta las decisiones.
- `series_id` adjusted corregido: `4d8e1c6a023ec3cba63bb70788459b85b252baca6e11a69cdd1e727344b50578`; `raw` sigue `b844560f...`.

**Alcance:** no se tocó el holdout, el protocolo (`2419ec7e...`), el lock (`55d89872...`), la configuración (`09dc0592...`); no se cambió la definición de la estrategia ni sus parámetros. Es una corrección de conformidad con §4.4, no una versión nueva del protocolo. El código cambia (`648858d5...`), por lo que se regeneró el manifiesto de desarrollo.

**Efecto en las puertas:** G3 pasa; quedan 9 fallos (G4–G12). La decisión sigue **INCONCLUSO** por muestra y edge. El agregado no cambia porque W1 `raw` no cambió.

Los artefactos previos a la corrección se conservan en `reports/backtest/pre_adjusted_fix/` para auditoría.

## 6. Ablaciones (descriptivas, no decisorias)

| Variante | Ops | PF | Exp. R | P&L neto | DD máx |
|---|---:|---:|---:|---:|---:|
| `orb` | 3 | 6,19 | +1,07 | +583,56 | 112,48 |
| `orb_smt` | 4 | 2,28 | +0,70 | +390,84 | 305,20 |
| `orb_retest` | 49 | 1,21 | +0,25 | +1.347,44 | 2.303,12 |
| `full` (endpoint) | 38 | 1,13 | +0,13 | +661,44 | 1.967,82 |

Las muestras de `orb` y `orb_smt` son demasiado pequeñas para comparar; no se usan para aprobar ni rechazar.

## 7. Robustez

| Prueba | Resultado |
|---|---|
| Costes dobles (G8) | 38 ops, PF 1,07, exp. R +0,11, neto +347,38 |
| Drop-best 5 | Neto −2.607,48 |
| Top-5 / beneficio bruto | 57,94 % |
| Mejor mes / P&L neto | 134,0 % |
| Bootstrap esperanza R (10.000, semilla 20250102) | media +0,129; p2,5 −0,391; p10 −0,219; p90 +0,482; p97,5 +0,676 |
| Barras ambiguas | 0 ops (0 %) |

## 8. Holdout

No ejecutado. El protocolo solo lo permite si todas las puertas duras de desarrollo pasan; no es el caso. El holdout (`2026-07-01` → `2026-10-30`) sigue sellado y no se descargó ni observó.

## 9. Decisión

**INCONCLUSO.** G3 quedó corregido y en PASS. G4 no alcanza la muestra mínima (38 operaciones y 17 cortos), por lo que el resultado no permite distinguir la estrategia de la nada. Además fallan G5, G6, G7, G8, G9, G10, G11 y G12. No se promueve a paper trading con fines de validación y el holdout no se ejecuta; el replay visual en paper no altera esta decisión.

## 10. Limitaciones

- 38 operaciones dan intervalos amplios; el bootstrap remuestrea operaciones, no sesiones, y es una cota optimista.
- El PF agregado 1,13 es descriptivo: no supera la puerta y depende de 5 operaciones.
- Sharpe/Sortino usan días con operaciones, según §8.3, no las 362 sesiones.
- El modo `adjusted` ya comparte la base NQ/MNQ. NQ conserva un residuo de continuidad de hasta 5,25 pts por roll para preservar el diferencial del par; ES usa su propio offset.
- La corrección de G3 no cambia la muestra ni el edge; el veredicto sigue limitado por G4.
- W2–W6 se conservan del run original: la corrección solo afecta al camino `adjusted`; W1 `raw` se reprodujo 8/8, `W1_repeat` se reejecutó con el código nuevo y el agregado no cambió. Por eso W2–W6 mantienen el hash de código anterior (`22c68a13...`).
- En `W4.json` y `blocks_summary.json` el PF es `null` porque `compute_stats` no representa infinito; `gates.json` lo normaliza a `"inf"` para G7 y para la tabla de bloques.
- Sin holdout no hay confirmación fuera de muestra.

## 11. Anexo de archivos

- `reports/backtest/validator.json` — validación del CSV en `raw`.
- `reports/backtest/dataset_sha256.txt` — SHA-256 del CSV.
- `reports/backtest/dataset_manifest_dev.json` — procedencia de desarrollo.
- `reports/backtest/W1.json` … `W6.json` — 4 variantes por bloque.
- `reports/backtest/W1_repeat.json` — determinismo.
- `reports/backtest/W1_adjusted.json` — control G3.
- `reports/backtest/blocks_summary.json` — tabla por bloque.
- `reports/backtest/development_aggregate.json` — agregado `compute_stats`.
- `reports/backtest/variant_aggregate.json` — ablaciones agregadas.
- `reports/backtest/stress_costs.json` — costes dobles.
- `reports/backtest/determinism_w1.json` — G2.
- `reports/backtest/raw_vs_adjusted_w1.json` — G3 detallado.
- `reports/backtest/pre_adjusted_fix/` — W1, W1_repeat, W1_adjusted y G3 previos a la corrección, preservados.
- `reports/backtest/gates.json` — todas las puertas y la decisión.
