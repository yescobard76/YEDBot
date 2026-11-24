# Análisis de shorts — ¿sesgo direccional o geometría?

**Código:** D-1 (diagnóstico, no experimento)
**Fecha:** 2026-11-20
**Datos:** desarrollo completo, W1–W6, 2025-01-10 → 2026-06-30 (362 sesiones, 318 rupturas).
**Holdout:** sellado, no observado.
**Protocolo v1.2, lock y configuración:** sin cambios. Este documento no modifica la estrategia ni
autoriza ninguna corrida confirmatoria.

> **Pregunta:** ¿`full` omite shorts buenos por un sesgo direccional o porque la geometría
> entrada–stop no encaja con cómo se mueven esos días?
>
> **Respuesta corta:** no hay evidencia de sesgo direccional contra los shorts. Hay dos causas
> geométricas —la referencia de entrada al 50 % del OR y el stop anclado al OR— y una tercera
> causa no direccional: la ventana de validez de la SMT.

---

## 1. Método y definiciones

Se reejecutaron `full` y `orb_retest` sobre los seis bloques del protocolo, con el código
instrumentado del embudo (`funnel-v1`). Los totales reproducen el informe de desarrollo:

| Variante | Operaciones | Sesiones |
|---|---:|---:|
| `full` | 38 | 362 |
| `orb_retest` | 49 | 362 |

Definiciones usadas, todas ex-post y solo descriptivas:

- **Ruptura sin retesteo:** sesión con ruptura confirmada por cierre de 15 m, sin toque de la
  referencia de retesteo y sin operación `full`.
- **Buena:** excursión favorable ≥ 100 pts y excursión adversa ≤ 50 pts, medidas desde el cierre
  de ruptura hasta el cierre de sesión. Es el mismo filtro del análisis previo.
- **Conjunto A:** shorts sin retesteo que cumplen “buena”.
- **Conjunto B:** shorts que `orb_retest` operó y `full` no. La diferencia entre ambas variantes es
  solo SMT.
- **Profundidad `d`:** fracción del camino desde el borde del OR roto hasta el mid. `d=0` es el
  borde; `d=1` es el mid (la referencia actual de `full`); `d=0,25` es un cuarto del camino, la
  profundidad que propone E-1. No confundir con el “50 % del OR”: el mid es el 50 % del ancho, que
  en esta escala es `d=1`.

**Aviso de conteo:** el barrido previo citaba 37 shorts buenos sin retesteo. Con el registro nuevo
salen **38**. No hay ningún caso en el umbral exacto (ni MFE = 100 ni MAE = 50), así que la
diferencia de uno es de definición del barrido anterior, no de datos. Se analizan los 38 y se
reporta el hecho.

**Los conjuntos A y B son disjuntos:** ninguno de los 7 shorts rechazados cumple el filtro de
“bueno” del conjunto A. Son dos fenómenos distintos y se analizan por separado.

---

## 2. Conjunto A — 38 shorts buenos que nunca retestean

### 2.1 Perfil

| Métrica | Valor |
|---|---:|
| Shorts sin retesteo (todos) | 93 |
| Buenos (MFE ≥ 100, MAE ≤ 50) | **38 (40,9 %)** |
| MFE mediana / p90 | 231,88 / 424,55 pts |
| MAE mediana / p90 / máximo | 20,12 / 35,88 / **42,25 pts** |
| MFE ≥ 200 pts | 25 de 38 |
| MAE antes que MFE | **36 de 38** |
| Distancia mediana al mid en la ruptura | 113,31 pts |
| Semiancho mediano del OR | 74,00 pts |
| Distancia mínima al mid (mediana) | **92,44 pts** |

Dos lecturas inmediatas:

1. **El movimiento era grande y el adverse pequeño.** La mediana de MFE es 232 pts y el máximo
   MAE es 42,25 pts. El presupuesto de riesgo de 200 ticks (50 pts) habría cubierto el peor caso
   de los 38. El problema no fue el tamaño del riesgo permitido, sino dónde se colocaba el stop.
