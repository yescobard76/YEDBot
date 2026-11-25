# Pre-registro forward — SL 200 con 10 contratos frente al manual 8765 y frente a P1

**Versión:** 1.0  
**Fecha:** 2026-11-24  
**Estado:** pre-registrado y **no ejecutado**. No se ha capturado ni leído ninguna
barra forward, no se ha ejecutado ningún backtest nuevo y el holdout
`2026-07-01 → 2026-10-30` sigue sellado.  
**Lock:** [`pre_registro_sl200_10c_vs_p1.lock.json`](pre_registro_sl200_10c_vs_p1.lock.json).  
**Hipótesis:** `H-SL200-10C-VS-P1-FORWARD`.  
**Brazos:** manual 8765 (`M`), SL 200 con 10 contratos (`T`) y P1 (`P1`), los tres
con filtro 0,00.  
**Ventana:** `2026-12-01 → 2029-11-30`, 742 sesiones evaluadas.

> Este documento no demuestra que bajar el stop sea rentable. Fija de antemano
> qué se medirá, contra qué benchmarks, qué mejora se exigirá y cuándo el
> candidato se considera muerto. No modifica `data/config.json` ni
> `profiles/live_8765/config.json`, no cambia el 8765, no activa el filtro 0,25,
> no reabre el holdout y no sustituye la prioridad forward actual
> `docs/FORWARD_ORIGINAL_VS_P1.md`.
>
> **Solapamiento declarado:** este pre-registro comparte control, tratamiento y
> ventana con [`P2_VS_MANUAL_8765_FORWARD.md`](P2_VS_MANUAL_8765_FORWARD.md) y
> con [`P2_BE_1R_FORWARD.md`](P2_BE_1R_FORWARD.md), y comparte ventana con
> [`FORWARD_ORIGINAL_VS_P1.md`](FORWARD_ORIGINAL_VS_P1.md). **No es una
> confirmación independiente.** Añade el brazo P1 para separar el efecto del
> stop del efecto del sizing. Solo uno de estos planes puede ejecutarse sobre la
> misma ventana; si se ejecuta este, el P2 vs manual se cancela para esta
> muestra. Los documentos y locks existentes no se editan: quedan como
> históricos.

---

## 1. Pregunta e hipótesis

### 1.1 Pregunta

En una muestra forward independiente, con **10 contratos** y frecuencia
`210/24`:

1. ¿Bajar `max_sl_ticks` de **300 a 200** mejora el neto y reduce el drawdown
   frente al manual vivo del 8765, sin cambiar nada más?
2. ¿El perfil resultante `10/200/210/24` conserva el edge por operación de P1
   (`5/200/210/24`) y su rentabilidad ajustada al riesgo, o el cambio de sizing
   introduce un deterioro que el neto bruto esconde?

La segunda pregunta es la **comparación contra P1**. No se plantea como
“10 contratos gana más dólares que 5” —eso es aritmética de sizing— sino como
**equivalencia del edge en R y del RDD**, más el coste en drawdown.

### 1.2 Motivación in-sample

En W1–W6, con el mismo dataset de desarrollo:

| Brazo | Ops | Neto USD | PF | DD USD | R medio | RDD (neto/DD) |
|---|---:|---:|---:|---:|---:|---:|
| Manual 8765 `M` 10/300 | 72 | +2.022,94 | 1,22 | 2.891,66 | 0,18 | 0,6996 |
| SL 200 `T` 10/200 | 46 | +2.471,78 | 1,39 | 2.304,46 | 0,25 | 1,0726 |
| P1 `P1` 5/200 | 46 | +1.992,26 | 1,37 | 1.947,82 | 0,25 | 1,0228 |

Descomposición histórica:

- `M → T` (stop 300→200, mismo sizing 10): **+448,84 USD**, **−587,20 USD de
  DD**, **+0,17 PF**, **+0,07 R** de expectancy.
- `P1 → T` (sizing 5→10, mismo SL 200): **+479,52 USD**, **+356,64 USD de DD**,
  **+0,02 PF**, **0,00 R** de expectancy.
- `M → P1` (stop y sizing): **−30,68 USD**, **−943,84 USD de DD**, **+0,15 PF**,
  **+0,07 R**; descriptivo, no es la palanca de frecuencia.
