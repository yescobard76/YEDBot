# Bootstrap por bloques y comparaciones múltiples — 11 presets

**Fecha:** 2026-11-21.  
**Fuente:** `reports/backtest/equity_continuous_dev.json` (362 sesiones de desarrollo, capital arrastrado).  
**Implementación:** `reports/backtest/block_bootstrap.py`.  
**Holdout:** sellado; no ejecutado ni inspeccionado.  
**Protocolo/configuración activa:** no modificados.

## 1. Método

### Bloques

Se usa un **bootstrap móvil circular por bloques de 20 sesiones**:

- 362 sesiones, 19 bloques de 20 sesiones (el último se recorta a 362).
- 10.000 remuestras con semilla `20250102`.
- Se conserva el orden dentro de cada bloque y se incluyen las sesiones sin operaciones con P&L 0.
- Los mismos bloques se aplican a los 11 presets: el bootstrap es **pareado** y las diferencias contra baseline usan la misma secuencia.

**Por qué no se remuestrean W1–W6 como seis bloques:** con solo seis unidades, los presets de baja frecuencia quedan degenerados. Por ejemplo, `entry_or_level` solo tiene actividad en W3; al remuestrear bloques W, sus intervalos de PF/DD colapsan a un único valor y no representan incertidumbre. El bloque móvil de sesiones conserva la dependencia temporal y utiliza las 362 sesiones. La estructura W1–W6 sigue presente en la curva y en los análisis por bloque, pero no se usa como unidad de remuestreo.

La longitud 20 sale de `ceil(sqrt(362))`. Se comprobó sensibilidad con longitudes 10, 20 y 40: el único resultado significativo después de corregir es el mismo en los tres casos (DD de `entry_or_level`).

### Métricas

- **Neto:** suma del P&L de las sesiones remuestreadas.
- **PF:** beneficio bruto / pérdida bruta usando las operaciones individuales de esas sesiones. Si no hay pérdidas pero sí ganancias, PF = `inf`; si no hay operaciones, PF no definido.
- **DD:** máximo drawdown de la curva de equity diaria remuestreada, desde 25.000 USD.
- Los valores puntuales son los de la curva completa, no la media de las remuestras.

### Intervalos y corrección

- **IC95 individuales:** percentiles 2,5/97,5 de cada métrica. Están en el JSON y el CSV.
- **IC95 simultáneos:** Bonferroni sobre **33 intervalos** (11 presets × 3 métricas); son los que aparecen en la tabla principal. Controlan la familia de estimaciones al 95 %.
- **Contrastes:** cada preset contra baseline, para neto, PF y DD: 10 × 3 = **30 pruebas**.
- **Corrección de contrastes:** Holm-Bonferroni, FWER 5 %. Los p-valores son bootstrap de dos colas; los PF con `inf` o no definidos se excluyen del contraste y se reporta su frecuencia.
- No se hacen los 55 pares posibles: baseline es el control predefinido y 165 contrastes no tendrían potencia útil con 362 sesiones.

## 2. Intervalos por preset

`IC95*` = intervalo simultáneo corregido por Bonferroni (33 intervalos). Para PF, `inf` significa que la cola superior no es finita; `PF inf / n.d.` indica el número de remuestras con PF infinito o no definido.

