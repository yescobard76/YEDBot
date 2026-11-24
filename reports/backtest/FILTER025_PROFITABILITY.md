# Rentabilidad comparada — filtro 0,25, P2, manual 8765 y original

**Estado:** histórico in-sample. **No es promoción.**
**Ámbito:** W1–W6, 2025-01-10 → 2026-06-30, 362 sesiones. Holdout H1
2026-07-01 → 2026-10-30 **sellado y no leído**.
**Backtests nuevos:** cero. Este informe agrega artefactos existentes y consulta
la configuración viva en modo lectura.
**Veredicto de gates:** `INCONCLUSO`; ver `FILTER025_GATES.md` y
`filter025_gates.json`.

## 1. Chequeo de la instancia 8765

El servidor HTTP de 8765 responde, pero el motor está **detenido**:
`GET /api/status` devuelve `status="stopped"`, modo paper y feed CSV conectado.
No hay P&L live nuevo que valorar.

La configuración viva leída en `/api/config` y en
`profiles/live_8765/config.json` es:

| Parámetro | 8765 vivo | Original 38 | P2 | Filtro 0,25 |
|---|---:|---:|---:|---:|
| `max_contracts` | 10 | 5 | 10 | 10 (aceptadas con qty ≤5) |
| `max_sl_ticks` | **300** | 200 | 200 | 200 |
| `setup_validity_minutes` | 210 | 150 | 210 | 210 |
| `retest_tolerance_ticks` | 24 | 12 | 24 | 24 |
| `min_stop_or_ratio` | **0,00** | 0,00 | 0,00 | **0,25** |

`profiles/live_8765/config.json` y `data/config.json` tienen el mismo SHA-256
(`9bf4f9c7…`). **8765 no está aplicando el filtro 0,25**: su ratio mínimo es
0,00 y su perfil es el manual `10/300/210/24`. Tampoco es exactamente P2, porque
P2 usa `max_sl_ticks=200`.

El artefacto existente `forward_validation.json` identifica ese perfil manual
con 72 operaciones W1–W6, +2.022,94 USD, PF 1,22 y DD 2.891,66. Es la referencia
histórica del perfil vivo, no una validación forward.

## 2. Muestras y composición

| Perfil | Configuración | Ops | Largas / cortas | Max qty / ops>5 / stop caps | Sesiones | Meses activos | Fee base |
|---|---|---:|---:|---:|---:|---:|---:|
| Original | 5/200/150/12 | 38 | 21 / 17 | 5 / 0 / 50 | 38 (10,5 %) | 17 / 18 | 178,56 |
| Manual 8765 | 10/300/210/24 | 72 | n/d en artefacto | 10 / 17 / 37 | 72 ops (19,9 % de densidad; únicas n/d) | n/d | n/d |
| P2 | 10/200/210/24 | 46 | 26 / 20 | 10 / 17 / 63 | 46 (12,7 %) | 17 / 18 | 282,72 |
| P2 + filtro 0,25 | 10/200/210/24 + ratio 0,25 | 17 | 9 / 8 | ≤5 / 0 / n/d | 17 (4,7 %) | 10 / 18 | 55,80 |
| Rechazados por el filtro | P2 con ratio <0,25 | 29 | 17 / 12 | n/d / n/d / n/d | 29 | 13 / 18 | 226,92 |

La fila manual 72 conserva los agregados que sí están en
`_manual_w1_w6_analysis.log` y `forward_validation.json`: 72 operaciones, 37
stop caps, 17 operaciones con qty>5 y max qty10. **No conserva** el listado
trade-by-trade, `duration_sec`, `by_direction` ni fees; el SQLite de
`profiles/live_8765` tiene `trades=0`. Por eso esas celdas se marcan `n/d` en
lugar de inventarlas. Completarlas exigiría una corrida nueva, prohibida por
este encargo.

