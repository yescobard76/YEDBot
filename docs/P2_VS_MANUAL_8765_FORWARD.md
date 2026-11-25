# Pre-registro forward — P2 `10/200/210/24` frente al manual 8765

**Versión:** 1.0  
**Fecha:** 2026-11-24  
**Estado:** pre-registrado y **no ejecutado**. No se ha capturado ni leído ninguna
barra forward, no se ha ejecutado ningún backtest nuevo y el holdout
`2026-07-01 → 2026-10-30` sigue sellado.  
**Lock:** [`p2_vs_manual_8765_forward.lock.json`](p2_vs_manual_8765_forward.lock.json).  
**Hipótesis:** `H-P2-VS-MANUAL-8765-FORWARD`.  
**Brazos:** manual 8765 (`M`) y P2 (`C`), ambos con filtro 0,00.  
**Ventana:** `2026-12-01 → 2029-11-30`, 742 sesiones evaluadas.

> Este documento no demuestra que P2 sea rentable. Fija de antemano qué se
> medirá, contra qué benchmark, qué mejora se exigirá y cuándo el candidato se
> considera muerto. No modifica `data/config.json` ni
> `profiles/live_8765/config.json`, no cambia el 8765, no activa el filtro 0,25,
> no reabre el holdout y no sustituye la prioridad forward actual
> `docs/FORWARD_ORIGINAL_VS_P1.md`.
>
> **Solapamiento declarado:** el plan [`P2_BE_1R_FORWARD.md`](P2_BE_1R_FORWARD.md)
> ya incluye esta comparación M/C como H1. Este es un pre-registro **enfocado**
> de esa misma pregunta, no una segunda confirmación independiente. Si P2+BE se
> ejecuta, este plan se cancela; si este plan se ejecuta, P2+BE no puede
> reclamar independencia. Solo uno de los dos puede usar la ventana.

---

## 1. Pregunta e hipótesis

### 1.1 Pregunta

En una muestra forward independiente, ¿P2 (`max_sl_ticks=200`, 10 contratos,
210/24, filtro 0,00) obtiene más neto y menor drawdown que el manual vivo del
8765 (`max_sl_ticks=300`, 10 contratos, 210/24, filtro 0,00), sin cambiar nada
más?

### 1.2 Motivación in-sample

En W1–W6, con el mismo dataset de desarrollo:

| Brazo | Ops | Neto USD | PF | DD USD | R medio |
|---|---:|---:|---:|---:|---:|
| Manual 8765 `M` | 72 | +2.022,94 | 1,22 | 2.891,66 | 0,18 |
| P2 `C` | 46 | +2.471,78 | 1,39 | 2.304,46 | 0,25 |
| **Diferencia C − M** | **−26** | **+448,84** | **+0,17** | **−587,20** | **+0,07** |

Estas cifras son **in-sample y solo motivan la hipótesis**. No se exige
reproducir exactamente `+448,84` ni `−587,20`: el forward debe validar el signo,
la incertidumbre y el límite de drawdown definidos abajo. El replay de 45 trades
del 8765 (snapshot 06:26Z, +2.720,04, PF 1,46, DD 2.366,76) es runtime paper y
**no se usa** como muestra ni como validación.

### 1.3 Hipótesis

**H1:** en forward, P2 mejora el neto frente a M, con un límite inferior del
IC95 % de `Δnet` mayor que cero, y reduce el drawdown máximo al menos un 10 %
frente a M, sin deteriorar el profit factor, la esperanza en R ni el RDD.

**H0:** `Δnet <= 0`, o el IC95 % incluye cero, o el drawdown no baja al menos un
10 %, o P2 no alcanza las puertas de rentabilidad/robustez. No se promociona
“el que menos pierde”.

### 1.4 Endpoints

**Primario de rentabilidad:**

```text
Δnet = net_profit_usd(P2) − net_profit_usd(M)
```

- Unidad de observación: operación cerrada.
- Unidad de remuestreo: sesión.
- Bootstrap percentil 95 %, 10.000 réplicas, semilla `20261124`, contraste
  unilateral `H0: Δnet <= 0`, mínimo 9.500 réplicas válidas.