- La frecuencia original→P1 (**+1.330,82 USD**) no se usa aquí porque la original
  `5/200/150/12` no es brazo de este plan.

Estas cifras son **in-sample y solo motivan la hipótesis**. No se exige
reproducir `+448,84` ni `−587,20`: el forward debe validar el signo, la
incertidumbre y los límites de riesgo definidos abajo. El replay parcial del
8765 (runtime paper, decenas de trades y equity en curso) **no se usa** como
muestra ni como validación; además, la muestra viva de enero de 2025 es
demasiado pequeña y contradice el signo histórico del stop, lo que refuerza la
necesidad del forward.

### 1.3 Hipótesis

**H1 (stop):** en forward, `T` (`10/200/210/24`) obtiene más neto que `M`
(`10/300/210/24`), con el límite inferior del IC95 % de `Δnet` mayor que cero,
y reduce el drawdown máximo al menos un 10 %, sin deteriorar PF, expectancy en R
ni RDD.

**H2 (sizing vs P1):** `T` conserva el edge por operación de `P1`: expectancy R
y PF equivalentes dentro de tolerancia, `total_R` equivalente, y RDD no inferior
al de P1. Si H2 falla, el resultado de H1 no autoriza a adoptar 10 contratos
frente a P1: solo describe el efecto del stop con el sizing actual.

**H0:** `Δnet <= 0`, o el IC95 % incluye cero, o el drawdown no baja al menos un
10 %, o `T` no alcanza las puertas de rentabilidad/robustez, o `T` no es
equivalente a P1 en R. No se promociona “el que menos pierde”.

### 1.4 Endpoints

**Primario de rentabilidad (M → T, mismo sizing 10):**

```text
Δnet = net_profit_usd(T) − net_profit_usd(M)
```

- Unidad de observación: operación cerrada.
- Unidad de remuestreo: sesión.
- Bootstrap percentil 95 %, 10.000 réplicas, semilla `20261124`, contraste
  unilateral `H0: Δnet <= 0`, mínimo 9.500 réplicas válidas.
- PASS de E1 si `Δnet > 0` y el límite inferior del IC95 % es `> 0`.

**Primario de riesgo (M → T):**

```text
DD_ratio = max_drawdown_usd(T) / max_drawdown_usd(M)
```

- PASS de E2 si `DD_ratio <= 0,90` y `DD_T <= DD_M`.
- Si `DD_M == 0`, el estudio es `INCONCLUSO`; no se usa un denominador cero.

**Rentabilidad ajustada (M → T):**

```text
RDD_USD = net_profit_usd / max_drawdown_usd
```

- PASS de E4 si `RDD_USD(T) >= 1,05 × RDD_USD(M)`.
- Se reporta también RDD en R, pero el endpoint de decisión es USD.

**Comparación contra P1 (T vs P1, mismo SL y frecuencia, distinto sizing):**

```text
Δexpectancy_R = expectancy_R(T) − expectancy_R(P1)
ΔPF           = PF(T) − PF(P1)
Δtotal_R      = total_R(T) − total_R(P1)
```

- E5a: `|Δexpectancy_R| <= 0,05 R`.
- E5b: `|ΔPF| <= 0,10`.
- E5c: `|Δtotal_R| <= 2,0 R`.
- E5d: `DD_T <= 1,30 × DD_P1`.
- E5e: `RDD_USD(T) >= RDD_USD(P1)`.
- PASS de E5 solo si se cumplen las cinco. Si falla E5a–E5c, el sizing o la
  secuencia de equity cambiaron las operaciones; no se adopta `T` como versión
  escalada de P1 y se investiga antes de cualquier conclusión.
- `net_T > net_P1` se reporta, pero **no es un test de superioridad**: con 10 vs
  5 contratos el neto se escala mecánicamente. La pregunta útil es si el edge y
  el RDD se conservan.

**Por qué el primario es Δnet y no Δtotal_R:** `M` y `T` no tienen el mismo
número de operaciones (el stop 200 rechaza señales con stop >200 que `M`
acepta). `total_R` puede bajar aunque el neto suba, porque suma R de menos
trades. Con el mismo sizing, el efecto económico es el neto en USD. Entre `T` y
`P1`, que sí comparten selección, la unidad comparable es R. Usar `Δtotal_R`
como primario mezclaría conteo de trades con rentabilidad y favorecería
mecánicamente al brazo con más operaciones.

