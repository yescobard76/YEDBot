# Paso 1 — Reality Check N=25 y bootstrap por sesión

**Fecha:** 2026-11-25
**Objeto:** aplicar corrección por multiple testing (Reality Check de White, N=25), bootstrap por sesión, neto sin top-3 e intervalo del RDD a las 25 variantes ya medidas, y decidir si alguna merece gastar H1.
**Naturaleza:** análisis **read-only** sobre artefactos existentes. No se re-ejecutó ningún backtest, no se tocó el 8765, no se modificó ninguna configuración, no se leyó ni ejecutó el holdout y no se cambiaron locks.
**H1:** `2026-07-01 → 2026-10-30`, 85 sesiones, sellado. **No se abre en esta pasada.**

---

## 0. Resumen ejecutivo

- **Ninguna de las 25 variantes supera la corrección por multiple testing.** Reality Check con N=25: **p = 0,547**. Sin la base (N=24): **0,547**. Sin las tres variantes de coste x2 (N=22): **0,5467**. El mejor candidato nominal no es distinguible de la base.
- **Tampoco hay edge absoluto demostrable:** el Reality Check contra cero da **p = 0,2244**. Es decir, ni siquiera “alguna variante gana dinero” sobrevive a las 25 pruebas.
- **Mejor candidato nominal:** `excl_1200_1400` (exclusión 12:00–14:00), **+1.478,00 USD** de delta, neto **3.500,94**, DD **1.835,30**, RDD **1,9076**. Su **neto sin sus 3 mayores ganancias es 1.289,28** (la base, sin las suyas, es **−196,98**). Aun así: **IC 95 % del RDD [−0,43; 10,00]**, **IC 95 % del ΔRDD [−0,14; 6,03]**, p individual **0,2838**, 3/6 ventanas positivas. **No pasa.**
- **La base es frágil:** sus 3 mejores operaciones aportan **2.219,92 USD**; sin ellas, el neto de la manual es **−196,98 USD**. La ventaja de la manual en la muestra está muy concentrada.
- **RDD:** 0/25 intervalos absolutos excluyen el cero (ni por arriba ni por abajo). Solo `cost_x2` tiene un IC de ΔRDD que excluye el cero, y lo hace **por abajo** ([−0,79; −0,04]): es peor, no una mejora.
- **Decisión:** **ningún candidato merece gastar H1**. Se mantiene la manual, H1 sigue sellado y no se cambia el 8765. Añadir más variantes in-sample solo empeoraría el problema de multiple testing.

---

## 1. Método

### 1.1 Entradas y verificación