- PASS de E1 si `Δnet > 0` y el límite inferior del IC95 % es `> 0`.

**Primario de riesgo:**

```text
DD_ratio = max_drawdown_usd(P2) / max_drawdown_usd(M)
```

- PASS de E2 si `DD_ratio <= 0,90` (drawdown de P2 al menos 10 % menor) y el
  drawdown absoluto de P2 no supera al de M.
- No se usa un drawdown cero como denominador; si M tiene DD cero, el estudio
  es `INCONCLUSO`.

**Rentabilidad ajustada:**

```text
RDD_USD = net_profit_usd / max_drawdown_usd
```

- PASS de E5 si `RDD_USD(P2) >= 1,05 × RDD_USD(M)`.
- Se reporta también RDD en R, pero el endpoint de decisión es USD.

---

## 2. Brazos y configuración congelada

| Elemento | Manual M | P2 C |
|---|---|---|
| ID | `M` | `C` |
| Rol | benchmark vivo | candidato |
| Perfil | `data/config.json`; copia de solo lectura `profiles/live_8765/config.json` | `profiles/p2_freq/config.json` |
| `config_sha256` canónico | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` | `54656561bf692731d71013c6655155a566c9b4b49fe53a88d61bf20814310f4f` |
| Hash de archivo | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` | `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb` |
| `risk.max_contracts` | 10 | 10 |
| `risk.max_sl_ticks` | **300** | **200** |
| `strategy.setup_validity_minutes` | 210 | 210 |
| `strategy.retest_tolerance_ticks` | 24 | 24 |
| `risk.min_stop_or_ratio` efectivo | 0,00 | 0,00 |
| `risk.risk_per_trade_pct` | 1,0 | 1,0 |
| `risk.max_trades_per_day` | 3 | 3 |
| `risk.max_concurrent_positions` | 1 | 1 |
| `strategy.tp_rr` | 3,0 | 3,0 |
| Gestión | ninguna | ninguna |
| `live.live_enabled` | false | false |

Los hashes canónicos excluyen `feed`, `live` y `mode`; los hashes de archivo
identifican los bytes exactos. El perfil manual es de **solo lectura**: si
cambia antes o durante la captura, el estudio se aborta; no se actualiza el
benchmark en silencio.

### 2.1 Única diferencia permitida

```text
M -> C:
  risk.max_sl_ticks: 300 -> 200
```

No hay ninguna otra diferencia de estrategia, ejecución, sizing, riesgo,
frecuencia, feed, contratos, comisiones o ventana. En particular:

- `max_contracts=10` en ambos.
- `setup_validity_minutes=210` y `retest_tolerance_ticks=24` en ambos.
- `min_stop_or_ratio=0,00` en ambos; **este estudio no activa el filtro 0,25**.
- `tp_rr=3,0`, ORB, SMT y geometría de entrada sin cambios.
- Mismo CSV forward, mismos timestamps, mismos contratos y mismos rolls.
- `live.live_enabled=false`; no hay paper en tiempo real ni LIVE.

El feed forward sustituye únicamente el feed de backtest, igual en ambos brazos:

```text
feed.provider=csv
feed.csv_path=reports/backtest/p2_vs_manual_8765_forward/bars_forward.csv
feed.series_mode=raw
feed.exclude_roll_sessions=true
feed.loop_sessions=false
feed.replay_speed=1.0
```

### 2.2 Qué no es este experimento

- No es el filtro `min_stop_or_ratio=0,25`.
- No es P2+BE; no hay break-even, trailing, parcial ni cambio de target.
- No es una comparación contra el original `5/200/150/12`; el control es el
  manual vivo `10/300/210/24`.
