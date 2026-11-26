# Paso 3 — Factorial stop × frecuencia con qty=1 y métricas en R

**Fecha:** 2026-11-25
**Objeto:** re-rankear los levers de stop, contratos y frecuencia con **qty fija de 1 contrato** y **R por operación**, mediante un factorial 2×2 stop × frecuencia, para separar el efecto del stop del de contratos y del de frecuencia.
**Naturaleza:** análisis de desarrollo. Las celdas A, B y D se reconstruyen desde operaciones ya medidas; la celda C se ejecuta nueva a qty=1. No se modifica ninguna configuración, no se toca el 8765, no se abren locks y no se lee ni ejecuta el holdout.
**H1:** `2026-07-01 → 2026-10-30`, sellado. **No se abre en esta pasada.**

---

## 0. Resumen ejecutivo

- **El lever dominante es la frecuencia 210/24, no el stop.** El efecto principal de frecuencia es **+0,1436 R por operación** y **+9,40 R totales** en W1–W6; es positivo en **5/6 ventanas** y no aumenta el R-DD en ninguna de las dos ramas de stop.
- **El stop 300 no es un lever de edge.** Su efecto principal es **−0,0915 R por operación**; es negativo en **4/6 ventanas**, neutro en W5 y solo ligeramente positivo en W1. En frecuencia 150/12 hunde la celda C a **0,97 R totales**, PF **1,024** y R-DD **13,15**. En frecuencia 210/24 añade **+1,63 R totales**, pero a costa de **−0,0681 R/op**, **+3,00 R de DD** y 26 operaciones extra de baja calidad.
- **La manual (D: 300/210) gana el total de la muestra; la P2 (B: 200/210) gana la calidad.** D: **13,19 R** y **1.361,72 USD** a qty=1; B: **11,56 R** y **882,46 USD**, pero con **0,2513 R/op** (vs 0,1832), PF **1,413** (vs 1,306) y RDD_R **1,139** (vs 1,003). D no gana por mejor stop: gana por 26 operaciones extra que aportan solo **+1,63 R** (0,063 R/op) y **+3,00 R de DD**.
- **Los contratos no son edge: son sizing.** El R es invariante al tamaño. El `sl_200` que en USD dinámico parecía **+448,84 USD** frente a la manual pasa a **−479,26 USD** a qty=1. La ventaja dinámica era sizing (qty media 4,96 vs 3,74), no una mejora de la estrategia.
- **Decisión:** no se cambia la configuración, no se promueve ninguna celda y H1 sigue sellado. La manual ya usa la frecuencia ganadora; su stop 300 no está justificado por edge, solo por volumen de operaciones en la muestra.

---

## 1. Diseño y método

### 1.1 Matriz 2×2

| Celda | Stop (`max_sl_ticks`) | Frecuencia (`validity`/`retest`) | qty | Fuente |
|---|---:|---|---:|---|
| **A** | 200 | 150/12 | 1 | original ya medido |
| **B** | 200 | 210/24 | 1 | P2 ya medido (`sl_200`) |
| **C** | 300 | 150/12 | 1 | corrida nueva a qty=1 |
| **D** | 300 | 210/24 | 1 | manual ya medido |

**Por qué la frecuencia es el par 150/12 vs 210/24.** El cambio que separa la original de la manual no es solo `setup_validity_minutes`: también cambia `retest_tolerance_ticks` (150/12 → 210/24). El factor de frecuencia se define como **el perfil completo que realmente cambió**, no como validez con retest fijo. Un factorial “solo validez” (150/24 vs 210/24) no corresponde a ninguna de las dos configuraciones establecidas y añadiría celdas que no existen en el histórico. Este diseño 2×2 es el mínimo que separa stop y frecuencia con las configuraciones reales.

**qty=1.** Se fija `risk.max_contracts=1`. Con stop ≤ 300 ticks, el riesgo de un contrato cabe en el 1 % de 25.000 USD (300 ticks × 0,50 USD = 150 USD < 250 USD), así que no hay operaciones con qty=0 por sizing. En la celda C las 60 operaciones tienen qty=1; en A/B/D el R se toma de las operaciones ya registradas, cuyo `r_multiple` es por unidad de riesgo y no depende de qty.

