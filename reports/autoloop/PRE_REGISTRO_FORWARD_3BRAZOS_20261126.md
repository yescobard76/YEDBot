# Pre-registro forward de tres brazos — original, viva(`next_open`) y P1

**Versión:** 1.0  
**Fecha:** 2026-11-26  
**Hipótesis:** `H-FWD-3ARM-ORIGINAL-LIVE-P1`  
**Lock:** `reports/autoloop/pre_registro_forward_3brazos_20261126.lock.json`  
**Estado:** `pre_registered_not_executed` — **no ejecutado**, `can_execute=false`.

> Este documento congela el diseño de **un solo forward** con tres brazos. No
> crea ventana, perfiles, captura, CSV, DB, replay ni análisis. No toca el
> 8765, su configuración, su DB ni H1. No modifica locks ni documentos
> existentes. No autoriza LIVE ni paper en tiempo real.

---

## 0. Resumen y veredicto de diseño

El forward propuesto compara, sobre la misma captura prospectiva y el mismo
`fill_model=next_open`:

| Brazo | ID | Configuración | Papel |
|---|---|---|---|
| Original canónica | **C** | 5 contratos, SL 200, 150/12, TP 3R, `or_mid`/`close` | control |
| Viva con fill justo | **L** | 8 contratos, SL 300, 210/24, TP 2R, `or_retracement`/`touch` | paquete actual |
| P1 | **T** | 5 contratos, SL 200, 210/24, TP 3R, `or_mid`/`close` | palanca de frecuencia |

La ventana prevista es la ya pre-registrada `2026-12-01 → 2029-11-30`: 742
sesiones evaluadas, 6 bloques de 6 meses y 12 rolls excluidos.

**Veredicto de potencia, antes de ejecutar:** este forward **no está
potenciado** para confirmar los deltas históricos. Con las tres series diarias
exactas de 362 sesiones (cero si no hay operación):

- `L − C`: MDE ≈ **9.227,56 USD** a 742 sesiones (α 0,05; 80 % de potencia).
  Para detectar los +820,18 históricos harían falta **22.354,7 sesiones**
  (≈ 90,4 años).
- `P1 − C`: MDE ≈ **4.501,70 USD**. Para detectar los +1.330,82 históricos
  harían falta **2.020,8 sesiones** (≈ 8,17 años).
- `L − P1`: el efecto histórico es **negativo** (−510,64); el N80 de
  **61.752,9 sesiones** (≈ 249,7 años) es solo para detectar `|Δ|`, no para
  superioridad de L.

Por tanto, el forward de 36 meses solo puede detectar efectos grandes
(≈ 4,5–9,5k USD) o certificar riesgo/operación. **No debe presentarse como
prueba de que la viva o P1 baten a la original.** Si el requisito es probar un
efecto de ~0,8–1,3k USD con 80 % de potencia, el diseño es inviable en esta
ventana y no debería ejecutarse como confirmatorio.

Además, el arnés actual **no soporta tres brazos**: `ARM_PORTS`, `capture.ARMS`
y `autorun --ports` están cableados a `control`/`treatment`, y `init_window`
impone 5 contratos/SL 200 y el filtro por nombre de brazo. La fase 0 debe
extender el arnés y materializar los tres perfiles antes de que exista un
lock ejecutable. Nada de eso se hace aquí.

---

## 1. Pregunta, hipótesis y familia de contrastes

### 1.1 Pregunta

En una muestra forward independiente, con el mismo feed, los mismos costes y
`next_open` en los tres brazos:

1. ¿El paquete vivo **L** (8/300/210/24, TP 2R, `or_retracement`/`touch`)
   obtiene más neto que la original **C**?
2. ¿La palanca de frecuencia **P1** (5/200/210/24, TP 3R, `or_mid`/`close`)
   obtiene más neto que **C**?
3. ¿Alguno de los dos candidatos respeta el presupuesto de drawdown
   **≤ 2.000 USD** en coste exacto y en coste 2×?

### 1.2 Hipótesis

- **H1 (paquete vivo):** `Δnet(L − C) > 0` y su IC95 % por sesión excluye el
  cero por abajo, sin que la ventaja desaparezca al normalizar por riesgo
  (`Δ expectancy R > 0`).
- **H2 (frecuencia P1):** `Δnet(P1 − C) > 0` y su IC95 % por sesión excluye el
  cero por abajo.
- **H3 (riesgo):** `DD(L) ≤ 2.000` y `DD(P1) ≤ 2.000`, en exacto **y** en 2×.
- **H4 (calidad):** el candidato conserva `PF ≥ 1,10`, `expectancy R > 0` y
  robustez a `drop-best-3` y concentración.
- **H0:** `Δnet ≤ 0`, IC que incluye cero, DD > 2.000 en cualquiera de los dos
  regímenes, o muestra insuficiente. No se promociona “el que menos pierde”.

