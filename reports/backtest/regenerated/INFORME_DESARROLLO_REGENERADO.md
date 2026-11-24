# Informe de desarrollo regenerado — Protocolo v1.2

**Alcance:** W1–W6 sobre las 362 sesiones evaluadas de desarrollo (2025-01-10 → 2026-06-30).  
**Holdout:** sellado, no ejecutado y no inspeccionado.  
**Código:** `dd9c882668c14a15c281f44b31cee4e474e8ce0d902a68cec656c62556482b37` (42 archivos).  
**Dataset:** `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a`.  
**Generado:** 2026-11-20T21:15:36-06:00  
**Estado:** contraste aislado; no sustituye todavía a `INFORME_DESARROLLO.md`.

## 1. Método

Se usó el runner del protocolo con la configuración del lock y el código actual. Los seis bloques se ejecutaron en paralelo; W1 se repitió y se ejecutó también en `adjusted` para recalcular G2/G3. La salida se escribió en `reports/backtest/regenerated/`, sin sobrescribir W1–W6 ni el informe actual. G8 reutiliza el `stress_costs.json` existente: no se reejecutó el stress de costes. El holdout no se abrió: sus cuatro rutas posibles siguen ausentes y el hash del CSV no cambió.

## 2. Bloques

| Bloque | Sesiones | Ops actual / regen | PF actual / regen | Exp. R actual / regen | Neto actual / regen | DD actual / regen | Código actual → regen |
|---|---:|---:|---:|---:|---:|---:|---|
| W1 | 54 | 8 / 8 | 1.35 / 1.35 | +0,56 / +0,56 | +364,82 / +364,82 | 619,42 / 619,42 | `648858d5` → `dd9c8826` |
| W2 | 61 | 4 / 4 | 1.71 / 1.71 | +0,11 / +0,11 | +268,40 / +268,40 | 378,88 / 378,88 | `22c68a13` → `dd9c8826` |
| W3 | 63 | 9 / 9 | 0.92 / 0.92 | -0,13 / -0,13 | -110,46 / -110,46 | 1.084,80 / 1.084,80 | `22c68a13` → `dd9c8826` |
| W4 | 63 | 4 / 4 | ∞ / ∞ | +2,36 / +2,36 | +2.034,12 / +2.034,12 | 0,00 / 0,00 | `22c68a13` → `dd9c8826` |
| W5 | 60 | 5 / 5 | 0.00 / 0.00 | -1,01 / -1,01 | -1.036,52 / -1.036,52 | 1.036,52 / 1.036,52 | `22c68a13` → `dd9c8826` |
| W6 | 61 | 8 / 8 | 0.27 / 0.27 | -0,40 / -0,40 | -858,92 / -858,92 | 931,30 / 931,30 | `22c68a13` → `dd9c8826` |

**Resultado:** las 6 filas son idénticas en operaciones, P&L, PF, esperanza, drawdown y racha. Solo cambia el hash de código: W1 ya estaba en `648858d5`; W2–W6 estaban en `22c68a13` y ahora quedan en `dd9c8826`.

## 3. Agregado

| Métrica | Actual | Regenerado |
|---|---:|---:|
| Operaciones | 38 | 38 |
| Ganadoras | 12 | 12 |
| Perdedoras | 26 | 26 |
| Profit factor | 1.1300 | 1.1300 |
| Esperanza R | +0,1300 | +0,1300 |
| Neto USD | +661,44 | +661,44 |
| Bruto ganador | +5.641,66 | +5.641,66 |
| Bruto perdedor | -4.980,22 | -4.980,22 |
| DD máximo USD | 1.967,82 | 1.967,82 |
| DD máximo % | 7,141 | 7,141 |
| Peor racha | 10 | 10 |
| Sharpe | 0.82 | 0.82 |
| Sortino | 1.58 | 1.58 |
| MFE medio R | +1,48 | +1,48 |
| MAE medio R | -0,94 | -0,94 |

Largos: 21 ops, +335,36 USD. Cortos: 17 ops, +326,08 USD, PF 1,15, exp. R +0,033. Sin cambios.

## 4. Puertas