2. **Casi todos sufrieron primero.** En 36 de 38 el máximo adverso llegó antes que el máximo
   favorable. Cualquier entrada con stop ajustado tiene que sobrevivir ese primer envión; no basta
   con entrar antes.

### 2.2 Curva de profundidad: ¿qué referencia los habría capturado?

Toque de la referencia con tolerancia de 12 ticks, usando el extremo de la sesión posterior a la
ruptura. Es una **cota superior de fillability**: no exige cierre de recuperación ni evalúa P&L.

| Profundidad `d` | 0 (borde) | 0,10 | 0,25 (E-1) | 0,50 | 0,75 | 1 (mid) |
|---|---:|---:|---:|---:|---:|---:|
| Shorts buenos capturados (de 38) | **17** | 13 | **9** | 4 | 2 | **1** |
| Largos buenos capturados (de 40) | 24 | 19 | 15 | 6 | 3 | 0 |

La tabla es el centro del diagnóstico:

- La referencia actual (mid, `d=1`) solo habría tocado en **1 de 38** shorts.
- Un retesteo al borde del OR (`d=0`) habría tocado en **17 de 38**.
- Un retesteo al 25 % del camino (`d=0,25`, el de E-1) habría tocado en **9 de 38**.
- **21 de 38 no volvieron ni al borde del OR** antes de expirar. Esos días son de huida: ningún
  retesteo, por superficial que sea, los captura. Solo una entrada directa los cubre.

Por eso “cambiar el 50 % por el 25 %” mejora la cobertura (de 1 a 9) pero no resuelve el problema:
la mayor parte de los shorts buenos omitidos exige **entrada directa**, no un retesteo más
superficial. El brazo B de E-1 (directa + stop de confirmación) es el que cubre a los 38; el brazo
C (25 %) cubre a 9; la arquitectura actual cubre a 1.

### 2.3 Por qué el stop también importa

El stop estructural actual se ancla al 50 % del OR (`min(swing, orb.mid)` en largos y
`max(swing, orb.mid)` en cortos), de modo que en un OR de 148 pts de ancho el stop mínimo ronda
los 300 ticks, por encima del máximo de 200. Pero el adverse real de estos 38 shorts nunca superó
42,25 pts (169 ticks). El stop de confirmación de E-1, con buffer de 4 ticks y mínimo de 8, cabe
holgadamente por debajo del tope. La geometría del stop es, por sí sola, suficiente para explicar
los rechazos por `max_sl_ticks`.

---

## 3. Conjunto B — 7 shorts que `full` rechazó

### 3.1 Resultado

| Métrica | Valor |
|---|---:|
| Operaciones | 7 |
| Ganadoras / perdedoras | **2 / 5** |
| P&L neto | **−317,68 USD** |
| Profit factor | **0,70** |
| Expectativa | −45,38 USD |
| Win rate | 28,57 % |

En agregado, `full` **acertó al rechazarlos**: el conjunto pierde. No es una bolsa de shorts
buenos omitidos; es una mezcla de 2 aciertos grandes y 5 fallos.

### 3.2 Detalle

| Fecha | Entrada | P&L | R | MFE/MAE (R) | Salida | Motivo en `full` | SMT |
|---|---|---:|---:|---|---|---|---|
| 2025-03-04 | 11:58 | −234,96 | −1,01 | 2,08 / −1,57 | SL | falso rompimiento | confirmada |
| 2025-04-17 | 12:31 | −224,22 | −1,01 | 0,05 / −1,21 | SL | setup expirado, sin SMT | sin divergencia |
| 2025-05-08 | 11:22 | −236,20 | −1,02 | 0,02 / −1,14 | SL | falso rompimiento | sin divergencia |
| **2025-08-15** | **14:02** | **+351,30** | **+2,98** | 3,21 / −0,48 | TP | SMT caducada | caducada |
| 2025-11-11 | 12:52 | −148,70 | −1,01 | 0,19 / −1,22 | SL | falso rompimiento | confirmada |
| 2026-01-13 | 11:49 | −198,70 | −1,01 | 0,07 / −1,03 | SL | setup expirado, con SMT | confirmada |
| **2026-04-08** | **12:57** | **+373,80** | **+2,76** | 2,87 / −0,20 | TP | setup expirado, con SMT | confirmada |

