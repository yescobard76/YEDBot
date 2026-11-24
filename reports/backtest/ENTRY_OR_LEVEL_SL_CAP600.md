# Preset opt-in: Nivel OR + tope SL 600

**Datos:** W1–W6, 362 sesiones de desarrollo (2025-01-10 → 2026-06-30).  
**Holdout:** sellado, no ejecutado.  
**Configuración activa:** no modificada.  
**Perfil del run:** `profiles/backtest_real/config.json`.  
**Código del run:** `b17313ba3010897ccc386ac0cdf3ac30924f0d3d87cecaa8524e84d2530c991e`.  
**Estado:** comparación exploratoria; el preset no es default y no se ha promovido.

## 1. Preset

```json
{
  "entry_or_level_sl_cap_600": {
    "label": "Nivel OR + tope SL 600",
    "group": "combinado",
    "description": "Espera el retesteo de ORH/ORL y levanta solo max_sl_ticks a 600; conserva risk_per_trade_pct para separar el cap del presupuesto.",
    "patch": {
      "strategy": {
        "entry_reference": "breakout_level"
      },
      "risk": {
        "max_sl_ticks": 600
      }
    }
  }
}
```

Es opt-in: no está en `DEFAULT_PRESETS`. Solo cambia la referencia de entrada a `breakout_level` y relaja `max_sl_ticks` de 200 a 600; conserva `risk_per_trade_pct=1.0`, `max_contracts=5` y el resto del lock.

## 2. Comparación agregada

| Preset | Ops | Señales | WR % | PF | Exp. $ | Neto $ | Peor DD $ | Caps | qty0 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `baseline` | 38 | 38 | 31,6 | 1,13 | 17,41 | 661,44 | 1.084,80 | 50 | 0 |
| `entry_breakout_direct` | 4 | 4 | 50,0 | 2,28 | 97,71 | 390,84 | 305,20 | 290 | 0 |
| `entry_or_level` | 4 | 4 | 50,0 | 3,32 | 120,58 | 482,34 | 207,96 | 219 | 0 |
| `entry_retrace_382` | 31 | 31 | 32,3 | 0,99 | -0,93 | -28,76 | 1.007,58 | 73 | 0 |
| `smt_window_120` | 39 | 39 | 33,3 | 1,19 | 25,79 | 1.005,98 | 1.187,80 | 51 | 0 |
| `smt_tolerance_16` | 48 | 48 | 35,4 | 1,18 | 22,74 | 1.091,64 | 1.423,92 | 53 | 0 |
| `setup_validity_240` | 51 | 51 | 33,3 | 1,28 | 33,25 | 1.695,96 | 1.583,44 | 58 | 0 |
| `sl_depth_6` | 15 | 15 | 46,7 | 2,02 | 102,64 | 1.539,64 | 1.199,86 | 73 | 0 |
| `sl_buffer_12` | 37 | 37 | 29,7 | 1,03 | 3,78 | 139,86 | 1.101,06 | 51 | 0 |
| `recovery_off` | 41 | 41 | 24,4 | 1,08 | 10,44 | 428,10 | 1.181,00 | 53 | 0 |
| `rr_2_5` | 38 | 38 | 34,2 | 1,15 | 19,55 | 742,94 | 1.084,80 | 50 | 0 |
| **`entry_or_level_sl_cap_600`** | **100** | **130** | **52,0** | **1,18** | **12,56** | **1.255,62** | **1.013,82** | **93** | **30** |

Los 11 defaults son los de `presets_default_dev.json`. El baseline y `entry_or_level` del run nuevo reproducen exactamente sus métricas comunes, así que la comparación es sobre el mismo dataset y comportamiento.

## 3. El efecto del cap, aislado

| Configuración | Ops | Señales | PF | Neto $ | Caps | qty0 | Bloques con ops |
|---|---:|---:|---:|---:|---:|---:|---:|
| `baseline` | 38 | 38 | 1,13 | 661,44 | 50 | 0 | 6/6 |
| `entry_or_level` | 4 | 4 | 3,32 | 482,34 | 219 | 0 | 1/6 |
| `entry_or_level_sl_cap_600` | 100 | 130 | 1,18 | 1.255,62 | 93 | 30 | 6/6 |

