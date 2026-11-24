# Experimento pre-registrado E-1 — geometría entrada–stop

**Código:** E-1
**Versión:** 0.1 (diseño pre-registrado, **no ejecutado**)
**Fecha:** 2026-11-20
**Datos:** solo desarrollo, W1–W6, 2025-01-10 → 2026-06-30 (362 sesiones evaluadas).
**Holdout:** `2026-07-01` → `2026-10-30`, **sellado y no observado**. No se usa en este experimento.
**Protocolo v1.2 y su lock:** **no se modifican**. Este documento no es el protocolo, no tiene lock
y no autoriza ninguna corrida confirmatoria.

> Este experimento es una **selección de arquitectura sobre datos de desarrollo**, no una prueba
> de rentabilidad. Nada de lo que salga de aquí se puede promover a paper trading ni citar como
> evidencia fuera de muestra. Su único producto es un candidato único para una versión nueva del
> protocolo, que exigirá su propio holdout nunca observado.

---

## 0. Resumen

El endpoint `full` (ORB + SMT + retesteo al 50 % del OR, stop estructural anclado al OR) produjo
38 operaciones, PF 1,1328 y esperanza +0,1311 R en 362 sesiones. El análisis posterior mostró que
el limitante no es la SMT sino la **geometría entrada–stop**: en rangos amplios, el retesteo al
50 % no llega y, cuando llega, el stop estructural queda a cientos de ticks y lo rechaza
`max_sl_ticks=200`.

Este documento fija de antemano:

1. tres brazos decidibles (A = actual, B = entrada directa con stop de confirmación, C = retesteo
   superficial con stop de confirmación) y tres controles de descomposición (K1–K3);
2. la definición exacta, causal y sin look-ahead de cada geometría;
3. las métricas primarias y el análisis pareado por sesión;
4. las reglas de elegibilidad, selección y parada;
5. lo que exigiría una versión v2 del protocolo.

**No se implementa nada en este documento.** La fase 0 (instrumentación sin cambio de conducta)
se describe en §10 y requiere autorización separada.

---

## 1. Evidencia de desarrollo que motiva el experimento

Todas las cifras son del agregado de desarrollo ya reportado en
`reports/backtest/INFORME_DESARROLLO.md` y del análisis posterior de la sesión 2025-01-28.
Se incluyen como **evidencia indiciaria, no decisoria**: el experimento se juzga con sus propias
métricas, no con estas.

| Hecho medido | Valor |
|---|---|
| `full`: operaciones / PF / esperanza R / neto | 38 / 1,1328 / +0,1311 / +661,44 USD |
| `full`: drawdown máximo / peor racha | 1.967,82 USD (7,14 %) / 10 |
| `orb_retest` (sin SMT): operaciones / PF / neto | 49 / 1,2130 / +1.347,44 USD |
| Operaciones comunes `full` ∩ `orb_retest` | 38 (0 solo en `full`) |
| Ausentes de `full` con SMT caducada pese a recuperación | 7 ops, neto −249,66, PF 0,7439 |
| Ausentes de `full` sin SMT oportuna | 4 ops, neto +615,42, PF 2,3366 |
| Rupturas confirmadas que `full` no operó | 175 |
| De esas, con MFE ≥ 100 pts | 111 |
| De esas, con MFE ≥ 100 pts y MAE ≤ 50 pts | 77 (40 largos / 37 cortos) |
| De esas, con MFE ≥ 200 pts y MAE ≤ 50 pts | 40 |
| `orb_smt` (entrada directa + stop estructural actual) | 4 ops en 362 sesiones |
| Sesión 2025-01-28: stop de la entrada directa | 864 ticks (> 200, rechazada) |

**Lectura.** `orb_smt` con 4 operaciones no es una muestra: es la firma de un filtro de stop que
anula la entrada directa. El caso 2025-01-28 lo muestra de forma aislada: la SMT se confirmó a las
10:51–10:52, el precio solo retrocedió 15,5 pts desde el cierre de ruptura (mínimo 21.359,00,
39,5 pts por encima del ORH 21.319,50) y el stop estructural quedó a 864 ticks. Ni el retesteo al
50 % ni el stop anclado al OR permiten operar esa ruptura; una entrada directa con stop de
confirmación sí.

**Advertencia metodológica.** Las cohortes de 175/111/77/40 se midieron sobre rupturas, no sobre
operaciones, y su línea base de MFE/MAE debe reproducirse en la fase 0 antes de usarlas como
criterio. No se usan para aprobar ni rechazar ningún brazo.

