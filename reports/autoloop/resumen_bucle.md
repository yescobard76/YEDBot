# Ranking autónomo (W1-W6, in-sample)

Generado: 2026-11-25T00:23:45+00:00

Exploratorio: el holdout no se ha leído y nada de esto se aplica al 8765.

| # | Variante | Ops | Neto USD | PF | DD USD | RDD | Cambio |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | excl_1100_1300 | 26 | 2,500.18 | 1.92 | 501.90 | 4.9814 | `{"risk": {"entry_exclusion_start": "11:00", "entry_exclusion_end": "13:00"}}` |
| 2 | excl_1100_1300+daily_loss_2 | 26 | 2,500.18 | 1.92 | 501.90 | 4.9814 | `{"risk": {"entry_exclusion_start": "11:00", "entry_exclusion_end": "13:00", "max_daily_loss_pct": 2.0}}` |
| 3 | excl_1100_1300+range_min_15 | 26 | 2,500.18 | 1.92 | 501.90 | 4.9814 | `{"risk": {"entry_exclusion_start": "11:00", "entry_exclusion_end": "13:00"}, "strategy": {"min_range_ticks": 15}}` |
| 4 | excl_1100_1300+sl_200 | 15 | 2,362.02 | 2.47 | 501.90 | 4.7062 | `{"risk": {"entry_exclusion_start": "11:00", "entry_exclusion_end": "13:00", "max_sl_ticks": 200}}` |
| 5 | excl_1130_1330+sl_200 | 17 | 2,805.52 | 2.74 | 813.86 | 3.4472 | `{"risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "13:30", "max_sl_ticks": 200}}` |
| 6 | excl_1130_1330+sl_200+cost_x2 | 17 | 2,638.54 | 2.56 | 843.22 | 3.1291 | `{"risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "13:30", "max_sl_ticks": 200}, "execution": {"commission_per_contract_side": 1.24, "slippage_ticks": 2}}` |
| 7 | excl_1130_1230 | 48 | 3,340.90 | 1.67 | 1,259.18 | 2.6532 | `{"risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "12:30"}}` |
| 8 | excl_1130_1330 | 36 | 3,203.82 | 1.9 | 1,376.54 | 2.3274 | `{"risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "13:30"}}` |
| 9 | excl_1130_1330+daily_loss_2 | 36 | 3,203.82 | 1.9 | 1,376.54 | 2.3274 | `{"risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "13:30", "max_daily_loss_pct": 2.0}}` |
| 10 | excl_1130_1330+range_min_15 | 36 | 3,203.82 | 1.9 | 1,376.54 | 2.3274 | `{"risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "13:30"}, "strategy": {"min_range_ticks": 15}}` |
| 11 | excl_1130_1330+cost_x2 | 36 | 2,975.14 | 1.81 | 1,421.08 | 2.0936 | `{"risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "13:30"}, "execution": {"commission_per_contract_side": 1.24, "slippage_ticks": 2}}` |
| 12 | excl_1200_1400 | 46 | 3,500.94 | 1.65 | 1,835.30 | 1.9076 | `{"risk": {"entry_exclusion_start": "12:00", "entry_exclusion_end": "14:00"}}` |
| 13 | excl_1130_1330+validity_180 | 31 | 2,025.98 | 1.62 | 1,351.58 | 1.499 | `{"risk": {"entry_exclusion_start": "11:30", "entry_exclusion_end": "13:30"}, "strategy": {"setup_validity_minutes": 180}}` |
| 14 | sl_200 | 46 | 2,471.78 | 1.39 | 2,304.46 | 1.0726 | `{"risk": {"max_sl_ticks": 200}}` |
| 15 | manual_base | 72 | 2,022.94 | 1.22 | 2,891.66 | 0.6996 | `{}` |
| 16 | daily_loss_2 | 72 | 2,022.94 | 1.22 | 2,891.66 | 0.6996 | `{"risk": {"max_daily_loss_pct": 2.0}}` |
| 17 | range_min_15 | 72 | 2,022.94 | 1.22 | 2,891.66 | 0.6996 | `{"strategy": {"min_range_ticks": 15}}` |
| 18 | tol_18 | 70 | 1,960.38 | 1.22 | 2,887.88 | 0.6788 | `{"strategy": {"retest_tolerance_ticks": 18}}` |
| 19 | sl_buffer_8 | 71 | 1,822.38 | 1.2 | 2,847.92 | 0.6399 | `{"strategy": {"sl_buffer_ticks": 8}}` |
| 20 | contracts_7 | 72 | 1,669.48 | 1.19 | 2,781.20 | 0.6003 | `{"risk": {"max_contracts": 7}}` |
| 21 | rr_2_5 | 72 | 1,462.18 | 1.16 | 2,891.66 | 0.5057 | `{"strategy": {"tp_rr": 2.5}}` |
| 22 | cost_x2 | 72 | 1,436.88 | 1.15 | 3,023.82 | 0.4752 | `{"execution": {"commission_per_contract_side": 1.24, "slippage_ticks": 2}}` |
| 23 | validity_180 | 66 | 1,154.30 | 1.13 | 2,625.74 | 0.4396 | `{"strategy": {"setup_validity_minutes": 180}}` |
| 24 | rr_3_5 | 72 | 977.44 | 1.1 | 3,635.80 | 0.2688 | `{"strategy": {"tp_rr": 3.5}}` |
| 25 | sl_250 | 60 | 728.06 | 1.08 | 3,186.32 | 0.2285 | `{"risk": {"max_sl_ticks": 250}}` |

## Notas

- RDD = neto / drawdown máximo; premia retorno por unidad de dolor.
- Es una muestra única y elegida in-sample: sirve para priorizar, no para promocionar.