| Preset | Ops | Bloques activos | Neto [IC95*] | PF [IC95*] | DD [IC95*] | PF inf / n.d. |
|---|---:|---:|---|---|---|---:|
| `baseline` | 38 | 6 | 661,44 [−5.918,69; 7.847,46] | 1,13 [0,14; 3,65] | 1.967,82 [522,59; 6.107,52] | 0 / 0 |
| `entry_breakout_direct` | 4 | 2 | 390,84 [−1.461,32; 2.910,12] | 2,28 [0,00; inf] | 305,20 [0,00; 1.526,00] | 3.076 / 361 |
| `entry_or_level` | 4 | 1 | 482,34 [−312,44; 2.357,63] | 3,32 [0,00; inf] | 207,96 [0,00; 416,92] | 581 / 626 |
| `entry_retrace_382` | 31 | 6 | −28,76 [−5.650,36; 6.362,21] | 0,99 [0,07; 3,70] | 2.053,10 [444,18; 5.840,70] | 0 / 0 |
| `smt_window_120` | 39 | 6 | 1.005,98 [−5.657,80; 8.068,86] | 1,19 [0,20; 3,72] | 2.224,32 [467,94; 6.215,69] | 0 / 0 |
| `smt_tolerance_16` | 48 | 6 | 1.245,40 [−5.717,46; 8.867,20] | 1,20 [0,28; 3,11] | 2.185,12 [619,42; 6.298,29] | 0 / 0 |
| `setup_validity_240` | 51 | 6 | 1.695,96 [−5.852,89; 9.652,38] | 1,28 [0,25; 3,68] | 1.583,44 [626,29; 6.345,58] | 0 / 0 |
| `sl_depth_6` | 15 | 5 | 1.454,40 [−2.919,90; 6.325,45] | 1,91 [0,00; inf] | 1.285,10 [0,00; 3.182,02] | 50 / 0 |
| `sl_buffer_12` | 37 | 6 | 84,90 [−6.220,00; 6.966,15] | 1,02 [0,13; 3,15] | 2.005,08 [525,41; 6.351,37] | 0 / 0 |
| `recovery_off` | 41 | 6 | 468,62 [−5.998,32; 7.862,88] | 1,09 [0,12; 3,37] | 2.105,64 [623,76; 6.420,93] | 0 / 0 |
| `rr_2_5` | 38 | 6 | 742,94 [−5.360,48; 7.230,14] | 1,15 [0,20; 3,51] | 1.967,82 [467,71; 5.642,76] | 0 / 0 |

**Lectura directa:** todos los IC de neto contienen 0 y todos los de PF contienen 1. Los IC de DD son niveles no negativos, no contrastes contra 0; para comparar DD contra baseline hay que usar la sección 3. Ningún preset tiene un IC de neto que excluya 0 ni un IC de PF que excluya 1. Los intervalos son muy anchos: la muestra de 362 sesiones no permite ordenar los presets con esta incertidumbre.

## 3. Contrastes contra baseline y corrección múltiple

`Δ = preset − baseline`. Para DD, un valor negativo significa **menos drawdown** (favorable). `p_Holm` es el p-valor bootstrap de dos colas corregido por Holm en la familia de 30 contrastes.

| Preset | ΔNeto $ | p_Holm | ΔPF | p_Holm | ΔDD $ | p_Holm |
|---|---:|---:|---:|---:|---:|---:|
| `entry_breakout_direct` | −270,60 | 1,000 | +1,1478 | 1,000 | −1.662,62 | 0,191 |
| `entry_or_level` | −179,10 | 1,000 | +2,1866 | 1,000 | **−1.759,86** | **0,006** |
| `entry_retrace_382` | −690,20 | 1,000 | −0,1396 | 1,000 | +85,28 | 1,000 |
| `smt_window_120` | +344,54 | 1,000 | +0,0593 | 1,000 | +256,50 | 1,000 |
| `smt_tolerance_16` | +583,96 | 1,000 | +0,0690 | 1,000 | +217,30 | 1,000 |
| `setup_validity_240` | +1.034,52 | 1,000 | +0,1505 | 1,000 | −384,38 | 1,000 |
| `sl_depth_6` | +792,96 | 1,000 | +0,7797 | 1,000 | −682,72 | 1,000 |
| `sl_buffer_12` | −576,54 | 1,000 | −0,1163 | 1,000 | +37,26 | 1,000 |
| `recovery_off` | −192,82 | 1,000 | −0,0454 | 1,000 | +137,82 | 1,000 |
| `rr_2_5` | +81,50 | 1,000 | +0,0188 | 1,000 | 0,00 | 1,000 |