**Métricas.** R total, R medio por operación, R-PF (R positivos / |R negativos|), R-DD máximo sobre la curva de R, **RDD_R = R total / R-DD**, win rate, R medio ganador/perdedor, máxima racha de pérdidas, USD a qty=1 (`pnl/qty`) y USD dinámico histórico. El R-DD se calcula sobre la secuencia concatenada de W1–W6, no sobre una curva continua con sizing arrastrado; es la misma convención de los informes W1–W6.

### 1.2 Reutilización y control

- **A/B/D** se reconstruyen desde `_fresh_original_1x.json`, `progreso.json#sl_200` y `_fresh_manual_1x.json`. No se re-simulan completas: el R por operación ya está medido y es invariante a qty.
- **C** se ejecuta nueva: `data/config.json` en memoria con `max_contracts=1`, `max_sl_ticks=300`, `setup_validity_minutes=150`, `retest_tolerance_ticks=12`; W1–W6, 362 sesiones, 60 operaciones, todas qty=1 y 0 sesiones con qty=0.
- **Control D-W1 a qty=1:** se ejecuta para validar la reconstrucción; reproduce **19/19 operaciones**, **R 14,30** y **USD 1.322,94**, exactamente igual que la celda D derivada. Esto valida que qty=1 no altera señales, precios, R ni la reconstrucción de A/B/D.
- **Holdout:** el script aborta si una sesión es ≥ `2026-07-01`; las seis ventanas terminan en `2026-06-30`. No se leyó ni ejecutó H1.

### 1.3 Artefactos

| Artefacto | Contenido |
|---|---|
| `research/factorial_stop_validity.py` | corrida C + control, análisis factorial y salidas |
| `reports/backtest/_factorial_cell_c.json` | 60 operaciones nuevas de C, por ventana, con procedencia |
| `reports/backtest/_factorial_control_w1.json` | control D-W1 a qty=1 |
| `reports/backtest/factorial_stop_validity.json` | métricas, efectos, ventanas y panel de contratos |
| `reports/backtest/factorial_stop_validity.csv` | tabla plana de las cuatro celdas |

---

## 2. Resultados por celda

| Celda | Stop | Frecuencia | Ops | R total | R/op | R-PF | R-DD | RDD_R | Win % | Ganador R | Perdedor R | Máx. racha | USD qty=1 | USD dinámico | qty máx. |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| **A** | 200 | 150/12 | 38 | 4,98 | 0,1311 | 1,2012 | 10,15 | 0,4906 | 31,58 | 2,4775 | −0,9900 | 10 | 378,88 | 661,44 | 5 |
| **B** | 200 | 210/24 | 46 | 11,56 | **0,2513** | **1,4126** | 10,15 | **1,1389** | 32,61 | 2,6387 | −0,9340 | 10 | 882,46 | 2.471,78 | 10 |
| **C** | 300 | 150/12 | 60 | **0,97** | **0,0162** | **1,0244** | 13,15 | **0,0738** | 31,67 | 2,1447 | −0,9945 | 13 | 124,10 | 124,10 | 1 |
| **D** | 300 | 210/24 | 72 | **13,19** | 0,1832 | 1,3064 | 13,15 | 1,0030 | 36,11 | 2,1631 | −0,9567 | 13 | **1.361,72** | 2.022,94 | 10 |

**Lectura:**

- **C es la peor celda.** Con stop 300 y frecuencia 150/12 produce 60 operaciones, pero solo **0,97 R** y PF **1,024**: un sistema prácticamente plano, con el R-DD más alto (13,15, empatado con D) y la peor racha (13, empatada con D). El stop 300 no compensa la frecuencia corta; la empeora.
- **D es la celda con más R y USD a qty=1**, pero su ventaja sobre B es de **volumen**: 72 vs 46 operaciones, **+1,63 R** y **+3,00 R de DD**. Su R/op (0,1832) y su RDD_R (1,003) son inferiores a B (0,2513 y 1,139).
- **B es la mejor por calidad:** mayor R/op, mayor R-PF, mayor RDD_R y menor R-DD (10,15 vs 13,15), con 46 operaciones. Es la celda que mejor paga por unidad de riesgo y por unidad de drawdown.
- **A** (original 200/150) es intermedia: 4,98 R totales, 0,1311 R/op, PF 1,201, RDD_R 0,491. La frecuencia 210/24 la mejora en todas las métricas de R (B); el stop 300 sin cambiar frecuencia la destruye (C).

