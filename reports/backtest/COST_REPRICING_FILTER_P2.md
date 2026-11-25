# Reprecio exacto de costes — filtro 0,25 y P2

**Estado:** diseño. **No ejecutado.** No se ha lanzado ningún backtest, no se ha
creado el artefacto de reprecio, no se ha modificado la configuración viva, el
filtro, sus umbrales, la DB ni el holdout.

**Alcance:** W1–W6, `2025-01-10 → 2026-06-30`, 362 sesiones. Holdout H1
`2026-07-01 → 2026-10-30` **sellado y no leído**.

**Objetivo:** definir cómo obtener un reprecio **exacto**, no una estimación
uniforme, para P2 y para el filtro 0,25 con:

- comisión `1,24 USD` por contrato y lado;
- slippage `2 ticks` por lado;
- `max_slippage_ticks=4`, por lo que el shock de 2 no queda truncado;
- las mismas señales, ventanas, dataset, motor y configuración, cambiando solo
  las dos claves de ejecución.

**Decisión clave:** el reprecio se hace **reejecutando el motor**. No se
recalcula el P&L de los trades ya guardados restando una cantidad fija. El
slippage altera el precio de entrada, el stop efectivo, el denominador de R, la
curva de equity y posiblemente la qty o la secuencia de fills. Una resta sobre
el listado histórico sería una aproximación, no evidencia P6.

---

## 1. P6: qué se evalúa y qué no

P6 es el gate de costes del **filtro 0,25**:

```text
P6_COST_STRESS:
  mean_r_accepted > 0
  AND r_profit_factor_accepted >= 1,10
```

- `mean_r_accepted` es la media de `r_multiple` de las operaciones aceptadas por
  el filtro, con los fills repreciados.
- `r_profit_factor_accepted` es la suma de R positivas dividida por el valor
  absoluto de la suma de R negativas, en el mismo cohorte.
- P6 **no** es un gate de P2. P2 es el control obligatorio del reprecio; no se
  crea un “P6 de P2”.
- Un PASS de P6 no promociona el filtro: el resultado global sigue dependiendo
  de los demás gates. Hoy el global es `INCONCLUSO`.
- La estimación uniforme de `−100,80 USD` no es evidencia P6. El
  `stress_costs.json` del original (`38` trades, `347,38 USD`, PF `1,07`) es una
  referencia de método, no un resultado del filtro ni de P2.

**Estado actual:** `P6_COST_STRESS = NO_EVALUABLE`. Este documento no cambia ese
estado; define qué haría falta para evaluarlo. El evaluador actual
(`filter025_gates.py`) hardcodea ese estado y `filter025_gates.config.json`
tiene `cost_stress.artifact=null`: una implementación posterior tendría que
enseñarle a leer y validar el artefacto. Ese cambio no forma parte de este
diseño y no se ejecuta aquí.

---

## 2. Por qué hace falta reejecutar

El motor aplica el slippage de forma adversa y dependiente del camino:

- entrada con `fill_model="next_open"`: el fill parte del open de la vela
  siguiente, no del precio de la señal;
- stop: usa el stop o el open si hay gap, más slippage adverso;
- target: usa el target menos slippage adverso; si hay gap favorable, usa el
  open sin slippage;
- cierre de sesión: usa el cierre de la última vela, sin un slippage adicional
  en `close()`;
- comisión: se carga por lado y por contrato al cerrar;
- R: se calcula con la distancia entre el fill real y el stop inicial, no con el
  stop teórico de la señal.

Por eso, un trade puede cambiar de precio, de R, de qty o de razón de salida.
El filtro se decide antes de la entrada con `stop_ticks / orb_width_ticks`; el
conjunto aceptado debería seguir siendo el mismo, pero eso debe **comprobarse**
en el reprecio. Si cambia, P6 no es comparable y queda `INCONCLUSO`.

La validación de método es reproducible: el baseline original con costes
combinados de `COST_SENSITIVITY_PRESETS.md` da `347,38 USD`, exactamente el
mismo neto que `stress_costs.json` con `38` operaciones. Ese artefacto no se
reutiliza para el filtro ni para P2.

---

## 3. Brazos congelados

| ID | Perfil | `min_stop_or_ratio` | Comisión/lado | Slippage | Rol |
|---|---|---:|---:|---:|---|
| `P2_BASE` | `profiles/p2_freq/config.json` | 0,00 | 0,62 | 1 tick | Control base P2 |
| `P2_STRESS` | mismo perfil | 0,00 | **1,24** | **2 ticks** | Control de costes P2 |
| `F_BASE` | mismo perfil | **0,25** | 0,62 | 1 tick | Filtro base |
| `F_STRESS` | mismo perfil | **0,25** | **1,24** | **2 ticks** | Brazo P6 |

