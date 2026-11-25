# Decisión forward — original vs P1, sin filtro 0,25

**Fecha:** 2026-11-24  
**Estado:** decisión documentada, **no implementada y no ejecutable**.  
**Naturaleza:** nota de alineación; **no es un lock**, no crea captura, no modifica perfiles, configuración, DB, holdout ni los documentos/locks existentes.  
**Decisión:** el filtro `risk.min_stop_or_ratio=0,25` **queda descartado** para el forward. El estudio se reorienta a una comparación de frecuencia: **original como control** y **P1 sin filtro como challenger**.

> Los planes `docs/VALIDACION_FILTRO_STOP_OR.md` y `docs/P2_FILTRO_STOP_OR_FORWARD.md` siguen existiendo como artefactos históricos congelados. No se editan porque sus SHA-256 están registrados en sus locks. Esta nota los sustituye **solo para la decisión de qué forward se quiere hacer**; no reescribe su historia ni reutiliza sus resultados como validación.

---

## 1. Qué se decide

1. **No se valida el filtro 0,25.** No habrá brazo de tratamiento con `min_stop_or_ratio=0,25` ni endpoint `Δ_sel` de aceptadas contra rechazadas.
2. El forward pasa a medir **una sola palanca**: la frecuencia de entrada `150/12 → 210/24`, manteniendo 5 contratos, SL 200 y el filtro desactivado.
3. El control es la **configuración original canónica** `5/200/150/12`.
4. El challenger es **P1** `5/200/210/24`, sin filtro.
5. P2 (10 contratos), la configuración viva `10/300/210/24` y el perfil `p1_forward_filter025` **no forman parte** de este forward.
6. No se implementa nada en este acto: no hay lock nuevo, no hay captura, no hay cambio de configuración ni de perfiles. Sin un lock nuevo, este documento **no autoriza ejecutar**.

---

## 2. Brazos que se congelan en el lock nuevo

| Brazo | ID | Configuración de trading | Filtro | Fuente | Estado de materialización |
|---|---|---|---|---|---|
| Control | C | **5 contratos, SL 200, validez 150, retest 12** | 0,00 | Configuración original canónica del protocolo | Definido; **perfil forward pendiente** |
| Challenger | T | **5 contratos, SL 200, validez 210, retest 24** | 0,00 | `profiles/p1_forward_control/config.json` | Perfil existente; feed neutral pendiente |

### 2.1 Control original

El control es la configuración canónica:

```text
risk.max_contracts             = 5
risk.max_sl_ticks              = 200
risk.risk_per_trade_pct        = 1,0
strategy.setup_validity_minutes= 150
strategy.retest_tolerance_ticks= 12
risk.min_stop_or_ratio         = 0,00
execution / ORB / SMT / TP     = sin cambios
```

**Atención:** `profiles/backtest_real/config.json` **no es utilizable tal cual** como control forward: su archivo actual contiene `210/24`, no `150/12`. El original se define por `docs/protocolo_backtest.lock.json` y por `ORIGINAL_FREQUENCY_PATCH` de `reports/backtest/_manual_common.py`, pero **no existe todavía un perfil forward inmutable** que materialice exactamente `5/200/150/12` con el feed forward. Por tanto, el control está **definido pero no congelado en un archivo**: crear el perfil y registrarlo en el lock nuevo es un prerrequisito, no parte de esta nota.

### 2.2 Challenger P1

El challenger es el perfil P1 sin filtro ya congelado:

| Campo | Valor |
|---|---:|
| Archivo | `profiles/p1_forward_control/config.json` |
| SHA-256 del archivo | `8058b7d7002de547a535a349dbe7f3557e4aaea1e92d392b064dd51b0b8b624b` |
| `config_sha256` canónico | `5527b32cd54353c52968a47fb84471b7012846cefa06413349bcba7085e7e087` |
| `risk.max_contracts` | 5 |
| `risk.max_sl_ticks` | 200 |
| `risk.min_stop_or_ratio` | 0,00 |
| `strategy.setup_validity_minutes` | 210 |
| `strategy.retest_tolerance_ticks` | 24 |
| Feed | CSV forward, `series_mode=raw`, `loop_sessions=false`, replay 1× |
| `live.live_enabled` | false |