### 1.3 Familia de contrastes y multiplicidad

| Contraste | Papel | Prueba |
|---|---|---|
| `L − C` neto USD | **primario confirmatorio** | Holm |
| `P1 − C` neto USD | **secundario confirmatorio** | Holm |
| `L − P1` neto USD | descriptivo | sin alfa |
| `L − C` expectancy R | co-criterio del primario | sin alfa propio |
| `P1 − C` expectancy R | apoyo | sin alfa propio |

Holm sobre dos contrastes confirmatorios: el menor p se compara con 0,025 y el
siguiente con 0,05. El contraste `L − P1` no se usa para rescatar un fallo.

**Justificación del primario:** la decisión inmediata es si el paquete vivo,
con fill justo, supera a la original. P1 es la comparación limpia de estrategia
(mismos 5 contratos, SL, TP y entrada), pero no es la configuración que está
corriendo. Si el objetivo fuese una prueba limpia de la palanca de frecuencia,
P1 sería el primario; el MDE sigue siendo grande (8,17 años para el efecto
histórico), así que el problema de potencia no se resuelve cambiando el orden.

---

## 2. Brazos y diferencia exacta

### 2.1 Configuración congelada

| Campo | C | L | P1 |
|---|---:|---:|---:|
| `risk.max_contracts` | 5 | 8 | 5 |
| `risk.max_sl_ticks` | 200 | 300 | 200 |
| `risk.risk_per_trade_pct` | 1,0 | 1,0 | 1,0 |
| `risk.max_trades_per_day` | 3 | 3 | 3 |
| `risk.max_concurrent_positions` | 1 | 1 | 1 |
| `risk.min_stop_or_ratio` | 0,0 | 0,0 | 0,0 |
| `strategy.setup_validity_minutes` | 150 | 210 | 210 |
| `strategy.retest_tolerance_ticks` | 12 | 24 | 24 |
| `strategy.tp_rr` | 3,0 | 2,0 | 3,0 |
| `strategy.entry_reference` | `or_mid` | `or_retracement` | `or_mid` |
| `strategy.entry_trigger` | `close` | `touch` | `close` |
| `execution.fill_model` | `next_open` | `next_open` | `next_open` |
| `mode` | `paper` | `paper` | `paper` |
| `live.live_enabled` | `false` | `false` | `false` |

### 2.2 Diff exacto, tras el override común de feed

Verificado con los tres archivos fuente y un override idéntico de feed,
`mode=paper`, `live.live_enabled=false` y `fill_model=next_open`:

- **C − P1:** solo 2 claves.
  - `strategy.setup_validity_minutes: 150 → 210`
  - `strategy.retest_tolerance_ticks: 12 → 24`
- **C − L:** 7 claves.
  - `risk.max_contracts: 5 → 8`
  - `risk.max_sl_ticks: 200 → 300`
  - `strategy.setup_validity_minutes: 150 → 210`
  - `strategy.retest_tolerance_ticks: 12 → 24`
  - `strategy.tp_rr: 3,0 → 2,0`
  - `strategy.entry_reference: or_mid → or_retracement`
  - `strategy.entry_trigger: close → touch`
- **L − P1:** 5 claves.
  - `risk.max_contracts: 8 → 5`
  - `risk.max_sl_ticks: 300 → 200`
  - `strategy.tp_rr: 2,0 → 3,0`
  - `strategy.entry_reference: or_retracement → or_mid`
  - `strategy.entry_trigger: touch → close`

No hay otras diferencias de estrategia, ejecución, riesgo, ventana, sesión,
cooldown, SMT, ORB o sizing. `or_retracement_pct=0,382` existe en los tres
archivos, pero solo se usa cuando `entry_reference=or_retracement`; no es una
diferencia efectiva para C ni P1.

### 2.3 Lo que NO es un brazo

- La config viva real `profiles/live_8765/config.json` con
  `fill_model=signal_price`: **no es L**. L es un clon con `next_open`; su
  histórico comparable es 1.481,62, no 4.550,66.
- `profiles/backtest_real/config.json` tal cual: contiene 210/24, **no es C**.
  C se reconstruye con el parche 150/12.
- `profiles/p1_forward_control` tal cual: sirve de fuente para P1, pero su
  `feed.csv_path` apunta al path legado `p1_filter025`; se copia/overridea.
- P2, el filtro 0,25, la config de 10 contratos y los planes de exclusión
  horaria: fuera de alcance.

---

## 3. Perfiles: materialización y verificación (fase 0)

No se crea ninguno en este acto. La fase 0 debe materializar **tres perfiles
nuevos e inmutables**, sin editar los existentes:

