# Validación por bloques — diseño metodológico

**Versión:** 1.0  
**Fecha:** 2026-11-21  
**Estado:** diseño **no ejecutado**. No se ha leído ninguna barra nueva, no se ha ejecutado ningún backtest y el holdout sigue sellado.  
**Módulo:** [`research/validacion_bloques.py`](../research/validacion_bloques.py)  
**Tests:** [`tests/test_validacion_bloques.py`](../tests/test_validacion_bloques.py)

> Este documento fija el **método** de una validación futura. No fija fechas, contratos ni
> datos: eso debe congelarse en un lock nuevo antes de ejecutar. No modifica la
> configuración activa, el lock de la hipótesis, el protocolo v1.2 ni el holdout. Tampoco
> sustituye las puertas C1–C8 del lock vigente.

---

## 1. Objetivo y alcance

La validación comprueba si una regla candidata mejora a un baseline en una muestra externa,
sin que el resultado dependa de un trimestre aislado, de una racha de pocas operaciones o de
la simple exposición al mercado.

El diseño combina cuatro controles:

1. **Bloques con mínimo de operaciones:** cada bloque debe tener muestra suficiente; un
   bloque pequeño no se compensa con otro.
2. **Bootstrap pareado por bloque:** candidato y baseline se comparan sobre los mismos
   bloques remuestreados.
3. **Gasto alfa secuencial:** hay una mirada intermedia y una final; el alfa global no supera
   0,05 aunque se mire dos veces.
4. **Placebo de entradas aleatorias:** el candidato debe superar también a entradas del mismo
   día y dirección elegidas al azar dentro de la ventana permitida. El placebo es un control
   de falsificación, no una segunda hipótesis de eficacia.

El diseño **no ejecuta** la estrategia. El módulo recibe los R por operación ya calculados y
devuelve una decisión; los tests usan bloques sintéticos.

## 2. Bloques y mínimo de operaciones

La muestra se divide ex ante en **4 bloques consecutivos de igual duración calendario**. Los
límites exactos deben quedar en el lock nuevo antes de mirar resultados. El bloque es la
unidad de remuestreo y de consistencia; no se remuestrean operaciones individuales.

| Regla | Valor |
|---|---:|
| Bloques | 4 |
| Mínimo de operaciones del candidato por bloque | 20 |
| Mínimo de operaciones del baseline por bloque | 20 |
| Mínimo total del candidato | 80 |
| Mínimo total del baseline | 80 |
| Placebo | 1 entrada por operación del candidato |

Un bloque con menos de 20 operaciones del candidato **o** del baseline produce
`inconclusive`. No se agrega el bloque pequeño al resto, no se baja el umbral y no se gasta
alfa. El mínimo de 80 en total coincide con G4 del protocolo v1.2; el mínimo por bloque evita
que ese total se concentre en un solo periodo.

El mínimo se comprueba en cada mirada con los bloques observados hasta ese momento. Si el
bloque 1 o 2 no llega a 20, la mirada intermedia no se evalúa. Si el bloque 3 o 4 no llega a
20, la mirada final es `inconclusive`.

## 3. Endpoint e hipótesis

Para cada bloque `b`:

```text
d_b = media(R candidato_b) - media(R baseline_b)
```

El endpoint primario es la **media de los cuatro `d_b`**, con cada bloque pesando igual. Se
mide en R por operación y se calcula antes de remuestrear. No se agregan todas las
operaciones en una sola bolsa: así un bloque con muchas operaciones no domina la comparación.

- **H0:** `Δ <= 0` (el candidato no mejora al baseline).
- **H1:** `Δ > 0` (el candidato mejora).
- **Contraste:** unilateral, alfa global 0,05.
- **Objetivo práctico:** `Δ >= +0,10 R` por operación.

El +0,10 R es una **condición de relevancia práctica**, no el nivel nulo del contraste. Un
resultado puede ser estadísticamente positivo y no alcanzar +0,10; en ese caso no pasa. El
objetivo práctico solo puede reducir los falsos positivos, no aumentarlos.