El nombre del `feed.csv_path` actual conserva `p1_filter025`:

```text
data/forward/2026-12-01_p1_filter025/bars_forward.csv
```

Ese nombre es herencia del plan anterior. **No es una diferencia de tratamiento**, pero antes del lock nuevo conviene que ambos brazos apunten a un CSV forward con nombre neutro; el archivo **no existe** y no se crea en esta nota. El challenger está materializado como perfil, pero su feed todavía no está listo para el nuevo lock.

### 2.3 Diferencia exacta entre brazos

Con el mismo feed, misma ejecución, mismo capital y el filtro desactivado, el diff debe ser exactamente:

```text
strategy.setup_validity_minutes:  150 -> 210
strategy.retest_tolerance_ticks:   12 -> 24
```

No debe haber diferencias en:

- `risk.max_contracts` (5 en ambos);
- `risk.max_sl_ticks` (200 en ambos);
- `risk.min_stop_or_ratio` (0,00 en ambos);
- `risk.risk_per_trade_pct`, límites diarios, ventana, cooldown;
- `strategy.entry_reference`, `tp_rr`, SMT, ORB, ejecución;
- feed, timestamps, contratos, rolls, `series_mode=raw`, `exclude_roll_sessions=true`;
- `mode=paper`, `live.live_enabled=false`.

El verificador actual `scripts/verify_p1_forward_profiles.py` **no sirve** para este plan: exige que el único diff sea `risk.min_stop_or_ratio` y que exista un brazo `filter025`. Habrá que escribir un verificador nuevo para los dos campos de frecuencia.

### 2.4 Fuera de alcance

| Perfil / elemento | Por qué queda fuera |
|---|---|
| `profiles/p1_forward_filter025/config.json` | El filtro 0,25 está descartado; no es brazo. |
| `profiles/p2_freq/config.json` | Cambia 5 → 10 contratos; es apalancamiento, no la palanca de frecuencia. |
| `profiles/live_8765/config.json` | Cambia SL 200 → 300 y contratos; no es el challenger P1. |
| `docs/VALIDACION_FILTRO_STOP_OR.md` | Plan de filtro; hipótesis y endpoints obsoletos para esta decisión. |
| `docs/P2_FILTRO_STOP_OR_FORWARD.md` | Plan P2 + filtro; no aplica a original vs P1. |
| `docs/filtro_stop_or_forward.lock.json` | Lock del plan de filtro; no es el lock de esta decisión. |
| `docs/p2_filtro_stop_or_forward.lock.json` | Lock del plan P2 + filtro; no es el lock de esta decisión. |
| `profiles/p1_forward.lock.json` | Congela control + filtro; el manifiesto completo no representa el nuevo plan. El perfil de control sí se reutiliza como challenger. |

---

## 3. Muestra, captura y ventana

La ventana y la plomería se mantienen, salvo el número de brazos y el endpoint:

| Elemento | Decisión |
|---|---|
| Ventana | **2026-12-01 → 2029-11-30** |
| Sesiones evaluadas | **742** |
| Bloques | 6 bloques de 6 meses |
| Rolls | 12 sesiones de roll excluidas |
| Feed | CSV forward **raw**, 3 símbolos alineados, RTH 09:00–15:59 ET |
| Captura | Prospectiva, una sesión por archivo, después del cierre, append-only y sellada |
| Burn-in | 2026-11-23 → 2026-11-30, excluido del análisis |
| Datos prohibidos | W1–W6, H1 `2026-07-01 → 2026-10-30`, 2024 y burn-in |
| Live | Deshabilitado; el diseño es captura + replay ciego, no paper en tiempo real |

No se cambia la ventana si la captura empieza tarde: si no se puede empezar el `2026-12-01`, se necesita un lock nuevo con otra ventana.

### 3.1 Frecuencia esperada

Con las tasas in-sample de W1–W6:

- original: 38 operaciones / 362 sesiones = **10,5 %** → ~**78** operaciones en 742 sesiones;
- P1: 46 / 362 = **12,7 %** → ~**94** operaciones.