- No es una prueba de contratos: 10 en ambos brazos.
- No autoriza cambiar el 8765, `data/config.json`, P2 ni ningún lock.

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
| W1–W6 | 2025-01-10 → 2026-06-30 | Usada para descubrir/motivar P2; es in-sample. |
| Holdout H1 | 2026-07-01 → 2026-10-30 | Sellado por el protocolo v1.2; no se abre. |
| 2024 externo | 2024-01-02 → 2024-12-30 | Reservado por otra hipótesis; no independiente. |
| Burn-in | 2026-11-23 → 2026-11-30 | Solo plomería; excluido. |
| Muestra compartida | la que use otro lock | Dos hipótesis sobre la misma muestra no son confirmaciones independientes. |

**Conflicto de independencia:** este plan comparte la ventana con
`docs/P2_BE_1R_FORWARD.md` y con el plan original/P1. No se puede ejecutar a la
vez que otro forward. Si P2+BE u otro plan usa esta muestra, este estudio no es
una confirmación independiente y debe cancelarse. No se abre el holdout para
“completar” la muestra.

### 3.3 Frecuencia esperada y mínimos

Con las tasas in-sample W1–W6:

- Manual: `72 / 362 = 19,9 %` → ~148 operaciones en 742 sesiones.
- P2: `46 / 362 = 12,7 %` → ~94 operaciones.
- Pares M/C: como máximo ~94; P2 rechaza señales con stop >200 que M acepta.
  El solapamiento esperado es alto, pero no se exige que las entradas sean
  idénticas.

Son conteos esperados, no una promesa. La muestra se fija por calendario, no por
número de operaciones.

| ID | Condición | Si falla |
|---|---|---|
| P2M-S1 | ≥720 de 742 sesiones evaluadas; ningún mes <80 %; ningún hueco >5 sesiones | `INCONCLUSO` |
| P2M-S2 | ≥60 operaciones cerradas por brazo (M y C) | `INCONCLUSO` |
| P2M-S3 | ≥5/6 bloques con ≥6 operaciones cerradas por brazo | `INCONCLUSO` |
| P2M-S4 | ≥5 cortos por brazo | `INCONCLUSO_SHORT` |
| P2M-S5 | ≥60 pares M/C y ≥95 % de las operaciones de C con pareja en M | `INCONCLUSO` |

No se bajan los mínimos, no se añaden bloques, no se extiende la ventana, no se
rellena una sesión y no se sustituye la muestra después de ver resultados.

### 3.4 Captura

- **Proveedor:** Databento `GLBX.MDP3`, `ohlcv-1m`, `raw_symbol` para MNQ, NQ y
  ES.
- **Contratos:** 39 en total, 13 por raíz: `Z26, H27, M27, U27, Z27, H28, M28,
  U28, Z28, H29, M29, U29, Z29`.
- **Rolls:** 36 en total, 12 sesiones de roll excluidas.
- **Series:** `raw`, 1 minuto, `America/New_York`, RTH 09:00–15:59 ET (o cierre
  anticipado oficial 12:59/13:14).
- **Captura:** una sesión por archivo, después del cierre (16:05 ET o más
  tarde), con manifiesto, SHA-256, validación y append-only.
- **Sin relleno:** no se interpolan precios, no se derivan símbolos, no se usan
  barras sintéticas y no se descargan sesiones pasadas para completar.
- **Un solo CSV forward** para M y C; las diferencias se aplican en el replay,
  no en la captura.

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

### 4.1 Integridad (P2M-I)

| ID | Condición | Si falla |
|---|---|---|
| P2M-I1 | Hash del protocolo, lock, perfiles M/C y código verificados | abortar |
| P2M-I2 | Todas las sesiones dentro de 2026-12-01 → 2029-11-30; cero W1–W6, H1, 2024 o burn-in | abortar |
| P2M-I3 | Dataset válido: 39 contratos, 36 rolls, 12 sesiones de roll excluidas, 3 símbolos alineados, ORB completo, cero huecos injustificados | abortar |
| P2M-I4 | Captura prospective: manifiesto por sesión, `captured_at_et` del mismo día, sin backfill, sin datos sintéticos, SHA-256 por archivo | abortar |
| P2M-I5 | Simetría: mismo feed, timestamps, 10 contratos, 210/24 y filtro 0,00; único diff `risk.max_sl_ticks` | abortar |
| P2M-I6 | `min_stop_or_ratio=0,00` en ambos; no se aplica el filtro 0,25 en ningún brazo | abortar |
| P2M-I7 | Sin lookahead: entradas, stops y salidas solo usan barras conocidas en el momento de la señal/ejecución | abortar |
| P2M-I8 | Determinismo: replay del 10 % de las sesiones dos veces produce los mismos `signal_id` y operaciones | abortar |
| P2M-I9 | One-shot: `analysis.json` no existe antes; una sola análisis de eficacia | abortar |
| P2M-I10 | `holdout_bars_read=false` y cero sesiones H1 | abortar |

