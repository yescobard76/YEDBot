# Validación fuera de muestra — P2 y P2 + BE 1R

**Estado:** `INSUFICIENTE` · **Decisión:** mantener la configuración manual viva (`8765 10/300/210/24`).<br>
**Generado:** 2026-11-25T02:43:43+00:00<br>
**Holdout:** `H1` 2026-07-01 → 2026-10-30, **sellado y no ejecutado**.<br>
**Hash del lock:** `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c`<br>
**Dataset de desarrollo:** termina en `2026-06-30`; no contiene barras del holdout ni forward.

## Por qué no hay una decisión de promoción

No hay muestra forward independiente para P2 ni para P2+BE. El holdout sigue sellado y la ventana forward empieza después de la fecha de esta evaluación. Se mantiene la configuración manual viva.

- No hay CSV forward ni sesiones posteriores al 2026-06-30.
- El único lock forward existente (`H-P2-FILTER-STOP-OR-025`) prueba el filtro 0,25, no P2 ni P2+BE.
- No se ejecutó ningún backtest nuevo sobre validación; no se abrió el holdout.
- Las métricas de desarrollo son **in-sample** y se muestran solo como contexto.

## Límite de contratos del manual

- **Valor:** `10` · **fuente:** `data/config.json#risk.max_contracts` · **estado:** `configured`.
- Leído de la configuración efectiva usada por la instancia 8765; no es un valor fijo del generador.

## Comparación histórica vs forward

| Candidato | Ops hist. | Neto hist. USD | PF hist. | DD hist. USD | R medio hist. | Forward | Estado |
|---|---:|---:|---:|---:|---:|---|---|
| Manual 8765 · 10 contratos · SL 300 · 210/24 | 72 | +2022.94 | 1.22 | 2891.66 | +0.18 | — | Referencia |
| P2 · 10 contratos · SL 200 · 210/24 | 46 | +2471.78 | 1.39 | 2304.46 | +0.25 | — | Sin datos forward |
| P2 + break-even 1R | 46 | +2036.52 | 1.48 | 1794.46 | +0.22 | — | Sin datos forward |

**Forward:** 0 sesiones disponibles. No se inventan métricas ni se usa el holdout como sustituto.

## Integridad

- Protocolo v1.2: `55d89872804ea091c31291cad04d4bdc49d4558aa8e60455ff7d6d1e179f353c`
- Lock forward P2/filtro: `d1a2c87b1a855d2040347dbc513711302fd3a4d667ffeb24ca4ae4861719fb01`
- Lock forward P2/BE/manual: `ad72a200943febc2382e40372d199b8a7fda2d78fa67818e96c27be779735dd5`
- `data/config.json`: `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f`
- `profiles/backtest_real/config.json`: `8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f`
- `profiles/p2_freq/config.json`: `ab161d6e53aa9825886596d597e65ee796bd6157b738f046bdc32a50f3f9aefb`
- Dataset de desarrollo: `1cc455e937e6cf2fad201bec95c78774b4028f012311b7a66ecedbad03f0af8a`

No se modificó `data/config.json`, el perfil P2, el protocolo ni el holdout. El informe es reproducible con `python reports/backtest/build_forward_validation.py`.