| Brazo | Perfil nuevo previsto | Fuente | Cambios respecto a la fuente |
|---|---|---|---|
| C | `profiles/fwd_c_original_5_200_150_12/config.json` | `profiles/backtest_real/config.json` | `setup_validity=150`, `retest=12`; feed común; `live=false` |
| L | `profiles/fwd_l_manual_8_300_210_24_next_open/config.json` | `profiles/live_8765/config.json` | solo `fill_model=next_open`; feed común; `live=false` |
| P1 | `profiles/fwd_p1_5_200_210_24/config.json` | `profiles/p1_forward_control/config.json` | feed común; `live=false` |

Hashes de las fuentes (solo lectura, ya verificados):

| Fuente | SHA-256 del archivo |
|---|---|
| `profiles/backtest_real/config.json` | `8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f` |
| `profiles/live_8765/config.json` | `1b981d247b6ca6e828a73782ce016fcfd78a4332bcc932b89e5a17c7d945f81c` |
| `profiles/p1_forward_control/config.json` | `8058b7d7002de547a535a349dbe7f3557e4aaea1e92d392b064dd51b0b8b624b` |
| Original canónica (base+parche) | `87b8b9f18dbce9e4739112cf734850fe75de7e82e7548425d246027d2234e708` |
| P1 canónica | `5527b32cd54353c52968a47fb84471b7012846cefa06413349bcba7085e7e087` |

El hash canónico de L con `next_open` **no existe todavía**; se calcula en
fase 0. No se usa el hash de la config viva con `signal_price` como hash del
brazo.

### 3.1 Override común de feed y ejecución

Los tres perfiles deben compartir exactamente:

```text
mode=paper
live.live_enabled=false
live.broker=none
execution.fill_model=next_open
execution.tick_size=0.25
execution.tick_value=0.50
execution.point_value=2.0
execution.slippage_ticks=1
execution.commission_per_contract_side=0.62
execution.max_slippage_ticks=4
feed.provider=csv
feed.csv_path=data/forward/<WINDOW_ID>/bars_forward.csv
feed.series_mode=raw
feed.exclude_roll_sessions=true
feed.loop_sessions=false
feed.replay_speed=1.0
feed.start_date=""
feed.latency_ms=0
```

El path del CSV es el mismo para los tres; no se permite un feed distinto por
brazo. El CSV no existe todavía.

### 3.2 Verificador obligatorio

Un verificador nuevo (no el `scripts/verify_p1_forward_profiles.py` actual)
debe comprobar, tras el override:

1. `C − P1` = exactamente las 2 claves de frecuencia.
2. `C − L` = exactamente las 7 claves listadas.
3. `L − P1` = exactamente las 5 claves listadas.
4. Los tres tienen `fill_model=next_open`, `live.live_enabled=false`,
   `mode=paper`, `min_stop_or_ratio=0`.
5. Los tres apuntan al mismo `csv_path`, `series_mode=raw`,
   `loop_sessions=false`, `replay_speed=1.0`.
6. Ningún perfil existente cambió de hash.

Si el verificador falla, el forward no se crea.

---

## 4. Arnés: el problema de los tres brazos (fase 0)

El arnés actual es de **dos brazos** y no puede ejecutar este diseño sin
cambios:

| Archivo | Limitación actual |
|---|---|
| `server/forward/paths.py` | `ARM_PORTS = {"control": 8775, "treatment": 8776}`; `validate_arm` solo acepta esos dos. |
| `server/forward/capture.py` | `ARMS = ("control", "treatment")`. |
| `server/forward/autorun.py` | `parse_ports` exige exactamente 2 puertos y que sean 8775/8776. |
| `server/forward/init_window.py` | Impone `max_contracts=5`, `max_sl_ticks=200` a todos los brazos y `min_stop_or_ratio=0,25` al brazo llamado `treatment`; no acepta un perfil base por brazo. |
| `server/forward/panel.py` | Resumen pensado para dos brazos. |

Por tanto, `init_window --arms control,treatment,...` **no** puede crear L
(8/300) ni P1 sin corromper el sizing: el override común los dejaría en
5/200. La fase 0 debe:

1. Hacer configurable la lista de brazos y puertos (sin hardcode 8775/8776).
2. Crear cada brazo desde su propio perfil base, no desde un único base.
3. Eliminar el filtro por nombre de brazo; los tres tienen
   `min_stop_or_ratio=0`.
4. Extender captura, panel y autorun a N brazos.
5. Añadir tests con fixtures sintéticos (sin W1–W6 ni H1).
6. Congelar el hash de código después de los tests; ningún cambio posterior.