### 1.1 Causa mecánica en el código

En `server/strategy/strategy.py`, `_stop` calcula para un largo:

```python
base = min(swing, orb.mid) - buffer
```

`swing` es el mínimo de las últimas `structural_depth` velas de 15 m y `orb.mid` está muy por
debajo del ORH. El `min` elige **siempre el más profundo** de los dos, de modo que el stop nunca
puede ser más ajustado que la distancia al 50 % del rango. En un OR de 160 pts eso son 80 pts
(320 ticks) más el buffer, antes incluso de mirar la estructura. No es un problema de SMT ni de
dirección: es la cláusula de anclaje.

El experimento separa esa cláusula del resto de la arquitectura. No la cambia por decreto.

---

## 2. Pregunta e hipótesis

**Pregunta.** En datos de desarrollo, ¿una geometría de entrada más superficial y un stop anclado
a la confirmación —en lugar del 50 % del OR— producen más operaciones y mejor esperanza neta que
la arquitectura actual, sin romper los límites de riesgo?

### H1 — Cobertura (principal)

La arquitectura actual pierde rupturas válidas por geometría, no por señal. Una entrada directa
tras la confirmación de SMT (brazo B) o un retesteo superficial (brazo C) cubrirán una fracción
materialmente mayor de las rupturas confirmadas con SMT que A.

- **Métrica:** cobertura = eventos operados / eventos con ruptura confirmada y SMT válida.
- **Dirección esperada:** B > C > A.
- **Falsación:** si B y C no superan a A en al menos 10 puntos porcentuales de cobertura, H1 se
  rechaza y la hipótesis de geometría queda desmentida en desarrollo.

### H2 — Eficiencia (principal)

El stop de confirmación reduce la distancia media de stop y la tasa de rechazo por
`max_sl_ticks` sin destruir la esperanza neta en R.

- **Métricas:** mediana y p90 de `stop_ticks`; % de señales rechazadas por `max_sl_ticks`;
  esperanza neta en R; PF neto.
- **Dirección esperada:** B y C con mediana de stop < 50 % de la de A y rechazo por tope < 10 %.
- **Falsación:** si la mediana de stop de B o C no baja del 50 % de A, o si la esperanza neta en R
  cae por debajo de −0,05 R respecto de A en los eventos comunes, la hipótesis se rechaza.

### H3 — Sustitución frente a cobertura (principal)

La mejora, si existe, no puede venir solo de añadir operaciones: en los eventos que A también
opera, la nueva geometría no debe degradar el resultado.

- **Métrica:** ΔR pareado en eventos comunes y P&L de los eventos exclusivos, reportados por
  separado (§5.4).
- **Falsación:** un brazo con ΔR pareado < −0,05 R no es elegible aunque su P&L total sea mayor.

### H4 — Viabilidad bajo el riesgo congelado (secundaria)

B y C son implementables sin tocar `max_sl_ticks`, `max_contracts` ni el resto del bloque de
riesgo.

- **Métricas:** % de señales con `stop_ticks > 200`; % de operaciones con `qty` topado en 5;
  riesgo efectivo medio (% del capital).
- **Falsación:** si más del 25 % de las señales de un brazo siguen superando 200 ticks, ese brazo
  no es viable con la configuración congelada y queda fuera de selección.

**Hipótesis nula global:** ninguna de B o C supera a A en cobertura y esperanza sin violar las
puertas de riesgo. En ese caso se retiene la arquitectura actual y no se abre v2.

---

## 3. Diseño

### 3.1 Factorial 3 × 2

Se varían dos ejes por separado para no confundir entrada con stop:

- **Entrada (E):** directa · retesteo superficial · retesteo profundo (actual).
- **Stop (S):** confirmación · estructural anclado al OR (actual).

| Celda | Entrada | Stop | Rol | ¿Seleccionable? |
|---|---|---|---|---|
| **A** | retesteo 50 % del OR | estructural OR | referencia actual | sí (solo si gana) |
| **B** | directa tras SMT | confirmación | hipótesis principal | sí |
| **C** | retesteo 25 % del semiancho | confirmación | hipótesis principal | sí |
| K1 | directa tras SMT | estructural OR | control = `orb_smt` actual | no |
| K2 | retesteo 25 % | estructural OR | control de interacción | no |
| K3 | retesteo 50 % | confirmación | control del anclaje | no |