| ID | Actual | Regenerado | Valor regenerado |
|---|---:|---:|---|
| G1 | PASS | PASS | sessions=368, evaluated=362, block_sessions=362, intra_session_gaps=0 |
| G2 | PASS | PASS | trades=8, runs=2, code=dd9c882668c1 |
| G3 | PASS | PASS | trades_raw=8, trades_adjusted=8, same_operations=True, operation_differences=0 |
| G4 | FAIL | FAIL | trades=38, long=21, short=17 |
| G5 | FAIL | FAIL | profit_factor=1.1328, expectancy_r=0.1311 |
| G6 | FAIL | FAIL | max_drawdown_usd=1967.82, worst_loss_streak=10 |
| G7 | FAIL | FAIL | blocks_pf_above_1=3, blocks=[{'id': 'W1', 'trades': 8, 'pf': 1.3480841157163577}, {'id': 'W2', 'trades': 4, 'pf': 1.7084037162162162}, {'id': 'W3', 'trades': 9, 'pf': 0.9175068333557378}, {'id': 'W4', 'trades': 4, 'pf': 'inf'}, {'id': 'W5', 'trades': 5, 'pf': 0.0}, {'id': 'W6', 'trades': 8, 'pf': 0.27069252453893966}] |
| G8 | FAIL | FAIL | profit_factor=1.07, commission_per_side=1.24, slippage_ticks=2, trades=38 |
| G9 | FAIL | FAIL | net_profit=661.44, top5_pnl=3268.92, net_drop_best5=-2607.48 |
| G10 | FAIL | FAIL | top5_share_gross_profit_pct=57.94, best_month_share_net_pct=134.0 |
| G11 | FAIL | FAIL | mean=0.12934444736842107, p2_5=-0.3913157894736842, p10=-0.21850000000000003, p90=0.4816052631578948 |
| G12 | FAIL | FAIL | trades=17, pf=1.1482, expectancy_r=0.0329 |
| G13 | PASS | PASS | ambiguous_trades=0, share_pct=0.0 |
| G14 | PASS | PASS | incomplete=0, duplicate_ids=0, duplicate_signal_ids=0 |

**Fallan:** G4, G5, G6, G7, G8, G9, G10, G11, G12. **Decisión:** INCONCLUSO. Idéntica al informe actual.

## 5. Ablaciones

| Variante | Ops | PF | Exp. R | Neto | DD |
|---|---:|---:|---:|---:|---:|
| `orb` | 3 | 6.19 | +1,07 | +583,56 | 112,48 |
| `orb_smt` | 4 | 2.28 | +0,70 | +390,84 | 305,20 |
| `orb_retest` | 49 | 1.21 | +0,25 | +1.347,44 | 2.303,12 |
| `full` | 38 | 1.13 | +0,13 | +661,44 | 1.967,82 |

Idénticas al informe actual.

## 6. Robustez

| Prueba | Actual | Regenerado |
|---|---:|---:|
| Costes dobles (G8, stress reutilizado) | PF 1,07 / neto +347,38 | PF 1,07 / neto +347,38 |
| Drop-best 5 | −2.607,48 | −2.607,48 |
| Top-5 / bruto | 57,94 % | 57,94 % |
| Mejor mes / neto | 134,0 % | 134,0 % |
| Bootstrap p10 | −0,2185 | −0,2185 |
| Bootstrap p2,5 | −0,3913 | −0,3913 |
| Barras ambiguas | 0 ops (0 %) | 0 ops (0 %) |

## 7. Comparación con el informe actual

- **Operaciones:** idénticas trade a trade en las 4 variantes y los 6 bloques (`signal_id`, entrada, salida, dirección, cantidad, motivo, P&L y R).
- **Agregado:** `development_aggregate.json` idéntico campo por campo.
- **Ablaciones:** `variant_aggregate.json` idéntico.
- **Puertas:** mismos PASS/FAIL y misma decisión. La única diferencia es el hash de código en G2 (`648858d5` → `dd9c8826`).
- **Procedencia:** el informe actual declara `648858d5` y dice que W2–W6 se conservan del run original (`22c68a13`). Tras esta reejecución, los seis bloques están en `dd9c8826` y siguen produciendo el mismo resultado.
- **Conclusión:** el informe actual es numéricamente correcto. Si se adopta esta corrida, solo hay que actualizar la fila de hash de código y la nota de procedencia de W2–W6; no cambian tablas, puertas ni decisión.

## 8. Holdout

No ejecutado. No existe `holdout.json`, `holdout.seal.json`, `holdout.ledger.jsonl` ni `holdout.receipt.json`. El hash del CSV es el mismo antes y después. El holdout sigue sellado.