La comparación de selección correcta es **P2 46 → filtro 17**. El original 38
no es el contrafactual del filtro: tiene otra frecuencia, otro límite de stop y
otro tamaño máximo. La comparación original → filtro sirve para valorar la
política completa, pero mezcla perfil y selección.

## 3. Resultado económico

Cifras de los artefactos, sin reejecutar estrategia:

La **expectativa por trade** se mide de dos formas: dinero (neto/op) y R medio.
El **profit factor** es USD (no el PF-R del gate), y la **tasa de acierto** es el
porcentaje de operaciones con P&L positivo. El drawdown es el de la curva de
trades concatenados desde 25.000 USD.

| Perfil | Ops | Neto USD | Expectativa/op USD | Expectativa/op R | Profit factor | DD USD | DD % | Tasa de acierto | R total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Original | 38 | +661,44 | +17,41 | +0,1311 | 1,13 | 1.967,82 | 7,14 % | 31,58 % | +4,98 |
| Manual 8765 | 72 | +2.022,94 | +28,10 | +0,18 | 1,22 | 2.891,66 | 9,79 % | 36,10 % | +13,19 |
| P2 | 46 | +2.471,78 | +53,73 | +0,2513 | 1,39 | 2.304,46 | 7,84 % | 32,61 % | +11,56 |
| **Filtro 0,25** | **17** | **+4.202,20** | **+247,19** | **+1,1088** | **4,25** | **946,38** | **3,36 %** | **58,82 %** | **+18,85** |
| Rechazados | 29 | −1.730,42 | −59,67 | −0,2514 | 0,65 | 2.828,74 | — | 17,24 % | −7,29 |

Lectura directa:

- El filtro es el mejor de la muestra en **neto, neto por operación, R medio,
  PF, drawdown y acierto**. Duplica con creces el neto del original
  (+4.202,20 vs +661,44; +535,3 %) y reduce el DD un 51,9 %.
- Pero lo hace con **17 operaciones**, no con 38. El PF de 4,25 no es comparable
  en precisión con el 1,13 de una muestra de 38; la diferencia de tamaño es
  parte del problema, no un detalle.
- El perfil vivo 8765 gana más que el original en absoluto (+1.361,50), pero
  tiene **peor DD** (+923,84) y un PF de 1,22, inferior al 1,39 de P2.
- El filtro elimina un cohorte que pierde −1.730,42. Esa es exactamente la
  mejora bruta frente a P2: 2.471,78 + 1.730,42 = 4.202,20.

## 4. Exposición temporal y concentración trimestral

W1 = 2025-Q1, W2 = 2025-Q2, W3 = 2025-Q3, W4 = 2025-Q4, W5 = 2026-Q1,
W6 = 2026-Q2. Neto en USD:

| Perfil | W1 | W2 | W3 | W4 | W5 | W6 | Total |
|---|---:|---:|---:|---:|---:|---:|---:|
| Original | +364,82 | +268,40 | −110,46 | +2.034,12 | −1.036,52 | −858,92 | +661,44 |
| Manual 8765 | +2.735,34 | +418,30 | −1.088,22 | +2.461,48 | −1.497,14 | −1.006,82 | +2.022,94 |
| P2 | +2.245,50 | +642,76 | −460,32 | +1.960,60 | −1.497,14 | −419,62 | +2.471,78 |
| Filtro 0,25 | +1.622,84 | +554,80 | +63,96 | +1.960,60 | 0,00 | 0,00 | +4.202,20 |
| Rechazados | +622,66 | +87,96 | −524,28 | 0,00 | −1.497,14 | −419,62 | −1.730,42 |

### Tiempo en mercado

La duración sale de `duration_sec` de cada trade en
`p2_w1_w6_confirm.json` y `_manual_filter025_w1_w6.json`. La exposición se
calcula sobre 362 sesiones × 6,5 horas de ventana operable (09:00–15:30) =
2.353 horas; `max_concurrent_positions=1`, así que los tiempos no se solapan.