K1 ya está medido (4 operaciones). Se re-ejecuta con el código instrumentado como ancla de
regresión. K2 y K3 no existen todavía; su función es atribuir el efecto a la entrada, al stop o a
la interacción.

**Regla de los controles.** Si un control K supera a A, B y C en todas las puertas de selección,
el experimento **no lo selecciona**: informa de que la descomposición contradice la hipótesis y
exige un pre-registro nuevo (E-2) con esa celda como candidata única. Esto evita elegir a posteriori
entre seis celdas.

### 3.2 Definiciones exactas

Todas las definiciones son **causales**: solo usan velas cerradas con `ts + 60 <= entry_ts`.
Ninguna lee el futuro de la sesión.

#### Profundidad de retesteo (`retest_depth`)

Generaliza `entry_reference` con un parámetro continuo `d ∈ [0, 1]`:

```
mid   = (ORH + ORL) / 2
ref   = ORH - d * (ORH - mid)     # largo
ref   = ORL + d * (mid - ORL)     # corto
```

- `d = 0` → borde del OR (equivale a `breakout_level`);
- `d = 0,25` → **retesteo superficial** (brazo C): un cuarto del camino hacia el 50 %;
- `d = 1` → 50 % del OR (equivale a `or_mid`, brazo A).

El toque se detecta con `retest_tolerance_ticks = 12` y la entrada sigue exigiendo cierre de
recuperación (`require_recovery_close = true`, `entry_trigger = "close"`), igual que A. Así C se
diferencia de A **solo** en `d` y en el stop.

*Por qué 0,25 y no otro valor:* es un retroceso del 12,5 % del ancho del OR, sigue siendo
"superficial" en cualquier régimen y no requiere estimar la pierna (que introduciría una referencia
móvil y una forma de persecución). No se exploran otros valores: E-1 tiene una sola profundidad
pre-registrada.

#### Entrada directa

Sin retesteo. La entrada se ejecuta en el cierre de la primera vela de 1 m en la que ya está
confirmada la SMT, y nunca a un precio peor que el cierre de ruptura:

```
entry_ts    = max(breakout.confirm_ts, smt.confirm_ts + 60)
entry_price = close(vela en entry_ts)
entry_price = max(entry_price, breakout.close)   # largo
entry_price = min(entry_price, breakout.close)   # corto
```

Es el camino `direct` que ya existe en `strategy.py`. El `max`/`min` es conservador (empeora el
precio, nunca lo mejora) y debe conservarse tal cual.

#### Stop de confirmación (`sl_mode = "confirmation"`)

```
history = velas de 15 m cerradas con ts + 15m <= entry_ts
swing   = min(low de las últimas structural_depth=3)   # largo
swing   = max(high de las últimas structural_depth=3)  # corto
base    = swing - sl_buffer_ticks * tick               # largo
base    = swing + sl_buffer_ticks * tick               # corto
stop    = min(base, entry - 8 ticks)                   # largo, distancia mínima
stop    = max(base, entry + 8 ticks)                   # corto
```

- **Sin** anclaje a `orb.mid`.
- **Sin** ATR.
- `sl_buffer_ticks = 4`, `structural_depth = 3`, mínimo 8 ticks: idénticos a hoy.
- Si `stop_ticks > 200`, la señal se rechaza y se cuenta como `stop_cap_binding`.

El stop queda en el nivel que invalida la confirmación: el extremo de la estructura de 15 m que
produjo la señal. Para una entrada directa suele quedar justo tras el borde del OR; para un
retesteo superficial, en el mínimo del retroceso. Es la definición que ataca la causa mecánica de
§1.1 sin cambiar el resto de la regla.

#### Stop estructural actual (`sl_mode = "structural"`)

Sin cambios: `base = min(swing, orb.mid) - buffer` en largos y `max(swing, orb.mid) + buffer` en
cortos. Se conserva literalmente para A y para K1/K2.

### 3.3 Parámetros del experimento

Base: `lock["settings"]` de v1.2, sin ninguna otra modificación. Solo cambian las claves de la
tabla. Todo lo demás —ORB, SMT, `setup_validity_minutes`, `tp_rr`, riesgo, ejecución, feed— queda
congelado tal cual.

| Brazo | `entry_reference` | `retest_depth` | `sl_mode` | `use_smt` |
|---|---|---|---|---|
| A | `or_mid` | 1,00 | `structural` | true |
| B | `none` | — | `confirmation` | true |
| C | `or_mid` | 0,25 | `confirmation` | true |
| K1 | `none` | — | `structural` | true |
| K2 | `or_mid` | 0,25 | `structural` | true |
| K3 | `or_mid` | 1,00 | `confirmation` | true |

