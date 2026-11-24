# Experimento pre-registrado E-ATR-1 — stop normalizado por ATR

**Código:** E-ATR-1  
**Versión:** 1.4  
**Fecha:** 2026-11-21  
**Estado:** pre-registrado, **no ejecutado**.  
**Lock:** [`experimento_stop_atr.lock.json`](experimento_stop_atr.lock.json)  
**Módulo de verificación:** [`research/stop_atr.py`](../research/stop_atr.py)

> No se ha ejecutado ningún backtest, no se ha leído una muestra nueva y el holdout
> `2026-07-01 → 2026-10-30` sigue sellado. Este documento no modifica la estrategia activa,
> la configuración viva ni el protocolo v1.2. Un resultado de E-ATR-1 no autoriza paper ni
> live por sí solo.

## 1. Pregunta e hipótesis

**Pregunta.** ¿Un stop normalizado por volatilidad, en lugar del stop estructural anclado al
Opening Range, mejora la esperanza en R cuando el tamaño mantiene el riesgo planificado en el
1 % del equity y el objetivo sigue en 3R?

**H1 (sin cambios).** Un stop normalizado por ATR(14) de 15m, evaluado dentro del mismo tope
de 200 ticks que el control, con sizing que mantiene el riesgo planificado en el 1 % del
equity, un gate de riesgo efectivo al fill tolerante al slippage máximo y objetivo 3R, mejora
la esperanza en R frente al stop estructural sin degradar el perfil de riesgo.

**H0.** La diferencia de esperanza en R es menor o igual a cero, o el tratamiento incumple
una guardia de riesgo o de integridad.

## 2. Brazos y única variable

| Brazo | `strategy.sl_mode` | Stop |
|---|---|---|
| **C — control** | `structural` | Swing de 15m anclado al OR, buffer 4 ticks |
| **T — tratamiento** | `atr` | `entry ∓ 1,2 × ATR(14) de 15m` |

El único override del tratamiento es:

```json
{"strategy": {"sl_mode": "atr"}}
```

Todo lo demás es idéntico: entradas, SMT, retesteo, riesgo, objetivo, costes y motor. En el
código, la rama ATR solo se activa con `sl_mode="atr"`; el camino `structural` no cambia. Las
guardias compartidas —mínimo de 4 ticks y tope de 200 ticks— se aplican a ambos brazos y no
son una segunda variable experimental.

## 3. Configuración congelada

| Grupo | Parámetro | Valor |
|---|---|---:|
| Base | Variante | `full` (ORB + SMT + retesteo) |
| Entrada | `entry_reference` | `or_mid` |
| Entrada | `setup_validity_minutes` | 150 |
| Entrada | `retest_tolerance_ticks` | 12 |
| Entrada | `require_recovery_close` / `entry_trigger` | `true` / `close` |
| Stop | `sl_buffer_ticks` / `structural_depth` | 4 / 3 |
| ATR | `atr_period` / `atr_sl_mult` | 14 / 1,2 |
| Objetivo | `tp_rr` | 3,0 |
| Riesgo | `initial_capital` / `risk_per_trade_pct` | 25.000 USD / 1,0 % |
| Riesgo | `max_contracts` / `max_sl_ticks` | 5 / 200 |
| Riesgo | `max_trades_per_day` / `max_daily_loss_pct` | 3 / 3,0 % |
| Ejecución | `fill_model` | `next_open` |
| Ejecución | `slippage_ticks` / `max_slippage_ticks` | 1 / 4 |
| Ejecución | `commission_per_contract_side` | 0,62 USD |
| Datos | `series_mode` / rolls | `raw` / excluidos |

El volcado completo y el hash están en el lock. Cualquier diferencia entre el lock y
`Settings()` al ejecutar aborta el experimento; no se aproxima la configuración.

## 4. Regla del stop y objetivo

### 4.1 ATR

- Velas de **15 minutos**, periodo **14**, suavizado **Wilder**.
- Ventana causal: solo velas cerradas con `ts + 60 <= entry_ts`; no se usa la vela de entrada
  ni ninguna posterior.
- ATR ausente o cero: se rechaza con `no_stop`; no se cae al stop estructural.

### 4.2 Stop, mínimo y tope compartido

```text
stop_largo = entry - 1,2 × ATR14_15m
stop_corto = entry + 1,2 × ATR14_15m
distancia_minima = max(8 ticks, 0,25 × ATR14_15m)
```

El motor lleva la distancia mínima a 4 ticks si hiciera falta. Si el stop supera
`max_sl_ticks = 200`, la señal se rechaza antes del sizing y antes de calcular el target. El
tope es una guardia de **elegibilidad compartida por C y T**, no un presupuesto de sizing ni
un parámetro del tratamiento: un stop de 300 ticks se rechaza, no se convierte en una
operación de 1 contrato. La tasa de `stop_cap` se reporta; elevarlo o quitarlo exigiría otro
experimento aplicado a ambos brazos.

Los precios de la señal se redondean a **2 decimales**; `stop_ticks` se calcula con
`abs(entry - stop) / tick`. El redondeo no altera la regla del stop.

### 4.3 Target 3R

```text
target = entry + 3,0 × (entry - stop)   # largo
target = entry - 3,0 × (entry - stop)   # corto
```

El target se calcula después del mínimo y del tope, antes del sizing y del fill. No hay
trailing stop ni break-even. El gate de riesgo efectivo no modifica el target. La integridad
verifica la relación 3R con tolerancia de 1 centavo por el redondeo de precios.

## 5. Sizing y riesgo efectivo

```text
risk_budget      = equity × 0,01
per_contract     = stop_ticks × tick_value
qty              = floor(risk_budget / per_contract), limitado a 5
planned_risk     = qty × stop_ticks × tick_value
```