| Fuente | Uso | SHA-256 |
|---|---|---|
| `reports/autoloop/progreso.json` | Operaciones completas de las 25 variantes | `1953a040861178f5091612779bb4ae98ada15163ec32c30a3ed3867ac05780c6` |
| `reports/autoloop/resultados.jsonl` | Agregados publicados; contraste de neto/DD | `84e89705eb03ffa160b1b89fa0abacccb7efceb97ef10f4eced6f64c570661b7` |
| `reports/autoloop/_delta_calendar.json` | Calendario W1–W6, 362 sesiones | `51cafe6d4d8e2bc30ec1f60b8419db76c1d141eba52c1ebe4cf84bcfd09a7363` |
| `data/bars.csv` | Dataset de las corridas (solo identidad) | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` |
| `profiles/live_8765/config.json` | Configuración de referencia | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |

Comprobaciones hechas por el script antes de calcular:

- 25 variantes, con los mismos ids en `progreso.json` y `resultados.jsonl`.
- 362 sesiones, de `2025-01-10` a `2026-06-30`; ninguna sesión en H1.
- La suma de `pnl` de cada variante coincide con su `net` publicado (tolerancia 0,01 USD) y el número de operaciones coincide.
- El calendario se generó con el mismo hash de configuración que `data/config.json` y que el perfil vivo.
- El DD calculado sobre la secuencia de operaciones coincide con el `dd` publicado (tolerancia 0,01 USD).

No se re-simuló nada: se usan las operaciones ya registradas.

### 1.2 Unidad y bootstrap

- **Unidad:** sesión ET, fechada por `exit_ts`; las 362 sesiones del calendario entran, con **0** en las que no hay operación. Es el mismo criterio que `research/validate_delta.py`.
- **Bootstrap:** bloques móviles circulares, longitud **20** = `ceil(sqrt(362))`, **10.000** remuestras, semilla **20250102**, IC percentil 95 %.
- **Remuestreo conjunto:** los mismos bloques para las 25 variantes. Así se conserva la correlación entre variantes y la comparación pareada con la base.
- **RDD:** `neto / max(DD absoluto, 1)`. El DD se calcula sobre la curva de PnL cerrado (orden `entry_ts`). En cada remuestra se concatenan las operaciones de las sesiones sorteadas, preservando el orden intra-sesión, y se recalcula neto, DD y RDD.
- **IC del RDD:** percentiles 2,5/97,5 de las 10.000 remuestras. **IC del ΔRDD:** diferencia pareada RDD(variante) − RDD(base) en cada remuestra.
- **Neto sin top-3:** se eliminan hasta las 3 mayores ganancias de cada variante y se recalcula el neto. Para comparar, también se calcula la base sin sus 3 mayores ganancias.

### 1.3 Reality Check

Para cada variante \(k\) se define la serie de exceso por sesión \(f_{k,t} = PnL_{k,t} - PnL_{base,t}\). El estadístico es:

\[
V = \sqrt{T}\max_k \bar f_k
\]

La distribución nula se obtiene remuestreando bloques de sesiones y recentrando cada variante en su media muestral:

\[
V^*_b = \sqrt{T}\max_k \left(\bar f^*_{k,b} - \bar f_k\right)
\]

El p-valor de familia es `(1 + #{V*_b ≥ V}) / (B+1)`. Es el p de **“ninguna variante supera a la base”**, no un p por variante. Con N=25 se incluye la base como estrategia de exceso cero; como su exceso es 0 y nunca es el máximo, el resultado coincide con N=24. La sensibilidad N=22 excluye las tres variantes de coste x2. El contraste absoluto contra cero usa la misma mecánica con \(f_{k,t}=PnL_{k,t}\).

**Puerta H1 fijada antes de ejecutar** (en el script):

1. RC p (N=25) < 0,05.
2. IC 95 % del RDD absoluto con límite inferior > 0.
3. IC 95 % del ΔRDD con límite inferior > 0.
4. Δ del neto sin top-3 > 0.
5. Neto sin top-3 > 0.

No se rebajan después de ver el resultado.

---

## 2. Reality Check

| Familia | N | Estadístico V | p | Mejor por delta |
|---|---:|---:|---:|---|
| **N=25 (todas, con base)** | 25 | 77,682 | **0,5470** | `excl_1200_1400` |
| N=24 (sin base) | 24 | 77,682 | 0,5470 | `excl_1200_1400` |
| N=22 (sin coste x2) | 22 | 77,682 | 0,5467 | `excl_1200_1400` |
| Absoluto contra cero | 25 | 184,005 | 0,2244 | `excl_1200_1400` |

**Lectura:**

- El p de familia es **0,547**: en más de la mitad de las remuestras, el máximo exceso recentrado supera al observado. No hay evidencia de que la mejor variante bata a la manual.
- El p individual del mejor (`excl_1200_1400`) es **0,2838**; Bonferroni con 25 pruebas lo lleva a **1,0**. El Reality Check (0,547) es menos conservador que Bonferroni pero muy lejos de 0,05.
- El contraste absoluto (p **0,2244**) confirma que el problema no es solo “comparar con la manual”: **tampoco se puede afirmar que alguna de las 25 tenga un edge positivo** con esta muestra.
- N=25 incluye la base porque es una de las configuraciones medidas; su exceso es cero y no altera el máximo. El resultado es idéntico con N=24. La conclusión no depende de ese detalle.

---

## 3. Ranking, neto sin top-3 e intervalo del RDD

### 3.1 Principales candidatos

| Candidato | Ops | Neto | Δ neto | Neto s/top-3 | Δ s/top-3 | RDD | IC 95 % RDD | IC 95 % ΔRDD | +W | p ind. |
|---|---:|---:|---:|---:|---:|---:|---|---|---:|---:|
| `excl_1200_1400` | 46 | 3.500,94 | 1.478,00 | 1.289,28 | 1.486,26 | 1,9076 | [−0,43; 10,00] | [−0,14; 6,03] | 3/6 | 0,2838 |
| `excl_1130_1230` | 48 | 3.340,90 | 1.317,96 | 1.179,42 | 1.376,40 | 2,6532 | [−0,38; 9,89] | [−0,72; 6,38] | 3/6 | 0,4243 |
| `excl_1130_1330` | 36 | 3.203,82 | 1.180,88 | 1.105,14 | 1.302,12 | 2,3274 | [−0,35; 12,74] | [−1,00; 9,90] | 3/6 | 0,5648 |
| `excl_1100_1300` | 26 | 2.500,18 | 477,24 | 532,70 | 729,68 | 4,9814 | [−0,53; 12,42] | [−1,75; 9,74] | 3/6 | 0,8400 |
| `sl_200` | 46 | 2.471,78 | 448,84 | 251,86 | 448,84 | 1,0726 | [−0,78; 7,71] | [−1,21; 3,33] | 3/6 | 0,7070 |
| `excl_1130_1330+sl_200` | 17 | 2.805,52 | 782,58 | 838,04 | 1.035,02 | 3,4472 | [−0,38; 20,72] | [−1,27; 17,88] | 4/6 | 0,7476 |

`+W` = ventanas con neto positivo (no con delta positivo). `p ind.` es el bootstrap recienteado de dos colas, **sin corregir**; se muestra solo para ver la distancia con la corrección.

**Lo importante:** todos los IC del RDD y del ΔRDD incluyen cero. Los RDD puntuales altos de `excl_1100_1300` (4,98 con 26 ops) y `excl_1130_1330+sl_200` (3,45 con 17 ops) son inestables: sus IC llegan a 12,4 y 20,7. No son una base para promover nada.

### 3.2 Las 25 variantes

| # | Variante | Ops | Neto | Δ neto | Neto s/top-3 | Δ s/top-3 | DD | RDD | IC 95 % RDD | +W |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---:|
| 1 | `excl_1200_1400` | 46 | 3.500,94 | 1.478,00 | 1.289,28 | 1.486,26 | 1.835,30 | 1,9076 | [−0,43; 10,00] | 3/6 |
| 2 | `excl_1130_1230` | 48 | 3.340,90 | 1.317,96 | 1.179,42 | 1.376,40 | 1.259,18 | 2,6532 | [−0,38; 9,89] | 3/6 |
| 3 | `excl_1130_1330` | 36 | 3.203,82 | 1.180,88 | 1.105,14 | 1.302,12 | 1.376,54 | 2,3274 | [−0,35; 12,74] | 3/6 |
| 4 | `excl_1130_1330+daily_loss_2` | 36 | 3.203,82 | 1.180,88 | 1.105,14 | 1.302,12 | 1.376,54 | 2,3274 | [−0,35; 12,74] | 3/6 |
| 5 | `excl_1130_1330+range_min_15` | 36 | 3.203,82 | 1.180,88 | 1.105,14 | 1.302,12 | 1.376,54 | 2,3274 | [−0,35; 12,74] | 3/6 |
| 6 | `excl_1130_1330+cost_x2` | 36 | 2.975,14 | 952,20 | 916,78 | 1.113,76 | 1.421,08 | 2,0936 | [−0,43; 11,85] | 3/6 |
| 7 | `excl_1130_1330+sl_200` | 17 | 2.805,52 | 782,58 | 838,04 | 1.035,02 | 813,86 | 3,4472 | [−0,38; 20,72] | 4/6 |
| 8 | `excl_1130_1330+sl_200+cost_x2` | 17 | 2.638,54 | 615,60 | 722,58 | 919,56 | 843,22 | 3,1291 | [−0,46; 19,17] | 4/6 |
| 9 | `excl_1100_1300` | 26 | 2.500,18 | 477,24 | 532,70 | 729,68 | 501,90 | 4,9814 | [−0,53; 12,42] | 3/6 |
| 10 | `excl_1100_1300+daily_loss_2` | 26 | 2.500,18 | 477,24 | 532,70 | 729,68 | 501,90 | 4,9814 | [−0,53; 12,42] | 3/6 |
| 11 | `excl_1100_1300+range_min_15` | 26 | 2.500,18 | 477,24 | 532,70 | 729,68 | 501,90 | 4,9814 | [−0,53; 12,42] | 3/6 |
| 12 | `sl_200` | 46 | 2.471,78 | 448,84 | 251,86 | 448,84 | 2.304,46 | 1,0726 | [−0,78; 7,71] | 3/6 |
| 13 | `excl_1100_1300+sl_200` | 15 | 2.362,02 | 339,08 | 394,54 | 591,52 | 501,90 | 4,7062 | [−0,71; 16,50] | 4/6 |
| 14 | `excl_1130_1330+validity_180` | 31 | 2.025,98 | 3,04 | −27,70 | 169,28 | 1.351,58 | 1,4990 | [−0,67; 9,90] | 4/6 |
| 15 | `manual_base` *(base)* | 72 | 2.022,94 | 0,00 | −196,98 | 0,00 | 2.891,66 | 0,6996 | [−0,81; 5,78] | 3/6 |
| 16 | `daily_loss_2` | 72 | 2.022,94 | 0,00 | −196,98 | 0,00 | 2.891,66 | 0,6996 | [−0,81; 5,78] | 3/6 |
| 17 | `range_min_15` | 72 | 2.022,94 | 0,00 | −196,98 | 0,00 | 2.891,66 | 0,6996 | [−0,81; 5,78] | 3/6 |
| 18 | `tol_18` | 70 | 1.960,38 | −62,56 | −234,78 | −37,80 | 2.887,88 | 0,6788 | [−0,84; 6,14] | 3/6 |
| 19 | `sl_buffer_8` | 71 | 1.822,38 | −200,56 | −272,12 | −75,14 | 2.847,92 | 0,6399 | [−0,84; 5,65] | 3/6 |
| 20 | `contracts_7` | 72 | 1.669,48 | −353,46 | −542,18 | −345,20 | 2.781,20 | 0,6003 | [−0,85; 5,52] | 3/6 |
| 21 | `rr_2_5` | 72 | 1.462,18 | −560,76 | −394,44 | −197,46 | 2.891,66 | 0,5057 | [−0,83; 5,16] | 3/6 |
| 22 | `cost_x2` | 72 | 1.436,88 | −586,06 | −744,96 | −547,98 | 3.023,82 | 0,4752 | [−0,87; 5,03] | 3/6 |
| 23 | `validity_180` | 66 | 1.154,30 | −868,64 | −1.065,62 | −868,64 | 2.625,74 | 0,4396 | [−0,87; 4,92] | 2/6 |
| 24 | `rr_3_5` | 72 | 977,44 | −1.045,50 | −1.475,06 | −1.278,08 | 3.635,80 | 0,2688 | [−0,93; 4,73] | 3/6 |
| 25 | `sl_250` | 60 | 728,06 | −1.294,88 | −1.491,86 | −1.294,88 | 3.186,32 | 0,2285 | [−0,93; 4,38] | 3/6 |

La tabla completa con DD, IC del ΔRDD, p individual, ventana mejor y ranking por RDD está en `reports/autoloop/reality_check_25.csv` y en el JSON.

### 3.3 Neto sin top-3: la base no sobrevive

| Métrica | Base | `excl_1200_1400` | `excl_1130_1230` | `excl_1130_1330` |
|---|---:|---:|---:|---:|
| Neto completo | 2.022,94 | 3.500,94 | 3.340,90 | 3.203,82 |
| Suma de las 3 mayores ganancias | 2.219,92 | 2.211,66 | 2.161,48 | 2.098,68 |
| **Neto sin top-3** | **−196,98** | **1.289,28** | **1.179,42** | **1.105,14** |
| Δ sin top-3 vs base | — | +1.486,26 | +1.376,40 | +1.302,12 |

- **13/25** variantes conservan neto positivo sin sus 3 mejores operaciones; **14/25** baten a la base en esa métrica.
- La manual **no** conserva neto positivo: sin sus 3 mejores trades pierde **196,98 USD**. Su ventaja histórica está concentrada en muy pocas operaciones.
- Los tres candidatos de exclusión horaria sí conservan más de **1,1–1,3k** sin sus top-3. Es un punto descriptivo a favor, pero **no corrige** el problema de significación: el IC del RDD sigue incluyendo cero y el RC p es 0,547.

### 3.4 Consistencia por ventana

Delta de neto frente a la base (USD):

| Variante | W1 | W2 | W3 | W4 | W5 | W6 |
|---|---:|---:|---:|---:|---:|---:|
| `excl_1200_1400` | −506,18 | −61,20 | +349,02 | +224,20 | +537,84 | +934,32 |
| `excl_1130_1230` | −289,56 | +439,64 | −113,06 | −349,80 | +959,30 | +671,44 |
| `excl_1130_1330` | −1.045,82 | +532,12 | −288,32 | −448,56 | +1.497,14 | +934,32 |

- El mejor candidato tiene **4/6 ventanas con delta positivo** (W3–W6), pero **pierde en W1 y W2**. Las otras dos dependen de W5/W6 y pierden mucho en W1.
- Las “3/6 ventanas positivas” de la tabla anterior son de **neto absoluto** (W1, W2, W4); el delta se concentra en W3–W6. No hay una mejora amplia y estable: es, sobre todo, evitación de pérdidas en la segunda mitad de la muestra.
- A coste x2, la mejor variante de exclusión (`excl_1130_1330+cost_x2`) hace **+952,20** de delta, RDD **2,0936**, IC [−0,43; 11,85]; sigue sin significación (p individual 0,6130). El estrés de costes no rescata ninguna candidata.

### 3.5 Duplicados y correlación

- `daily_loss_2` y `range_min_15` son **idénticas a la base** (no cambian ninguna operación).
- `excl_1130_1330+daily_loss_2` y `excl_1130_1330+range_min_15` son **idénticas a `excl_1130_1330`**.
- Las tres variantes `cost_x2` son otro régimen de costes, no otra hipótesis de estrategia.

Por eso el número efectivo de hipótesis independientes es menor que 25. El RC con N=25 es el encuadre literal pedido y, en la práctica, conservador en el conteo; aun así, el p de familia es 0,547. La conclusión no cambia si se quitan duplicados o coste x2.

---

## 4. Puerta H1

| Candidato | RC p N=25 | IC RDD, límite bajo | IC ΔRDD, límite bajo | Δ neto s/top-3 | Neto s/top-3 | Puerta |
|---|---:|---:|---:|---:|---:|---|
| `excl_1200_1400` | 0,547 | −0,43 | −0,14 | 1.486,26 | 1.289,28 | **NO** |
| `excl_1130_1230` | 0,547 | −0,38 | −0,72 | 1.376,40 | 1.179,42 | **NO** |
| `excl_1130_1330` | 0,547 | −0,35 | −1,00 | 1.302,12 | 1.105,14 | **NO** |
| `excl_1100_1300` | 0,547 | −0,53 | −1,75 | 729,68 | 532,70 | **NO** |
| `sl_200` | 0,547 | −0,78 | −1,21 | 448,84 | 251,86 | **NO** |
| `excl_1130_1330+sl_200` | 0,547 | −0,38 | −1,27 | 1.035,02 | 838,04 | **NO** |

**0/25 pasan.** Los candidatos con mejor neto pasan las dos puertas de neto sin top-3, pero **fallan las tres puertas estadísticas**: RC, RDD absoluto y ΔRDD. `excl_1130_1330+sl_200` añade además un problema de tamaño: 17 operaciones.

**Decisión:** **no se gasta H1.** El holdout es la única muestra ciega disponible; abrirlo con un p de familia de 0,547 y un IC del RDD que cruza cero destruiría su valor sin una hipótesis que haya pasado la selección. Se mantiene el estado `sealed_not_executed`.

---

## 5. Conclusión

1. **Ningún candidato merece H1.** La mejor variante nominal (`excl_1200_1400`) no es significativa ni antes (p individual 0,2838) ni después de corregir (RC p 0,547), y su RDD no es distinguible de cero.
2. **La manual sigue siendo la referencia**, pero su neto es frágil: sin sus 3 mejores trades es negativo. Eso no la convierte en mala, pero sí obliga a no presentarla como una ventaja robusta.
3. **No cambiar el 8765, no abrir H1 y no añadir más variantes in-sample.** Con 25 pruebas ya no hay señal; ampliar la búsqueda sobre la misma muestra solo aumenta el data snooping.
4. Si se quiere seguir, el cuello de botella es **muestra independiente** (forward o H1 con un protocolo pre-registrado y one-shot), no otra vuelta sobre W1–W6. La exclusión 12:00–14:00 es la hipótesis con mejor soporte descriptivo, pero **no ha pasado la puerta** y no se promociona.

---

## 6. Integridad y reproducción

### 6.1 Lo que no se tocó

| Comprobación | Resultado |
|---|---|
| 8765 | PID **16016**, listener `127.0.0.1:8765`; sin parada, reinicio ni llamada a la API |
| Log del 8765 | `logs/server_8765_20261125.log`, 580 B, sin cambios |
| DB del 8765 | 72 trades / 730 eventos; no abierta |
| Configuración | `data/config.json` y `profiles/live_8765/config.json` con SHA-256 `9bf4f9c7…e29479f`; sin cambios |
| Locks | `docs/protocolo_backtest.lock.json` y `docs/pre_registro_sl200_10c_vs_p1.lock.json` sin cambios |
| Holdout | No leído ni ejecutado; el calendario termina en `2026-06-30` y el script aborta si ve una sesión ≥ `2026-07-01` |
| Backtests | Ninguno; solo se remuestrearon operaciones ya registradas |

### 6.2 Reproducción

```bash
PYTHONIOENCODING=utf-8 python research/reality_check_25.py
```

- 10.000 remuestras, semilla 20250102; runtime ~24 s.
- Salidas: `reports/autoloop/reality_check_25.json` (completo) y `reports/autoloop/reality_check_25.csv` (tabla plana).
- El script verifica netos, DD, número de operaciones, calendario y hash de configuración antes de calcular; si algo no cuadra, aborta.

### 6.3 Limitaciones

- **In-sample:** las 25 variantes se propusieron y midieron sobre W1–W6. El RC corrige la selección entre 25, pero no convierte la muestra en independiente.
- **Búsqueda adaptativa:** el universo real de hipótesis probadas es mayor que 25 (autoloop, combinaciones, presets previos). El p de 0,547 es, si acaso, **optimista**; la conclusión de no promover es robusta.
- **Bootstrap aproximado:** remuestrea sesiones y conserva el orden intra-sesión, pero no re-simula el sizing dependiente del equity ni los fills. Los IC son una aproximación, no una garantía.
- **RDD inestable con pocas operaciones:** los IC de 15–26 ops son muy anchos (hasta 20,7). No se debe leer el RDD puntual sin su intervalo.
- **Coste x2:** las tres variantes de coste x2 se incluyen en N=25; la sensibilidad N=22 no cambia la conclusión.
- **Sin forward:** no hay muestra independiente; H1 sigue sellado.

---

**Resumen de una línea:** con N=25, RC p=0,547; ningún RDD positivo excluye el cero; el mejor candidato no pasa; **H1 no se gasta**.