**No se cambia:** `max_sl_ticks=200`, `max_contracts=5`, `risk_per_trade_pct=1,0`,
`max_trades_per_day=3`, `max_daily_loss_pct=3,0`, `setup_validity_minutes=150`,
`retest_tolerance_ticks=12`, `tp_rr=3,0`, SMT completa, ventanas, comisiones ni slippage.

`max_sl_ticks` es precisamente la restricción que se mide. Subirlo convertiría el experimento en
un cambio de riesgo y confundiría las dos causas.

### 3.4 Interacción con el sizing

Con stops más ajustados, `RiskManager.size` pide más contratos para el mismo 1 % de riesgo y puede
topar en `max_contracts=5`:

```
qty = min(floor(risk_budget / (stop_ticks * 0,50)), 5)
risk_amount = qty * stop_ticks * 0,50
```

Con un stop de 20 ticks, el tope de 5 contratos limita el riesgo real a 50 USD (0,2 % del capital),
no al 1 %. Consecuencias que el experimento debe reportar y no confundir:

- **R sigue siendo comparable:** `r_multiple = pnl / risk_amount` usa el riesgo real tras el tope.
- **El P&L en USD y el drawdown en USD bajan mecánicamente** con stops ajustados. Un DD menor no
  es evidencia de mejor estrategia; es consecuencia del tope de contratos.
- **Se reportan** `avg_qty`, `qty_cap_share` y `effective_risk_pct` por brazo.
- **No se cambia** `max_contracts` en E-1.

---

## 4. Datos y unidad de análisis

| Elemento | Valor |
|---|---|
| Ventana | 2025-01-10 → 2026-06-30 |
| Sesiones de calendario / evaluadas | 368 / 362 |
| Bloques | W1–W6 (54, 61, 63, 63, 60, 61) |
| Dataset | `data/real/bars_mnq_nq_es_1m.csv` (raw) |
| SHA-256 dataset | `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a` |
| `series_id` raw | `b844560f36b33c478c0e1e7caee18bb639488b0113d071d5369c640b865f07ff` |
| Contratos / rolls | 21 / 6 sesiones excluidas |
| Rellenos | 0 |

El CSV **no contiene** sesiones desde 2026-07-01: `allow_holdout=False` rechazaría el archivo
completo. El holdout no está descargado. Nada en E-1 lo descarga ni lo abre.

**Unidad de análisis:** el **evento**, definido como `(sesión, dirección, breakout_ts)`. En la
práctica hay como máximo un evento por sesión, porque la estrategia se fija en la primera ruptura
confirmada y no reentra (`allow_reentry_after_false_breakout=false`, `signal.id` único por
ruptura). Cada celda se evalúa sobre los mismos 362 eventos potenciales.

**Unidad de remuestreo:** la **sesión**, no la operación. El bootstrap de E-1 remuestrea sesiones
completas con reemplazo (10.000 remuestras, semilla `20261120`), porque las operaciones de un mismo
día comparten régimen y no son independientes. Esto corrige la limitación declarada en §10 del
protocolo v1.2.

---

## 5. Métricas

### 5.1 Primarias (deciden)

| ID | Métrica | Definición |
|---|---|---|
| P1 | Cobertura | eventos operados / `N_eventos`, con `N_eventos` pre-registrado en §5.3 e **independiente de la celda** |
| P2 | Esperanza neta en R | media de `r_multiple` de operaciones cerradas, neta de costes |
| P3 | Profit factor neto | beneficio bruto / \|pérdida bruta\| |
| P4 | P&L neto | suma de `pnl` |
| P5 | Drawdown máximo | `max_drawdown` en USD y % del capital inicial |
| P6 | Peor racha perdedora | `worst_loss_streak` |
| P7 | Distancia de stop | mediana y p90 de `stop_ticks`; % con `stop_ticks > 200` |
| P8 | ΔR pareado | diferencia de R en eventos comunes contra A, con IC bootstrap por sesión |

### 5.2 Secundarias (describen, no deciden)

