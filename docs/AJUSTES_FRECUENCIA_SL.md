# Ajustes de frecuencia y protección del Stop Loss

Este documento describe los parámetros añadidos para investigar dos objetivos:

1. aumentar la frecuencia de entradas sin romper la estructura ORB + SMT + retesteo;
2. reducir cierres prematuros por Stop Loss.

Son **experimentos de desarrollo**. No modifican la configuración activa del bot, no
ejecutan el holdout y no sustituyen al protocolo pre-registrado de
[`PROTOCOLO_BACKTEST.md`](PROTOCOLO_BACKTEST.md). Cualquier resultado debe compararse
sobre el mismo dataset y con el baseline incluido.

## 1. Entrada: referencias disponibles

`strategy.entry_reference` acepta ahora:

| Valor | Nivel de referencia (larga) | Nivel de referencia (corta) |
|---|---|---|
| `or_mid` | `MID = (ORH + ORL) / 2` | `MID` |
| `or_retracement` | `ORH − pct × (ORH − ORL)` | `ORL + pct × (ORH − ORL)` |
| `breakout_level` | `ORH` | `ORL` |
| `half_leg` | 50% de la pierna de ruptura | 50% de la pierna de ruptura |
| `none` | Entrada directa al confirmar la ruptura | Igual |

El nuevo parámetro `strategy.or_retracement_pct` define `pct` y admite valores entre
`0.10` y `0.49`. Los presets usan `0.30` (30%) y `0.382` (38.2%), que son retrocesos
más superficiales que el 50% y, por tanto, deberían producir más toques y entradas.
`0.50` se evita a propósito porque equivale a `or_mid`; para ese caso se usa `or_mid`.

La tolerancia del retesteo sigue siendo `strategy.retest_tolerance_ticks` y se mide
desde el nivel de referencia. `breakout_level` no cambia la definición de la ruptura:
solo cambia dónde se espera el retroceso.

## 2. Parámetros de frecuencia

| Parámetro | Default | Rango útil | Efecto esperado |
|---|---:|---:|---|
| `strategy.entry_reference` | `or_mid` | ver tabla | Niveles más superficiales → más entradas; menos confirmación. |
| `strategy.or_retracement_pct` | `0.382` | 0.10–0.49 | Menor `pct` → entrada más cerca de ORH/ORL → más frecuencia. |
| `smt.window_minutes` | `60` | 90–120 | Más pivotes previos elegibles → más divergencias, también más antiguas. |
| `smt.tolerance_ticks` | `8` | 12–16 | Menos invalidaciones por ruido del ES; riesgo de aceptar divergencias débiles. |
| `strategy.setup_validity_minutes` | `150` | 180–240 | Más tiempo para que SMT y retesteo se completen; entradas más tardías. |

No se modifican `confirm_tf=15m`, `require_close_breakout`, la SMT de 1 minuto con
pivotes de 5 velas, la recuperación del nivel barrido (`smt.require_recovery`), el
bloqueo de reentradas tras falso rompimiento ni el filtro `min_range_ticks`.

## 3. Parámetros de protección del Stop Loss

| Parámetro | Default | Rango útil | Efecto esperado |
|---|---:|---:|---|
| `strategy.structural_depth` | `3` | 5–6 | Swing más profundo → SL detrás de estructura más sólida; stop más ancho y menor qty. |
| `strategy.sl_buffer_ticks` | `4` | 8–12 | Más margen para barridos, spread y slippage; stop más ancho. |
| `strategy.require_recovery_close` | `true` | `true`/`false` | `false` acepta rechazo dentro de tolerancia sin vela de recuperación. |
| `strategy.tp_rr` | `3.0` | 2.0 / 2.5 | Objetivos más cercanos → más TP, pero menor R por acierto. |
| `risk.max_sl_ticks` | `200` | 200–600 (experimento) | Tope duro: si el stop lo supera, se rechaza antes de dimensionar. |