---

## 2. Brazos y configuración congelada

| Elemento | Manual `M` | SL 200 `T` | P1 `P1` |
|---|---|---|---|
| Rol | control / benchmark vivo | tratamiento | referencia de sizing |
| Perfil fuente | `profiles/live_8765/config.json`; copia idéntica en `data/config.json` | `profiles/p2_freq/config.json` | `profiles/p1_forward_control/config.json` |
| `config_sha256` canónico | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` | `54656561bf692731d71013c6655155a566c9b4b49fe53a88d61bf20814310f4f` | `5527b32cd54353c52968a47fb84471b7012846cefa06413349bcba7085e7e087` |
| Hash de archivo | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb` | `8058b7d7002de547a535a349dbe7f3557e4aaea1e92d392b064dd51b0b8b624b` |
| `risk.max_contracts` | 10 | 10 | 5 |
| `risk.max_sl_ticks` | **300** | **200** | **200** |
| `strategy.setup_validity_minutes` | 210 | 210 | 210 |
| `strategy.retest_tolerance_ticks` | 24 | 24 | 24 |
| `risk.min_stop_or_ratio` efectivo | 0,00 | 0,00 | 0,00 |
| `risk.risk_per_trade_pct` | 1,0 | 1,0 | 1,0 |
| `risk.max_trades_per_day` | 3 | 3 | 3 |
| `risk.max_concurrent_positions` | 1 | 1 | 1 |
| `strategy.tp_rr` | 3,0 | 3,0 | 3,0 |
| Gestión | ninguna | ninguna | ninguna |
| `live.live_enabled` | false | false | false |

Los hashes canónicos excluyen `feed`, `live` y `mode`; los hashes de archivo
identifican los bytes exactos. Los tres perfiles fuente son de **solo lectura**:
si cambia cualquiera antes o durante la captura, el estudio se aborta; no se
actualiza el benchmark en silencio. Los perfiles de brazo se generarán dentro de
la ventana nueva; no se editan los ficheros de `profiles/`.

### 2.1 Diferencias permitidas

```text
M -> T:
  risk.max_sl_ticks: 300 -> 200

T -> P1:
  risk.max_contracts: 10 -> 5
```

No hay ninguna otra diferencia de estrategia, ejecución, sizing, riesgo,
frecuencia, feed, contratos, comisiones o ventana. En particular:

- `max_contracts=10` en `M` y `T`; 5 en `P1`.
- `setup_validity_minutes=210` y `retest_tolerance_ticks=24` en los tres.
- `min_stop_or_ratio=0,00` en los tres; **este estudio no activa el filtro 0,25**.
- `tp_rr=3,0`, ORB, SMT y geometría de entrada sin cambios.
- Mismo CSV forward, mismos timestamps, mismos contratos y mismos rolls.
- `mode=paper`, `live.live_enabled=false`, `broker=none`.
- Feed forward idéntico para los tres brazos:

```text
feed.provider=csv
feed.csv_path=reports/backtest/sl200_10c_vs_p1_forward/bars_forward.csv
feed.series_mode=raw
feed.exclude_roll_sessions=true
feed.loop_sessions=false
feed.replay_speed=1.0
```

### 2.2 Qué no es este experimento

- No es el filtro `min_stop_or_ratio=0,25`.
- No es P2+BE; no hay break-even, trailing, parcial ni cambio de target.
- No es una comparación contra el original `5/200/150/12`; el control es el
  manual vivo `10/300/210/24`. La comparación contra P1 es de sizing/edge, no
  contra la original.
- No es una prueba de frecuencia: 210/24 en los tres.
- No autoriza cambiar el 8765, `data/config.json`, `profiles/live_8765`,
  `profiles/p2_freq`, `profiles/p1_forward_control` ni ningún lock.
- No usa el runtime paper del 8765 como muestra.

---

## 3. Muestra, captura y mínimos

### 3.1 Ventana