- Operaciones por dirección, PF y esperanza por dirección (largos y cortos por separado).
- `avg_win_r`, `avg_loss_r`, payoff y win rate.
- `avg_mfe_r`, `avg_mae_r` y su relación con la distancia de stop.
- Duración media y `entry_delay_min` (confirmación de ruptura → entrada).
- Operaciones por sesión y % de sesiones operadas.
- Consistencia por bloque: PF y esperanza en W1–W6.
- Sensibilidad a costes: comisión 1,24 USD/lado y slippage 2 ticks (máximo 4).
- Drop-best 5; concentración top-5 y mejor mes.
- `qty_cap_share`, `avg_qty`, `effective_risk_pct`.
- Barras ambiguas y su impacto económico.

### 5.3 Métricas nuevas de observabilidad

Se calculan por señal y se agregan por brazo. Son el núcleo de la fase 0 y no cambian ninguna
decisión de la estrategia.

| Campo | Definición |
|---|---|
| `n_breakouts` | rupturas confirmadas por cierre de 15 m |
| `n_breakouts_smt` | de esas, con SMT del sesgo correcto, recuperada y confirmada dentro de la ventana de setup (`smt.confirm_ts <= breakout.confirm_ts + 150 min`). Es el denominador `N_eventos`, común a todas las celdas |
| `n_entry_trigger` | de esas, con referencia tocada y cierre de recuperación |
| `n_signals` | señales construidas |
| `n_risk_rejected` | rechazadas por el gestor de riesgo, por motivo |
| `n_filled` | operaciones ejecutadas |
| `miss_reason` | `sin_smt`, `smt_caducada`, `sin_retesteo`, `setup_expirado`, `stop_cap`, `ventana`, `riesgo`, `sin_estructura` |
| `stop_ticks` | distancia de stop de la señal |
| `direct_stop_ticks` | distancia de stop que tendría la entrada directa en ese mismo evento |
| `retest_distance_ticks` | distancia desde el cierre de ruptura a la referencia |
| `retest_depth_pct` | profundidad efectiva alcanzada por el precio, en % del semiancho del OR |
| `mfe_before_entry_r` | recorrido favorable antes de entrar, en R del stop de esa señal |
| `entry_delay_min` | minutos desde `breakout.confirm_ts` hasta `entry_ts` |
| `stop_cap_binding` | `true` si `stop_ticks > 200` |
| `event_id` | `(sesión, dirección, breakout_ts)` para el pareado |

`direct_stop_ticks` es clave: permite saber, **sin operar**, cuántas rupturas quedarían fuera por
el tope en cada arquitectura. Es el diagnóstico que hoy falta en la UI.

### 5.4 Descomposición obligatoria

Comparar agregados entre brazos confunde dos efectos. Se reportan siempre por separado:

1. **Sustitución:** en eventos que A y el brazo X operan, ΔR y Δnet por evento (pareado).
2. **Cobertura:** P&L de los eventos que X opera y A no.
3. **Total:** suma de ambos, que debe cuadrar con el agregado de X.

Un brazo solo es elegible si **sustitución ≥ −0,05 R** y **cobertura > 0**. Así se impide que un
brazo gane por añadir operaciones malas o que pierda por no poder operar las buenas.

---

## 6. Análisis estadístico

### 6.1 Contraste principal

Para cada brazo X ∈ {B, C} y para cada métrica P2–P5:

- **Pareado:** Δ = X − A sobre los eventos comunes, remuestreando **sesiones** con reemplazo.
- **No pareado:** X sobre todos sus eventos, como descriptivo.
- **IC bootstrap al 80 % y 95 %** de Δ (percentiles 10/90 y 2,5/97,5), 10.000 remuestras,
  semilla `20261120`.
- **Signo:** proporción de sesiones con Δ > 0.

No se usa un p-valor como criterio de selección (§6.3). El IC sirve para dimensionar la
incertidumbre, no para declarar significación.

### 6.2 Potencia y efecto mínimo detectable

Con la desviación observada de `full` (sd de R = 1,6954) y α = 0,05 bilateral, potencia 0,80:

| Diseño | n | Efecto mínimo detectable |
|---|---:|---:|
| Dos muestras independientes | 38 por brazo | ≈ 1,09 R |
| Dos muestras independientes | 80 por brazo | ≈ 0,75 R |
| Pareado por sesión (σΔ = 1,0 R) | 38 pares | ≈ 0,45 R |
| Pareado por sesión (σΔ = 1,0 R) | 60 pares | ≈ 0,36 R |
| Pareado por sesión (σΔ = 1,0 R) | 80 pares | ≈ 0,31 R |