| Perfil | Tiempo total | Media por op | Mediana por op | Exposición de la ventana |
|---|---:|---:|---:|---:|
| Original 38 | 44,50 h | 70,26 min | 16,50 min | 1,891 % |
| P2 46 | 47,10 h | 61,43 min | 14,50 min | 2,002 % |
| Filtro 17 | 39,97 h | 141,06 min | 132,00 min | 1,699 % |
| Rechazados 29 | 7,13 h | 14,76 min | 5,00 min | 0,303 % |
| Manual 72 | **n/d** | **n/d** | **n/d** | **n/d**; solo 72 ops / 362 = 19,9 % de densidad |

El filtro tiene **menos** tiempo total en mercado que el original y que P2
(39,97 h vs 44,50/47,10 h), pero sus operaciones duran más del doble en media
(141,06 min vs 70,26/61,43 min). No es un perfil de alta exposición: su ventaja
no proviene de estar más tiempo expuesto. El manual 72 no permite calcular esta
dimensión sin una corrida nueva; su densidad de operaciones no es tiempo en
mercado y se deja explícitamente separada.

Concentración:

| Perfil | Trimestres activos | Mejor trimestre / positivo bruto | Top-2 / positivo bruto | Top-2 / neto | Top-5 trades / bruto |
|---|---:|---:|---:|---:|---:|
| Original | 6 / 6 | 76,26 % | 89,94 % | 362,68 % | 57,94 % |
| Manual 8765 | 6 / 6 | 48,71 % | 92,55 % | 256,89 % | n/d |
| P2 | 6 / 6 | 46,31 % | 86,74 % | 170,16 % | 41,17 % |
| Filtro 0,25 | **4 / 6** | 46,66 % | **85,28 %** | **85,28 %** | 61,23 % |

El “top-2 / neto” supera 100 % en original, manual y P2 porque otros trimestres
pierden. Es una medida de dependencia, no un porcentaje de ganancia. El gate Q3
usa el neto y, con esa definición, el filtro falla: **85,28 % > 80 %**. El
filtro también falla cobertura: 4/6 trimestres activos, con W5 y W6 vacíos, y
solo 10/18 meses activos; su racha sin operar es de 6 meses (P7 falla).

### El filtro no mejora en todos los regímenes

La diferencia trimestral P2 → filtro es:

| Trimestre | P2 | Filtro | Diferencia |
|---|---:|---:|---:|
| W1 2025-Q1 | +2.245,50 | +1.622,84 | **−622,66** |
| W2 2025-Q2 | +642,76 | +554,80 | **−87,96** |
| W3 2025-Q3 | −460,32 | +63,96 | **+524,28** |
| W4 2025-Q4 | +1.960,60 | +1.960,60 | 0,00 |
| W5 2026-Q1 | −1.497,14 | 0,00 | **+1.497,14** |
| W6 2026-Q2 | −419,62 | 0,00 | **+419,62** |
| **Total** | **+2.471,78** | **+4.202,20** | **+1.730,42** |

La mejora no viene de elegir mejores ganadores en todos los trimestres. Viene
de **evitar pérdidas en W3/W5/W6** (+2.441,04) y de sacrificar parte de las
ganancias de W1/W2 (−710,62). En 2026 el filtro no opera: no pierde, pero
tampoco gana. Esa asimetría es clave para interpretar el resultado y para el
riesgo de sobreajuste.

## 5. Coste estimado

| Perfil | Fees base | Coste stress | Neto stress | PF stress | DD stress | Coste absorbido |
|---|---:|---:|---:|---:|---:|---:|
| Original 38 | 178,56 | 357,12 (comisión 1,24/lado; slippage 2) | 347,38 | 1,07 | 2.064,14 | **−314,06** |
| Filtro 17 | 55,80 | reprecio exacto no disponible | 4.101,40 estimado | 4,0811 estimado | n/d | **−100,80 estimado** |
| Manual 72 | n/d | no hay stress exacto | n/d | n/d | n/d | n/d |
| P2 46 | 282,72 | no hay stress exacto | n/d | n/d | n/d | n/d |