| Bloque | Desde | Hasta | Sesiones de calendario | Rolls excluidos | Sesiones evaluadas |
|---|---|---:|---:|---:|---:|
| F1 | 2026-12-01 | 2027-05-31 | 124 | 2 | 122 |
| F2 | 2027-06-01 | 2027-11-30 | 127 | 2 | 125 |
| F3 | 2027-12-01 | 2028-05-31 | 125 | 2 | 123 |
| F4 | 2028-06-01 | 2028-11-30 | 127 | 2 | 125 |
| F5 | 2028-12-01 | 2029-05-31 | 124 | 2 | 122 |
| F6 | 2029-06-01 | 2029-11-30 | 127 | 2 | 125 |
| **Total** | **2026-12-01** | **2029-11-30** | **754** | **12** | **742** |

- La ventana se fija antes de capturar. No se desplaza si la captura empieza
  tarde: si no se puede empezar el 2026-12-01, se necesita un lock nuevo con
  otra ventana y otra muestra.
- **Burn-in:** `2026-11-23 → 2026-11-30`, excluido del análisis; solo prueba
  captura, validación y sellado.
- Rolls previstos: `2026-12-10`, `2027-03-11`, `2027-06-09`, `2027-09-09`,
  `2027-12-09`, `2028-03-09`, `2028-06-08`, `2028-09-07`, `2028-12-07`,
  `2029-03-08`, `2029-06-07`, `2029-09-13`.

### 3.2 Muestras prohibidas

| Muestra | Fechas | Por qué está prohibida |
|---|---|---|
| W1–W6 | 2025-01-10 → 2026-06-30 | Usada para descubrir/motivar P2 y el stop 200; es in-sample. |
| Holdout H1 | 2026-07-01 → 2026-10-30 | Sellado por el protocolo v1.2; no se abre. |
| 2024 externo | 2024-01-02 → 2024-12-30 | Reservado por otra hipótesis; no independiente. |
| Burn-in | 2026-11-23 → 2026-11-30 | Solo plomería; excluido. |
| Muestra compartida | la que use otro lock | Dos hipótesis sobre la misma muestra no son confirmaciones independientes. |

**Conflicto de independencia:** este plan comparte la ventana con
`P2_VS_MANUAL_8765_FORWARD.md`, `P2_BE_1R_FORWARD.md` y
`FORWARD_ORIGINAL_VS_P1.md`. No se puede ejecutar a la vez que otro forward. Si
otro plan usa esta muestra, este estudio no es una confirmación independiente y
debe cancelarse. No se abre el holdout para “completar” la muestra.

### 3.3 Frecuencia esperada y mínimos

Con las tasas in-sample W1–W6:

- Manual: `72 / 362 = 19,9 %` → ~148 operaciones en 742 sesiones.
- SL 200: `46 / 362 = 12,7 %` → ~94 operaciones.
- P1: `46 / 362 = 12,7 %` → ~94 operaciones.
- Pares `M/T`: como máximo ~94; `T` rechaza señales con stop >200 que `M`
  acepta. El subconjunto común es descriptivo.
- Pares `T/P1`: se espera ~100 %, porque comparten SL 200, frecuencia y filtro;
  solo cambia el sizing. Un pairing inferior al 99 % es una señal de que la
  secuencia de equity o el sizing alteraron las operaciones y debe investigarse.

Son conteos esperados, no una promesa. La muestra se fija por calendario, no por
número de operaciones.

| ID | Condición | Si falla |
|---|---|---|
| S1 | ≥720 de 742 sesiones evaluadas; ningún mes <80 %; ningún hueco >5 sesiones | `INCONCLUSO` |
| S2 | ≥80 operaciones cerradas en `M`; ≥60 en `T`; ≥60 en `P1` | `INCONCLUSO` |
| S3 | ≥5/6 bloques con ≥6 operaciones cerradas por brazo | `INCONCLUSO` |
| S4 | ≥8 cortos por brazo | `INCONCLUSO_SHORT` |
| S5 | ≥60 pares `M/T` y ≥95 % de `T` con pareja en `M`; ≥99 % de `T` con pareja en `P1` | `INCONCLUSO` |

No se bajan los mínimos, no se añaden bloques, no se extiende la ventana, no se
rellena una sesión y no se sustituye la muestra después de ver resultados.

### 3.4 Captura

