# Atribución del parcial 50% y del BE a +1R

**Alcance:** W1-W6, 362 sesiones, motor completo con qty dinámica.  
**Puerta común:** `min_stop_or_ratio = 0.25`.  
**Holdout:** no usado.  
**Fuentes:** baseline/BE del protocolo oficial; parcial+BE del artefacto full-engine; parcial sin BE de esta corrida.  
**Fuente estructurada:** `reports/backtest/partial_exit_1r_attribution.json`

## Brazos

| Brazo | Salida a +1R | Resto |
|---|---|---|
| `filter` | Nada | Stop y target originales. |
| `be_1r` | Nada | BE desde la vela siguiente. |
| `partial_50_no_be` | 50% | Stop original. |
| `partial_50_be` | 50% | BE desde la vela siguiente. |

La qty se calcula con el 1% del equity y `max_contracts=5`; no se impone la qty fija del replay antiguo.

## Resultado

| Brazo | Ops | Neto USD | PF | R medio | DD caja USD | DD caja % | W/L | Peor racha | P&L parcial | BE movidos |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 14 | +3026.88 | 3.57 | 1.04 | 839.90 | 3.13% | 8/6 | 4 | +0.00 | 0 |
| BE solo | 14 | +3163.38 | 15.61 | 1.09 | 209.58 | 0.79% | 6/8 | 6 | +0.00 | 13 |
| Parcial solo | 14 | +2552.12 | 6.83 | 0.92 | 419.44 | 1.58% | 9/5 | 4 | +1117.40 | 0 |
| Parcial + BE | 14 | +2738.12 | 15.92 | 0.98 | 185.22 | 0.70% | 13/1 | 1 | +1117.40 | 13 |

## Descomposición

| Concepto | Δ neto vs baseline | DD caja | Δ DD vs baseline | Recorte de DD |
|---|---:|---:|---:|---:|
| BE solo | +136.50 | 209.58 | -630.32 | 630.32 |
| Parcial solo | -474.76 | 419.44 | -420.46 | 420.46 |
| Parcial + BE | -288.76 | 185.22 | -654.68 | 654.68 |
| Interacción | +49.50 | — | — | -396.10 |

La interacción es la parte del resultado combinado que no se explica por la suma de los efectos individuales. Es negativa cuando ambas gestiones protegen la misma cola; la qty dinámica también puede hacerla no aditiva.

## Aportes incrementales

| Pregunta | Δ neto | Δ DD / recorte adicional |
|---|---:|---:|
| ¿Cuánto añade el BE al parcial? | +186.00 | +234.22 |
| ¿Cuánto añade el parcial al BE? | -425.26 | +24.36 |

**Lectura:** el recorte de DD del parcial solo es **420.46** y cuesta **474.76** de neto. El BE solo recorta **630.32** y suma **+136.50**. El combinado recorta **654.68** y resta **288.76**; añadir BE al parcial mejora el neto en **+186.00** y recorta **234.22** más. Añadir el parcial al BE solo recorta **24.36** más y cuesta **425.26** de neto. La interacción de DD es **-396.10**: ambas gestiones protegen la misma cola.

## Detalle por señal

| Señal | Qty parcial | Parcial ejecutado | P&L base | P&L parcial | Δ parcial | P&L BE | P&L parcial+BE | Δ BE sobre parcial | Salida parcial | Salida combinada |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---|
| `2025-02-14-long-1739545200` | 2 | 1 | +292.52 | +230.52 | -62.00 | +292.52 | +230.52 | +0.00 | session_close | session_close |
| `2025-05-22-long-1747929600` | 2 | 1 | -81.48 | +49.52 | +131.00 | -3.48 | +88.52 | +39.00 | session_close | stop_loss |
| `2025-06-25-short-1750860000` | 3 | 1 | +647.28 | +504.28 | -143.00 | +647.28 | +504.28 | +0.00 | take_profit | take_profit |
| `2025-07-07-short-1751899500` | 2 | 1 | +523.52 | +348.52 | -175.00 | +523.52 | +348.52 | +0.00 | take_profit | take_profit |
| `2025-07-08-short-1751984100` | 3 | 1 | -254.22 | -88.22 | +166.00 | -5.22 | +77.78 | +166.00 | stop_loss | stop_loss |
| `2025-07-15-short-1752590700` | 4 | 2 | +705.04 | +469.04 | -236.00 | -6.96 | +113.04 | -356.00 | take_profit | stop_loss |
| `2025-07-24-short-1753365600` | 3 | 1 | -119.22 | -43.22 | +76.00 | -5.22 | +32.78 | +76.00 | stop_loss | stop_loss |
| `2025-08-11-long-1754920800` | 3 | 1 | -348.72 | -119.72 | +229.00 | -5.22 | +109.28 | +229.00 | stop_loss | stop_loss |
| `2025-09-03-long-1756909800` | 2 | 1 | -188.48 | -3.48 | +185.00 | -3.48 | +89.02 | +92.50 | stop_loss | stop_loss |
| `2025-09-19-short-1758294900` | 2 | None | -183.48 | -183.48 | +0.00 | -183.48 | -183.48 | +0.00 | stop_loss | stop_loss |
| `2025-10-03-short-1759500000` | 2 | 1 | +533.52 | +348.52 | -185.00 | +533.52 | +348.52 | +0.00 | take_profit | take_profit |
| `2025-11-28-long-1764345600` | 3 | 1 | +614.28 | +487.28 | -127.00 | +614.28 | +487.28 | +0.00 | session_close | session_close |
| `2025-12-24-long-1766588400` | 4 | 2 | +768.80 | +409.04 | -359.76 | +768.80 | +409.04 | +0.00 | take_profit | take_profit |
| `2025-12-26-short-1766761200` | 2 | 1 | +117.52 | +143.52 | +26.00 | -3.48 | +83.02 | -60.50 | session_close | stop_loss |

## Qty dinámica

- Qty observada: `{'filter': [2, 3, 4, 5], 'be_1r': [2, 3, 4, 5], 'partial_50_no_be': [2, 3, 4], 'partial_50_be': [2, 3, 4]}`.
- Señales con qty distinta al baseline: parcial **1**, BE **0**, parcial+BE **1**.
- Parcial sin BE: **13** señales con parcial; BE movidos: **0** (debe ser 0).

## Verificación

- Sesiones evaluadas: **362**.
- Mismos IDs de señal en las cuatro ramas: **True**.
- Ratio stop/ORB mínimo: **0.258741** (puerta 0.25).
- Baseline vs oficial: **True**.
- BE vs oficial: **True**.
- Parcial+BE vs artefacto fuente: **True**.
- Parcial sin BE no movió ningún stop a BE: **True**.
- Último trade: **2025-12-26**; holdout usado: **False**.

No se modificaron lock, configuración, CSV raw ni holdout. Las 14 operaciones son in-sample y no alcanzan el mínimo de 80 para promoción.

## Artefactos

- `reports/backtest/run_partial_1r_attribution.py`
- `reports/backtest/partial_exit_1r_attribution.json`
- `reports/backtest/PARTIAL_EXIT_1R_ATTRIBUTION.md`
