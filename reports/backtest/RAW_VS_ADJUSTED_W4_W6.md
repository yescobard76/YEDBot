# Comparación raw vs adjusted — W4–W6

**Código:** actual, configuración congelada de `docs/protocolo_backtest.lock.json`.  
**Datos:** mismo CSV crudo; solo cambia `feed.series_mode` en memoria.  
**Holdout:** no abierto; todas las sesiones terminan el 2026-06-30.  
**Configuración:** sin cambios; hashes antes/después idénticos.

## Resultado

| Ventana | Sesiones | Ops raw | Ops adj | Neto raw | Neto adj | Δ neto | PF raw | PF adj | DD raw | DD adj | Ops idénticas | P&L idéntico |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|:---:|:---:|
| W4 | 63 | 4 | 4 | 2,034.12 | 2,034.12 | 0.00 | — | — | 0.00 | 0.00 | Sí | Sí |
| W5 | 60 | 5 | 5 | -1,036.52 | -1,036.52 | 0.00 | 0.00 | 0.00 | 1,036.52 | 1,036.52 | Sí | Sí |
| W6 | 61 | 8 | 8 | -858.92 | -858.92 | 0.00 | 0.27 | 0.27 | 931.30 | 931.30 | Sí | Sí |
| **W4–W6** | **184** | **17** | **17** | **138.68** | **138.68** | **0.00** | — | — | — | — | **Sí** | **Sí** |

El neto W4–W6 es la suma de los tres bloques; cada bloque se ejecuta con capital
reiniciado, por lo que no se interpreta como una curva continua.

## Operaciones y P&L

- **Operaciones idénticas:** sí. 17 operaciones en ambos modos, con la misma señal, entrada, salida, dirección, cantidad y `exit_reason`.
- **P&L idéntico:** sí. Neto raw 138.68 USD; neto adjusted 138.68 USD; delta 0,00 USD.
- **Métricas principales:** idénticas (trades, win rate, PF, neto, DD, R).
- **Diferencias de operación:** ninguna.
- **Diferencias de P&L:** ninguna.

## Contexto de rolls

| Ventana | Sesión de roll excluida | Contratos activos en la ventana |
|---|---|---|
| W4 | 2025-12-11 | ES: ESH26, ESZ25; MNQ: MNQH26, MNQZ25; NQ: NQH26, NQZ25 |
| W5 | 2026-03-12 | ES: ESH26, ESM26; MNQ: MNQH26, MNQM26; NQ: NQH26, NQM26 |
| W6 | 2026-06-10 | ES: ESM26, ESU26; MNQ: MNQM26, MNQU26; NQ: NQM26, NQU26 |

Las tres ventanas contienen un roll (2025-12-11, 2026-03-12 y 2026-06-10).
La sesión de roll se excluye en ambos modos. El modo `adjusted` desplaza el
histórico del contrato saliente con la convención del motor; el modo `raw` no.

## Datos y hashes

- **CSV crudo:** `data/real/bars_mnq_nq_es_1m.csv`
  - SHA-256: `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a`
- **CSV ajustado de referencia:** `data/real/bars_mnq_nq_es_1m_roll_adjusted.csv`
  - SHA-256: `1c80da8b312f06a329caf30dc3a1505949f31e0bacd72bc14349282dffed3e5f`
- **Lock:** `docs/protocolo_backtest.lock.json`
  - SHA-256: `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c`
- **Código del motor:** `7f5704a701401c2a68e3d077f4e79f8820cc9d2d181e122bbeab945084dd25dd` (32 archivos)

La comparación usa el modo `adjusted` del cargador sobre el CSV crudo, no la
copia pre-ajustada. La copia queda como artefacto de referencia.

## Configuración y holdout

Hashes de configuración antes/después:

| Archivo | Antes | Después | Igual |
|---|---|---|---|
| `data/config.json` | `0f907ba75665932120e987065ad7b77fefcbb3273a62c7aff887d798598eb112` | `0f907ba75665932120e987065ad7b77fefcbb3273a62c7aff887d798598eb112` | Sí |
| `profiles/backtest_real/config.json` | `f9cb1316be6f891b11619f09b7f20d10b7ec060e15113f9e33c97f350aa91472` | `f9cb1316be6f891b11619f09b7f20d10b7ec060e15113f9e33c97f350aa91472` | Sí |
| `docs/protocolo_backtest.lock.json` | `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c` | `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c` | Sí |

- `allow_holdout=False` en todas las ejecuciones.
- Última sesión usada: **2026-06-30 15:59**.
- Holdout: **no abierto** (ventana sellada 2026-07-01 → 2026-10-30).

## Lectura

La coherencia raw/adjusted se cumple en W4–W6: las decisiones intradía, las operaciones y el P&L son idénticos. Los precios absolutos no son idénticos porque el modo ajustado desplaza el histórico de los contratos antiguos; esa diferencia de niveles no altera la operación.

Esto es un control de coherencia de datos, no una validación de rentabilidad.
W4–W6 son desarrollo y ya se usaron para diseñar; el holdout sigue sellado.

JSON: `reports/backtest/raw_vs_adjusted_w4_w6.json`