El tamaño de posición no se fuerza: se recalcula con
`riesgo_por_contrato = |entry − stop| / tick × tick_value`, por lo que un stop más
ancho reduce contratos para mantener el mismo riesgo porcentual. Si el stop resultante
supera `risk.max_sl_ticks` (200 por defecto), la señal se rechaza y el embudo lo registra
como `stop_cap`. Si el stop es tan ancho que el presupuesto de riesgo no alcanza para un
contrato, el riesgo también devuelve `qty=0`.

Por eso un preset de stop profundo o de entrada directa puede mostrar **0 operaciones**.
No es un fallo del preset: es la señal de que el stop estructural no es financiable con
el capital, el riesgo por operación y el tope de SL actuales.

### Tope de stop y presupuesto de riesgo (qty=0)

El tope y el presupuesto son restricciones distintas y el backtest las reporta por
separado:

1. **Tope de stop (`risk.max_sl_ticks`)**: si `stop_ticks > max_sl_ticks`, la estrategia
   rechaza la señal antes de dimensionar. Se cuenta en `stop_cap_sessions`.
2. **Presupuesto de riesgo (`risk.risk_per_trade_pct`)**: si el stop cabe en el tope pero
   `floor(equity × riesgo% / (stop_ticks × tick_value)) < 1`, el riesgo rechaza la señal
   con `qty=0` y motivo `Capital/riesgo insuficiente`. Se cuenta en
   `qty_zero_sessions`. Ambas métricas son por sesión, no por señal; una misma sesión
   puede aparecer en las dos si tuvo señales con ambos problemas.

Con `initial_capital=25.000`, `risk_per_trade_pct=1.0` y `tick_value=0.50`, el presupuesto
es 250 USD por operación y el límite de financiación es `stop_ticks > 500`. Con el tope
habitual de 200 esas señales ni siquiera llegan al dimensionamiento. Por eso un preset
profundo puede mostrar 0 trades por dos causas distintas: `stop_cap_sessions > 0` o
`qty_zero_sessions > 0`.

El preset de control `sl_cap_600` sube solo `max_sl_ticks` a 600 y no cambia
`risk_per_trade_pct` (1% en el perfil por defecto): los stops de 201–500 ticks se vuelven
financiables, los de 501–600 aparecen como `qty=0` y los de más de 600 siguen como
`stop_cap`. No es una recomendación de riesgo; es un instrumento para separar ambas
restricciones sin tocar la configuración activa.

### Cierre de recuperación

Con `require_recovery_close=true` se exige una vela posterior al toque que cierre de
vuelta sobre el nivel (con el buffer de ruptura). Con `false`, el rechazo dentro de la
tolerancia es suficiente:

- `entry_trigger="close"` usa el cierre de la vela del toque;
- `entry_trigger="touch"` usa ese mismo cierre como referencia y ejecuta en la apertura
  siguiente; no simula un llenado instantáneo en el nivel.

El flag es independiente de `entry_trigger`: desactivarlo no cambia la definición del
toque ni la tolerancia, solo elimina la espera de confirmación.

## 4. Presets de comparación

El catálogo vive en `server/backtest.py` (`PRESETS`). Cada preset es un patch parcial
sobre la configuración activa y se ejecuta sobre el **mismo dataset** que el baseline.
El baseline se añade siempre para calcular deltas.

Presets incluidos:

| Grupo | Presets |
|---|---|
| Base | `baseline` |
| Frecuencia | `entry_breakout_direct`, `entry_or_level`, `entry_retrace_30`, `entry_retrace_382`, `smt_window_90`, `smt_window_120`, `smt_tolerance_12`, `smt_tolerance_16`, `retest_tolerance_24`, `retest_tolerance_40`, `setup_validity_180`, `setup_validity_240` |
| Stop | `sl_depth_5`, `sl_depth_6`, `sl_buffer_8`, `sl_buffer_12`, `recovery_off` |
| Riesgo | `sl_cap_600` (control de `max_sl_ticks`) |
| Objetivo | `rr_2`, `rr_2_5` |
| Combinado | `direct_sl_cap_600`, `deep_stop_sl_cap_600`, `combo_requested` (exploratorio, no confirmatorio) |

