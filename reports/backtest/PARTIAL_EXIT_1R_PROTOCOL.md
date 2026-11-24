# Salida parcial 50% a +1R + break-even en el resto

**Alcance:** 14 operaciones del brazo `filter` del protocolo oficial de 362 sesiones. Holdout no usado.  
**Naturaleza:** replay de gestión con entradas, qty, stops y targets oficiales; no re-simula señales.  
**Fuente:** `reports/backtest/breakeven_1r_protocol_be.json`  
**Resultado estructurado:** `reports/backtest/partial_exit_1r_protocol.json`

## 1. Qué se probó

| Política | Salida | Resto |
|---|---|---|
| `baseline` | target original 3R | stop original |
| `be_1r` | target original 3R | stop a entrada tras +1R |
| `partial_50_be` | 50% a +1R | 50% con stop a entrada tras +1R |

La qty es la del protocolo oficial y no se recalcula. El parcial se llena a +1R; si la vela abre más allá, al open. El break-even del resto se activa para la vela siguiente, no dentro de la misma vela que toca +1R. Si stop y +1R coinciden en una vela, se aplica stop primero. Si +1R y target coinciden, se asume camino favorable: parcial a +1R y resto a target. La mitad es entera (`qty // 2`): con 3 contratos se toma 1 y quedan 2; con 5 se toman 2 y quedan 3.

El **R** es el R de precio por operación, redondeado a 2 decimales; en el parcial se pondera por contratos, igual que el motor full-engine. No es el P&L neto dividido por el riesgo. El **DD** es de caja: el parcial se acredita cuando se ejecuta; el porcentaje se calcula sobre el pico de equity.

## 2. Resultado

| Brazo | Ops | Neto USD | PF | R medio | DD USD | DD % | Ganadoras | Perdedoras | Peor racha |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline | 14 | +3.028,38 | 3.58 | 1.04 | 839,90 | 3,13% | 8 | 6 | 4 |
| BE completo | 14 | +3.164,88 | 15.62 | 1.09 | 209,58 | 0,79% | 6 | 8 | 6 |
| Parcial 50% + BE | 14 | +2.892,88 | 16.77 | 0.99 | 185,22 | 0,70% | 13 | 1 | 1 |

El baseline simulado deja **+3.028,38** con DD **839,90**. El BE completo deja **+3.164,88** y DD **209,58**; el parcial deja **+2.892,88** y DD **185,22**.

El BE completo reduce el DD un **75,05%** pero corta **2 ganadoras** y deja **6** ganadoras. El parcial reduce el DD un **77,95%**, deja **13** ganadoras y no corta ninguna; el coste es que baja el P&L de las ganadoras en **1.525,00**.

## 3. Efecto sobre ganadoras y perdedoras

| Política | Ganadoras cortadas | Ganadoras por debajo | P&L perdido en ganadoras | Perdedoras mejoradas | Ahorro en perdedoras |
|---|---:|---:|---:|---:|---:|
| BE completo | 2 | 0 | 833,00 | 5 | 969,50 |
| Parcial 50% + BE | 0 | 8 | 1.525,00 | 5 | 1.389,50 |

## 4. Detalle del parcial

Se ejecutó parcial en **13** de 14 señales. El P&L del parcial suma **+1.117,40**; el resto se cerró por stop, target o sesión según el caso. La única señal sin parcial es `2025-09-19-short-1758294900` (MFE 0,11R), que se queda en -183,48 USD.

| Señal | Qty | Parcial | Precio | P&L parcial | Resto | Salida resto | P&L total | Baseline |
|---|---:|---:|---:|---:|---:|---|---:|---:|
| `2025-02-14-long-1739545200` | 2 | 1 | 22174.75 | +84,26 | 1 | session_close | +230,52 | +292,52 |
| `2025-05-22-long-1747929600` | 2 | 1 | 21257.25 | +90,26 | 1 | stop_loss | +88,52 | -81,48 |
| `2025-06-25-short-1750860000` | 3 | 1 | 22475.00 | +72,76 | 2 | take_profit | +504,28 | +647,28 |
| `2025-07-07-short-1751899500` | 2 | 1 | 22890.25 | +86,76 | 1 | take_profit | +348,52 | +523,52 |
| `2025-07-08-short-1751984100` | 3 | 1 | 22869.50 | +81,26 | 2 | stop_loss | +77,78 | -254,22 |
| `2025-07-15-short-1752590700` | 4 | 2 | 23139.75 | +116,52 | 2 | stop_loss | +113,04 | +705,04 |
| `2025-07-24-short-1753365600` | 3 | 1 | 23364.25 | +36,26 | 2 | stop_loss | +32,78 | -119,22 |
| `2025-08-11-long-1754920800` | 3 | 1 | 23794.00 | +112,76 | 2 | stop_loss | +109,28 | -348,72 |
| `2025-09-03-long-1756909800` | 2 | 1 | 23461.25 | +90,76 | 1 | stop_loss | +89,02 | -188,48 |
| `2025-10-03-short-1759500000` | 2 | 1 | 25085.75 | +81,76 | 1 | take_profit | +348,52 | +533,52 |
| `2025-11-28-long-1764345600` | 3 | 1 | 25421.00 | +77,76 | 2 | session_close | +488,28 | +614,28 |
| `2025-12-24-long-1766588400` | 5 | 2 | 25835.25 | +101,52 | 3 | take_profit | +562,80 | +768,80 |
| `2025-12-26-short-1766761200` | 2 | 1 | 25850.00 | +84,76 | 1 | stop_loss | +83,02 | +117,52 |