---

## 3. Factorial: efectos principales

### 3.1 En R por operación

| Efecto | R/op | Lectura |
|---|---:|---|
| Stop 200 → 300 en frecuencia 150 | **−0,1149** | el stop 300 destruye edge con frecuencia corta |
| Stop 200 → 300 en frecuencia 210 | **−0,0681** | sigue siendo negativo con frecuencia larga |
| **Stop: efecto principal** | **−0,0915** | 300 es peor que 200 en promedio |
| Frecuencia 150 → 210 con stop 200 | **+0,1202** | mejora clara |
| Frecuencia 150 → 210 con stop 300 | **+0,1670** | mejora aún mayor porque C es muy malo |
| **Frecuencia: efecto principal** | **+0,1436** | el lever dominante |
| Interacción | +0,0468 | la frecuencia rinde más con stop 300; no rescata a C |

### 3.2 En R total

| Efecto | R total | Lectura |
|---|---:|---|
| Stop 200 → 300 en frecuencia 150 | **−4,01** | C (0,97) vs A (4,98) |
| Stop 200 → 300 en frecuencia 210 | **+1,63** | D (13,19) vs B (11,56), por 26 ops extra |
| **Stop: efecto principal** | **−1,19** | en promedio, 300 no añade R |
| Frecuencia 150 → 210 con stop 200 | **+6,58** | B (11,56) vs A (4,98) |
| Frecuencia 150 → 210 con stop 300 | **+12,22** | D (13,19) vs C (0,97) |
| **Frecuencia: efecto principal** | **+9,40** | el lever que sí añade R |
| Interacción | +5,64 | el beneficio de frecuencia es mayor con stop 300 |

**La aparente mejora de total del stop 300 en 210/24 es un efecto de volumen, no de edge.** D añade 26 operaciones frente a B y solo +1,63 R; esas operaciones extra rinden **0,063 R/op**, muy por debajo del 0,2513 R/op de B. Además elevan el R-DD de 10,15 a 13,15. El stop 300 no mejora la calidad de la estrategia; compra más operaciones marginales.

### 3.3 Descomposición manual vs original

Tomando el camino A → C → D:

| Paso | Δ R total | Δ R/op | Δ R-DD | Lectura |
|---|---:|---:|---:|---|
| A → C: stop 300, misma frecuencia 150/12 | **−4,01** | −0,1149 | +3,00 | el stop 300 resta |
| C → D: frecuencia 210/24, mismo stop 300 | **+12,22** | +0,1670 | 0,00 | la frecuencia suma y no cuesta DD |
| **A → D: manual vs original** | **+8,21** | **+0,0521** | +3,00 | **la frecuencia más que compensa el stop** |

**Conclusión de la descomposición:** la manual gana **+8,21 R** frente a la original, pero ese resultado es **frecuencia +12,22 menos stop −4,01**. El stop 300 no es la fuente de la mejora: es un lastre que la frecuencia 210/24 compensa. Si se hubiera mantenido la frecuencia 150/12, el stop 300 habría dejado la estrategia casi plana (C: 0,97 R).

La comparación B → D aísla el stop con la frecuencia ya larga: **+1,63 R totales, −0,0681 R/op, +3,00 R-DD**. No es una mejora limpia; es más volumen con peor calidad y más drawdown.

---

## 4. Robustez por ventana

R/op por celda y efectos principales (stop = 300 vs 200; frecuencia = 210/24 vs 150/12), promediados sobre el otro factor:

| Ventana | A (200/150) | B (200/210) | C (300/150) | D (300/210) | Efecto stop | Efecto frecuencia |
|---|---:|---:|---:|---:|---:|---:|
| W1 | 0,5650 | 0,7021 | 0,5277 | 0,7526 | **+0,0066** | **+0,1810** |
| W2 | 0,1125 | 0,6200 | −0,2583 | 0,2463 | −0,3723 | **+0,5060** |
| W3 | −0,1289 | −0,1918 | −0,1507 | −0,2453 | −0,0377 | **−0,0788** |
| W4 | 2,3600 | 3,0033 | 0,8218 | 1,0300 | −1,7557 | **+0,4257** |
| W5 | −1,0140 | −1,0133 | −1,0140 | −1,0133 | 0,0000 | **+0,0007** |
| W6 | −0,4000 | −0,3129 | −0,5636 | −0,5190 | −0,1848 | **+0,0658** |