Fórmulas: `n = 2(z₀,₉₇₅+z₀,₈)²σ²/Δ²` para muestras independientes;
`MDE = (z₀,₉₇₅+z₀,₈)σΔ/√n` para el pareado.

**Consecuencia pre-registrada:** con 38–60 eventos, E-1 solo puede detectar diferencias grandes
(≥ 0,4 R). Por eso es un **cribado**, no una confirmación. Un brazo que gane por menos de ese
margen no puede declararse mejor; solo puede quedar como candidato a confirmar en v2. La σΔ real
se calculará en la fase 0 y se reportará; si es mayor que 1,0 R, el MDE empeora y se declara.

### 6.3 Regla de selección (lexicográfica)

Se aplica en este orden. Un brazo que falla un escalón no pasa al siguiente. **Como máximo se
selecciona un brazo.**

**E1. Viabilidad**
1. ≥ 50 operaciones cerradas y ≥ 15 por dirección.
2. `stop_cap_binding` ≤ 25 % de las señales.
3. Sin errores de integridad (G14): `signal_id`, contrato, `expiry`, sin duplicados.

> 50 operaciones y 15 por dirección quedan **por debajo** de G4 (80 y 20). Un brazo que pase E1
> **no cumple G4** y no es promovible: solo califica para diseñar v2.

**E2. Riesgo**
4. `max_drawdown` ≤ 2.000 USD y peor racha ≤ 8 (idéntico a G6).

**E3. Edge**
5. PF ≥ 1,25 y esperanza ≥ +0,10 R (idéntico a G5).
6. Sustitución ΔR ≥ −0,05 R y cobertura > 0.

**E4. Robustez**
7. Con costes dobles: PF ≥ 1,10 (G8).
8. Drop-best 5 > 0 (G9).
9. Top-5 ≤ 50 % del bruto y mejor mes ≤ 50 % del neto (G10).
10. IC bootstrap al 80 % de la esperanza en R con límite inferior > 0 (G11).

**E5. Consistencia**
11. ≥ 4 de 6 bloques con PF > 1; ningún bloque con ≥ 15 operaciones y PF < 0,70 (G7).

**Desempate**, solo entre brazos que superen E1–E5, en este orden:
1. mayor límite inferior del IC al 80 % de ΔR pareado contra A;
2. menor `stop_cap_binding`;
3. regla más simple (menos parámetros nuevos).

**Si ningún brazo supera E1–E5:** se retiene la arquitectura actual, no se abre v2 y se documenta
el resultado negativo. No se prueban variantes adicionales dentro de E-1.

**Si un control K supera a todos:** no se selecciona (§3.1); se abre E-2.

---

## 7. Criterios de parada

### 7.1 Paradas de integridad (abortan el experimento)

| ID | Condición | Acción |
|---|---|---|
| S1 | El código instrumentado no reproduce las 38 operaciones de `full` (ids, entrada, salida, P&L) | abortar; la instrumentación cambió conducta |
| S2 | K1 no reproduce las 4 operaciones de `orb_smt` | abortar |
| S3 | Una celda no es determinista en W1 (dos corridas distintas) | abortar esa celda y reportar |
| S4 | `raw` y `adjusted` difieren en W1 para una celda | abortar esa celda e investigar rolls |
| S5 | Aparece look-ahead: `entry_ts` anterior a `breakout.confirm_ts` o a `smt.confirm_ts` | abortar |
| S6 | El dataset cambia de hash o aparecen sesiones fuera de desarrollo | abortar |

### 7.2 Parada por resultado

**No hay parada anticipada por rendimiento.** Las seis celdas se ejecutan completas, una vez cada
una, sobre las 362 sesiones. Parar al ver un resultado favorable o desfavorable es exactamente lo
que el pre-registro pretende impedir.

Una celda puede marcarse **no viable** solo por E1 (viabilidad), y se reporta igualmente su
resultado completo. Marcarla no autoriza a sustituirla por otra geometría.

### 7.3 Límites de ejecución

- **Presupuesto:** 6 celdas × 6 bloques + repeticiones de determinismo (S3) y raw/adjusted (S4).
  Ninguna corrida adicional.
- **Reejecución:** solo por defecto técnico documentado (excepción, archivo corrupto). Se reportan
  ambas corridas y la causa. Nunca para cambiar parámetros.
- **Cierre:** tras la selección, E-1 termina. Cualquier idea nueva —otra profundidad, otro buffer,
  ATR, parciales— exige un pre-registro nuevo, no una celda extra.