**Resultado:** **1 de 30** contrastes sobrevive a Holm: el DD de `entry_or_level` es menor que el de baseline. `entry_breakout_direct` tiene un p-valor bruto de 0,0066 para DD, pero su p_Holm es 0,191: no sobrevive a la corrección. Es el ejemplo más claro de por qué no se puede leer el p-valor bruto.

El IC95 simultáneo de la diferencia de DD de `entry_or_level` es **−5.919,71 a −369,32 USD**; el individual es −4.208,00 a −696,82. El IC95 simultáneo de `entry_breakout_direct` es **−5.932,56 a +155,98**, por lo que incluye 0.

**Ningún contraste de neto o PF es significativo después de Holm.** Los p-valores brutos más bajos de esas dos métricas son 0,0566 (neto de `sl_buffer_12`) y 0,0604 (PF de `sl_buffer_12`), y quedan en 1,000 tras la corrección.

## 4. Qué cambia respecto a la comparación anterior

1. **La incertidumbre domina la comparación.** El neto puntual de `setup_validity_240` (+1.695,96) o `sl_depth_6` (+1.454,40) parece atractivo, pero sus IC95 simultáneos incluyen pérdidas de −5.852,89 y −2.919,90 USD. No se puede afirmar que sean mejores que baseline, ni siquiera que su neto sea positivo.
2. **El PF no separa a los presets.** Todos los IC95 de PF contienen 1. En los presets de 4 operaciones la cola superior es infinita y una parte relevante de las remuestras no tiene PF definido; el PF bootstrap no es una herramienta útil para ordenarlos.
3. **El único resultado significativo es un DD menor, no un edge.** `entry_or_level` tiene solo 4 operaciones y un único bloque activo (W3). Su DD menor es compatible con menor exposición y no viene acompañado de mejora significativa de neto o PF. No es evidencia de superioridad ni justifica promoción.
4. **`entry_breakout_direct` ilustra el efecto de la corrección.** Su DD parece menor antes de corregir, pero el IC simultáneo incluye 0 y p_Holm = 0,191. Sería un falso positivo si se reportara con el p-valor bruto.
5. **La conclusión del scorecard no cambia:** A 0, B 1, C 10. Este bootstrap añade incertidumbre, no un ganador. `sl_depth_6` sigue siendo el único B y sigue lejos de G4 (15 operaciones).

## 5. Límites

- **Unidad de remuestreo:** sesiones, no operaciones. Es adecuado para preservar dependencia temporal, pero no modela la incertidumbre de parámetros ni crea regímenes nuevos.
- **Longitud de bloque:** 20 sesiones. Se comprobó 10/20/40; el resultado significativo se mantiene, pero los intervalos cambian con la longitud. No se elige la longitud según el resultado.
- **PF:** puede ser `inf` o no definido, sobre todo en presets de 4 operaciones. Los IC de PF son condicionales a que PF esté definido y la cola superior puede ser infinita; no deben usarse para ranking.
- **DD:** no está ajustado por exposición, número de operaciones ni capital en riesgo. Un DD menor por operar menos no es una ventaja de la estrategia.
- **Comparaciones:** solo contra baseline, no los 55 pares. La familia es de 30 pruebas; Holm controla FWER, no FDR.
- **IC:** percentiles bootstrap, sin BCa; no hay anualización ni neto/DD en este informe.
- **Holdout:** no se abrió. No se ejecutó un backtest nuevo ni se modificó la configuración activa.
- **W1–W6:** no se remuestrean como seis bloques por la degeneración descrita; siguen siendo la unidad de los análisis por bloque y de G7.

## 6. Artefactos

- `reports/backtest/block_bootstrap.py` — cálculo reproducible.
- `reports/backtest/block_bootstrap.json` — IC, contrastes, p-valores y metadatos.
- `reports/backtest/block_bootstrap_presets.csv` — tabla por preset.
- `reports/backtest/block_bootstrap_comparisons.csv` — 30 contrastes.
- `reports/backtest/BOOTSTRAP_BLOQUES.md` — este documento.
- `reports/backtest/equity_continuous_dev.json` — curva de origen.

Comando:

```bash
python reports/backtest/block_bootstrap.py
```