- **Frecuencia:** positiva en **5/6** ventanas; solo W3 es negativa (−0,0788). W5 es un régimen perdedor común: las cuatro celdas quedan en ≈−1,014 R/op y no discriminan. Es el efecto más estable.
- **Stop:** positivo solo en W1 (+0,0066), negativo en W2/W3/W4/W6 y cero en W5. **4/6 negativas**. La dirección no es robusta a favor del stop 300.
- **W4** es el caso más claro contra el stop 300: con frecuencia 210/24, D (1,0300) queda muy por debajo de B (3,0033); el stop 300 pierde 1,7557 R/op en esa ventana. La frecuencia ayuda, pero no lo compensa.
- **W5** no discrimina: todas las celdas pierden aproximadamente −1,014 R/op; no hay señal para ranking.

---

## 5. Contratos: el confusor que el USD ocultaba

| Celda | qty media | USD dinámico | USD qty=1 | Δ USD por contratos | % del USD dinámico | R total |
|---|---:|---:|---:|---:|---:|---:|
| A (200/150) | 3,7895 | 661,44 | 378,88 | +282,56 | 42,72 % | 4,98 |
| B (200/210) | 4,9565 | 2.471,78 | 882,46 | **+1.589,32** | **64,30 %** | 11,56 |
| D (300/210) | 3,7361 | 2.022,94 | 1.361,72 | +661,22 | 32,69 % | 13,19 |
| C (300/150) | 1,0000 | 124,10 | 124,10 | 0,00 | 0,00 % | 0,97 |

- **El R no cambia con qty; el USD sí.** B y D tienen el mismo R total que sus versiones a qty=1, pero el 64,30 % y el 32,69 % de su USD dinámico, respectivamente, es sizing. A también tenía un 42,72 % de sizing (qty 2–5).
- **El ranking USD se invierte al fijar qty=1.** En dinámico, B supera a D por **+448,84 USD** (el viejo `sl_200`). A qty=1, B queda **−479,26 USD** por debajo de D. La diferencia no es edge: B tiene qty media **4,9565** frente a **3,7361** de D. El stop 200 permite más contratos por operación y eso infla el USD dinámico.
- **Corrección al ranking anterior:** el `sl_200` +448,84 USD de la lista de mejoras **no es una mejora de R**. A qty=1 es negativo en USD total frente a la manual. Lo que sí mejora el stop 200 es la **calidad** (R/op, PF, RDD_R), no el total de la muestra.
- **Contratos = 0 R.** Fijar qty=1 no es una hipótesis de estrategia: es la forma de comparar edge sin el confusor de sizing. Cualquier ranking en USD dinámico mezcla las tres cosas (stop, frecuencia y contratos).

---

## 6. Re-ranking de levers

### 6.1 Rankings por objetivo

| Puesto | R total | R/op | RDD_R | USD qty=1 |
|---:|---|---|---|---|
| 1 | **D** 13,19 | **B** 0,2513 | **B** 1,1389 | **D** 1.361,72 |
| 2 | **B** 11,56 | **D** 0,1832 | **D** 1,0030 | **B** 882,46 |
| 3 | **A** 4,98 | **A** 0,1311 | **A** 0,4906 | **A** 378,88 |
| 4 | **C** 0,97 | **C** 0,0162 | **C** 0,0738 | **C** 124,10 |

**No hay una celda dominante.** D domina el total (R y USD a qty=1); B domina la calidad y el retorno por drawdown. La elección depende del objetivo:

- **Si se prioriza el beneficio total observado en W1–W6 a 1 contrato:** D (manual, 300/210) es la mejor celda: 13,19 R y 1.361,72 USD. Pero su ventaja sobre B es de 26 operaciones extra que aportan solo +1,63 R y +3,00 R-DD; no es una ventaja de edge.
- **Si se prioriza R/op, PF o RDD_R:** B (200/210) es la mejor: 0,2513 R/op, PF 1,413, RDD_R 1,139, con 46 operaciones y R-DD 10,15.
- **C (300/150)** queda última en todas las métricas relevantes: 0,0162 R/op, PF 1,024, RDD_R 0,074. Es la prueba de que el stop 300 sin la frecuencia 210/24 no funciona.