- **Proveedor:** Databento `GLBX.MDP3`, `ohlcv-1m`, `raw_symbol` para MNQ, NQ y
  ES; misma especificación que el resto de forwards del proyecto.
- **Contratos:** 39 en total, 13 por raíz: `Z26, H27, M27, U27, Z27, H28, M28,
  U28, Z28, H29, M29, U29, Z29`.
- **Rolls:** 36 en total, 12 sesiones de roll excluidas.
- **Series:** `raw`, 1 minuto, `America/New_York`, RTH 09:00–15:59 ET (o cierre
  anticipado oficial 12:59/13:14).
- **Captura:** una sesión por archivo, después del cierre (16:05 ET o más
  tarde), con manifiesto, SHA-256, validación y append-only.
- **Sin relleno:** no se interpolan precios, no se derivan símbolos, no se usan
  barras sintéticas y no se descargan sesiones pasadas para completar.
- **Un solo CSV forward** para `M`, `T` y `P1`; las diferencias se aplican en el
  replay, no en la captura.

Cada archivo debe incluir, como mínimo:

```text
window_id, session_date, captured_at_et, provider, schema,
symbols, contracts, expiries, rows_per_symbol,
first_bar_et, last_bar_et, sha256,
validation {ok, aligned, gaps, opening_range_complete, roll_session},
holdout_bars_read=false, forbidden_session=false
```

---

## 4. Métricas y puertas

Todas las puertas se evalúan una sola vez, al final, con la muestra sellada.
Ninguna se relaja después de ver resultados. No se heredan los gates S0–Q5 del
filtro 0,25.

### 4.1 Integridad (G0–G3)

| ID | Condición | Si falla |
|---|---|---|
| G0 | Hash del protocolo, lock, perfiles `M/T/P1`, código y ventana verificados; 8765 con PID 15108 y hash `9bf4…` sin cambios | abortar |
| G1 | Todas las sesiones dentro de 2026-12-01 → 2029-11-30; cero W1–W6, H1, 2024 o burn-in | abortar |
| G2 | Dataset válido: 39 contratos, 36 rolls, 12 sesiones de roll excluidas, 3 símbolos alineados, ORB completo, cero huecos injustificados; un único SHA-256 de feed para los tres brazos | abortar |
| G3 | Captura prospective: manifiesto por sesión, `captured_at_et` del mismo día, sin backfill, sin datos sintéticos, SHA-256 por archivo; 742/742 sesiones selladas | abortar; 720–741 → `INCONCLUSO` |

### 4.2 Muestra (G4)

Las puertas S1–S5 de §3.3.

### 4.3 Rentabilidad y riesgo (G5–G6)

| ID | Condición | Si falla |
|---|---|---|
| G5 / E1 | `Δnet > 0` y límite inferior del IC95 % por sesión `> 0` | `FAIL`; `INCONCLUSO` si el IC incluye 0 |
| G6 / E2 | `DD_T / DD_M <= 0,90` y `DD_T <= DD_M` | `FAIL` |
| G6 / E3 | `PF_T >= 1,25` y `PF_T >= PF_M`; `expectancy_R_T >= +0,10` y `>= M` | `FAIL` |
| G6 / E4 | `RDD_USD_T >= 1,05 × RDD_USD_M` | `FAIL` |
| G6 / E5 | `|Δexpectancy_R| <= 0,05`; `|ΔPF| <= 0,10`; `|Δtotal_R| <= 2,0 R`; `DD_T <= 1,30 × DD_P1`; `RDD_T >= RDD_P1` | `FAIL` de la comparación con P1 |

`E1` no exige reproducir `+448,84`; exige que la mejora de neto sea positiva y
distinguible de cero. `E2` no exige reproducir `−587,20`; exige que el drawdown
baje al menos un 10 %, un margen inferior al 20,3 % observado in-sample.

### 4.4 Costes y robustez (G8)

| ID | Condición | Si falla |
|---|---|---|
| C1 | Reprecio exacto de `M` y `T` con comisión 1,24 USD/lado y slippage 2 ticks; `net_T > 0`, `PF_T >= 1,10` y `Δnet(T−M) >= 0` después de costes | `FAIL` |
| C2 | `drop_best_3_net_T > 0` | `FAIL` |
| C3 | `top_trade_share_gross_T <= 50 %`; mejor mes `<= 50 %` del neto | `FAIL` |