- Si `qty < 1`, no hay operación (`qty_zero`). El riesgo planificado es siempre **≤ 1 %**;
  por contratos enteros puede quedar por debajo y no se compensa.
- El 1 % se refiere al **riesgo planificado en la señal**, no al riesgo efectivo al fill.
- Después del fill se mide:

```text
effective_fill_risk = qty_filled × |fill_price − stop| / tick × tick_value
fill_gate_limit     = equity × 0,01 + qty_filled × max_slippage_ticks × tick_value
gate_passes         = effective_fill_risk ≤ fill_gate_limit + ε
```

La tolerancia usa el slippage máximo configurado, no el observado. Superar el gate es
`integrity_failure`; no se reescribe el riesgo planificado ni se cambia el target. El gate es
de análisis: no liquida la posición ni modifica la regla de salida.

## 6. Muestra y verificación del código

La muestra debe ser externa y nueva: fuera de W1–W6 (`2025-01-10 → 2026-06-30`), fuera del
holdout (`2026-07-01 → 2026-10-30`), real, con universo completo de contratos, serie `raw` y
rolls excluidos. Sus fechas, dataset, contratos y hashes se fijan antes de observar
resultados.

El lock deja `start`, `end`, `source` y `contract_suffixes` vacíos a propósito.
`can_execute = false` y `assert_execution_blocked()` siempre falla. Para ejecutar hace falta
un **lock de ejecución nuevo**, no una edición de este.

### 6.1 Provenance del código ATR

| Archivo | SHA-256 |
|---|---|
| `server/strategy/indicators.py` | `549dfa0d2afe39d09d6196b50902cf42092f942e728631b55e062ccc8e06826a` |
| `server/strategy/strategy.py` | `4150d01cdee8364d14bc34610bb9ac9e4536fbb9a4c6bf3eeb4a13a2177ea628` |

- Algoritmo `sha256-files-v1`: ruta, longitud y contenido de cada archivo completo, en orden
  lexicográfico. Hash combinado:
  `db00b24de78fc51117430fe2b6df75066ed745ab6e9aa21eff0edf28bd31f0d9`.
- Puntos de entrada: `ORBStrategy.evaluate`, `ORBStrategy._stop`, `atr`, `true_range` y
  `aggregate`. Cualquier cambio en esos archivos invalida este pre-registro.

El lock de ejecución debe incluir:

```json
{
  "pre_registration": {
    "path": "docs/experimento_stop_atr.lock.json",
    "payload_sha256": "227af811a4450e1fce598053f777af457c242de63f2ed554bee1c6470ad42bbc",
    "code_provenance_sha256": "db00b24de78fc51117430fe2b6df75066ed745ab6e9aa21eff0edf28bd31f0d9"
  },
  "code_provenance": { "...": "copia exacta del bloque del lock" }
}
```

`verify_execution_lock_provenance()` comprueba el binding, la copia exacta y recalcula los
archivos actuales. No valida la muestra ni autoriza la corrida.

## 7. Análisis y decisión

### 7.1 Endpoint primario

Diferencia pareada de R en entradas comunes, tratamiento menos control:

```text
ΔR_i = R_tratamiento_i - R_control_i
```

Unidad: operación. Dependencia: sesión. Bootstrap de 10.000 remuestras de sesiones completas,
semilla `20261121`, IC percentil 95 %. Positivo si `IC95 inferior > 0`. Las entradas que un
brazo rechaza por `stop_cap`, `qty_zero` u otra guardia no son comunes y se reportan aparte.

### 7.2 Mínimo y guardias

| Condición | Umbral |
|---|---:|
| Entradas comunes / operaciones por brazo | 20 / 20 |
| Sesiones | 60 |
| Profit factor del tratamiento | No inferior al control |
| Drawdown máximo | ≤ control + 500 USD y ≤ 2.500 USD |
| Costes duplicados | Comisión 1,24/lado, slippage 2 ticks, PF ≥ 1,10 |

Integridad obligatoria: ATR positivo y stop según la regla; target 3R; riesgo planificado
≤ 1 %; tope de 200 ticks comprobado antes del sizing; gate de riesgo efectivo; procedencia
del código verificada; sin look-ahead y con las mismas entradas que el control. Cualquier
fallo de integridad invalida el experimento.

### 7.3 Decisión

| Estado | Condición |
|---|---|
| `candidate_for_new_protocol` | IC95 inferior > 0 y todas las guardias e integridad pasan. |
| `rejected` | IC95 superior < 0, o falla una guardia o la integridad. |
| `inconclusive` | No se alcanza el mínimo o el IC incluye cero sin resultado claramente negativo. |

Un `candidate_for_new_protocol` no autoriza paper ni live; solo habilita un protocolo nuevo
con su propia muestra y su propio lock. Un `rejected` no se rescata cambiando ATR, periodo,
objetivo, tope o muestra.

## 8. Estado de ejecución

No se ejecutó nada: no hay corrida, CSV nuevo, métricas ni holdout abierto. Los cambios de
código son la rama ATR condicionada por `sl_mode`, la guardia compartida del tope, la
metadata de riesgo planificado y el gate de análisis. No cambian sizing, target ni salidas
del control.

## 9. Artefactos

- `docs/EXPERIMENTO_STOP_ATR.md` — este pre-registro.
- `docs/experimento_stop_atr.lock.json` — lock, hash y procedencia.
- `research/stop_atr.py` — carga, hashes, gate y bloqueo de ejecución.
- `tests/test_stop_atr_experiment.py` — tests del lock, sizing, stop, target y procedencia.
- `server/strategy/strategy.py` — ATR, tope y target; archivo congelado.
- `server/strategy/indicators.py` — `atr`, `true_range` y `aggregate`; archivo congelado.