### 6.2 Qué lever es cada cosa

1. **Frecuencia 210/24 — el lever rentable y robusto.** Efecto principal **+0,1436 R/op** y **+9,40 R totales**, positivo en 5/6 ventanas, sin coste de R-DD en ninguna rama de stop. Es la única palanca que mejora a la vez total y calidad. **Ya está en la manual.**
2. **Stop 300 — no es un lever de edge.** Efecto principal **−0,0915 R/op**; 4/6 ventanas negativas. En 210/24 añade +1,63 R totales solo a base de 26 operaciones marginales (+0,063 R/op) y +3,00 R-DD. En 150/12 destruye la estrategia (C: 0,97 R, PF 1,024). **No está justificado por edge; solo por volumen muestral.**
3. **Contratos — no son edge.** El R es invariante; el USD dinámico escala con qty. El +448,84 USD del `sl_200` se convierte en −479,26 USD a qty=1. **El ranking USD anterior no sirve para elegir stop.**

### 6.3 Lectura para la configuración manual

- La manual (D) **acierta en la frecuencia** (210/24) y **no acierta por el stop**: su ganancia frente a la original es frecuencia +12,22 R menos stop −4,01 R. El stop 300 es un lastre que la frecuencia compensa.
- Si se buscara **calidad/DD** sin cambiar la frecuencia, B (stop 200) es mejor: +0,0681 R/op, +3,00 R-DD menos, PF +0,106 y RDD_R +0,136. Pero pierde **1,63 R totales** y **479,26 USD** a qty=1 frente a D por tener 26 operaciones menos. No es una mejora de total; es un cambio de perfil.
- **No se propone cambiar la configuración en esta pasada.** El paso 3 es un re-ranking, no una promoción. No hay forward ni H1; la muestra es la misma W1–W6 y ya está muy explorada.

---

## 7. Integridad y reproducción

### 7.1 Lo que no se tocó

| Comprobación | Resultado |
|---|---|
| 8765 | PID **16016**, listener `127.0.0.1:8765`, inicio 17:16:56; sin parada, reinicio ni llamada a la API |
| Log del 8765 | `logs/server_8765_20261125.log`, **580 B**, mtime 17:19:07; sin cambios |
| DB del 8765 | `profiles/live_8765/yedbot.db` leída en modo read-only: **72 trades / 730 eventos**; sin escrituras |
| Configuración | `data/config.json` y `profiles/live_8765/config.json` con SHA-256 `9bf4f9c7…e29479f`; sin cambios |
| Locks | `docs/protocolo_backtest.lock.json` `55d89872…` y `docs/pre_registro_sl200_10c_vs_p1.lock.json` `38e818f6…`; sin cambios |
| Holdout | No leído ni ejecutado; W1–W6 termina en `2026-06-30` y el script aborta si ve una sesión ≥ `2026-07-01` |
| Configuración aplicada | Solo en memoria (`apply_settings`); no se escribió ningún `config.json` |

### 7.2 Reproducción

```bash
# Corrida nueva de C + control D-W1 (repite aunque existan los artefactos)
PYTHONIOENCODING=utf-8 python research/factorial_stop_validity.py --run --force --workers 4

# Solo análisis sobre los artefactos existentes
PYTHONIOENCODING=utf-8 python research/factorial_stop_validity.py --analyze
```

La corrida nueva de C + control terminó en **178,9 s (≈3 min)** con 4 procesos; la simulación de cada ventana tardó 32–42 s. El control D-W1 dio **19/19 operaciones, R 14,30, USD 1.322,94**, idéntico a la celda D derivada. Las salidas quedan en `reports/backtest/factorial_stop_validity.{json,csv}`.

### 7.3 Limitaciones

