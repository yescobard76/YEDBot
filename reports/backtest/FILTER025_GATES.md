# Gates históricos del filtro 0,25 — evaluación read-only

**Estado:** evaluación histórica de W1–W6. **No es una validación forward.**
**Alcance:** solo capa de gates y agregación de artefactos existentes. No se
modificó la estrategia, el filtro 0,25, sus umbrales de entrada, la DB, la
configuración viva, el protocolo forward ni el holdout.

## Entradas y reproducibilidad

- `reports/backtest/_manual_filter025_w1_w6.json`: 17 trades aceptados.
- `reports/backtest/p2_w1_w6_confirm.json`: 46 trades baseline P2; de ellos 29
  quedan fuera del filtro y forman el cohorte rechazado.
- `reports/backtest/filter025_gates.config.json`: umbrales reales de la
  evaluación.
- `reports/backtest/filter025_gates.json`: salida generada, con hashes de
  entrada, valores por gate, demo de discriminación y decisión.

```bash
python reports/backtest/filter025_gates.py
python -m pytest tests/test_filter025_gates.py -q
```

El script no importa el motor, no llama a `prepare_dataset`, no simula barras y
no escribe en la DB. `I1_SCOPE` verifica que los 46 trades pertenecen a W1–W6 y
el artefacto declara `holdout_read=false`.

## Muestra

| Cohorte | Trades | Neto | PF USD | R total | R medio | DD USD |
|---|---:|---:|---:|---:|---:|---:|
| Aceptado | 17 | +4.202,20 | 4,25 | +18,85 | +1,1088 | 946,38 |
| Baseline P2 | 46 | +2.471,78 | 1,39 | +11,56 | +0,251 | 2.304,46 |
| Rechazado | 29 | −1.730,42 | 0,65 | −7,29 | −0,251 | 2.828,74 |

Los 17 aceptados están en 2025. W5 y W6 (2026) no tienen ningún aceptado.

## Definiciones recalibradas

### 1. Cobertura y concentración trimestral

Un bloque vacío **no** es neutral. La cobertura se separa de la consistencia:

- `Q1_QUARTER_COVERAGE`: exige ≥5/6 trimestres con al menos un aceptado. Un
  bloque sin aceptados es FALLA, no un pase automático.
- `Q2_QUARTER_CONSISTENCY`: entre los trimestres con aceptados, exige ≥75 % con
  R>0 y que ninguno tenga R<−0,5. Si hay menos de 4 trimestres activos, es
  INCONCLUSO.
- `Q3_QUARTER_CONCENTRATION`: el top-2 de trimestres no puede superar el 80 %
  del neto.
- `Q4_REJECTED_CONSISTENCY` (sustituye la lectura laxa de P4): exige R rechazado
  ≤0 en ≥5/6 trimestres. Un trimestre sin rechazados cuenta como FALLA de
  cobertura, no como pase neutral.

### 2. Umbral de bloque activo

`Q5_BLOCK_PF` usa `max(3, ceil(n_aceptados/6))`. Con 17 trades el umbral es
**3**, no 15. Solo entran bloques con al menos ese número de aceptados; si no
hay ninguno, el gate es INCONCLUSO. El umbral antiguo de 15 era inerte porque el
bloque más grande tiene 8 trades.

### 3. Bootstrap con precondiciones

`E2_BOOTSTRAP` mantiene el bootstrap por sesión, 10.000 réplicas y semilla
`20261123`, pero **no puede dar PASS solo porque el IC inferior sea positivo**.
También exige:

- ≥24 aceptados y ≥30 rechazados;
- ≥5/6 trimestres con aceptados;
- ≥9.500 réplicas válidas.

Los mínimos de muestra no se rebajan para “hacer pasar” el filtro.

### 4. Mínimos inalcanzables

`S0_TOTAL_SAMPLE`, `S2_BASELINE`, `S3_COHORT` y `S4_BLOCK_SAMPLE` no se
recalibran hacia abajo. Si la muestra no alcanza, el estado es **INCONCLUSO**,
nunca PASS. Lo mismo aplica a la muestra de cortos: la participación mínima de
5 puede pasar, pero la muestra de 20 cortos no se sustituye por 8.

### 5. Costes

`P6_COST_STRESS` queda **NO_EVALUABLE**: no existe un reprecio exacto del
filtro. `stress_costs.json` pertenece al perfil original de 38 trades y no se
reutiliza. La resta uniforme de costes se conserva solo como diagnóstico.