**Los 5 malos.** Cuatro fueron falsos rompimientos y uno no tuvo SMT. Su MFE desde la entrada de
`orb_retest` fue 0,02–0,19 R en cuatro de los cinco: nunca se movieron a favor. `full` hizo bien en
no tomarlos. El caso 2025-03-04 llegó a 2,08 R y luego volvió al stop; es un problema de gestión
(sin parciales ni trailing), no de dirección, y aun así terminó perdiendo.

**Los 2 buenos.** No fueron un fallo de profundidad: en ambos el precio **sí tocó el mid** antes de
la expiración del setup.

- **2025-08-15:** ruptura a las 11:45, mid tocado a las 14:00, setup expira 14:15. Pero la SMT
  nunca se confirmó: la divergencia caducó. El bloqueo fue la SMT, no el retesteo.
- **2026-04-08:** SMT confirmada a las 09:35 y caducada a las 11:35; el mid se tocó a las 12:55 y
  el setup expiraba a las 13:00. El retesteo llegó **80 minutos después** de que la SMT dejara de
  ser válida. El bloqueo fue la ventana de 120 minutos de la SMT, no la profundidad.

Es decir: los 2 ganadores del conjunto B no son evidencia de “entrar más cerca”; son evidencia de
que la **validez SMT** puede caducar antes de que llegue un retesteo válido.

### 3.3 Contraste con los largos rechazados

| Conjunto | n | Neto | PF | Expectativa |
|---|---:|---:|---:|---:|
| Shorts rechazados | 7 | −317,68 | 0,70 | −45,38 |
| Largos rechazados | 4 | **+683,44** | **2,74** | +170,86 |

Si el filtro tuviera un sesgo direccional, habría rechazado shorts buenos y largos malos. Ocurre lo
contrario: rechazó un conjunto de shorts perdedor y un conjunto de largos ganador. El coste de
oportunidad del filtro está, en esta muestra, del lado largo.

---

## 4. ¿Direccional o geometría?

### 4.1 Evidencia direccional

| Prueba | Largos | Shorts | Lectura |
|---|---:|---:|---|
| Sin retesteo (oportunidades) | 131 | 93 | — |
| Buenos | 40 (30,5 %) | **38 (40,9 %)** | Los shorts tienen mejor tasa |
| MFE mediana | 100,0 | **149,5** | Los shorts recorren más |
| MAE mediana | 46,75 | 56,0 | Similar; el filtro ya exige ≤ 50 |
| MAE antes que MFE | 84/131 (64,1 %) | 54/93 (58,1 %) | Los shorts sufren algo menos primero |
| MFE ≥ 200 | 21 | **31** | Más shorts con recorrido grande |
| Realizado `full`: PF | 1,12 | **1,15** | Sin inferioridad de shorts |
| Realizado `full`: neto | +335,36 | +326,08 | Equilibrado |
| Rechazados por `full`: neto | **+683,44** | −317,68 | El filtro costó en largos, no en shorts |

Bootstrap de la diferencia de tasa de “buenos” (shorts − largos), 10.000 remuestras por sesión,
semilla `20261120`, 280 sesiones con ruptura y sin operación `full`:

- media **+7,95 pp**;
- IC 80 %: **[+0,9 pp, +14,9 pp]**;
- P(diferencia > 0) = **0,926**.

La diferencia es pequeña y el intervalo roza el cero, pero apunta en la dirección contraria a un
sesgo contra los shorts: si algo hay, los shorts omitidos son **ligeramente mejores** que los largos
omitidos.

### 4.2 Evidencia geométrica

- **37 de 38** shorts buenos no llegaron ni a 3 pts del mid; la distancia mediana al mid fue
  92,44 pts.
- **21 de 38** no volvieron ni al borde del OR. Ningún retesteo los captura.
- La referencia al mid (`d=1`) solo habría tocado en **1 de 38**; a `d=0,25`, en 9; al borde, en 17.
- El stop estructural anclado al OR supera los 200 ticks en estos rangos, pero el adverse real
  máximo fue 42,25 pts (169 ticks). El tope de riesgo no era el problema; el anclaje del stop sí.