**Estado operativo a verificar:** `autorun_state.json` del forward de dos
brazos `2026-12-01_p1_filter025` declara `status=running` con puertos
8775/8776 (actualizado 2026-11-26T16:25:34Z), pero la comprobación de
listeners de este acto **no ve 8775/8776/8778 escuchando**. No se asume que el
forward viejo esté vivo ni que los puertos estén libres: la fase 0 debe
verificar procesos, tareas programadas y puertos antes de decidir. No se para
ni se reinicia desde este pre-registro. Si sigue vivo, hay riesgo de colisión;
si no, igualmente no se reutiliza su ventana ni su captura. La fase 0 debe
elegir puertos libres (por ejemplo 8795/8796/8797 y panel 8798) o detener el
forward viejo con su procedimiento ordenado y autorización explícita.
Modificar `server/forward` mientras el forward viejo corre puede invalidar su
snapshot de código; por tanto, el desarrollo del arnés de tres brazos no debe
desplegarse en caliente.

---

## 5. Datos y captura

### 5.1 Fuente

| Elemento | Valor congelado |
|---|---|
| Proveedor | Databento `GLBX.MDP3` |
| Esquema | `ohlcv-1m` |
| Símbolos | `MNQ`, `NQ`, `ES` |
| Serie | `raw` (no ajustada) |
| Zona | `America/New_York` |
| Sesión | RTH 09:00–15:59 ET; cierre anticipado oficial |
| Contratos | Z26, H27, M27, U27, Z27, H28, M28, U28, Z28, H29, M29, U29, Z29 (39) |
| Rolls | 36; 12 sesiones de roll excluidas |
| Captura | Prospectiva, una sesión por archivo, después del cierre (16:05 ET) |
| Integridad | Append-only, manifiesto por sesión, SHA-256, sin backfill |
| Sintéticos | Prohibidos |
| Ajustados | Prohibidos |

### 5.2 Feed de replay

```text
data/forward/<WINDOW_ID>/bars_forward.csv
```

Construido desde la captura, con los tres símbolos alineados y los mismos
timestamps para los tres brazos. `loop_sessions=false`, `replay_speed=1.0`,
`latency_ms=0`. El CSV no se crea en este acto.

### 5.3 Muestras prohibidas

| Muestra | Fechas | Motivo |
|---|---|---|
| W1–W6 | 2025-01-10 → 2026-06-30 | in-sample; solo motivación/potencia |
| H1 | 2026-07-01 → 2026-10-30 | holdout sellado; no se lee ni se ejecuta |
| 2024 externo | 2024-01-02 → 2024-12-30 | reservado por otra hipótesis |
| Burn-in | 2026-11-23 → 2026-11-30 | solo plomería; excluido |

`data/bars.csv` (ajustado, sha256 `1cc455e9…`) **no** es el feed del forward.
El forward usa la captura raw nueva. H1 sigue `sealed_not_executed`.

### 5.4 Checks de datos antes de T0

- 742 sesiones evaluadas; 12 rolls excluidos; 754 sesiones de calendario.
- Cobertura mensual ≥ 80 %; ningún hueco > 5 sesiones.
- Tres símbolos alineados; sin timestamps duplicados ni barras fuera de RTH.
- ORB 09:00–10:00 completo en cada sesión válida.
- Contratos y rolls exactos; sin sesiones de roll en la muestra.
- Hash del CSV y de cada manifiesto de sesión.
- `series_mode=raw`; cero barras ajustadas, sintéticas o backfilled.
- Reproducibilidad: replay del 10 % dos veces con los mismos `signal_id` y
  operaciones.

---

## 6. Muestra, ventana y mínimos

| Elemento | Valor |
|---|---|
| Ventana | `2026-12-01` → `2029-11-30` |
| Sesiones de calendario | 754 |
| Rolls excluidos | 12 |
| Sesiones evaluadas | 742 |
| Bloques | F1–F6, 122/125/123/125/122/125 sesiones |
| Burn-in | 2026-11-23 → 2026-11-30, excluido |
| Análisis intermedio | prohibido |
| Búsqueda de parámetros | prohibida |

### 6.1 Mínimos de muestra

- ≥ 720 de 742 sesiones evaluadas.
- Ningún mes < 80 % de cobertura; ningún hueco > 5 sesiones.
- ≥ 60 operaciones cerradas **por brazo**.
- ≥ 5/6 bloques con ≥ 6 operaciones por brazo.
- ≥ 5 cortos por brazo; si no, `INCONCLUSO_SHORT`.
- ≥ 12/36 meses con operaciones; máximo 4 meses consecutivos sin operaciones.
- Cualquier falta estructural es `INCONCLUSO` o `ANULA`; no se rellena con
  backfill.

### 6.2 Conteos esperados (estimación de trabajo, no promesa)

Con las tasas W1–W6 (38/362, 46/362, 72/362) sobre 742 sesiones:

| Brazo | Operaciones esperadas |
|---|---:|
| C | 77,9 |
| P1 | 94,3 |
| L | 147,6 |

Los mínimos de 60 por brazo son alcanzables con esas tasas, pero no están
garantizados. Si un brazo no llega a 60, el resultado es `INCONCLUSO`, no se
amplía la ventana ni se mezclan muestras.

