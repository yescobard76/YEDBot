# Parcial 50% a +1R + BE en el motor completo

**Alcance:** W1-W6, 362 sesiones, motor completo con qty dinámica.  
**Puerta común:** `min_stop_or_ratio = 0.25` en las tres ramas.  
**Holdout:** no usado.  
**Baseline/BE:** brazos full-engine del protocolo oficial, con qty dinámica. **Parcial:** corrida nueva en este motor.  
**Fuente:** `reports/backtest/partial_exit_1r_full.json`

## Reglas

| Rama | Gestión |
|---|---|
| `filter` | Sin gestión a 1R; stop y target originales. |
| `be_1r` | Stop a entrada después de MFE ≥ 1R, para la vela siguiente. |
| `partial_50_be` | 50% de la posición a +1R; resto con stop a entrada desde la vela siguiente. |

La qty la calcula el `RiskManager` con el 1% del equity y `max_contracts=5`. El parcial usa `qty // 2`: 2→1, 3→1, 4→2, 5→2. Si la posición tiene 1 contrato no se fuerza un parcial imposible.

## Resultado

| Brazo | Ops | Neto USD | PF | R medio | DD caja USD | DD caja % | DD motor USD | Ganadoras | Perdedoras | Peor racha |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 14 | +3026.88 | 3.57 | 1.04 | 839.90 | 3.13% | 839.90 | 8 | 6 | 4 |
| BE completo | 14 | +3163.38 | 15.61 | 1.09 | 209.58 | 0.79% | 209.58 | 6 | 8 | 6 |
| Parcial 50% + BE | 14 | +2738.12 | 15.92 | 0.98 | 185.22 | 0.70% | 183.48 | 13 | 1 | 1 |

El DD de caja acredita el parcial cuando se ejecuta; el DD motor solo lo reconoce al cierre final. Para comparar la suavidad de la curva se usa el primero.

## Comparación contra baseline

| Brazo | Δ neto | Ganadoras cortadas | P&L perdido en ganadoras | Perdedoras mejoradas | Ahorro en perdedoras | Δ DD caja |
|---|---:|---:|---:|---:|---:|---:|
| BE completo | +136.50 | 2 | 833.00 | 5 | 969.50 | -630.32 |
| Parcial 50% + BE | -288.76 | 0 | 1678.26 | 5 | 1389.50 | -654.68 |

La qty es dinámica y, por tanto, dependiente del camino de equity. El parcial llega al 2025-12-24 con **4 contratos** (baseline/BE: **5**); el resto de entradas coincide. No se reutiliza la qty fija del replay anterior. Esa diferencia de un contrato explica 153,76 USD del menor neto del parcial; el resto es el cierre de sesión del 2025-11-28, que en el motor queda 1,00 USD por debajo del replay post-hoc.

## Parcial por operación

| Señal | Qty | Qty baseline | Parcial | Precio parcial | P&L parcial | P&L resto | Salida resto | P&L total | Baseline | Δ |
|---|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| `2025-02-14-long-1739545200` | 2 | 2 | 1 | 22174.75 | +84.26 | +146.26 | session_close | +230.52 | +292.52 | -62.00 |
| `2025-05-22-long-1747929600` | 2 | 2 | 1 | 21257.25 | +90.26 | -1.74 | stop_loss | +88.52 | -81.48 | +170.00 |
| `2025-06-25-short-1750860000` | 3 | 3 | 1 | 22475.00 | +72.76 | +431.52 | take_profit | +504.28 | +647.28 | -143.00 |
| `2025-07-07-short-1751899500` | 2 | 2 | 1 | 22890.25 | +86.76 | +261.76 | take_profit | +348.52 | +523.52 | -175.00 |
| `2025-07-08-short-1751984100` | 3 | 3 | 1 | 22869.50 | +81.26 | -3.48 | stop_loss | +77.78 | -254.22 | +332.00 |
| `2025-07-15-short-1752590700` | 4 | 4 | 2 | 23139.75 | +116.52 | -3.48 | stop_loss | +113.04 | +705.04 | -592.00 |
| `2025-07-24-short-1753365600` | 3 | 3 | 1 | 23364.25 | +36.26 | -3.48 | stop_loss | +32.78 | -119.22 | +152.00 |
| `2025-08-11-long-1754920800` | 3 | 3 | 1 | 23794.00 | +112.76 | -3.48 | stop_loss | +109.28 | -348.72 | +458.00 |
| `2025-09-03-long-1756909800` | 2 | 2 | 1 | 23461.25 | +90.76 | -1.74 | stop_loss | +89.02 | -188.48 | +277.50 |
| `2025-10-03-short-1759500000` | 2 | 2 | 1 | 25085.75 | +81.76 | +266.76 | take_profit | +348.52 | +533.52 | -185.00 |
| `2025-11-28-long-1764345600` | 3 | 3 | 1 | 25421.00 | +77.76 | +409.52 | session_close | +487.28 | +614.28 | -127.00 |
| `2025-12-24-long-1766588400` | 4 | 5 | 2 | 25835.25 | +101.52 | +307.52 | take_profit | +409.04 | +768.80 | -359.76 |
| `2025-12-26-short-1766761200` | 2 | 2 | 1 | 25850.00 | +84.76 | -1.74 | stop_loss | +83.02 | +117.52 | -34.50 |

La señal `2025-09-19-short-1758294900` no ejecutó parcial: su MFE fue 0,11R. Se mantiene como única perdedora del brazo, con −183,48 USD.

## Verificación

- Sesiones evaluadas: **362**.
- Ops por rama: baseline **14**, BE **14**, parcial **14**.
- Mismos IDs de señal en las tres ramas: **True**.
- Qty dinámica observada: **{'filter': [2, 3, 4, 5], 'be_1r': [2, 3, 4, 5], 'partial_50_be': [2, 3, 4]}**.
- Señales con qty distinta al baseline: **1**; detalle en el JSON.
- Ratio stop/ORB mínimo: **0.258741** (puerta 0.25).
- Baseline vs protocolo oficial: **True**.
- Baseline/BE de origen oficial full-engine: **True**.
- BE vs protocolo oficial: **True**.
- Reconciliación de caja del parcial: **True**.
- Último trade: **2025-12-26**; holdout usado: **False**.

El baseline y el BE se comparan contra el protocolo oficial para comprobar que la integración no cambió las entradas ni el sizing. El parcial no tiene un equivalente oficial full-engine: esta es la primera ejecución con qty dinámica. El replay post-hoc anterior, con qty fija, no se usa como resultado comparable.

## Artefactos

- `reports/backtest/run_partial_exit_1r_full.py`
- `reports/backtest/partial_exit_1r_full.json`
- `reports/backtest/PARTIAL_EXIT_1R_FULL.md`