## Resultado actual por gate

| Gate | Estado | Valor / motivo |
|---|---|---|
| I1_SCOPE | PASS | 0 trades fuera de W1–W6; holdout no leído |
| I2_PARTITION | PASS | 17 + 29 = 46; signal_id únicos |
| S0_TOTAL_SAMPLE | INCONCLUSO | 17 trades; 9 largos / 8 cortos; mínimos 80 y 20/dirección |
| S2_BASELINE | INCONCLUSO | 46 baseline < 60 |
| S3_COHORT | INCONCLUSO | 17 aceptados < 24; 29 rechazados < 30 |
| S4_BLOCK_SAMPLE | INCONCLUSO | Solo 2/6 bloques con baseline ≥6 y aceptados ≥2 |
| S5_SHORT_PARTICIPATION | PASS | 8 cortos ≥ 5 |
| E1_SELECTION | PASS | Δ = +1,3602 R ≥ +0,25 R |
| E2_BOOTSTRAP | INCONCLUSO | IC95 % [+0,3312, +2,3548], p=0,0060; pero 17/29 y 4/6 no cumplen muestra/cobertura |
| E3_MEAN_R | PASS | +1,1088 R ≥ +0,20 R |
| P1_REJECTED_R | PASS | −7,29 R ≤ 0 |
| P2_PF_R | PASS | 3,8955 ≥ 1,25 |
| P3_DRAWDOWN | PASS | DD-R 5,04 ≤ 8; DD-USD 946,38 ≤ 2.000 |
| Q1_QUARTER_COVERAGE | **FALLA** | 4/6 trimestres activos < 5/6; W5 y W6 vacíos |
| Q2_QUARTER_CONSISTENCY | PASS | 3/4 activos con R>0 (75 %); peor activo −0,02 R |
| Q3_QUARTER_CONCENTRATION | **FALLA** | Top-2 concentra 85,28 % > 80 % |
| Q4_REJECTED_CONSISTENCY | **FALLA** | 3/6 trimestres con R rechazado ≤0 < 5/6; W4 sin rechazados |
| Q5_BLOCK_PF | PASS | Umbral 3; 3 bloques evaluables; mínimo PF 1,053 |
| P5_ROBUSTNESS | PASS | Drop-best-3 +9,35 R; drop-best-month +14,58 R; mejor trade 13,68 % |
| P6_COST_STRESS | NO_EVALUABLE | Falta reprecio exacto del filtro |
| P7_MONTHLY_COVERAGE | **FALLA** | 10/18 meses activos; racha cero 6 > 4 |
| P8_SHORTS | PASS | 8 cortos; media +1,285 R; total +10,28 R |
| P9_TREATMENT | PASS | +18,85 R vs +11,56 R; DD 946,38 vs 2.304,46 |

**Global: INCONCLUSO.** No hay promoción. Los fallos de consistencia y
cobertura no se compensan con el buen agregado ni con el bootstrap positivo.

## Demostración de discriminación

La muestra actual demuestra que la recalibración no es cosmética:

- El antiguo `G7` habría dado **PASS** con 4/6 bloques PF>1, aunque W5 y W6
  estaban vacíos. La cláusula “ningún bloque ≥15 trades con PF<0,70” era
  inerte: el máximo era 8.
- El nuevo `Q1_QUARTER_COVERAGE` **FALLA** con 4/6 trimestres activos.
- El nuevo `Q4_REJECTED_CONSISTENCY` **FALLA** con 3/6 trimestres; W4 no tenía
  rechazados y se cuenta como fallo, no como neutral.
- `Q3_QUARTER_CONCENTRATION` **FALLA** con 85,28 % real del neto en dos
  trimestres.
- `Q5_BLOCK_PF` ya tiene un umbral alcanzable (3) y 3 bloques evaluables; no es
  inerte por construcción.

Por tanto, al menos un gate que antes pasaba de forma trivial ahora falla con
los números de la misma muestra.

## Consecuencia

La evidencia histórica permite describir un edge agregado, pero no promocionar
el filtro. Los gates que faltan son de muestra/cobertura/consistencia y no se
pueden “arreglar” cambiando el bootstrap, el umbral de entrada ni la ventana.
El holdout y el protocolo forward permanecen sellados.