No se usa una estimación uniforme de costes como si fuera un reprecio exacto.

### 4.5 Determinismo y one-shot (G7 y G9)

| ID | Condición | Si falla |
|---|---|---|
| G7 | Replay del 10 % de las sesiones (75) dos veces produce los mismos `signal_id`, `trade_id`, `qty` y fills; 20 sesiones auditadas: `T` y `P1` con las mismas señales; `M/T` solo difieren en el cohorte stop >200 | abortar |
| G9 | `analysis.json` no existe antes; una sola análisis de eficacia; código y plan de análisis sellados antes de desbloquear | abortar |

---

## 5. Decisión, KILL y parada

### 5.1 Regla de decisión

| Resultado | Condición |
|---|---|
| **PASS** | Pasan G0–G9 y E1–E5. `T` es candidato a un protocolo nuevo de preparación operativa; **no autoriza LIVE**. |
| **FAIL** | Pasan integridad y muestra, pero E1–E5 fallan con evidencia clara en contra. Se mantiene `M`. |
| **INCONCLUSO** | Fallan G0–G4 o G7/G9; o E1 incluye cero sin un fallo claro; o faltan muestras; o `DD_M == 0`. Se mantiene `M`. |
| **ANULA** | Se lee el holdout, la captura no es prospective, hay backfill/sintético, cambia el código/perfil o hay más de un análisis. No hay resultado. |

`PASS` **no autoriza LIVE**, no cambia `data/config.json`, no cambia el 8765 y no
autoriza paper en tiempo real. Solo indica que `T` superó este protocolo.

### 5.2 KILL

| ID | Condición | Efecto |
|---|---|---|
| K1 | Falla G0–G3/G7/G9, se lee el holdout o la captura no es prospective | abortar; no hay resultado |
| K2 | `net_T < 0,70 × net_M` o `DD_T > 1,25 × DD_M` | KILL de `T` |
| K3 | `net_T <= 0`, `PF_T < 1,00` o `expectancy_R_T < 0` | KILL de `T` |
| K4 | E5a–E5c fuera de tolerancia (el sizing cambió las operaciones) | KILL de la comparación `T` vs `P1`; `T` no se adopta como versión escalada de P1 |

Un KILL cierra la hipótesis para esta muestra. No se reintenta con otra ventana,
otro stop, otro umbral ni un subgrupo.

### 5.3 Parada en cuatro momentos

| Momento | Disparador | Acción | Veredicto |
|---|---|---|---|
| **Antes de empezar** | Falla G0–G2; suite no verde; lock ausente o `can_execute=false`; feed ausente; perfiles con diff no permitido; puertos ocupados; 8765 con PID/hash distinto; ventana ya existente | No crear ventana, no capturar, no replay | **STOP** |
| **Durante la captura** | Manifiesto inválido; cadena de hash rota; duplicado/faltante >0,1 %; roll no marcado; gap >5 sesiones; cobertura mensual <80 %; cambio de código/config/snapshot; 8765 cambia; retraso >2 sesiones; backfill/sintético | Parar; marcar `NO_VALIDA`; no reparar editando; T0 y ventana nuevos si se reinicia | **STOP** / **ANULA** |
| **Durante el replay** | `verify_snapshot` no vacío; SHA del feed distinto; error de motor; no determinismo; pairing `T/P1` <99 %; diferencia `M/T` no explicable; holdout; >0,5 % barras ambiguas | No emitir decisión; archivar como inválido | **ANULA** |
| **Tras el análisis** | IC incluye 0; muestra insuficiente; E1–E5 fallan; se intenta ampliar la ventana, reejecutar o mirar subgrupos para rescatar el resultado | Emitir veredicto y cerrar. `INCONCLUSO` no se convierte en `PASS` con más miradas; `FAIL` no se re-testea en la misma ventana | **INCONCLUSO / FAIL / PASS** |

No hay parada anticipada por P&L, DD, RDD, número de ganadoras ni resultado
prometedor. La captura diaria solo produce conteos de integridad; no produce
P&L ni decisiones.

---

## 6. Prerrequisitos de ejecución (fase 0)