Con cap 200, `entry_or_level` solo consigue 4 operaciones y 219 sesiones quedan en `stop_cap`. Al subir el cap a 600, el mismo patrón de entrada genera 130 señales y 100 operaciones; 93 sesiones siguen en `stop_cap` (>600 ticks) y 30 terminan con `qty=0` porque el presupuesto de riesgo del 1 % no compra un contrato.

## 4. Desglose por bloque

| Bloque | Baseline ops / PF / neto | `entry_or_level` ops / PF / neto | Nuevo ops / PF / neto | Nuevo DD | Nuevo caps / qty0 |
|---|---:|---:|---:|---:|---:|
| W1 | 8 / 1,35 / 364,82 | 0 / ∞ / 0,00 | 16 / 1,14 / 175,92 | 767,92 | 15 / 5 |
| W2 | 4 / 1,71 / 268,40 | 0 / ∞ / 0,00 | 14 / 0,72 / -294,60 | 500,40 | 13 / 6 |
| W3 | 9 / 0,92 / -110,46 | 4 / 3,32 / 482,34 | 33 / 0,97 / -68,34 | 1.013,82 | 5 / 5 |
| W4 | 4 / ∞ / 2.034,12 | 0 / ∞ / 0,00 | 20 / 5,08 / 1.956,22 | 202,46 | 13 / 7 |
| W5 | 5 / 0,00 / -1.036,52 | 0 / ∞ / 0,00 | 8 / 0,56 / -359,42 | 380,20 | 18 / 3 |
| W6 | 8 / 0,27 / -858,92 | 0 / ∞ / 0,00 | 9 / 0,83 / -154,16 | 567,72 | 29 / 4 |

W4 aporta +1.956,22 USD de los +1.255,62 netos del preset. Sin W4, el agregado queda en −700,60 USD. W1 es el otro bloque positivo (+175,92); W2, W3, W5 y W6 son negativos. Solo 2/6 bloques tienen PF>1 (W1 y W4).

## 5. Comparación con los otros controles de cap 600

| Preset | Ops | PF | Neto $ | Peor DD $ | Caps | qty0 |
|---|---:|---:|---:|---:|---:|---:|
| `sl_cap_600` | 79 | 0,95 | -514,80 | 2.102,72 | 3 | 6 |
| `direct_sl_cap_600` | 90 | 1,24 | 1.404,74 | 931,20 | 171 | 54 |
| `deep_stop_sl_cap_600` | 74 | 1,11 | 836,86 | 2.102,06 | 5 | 9 |
| `entry_or_level_sl_cap_600` | 100 | 1,18 | 1.255,62 | 1.013,82 | 93 | 30 |

La entrada directa con cap 600 sigue siendo mejor en PF (1,24 vs 1,18), neto (+1.404,74 vs +1.255,62) y peor DD (931,20 vs 1.013,82). El nuevo preset mejora al `sl_cap_600` de referencia (PF 1,18 vs 0,95; neto +1.255,62 vs −514,80), pero no domina a la entrada directa.

## 6. Lectura

- El cap de 200 ticks era el principal limitante de `entry_or_level`: no es que la entrada no aparezca, es que casi todas sus señales quedaban fuera por stop profundo.
- Al liberar el cap hasta 600, el preset deja de ser de baja frecuencia: pasa de 4 a 100 operaciones y de 1 a 6 bloques con actividad.
- La mejora de neto frente al baseline viene con más operaciones, PF solo 1,18 y una concentración extrema en W4; no es un edge consistente.
- El `qty=0` aparece en 30 sesiones: el cap ya no las bloquea, pero el presupuesto de riesgo del 1 % no compra un contrato.
- Para una decisión confirmatoria faltaría una hipótesis pre-registrada y un holdout nuevo; este resultado es exploratorio y no cambia el protocolo.

## 7. Artefactos

- `reports/backtest/presets_entry_or_level_sl_cap600_dev.json` — filas por bloque y agregado.
- `reports/backtest/presets_entry_or_level_sl_cap600_dev.log` — salida del runner.
- `reports/backtest/presets_default_dev.json` — defaults de comparación.
- `server/backtest.py` — preset `entry_or_level_sl_cap_600` (opt-in).
