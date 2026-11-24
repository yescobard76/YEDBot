# Criterio de estabilidad por bloques para presets

**Fecha:** 2026-11-21.  
**Alcance:** análisis retrospectivo de los 15 presets ya ejecutados sobre W1–W6 (362 sesiones).  
**Holdout:** sellado; no ejecutado ni inspeccionado.  
**Protocolo/configuración activa:** no modificados.  
**Naturaleza:** filtro de investigación para priorizar la siguiente fase; **no es una puerta G nueva** ni autoriza paper trading.

## 1. Definición

Para cada preset y cada bloque `b ∈ {W1..W6}`:

- `net_b`: P&L neto del bloque, después de comisiones y slippage.
- `exW4`: P&L neto de W1+W2+W3+W5+W6; elimina W4, el bloque que sostiene el baseline y la mayoría de los presets. No es un leave-one-out genérico: es un stress test fijo sobre ese trimestre.
- `pos`: número de bloques con `net_b > 0`. Un bloque con 0 no cuenta como positivo.
- `dd_b`: drawdown máximo cerrado dentro del bloque. `dd_worst = max(dd_b)`; no es el drawdown del agregado concatenado.

**Screening de estabilidad (pasa si se cumplen las tres):**

| ID | Condición | Umbral | Razón |
|---|---|---|---|
| E1 | P&L ex-W4 | `exW4 > 0` | evita que W4 sostenga todo el resultado |
| E2 | Peor drawdown por bloque | `dd_worst <= 2.000 USD` | 8 % del capital inicial, alineado con G6 pero aplicado al peor bloque |
| E3 | Ventanas positivas | `pos >= 4/6` | misma amplitud que G7, medida en P&L en vez de PF |

`E1 ∧ E2 ∧ E3` es el **pase de screening**. No sustituye a G4–G6, G8–G14 ni a las puertas del holdout.

### Calidad posterior

Si un preset pasa el screening, se marca con estas tres banderas antes de decir que está listo para la siguiente fase:

- **Q1 (muestra):** `trades >= 80`, el mínimo de G4.
- **Q2 (concentración):** `net_W4 / net_total <= 50 %` cuando `net_total > 0`; si el total es negativo, Q2 falla.
- **Q3 (cola):** ningún bloque con `>= 15` operaciones y `PF < 0,70` (cola de G7).

Clasificación:

- **A — pasa a validación pre-registrada:** screening + Q1 + Q2 + Q3.
- **B — pasa solo a ampliación de muestra:** screening, pero falla Q1, Q2 o Q3. No se promueve ni se ejecuta el holdout.
- **C — no pasa:** falla E1, E2 o E3.

## 2. Resultado

**A: 0 · B: 1 · C: 14.** Solo `sl_depth_6` supera el screening; ningún preset alcanza A.

### Tabla completa

Orden: B primero; después C por `exW4` descendente. `W4 %` es `net_W4 / net_total`; `—` si el total no es positivo. Puede superar 100 % cuando los otros bloques son negativos: mide dependencia de W4, no un peso de cartera.

| Preset | Tipo | Ops | Neto $ | ex-W4 $ | Pos | Peor DD $ | DD medio $ | W4 % | E1 | E2 | E3 | Grado |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| **`sl_depth_6`** | default | 15 | 1.539,64 | 273,56 | 4/6 | 1.199,86 | 251,43 | 82,2 % | PASS | PASS | PASS | **B** |
| `entry_or_level` | default | 4 | 482,34 | 482,34 | 1/6 | 207,96 | 34,66 | 0,0 % | PASS | PASS | FAIL | C |
| `entry_breakout_direct` | default | 4 | 390,84 | 248,32 | 2/6 | 305,20 | 50,87 | 36,5 % | PASS | PASS | FAIL | C |
| `direct_sl_cap_600` | opt-in | 90 | 1.404,74 | 149,80 | 3/6 | 931,20 | 532,12 | 89,3 % | PASS | PASS | FAIL | C |
| `deep_stop_sl_cap_600` | opt-in | 74 | 836,86 | -152,60 | 4/6 | 2.102,06 | 987,70 | 118,2 % | FAIL | FAIL | PASS | C |
| `setup_validity_240` | default | 51 | 1.695,96 | -338,16 | 3/6 | 1.583,44 | 776,63 | 119,9 % | FAIL | PASS | FAIL | C |
| `smt_tolerance_16` | default | 48 | 1.091,64 | -586,02 | 4/6 | 1.423,92 | 743,81 | 153,7 % | FAIL | PASS | PASS | C |
| `entry_or_level_sl_cap_600` | opt-in | 100 | 1.255,62 | -700,60 | 2/6 | 1.013,82 | 572,09 | 155,8 % | FAIL | PASS | FAIL | C |
| `smt_window_120` | default | 39 | 1.005,98 | -1.028,14 | 4/6 | 1.187,80 | 639,91 | 202,2 % | FAIL | PASS | PASS | C |
| `rr_2_5` | default | 38 | 742,94 | -1.059,68 | 3/6 | 1.084,80 | 661,57 | 242,6 % | FAIL | PASS | FAIL | C |
| `baseline` | default | 38 | 661,44 | -1.372,68 | 3/6 | 1.084,80 | 675,15 | 307,5 % | FAIL | PASS | FAIL | C |
| `sl_buffer_12` | default | 37 | 139,86 | -1.470,98 | 3/6 | 1.101,06 | 675,45 | 1.151,8 % | FAIL | PASS | FAIL | C |
| `entry_retrace_382` | default | 31 | -28,76 | -1.514,12 | 2/6 | 1.007,58 | 630,10 | — | FAIL | PASS | FAIL | C |
| `recovery_off` | default | 41 | 428,10 | -1.680,02 | 3/6 | 1.181,00 | 754,61 | 492,4 % | FAIL | PASS | FAIL | C |
| `sl_cap_600` | opt-in | 79 | -514,80 | -2.052,54 | 2/6 | 2.102,72 | 1.138,41 | — | FAIL | FAIL | FAIL | C |