## 4. Bootstrap pareado

Para cada mirada:

1. Se calculan las cuatro diferencias `d_b` con los bloques observados.
2. Se remuestrean los bloques con reemplazo, conservando el mismo índice para candidato,
   baseline y placebo en cada réplica.
3. En cada réplica se calcula la media de los `d_b` seleccionados.
4. Se reportan el IC percentil del 95 % y el p-valor unilateral
   `P*(D <= 0)`, con corrección `+1` para no devolver cero con un bootstrap finito.

| Parámetro | Valor |
|---|---:|
| Unidad | Bloque |
| Remuestras | 10.000 |
| Semilla | `20261121` |
| IC | Percentil 95 % |
| p-valor | Unilateral, `H0: D <= 0` |
| Pareado | Sí: mismos índices para todos los brazos |

**Limitación explícita:** con cuatro bloques, el bootstrap tiene pocos conglomerados y su
p-valor puede ser optimista. El mínimo de 20 operaciones por bloque estabiliza cada media,
pero no convierte cuatro bloques en una muestra grande. Por eso el diseño reporta las cuatro
diferencias `d_b`, no solo el agregado, y no usa el p-valor para afirmar precisión fina. Si se
quisiera una inferencia con más conglomerados, sería un diseño nuevo con más bloques, no un
cambio posterior a ver el resultado.

El bootstrap del placebo usa exactamente el mismo procedimiento, con `placebo_r` como control.

## 5. Gasto alfa secuencial

Hay **dos miradas**:

- **Mirada 1:** después del bloque 2 (fracción de información 0,50).
- **Mirada 2:** después del bloque 4 (fracción 1,00).

No hay mirada después del bloque 1 porque el bootstrap pareado necesita al menos dos bloques.
No hay mirada después del bloque 3 para limitar el número de contrastes y conservar alfa para
la decisión final; el bloque 3 se incluye en la mirada final.

Se usa una curva de gasto O'Brien-Fleming unilateral con alfa global 0,05. El alfa nominal de
cada mirada es el **incremento** de gasto acumulado. Es una implementación conservadora: no
explota la correlación entre miradas, de modo que, por unión de eventos, el error tipo I
global no supera 0,05. No pretende reproducir los límites conjuntos exactos de un grupo
secuencial multivariante.

| Mirada | Bloque | Información | Alfa acumulado | Alfa nominal | Frontera z |
|---:|---:|---:|---:|---:|---:|
| 1 | 2 | 0,50 | 0,0100046269 | 0,0100046269 | 2,326174307 |
| 2 | 4 | 1,00 | 0,0500000000 | 0,0399953731 | 1,750739766 |

Regla: si el p-valor unilateral es menor o igual que el alfa nominal de la mirada, hay
**eficacia secuencial**. Si no, se continúa hasta la mirada final. En la mirada final, no
alcanzar el alfa nominal es `fail`.

## 6. Placebo de entradas aleatorias

El placebo responde a una pregunta distinta de “¿el candidato tiene R positivo?”: responde a
“¿la señal aporta algo frente a entrar al azar en la misma sesión y dirección?”.

### 6.1 Generación

Para cada operación real del candidato se genera **una** entrada placebo:

- misma sesión;
- misma dirección (`long`/`short`);
- minuto elegido uniformemente entre los timestamps permitidos de esa sesión;
- se excluye el minuto exacto de la entrada real;
- semilla fija `20261121`;
- el llamador debe entregar solo timestamps causales y dentro de la ventana de entrada.

El generador no calcula P&L. Cuando se ejecute la validación, el placebo debe pasar por el
mismo motor de fill, costes y salidas, aplicando la geometría de riesgo al precio de entrada
placebo, no reutilizando el P&L de la operación real. El placebo es de **timing**, no de
dirección: la dirección se conserva para aislar el efecto de la entrada.

### 6.2 Puerta