- El patrón es el mismo en largos (24/40 al borde, 15/40 al 25 %, 6/40 al 50 %, 0/40 al mid). La
  geometría es simétrica; lo que cambia es la proporción, no la causa.

### 4.3 Veredicto

**No hay sesgo direccional contra los shorts.** En desarrollo, los shorts omitidos son iguales o
mejores que los largos omitidos, los shorts operados tienen PF similar, y el filtro de `full`
rechazó un conjunto de shorts perdedor y uno de largos ganador.

**El sesgo es de geometría, con dos componentes:**

1. **Referencia de entrada demasiado profunda.** El mid del OR solo se toca en 1 de 38 casos
   buenos. El borde del OR multiplica por 17 la cobertura; la entrada directa es la única que
   cubre a los 38.
2. **Stop anclado al OR.** Convierte rangos amplios en stops de 300+ ticks y rechaza entradas que
   el mercado nunca pusieron en peligro (adverse máximo 42,25 pts).

**Hay una tercera causa, no direccional:** la validez SMT de 120 minutos caduca antes de que llegue
el retesteo en algunos casos (los 2 ganadores del conjunto B). No es geometría de entrada, pero
tampoco es sesgo de dirección: afecta a ambos lados y es un parámetro de la fase C.

---

## 5. Implicaciones para E-1 (sin cambiar nada)

- **Brazo B (directa + stop de confirmación)** es el único que cubre a los 38 shorts buenos: 21 de
  ellos ni siquiera vuelven al borde del OR.
- **Brazo C (retesteo al 25 %)** cubre a 9 de 38. Mejora la arquitectura actual (1 de 38), pero no
  es la solución principal.
- **Retesteo al borde (d = 0)**, que ya existe como `entry_reference="breakout_level"`, cubre a 17
  de 38. Es una alternativa a C que E-1 no evalúa; si se quisiera comparar, exigiría un
  pre-registro nuevo (E-2), no una celda extra.
- **El stop de confirmación** debe sobrevivir el primer envión: 36 de 38 sufrieron antes de ir a
  favor, pero el adverse máximo (42,25 pts) cabe bajo el tope de 200 ticks.
- **La validez SMT** es una causa separada. E-1 no la modifica. Si se quiere atacar, es otro
  pre-registro (E-2) con su propio holdout.

Nada de esto cambia el protocolo v1.2, el lock, la configuración viva ni el holdout. E-1 sigue
siendo el experimento pre-registrado y no se ha ejecutado.

---

## 6. Límites

- **38 vs 37:** el registro nuevo produce 38 con el mismo filtro; no hay casos en el umbral exacto.
  La diferencia de uno es de definición del barrido previo. No altera ninguna conclusión.
- **MFE/MAE desde el cierre de ruptura**, no desde una entrada hipotética. La curva de profundidad
  es un test de toque con tolerancia de 12 ticks; no exige cierre de recuperación ni calcula P&L.
- **El conjunto B tiene 7 operaciones.** Dos ganadores grandes y cinco perdedores pequeños: el neto
  es negativo, pero el intervalo de confianza es enorme. Se describe, no se infiere.
- **Sin holdout.** Todo es desarrollo y sirve para diseñar, no para confirmar.
- **Una sola arquitectura comparada.** No se probaron otras referencias ni otros stops en datos
  reales; la curva de profundidad es geométrica, no una simulación de la estrategia.

---

## 7. Anexo de archivos

- `reports/backtest/shorts_analysis.json` — conjuntos A y B, filas y resumen.
- `reports/backtest/shorts/full_dev.json` — corrida `full` instrumentada, 6 bloques.
- `reports/backtest/shorts/orb_retest_dev.json` — corrida `orb_retest`, 6 bloques.
- `reports/backtest/shorts/run.log` — registro de las corridas.
- `reports/backtest/EXPERIMENTO_GEOMETRIA_ENTRADA_STOP.md` — pre-registro E-1.