- **Prohibido durante E-1:** descargar el holdout, abrir `holdout.json`, cambiar el lock, cambiar
  `data/config.json` o usar el servidor en vivo para generar señales del experimento.

---

## 8. Amenazas a la validez

| Amenaza | Control pre-registrado |
|---|---|
| Sobreajuste por elegir entre 6 celdas | 3 decidibles + 3 controles; regla lexicográfica; un solo seleccionado; controles no elegibles |
| Confundir entrada con stop | factorial 3 × 2 y controles K2/K3 |
| Confundir cobertura con edge | descomposición obligatoria §5.4 |
| Drawdown bajo por stops ajustados | `qty_cap_share` y `effective_risk_pct` obligatorios; DD no se interpreta solo |
| Dependencia intradía | bootstrap por sesión, no por operación |
| Muestra pequeña | E1 exige 50 ops; se declara MDE y no se habla de significación |
| Look-ahead en la referencia | definiciones causales §3.2; S5 aborta |
| Supervivencia del mejor bloque | consistencia E5 sobre W1–W6, no sobre el agregado |
| Cambio de régimen | se reporta por bloque y por dirección; no se selecciona por un trimestre |
| El caso 2025-01-28 como anécdota | no es criterio; solo motivación. Se mide en el agregado |

**Limitación aceptada:** E-1 no puede demostrar que la arquitectura elegida sea rentable. Su
resultado es una hipótesis con evidencia en desarrollo, no una confirmación.

---

## 9. Qué NO es este documento

- No es el protocolo v1.2 ni una revisión suya. No cambia su hash
  (`2419ec7e…`) ni el del lock (`55d89872…`).
- No modifica la configuración congelada (`09dc0592…`) ni `data/config.json`.
- No cambia la estrategia, el motor, el frontend ni los datos.
- No autoriza ejecutar el holdout ni una corrida confirmatoria.
- No promueve `orb_retest` ni ninguna ablación.
- No fija un lock propio: **no es ejecutable** hasta que se implemente y se congele (§10, §11).

---

## 10. Plan de implementación (posterior y separado)

Ninguna fase se inicia sin autorización explícita. El orden es obligatorio: primero observar,
después decidir, y solo al final cambiar geometría.

### Fase 0 — Observabilidad sin cambio de conducta

1. Añadir `retest_depth` como parámetro con `d = 1,0` por defecto, de modo que `or_mid` se comporte
   exactamente igual que hoy.
2. Añadir `sl_mode = "confirmation"` **sin activarlo** en ninguna configuración viva.
3. Instrumentar el embudo de §5.3 y `event_id`.
4. Añadir a la UI la línea de tiempo de fases con historial: ruptura, SMT (aunque caduque), retesteo,
   entrada y motivo de descarte. Hoy la UI pierde el historial y muestra "SMT esperando" después de
   que el setup expiró.
5. **Ancla de regresión:** `full` debe reproducir 38 operaciones con ids, precios, P&L y PF 1,1328
   idénticos; `orb_smt` debe reproducir 4. Si no, se revierte la instrumentación.

La fase 0 no es el experimento: es la condición para que E-1 sea medible.

### Fase 1 — Corrida única de E-1

Las seis celdas, una vez, sobre W1–W6, con el código de la fase 0 congelado y su hash registrado.

### Fase 2 — Informe y decisión

Informe con la estructura del anexo B del protocolo, adaptada: identificación, dataset, tabla por
celda y bloque, embudo, descomposición, puertas E1–E5, controles K1–K3, decisión y limitaciones.

### Fase 3 — Solo si hay candidato

Redactar v2 (§11). No se implementa v2 ni se toca el holdout en E-1.

---

## 11. Qué exigiría una versión nueva del protocolo (v2)

Si E-1 produce un candidato, **nada de E-1 se puede reutilizar como confirmación**. v2 exige:

### 11.1 Gobernanza

1. **Documento nuevo:** `docs/PROTOCOLO_BACKTEST_V2.md`. No se edita v1.2.
2. **Lock nuevo:** `docs/protocolo_backtest_v2.lock.json`, con hash propio y estado
   `frozen-not-executed`.
3. **Un solo endpoint confirmatorio:** la celda seleccionada por E-1, con su geometría exacta
   (`entry_reference`/`retest_depth`, `sl_mode`) y todos los demás parámetros idénticos a v1.2.
4. **Las demás celdas pasan a descriptivas.** No se corrige por comparaciones múltiples porque solo
   hay un endpoint.