### 4.2 Muestra (P2M-S)

Las puertas P2M-S1 a P2M-S5 de §3.3.

### 4.3 Rentabilidad y riesgo (P2M-E)

| ID | Condición | Si falla |
|---|---|---|
| P2M-E1 | `Δnet > 0` y límite inferior del IC95 % por sesión `> 0` | `FAIL` / `INCONCLUSO` si el IC incluye 0 |
| P2M-E2 | `DD_P2 / DD_M <= 0,90` y `DD_P2 <= DD_M` | `FAIL` |
| P2M-E3 | `PF_P2 >= 1,25` y `PF_P2 >= PF_M` | `FAIL` |
| P2M-E4 | `expectancy_R_P2 >= +0,10` y `>= expectancy_R_M` | `FAIL` |
| P2M-E5 | `RDD_USD_P2 >= 1,05 × RDD_USD_M` | `FAIL` |

`P2M-E1` no exige reproducir `+448,84`; exige que la mejora de neto sea
positiva y distinguishable de cero. `P2M-E2` no exige reproducir `−587,20`;
exige que el drawdown baje al menos un 10 %, un margen inferior al 20,3 %
observado in-sample.

### 4.4 Costes y robustez (P2M-C)

| ID | Condición | Si falla |
|---|---|---|
| P2M-C1 | Reprecio exacto de M y P2 con comisión 1,24 USD/lado y slippage 2 ticks; `net_P2 > 0` y `PF_P2 >= 1,10` después de costes | `FAIL` |
| P2M-C2 | `drop_best_3_net_P2 > 0` | `FAIL` |
| P2M-C3 | `top_trade_share_gross_P2 <= 50 %` | `FAIL` |

No se usa una estimación uniforme de costes como si fuera un reprecio exacto.
El coste exacto del original (`−314,06`) y la estimación del filtro (`−100,80`)
no se trasladan a M ni a P2.

---

## 5. Decisión, KILL y parada

### 5.1 Regla de decisión

| Resultado | Condición |
|---|---|
| **PASS** | Pasan P2M-I, P2M-S, P2M-E y P2M-C. P2 es candidato a un protocolo nuevo de preparación operativa. |
| **FAIL** | P2M-I y P2M-S pasan, pero P2M-E o P2M-C fallan con evidencia clara en contra. Se mantiene M. |
| **INCONCLUSO** | Fallan P2M-I o P2M-S; o P2M-E1 incluye cero sin un fallo claro; o faltan muestras. Se mantiene M. |
| **KILL** | Se cumple K1–K3. |

`PASS` **no autoriza LIVE**, no cambia `data/config.json`, no cambia el 8765 y no
autoriza paper en tiempo real. Solo indica que P2 superó este protocolo.

### 5.2 KILL

| ID | Condición | Efecto |
|---|---|---|
| K1 | Falla P2M-I, se lee el holdout o la captura no es prospective | abortar; no hay resultado |
| K2 | `net_P2 < 0,70 × net_M` o `DD_P2 > 1,25 × DD_M` | KILL de P2 |
| K3 | `net_P2 <= 0`, `PF_P2 < 1,00` o `expectancy_R_P2 < 0` | KILL de P2 |

Un KILL cierra la hipótesis para esta muestra. No se reintenta con otra ventana,
otro stop, otro umbral ni un subgrupo.

### 5.3 Parada