En la mirada que se detiene, el candidato debe superar al placebo con **IC95 inferior > 0**.
El placebo no gasta alfa y no puede declarar eficacia: solo puede bloquearla. Si el candidato
supera al baseline pero no al placebo:

- en una mirada intermedia: se continúa, no se para;
- en la mirada final: `inconclusive_placebo`.

Las repeticiones de una misma entrada placebo entre candidatos distintos se permiten y se
reportan en `duplicate_entries`; no se eliminan después de ver resultados.

## 7. Regla de decisión

| Estado | Condición |
|---|---|
| `pass` | Todos los bloques observados cumplen el mínimo; el bootstrap supera el alfa nominal; `Δ >= +0,10 R`; el placebo tiene IC95 inferior > 0. |
| `continue` | Mirada intermedia sin condiciones de parada; no se ha gastado la decisión final. |
| `fail` | Mirada final sin eficacia secuencial o sin alcanzar `+0,10 R`. |
| `inconclusive` | Algún bloque no alcanza el mínimo o falta el placebo. No se rebajan umbrales. |
| `inconclusive_placebo` | Mirada final: el candidato supera al baseline, pero no al placebo. |

Un `pass` **no autoriza live**. Solo indica que la hipótesis superó este diseño y puede pasar
a la fase que se pre-registre después. Un `fail` no se rescata cambiando bloques, semilla,
ventana o umbral; exigiría una hipótesis nueva y una muestra nueva.

## 8. Implementación y tests

El módulo `research/validacion_bloques.py` es puro y usa solo la biblioteca estándar. No
importa `server.backtest`, no lee archivos de datos y no escribe configuración.

Funciones principales:

| Función | Uso |
|---|---|
| `validate_blocks` | Preflight de mínimos por bloque y placebo. |
| `paired_block_bootstrap` | Bootstrap pareado por bloque, IC y p unilateral. |
| `SequentialAlphaSpending` | Curva OBF, alfas nominales, fronteras z y decisión. |
| `generate_placebo_entries` | Placebo reproducible por sesión y dirección. |
| `evaluate_validation` | Aplica la regla de decisión a una mirada. |
| `design_spec` | Especificación serializable, con `design_only=true`. |

Los tests cubren:

- rechazo de bloques por debajo del mínimo, sin pooling;
- placebo ausente y longitudes inconsistentes;
- reproducibilidad y pareado del bootstrap;
- efecto nulo, efecto constante y brazo placebo;
- suma acumulada de alfa, monotonía de fronteras y niveles nominales;
- rechazo de fracciones de información inválidas;
- dominio, sesión, dirección y exclusión de la entrada real en el placebo;
- estados `pass`, `continue`, `fail`, `inconclusive` e `inconclusive_placebo`;
- que la especificación se declare explícitamente como no ejecutada.

Comando:

```bash
python -m pytest tests/test_validacion_bloques.py -q
```

## 9. Límites y estado de ejecución

- **No se ejecutó ninguna validación nueva.** No se usaron 2024, W1–W6 ni el holdout.
- **No se modificó** `data/config.json`, `profiles/backtest_real/config.json`,
  `docs/hipotesis_continuacion_selectiva.lock.json` ni `docs/protocolo_backtest.lock.json`.
- El holdout 2026-07-01 → 2026-10-30 sigue sellado.
- La validación 2024 sigue bloqueada por falta de barras/universo contractual; este diseño no
  la desbloquea ni la sustituye.
- Para usar este método hace falta un **lock nuevo** con fechas, dataset, contratos, hashes,
  semilla y estado `pre_registered_not_executed`. Sin ese lock, el módulo es solo una
  especificación y un conjunto de tests sintéticos.
- El diseño no cambia la estrategia, los umbrales, la configuración activa ni la decisión de
  paper/live.

## 10. Artefactos

- `research/validacion_bloques.py` — implementación pura del diseño.
- `tests/test_validacion_bloques.py` — tests sintéticos.
- `docs/VALIDACION_BLOQUES.md` — este protocolo.

No se generaron resultados, CSV, JSON de métricas ni ejecuciones de backtest.
