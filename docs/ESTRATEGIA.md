# Especificación matemática de la estrategia

Todas las decisiones se calculan con velas **ya cerradas**. El motor evalúa en cada vela
de 1 minuto cerrada y ejecuta en la apertura de la siguiente (modelo `next_open`).

## 0. Convenciones

- Zona horaria: `America/New_York` (IANA). El cambio de horario es automático; no se usan
  offsets fijos.
- `tick = 0.25` puntos, `tick_value = 0.50 USD`, `point_value = 2.00 USD` para MNQ.
- `t0` = inicio del Opening Range, `t1` = fin. Por defecto 09:00–10:00 ET.
- Precios redondeados al tick para que los niveles sean operables.

## 1. Opening Range (Fase A)

Con las velas de 1 minuto cuyo **inicio** cae en `[t0, t1)`:

```
ORH = max(high)
ORL = min(low)
W   = ORH - ORL
MID = (ORH + ORL) / 2
W%  = W / close_última_vela_del_rango × 100
```

- El rango se **congela** cuando llega la primera vela con `ts >= t1`; no se recalcula después.
- Se rechaza la sesión si `W% > max_width_pct` (filtro de volatilidad) o si
  `W < min_range_ticks × tick`.
- No se usan velas posteriores a `t1` para construir el rango.

## 2. Ruptura (Fase B)

Sobre velas agregadas a la temporalidad de confirmación (`confirm_tf`, por defecto 15m),
considerando solo las que cierran después de `t1`:

```
buffer = breakout_buffer_ticks × tick
Larga  si close > ORH + buffer
Corta  si close < ORL - buffer
```

- Si `require_close_breakout = true` (por defecto), una vela que solo perfora con la mecha
  se registra como **ruptura por mecha** y no genera señal.
- La primera vela de confirmación que rompe fija `breakout_ts` y el nivel de referencia.
- **Falso rompimiento:** si después de la ruptura una vela de confirmación cierra de vuelta
  más allá del extremo opuesto (larga: `close < ORL - buffer`; corta: `close > ORH + buffer`),
  el setup se marca rechazado y no se opera ese día (salvo que se habilite la reentrada).
- El setup expira a los `setup_validity_minutes` desde el cierre de la vela de ruptura.

## 3. Divergencia SMT (Fase C)

### 3.1 Pivotes sin repintado

Para una profundidad `d`:

```
pivote_low(i)  ⇔ low[i] < low[i−k]  ∀ k=1..d  y  low[i] ≤ low[i+k] ∀ k=1..d
pivote_high(i) ⇔ high[i] > high[i−k] ∀ k=1..d  y  high[i] ≥ high[i+k] ∀ k=1..d
```

El pivote **solo existe** en `i + d` (confirmación). El detector nunca lee índices
posteriores a la vela evaluada; por eso no hay repainting ni look-ahead.

### 3.2 Divergencia alcista

1. El NQ hace un mínimo `p2` más bajo que un mínimo estructural previo `p1`:
   `p2.price < p1.price − min_break`.
2. `p1` se elige como el mínimo más bajo entre los pivotes previos dentro de
   `window_minutes` (extremo estructural relevante), no el pivote inmediatamente anterior.
3. En la ventana de swing del pivote (`±d` velas) se mide el mínimo del ES:
   `ref1 = min(low_ES)` alrededor de `p1`, `ref2 = min(low_ES)` alrededor de `p2`.
4. El ES **no** rompe su mínimo equivalente:
   `ref2 ≥ ref1 − tolerance_ticks × tick`.
5. Se exige, si `require_recovery`, que alguna vela posterior cierre por encima de
   `p1.price + buffer` (recuperación del nivel barrido).

### 3.3 Divergencia bajista

Espejo: `p2.price > p1.price + min_break`, `p1` es el máximo más alto previo,
`ref2 ≤ ref1 + tolerance` y recuperación con cierre por debajo de `p1.price − buffer`.

> La variante bajista está implementada y puede compararse en el backtest, pero **no está
> validada estadísticamente** con datos reales. No debe asumirse equivalente a la alcista.

### 3.4 Selección y validez

Una sesión puede contener varias divergencias. La estrategia elige:

- la **última confirmada antes de la ruptura**;
- si la SMT aparece después de la ruptura, la **primera posterior**.

Caduca a los `validity_minutes` desde la confirmación del pivote. Una divergencia de sesgo
contrario a la ruptura bloquea el setup.

## 4. Retesteo y entrada (Fase D)

`entry_reference` define el nivel de referencia:

| Variante | Fórmula | Nombre en UI |
|---|---|---|
| `or_mid` (por defecto) | `(ORH + ORL) / 2` | 50% del Opening Range |
| `or_retracement` | Larga: `ORH − pct × W`; corta: `ORL + pct × W` | Retroceso superficial (30%–38.2%) |
| `breakout_level` | `ORH` en largas, `ORL` en cortas | Nivel de ruptura |
| `half_leg` | Larga: `ORH + 0.5 × (máx_high_desde_ruptura − ORH)`; corta: simétrico con el mínimo | 50% de la pierna |
| `none` | Entrada directa al cierre de ruptura | Sin retesteo |