El filtro tiene fees base de 55,80 (3,28/op) y el original de 178,56 (4,70/op);
P2 tiene 282,72 (6,15/op). El manual 72 no permite separar fees del neto en el
log, así que no se presenta un coste inventado. El coste exacto del filtro
tampoco existe: la única cifra de estrés del filtro es la estimación uniforme.

El stress exacto del original reduce el neto un **47,5 %** y el PF de 1,13 a
1,07; el DD empeora 96,32. El filtro solo tiene una estimación uniforme, no un
reprecio exacto: su PF estimado 4,0811 sigue siendo alto, pero **P6 queda
NO_EVALUABLE**. No se usa `stress_costs.json` del original como si fuera el
filtro.

## 6. Qué explica la diferencia: perfil, selección y falta de muestra

### Descomposición exacta

La contabilidad existente permite separar tres pasos sin reejecutar nada:

| Paso | Neto | Δ neto | PF | DD | Δ DD |
|---|---:|---:|---:|---:|---:|
| Original 38 (5/200/150/12) | +661,44 | — | 1,13 | 1.967,82 | — |
| P1: frecuencia 210/24, max5/SL200 | +1.992,26 | **+1.330,82** | 1,37 | 1.947,82 | −20,00 |
| P2: max_contracts 10 (SL200) | +2.471,78 | **+479,52** | 1,39 | 2.304,46 | +356,64 |
| Filtro 0,25: selección de 17/46 | +4.202,20 | **+1.730,42** | 4,25 | 946,38 | −1.358,08 |
| **Original → filtro** | **+4.202,20** | **+3.540,76** | **4,25** | **946,38** | **−1.021,44** |

Por tanto:

- **Perfil/frecuencia/contratos:** +1.810,34 USD (51,1 % de la diferencia total).
  No es efecto del filtro.
- **Selección del filtro:** +1.730,42 USD (48,9 % de la diferencia total).
  Es exactamente el resultado del cohorte rechazado.
- **Sobreajuste o falta de muestra:** no es un componente aditivo que se pueda
  cuantificar con estos datos. Lo que sí se puede afirmar es que **todo el
  +1.730,42 es in-sample**; el umbral se eligió en W1–W6 y no hay muestra
  forward. Por eso no se puede certificar que sea selección repetible en vez de
  sobreajuste.

### Señales de que el edge es frágil

- El filtro **empeora** W1 y W2 frente a P2; su ventaja agregada depende de no
  operar en W3/W5/W6, sobre todo de evitar 2026.
- Muestra: 17/80 totales, 9/8 largos/cortos frente a 20 por dirección; baseline
  46/60; cohorte 17/29 frente a 24/30; 2/6 bloques con muestra suficiente.
- 4/6 trimestres activos; W5/W6 vacíos; 10/18 meses activos; racha de 6 meses
  sin operar (P7 exige ≤4).
- Top-2 trimestres = 85,28 % del neto (Q3 exige ≤80 %); top-5 trades = 61,23 %
  del bruto.
- El bootstrap de selección es positivo, IC95 % [+0,3312, +2,3548] R, p≈0,006,
  con 10.000 réplicas válidas, pero **E2 no puede dar PASS** porque la muestra
  17/29 y la cobertura 4/6 no alcanzan sus precondiciones.
- El perfil vivo 8765 tampoco es una validación: es `10/300/210/24`, con SL
  300, y está detenido.

### Confianza

- **Confianza descriptiva del artefacto: alta.** Las cifras son consistentes
  entre los JSON, los hashes y los logs.
- **Confianza en que el filtro sea más rentable hacia adelante: baja /
  indeterminada.** Los gates globales son `INCONCLUSO`; no hay forward; el
  holdout está sellado. No se debe asignar capital por el PF 4,25 histórico.
- **Confianza en la comparación contra el original: media para el perfil
  (46 operaciones), baja para el filtro (17).** El original y P2 son más
  comparables entre sí; el filtro es una selección post hoc sobre P2.