5. **Declaración explícita** de que los resultados de E-1 son in-sample para la selección y no
   cuentan como evidencia de v2.

### 11.2 Holdout nuevo

6. **El holdout actual no se reutiliza.** §0.2 de v1.2 lo prohíbe para cualquier cambio sustantivo,
   y hacerlo destruiría la única muestra reservada del endpoint vigente. `2026-07-01` → `2026-10-30`
   queda sellado para v1.2 y no se abre para v2.
7. **El holdout de v2 debe ser datos nunca observados.** Como el dataset termina el 2026-10-30, eso
   obliga a **acumular datos hacia adelante** desde la primera sesión posterior. A 2026-11-20 hay
   ~14 sesiones disponibles: insuficiente para cualquier puerta.
8. **Tamaño mínimo, calculado con la tasa observada.** Si el brazo elegido opera a tasa `r`:

   | Puerta | Operaciones | Sesiones necesarias | Equivalente aproximado |
   |---|---:|---:|---:|
   | G4 (v2) | 80 | 80 / r | a r = 0,25: 320 sesiones ≈ 15 meses |
   | H2 (v2) | 18 | 18 / r | a r = 0,25: 72 sesiones ≈ 3,5 meses |

   Con la tasa de `full` (0,105), G4 exigiría 762 sesiones ≈ 3 años. La tasa real del candidato se
   mide en E-1 y se congela en v2 **antes** de mirar el holdout.

### 11.3 Diseño y puertas

9. **Ventana de desarrollo y holdout nuevas**, fijadas antes de ejecutar y sin solaparse.
10. **Puertas G1–G14 adaptadas:** G2 (determinismo) y G3 (raw/adjusted) se reejecutan sobre el código
    nuevo; G8–G11 se recalculan con la nueva distribución de stops; G12 (cortos) sigue siendo
    obligatoria.
11. **Puerta de viabilidad explícita:** `stop_cap_binding` y `qty_cap_share` se reportan, pero dejan
    de ser puerta si el candidato ya demostró ser viable en E-1. No se relajan G4–G6.
12. **Riesgo congelado:** si el stop de confirmación topa el sizing, v2 debe decidir *antes* si
    mantiene `max_contracts=5` (riesgo efectivo menor) o si define el riesgo en términos de R. No
    puede cambiarlo después de ver el holdout.
13. **Protocolo de una sola ejecución:** holdout una vez, con la misma regla de reejecución solo por
    defecto técnico documentado.

### 11.4 Lo que v2 no puede hacer

- Reutilizar el holdout de v1.2.
- Reutilizar los resultados de E-1 como confirmación.
- Elegir parámetros con el holdout a la vista.
- Promover a LIVE: sigue bloqueado por falta de adaptador de broker.
- Declarar APTO sin cumplir G4 y H2 con muestra suficiente.

---

## 12. Prohibiciones explícitas de E-1

1. No observar, descargar ni ejecutar el holdout.
2. No modificar `docs/PROTOCOLO_BACKTEST.md` ni `docs/protocolo_backtest.lock.json`.
3. No modificar `data/config.json` ni el perfil del servidor en vivo.
4. No cambiar `max_sl_ticks`, `max_contracts`, `risk_per_trade_pct` ni el resto del riesgo.
5. No añadir celdas, profundidades ni modos de stop después de ver resultados.
6. No seleccionar por P&L total sin la descomposición de §5.4.
7. No declarar rentabilidad, edge confirmado ni aptitud para paper.
8. No ejecutar nada de §10 sin autorización separada.

---

## 13. Anexo — referencias

- `docs/PROTOCOLO_BACKTEST.md` — protocolo v1.2 congelado (no modificado).
- `docs/protocolo_backtest.lock.json` — lock v1.2 (no modificado).
- `reports/backtest/INFORME_DESARROLLO.md` — resultados de desarrollo y puertas G1–G14.
- `reports/backtest/variant_aggregate.json` — ablaciones agregadas.
- `reports/backtest/gates.json` — decisión INCONCLUSO.
- `server/strategy/strategy.py` — `_stop`, `_reference` y camino `direct`.
- `server/risk.py` — `size`, tope de contratos y `max_sl_ticks`.
- `server/backtest.py` — `VARIANTS`, `_simulate`, `run_variants`.

**Estado del documento:** borrador pre-registrado. Se congela cuando se registre su SHA-256 y el
usuario autorice la fase 0. Hasta entonces no se ejecuta.