## 5. Verificación de métricas

### 5.1 Control contra el protocolo oficial

| Brazo | Métrica | Oficial | Replay | Δ |
|---|---|---:|---:|---:|
| Filter | Neto | +3.026,88 | +3.028,38 | +1,50 |
| Filter | DD caja | 839,90 | 839,90 | +0,00 |
| Filter | PF | 3.57 | 3.58 | +0.01 |
| Filter | R medio | 1.04 | 1.04 | +0.00 |
| BE | Neto | +3.163,38 | +3.164,88 | +1,50 |
| BE | DD caja | 209,58 | 209,58 | +0,00 |
| BE | PF | 15.61 | 15.62 | +0.01 |
| BE | R medio | 1.09 | 1.09 | +0.00 |

El control tiene **1 discrepancia** en baseline y **1** en BE, siempre en `2025-11-28-long-1764345600`: el CSV ajustado termina en 13:14 (25484,75) y el artefacto oficial usa 13:15 (25484,50). Eso explica +1,50 USD de neto y +0,01 de PF; el **DD coincide exactamente** y el **R medio coincide** al usar la definición de R del motor. Las demás 13 operaciones coinciden.

### 5.2 Parcial contra full-engine

| Métrica | Parcial qty fija | Full-engine qty dinámica | Δ |
|---|---:|---:|---:|
| Neto | +2.892,88 | +2.738,12 | +154,76 |
| PF | 16.77 | 15.92 | +0.85 |
| DD caja | 185,22 | 185,22 | +0,00 |
| R medio | 0.99 | 0.98 | +0.01 |

El replay de parcial usa la qty fija oficial; el full-engine usa la qty dinámica del RiskManager. El **DD de caja coincide exacto**. El **R medio difiere +0,01** porque el 24-DIC el replay mantiene 5 contratos (R 2,17) y el full-engine ejecuta 4 (R 1,97); en las otras 13 señales el R coincide. Neto y PF no son comparables al pie de la letra por esa misma qty. El DD de caja del parcial (185,22) es mayor que el DD por operaciones cerradas (183,48) porque el parcial se acredita antes del cierre del resto; se reporta el de caja.

## 6. Conclusión

- El parcial **reduce el DD** de 839,90 a 185,22: un 77,95% menos, incluso por debajo del BE completo (209,58).
- **No corta ganadoras**: conserva 13 ganadoras frente a 6 del BE completo y 0 cortadas. El coste es que el neto baja de +3.028,38 a +2.892,88 y el P&L de las 8 ganadoras se reduce en 1.525,00.
- El BE completo conserva mejor neto (+3.164,88 vs +2.892,88), pero corta 2 ganadoras y deja peor DD y peor PF. El parcial gana en DD, PF, racha y número de ganadoras; pierde en neto.
- **Verificación:** el DD de caja coincide exacto con el full-engine (185,22). El R medio queda +0,01 por la qty fija del 24-DIC (5 vs 4): 13 de 14 R coinciden. Neto y PF difieren por esa misma qty, no por la simulación de la gestión.
- Es un replay de gestión in-sample sobre 14 operaciones; no valida el filtro ni autoriza promoción. El holdout sigue sin usarse.

## 7. Verificación

- 14 operaciones oficiales; IDs y qty del brazo filter.
- Baseline simulado vs oficial: 1 discrepancia > 0,01 USD.
- BE simulado vs oficial: 1 discrepancia > 0,01 USD.
- Conciliación interna de métricas (neto, PF, R, DD): **True**.
- Parcial ejecutado en 13 señales; BE movido en 13 señales del brazo BE y en 13 del parcial.
- DD de caja del parcial: 185,22; DD por operaciones cerradas: 183,48.
- JSON: `reports\backtest\partial_exit_1r_protocol.json`