Son conteos esperados, no una promesa. El forward tiene 36 meses precisamente para que ambos brazos tengan muestra suficiente; no se reutiliza la muestra histórica como validación.

---

## 4. Gates: qué sigue aplicando y qué no

La tabla siguiente mapea las puertas de los planes de filtro. **Ninguna puerta de eficacia del filtro se hereda.**

| Gate | Estado para original vs P1 | Comentario |
|---|---|---|
| I1 | **Aplica, con lock nuevo** | Hash del protocolo, lock y procedencia del código. Los locks de filtro no sirven. |
| I2 | **Aplica** | Solo 2026-12-01 → 2029-11-30; cero W1–W6, H1, 2024 o burn-in. |
| I3 | **Aplica** | 39 contratos, 36 rolls, 12 rolls excluidos, 3 símbolos alineados, ORB completo, sin huecos. |
| I4 | **Aplica** | Captura prospective, manifiesto por sesión, sin backfill ni datos sintéticos. |
| I5 | **Aplica con redefinición** | Simetría de brazos: mismo feed y timestamp; el diff permitido son **los dos campos de frecuencia**, no el filtro. |
| I6 | **Obsoleto** | Validaba el ratio stop/ORB y la partición aceptadas/rechazadas; ya no existe ese cohorte. |
| I7 | **Obsoleto como ratio** | El “sin lookahead” genérico sigue siendo obligatorio, pero no se evalúa con `stop/ORB`. |
| I8 | **Aplica** | Determinismo: replay del 10 % dos veces, mismos `signal_id` y operaciones. |
| I9 | **Aplica** | One-shot: el análisis final no existe antes de ejecutar. |
| S1 | **Aplica** | ≥720/742 sesiones; ningún mes <80 %; ningún hueco >5 sesiones. |
| S2 | **Aplica con redefinición** | Debe exigir un mínimo **por brazo**, no un “baseline” único. Propuesta a fijar: ≥60 operaciones por brazo (esperadas 78/94). |
| S3 | **Obsoleto** | ≥24 aceptadas y ≥30 rechazadas es específico del filtro; no hay aceptadas/rechazadas. |
| S4 | **Aplica con redefinición** | Propuesta: ≥5/6 bloques con ≥6 operaciones **por brazo**. No se congela en esta nota. |
| S5 | **Aplica con redefinición** | Propuesta: ≥5 cortos **por brazo**, no “cortos aceptados”. |
| E1 | **Obsoleto** | `Δ_sel >= +0,25 R` compara aceptadas contra rechazadas; no existe ese contraste. |
| E2 | **Obsoleto** | El bootstrap de selección no es el bootstrap de diferencia entre brazos. |
| E3 | **Obsoleto** | `media(R aceptadas) >= +0,20 R` es del brazo filtrado. |
| P1 | **Obsoleto** | `sum_r_rejected <= 0` presupone un cohorte rechazado. |
| P2 | **Obsoleto** | `PF_R aceptadas` presupone aceptadas. |
| P3 | **Aplica con redefinición** | Debe comparar DD del challenger contra el control y conservar un tope absoluto; el “8 R aceptadas” no se hereda. |
| P4 | **Obsoleto** | Consistencia de rechazados por bloque; no hay rechazados. |
| P5 | **Aplica con redefinición** | Robustez del challenger: drop-best-3, drop-best-month y concentración; recalcular sobre el brazo P1. |
| P6 | **Obsoleto** | Cost stress sobre aceptadas; no hay aceptadas. Puede añadirse un cost stress nuevo, pero no es este gate. |
| P7 | **Obsoleto** | Meses con aceptadas; no hay aceptadas. La cobertura se mide con S1/S4 y actividad por brazo. |
| P8 | **Obsoleto** | Cortos aceptados; se reemplaza por participación/resultado de cortos del challenger si se decide. |
| P9 | **Aplica con redefinición** | Comparación directa: `total_R_P1 >= total_R_original` y `DD_USD_P1 <= DD_USD_original`. |

### 4.1 Falta el endpoint primario