| ID | Cuándo | Qué ocurre |
|---|---|---|
| STOP-T1 | Falla cualquier P2M-I, hay una sesión prohibida o se lee el holdout | abortar de inmediato |
| STOP-T2 | Cambia el hash del protocolo, lock o perfil M/C antes de ejecutar | abortar; se necesita lock nuevo |
| STOP-T3 | Un mes completo tiene <80 % de sesiones o >5 sesiones consecutivas perdidas | detener y declarar `INCONCLUSO` |
| STOP-F1 | Se alcanza 2029-11-30 con la muestra sellada o se completan 742 sesiones | una única análisis final |
| STOP-F2 | Fallan P2M-S1–S5 | `INCONCLUSO`; no hay análisis de eficacia |
| STOP-F3 | Se cumple K2–K3 | `KILL`; no se rescata |

No hay parada anticipada por P&L, DD, RDD, número de ganadoras ni resultado
prometedor. La captura diaria solo produce conteos de integridad; no produce
P&L ni decisiones.

---

## 6. Prerrequisitos de ejecución (fase 0)

El lock nace con `execution_gate.can_execute=false`. Antes de capturar o
ejecutar hay que resolver, como mínimo:

1. **Captura prospective:** job que descargue una sesión después del cierre, la
   valide, la selle y la agregue al CSV forward. `CSVFeed` sobre un CSV estático
   no basta.
2. **Universo contractual:** 39 contratos `Z26–Z29` y 36 rolls; no reutilizar la
   lista global H25–Z26 sin parametrizar.
3. **Credencial:** `DATABENTO_API_KEY` fuera del repositorio. Sin clave no hay
   captura.
4. **Preflight y runner one-shot:** verificación de hashes, ventana permitida,
   fechas prohibidas, holdout sellado, ausencia del directorio de salida y una
   única ejecución.
5. **Lock de ejecución:** hash del código final, perfiles M/C, feed y CSV.
   Cualquier cambio que afecte entradas, salidas, riesgo, sizing o ejecución
   invalida el pre-registro.
6. **Resolución de solapamiento:** antes de ejecutar, decidir si se usa este
   plan o `P2_BE_1R_FORWARD`; no ambos. Si se usa P2+BE, este plan se cancela.
7. **Tests de plomería:** captura, append, sellado, rechazo de fechas prohibidas
   y reproducibilidad con fixtures sintéticos; sin W1–W6 ni holdout.

Mientras estos prerrequisitos no estén completos, **no se captura ni se
ejecuta** nada.

---

## 7. Qué no autoriza este documento

- No autoriza LIVE ni cambia `live_enabled`.
- No autoriza paper en tiempo real.
- No modifica `data/config.json`, `profiles/live_8765/config.json`,
  `profiles/p2_freq/config.json`, la DB, el protocolo v1.2, sus locks ni el
  holdout.
- No reabre W1–W6, 2024, el holdout ni el burn-in.
- No activa el filtro 0,25; ambos brazos tienen `min_stop_or_ratio=0,00`.
- No reutiliza los gates S0–Q5 del filtro.
- No cambia la prioridad forward actual `docs/FORWARD_ORIGINAL_VS_P1.md`.
- No se ejecuta a la vez que P2+BE ni otro forward que use la misma ventana.
- No convierte el +448,84 in-sample en una validación.

---

## 8. Artefactos y estado

- `docs/P2_VS_MANUAL_8765_FORWARD.md` — este protocolo.
- `docs/p2_vs_manual_8765_forward.lock.json` — lock de pre-registro con hashes,
  brazos, muestra, gates, KILL y estado `can_execute=false`.
- `reports/backtest/p2_vs_manual_8765_forward/` — directorio futuro para
  captura, manifiestos y análisis; **no creado**.
- `reports/backtest/p2_vs_manual_8765_forward/analysis.json` — salida única
  futura; **no existe**.
- `reports/backtest/p2_vs_manual_8765_forward/ANALISIS.md` — informe futuro;
  **no existe**.

**Estado actual:** pre-registrado, no ejecutado. No se ha capturado ni analizado
ninguna barra forward. No se ha tocado el holdout, la configuración viva, el
8765, el perfil P2 ni los locks existentes. `execution_gate.can_execute = false`.