- **In-sample:** W1–W6 es la misma muestra de desarrollo ya usada para elegir la manual y las 25 variantes. Este factorial reordena evidencia, no crea evidencia nueva.
- **Sin test de significación:** no se calculan IC ni p-valores para los efectos. La robustez se reporta por ventana (5/6 y 4/6), no como inferencia formal. Cuatro celdas y seis ventanas no justifican un test fuerte.
- **A/B/D reconstruidas:** no se re-simularon; se usan sus operaciones ya medidas. El control D-W1 valida la invariancia a qty, y el R es por unidad de riesgo por construcción. Si se quisiera una réplica completa, habría que correr las cuatro celdas desde cero; no se hizo para no duplicar cómputo sin cambiar la conclusión.
- **Frecuencia bundle:** el factor 150/12 vs 210/24 no separa validez de retest. Un diseño 2×2×2 (validez × retest × stop) requeriría cuatro celdas nuevas y aumentaría el multiple testing; no se ejecutó.
- **R-DD concatenado:** el DD se calcula sobre trades de W1–W6 con capital 25.000 y sin compounding; no es el DD de una curva continua con sizing arrastrado.
- **qty=1:** elimina el confusor de contratos, pero también elimina el compounding y el sizing dinámico. Los USD a qty=1 no son la rentabilidad que habría producido la configuración con 10 contratos.
- **Sin forward:** no hay muestra independiente. H1 sigue sellado y no se usa para validar nada de este informe.

---

## 8. Cierre

**El paso 3 re-rankea los levers así:**

1. **Frecuencia 210/24:** el único lever que mejora total y calidad de forma robusta (+0,1436 R/op, +9,40 R, 5/6 ventanas, sin coste de DD). Ya está en la manual.
2. **Stop 300:** no es un lever de edge (−0,0915 R/op, 4/6 ventanas negativas). En 150/12 hunde la celda C a 0,97 R; en 210/24 solo compra 26 operaciones marginales (+1,63 R, +3,00 R-DD). La manual no gana por el stop.
3. **Contratos:** cero efecto en R; todo el efecto es sizing. El +448,84 USD del `sl_200` se convierte en −479,26 USD a qty=1. El ranking USD anterior no es un ranking de edge.

**No se adopta ninguna mejora, no se cambia la configuración y no se toca el 8765.** Bajo el criterio de rentabilidad ajustada a riesgo, la recomendación única es **B (200/210)**, no D; D solo sería preferible bajo un mandato explícito de total absoluto, que este informe no adopta. La diferencia entre ambas no es el stop: es la frecuencia y el sizing. El plan de validación está en §9. **H1 sigue sellado.**

---

## 9. Propuestas priorizadas por rentabilidad ajustada a riesgo

### 9.1 Criterio y orden

El criterio de este informe es **rentabilidad por unidad de riesgo**, no el R total bruto: primero **RDD_R**, después **R/op** y **PF**; el R total y el USD a qty=1 se usan como guardrails, no como prueba de edge. El orden de las propuestas es:

1. **Consolidar la frecuencia 210/24** — el lever dominante y ya presente en la manual.
2. **Stop 200 (B)** — el único candidato de mejora bajo el criterio risk-adjusted.
3. **qty=1 como decisión separada de sizing** — no escalar contratos para “mejorar” el edge.

Todas las cifras son **in-sample W1–W6** y describen lo observado, no una promesa forward.

### 9.2 Resumen de propuestas

| # | Propuesta | Cambio exacto | Evidencia del factorial | Impacto observado | Coste / riesgo |
|---:|---|---|---|---|---|
| 1 | **Consolidar frecuencia 210/24** | Ninguno: mantener `setup_validity_minutes=210` y `retest_tolerance_ticks=24`; no volver a 150/12 | Efecto principal **+0,1436 R/op**, **+9,40 R**, positivo 5/6 ventanas. A→B: +0,1202 R/op, +6,58 R, PF 1,2012→1,4126, RDD_R 0,4906→1,1389, R-DD 10,15→10,15, 38→46 ops. C→D: +0,1670, +12,22, PF 1,0244→1,3064, RDD_R 0,0738→1,0030, R-DD 13,15→13,15, 60→72 ops | Mayor edge y mayor total; no aumenta el R-DD en ninguna rama | Más operaciones y exposición (38→46 y 60→72); W3 negativo; in-sample |
| 2 | **Stop 200 (B) como candidato** | `risk.max_sl_ticks: 300 → 200`; mantener 210/24, qty=1 y el resto igual | B: **0,2513 R/op**, 11,56 R, PF **1,4126**, R-DD **10,15**, RDD_R **1,1389**, 46 ops, USD1 **882,46**. D: 0,1832, 13,19, 1,3064, 13,15, 1,0030, 72, 1.361,72 | Δ **+0,0681 R/op (+37,2 %)**, RDD_R **+0,1359 (+13,5 %)**, PF **+0,1062 (+8,1 %)**, R-DD **−3,00 (−22,8 %)**; pero **−1,63 R totales (−12,4 %)**, **−479,26 USD1 (−35,2 %)** y **−26 ops**. R/op gana W2/W3/W4/W6, pierde W1 y empata W5 | Menos total absoluto y menos operaciones; stop más ajustado; W1 peor; in-sample; sin OOS |
| 3 | **qty=1 / no escalar como edge** | Mantener `max_contracts=1` en la validación; no subir qty ni `risk_per_trade_pct` para buscar USD | R invariante. B: +1.589,32 USD dinámicos por sizing (**64,30 %** de su USD dinámico); D: +661,22 (**32,69 %**); A: +282,56 (**42,72 %**). `sl_200` pasa de **+448,84** frente a la manual en dinámico a **−479,26** a qty=1 | Escalar qty multiplica USD y DD, pero **no** R/op, PF ni RDD_R | Apalancamiento, margen, slippage y path; decisión de capital separada; el 8765 no se toca |