---

## 7. Potencia, tamaño muestral y MDE

### 7.1 Estimador, unidades y supuestos

- **Contraste primario:** `L − C` neto USD. **Secundario confirmatorio:**
  `P1 − C`. `L − P1` es descriptivo.
- **Unidad:** sesión. Para cada brazo, `net(s)` es la suma del P&L neto de las
  operaciones cerradas en la sesión `s`; `net(s)=0` si no hay operación.
- **Observable:** `d(s) = net_tratamiento(s) − net_control(s)`, emparejado por
  fecha. El estimando es `Δ = Σ_s d(s)` sobre `N` sesiones; equivalentemente
  `μ = Δ/N` por sesión. El test es sobre el total (o la media), **no** sobre
  operaciones individuales.
- **σ_d:** desviación típica muestral (`ddof=1`) de `d(s)` sobre las 362
  sesiones históricas, incluyendo los ceros. No se eliminan días sin trade.
- **Potencia:** `α=0,05` bilateral, potencia `80 %`, `z_{1-α/2}=1,959964`,
  `z_{1-β}=0,841621`. Fórmulas:

```text
N80 = ((z_{1-α/2} + z_{1-β}) · σ_d / |μ|)^2
MDE_N = (z_{1-α/2} + z_{1-β}) · σ_d · sqrt(N)
```

- **p unilateral:** en la dirección del efecto histórico. `L − C` y `P1 − C`
  usan `H0: Δ ≤ 0`; `L − P1` usa `H0: Δ ≥ 0`. El IC95 % es bilateral.
- **Bootstrap:** 10.000 remuestreos de **sesiones completas** (no de
  operaciones), semilla `20261201`, percentil 2,5/97,5.
- **Reproducibilidad:** todos los números se regeneran con
  `python reports/autoloop/power_forward_3brazos_20261126.py`. La opción
  `--check` compara la tabla de este documento con la salida y falla si no
  coincide al céntimo.

### 7.2 Series persistidas y validación

| Brazo | Fuente | Días con trade | Suma neta |
|---|---|---:|---:|
| C | `improvement_proposals_20261126_1x.json` → `original_next_open` | 38 | 661,44 |
| L | `improvement_proposals_20261126_1x.json` → `live_next_open` | 72 | 1.481,62 |
| P1 | `live_vs_original_mission.json` → `aggregate.p1.daily` | 46 | 1.992,26 |

El calendario de 362 sesiones sale de `_delta_dump_p1_5_200.json`. Las tres
series se alinean por fecha y se rellenan con 0 en los días sin operación:
324 ceros para C, 290 para L y 316 para P1. El script verifica que las sumas
sean exactamente 661,44 / 1.481,62 / 1.992,26 y que ninguna fecha quede fuera
del calendario; si falla, aborta. **No se ejecuta ningún backtest, captura ni
replay:** solo se leen estos artefactos persistidos.

### 7.3 Tabla reproducible

Salida literal del script (bloque delimitado; `--check` lo compara):

<!-- POWER_TABLE_START -->
| Contraste | Δ total (USD) | μ/día (USD) | σ/día (USD) | N80 (sesiones) | Años | MDE a 742 (USD) | IC95 % | p unilateral |
|---|---:|---:|---:|---:|---:|---:|---|---:|
| L − C | +820,18 | +2,265691 | 120,915272 | 22.354,7 | 90,40 | 9.227,56 | [-3.695,94; 5.247,44] | 0,3644 (≤0) |
| P1 − C | +1.330,82 | +3,676298 | 58,989026 | 2.020,8 | 8,17 | 4.501,70 | [-728,64; 3.633,94] | 0,1076 (≤0) |
| L − P1 | -510,64 | -1,410608 | 125,121248 | 61.752,9* | 249,71 | 9.548,54 | [-5.190,38; 4.140,44] | 0,4150 (≥0) |

\* N80 de L − P1 es para detectar |Δ| con dos colas; no es potencia de superioridad de L, cuyo signo histórico es negativo.
<!-- POWER_TABLE_END -->

`N80` es el número **total** de sesiones necesarias para 80 % de potencia;
`MDE a 742` es el efecto total mínimo detectable en la ventana de 742
sesiones (USD), no por sesión. La columna `μ/día` es el efecto histórico por
sesión; `σ/día` es la desviación de la diferencia diaria. `μ` y `σ` se
publican con 6 decimales para que `N80` y `MDE` se reproduzcan con la fórmula
de §7.1; el cálculo usa doble precisión.

### 7.4 Lectura

- A 742 sesiones, el forward solo distingue efectos de **≈ 9,2k USD** (L − C),
  **≈ 4,5k** (P1 − C) o **≈ 9,5k** (L − P1, en valor absoluto). Los deltas
  históricos (0,82k, 1,33k y −0,51k) quedan por debajo del MDE.