## 3. El único candidato: `sl_depth_6`

| Métrica | Valor |
|---|---:|
| Operaciones | 15 |
| P&L neto | 1.539,64 USD |
| P&L ex-W4 | 273,56 USD |
| Ventanas positivas | 4/6 |
| Peor DD por bloque | 1.199,86 USD |
| DD medio por bloque | 251,43 USD |
| W4 / neto total | 82,2 % |
| PF agregado | 2,02 |

**Grado B.** Supera E1–E3, pero falla Q1 (15 < 80 operaciones) y Q2 (W4 = 82,2 % del neto). Q3 pasa. Por tanto, no está listo para paper ni para holdout: la siguiente fase razonable es **ampliar la muestra de desarrollo fuera del holdout**, con la misma configuración y una hipótesis pre-registrada.

Desglose del candidato:

| Bloque | Neto $ | DD $ | Positivo |
|---|---:|---:|---|
| W1 | 292,52 | 0,00 | sí |
| W2 | 338,58 | 308,70 | sí |
| W3 | -676,34 | 1.199,86 | no |
| W4 | 1.266,08 | 0,00 | sí |
| W5 | 0,00 | 0,00 | no |
| W6 | 318,80 | 0,00 | sí |

## 4. Por qué caen los demás

| Preset | ex-W4 $ | Pos | Peor DD $ | W4 % | Motivo principal |
|---|---:|---:|---:|---:|---|
| `entry_or_level` | 482,34 | 1/6 | 207,96 | 0,0 % | E1 pasa, pero 1/6 ventanas positivas. |
| `entry_breakout_direct` | 248,32 | 2/6 | 305,20 | 36,5 % | E1 pasa, pero 2/6 ventanas positivas y solo 4 ops. |
| `direct_sl_cap_600` | 149,80 | 3/6 | 931,20 | 89,3 % | E1/E2 pasan, pero 3/6 ventanas positivas; W4 concentra 89,3 %. |
| `smt_window_120` | -1.028,14 | 4/6 | 1.187,80 | 202,2 % | 4/6 positivas, pero ex-W4 negativo. |
| `smt_tolerance_16` | -586,02 | 4/6 | 1.423,92 | 153,7 % | 4/6 positivas, pero ex-W4 negativo. |
| `deep_stop_sl_cap_600` | -152,60 | 4/6 | 2.102,06 | 118,2 % | 4/6 positivas, pero ex-W4 negativo y DD > 2.000. |
| `entry_or_level_sl_cap_600` | -700,60 | 2/6 | 1.013,82 | 155,8 % | Alta frecuencia, pero ex-W4 negativo y 2/6 positivas. |

Los 8 presets restantes fallan E1; entre ellos el baseline (ex-W4 -1.372,68, 3/6), `setup_validity_240` (ex-W4 -338,16), `rr_2_5` (ex-W4 -1.059,68) y `sl_cap_600` (ex-W4 -2.052,54; además DD 2.102,72).

## 5. Sensibilidad del umbral

- Con **3/6** ventanas positivas, `direct_sl_cap_600` también pasaría el screening (ex-W4 +149,80; DD 931,20; 3/6), pero seguiría en B por Q2 y Q3. No se recomienda bajar a 3/6 porque G7 ya exige 4/6.
- Con **5/6**, ningún preset pasaría.
- Bajar el DD a **2.100** no cambia el candidato; solo afectaría a `deep_stop_sl_cap_600` y `sl_cap_600`, que ya fallan E1.
- El cuello de botella real es **E1**: 11 de 15 presets tienen P&L ex-W4 negativo. Después, E3 elimina 3 de los 4 que sí sobreviven a E1.

## 6. Decisión y límites

- **No hay ningún preset A.** No se justifica ejecutar el holdout ni promover nada a paper por este análisis.
- **`sl_depth_6` es el único B.** Merece una fase de ampliación de muestra, no una promoción. Su resultado depende de W4 en un 82,2 % y tiene solo 15 operaciones.
- `direct_sl_cap_600` es el “casi”: 90 operaciones, buen DD y ex-W4 positivo, pero solo 3/6 ventanas positivas y W4 concentra el 89,3 %.
- El preset nuevo `entry_or_level_sl_cap_600` no pasa: su neto agregado es alto, pero ex-W4 es negativo y solo 2/6 bloques son positivos.
- Este criterio es **retrospectivo y exploratorio**. Para usarlo como filtro confirmatorio debe pre-registrarse antes de la siguiente ronda; no se cambia el protocolo v1.2, el lock, la configuración activa ni el holdout.
- El drawdown por bloque no es el drawdown agregado de G6; se reporta como estabilidad, no como sustituto de la puerta oficial.
- El filtro no corrige por comparaciones múltiples: se aplicó a 15 presets y es descriptivo. No convierte un pase en evidencia confirmatoria.

## 7. Artefactos y fuentes

- `reports/backtest/presets_default_dev.json` — 11 defaults.
- `reports/backtest/presets_optin_600_dev.json` — controles de cap 600.
- `reports/backtest/presets_entry_or_level_sl_cap600_dev.json` — preset nuevo y sus controles.
- `reports/backtest/CRITERIO_ESTABILIDAD_BLOQUES.md` — este documento.

No se ejecutó ningún backtest nuevo ni el holdout; el análisis se calculó sobre los JSON existentes. `holdout_executed=false` en las tres fuentes.
