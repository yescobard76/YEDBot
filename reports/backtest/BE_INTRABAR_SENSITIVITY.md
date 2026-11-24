# Sensibilidad del BE a la vela de activación

**Alcance:** W1-W6, 362 sesiones, motor completo con qty dinámica.  
**Puerta común:** `min_stop_or_ratio = 0.25`.  
**Holdout:** no usado.  
**Baseline/BE vela siguiente:** brazos full-engine oficiales. **BE misma vela:** corrida nueva.  
**Fuente:** `reports/backtest/be_intrabar_sensitivity.json`

## Reglas

| Rama | Activación del BE |
|---|---|
| `be_1r` | Tras MFE ≥ 1R, el stop pasa a entrada al empezar la vela siguiente. |
| `be_1r_same_bar` | Si la vela toca +1R, el stop pasa a entrada dentro de esa vela. Si la vela vuelve a entrada y no alcanza target, se ejecuta en la misma vela. |

Si la vela toca +1R y target, se cobra el target; si toca el stop inicial, el stop inicial tiene prioridad. No se modela un gap al open para el BE que nace intrabar. No hay salida parcial en esta sensibilidad.

## Resultado

| Brazo | Ops | Neto USD | PF | R medio | DD caja USD | DD caja % | W/L | Peor racha | BE movidos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 14 | +3026.88 | 3.57 | 1.04 | 839.90 | 3.13% | 8/6 | 4 | 0 |
| BE vela siguiente | 14 | +3163.38 | 15.61 | 1.09 | 209.58 | 0.79% | 6/8 | 6 | 13 |
| BE misma vela | 14 | +3163.38 | 15.61 | 1.09 | 209.58 | 0.79% | 6/8 | 6 | 13 |

## Cuánto depende del supuesto intrabar

| Métrica | BE vela siguiente | BE misma vela | Diferencia |
|---|---:|---:|---:|
| DD caja | 209.58 | 209.58 | +0.00 |
| Recorte de DD vs baseline | 630.32 | 630.32 | +0.00 |
| Neto | +3163.38 | +3163.38 | +0.00 |
| PF | 15.61 | 15.61 | +0.00 |

- El BE misma vela conserva **100.00%** del recorte de DD del BE vela siguiente.
- **0.00%** del recorte de DD depende de mover el BE solo en la vela siguiente.
- El BE misma vela ejecutó el stop en la propia vela en **0** operaciones, por **+0.00 USD**.
- En **13** señales se localizó la primera vela que toca +1R. La distancia mínima a la entrada en esa vela fue **+9.75 puntos** (**39.00 ticks**); **0** volvieron a entrada en la misma vela.
- Señales cuyo P&L o salida cambió: **0**; qty distinta por camino de equity: **0**.

## Por qué el resultado es idéntico

La condición para que el BE intrabar cambie algo es que la vela que toca +1R vuelva a entrada en esa misma vela. No ocurrió en ninguna de las **13** primeras velas +1R: la más cercana se quedó a **9.75 puntos** (**39.00 ticks**) de la entrada. Por eso los 13 BE se activan igual y no hay ninguna salida BE intrabar.

## Operaciones que cambian

Ninguna operación cambió: mismos IDs, misma qty, mismo P&L y mismas salidas en las dos variantes.

## Lectura

- El BE reduce el DD de caja de **839.90** a **209.58** (**630.32** puntos de recorte).
- Con BE en la misma vela el DD es **209.58**: se conserva el **100.00%** del recorte y el **0.00%** depende del supuesto de vela siguiente.
- En esta muestra el supuesto intrabar **no explica** la reducción de DD: no hay una vela +1R que retroceda a entrada. No es una prueba de robustez ante un timeframe menor; con OHLC de 1m no se puede reconstruir el orden interno.
- El resultado sigue siendo in-sample y con 14 operaciones; no autoriza promoción.

## Verificación

- Sesiones evaluadas: **362**.
- Ops por rama: baseline **14**, BE siguiente **14**, BE misma vela **14**.
- Mismos IDs de señal: **True**.
- Qty dinámica: **{'filter': [2, 3, 4, 5], 'be_1r': [2, 3, 4, 5], 'be_1r_same_bar': [2, 3, 4, 5]}**.
- Ratio stop/ORB mínimo: **0.258741** (puerta 0.25).
- Último trade: **2025-12-26**; holdout usado: **False**.

La comparación no cambia el lock, la configuración, el CSV raw ni el holdout. El baseline y el BE de vela siguiente son los brazos full-engine oficiales; la variante misma vela se simuló con las mismas puertas y el mismo sizing dinámico.

## Artefactos

- `reports/backtest/run_be_intrabar_sensitivity.py`
- `reports/backtest/be_intrabar_sensitivity.json`
- `reports/backtest/BE_INTRABAR_SENSITIVITY.md`