- Para el efecto histórico de L − C harían falta ~22.355 sesiones (90 años);
  para P1 − C, ~2.021 sesiones (8,2 años); para L − P1, ~61.753 sesiones
  (250 años) solo para detectar `|Δ|`. La ventana de 36 meses no se elige para
  alcanzar potencia; es el máximo operativo razonable.
- P1 es el contraste con mejor resolución, pero 8,2 años siguen siendo más que
  los 3 años del forward. Ninguno de los tres es confirmatorio a 3 años.
- Un resultado con IC que incluye cero será lo más probable y **no** debe
  interpretarse como “no hay diferencia”: será `INCONCLUSO` por falta de
  resolución.
- **No se alarga la ventana para cazar potencia.** Si se exige 80 % de
  potencia para 820 USD, este forward no debe ejecutarse como confirmatorio.

### 7.5 IC histórico y discrepancias

El IC previo de `L − C` citado en la auditoría de fills
(`[−1.865,60, 3.018,68]`, p ≈ 0,501) **no se reproduce** con la serie diaria
de 362 sesiones. El bootstrap por sesión de este pre-registro, semilla
`20261201`, da:

| Contraste | IC95 % | SE total | p unilateral |
|---|---:|---:|---:|
| L − C | `[-3.695,94; 5.247,44]` | 2.292,57 | 0,3644 (≤0) |
| P1 − C | `[-728,64; 3.633,94]` | 1.107,83 | 0,1076 (≤0) |
| L − P1 | `[-5.190,38; 4.140,44]` | 2.369,28 | 0,4150 (≥0) |

La diferencia con el IC antiguo es **consistente con un cambio de unidad de
remuestreo**: el script fija sesiones completas y no remuestrea operaciones.
Este documento no usa el IC antiguo; fase 0 debe reconciliar el método del IC
antiguo si se quiere citar. El bloque `not_statistically_significant` del lock P1
(`docs/p1_5_200_210_24_forward.lock.json`, p 0,9978, IC
`[−2.708,45, 2.540,14]`) tiene un centro de −84,16, compatible con
`P1 − manual` (−30,68), **no** con `P1 − original` (+1.330,82); tampoco se
hereda. El IC exacto de P1 − C es el de la tabla anterior.

---

## 8. Costes y endpoints

### 8.1 Regímenes

| Régimen | Comisión/lado | Slippage/lado | Tick value | Uso |
|---|---:|---:|---:|---|
| Exacto | 0,62 USD | 1 tick | 0,50 USD | primario |
| Estrés 2× | 1,24 USD | 2 ticks | 0,50 USD | gate de DD |

Ambos regímenes se aplican sobre el mismo dataset, timestamps y brazos. El 2×
no es una estimación: es una corrida de reprecio exacta.

### 8.2 Endpoint primario

```text
Δnet_usd = Σ_sesiones [net_L(s) − net_C(s)]
```

- Unidad: sesión; suma de operaciones cerradas de la sesión; 0 si no hay
  operaciones.
- Bootstrap percentil por sesión, 10.000 réplicas, semilla `20261201`,
  IC95 % bilateral; p unilateral `H0: Δnet ≤ 0`.
- PASS si `Δnet > 0` y el límite inferior del IC95 % (Holm) es `> 0`.
- Se reportan neto, PF, expectancy R, total R, DD USD, RDD, peor racha y
  cobertura por bloque.

### 8.3 Endpoints secundarios

- `Δnet(P1 − C)` con el mismo bootstrap y Holm.
- `Δnet(L − P1)` descriptivo.
- `Δ expectancy R(L − C)` y `Δ expectancy R(P1 − C)`: co-criterio/ apoyo.
- DD, PF, RDD, `drop-best-3`, concentración del mejor trade, participación de
  cortos y meses con operaciones, por brazo y por bloque.

---

## 9. Plan estadístico

1. **Unidad y emparejamiento:** una observación por sesión para cada brazo;
   las tres series se alinean por fecha. Si una sesión falta en un brazo, se
   elimina de los tres (borrado pareado) y se reporta.
2. **Bootstrap:** 10.000 réplicas de sesiones completas (no de operaciones),
   semilla `20261201`, percentil 2,5/97,5; mínimo 9.500 réplicas válidas.
3. **Multiplicidad:** Holm sobre `L − C` y `P1 − C`. `L − P1` no se prueba
   confirmatoriamente.
4. **Bloques:** F1–F6 se reportan; `Δnet > 0` en ≥ 4/6 es informativo, no
   rescata un fallo de DD ni cambia el alfa.
5. **Sin miradas intermedias de eficacia:** solo integridad y operación.
   Cualquier análisis de eficacia antes del final es `ANULA`.
6. **Sin subgrupos de rescate, sin búsqueda de parámetros, sin cambiar la
   ventana.** Un solo análisis final.