> **Sobre el “50 % del rango” del vídeo de referencia:** no se dispone del vídeo en este
> repositorio, así que no es posible demostrar que el autor se refería exactamente al punto
> medio. Por eso el valor predeterminado es la hipótesis matemáticamente explícita
> `MID = (ORH + ORL)/2`, y se ofrecen `breakout_level` y `half_leg` como variantes
> configurables para reproducir la metodología original y compararlas con backtests.

Condiciones:

```
tolerancia = retest_tolerance_ticks × tick
Toque (larga)  ⇔ low ≤ referencia + tolerancia, después de la vela de ruptura
Toque (corta)  ⇔ high ≥ referencia − tolerancia
Recuperación   ⇔ close ≥ referencia + buffer  (larga; espejo en corta)
```

`require_recovery_close=false` elimina la exigencia de la vela de recuperación: se acepta
el rechazo dentro de la tolerancia. Con `entry_trigger = close` se usa el cierre de la vela
del toque; con `touch`, también se usa ese cierre como precio de referencia. Si
`require_recovery_close=true`, con `entry_trigger = close` la entrada se marca al cierre de
la vela de recuperación; con `touch` se conserva la recuperación como confirmación, pero
la referencia sigue siendo el cierre de la vela del toque. La orden se ejecuta en la
apertura de la vela siguiente, con slippage adverso de
`min(slippage_ticks, max_slippage_ticks)`.

## 5. Stop Loss y Take Profit (Fase E)

Distancia mínima de stop: `max(8 ticks, 0.25 × ATR)`.

| `sl_mode` | Larga | Corta |
|---|---|---|
| `structural` (defecto) | `min(último swing low 15m, MID) − buffer` | `max(último swing high 15m, MID) + buffer` |
| `or_mid` | `MID − buffer` | `MID + buffer` |
| `atr` | `entry − atr_sl_mult × ATR` | `entry + atr_sl_mult × ATR` |

Si `sl_mode = "atr"` y el ATR no está disponible o es cero, la señal se rechaza con
`no_stop`; no se cae al stop estructural. Los swings se buscan en velas de la temporalidad de confirmación con profundidad
`structural_depth` (3 por defecto; 5–6 para estructura más sólida), solo con información
disponible antes de la entrada. El buffer `sl_buffer_ticks` separa el stop de la estructura
(4 por defecto; 8–12 para absorber barridos de liquidez).

```
riesgo_por_contrato = |entry − stop| / tick × tick_value
qty = floor(equity × risk_pct / riesgo_por_contrato), limitado por max_contracts
TP  = entry + R × (entry − stop)   (larga; espejo en corta)
```

El tamaño usa el **precio efectivo de ejecución** (con slippage), no el precio teórico de
la señal. Si el stop supera `max_sl_ticks`, la señal se rechaza. Si cabe en el tope pero el
presupuesto de riesgo no alcanza para un contrato, el riesgo devuelve `qty=0`; el backtest
lo reporta como `qty_zero_sessions`, separado de `stop_cap_sessions`.

## 6. Gestión y salidas

- SL y TP se supervisan con cada vela de 1 minuto.
- **Stop market con gap al open:** si la vela abre más allá del stop, el fill es al open
  (más slippage adverso), no al nivel teórico del stop. Si abre dentro y perfora el stop
  intrabar, se usa el stop.
- **Take profit con slippage adverso:** un TP largo se ejecuta en `target − slippage`; uno
  corto en `target + slippage`. Un gap favorable al open se respeta como mejora de precio.
- `slippage_ticks` es el slippage solicitado; `max_slippage_ticks` lo acota. Ambos se aplican
  también a la entrada. Un valor máximo de 0 elimina el slippage del modelo.
- Si una misma vela toca ambos niveles, se asume el **peor caso**: SL primero. La vela queda
  registrada en `diagnostics.ambiguous_bars` con OHLC, niveles, gap, resolución y P&L; el
  backtest no inventa una secuencia intrabar que no puede observar.
- Se registran **MFE/MAE** por operación en R (MAE negativo) y en USD, además del **drawdown
  abierto**: máximo retroceso del P&L no realizado desde su pico mientras la posición estuvo
  abierta. En el agregado se publican medias y el máximo.
- Al cerrar: `gross = (exit − entry) × point_value × qty` (signo según dirección),
  `fees = comisión_lado × 2 × qty`, `pnl = gross − fees`.
- `R = (exit − entry) / |entry − stop_inicial|` (con signo).
- Cierre forzado a `session_close_time` si `close_at_session_end`.
- Un máximo de operaciones diarias, cooldown, límite de pérdida y parada de emergencia
  bloquean nuevas entradas. Nunca se aumenta el riesgo para recuperar pérdidas.

## 7. Garantías anti-sesgo

1. La estrategia es una función determinista de las velas cerradas recibidas.
2. Los pivotes se confirman `d` velas después y el detector no lee el futuro.
3. El OR se congela al cerrar la ventana.
4. La SMT se elige con `confirm_ts` y se compara con el `breakout_ts`.
5. El backtest reutiliza la misma clase de estrategia y el mismo ejecutor que el modo paper.
6. No se usan datos sintéticos para presentar resultados como reales: el campo
   `data_source` y la UI lo indican.