Los planes de filtro tenían un endpoint primario claro: `Δ_sel`. Al descartar el filtro, **ese endpoint desaparece**. No se puede sustituir por E1, E2, E3 ni por P9 sin decidirlo antes.

Propuesta mínima para el lock nuevo, **no congelada aquí**:

```text
Δ_total_R = total_R(P1) - total_R(original)
```

- Unidad de observación: operación.
- Remuestreo: sesión, porque puede haber hasta 3 operaciones por día.
- IC95 % por bootstrap de sesiones.
- Reportar además neto USD, expectancy R, PF, DD USD/R y peor racha por brazo.
- Regla de decisión: se fija en el lock nuevo; no se hereda el `+0,25 R` del filtro.

Sin ese endpoint y su regla de decisión, **el plan está incompleto y no se ejecuta**. Esta nota no inventa un umbral de aprobación.

### 4.2 Regla de decisión

La regla `PASS = todas las I, S, E y P` del plan de filtro **no es aplicable**. El lock nuevo debe definir:

- qué pasa si falla I o S;
- qué pasa si el IC del endpoint primario incluye cero;
- qué pasa si P9 o P3 fallan;
- que un `PASS` no autoriza LIVE;
- que no hay análisis intermedio de eficacia.

Hasta entonces, el estado es **NO EJECUTABLE**.

---

## 5. Secciones que quedan obsoletas

### 5.1 `docs/VALIDACION_FILTRO_STOP_OR.md`

| Sección | Estado | Motivo |
|---|---|---|
| §1 “Resultado que motiva la validación” | **Obsoleta** | Motiva el filtro 0,25, descartado. |
| §2.1–§2.3 hipótesis, `Δ_sel`, endpoint de cartera | **Obsoletas** | No hay aceptadas/rechazadas. |
| §3.3 “Por qué 36 meses” | **Obsoleta en sus conteos** | 78/29/49 es del filtro; para original/P1 se esperan ~78/94. La ventana de 36 meses sigue siendo la base. |
| §3.4 S2–S5 | **Obsoleta o redefinida** | S3 desaparece; S2/S4/S5 cambian a por brazo. S1 se mantiene. |
| §3.5 muestras prohibidas | **Vigente** | W1–W6, H1, 2024 y burn-in siguen prohibidos. |
| §3.6 fuente y captura | **Vigente** | Se reutiliza la plomería, con feed forward neutral. |
| §4 brazos y configuración | **Obsoleta** | Control/filtro se sustituye por original/P1. |
| §4.1 registro por señal y ratio | **Obsoleta** | No hay decisión de ratio ni cohorte. |
| §5.1 métricas de selección | **Obsoleta** | No hay aceptadas/rechazadas. |
| §5.2 métricas de cartera | **Reutilizable con dos brazos** | Neto, R, DD, PF, expectancy. |
| §5.3 robustez y operación | **Parcialmente obsoleta** | `drop_best`, concentración y costes se pueden recalcular; “aceptadas” y ratio no. |
| §6.1 I1–I9 | **Parcial** | I1–I5, I8, I9 aplican con cambios; I6/I7 obsoletos. |
| §6.2 S1–S5 | **Parcial** | S1 aplica; S2/S4/S5 se redefinen; S3 obsoleto. |
| §6.3 E1–E3 | **Obsoletas** | Selección de filtro. |
| §6.4 P1–P9 | **Parcial** | P1/P2/P4/P6/P7/P8 obsoletos; P3/P5/P9 redefinidos. |
| §6.5 regla de decisión | **Obsoleta** | Debe reemplazarse por la regla del lock nuevo. |
| §7.1 bootstrap de selección | **Obsoleta** | Sustituir por bootstrap de diferencia entre brazos. |
| §7.2 “sin placebo de timing” | **Obsoleta** | Argumento específico del filtro. |
| §7.3 potencia | **Obsoleta en sus números** | 29/49 y 0,93 R son del filtro; recalcular para 78/94. |
| §7.4 sin comparaciones múltiples | **Obsoleta** | El endpoint cambia. |
| §8.1–§8.4 ejecución/one-shot/auditoría | **Reutilizable** | Se hereda la disciplina, con lock y runner nuevos. |
| §9 qué no autoriza | **Reutilizable en espíritu** | Sigue sin autorizar LIVE ni paper en tiempo real. |
| §10 limitaciones | **Parcial** | Potencia, régimen y datos se reevalúan para la nueva comparación. |
| §11 artefactos | **Obsoleta** | Apunta a los locks y salidas del filtro. |