7. **Datos faltantes:** no se imputan; si superan los mínimos, `INCONCLUSO`.
8. **Determinismo:** replay del 10 % dos veces; mismos `signal_id` y
   operaciones. Si no, `ANULA`.

---

## 10. Gates de riesgo, calidad y robustez

### 10.1 Drawdown (obligatorio)

```text
DD(L)_exacto  <= 2.000 USD
DD(L)_2x      <= 2.000 USD
DD(P1)_exacto <= 2.000 USD
DD(P1)_2x     <= 2.000 USD
```

El gate se aplica a los candidatos L y P1, no al benchmark C. Si cualquiera
falla, el candidato es `FAIL` aunque el neto sea positivo. No se cambia el
umbral después de ver los resultados.

Valores históricos 1×/2×: C 1.967,82 / 2.064,14; L 2.054,46 / 2.284,92;
P1 1.947,82 / 2.044,14. **L ya incumple el gate a 1× y 2×; P1 lo incumple a
2× por 44,14.** El forward puede confirmar ese fallo; no se rebaja el gate
para hacer pasar a L.

### 10.2 Calidad

- `PF_candidato_exacto ≥ 1,10` y `expectancy_R > 0`.
- `PF_candidato_2x ≥ 1,10` y `net_2x > 0`.
- Para L, además, `Δ expectancy R(L − C) > 0`: si la ventaja en USD
  desaparece al normalizar por riesgo, es sizing, no estrategia.

### 10.3 Robustez

- `drop_best_3_net_candidato > 0`.
- `top_trade_share_gross_candidato ≤ 50 %`.
- `Δnet > 0` en ≥ 4/6 bloques (informativo).
- Candidato opera en ≥ 12/36 meses; máximo 4 meses consecutivos sin
  operaciones.
- `RDD_candidato ≥ RDD_original` (informativo; no sustituye el gate absoluto).

---

## 11. Regla de decisión

| Resultado | Condición | Acción |
|---|---|---|
| **PASS L** | integridad + muestra + E1 (Holm) + R co-criterio + DD exacto/2× + calidad + robustez | habilita un memo de decisión; **no** autoriza LIVE ni cambia el 8765 |
| **PASS P1** | integridad + muestra + E2 (Holm) + DD exacto/2× + calidad + robustez | habilita un memo de decisión; **no** autoriza LIVE |
| **FAIL** | integridad/muestra OK, pero E1/E2, DD o calidad fallan con evidencia clara | se mantiene la config actual; no se promociona |
| **INCONCLUSO** | faltan mínimos, el IC incluye cero sin fallo claro, o faltan cortos | no se promociona; **no se cambia nada** por este forward |
| **ANULA** | se lee H1, hay backfill/sintéticos, cambia código/perfil/feed/lock, o hay más de un análisis | se detiene y se documenta; no se rescata |

- **PASS no es promoción automática.** No cambia `profiles/live_8765`, no
  arranca el 8765, no autoriza broker ni LIVE. Solo habilita una decisión
  posterior con su propio memo.
- Si L y P1 pasan, no hay “ganador automático”; se reportan ambos y decide un
  memo posterior. Para ordenar descriptivamente: más neto, luego menos DD,
  luego más RDD.
- Si L falla por DD y P1 pasa, P1 es el único candidato elegible; si ambos
  fallan, se mantiene la original o se reduce tamaño en un memo aparte.
- El estado por defecto es **no cambiar el 8765**. El forward es un replay
  aislado, no una operación real.

---

## 12. Qué no se mide / limitaciones

- **No hay fills reales de bróker.** El forward usa `next_open` modelado; no
  reproduce la latencia ni el slippage real de la config viva con
  `signal_price`.
- **No hay potencia para los efectos históricos.** El MDE a 742 sesiones es
  9,2k (L − C), 4,5k (P1 − C) y 9,5k (L − P1, en valor absoluto); los deltas
  históricos son 0,82k, 1,33k y −0,51k. Un IC que incluye cero es lo esperado
  y no prueba ausencia de edge.
- **Una sola ventana y un solo régimen.** 2026–2029 no cubre otras crisis ni
  garantiza estacionariedad.
- **Las tres series son exactas a nivel de sesión** (362 sesiones; 38/72/46
  días con trade y el resto ceros). La limitación es la resolución, no la
  serie: P1 no es provisional y no bloquea el lock. Además, las seis sumas
por bloque de P1 coinciden exactamente con W1–W6: 1.700,06; 445,44; −238,40;
1.960,60; −1.240,22; −635,22.
- **El arnés de tres brazos no existe.** El diseño es `can_execute=false`
  hasta que la fase 0 esté implementada y verificada.
- **La ventana se solapa con otros locks.** Solo uno puede ejecutarse sobre
  esta muestra; este plan no es una confirmación independiente de los otros.