### 9.3 Recomendación única: B, no D

**La recomendación es B (stop 200, frecuencia 210/24), bajo el criterio de rentabilidad ajustada a riesgo. No es un empate con D.**

- **B gana en calidad:** +37,2 % de R/op (0,2513 vs 0,1832), +13,5 % de RDD_R (1,1389 vs 1,0030), +8,1 % de PF (1,4126 vs 1,3064) y −22,8 % de R-DD (10,15 vs 13,15). Además gana en R/op en **W2, W3, W4 y W6**, pierde en **W1** y empata en **W5**.
- **D gana en total absoluto:** +14,1 % de R total (13,19 vs 11,56) y +54,3 % de USD a qty=1 (1.361,72 vs 882,46). B conserva el **87,6 %** del R total de D. Pero la ventaja de D son **26 operaciones extra** que aportan **+1,63 R** (0,0627 R/op), muy por debajo del 0,2513 R/op de B, y **+3,00 R-DD**. Es volumen, no edge.
- **Qué se prioriza:** la rentabilidad por unidad de riesgo y por unidad de drawdown. **Qué se sacrifica:** 1,63 R totales y 479,26 USD a qty=1. **Qué se gana:** +0,0681 R/op, +0,1359 RDD_R, +0,1062 PF y 3,00 R menos de DD.
- **D no es una mejora, es el statu quo.** Solo sería preferible si el mandato explícito fuera “máximo R total absoluto en la muestra”, aceptando 26 operaciones marginales y más DD. Este informe no adopta ese mandato.
- **No se aplica al 8765.** B es el candidato a validación fuera de muestra; la configuración viva sigue intacta hasta que exista esa validación.

### 9.4 Sizing: decisión separada del edge

- **El R es invariante a qty.** B y D conservan exactamente su R total, R/op, PF y RDD_R al pasar a qty=1; solo cambia el USD. En R, qty **no gana ni pierde ninguna de las seis ventanas**: las seis son idénticas; el efecto es exclusivamente USD/DD. El “extra” de USD de las celdas de qty alta es **apalancamiento**: 64,30 % en B, 32,69 % en D y 42,72 % en A.
- **El ranking USD se invierte al fijar qty=1.** `sl_200` pasa de **+448,84 USD** frente a la manual en dinámico a **−479,26 USD** a qty=1. Por tanto, el USD dinámico **no** sirve para elegir stop, frecuencia ni “mejor estrategia”; mezcla edge con sizing.
- **Recomendación de qty:** mantener **qty=1** para la validación del edge y **no elevar contratos ni `risk_per_trade_pct`** como si fuera una mejora de estrategia. Escalar qty multiplica linealmente el USD y el drawdown, pero no mejora R/op, PF ni RDD_R; añade riesgo de margen, slippage y path dependence.
- **Si se decide escalar capital**, que sea una decisión separada de asignación de capital, con presupuesto de riesgo propio y pre-registrada; no se mezcla con la hipótesis B vs D. El `max_contracts=10` actual del 8765 **no se modifica** en esta misión.

### 9.5 Qué NO hacer