Los presets de riesgo no forman parte de la ejecución default; se piden explícitamente.
`sl_cap_600` solo cambia `risk.max_sl_ticks`; los combinados añaden la entrada directa o
el stop profundo, pero mantienen `risk_per_trade_pct`, `max_contracts` e
`initial_capital`.

Los presets no tocan las reglas protegidas: `confirm_tf`, `require_close_breakout`,
`allow_reentry_after_false_breakout`, `min_range_ticks`, `use_smt`, `smt.enabled`,
`smt.pivot_depth`, `smt.detect_tf`, `smt.require_recovery`, ni el horario del OR.

La continuación tendencial sin retesteo fue **retirada** del código, los presets y
la UI tras la comparación W1–W6: añadía 109 operaciones, empeoraba el PF de 1,13 a
0,91 y elevaba los Stop Loss al 70,8%. El detalle histórico está en
[`CONTINUACION_TENDENCIAL.md`](../reports/backtest/CONTINUACION_TENDENCIAL.md).

## 5. Cómo ejecutar la comparación

CLI, sin arrancar el servidor:

```bash
# Presets default sobre las últimas 20 sesiones reales
python -m server.backtest --days 20

# Selección aislada; el baseline se añade automáticamente
python -m server.backtest --days 20 \
  --preset entry_retrace_382 --preset sl_buffer_12 --preset recovery_off

# Control de tope: entrada directa y stop profundo con max_sl_ticks=600
python -m server.backtest --days 20 \
  --preset sl_cap_600 --preset direct_sl_cap_600 --preset deep_stop_sl_cap_600

# Catálogo completo (más lento)
python -m server.backtest --days 20 --all --out reports/backtest/presets_full.json

# Incluir trades, funnel y curvas completas
python -m server.backtest --days 20 --full --out reports/backtest/presets_full.json
```

El JSON de salida incluye `comparison` con, por preset: operaciones, señales,
retesteos, win rate, profit factor, expectancy, neto, drawdown, `stop_losses`,
`stop_loss_rate`, `avg_stop_ticks`, `stop_cap_sessions`, `qty_zero_sessions`, R medio,
Sharpe/Sortino y curva de equity. También incluye `delta` frente al baseline.

API, con el servidor arrancado:

```bash
curl http://127.0.0.1:8765/api/backtest/presets

curl -X POST http://127.0.0.1:8765/api/backtest/presets \
  -H "Content-Type: application/json" \
  -d '{"days":20,"presets":["entry_retrace_382","sl_depth_6","sl_buffer_12"]}'
```

La API devuelve la tabla compacta, no los trades individuales. La configuración activa
del motor no se modifica.

## 6. Lectura de resultados

Para decidir si un ajuste merece pasar a una siguiente fase, comparar contra baseline:

- **Frecuencia:** `trades`, `signals` y `retests`. Más entradas no es mejor por sí solo.
- **Calidad:** win rate, profit factor, expectancy y R medio.
- **Riesgo:** drawdown absoluto/porcentual, peor racha y `stop_loss_rate`.
- **Protección del SL:** `stop_losses` y `avg_stop_ticks`; un stop más ancho debe reducir
  cierres prematuros, no solo desplazar la pérdida. Si aparecen 0 trades, distingue
  `stop_cap_sessions` (superó el tope) de `qty_zero_sessions` (pasó el tope pero el
  presupuesto no alcanza para un contrato).
- **Curva:** forma de `equity`, no solo el resultado final.

No se debe elegir el preset con mejor resultado in-sample y presentarlo como validado.
Cualquier promoción requiere un protocolo nuevo con su propio holdout; el holdout
actual permanece sellado.