- `P2_BASE` y `P2_STRESS` solo difieren en `execution.commission_per_contract_side`
  y `execution.slippage_ticks`.
- `F_BASE` y `F_STRESS` solo difieren en esas mismas dos claves.
- `P2_BASE` → `F_BASE` solo difiere en `risk.min_stop_or_ratio: 0,00 → 0,25`.
- No se cambia `max_contracts` (10), `max_sl_ticks` (200), `setup_validity_minutes`
  (210), `retest_tolerance_ticks` (24), `tp_rr`, ORB, SMT, feed, fill model,
  `max_slippage_ticks` ni `live.live_enabled`.
- No se usa el brazo `filter025_max5` como brazo principal: es una comprobación
  de invariancia del artefacto histórico. El brazo canónico es max10; si se
  incluye max5, se reporta aparte y no sustituye a `F_STRESS`.
- No se activa ningún filtro en `P2_BASE` o `P2_STRESS`.

### 3.1 Hashes de referencia

| Elemento | SHA-256 |
|---|---|
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `profiles/p2_freq/config.json` | `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb` |
| `data/bars.csv` | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` |
| `reports/backtest/p2_w1_w6_confirm.json` | `3b2d654a6298b181c0ad1161a038e7f8f95eaa70de26c211f2e3d2f82b9e9312` |
| `reports/backtest/_manual_filter025_w1_w6.json` | `193a2bc1ab9885eb55ee988ca082cf51ed2975ca15f6c1421605d379c723aca7` |
| `reports/backtest/filter025_gates.config.json` | `793911a4dc8b02794121f5b562faf207932d1628c155a309d51b18a9f6fbc852` |
| `reports/backtest/filter025_gates.json` | `66cf5ce0dabf1ab0b646a6809f8adee4c991d1f5e4f7211f79cdea0e07f6ee5b` |
| `reports/backtest/stress_costs.json` | `bfd50c4e07b7649da4ac92a7969df54bcfccb40e91cb1039ec7b26a07405de6d` |

El dataset tiene `38.312.629` bytes y el hash coincide con
`reports/backtest/dataset_sha256.txt`. La ejecución debe volver a calcular estos
hashes; si alguno cambió, el diseño no se ejecuta.

### 3.2 Código de referencia

El runner de reprecio debe registrar el SHA-256 de todos los archivos que
intervienen. Como mínimo:

```text
server/backtest.py
server/execution.py
server/stats.py
reports/backtest/_manual_common.py
reports/backtest/_windows.py
reports/backtest/_p2_w1_w6_confirm.py
reports/backtest/_manual_filter025_w1_w6.py
<runner nuevo de reprecio>
```

Hashes actuales de referencia:

```text
server/backtest.py                          d138b45790d93d57e3242e479f71860b1bc552a1255545ac6625f65f151b11ac
server/execution.py                         05cbf7ae6c630a69128c2f0f34ed720f97e012c78c7a69bc1031d1a21ad5f50b
server/stats.py                             83528d0386c7644db3185fffca5bdfe9e3fde908f6767f92013d04b234749a62
reports/backtest/_manual_common.py          1a8b48d8116220ca85e3ecde5d908147f0932b3f1a2b1ff1749cf7b14501734c
reports/backtest/_windows.py                e2996372685e7efa1942a4a182f9f5698ab845f57c382a51b44f80a95b2752ed
reports/backtest/_p2_w1_w6_confirm.py       710d4bcd8f8e5c2b4cb03eeb522deba4dc51aff164cb569c47a24bbc691cea47
reports/backtest/_manual_filter025_w1_w6.py c98767375d65e3eb45f42ebdff899fb38ec75b72331c4dffd9eaef25fff9d5c2
```

Un cambio en cualquiera de estos archivos, o en el runner, exige un nuevo
diseño/hash antes de ejecutar.

---

## 4. Modelo exacto de costes

### 4.1 Parámetros

```text
execution.tick_size                    = 0,25
execution.tick_value                   = 0,50 USD
execution.point_value                  = 2,00 USD
execution.commission_per_contract_side = 1,24 USD
execution.slippage_ticks               = 2
execution.max_slippage_ticks           = 4
execution.fill_model                   = next_open
execution.simulate_partial_fills       = false
```

`1,24/lado` es por contrato y por lado, no por operación completa. Para una
operación de ida y vuelta con `q` contratos:

```text
comisión_round_trip = 1,24 × q × 2
slippage_2_ticks_por_lado = q × 2 × 0,50 = q × 1,00 USD
coste_teórico_round_trip = q × (2,48 + 2,00) = q × 4,48 USD
```

Ese `4,48` por contrato es una **referencia aritmética**, no una resta que se
aplique al P&L histórico. El resultado exacto sale del motor porque el slippage
puede cambiar el camino y porque los gaps favorables de target no llevan
slippage adverso.

### 4.2 Reglas de fill que debe reproducir el motor

Para `next_open`, con `slip_ticks = min(2, 4) = 2` y `slip = 2 × 0,25 = 0,50`:

- **Entrada larga:** `round_to_tick(open + 0,50)`.
- **Entrada corta:** `round_to_tick(open - 0,50)`.
- **Stop largo:** `round_to_tick(stop - 0,50)`; si hay gap, `round_to_tick(open - 0,50)`.
- **Stop corto:** `round_to_tick(stop + 0,50)`; si hay gap, `round_to_tick(open + 0,50)`.
- **Target largo:** `round_to_tick(target - 0,50)`; si hay gap favorable, `round_to_tick(open)`.
- **Target corto:** `round_to_tick(target + 0,50)`; si hay gap favorable, `round_to_tick(open)`.
- **Cierre de sesión:** último cierre de la sesión, sin slippage adicional en
  `close()`; la comisión sí se aplica.

El diseño no inventa un slippage para el cierre de sesión ni para el gap
favorable de target. Esas reglas son parte del motor y deben quedar en el
artefacto mediante `entry_price`, `exit_price`, `exit_reason` y `gap_*`.

### 4.3 Contabilidad por trade

Para cada trade repreciado:

```text
gross_long  = (exit_price - entry_price) × point_value × qty
gross_short = (entry_price - exit_price) × point_value × qty
fees        = 1,24 × 2 × qty          # sin parciales; si hay parciales, por fill/lado
net         = gross - fees
R           = (exit_price - entry_price) × signo / |entry_price - initial_stop|
```

- `risk_amount` es el riesgo efectivo al fill, no el planificado de la señal.
- `r_multiple` se toma del motor (redondeo a 2 decimales); no se recalcula con
  el stop teórico.
- Si se habilitan parciales o cambios de qty, la comisión se cuenta por cada
  fill y el diseño debe reabrirse; el brazo congelado no los usa.

### 4.4 Lo que no es exacto

- Restar `4,48 × qty` al P&L del trade histórico.
- Aplicar 2 ticks solo a la entrada y no a la salida, o al revés.
- Aplicar slippage al cierre de sesión o a un gap favorable de target.
- Suponer que la qty, el stop o la secuencia de trades no cambian.
- Reutilizar `stress_costs.json` del original como si fuera el filtro o P2.

---

## 5. Muestra y ejecución

### 5.1 Muestra

- W1: `2025-01-10 → 2025-03-31`, 54 sesiones.
- W2: `2025-04-01 → 2025-06-30`, 61.
- W3: `2025-07-01 → 2025-09-30`, 63.
- W4: `2025-10-01 → 2025-12-31`, 63.
- W5: `2026-01-01 → 2026-03-31`, 60 (primera sesión 2026-01-02).
- W6: `2026-04-01 → 2026-06-30`, 61.
- Total: 362 sesiones; 46 trades P2; 17 aceptados por el filtro.
- El dataset termina antes del holdout. `allow_holdout=False` y
  `holdout_bars_read=false` son obligatorios.

### 5.2 Secuencia

1. **Preflight read-only:** hashes de perfiles, dataset, código, artefactos y
   configuración del filtro; comprobar que el directorio/artefacto de salida no
   existe; comprobar que `data/config.json` y P2 no cambiaron.
2. **Baseline P2:** ejecutar P2 con costes base `0,62/1` y filtro 0,00; exigir
   46 trades, +2.471,78, PF 1,39, DD 2.304,46.
3. **Baseline filtro:** ejecutar P2 + `min_stop_or_ratio=0,25` con costes base;
   exigir 17 trades, +4.202,20, PF 4,25, DD 946,38, R total +18,85, media R
   +1,1088 y PF-R 3,8955.
4. **Stress P2:** mismo P2, solo `1,24/2`; conservar el ledger completo.
5. **Stress filtro:** mismo filtro, solo `1,24/2`; conservar el ledger completo.
6. **Determinismo:** repetir un 10 % de las sesiones (o una corrida completa si
   el coste lo permite) y comparar `signal_id`, qty, entry/exit, exit reason,
   fees, net y R. La firma económica debe ser idéntica.
7. **Reconciliación:** sumar trades por ventana y comparar con el agregado;
   verificar `fees`, `gross`, `net` y `R`; no aceptar diferencias silenciosas.
8. **Sellado:** escribir un único JSON, su SHA-256 y el log; no reejecutar para
   “mejorar” el resultado. No escribir en la DB.

La secuencia baseline-first es obligatoria. Si los 46/17 base no reproducen, el
reprecio se aborta: no se compara un stress contra un baseline distinto.

---

## 6. Evidencia mínima para P6

P6 solo puede pasar de `NO_EVALUABLE` cuando exista un artefacto sellado con
**toda** esta evidencia:

| ID | Evidencia | Criterio |
|---|---|---|
| E1 | Manifiesto de alcance | 4 brazos, W1–W6, 362 sesiones, dataset `1cc455…`, hashes de perfiles/código/artefactos |
| E2 | Reproducción base | P2 46/+2.471,78/1,39/2.304,46 y filtro 17/+4.202,20/4,25/946,38, con tolerancia neto ±0,05, PF ±0,01, DD ±1,00 |
| E3 | Overrides exactos | `commission=1,24`, `slippage=2`, `max_slippage=4`; ningún otro diff entre base y stress |
| E4 | Ledger por trade | `signal_id`, `window`, `direction`, `qty`, `entry_ts/price`, `exit_ts/price`, `stop`, `target`, `exit_reason`, `gross_pnl`, `fees`, `net`, `r_multiple`, `risk_amount`, `gap_stop/gap_target` |
| E5 | Identidad contable | Para el 100 % de los trades: `net = gross − fees`; `fees = 1,24×2×qty` (sin parciales); `R` coincide con el motor |
| E6 | Cohorte del filtro | Los 17 `signal_id` aceptados en `F_BASE` son exactamente los 17 de `F_STRESS`; cero añadidos y cero eliminados; si no, P6 `INCONCLUSO` |
| E7 | Métricas P6 | `mean_r_accepted`, `r_profit_factor_accepted`, `total_r`, `net`, `PF USD`, `DD USD`, `worst_loss_streak`, por bloque |
| E8 | Control P2 | `P2_STRESS` existe y tiene ledger/agregado; se reporta `Δ` vs `P2_BASE`; no se usa para aprobar P6 |
| E9 | Determinismo | Repetición del 10 % (o completa) con la misma firma económica; sin diferencias de `signal_id`, qty, fills, fees, net o R |
| E10 | Sellado y no interferencia | Un solo artefacto, SHA-256, `holdout_read=false`, `db_written=false`, `config_before=config_after`, sin reejecución tras ver métricas |
| E11 | Procedencia | Comando, fecha, hashes del runner/código, estado de git y nombres de los cuatro brazos |

**E8 no es un gate P6.** P2 es el control que permite atribuir el coste y
comprobar que el filtro no se está comparando contra un baseline no repreciado.
Si falta P2_STRESS, P6 queda `NO_EVALUABLE`, no PASS.

### 6.1 Regla de evaluación

| Estado | Condición |
|---|---|
| **PASS** | E1–E11 completas; `F_STRESS` conserva los 17 `signal_id`; `mean_r_accepted > 0`; `PF-R >= 1,10` |
| **FALLA** | E1–E11 completas; cohorte correcto; `mean_r_accepted <= 0` o `PF-R < 1,10` |
| **INCONCLUSO** | Coorte del filtro distinto, muestra incompleta, o el ledger/agregado no reconcilia |
| **NO_EVALUABLE** | No hay artefacto sellado, no se reejecutó el motor, falta P2_STRESS, o se usó una estimación uniforme |

Un P6 `PASS` no cambia el veredicto global si otros gates siguen fallando o
inconclusos. Un P6 `FALLA` no se rescata cambiando costes, ventana, umbral,
semilla o subgrupos.

---

## 7. P2: evidencia de control, no P6

`P2_STRESS` debe reportar, como mínimo:

- `trades`, `net_profit_usd`, `profit_factor_usd`, `expectancy_usd`;
- `mean_r`, `total_r`, `r_profit_factor`;
- `max_drawdown_usd`, `worst_loss_streak`;
- `fees`, `gross_profit`, `gross_loss`;
- neto por W1–W6;
- `Δ` contra `P2_BASE` (neto, PF, R medio, DD);
- `signal_id` añadidos/eliminados y cambios de qty;
- `exit_reason` y `gap_stop/gap_target`.

No se define un P6 de P2. Si más adelante se usa P2 como candidato, su gate de
costes es `P2M-C1` del pre-registro correspondiente: reprecio exacto, `net > 0`
y `PF >= 1,10`. Este documento no ejecuta ni aprueba ese gate.

---

## 8. Contrato del artefacto futuro

El runner debe producir un único JSON con esta forma mínima:

```json
{
  "schema": "cost-repricing-filter-p2-v1",
  "status": "complete",
  "generated_at_utc": "...",
  "scope": {
    "windows": ["W1", "W2", "W3", "W4", "W5", "W6"],
    "sessions": 362,
    "start": "2025-01-10",
    "end": "2026-06-30",
    "holdout_read": false
  },
  "cost_model": {
    "commission_per_contract_side": 1.24,
    "slippage_ticks": 2,
    "max_slippage_ticks": 4,
    "tick_size": 0.25,
    "tick_value": 0.50,
    "point_value": 2.0,
    "fill_model": "next_open",
    "partial_fills": false
  },
  "hashes": {
    "profiles": {},
    "dataset": "1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a",
    "code": {},
    "baseline_artifacts": {},
    "output": null
  },
  "arms": {
    "P2_BASE": {},
    "P2_STRESS": {},
    "F_BASE": {},
    "F_STRESS": {}
  },
  "reconciliation": {},
  "p6": {},
  "p2": {},
  "seal": {}
}
```

Cada brazo debe contener `config_effective`, `windows`, `trades`, `aggregate` y
`signal_ids`. Cada trade debe contener los campos de E4. El `seal` debe incluir
`sha256`, `one_shot=true`, `db_written=false` y `config_unchanged=true`.

El artefacto no existe todavía. No se crea un JSON vacío que pueda confundirse
con evidencia.

---

## 9. Qué invalida el reprecio

- Cambiar cualquier perfil, el dataset, el filtro, sus umbrales, el motor o el
  runner después de fijar los hashes.
- Leer o usar el holdout, o cualquier sesión fuera de W1–W6.
- Usar `0,25` en un brazo que no sea el filtro, o cambiar el umbral.
- Repreciar solo el filtro y no P2, o comparar contra un P2 con costes base.
- Reemplazar la reejecución por una resta uniforme de `4,48/qty`.
- No reproducir los 46/17 baseline o no reconciliar el ledger.
- Cambiar el cohorte aceptado entre `F_BASE` y `F_STRESS`.
- Reejecutar después de ver resultados, cambiar la semilla o buscar un subgrupo.
- Presentar `−100,80` o `stress_costs.json` como si fueran el reprecio del
  filtro/P2.

Cualquiera de estos casos produce `NO_EVALUABLE`, `INCONCLUSO` o un nuevo
diseño; no se parchea el resultado.

---

## 10. Qué no autoriza este documento

- No autoriza ejecutar el reprecio; solo lo especifica.
- No modifica `data/config.json`, `profiles/p2_freq/config.json`, el filtro, el
  protocolo, sus locks, la DB ni el holdout.
- No cambia P6 de `NO_EVALUABLE`.
- No promociona el filtro ni P2, no autoriza LIVE ni paper en tiempo real.
- No convierte la estimación uniforme ni el stress del original en evidencia.
- No reabre W1–W6 como validación: son la muestra histórica del reprecio, no
  una confirmación forward.

---

## 11. Estado actual

- **Diseño:** completo.
- **Reprecio:** no ejecutado.
- **P6:** `NO_EVALUABLE`; `filter025_gates.json` sin cambios.
- **P2_STRESS / F_STRESS:** no existen.
- **Artefacto futuro:** no creado.
- **Holdout:** sellado, no leído.
- **Configuración viva y filtro:** sin cambios.
- **Estimación uniforme del filtro:** `−100,80 USD`, solo diagnóstico; no se usa
  para P6.
- **Stress del original:** `−314,06 USD` absorbidos, `347,38` neto, PF `1,07`;
  solo referencia de método.

Para ejecutarlo hará falta un runner nuevo, el preflight de hashes y una
autorización explícita. Este documento no la concede.