1. **No adoptar el stop 300 por el R total bruto de D.** Su total se compra con 26 operaciones de 0,0627 R/op y +3,00 R-DD; en 150/12 el stop 300 deja C en **0,97 R, PF 1,0244 y RDD_R 0,0738**. El stop 300 no es un lever de edge.
2. **No usar el ranking USD dinámico para elegir stop o contratos.** `sl_200` +448,84 → −479,26 a qty=1; B tiene 64,30 % de su USD dinámico como sizing.
3. **No extrapolar a intradía, otros símbolos, otros timeframes ni otra sesión.** La evidencia es NQ/MNQ, ORB+SMT, W1–W6; no hay ninguna prueba fuera de ese marco.
4. **No subir qty para “mejorar la rentabilidad”.** El apalancamiento no cambia el edge y aumenta el DD y el riesgo operativo.
5. **No adoptar las exclusiones horarias ni parámetros nuevos con esta evidencia.** No se probaron en este factorial; la lista anterior era USD y no pasó RC/RDD. Añadirlos ahora sería otro barrido in-sample.
6. **No abrir H1 ni reutilizar W1–W6 como confirmación.** H1 sigue sellado; W1–W6 ya está explorado y no es una muestra independiente.

### 9.6 Plan mínimo de validación antes de tocar dinero real

**Estado:** H1 (`2026-07-01 → 2026-10-30`) y W7+ siguen **sellados**. No se leen, no se ejecutan y no se usan para este informe. La validación que sigue es un plan, no una corrida.

**Diseño mínimo:**

1. **Una sola hipótesis primaria:** B (200/210) vs D (300/210), con **qty=1**, mismo instrumento, misma sesión, mismos costes y misma definición de R/op. Pre-registrar y bloquear el protocolo antes de abrir la muestra.
2. **Test primario:** bootstrap/permutación por bloques de sesión, pareado por sesión, **α = 0,05** a dos colas. Si se miran A/C, seis ventanas o subgrupos, aplicar **Holm** a los secundarios o **White Reality Check** con α familiar 0,05; no hacer fishing de ventanas.
3. **Muestra mínima:** **≥100 operaciones de B** en una muestra nueva. H1 tiene 85 sesiones; al ritmo observado de B (46/362 ≈ 0,127 ops/sesión) serían **≈11 operaciones**, insuficientes. Cien operaciones de B exigirían **≈787 sesiones** al mismo ritmo; si no se dispone de una muestra así, no se puede confirmar con el efecto observado y no se toca dinero real.
4. **Umbral de confirmación:**
   - **Δ R/op (B − D) ≥ +0,05 R** y **IC 95 % inferior > 0**.
   - **RDD_R(B) ≥ RDD_R(D) + 0,10**.
   - **R total(B) ≥ 85 % del R total(D)** — se acepta perder hasta 15 % de total por mejor calidad; el 87,6 % observado pasaría, un 15 %+ no.
   - **PF(B) ≥ PF(D)** y **R-DD(B) ≤ R-DD(D)**.
   - **Coste x2:** el Δ R/op debe seguir siendo > 0.
   - Si el mandato fuera total absoluto, el umbral sería D ≥ B + 10 % de R total con RDD_R no peor; **no es el criterio recomendado**.
5. **Qué lo confirmaría:** superar el test primario y todos los guardrails anteriores en la muestra OOS, con el protocolo bloqueado y sin cambios de parámetros. Si falla cualquiera, **no se cambia la configuración** y no se toca dinero real.
6. **Qué no se prueba:** exclusiones horarias, parámetros nuevos, otros símbolos, intradía, otro timeframe o otra sesión. No hay evidencia y añadirlos sería multiple testing.

### 9.7 Integridad de esta edición

Esta edición solo modifica este documento; no re-ejecuta backtests, no re-barre parámetros y no toca artefactos de resultados. Verificación final: **8765 PID 16016**, listener `127.0.0.1:8765`, log **580 B** sin cambios; DB `profiles/live_8765/yedbot.db` leída en **read-only: 72 trades / 730 eventos**; `data/config.json` y `profiles/live_8765/config.json` SHA-256 `9bf4f9c7…e29479f`; locks `55d89872…` y `38e818f6…`; holdout no leído ni ejecutado. **H1 sigue sellado.**