## 7. Veredicto de rentabilidad

**En la muestra histórica W1–W6, el filtro 0,25 es más rentable que el original
y que P2 en términos absolutos y ajustados por riesgo.** El original gana
+661,44 con PF 1,13 y DD 1.967,82; el filtro gana +4.202,20 con PF 4,25 y DD
946,38. El perfil vivo 8765 gana +2.022,94 con PF 1,22 y DD 2.891,66: más que
el original en absoluto, pero por debajo de P2 y con más drawdown.

**Eso no demuestra que el filtro sea una mejora promocionable.** La diferencia
frente al original es 51,1 % perfil y 48,9 % selección; la selección es
in-sample, con 17 operaciones y cuatro trimestres activos. El veredicto de
gates sigue siendo **INCONCLUSO**, no PASS, y la decisión es **no promocionar**.
La formulación correcta es: “mejor rentabilidad histórica observada, con
confianza predictiva insuficiente”.

## 8. Mejoras propuestas, ordenadas por rentabilidad esperada

Ninguna está implementada. No se cambia la estrategia, el filtro 0,25, sus
umbrales, la configuración viva ni el holdout. “Datos actuales” significa que
la comparación puede hacerse con los artefactos existentes; no autoriza a
desplegar. El ranking se ordena por **Δ neto in-sample medido**; las propuestas
sin efecto cuantificable quedan después y se marcan como tales.

| # | Mejora | Δ neto in-sample | Δ DD / coste | ¿Datos actuales? |
|---|---|---:|---:|---|
| 1 | P2 `10/200/210/24`; quitar SL 300 | +1.810,34 vs original; +448,84 vs 8765 | −587,20 vs 8765 | Sí para diagnóstico; cambio requiere forward |
| 2 | Validar filtro 0,25 forward | +1.730,42 vs P2 | −1.358,08 | No: requiere forward |
| 3 | Reprecio exacto de costes | protege 100,80–314,06 | PF/DD exactos pendientes | No: falta artefacto exacto |
| 4 | Cobertura para regímenes 2026 | no cuantificable | no cuantificable | No: requiere forward |
| 5 | Reducir concentración trimestral | no cuantificable (Q3 85,28 %) | objetivo: DD/PF, no bruto | No: requiere forward |

### Prioridad 1 — Consolidar P2 `10/200/210/24` y eliminar el lastre del SL 300

**Marca:** **datos actuales sí para el diagnóstico; cambio de producción
requiere muestra forward.**

**Problema.** El 8765 vivo usa `max_sl_ticks=300`; P2 usa 200. La atribución
existente muestra que el 300 añade 26 operaciones, pero resta **448,84 USD** y
suma **587,20 USD** de DD frente a P2. El perfil P2 completo, a su vez, mejora
al original en **+1.810,34 USD**, aunque con **+336,64** de DD.

**Cambio conceptual.** Mantener 210/24 y `max_contracts=10`; bajar
`max_sl_ticks` a 200. No tocar el filtro 0,25.

**Efecto esperado.** Frente al 8765 actual: +448,84 USD, PF 1,22 → 1,39, DD
2.891,66 → 2.304,46, R medio 0,18 → 0,25. Frente al original: +1.810,34 USD.
Riesgo: 46 operaciones siguen por debajo de S2 (60); el acierto de P2 es solo
32,61 % y depende de ganadores grandes; el DD absoluto sigue siendo 2.304,46.

**Validación.** No existe un gate específico de perfil; se usaría el estándar
de cartera del protocolo: S2 (≥60 baseline), S3 (≥24/30), Q1 (5/6 trimestres),
P2 (PF-R ≥1,25), P3 (DD) y Q3 (top-2 ≤80 %), con muestra forward. Evidencia
mínima: 60 operaciones baseline y 5/6 bloques; no basta el artifact de 46.

**Coste/complejidad.** Cambio de configuración bajo, pero **no ejecutable como
promoción con los datos actuales**: el diagnóstico es actual; el cambio
requiere pre-registro y forward. No se aplica aquí.