El lock nace con `execution_gate.can_execute=false`. Antes de capturar o
ejecutar hay que resolver, como mínimo:

1. **Arnés de tres brazos:** `ARM_PORTS` solo conoce `control` y `treatment`
   (`server/forward/paths.py`), y `init_window` fija `max_contracts=5`,
   `max_sl_ticks=200` y el ratio 0,0/0,25 por nombre de brazo. Hay que añadir un
   brazo `p1` (puerto 8777), overrides explícitos por brazo (contratos, SL,
   frecuencia, ratio) y `end_date=2029-11-30` en `window.json`. Sin este cambio,
   `T` y `P1` no se pueden materializar correctamente.
2. **Test del diff exacto:** un test que genere los tres perfiles y verifique que
   `M→T` solo cambia `max_sl_ticks` y `T→P1` solo cambia `max_contracts`, con
   los hashes canónicos esperados.
3. **Captura prospective:** job que descargue una sesión después del cierre, la
   valide, la selle y la agregue al CSV forward. `CSVFeed` sobre un CSV estático
   no basta.
4. **Universo contractual:** 39 contratos `Z26–Z29` y 36 rolls; no reutilizar la
   lista global H25–Z26 sin parametrizar.
5. **Credencial:** `DATABENTO_API_KEY` fuera del repositorio. Sin clave no hay
   captura.
6. **Preflight y runner one-shot:** verificación de hashes, ventana permitida,
   fechas prohibidas, holdout sellado, ausencia del directorio de salida y una
   única ejecución.
7. **Lock de ejecución:** hash del código final, perfiles `M/T/P1`, feed y CSV.
   Cualquier cambio que afecte entradas, salidas, riesgo, sizing o ejecución
   invalida el pre-registro.
8. **Resolución de solapamiento:** antes de ejecutar, decidir si se usa este
   plan, `P2_VS_MANUAL_8765_FORWARD`, `P2_BE_1R_FORWARD` o
   `FORWARD_ORIGINAL_VS_P1`; no varios sobre la misma ventana. Este plan añade
   P1 y sustituye la ejecución del P2 vs manual para esta muestra; los
   documentos y locks antiguos no se editan.
9. **Tests de plomería:** captura, append, sellado, rechazo de fechas prohibidas
   y reproducibilidad con fixtures sintéticos; sin W1–W6 ni holdout.

Mientras estos prerrequisitos no estén completos, **no se captura ni se
ejecuta** nada.

---

## 7. Qué no autoriza este documento

- No autoriza LIVE ni cambia `live_enabled`.
- No autoriza paper en tiempo real.
- No modifica `data/config.json`, `profiles/live_8765/config.json`,
  `profiles/p2_freq/config.json`, `profiles/p1_forward_control/config.json`, la
  DB, el protocolo v1.2, sus locks ni el holdout.
- No reabre W1–W6, 2024, el holdout ni el burn-in.
- No activa el filtro 0,25; los tres brazos tienen `min_stop_or_ratio=0,00`.
- No reutiliza los gates S0–Q5 del filtro.
- No convierte el `+448,84` ni el `−587,20` in-sample en una validación.
- No usa el runtime paper del 8765 como muestra.
- No se ejecuta a la vez que otro forward que use la misma ventana.

---

## 8. Artefactos y estado

- `docs/PRE_REGISTRO_SL200_10C_VS_P1.md` — este protocolo.
- `docs/pre_registro_sl200_10c_vs_p1.lock.json` — lock de pre-registro con
  hashes, brazos, muestra, gates, KILL y estado `can_execute=false`.
- `reports/backtest/sl200_10c_vs_p1_forward/` — directorio futuro para captura,
  manifiestos y análisis; **no creado**.
- `reports/backtest/sl200_10c_vs_p1_forward/analysis.json` — salida única
  futura; **no existe**.
- `reports/backtest/sl200_10c_vs_p1_forward/ANALISIS.md` — informe futuro;
  **no existe**.

**Estado actual:** pre-registrado, no ejecutado. No se ha capturado ni analizado
ninguna barra forward. No se ha tocado el holdout, la configuración viva, el
8765, los perfiles ni los locks existentes. `execution_gate.can_execute = false`.