### 5.2 `docs/P2_FILTRO_STOP_OR_FORWARD.md`

**El plan en su conjunto queda obsoleto para esta decisión.** Está construido sobre P2 (10 contratos) y el filtro 0,25. No se puede “reutilizar” cambiando solo los brazos porque su hipótesis, endpoints, gates, potencia y motivación son de selección.

Se pueden reutilizar únicamente piezas de plomería: captura prospective, ventana, contratos/rolls, integridad I1–I4/I8/I9, one-shot y auditoría. No se reutilizan como protocolo: §1, §2, §3.3, §4.3–§4.5, §6, §8 y §9 de ese documento.

### 5.3 Locks, perfiles y artefactos

| Artefacto | Estado |
|---|---|
| `docs/filtro_stop_or_forward.lock.json` | **No aplicable**; histórico, `can_execute=false`. No editar. |
| `docs/p2_filtro_stop_or_forward.lock.json` | **No aplicable**; histórico, `can_execute=false`. No editar. |
| `profiles/p1_forward_filter025/config.json` | **Fuera de alcance**; no borrar, no usar como brazo. |
| `profiles/p1_forward.lock.json` | **No reutilizable entero**: congela control + filtro y declara un solo diff. El perfil de control sí sirve como challenger. |
| `scripts/verify_p1_forward_profiles.py` | **No reutilizable**: espera `filter025` y un único diff. |
| `reports/backtest/forward_validation.json` | **No aplicable**: apunta al plan P2 + filtro. |
| `reports/backtest/filtro_stop_or_forward/` | **No crear ni usar** para esta decisión. |
| `reports/backtest/p2_filtro_stop_or_forward/` | **No crear ni usar** para esta decisión. |

No se editan documentos ni locks antiguos: hacerlo rompería sus hashes y la trazabilidad. Esta nota es la referencia de la decisión nueva.

---

## 6. Qué falta antes de poder ejecutar

Nada de esto se implementa en esta nota:

1. **Materializar el control original** `5/200/150/12` en un perfil forward inmutable. El archivo actual `profiles/backtest_real/config.json` no sirve porque contiene `210/24`.
2. **Definir un feed forward neutral** para ambos brazos; el path actual `p1_filter025` es herencia y el CSV no existe.
3. **Crear un lock nuevo** con:
   - hashes del documento, ambos perfiles y el feed;
   - ventana, muestra y bloques;
   - diff exacto de dos campos;
   - endpoint primario y regla de decisión;
   - gates I/S/P aplicables y los redefinidos;
   - estado `can_execute=false` hasta completar la fase 0.
4. **Crear un verificador nuevo** que compruebe el diff de frecuencia y la ausencia de filtro; no reutilizar el verificador P1 actual.
5. **Preflight/runner one-shot** que rechacen W1–W6, H1, 2024, burn-in y cualquier sesión fuera de ventana.
6. **Solo entonces** iniciar captura. Si el control no se puede materializar exactamente, el estudio se aborta; no se sustituye por `profiles/backtest_real` con 210/24 ni por P2.

---

## 7. Qué no cambia

- La configuración viva del 8765 **no se toca**.
- `data/config.json`, `profiles/live_8765`, la DB y el holdout **no se tocan**.
- `profiles/p1_forward_control` se reutiliza como challenger, pero no se modifica.
- `profiles/p1_forward_filter025` no se borra; queda fuera de alcance.
- Los locks y documentos de filtro no se reescriben; quedan como históricos.
- No se captura, no se ejecuta ningún backtest nuevo y no se abre 2024/H1 en esta decisión.

**Estado final de esta nota:** decisión alineada, brazos identificados, gates mapeados y secciones obsoletas declaradas. **No ejecutable** hasta que exista el lock nuevo con el control original materializado y el endpoint primario de dos brazos.
