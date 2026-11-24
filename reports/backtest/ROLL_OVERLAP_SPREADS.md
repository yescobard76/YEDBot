# Spreads old/new por solape en los seis rolls

**Fuente:** `data/real/raw_mnq_nq_es_1m.jsonl.gz` (dump Databento con los 24 contratos).  
**Boundary de referencia:** `bars_mnq_nq_es_1m_roll_adjusted.manifest.json`.  
**Método:** `nuevo.close − viejo.close` en timestamps comunes, sesión 09:00–15:59 ET.  
**Holdout:** no usado.  
**Descarga:** no se hizo una descarga nueva; el dump local ya contiene los 24 contratos.

## Resultado por roll

| Roll | Símbolo | Contratos | Boundary aplicado | Boundary recalc | Δ recalc−aplicado | Solape mediana | Δ boundary−mediana | Cierre roll | Apertura switch | Gap overnight implícito | N solape |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | MNQ | MNQH25→MNQM25 | 448.25 | 448.25 | 0.00 | 205.25 | 243.00 | 202.50 | 204.25 | 244.00 | 840 |
| 1 | NQ | NQH25→NQM25 | 448.25 | 448.50 | 0.25 | 205.50 | 243.00 | 204.25 | 204.25 | 244.25 | 838 |
| 1 | ES | ESH25→ESM25 | 104.50 | 104.50 | 0.00 | 51.50 | 53.00 | 50.75 | 51.25 | 53.25 | 840 |
| 2 | MNQ | MNQM25→MNQU25 | -57.00 | -57.00 | 0.00 | 221.75 | -278.75 | 225.25 | 222.00 | -279.00 | 829 |
| 2 | NQ | NQM25→NQU25 | -57.00 | -57.00 | 0.00 | 221.75 | -278.75 | 226.25 | 220.50 | -277.50 | 821 |
| 2 | ES | ESM25→ESU25 | -6.00 | -6.25 | -0.25 | 53.00 | -59.25 | 53.25 | 52.50 | -58.75 | 840 |
| 3 | MNQ | MNQU25→MNQZ25 | 262.50 | 262.50 | 0.00 | 233.00 | 29.50 | 230.25 | 232.50 | 30.00 | 840 |
| 3 | NQ | NQU25→NQZ25 | 262.50 | 261.50 | -1.00 | 233.00 | 28.50 | 229.75 | 232.00 | 29.50 | 829 |
| 3 | ES | ESU25→ESZ25 | 53.50 | 53.50 | 0.00 | 55.25 | -1.75 | 54.75 | 55.25 | -1.75 | 840 |
| 4 | MNQ | MNQZ25→MNQH26 | 171.00 | 171.00 | 0.00 | 255.50 | -84.50 | 258.50 | 260.75 | -89.75 | 840 |
| 4 | NQ | NQZ25→NQH26 | 171.00 | 171.25 | 0.25 | 255.75 | -84.50 | 259.75 | 260.75 | -89.50 | 822 |
| 4 | ES | ESZ25→ESH26 | 59.50 | 59.50 | 0.00 | 59.25 | 0.25 | 59.50 | 59.75 | -0.25 | 840 |
| 5 | MNQ | MNQH26→MNQM26 | 340.25 | 340.25 | 0.00 | 212.25 | 128.00 | 214.75 | 215.25 | 125.00 | 834 |
| 5 | NQ | NQH26→NQM26 | 340.25 | 335.00 | -5.25 | 212.00 | 123.00 | 215.25 | 209.75 | 125.25 | 824 |
| 5 | ES | ESH26→ESM26 | 83.50 | 83.25 | -0.25 | 49.75 | 33.50 | 49.75 | 49.50 | 33.75 | 840 |
| 6 | MNQ | MNQM26→MNQU26 | 560.25 | 561.25 | 1.00 | 279.75 | 281.50 | 277.00 | 277.00 | 284.25 | 837 |
| 6 | NQ | NQM26→NQU26 | 560.25 | 562.50 | 2.25 | 280.00 | 282.50 | 278.75 | 274.00 | 288.50 | 825 |
| 6 | ES | ESM26→ESU26 | 101.50 | 101.50 | 0.00 | 61.00 | 40.50 | 60.00 | 61.25 | 40.25 | 840 |

## Ejemplo de descomposición

Roll 1, MNQ: boundary 448.25 = gap overnight del viejo 244.00 + spread de apertura 204.25. El spread de solape fue 205.25. El boundary no mide el spread: mide el hueco de precio hasta la apertura siguiente.

## Lectura

- Observaciones de solape: **15,019** barras comunes.
- Mediana del valor absoluto de `mediana solape − boundary aplicado`: **84.62 puntos**.
- Mediana del valor absoluto de `boundary − mediana de solape`: **84.50 puntos**.
- Máxima diferencia absoluta `boundary − mediana de solape`: **282.50 puntos**.
- Mediana del gap overnight implícito (`boundary − apertura switch`): **89.62 puntos**.
- `Boundary recalc` es `nuevo.open 09:00 del switch − viejo.close 15:59 del roll`; debe coincidir con `raw_spread` del manifiesto (salvo redondeos y el residual NQ/MNQ).
- El boundary actual **no es un spread de calendario**: es un offset de frontera que incluye el movimiento overnight del contrato viejo. En los seis rolls, el spread de solape se mantiene en ~202–280 (MNQ/NQ) y ~50–62 (ES), pero el boundary cambia de signo y de magnitud (de −57 a 560 en MNQ/NQ, de −6 a 104 en ES).
- `overlap_bars=0` en el manifiesto no significa que no haya solape en el mercado: el manifiesto se calculó sobre el CSV final, que ya tiene solo el contrato activo. El dump crudo sí conserva ambos contratos.
- En NQ, el offset aplicado usa el de MNQ; por eso `Δ recalc−aplicado` puede incluir el residual NQ vs MNQ.
- El CSV `roll_overlap_spreads.csv` contiene cada spread por minuto para auditoría.

## Implicación

- Si el objetivo es **medir el spread entre contratos**, usa la mediana de solape (o el spread al mismo timestamp), no el boundary actual.
- Si el objetivo es **ajustar una serie continua de precios**, el boundary mantiene continuidad de nivel, pero elimina el retorno overnight. Para preservar retornos, el offset debe medirse con ambos contratos en el mismo timestamp (por ejemplo, cierre del roll o apertura del switch), no entre el cierre de un día y la apertura del siguiente.
- No conviene reemplazar el CSV roll-adjusted actual sin decidir esa convención: el cambio afecta la serie histórica. El raw y el CSV actual no se tocaron en esta auditoría.

## Artefactos

- `reports/backtest/roll_overlap_spreads.json`
- `reports/backtest/roll_overlap_spreads.csv`
- `reports/backtest/ROLL_OVERLAP_SPREADS.md`