### Prioridad 2 — Validar el filtro 0,25 forward sin bajar el umbral

**Marca:** **requiere muestra forward; no ejecutable con los datos actuales.**

**Problema.** Es la mayor mejora histórica del filtro (+1.730,42 USD frente a
P2), pero 17/29, 4/6 trimestres y cero aceptadas en 2026. Q1/Q3/Q4/P7 fallan y
E2 es INCONCLUSO; no hay forward.

**Cambio conceptual.** Ejecutar la hipótesis pre-registrada
`H-P2-FILTER-STOP-OR-025` con el umbral fijo 0,25 y el control P2. No probar
0,20/0,30 ni añadir filtros de calendario.

**Efecto esperado.** Si la selección histórica se repite, el filtro mantiene un
Δ de selección positivo y un DD menor; la proyección documentada es ~35
aceptadas y ~59 rechazadas en 36 meses. Si no se repite, el +1.730,42 es
sobreajuste y no hay mejora que capturar. Riesgo principal: reproducir el cero
de 2026 y quedarse sin actividad.

**Validación.** S3 ≥24/30; S0 ≥80 y ≥20/dirección; S2 ≥60; S4 ≥5/6 bloques;
E2 ≥9.500 réplicas y cobertura; Q1 ≥5/6 trimestres; Q3 ≤80 %; Q4 ≥5/6
trimestres con rechazados ≤0; P7 racha ≤4 meses; P6 reprecio exacto. La
evidencia mínima es una muestra forward independiente completa, no W1–W6.

**Coste/complejidad.** Alto: captura forward de 36 meses y datos nuevos. **Solo
forward.**

### Prioridad 3 — Reprecio exacto de costes y ejecución

**Marca:** **no ejecutable con los artefactos actuales; requiere reprecio exacto.**

**Problema.** P6 no se puede evaluar. El original pierde 314,06 USD y baja de
PF 1,13 a 1,07 con comisión 1,24/lado y slippage 2; el filtro solo tiene una
estimación uniforme de −100,80 y PF 4,0811. Un PF alto puede ocultar un coste
por operación desproporcionado.

**Cambio conceptual.** Repreciar el filtro y P2 con los fills reales, comisión
1,24/lado y slippage 2, en vez de restar un coste uniforme. Medir también el
impacto en R y en DD.

**Efecto esperado.** Proteger entre 100,80 USD (estimación del filtro) y 314,06
USD (stress exacto del original). No aumenta el bruto; evita sobreestimar la
rentabilidad. Riesgo: el filtro puede seguir siendo rentable, pero el PF
bajará; no se debe promocionar con el PF base.

**Validación.** P6 con artefacto exacto; E3 y P2 después de costes; mínimo 17
aceptadas y 46 baseline repreciados con los mismos fills. Sin P6 no hay PASS
de costes.

**Coste/complejidad.** Medio: requiere un reprecio exacto, no un backtest de
reoptimización. **No ejecutable con los artefactos actuales; sí con un reprecio
controlado.**

### Prioridad 4 — Añadir cobertura para regímenes como 2026, sin tocar el 0,25

**Marca:** **requiere muestra forward; no ejecutable con los datos actuales.**

**Problema.** El filtro tiene cero aceptadas en 2026; su neto es 100 % de 2025.
Q1 y Q4 fallan y P7 tiene una racha de 6 meses. Bajar el umbral estaría
prohibido y, además, no está justificado por los datos.

**Cambio conceptual.** Investigar una segunda fuente de señal o una condición
de régimen independiente que permita operar cuando el ratio stop/ORB no alcanza
0,25, manteniendo el filtro original intacto. No es “relajar el filtro”; es un
sleeve separado con su propio pre-registro.

**Efecto esperado.** Aumentaría la exposición y potencialmente el neto absoluto
en años sin aceptadas; hoy no hay evidencia de que esa señal exista. Riesgo:
correlación con el mismo ORB, más operaciones y más DD; podría diluir el PF.