- **H1 no se usa.** No se lee, no se ejecuta, no se usa para elegir nada.
- **No se ha ejecutado nada:** ni forward, ni captura, ni replay, ni backtest
  nuevo. La tabla de potencia se calculó desde artefactos ya existentes.

---

## 13. Fase 0: checklist de ejecutabilidad

Nada de esto se hace en este acto. El orden importa:

1. **Verificar el estado real del forward de dos brazos:** su
   `autorun_state` declara `running` en 8775/8776, pero no se observaron
   listeners en 8775/8776/8778. No se toca desde aquí. Antes de modificar
   `server/forward`, el operador debe confirmar que no hay procesos ni tareas
   activas, o aislar el desarrollo; el nuevo plan usará puertos libres.
2. **Extender el arnés a tres brazos** (paths, capture, autorun, init_window,
   panel) y añadir tests sintéticos. Sin tocar 8765.
3. **Materializar los tres perfiles** con el override común y verificar el
   diff exacto (2/7/5 claves). Calcular sus SHA-256 canónicos.
4. **Construir/recibir la captura prospectiva** y verificar los checks de
   datos; generar el CSV forward y su hash.
5. **Verificar la serie diaria exacta de P1** ya persistida en
   `reports/backtest/live_vs_original_mission.json` (`aggregate.p1.daily`):
   46 fechas, suma 1.992,26, alineada con el calendario de 362 sesiones;
   congelar su hash. El script de potencia la valida; no es bloqueante.
6. **Crear la ventana T0** con tres brazos, perfiles, puertos y feed
   congelados; snapshot de código y configuración.
7. **Preflight:** cero H1, cero W1–W6, cero 2024, cero burn-in; 742 sesiones;
   39 contratos; 36 rolls; tres símbolos alineados.
8. **Lock de ejecución one-shot** y runner que rechace muestras prohibidas.
9. **Solo entonces** iniciar captura/replay. Sin captura no hay forward.

Si falta cualquiera de 1–8, el estado sigue `can_execute=false`.

---

## 14. Integridad y guardas

Este acto es solo de diseño:

- No se abrió la DB del 8765; no se escribió en ella.
- No se reinició, paró ni reconfiguró el 8765.
- No se tocó `profiles/live_8765`, `data/config.json` ni H1.
- No se creó ventana, perfil, captura, CSV, DB ni análisis.
- No se ejecutó forward, replay, backtest nuevo ni paper.
- No se modificaron locks ni documentos existentes.
- Los únicos artefactos nuevos están en `reports/autoloop/`.
- El script, este documento, el JSON y el lock se versionan en un commit
  acotado (`cadb6a2`); el repositorio tiene auto-push y lo publicó en
  `origin/main`, sin `git push` manual. La corrección de esta nota va en un
  commit de seguimiento igualmente acotado.

La comprobación final de salud, PID, hashes de config/DB, HEAD y rutas fuera
de `reports/` se hace al cerrar la misión, no dentro del protocolo.

---

## 15. Artefactos y referencias

**Nuevos:**

- `reports/autoloop/PRE_REGISTRO_FORWARD_3BRAZOS_20261126.md` — este protocolo.
- `reports/autoloop/pre_registro_forward_3brazos_20261126.lock.json` — lock.
- `reports/autoloop/power_forward_3brazos_20261126.py` — script reproducible.
- `reports/autoloop/power_forward_3brazos_20261126.json` — salida del script.

**Fuentes (solo lectura):**

- `reports/autoloop/improvement_proposals_20261126_1x.json` — series diarias
  C y L.
- `reports/backtest/live_vs_original_mission.json` — serie diaria exacta de
  P1 (`aggregate.p1.daily`) y agregados C/P1.
- `reports/autoloop/live_manual_vs_original_20261126.json` — agregados y
  bloques C/L/P1.
- `reports/autoloop/_delta_dump_p1_5_200.json` — calendario de 362 sesiones.
- `docs/p1_5_200_210_24_forward.lock.json` — lock P1 de dos brazos; se cita,
  no se edita.
- `docs/FORWARD_ORIGINAL_VS_P1.md` — decisión de brazos original/P1; se cita,
  no se edita.
- `docs/FORWARD_OPERACION.md` — runbook operativo del arnés; se cita, no se
  edita.
- `profiles/backtest_real/config.json`,
  `profiles/live_8765/config.json`,
  `profiles/p1_forward_control/config.json` — fuentes de los perfiles.

**Versionado:** los cuatro artefactos están en `git ls-files`; el commit
inicial es `cadb6a2`. El script se ejecuta con
`python reports/autoloop/power_forward_3brazos_20261126.py --check`.

**Estado final:** `pre_registered_not_executed`, `can_execute=false`. No hay
captura, no hay CSV, no hay ventana, no hay perfil nuevo y no hay análisis.