**Validación.** S3 (nuevas aceptadas), Q1 ≥5/6, Q4 ≥5/6, P7 racha ≤4; mínimo
24 aceptadas/30 rechazadas y 5/6 bloques. Debe ser un protocolo nuevo, no una
extensión post hoc del filtro.

**Coste/complejidad.** Alto. **Solo forward / investigación nueva.**

### Prioridad 5 — Reducir la concentración trimestral sin recortar artificialmente los ganadores

**Marca:** **requiere muestra forward; no ejecutable con los datos actuales.**

**Problema.** Q3 falla con 85,28 % del neto en dos trimestres; top-5 trades =
61,23 % del bruto. El buen agregado depende de W1/W4 y de evitar 2026, no de una
base amplia.

**Cambio conceptual.** Priorizar una segunda fuente de retorno independiente o
una asignación de riesgo más diversificada entre regímenes; no añadir un
stop/objetivo que recorte los ganadores solo para mejorar el porcentaje. La
concentración es un síntoma de falta de amplitud, no un problema que se arregle
con un filtro de calendario.

**Efecto esperado.** Mejora esperada en robustez y DD; el efecto sobre el neto
bruto es incierto y podría ser negativo. Por eso queda por debajo de las
propuestas que sí tienen un Δ positivo medido.

**Validación.** Q3 top-2 ≤80 %; Q2 ≥75 % de trimestres activos positivos; P5
drop-best; mínimo 24/30, 5/6 trimestres y 9.500 réplicas. Si baja el neto sin
mejorar DD/PF, se descarta.

**Coste/complejidad.** Alto. **Requiere forward.**

### Alternativa no prioritaria: P2 + break-even 1R

El artefacto existente muestra 46 ops, +2.036,52 USD, PF 1,48 y DD 1.794,46
frente a P2 +2.471,78, PF 1,39 y DD 2.304,46. Mejora PF/DD, pero **pierde
435,26 USD de neto**. No entra en el ranking de rentabilidad; solo tendría
sentido si la restricción principal fuera el drawdown, y además su gestión vive
en un motor experimental, no en producción.

## 9. Gates que impiden promocionar

| Grupo | Estado actual |
|---|---|
| Global | **INCONCLUSO** |
| PASS | 13 gates |
| FALLA | Q1 cobertura (4/6), Q3 concentración (85,28 %), Q4 rechazados (3/6), P7 mensual (racha 6) |
| INCONCLUSO | S0, S2, S3, S4, E2 |
| NO_EVALUABLE | P6 coste exacto |

El detalle y la justificación están en `FILTER025_GATES.md`. La capa de gates se
revisó antes de este informe: `filter025_gates.py --no-write` volvió a declarar
`GLOBAL INCONCLUSO` y los 8 tests de `tests/test_filter025_gates.py` pasaron.
No se modificó ningún umbral.

## 10. Reproducir y ficheros

```bash
python reports/backtest/filter025_gates.py --no-write
python -m pytest tests/test_filter025_gates.py -q
```

Este informe se apoya en:

- `reports/backtest/p2_w1_w6_confirm.json` — original 38 y P2 46.
- `reports/backtest/_manual_filter025_w1_w6.json` — filtro 17 y rechazados 29.
- `reports/backtest/filter025_gates.json` — gates y veredicto.
- `reports/backtest/_manual_w1_w6_analysis.log` — manual 72 y atribución.
- `reports/backtest/forward_validation.json` — perfil vivo 8765.
- `reports/backtest/stress_costs.json` — stress exacto del original.
- `profiles/live_8765/config.json`, `data/config.json` y API local 8765 —
  configuración viva, solo lectura.

**Ficheros creados/modificados por este informe:** `FILTER025_PROFITABILITY.md`
(creado) y `README.md` de `reports/backtest/` (entrada añadida). No se modificó
ningún perfil, estrategia, filtro, umbral, lock ni archivo del holdout.
