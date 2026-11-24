# Plan de calibración de ejecución con datos de tick

**Versión:** 1.0  
**Fecha:** 2026-11-19  
**Estado:** plan previo a ejecución. No se ha descargado ningún dato de tick, no se ha ejecutado ningún replay tick y no se ha tocado el holdout.  
**Ámbito:** calibrar el modelo de ejecución de MNQ con datos L1 de 20–30 sesiones de desarrollo, comparando el camino de velas de 1 minuto con el camino de tick.  
**Autoridad:** [`docs/PROTOCOLO_BACKTEST.md`](PROTOCOLO_BACKTEST.md) 1.1, [`docs/protocolo_backtest.lock.json`](protocolo_backtest.lock.json) y [`docs/ESPECIFICACION_PIPELINE_DATABENTO.md`](ESPECIFICACION_PIPELINE_DATABENTO.md). El protocolo y el lock siguen mandando.

> Este documento es un plan. No autoriza una descarga, no crea un dataset nuevo y no modifica la configuración congelada. Cualquier cambio de los supuestos de ejecución del protocolo exige una versión nueva del protocolo y un holdout nuevo; los escenarios de este plan son análisis de sensibilidad y evidencia para esa decisión, no una modificación retroactiva del lock.

---

## 1. Pregunta y decisión que habilita

La pregunta es:

> ¿Cuánto se desvía el camino de ejecución modelado con velas de 1 minuto (`next_open`, slippage fijo, SL primero en barras ambiguas) del camino que habría producido el mismo conjunto de señales si las entradas, stops, targets y cierres se resolvieran con datos de tick?

La calibración debe producir:

1. una comparación trazable entre el camino 1m y el camino tick, señal por señal;
2. una distribución empírica de slippage de entrada, slippage de salida, gaps de stop, retraso de fill y fills parciales;
3. tres escenarios congelados —optimista, base y conservador— construidos con reglas pre-registradas;
4. una recomendación explícita sobre si el slippage fijo actual (1 tick, máximo 4) es defendible o si hace falta un protocolo nuevo.

No debe producir una estrategia nueva, una reoptimización de parámetros ni una decisión basada en el P&L de los escenarios.

---

## 2. Límites y no objetivos

### 2.1 Dentro del alcance

- 20–30 sesiones del **desarrollo**, nunca del holdout.
- MNQ como instrumento de ejecución.
- Datos L1 de tick (`mbp-1`) de Databento `GLBX.MDP3`.
- Replay de las mismas señales y los mismos niveles de stop/target del camino 1m.
- Comparación de precios, tiempos, motivo de salida, MFE/MAE y P&L.
- Fijación de escenarios de ejecución y su aplicación como sensibilidad al motor 1m.

### 2.2 Fuera del alcance

- descargar datos en esta tarea;
- usar el holdout (2026-07-01 a 2026-10-30);
- recalibrar la estrategia, sus parámetros o sus señales;
- cambiar el lock, el protocolo o la configuración primaria;
- modelar el libro completo, la cola de órdenes o el impacto de mercado;
- simular un broker real, latencia de red real o rechazos de broker;
- elegir el escenario que produzca mejor P&L;
- ejecutar el backtest confirmatorio o el holdout.

### 2.3 Estado actual que se calibra

El motor 1m actual:

- arma la señal al cierre de una vela;
- ejecuta en la apertura de la siguiente (`fill_model=next_open`);
- aplica un único `slippage_ticks`, acotado por `max_slippage_ticks`;
- usa el mismo slippage para entrada, stop y target;
- aplica SL primero si una vela toca stop y target;
- no modela latencia, cola, profundidad ni fills parciales por defecto (`simulate_partial_fills=false`);
- cierra posiciones a `session_close_time=15:55`.

La calibración debe medir estas simplificaciones, no ocultarlas.

---

## 3. Muestra de 20–30 sesiones

### 3.1 Regla de selección

Se seleccionan **24 sesiones objetivo**, con un mínimo de 20 y un máximo de 30. Todas deben pertenecer al desarrollo (`2025-01-10` a `2026-06-30`) y tener un CSV 1m aceptado.

La muestra se congela antes de descargar tick y se guarda en:

```text
reports/calibration/execution_sample.json
```

con la lista de fechas, la regla, la semilla y su SHA-256.

### 3.2 Estratos obligatorios

1. **Todas las sesiones de roll del desarrollo:** 6 sesiones.
   - 2025-03-13
   - 2025-06-12
   - 2025-09-11
   - 2025-12-11
   - 2026-03-12
   - 2026-06-10

   La séptima sesión de roll del protocolo, 2026-09-10, pertenece al holdout y **no se usa**.

2. **Todos los cierres anticipados del desarrollo:** 3 sesiones.
   - 2025-07-03 (13:00 ET)
   - 2025-11-28 (13:15 ET)
   - 2025-12-24 (13:15 ET)

3. **Fronteras del desarrollo:** 2 sesiones.
   - 2025-01-10 (primera)
   - 2026-06-30 (última)

Estos 11 estratos son obligatorios aunque alguna sesión no tenga señales. Sirven también para validar ventanas, rolls y cierres.

### 3.3 Sesiones adicionales

Hasta llegar a 24, se eligen del resto de sesiones de desarrollo con al menos una señal ejecutada de la variante `full` en el camino 1m de referencia:

```text
ordenar SHA256("execution-calibration-v1|20250102|<fecha>")
y tomar las primeras 13 sesiones con señal
```

Si hay menos de 13 sesiones con señal, se completan con las primeras sesiones restantes del mismo orden determinista. No se seleccionan por P&L, win rate, volatilidad ni resultados de la estrategia.

Se reservan 6 sesiones adicionales, en el mismo orden, para reemplazos técnicos. Solo se sustituye una sesión si el proveedor no entrega datos, el archivo está corrupto o falta la cobertura de un contrato; nunca porque el resultado de la calibración sea incómodo.

### 3.4 Extensiones

- Si hay menos de 20 sesiones válidas tras los reemplazos, la calibración es **INCONCLUSA**.
- Si hay menos de 10 operaciones ejecutadas comparables, la calibración es **PROVISIONAL** y no se adopta ningún escenario.
- Se puede ampliar de 24 a 30 sesiones usando la lista de reserva ya congelada, sin mirar el P&L, si el objetivo es mejorar la precisión de los cuantiles.
- No se permite ampliar la muestra después de ver los escenarios o los resultados.

---

## 4. Qué descargar

### 4.1 Fuente y esquema

| Elemento | Decisión |
|---|---|
| Proveedor | Databento Historical |
| Dataset | `GLBX.MDP3` |
| Instrumento principal | MNQ |
| Esquema de ejecución | `mbp-1` |
| Esquema de definiciones | `definition` |
| Cobertura | 24 sesiones del desarrollo |
| Contratos | Contrato activo por sesión; ambos en sesiones de roll |
| Serie | Contratos individuales, nunca continua |
| Encoding | DBN con compresión Zstandard |
| Zona de petición | UTC |
| Zona de sesión | `America/New_York` |

`mbp-1` es suficiente y preferible a descargar `trades` por separado: incluye **todos los trades y todos los cambios del mejor bid/ask**, con precio, tamaño, lado agresor, tamaños del BBO y timestamps. No incluye detalle de fills pasivos ni prioridad de cola; eso se trata como una limitación explícita y se compensa con reglas conservadoras, no se inventa.

### 4.2 Consulta por sesión

Para cada sesión seleccionada, con el contrato activo resuelto por el manifiesto 1m:

```text
dataset     = GLBX.MDP3
schema      = mbp-1
stype_in    = raw_symbol
stype_out   = raw_symbol
symbols     = raw_symbol del contrato activo
start       = fecha de sesión T00:00:00Z
end         = (fecha de sesión + 1 día) T00:00:00Z
encoding    = DBN
compression = zstd
```

Reglas:

- No se usa symbology `continuous`.
- En una sesión de roll se descargan el contrato saliente y el entrante para verificar la transición; la simulación usa el activo según la regla del protocolo.
- La consulta se hace por sesión para controlar tamaño, coste y reanudación. Se puede usar batch si una sesión supera 5 GB.
- Los registros se filtran a la ventana RTH después de descargar; descargar premarket/afterhours no los convierte en datos de sesión.
- El `instrument_id` se resuelve por sesión con el mapa de la especificación de Databento; no se asume que sea global.
- Se descarga `definition` para el rango de sesiones si no está ya en el snapshot aceptado; sirve para resolver `raw_symbol`, `expiration`, `instrument_id` y tick size.
- `status` es opcional, pero recomendable para detectar halts o estados de mercado; si se descarga, se registra como evidencia y no se usa para inventar fills.

### 4.3 Qué no descargar

- No se descarga `trades` por separado: es un subconjunto de los trades de `mbp-1` para este propósito y cuesta más por GB.
- No se descargan NQ ni ES en tick para el núcleo: el camino de señal usa sus velas 1m aceptadas y no se recalcula la estrategia.
- No se descargan series continuas ni ajustadas.
- No se descarga el holdout.
- No se descarga `ohlcv-1m` si el CSV 1m ya está validado y congelado; si no existe, el plan se bloquea, no se sustituye por datos sintéticos.

### 4.4 Coste y control previo

Antes de descargar:

1. Ejecutar `metadata.get_cost` para la consulta exacta de cada sesión y para el total.
2. Registrar el importe estimado, el número de registros y el tamaño estimado en `reports/calibration/download_quote.json`.
3. Aprobar un presupuesto máximo antes de la primera descarga.
4. Si el coste o el volumen superan el presupuesto, reducir la muestra **antes** de descargar, respetando el mínimo de 20 sesiones y los estratos obligatorios; no se recorta después de ver los datos.

Precio de referencia: `mbp-1` histórico de `GLBX.MDP3` figura en la lista de precios de Databento a **1,80 USD/GB** no comprimido (frente a 28 USD/GB de `trades`). Es una referencia, no una cotización firme: el importe válido es el que devuelva la API para la consulta concreta.

### 4.5 Archivo local

```text
data/real/databento/tick/<snapshot_id>/
    <session_date>/
        <raw_symbol>.mbp-1.dbn.zst
        request.json
    definitions.dbn.zst
    download.json
```

- `snapshot_id` incluye la consulta canónica y los hashes de los archivos.
- No se versiona en git ni se redistribuye; se conserva localmente según la licencia.
- `download.json` contiene hashes, bytes, fecha, versión del cliente y consulta; nunca la clave de API.
- Un archivo que no coincida con su hash se descarta y se reemplaza desde el snapshot; no se mezcla con el resto.

### 4.6 Consulta extendida opcional

Si se quiere validar también el camino completo de señal, se puede descargar `mbp-1` de NQ y ES para **5–8 sesiones** de la muestra, no para las 24. Es una extensión de validación, no un requisito para calibrar fills de MNQ. Si se usa, debe congelarse antes de mirar resultados y aplicar las mismas reglas de archivo y coste.

---

## 5. Comparar el camino de 1m con el camino de tick

### 5.1 Preparación: referencia 1m congelada

Antes de tocar tick:

1. Validar el CSV 1m con `series_mode=raw` y `exclude_roll_sessions=true`.
2. Cargar el perfil del lock y comprobar que coincide exactamente.
3. Ejecutar la variante `full` solo sobre las sesiones seleccionadas, con la configuración congelada.
4. Guardar la lista de señales y operaciones, no solo las métricas agregadas:

   ```text
   signal_id, session_date, contract, expiry, direction, qty,
   signal_ts, expected_entry_ts, entry_price_1m, stop, target,
   exit_ts_1m, exit_price_1m, exit_reason_1m, pnl_1m, r_1m,
   mfe_r_1m, mae_r_1m, ambiguous_bar_1m
   ```

5. Guardar el hash del dataset, del lock y de la lista de señales.

La referencia 1m es la que se compara; no se vuelve a ejecutar la estrategia con tick para “mejorar” las señales. La calibración es de ejecución.

### 5.2 Reconstrucción tick → 1m

Antes de comparar fills, demostrar que el tick reproduce el 1m:

1. Seleccionar los registros `action=T` de `mbp-1` del contrato activo.
2. Agrupar por minuto ET usando `ts_recv`, que es el criterio con el que Databento construye `ohlcv-1m`.
3. Calcular `open`, `high`, `low`, `close` y `volume` por minuto.
4. Añadir los minutos planos del CSV auxiliar de rellenos cuando no hubo trades.
5. Comparar con el CSV 1m aceptado:
   - timestamps exactos;
   - precios exactos al tick;
   - volumen exacto;
   - contrato y `expiry` exactos;
   - 420/240/255 barras por sesión/raíz;
   - mismos minutos rellenados.

Si la reconstrucción no coincide, el problema es de datos, de calendario o de agregación. Se detiene la calibración de fills; no se “ajusta” el 1m ni se descartan sesiones para hacerlo pasar.

### 5.3 Replay 1m de referencia

Para cada señal ejecutada en la referencia:

- entrada: apertura del minuto siguiente;
- slippage: 1 tick adverso, con el tope actual;
- stop: precio de stop, salvo gap al open;
- target: target con slippage adverso;
- si la vela toca stop y target: stop primero;
- cierre de sesión: 15:55;
- sin fills parciales;
- comisión 0,62 USD por lado.

El resultado es el **camino 1m**.

### 5.4 Replay tick

Para cada señal de la referencia, con los mismos `stop`, `target`, `qty` y dirección:

1. **Liberación de la orden:** en la apertura del minuto siguiente a la señal, más la latencia del escenario. La señal 1m solo se conoce al cierre; no se puede ejecutar antes.
2. **Reloj de disponibilidad:** ordenar los registros de `mbp-1` por `(ts_recv, sequence, ts_event, índice)`. Un registro solo es elegible si `ts_recv >= liberación`.
3. **Entrada market:**
   - compra: primer ask válido después de la liberación;
   - venta: primer bid válido;
   - si no hay BBO, el registro no es elegible para un fill market;
   - registrar `ts_event`, `ts_recv`, precio, tamaño y spread.
4. **Stop:**
   - dispara cuando el trade o el BBO cruza el nivel, según el escenario;
   - el fill es al siguiente precio elegible del lado correspondiente;
   - un gap se paga al primer precio disponible, no al nivel teórico;
   - registrar `gap_stop` y slippage.
5. **Target:**
   - orden limit; para una posición larga se vende en el bid, para una corta se compra en el ask;
   - `optimistic`: fill al toque;
   - `base`: fill cuando el BBO alcanza el nivel;
   - `conservative`: fill solo cuando un trade atraviesa el nivel al menos 1 tick;
   - si no se llena, la posición sigue hasta stop o cierre de sesión.
6. **Ambigüedad:** si stop y target se tocan en el mismo registro/evento, aplicar la regla del escenario (`stop` primero en conservador, orden de secuencia en base, target primero en optimista) y registrar la resolución.
7. **Cierre de sesión:** a las 15:55 ET, cerrar a market con el primer precio elegible; no mantener overnight.
8. **Fills parciales:** desactivados en optimista/base; en conservador, usar el 60 % del tamaño y dejar el resto para el siguiente precio elegible, si el escenario lo permite.
9. **Sin look-ahead:** no se leen registros posteriores para decidir el fill; el registro que llena es el primero elegible, no el mejor del minuto.
10. **Sin estrategia:** no se reevalúa ORB, SMT, retesteo ni riesgo. Solo se ejecuta la señal congelada.

### 5.5 Dos comparaciones

**A. Por señal, aislada (primaria).**

Cada señal se simula por separado desde su entrada hasta su salida o cierre de sesión. Evita que una salida tardía en tick bloquee señales posteriores y permite comparar la calidad de ejecución de la misma señal.

**B. Secuencial, tipo cartera (secundaria).**

Se reproducen las señales en orden, con una sola posición y las mismas reglas de riesgo. Sirve para ver el efecto acumulado y la dependencia del camino; no se usa para fijar los escenarios.

### 5.6 Métricas de comparación

Por señal:

```text
entry_diff_ticks      = diferencia de precio de entrada, con signo adverso
exit_diff_ticks       = diferencia de precio de salida, con signo adverso
entry_delay_ms        = ts_event del fill tick - apertura 1m de referencia
exit_delay_ms
stop_gap_ticks
target_shortfall_ticks
spread_at_entry_ticks
pnl_diff_usd
r_diff
mfe_diff_r
mae_diff_r
exit_reason_match     = sí/no
fill_status           = filled / not_filled / partial
ambiguous_resolution  = stop_first / target_first / no_ambigua
```

Agregados:

- mediana, P10, P90 y P95 de cada diferencia;
- sesgo medio por dirección y por sesión;
- tasa de fills, tasa de target y tasa de stop;
- diferencias de P&L, PF y expectativa;
- número de señales donde el camino tick no habría llenado la entrada;
- número de targets que el 1m daba por llenados y tick no;
- número de barras ambiguas que tick resuelve de forma distinta;
- intervalos bootstrap de las métricas de ejecución.

Las diferencias de P&L se reportan, pero **no se usan para elegir el escenario**.

---

## 6. Cómo fijar los escenarios

### 6.1 Principio

Los escenarios se fijan con la **distribución de errores de ejecución del camino tick**, no con el resultado de la estrategia. El orden es obligatorio:

1. calcular las métricas de ejecución;
2. fijar y hashear los parámetros;
3. recién entonces aplicar los escenarios al motor 1m;
4. reportar la sensibilidad.

Si se invierte el orden, el escenario deja de ser calibración y se convierte en selección por P&L.

### 6.2 Métricas primitivas

Para cada señal ejecutada, con el camino tick neutral (entrada a BBO, stop al primer precio elegible, target al toque, sin latencia añadida):

```text
entry_adverse_ticks
exit_adverse_ticks
stop_adverse_ticks
target_shortfall_ticks
fill_delay_ms
spread_ticks
fill_ratio
```

Se calculan contra el camino 1m de la misma señal. La dirección se normaliza para que un valor positivo sea siempre adverso, tanto en largos como en cortos.

Se reportan por separado largos y cortos. Si la diferencia entre direcciones supera 1 tick en la mediana, se documenta; el escenario principal usa la distribución combinada.

### 6.3 Cuantiles y regla de redondeo

Con al menos 10 operaciones:

- **Optimista:** P10 de la métrica adversa, con suelo en 0 ticks; latencia 0 ms; target al toque; sin fills parciales.
- **Base:** P50 (mediana); latencia 250 ms; target al toque; sin fills parciales.
- **Conservador:** P95 + 1 tick de colchón; latencia 1.000 ms; target solo con 1 tick de atravieso; fills parciales al 60 %; stop primero en ambigüedad.

Los valores se redondean al tick de 0,25:

- optimista: hacia abajo, nunca por debajo de 0;
- base: al tick más cercano;
- conservador: hacia arriba.

La latencia y la regla de fills parciales son **supuestos de escenario**, no mediciones de red: se fijan ahora y se declaran como tales. Los cuantiles de slippage sí salen de tick.

### 6.4 Incertidumbre

- Bootstrap de 10.000 remuestreos de operaciones, semilla `20250102`, percentiles 2,5/10/50/90/97,5.
- Si el intervalo del P50 o del P95 supera 1 tick de ancho, el escenario es **PROVISIONAL**.
- Si hay menos de 10 operaciones, no se fija ningún escenario; el resultado es **INCONCLUSO**.
- Si el P95 + 1 supera el máximo de 4 ticks del motor actual, se reporta el valor sin recortar y se usa 4 ticks solo para la sensibilidad 1m, marcado como `capped=true`. No se presenta ese recorte como calibración exacta.

### 6.5 Tabla de escenarios

| Parámetro | Optimista | Base | Conservador |
|---|---|---|---|
| Latencia | 0 ms | 250 ms | 1.000 ms |
| Entrada market | BBO inmediato | BBO al primer registro | BBO + 1 tick |
| Stop | al nivel, sin colchón | primer precio elegible | primer precio + 2 ticks |
| Gap de stop | open | open + slippage | open + 2 ticks |
| Target | fill al toque | fill al toque | requiere 1 tick de atravieso |
| Ambigüedad | target primero | orden de secuencia | stop primero |
| Fills parciales | no | no | 60 % / resto |
| Comisión por lado | 0,62 USD | 0,62 USD | 0,62 USD |
| Slippage máximo | 0 ticks | P50, máximo 4 | P95+1, máximo 4 |

La tabla es la **regla de composición**. Los números de slippage de la columna base/conservador se sustituyen por los cuantiles calculados; no se eligen a mano. La tabla vacía antes de la calibración se conserva en `execution_scenarios.json` con `status="pending"` hasta que se rellene y se hashee.

### 6.6 Correspondencia con el motor 1m actual

El motor 1m solo tiene un `slippage_ticks` común y un flag de fills parciales. Por tanto:

```text
slippage_ticks_sensibilidad =
    ceil(max(entry_adverse, exit_adverse)) del escenario
max_slippage_ticks = 4
simulate_partial_fills = true solo en conservador
```

- `optimista`: slippage 0, sin parciales.
- `base`: slippage P50 redondeado, sin parciales.
- `conservador`: slippage P95+1, con parciales; si supera 4, `capped=true`.
- **S0 (protocolo):** el valor congelado actual, 1 tick y sin parciales, se mantiene como referencia separada. No se cambia el lock.
- Si la mediana calibrada difiere de 1 tick, se reporta `base_calibrado` y `S0` por separado. Adoptar un nuevo valor requiere una versión nueva del protocolo.
- El motor 1m no puede representar latencia, cola ni target condicional por sí solo; la sensibilidad 1m es una **aproximación conservadora**, no una réplica del camino tick.

### 6.7 Aplicación y reporte

Después de congelar los escenarios:

1. Ejecutar la variante `full` en 1m con `S0`, optimista, base y conservador, sobre la misma muestra.
2. Reportar P&L, PF, expectativa, drawdown, tasas de fill y diferencias por sesión.
3. Marcar los escenarios como análisis de sensibilidad, no como resultados confirmatorios.
4. No seleccionar el escenario con mejor P&L.
5. No usar esta calibración para desbloquear el holdout ni para cambiar el protocolo dentro de la versión 1.1.

---

## 7. Criterios de aceptación del plan

| ID | Criterio | Umbral |
|---|---|---|
| C1 | Muestra | 20–30 sesiones, objetivo 24; todas del desarrollo; ninguna del holdout |
| C2 | Cobertura tick | 100 % de las sesiones seleccionadas y contratos activos con archivo válido |
| C3 | Reconstrucción 1m | OHLCV, timestamps, contratos, expiries y rellenos exactos en el 100 % de los minutos seleccionados |
| C4 | Señales comparables | 100 % de las señales ejecutadas del camino 1m identificadas y emparejadas; 0 pérdidas inexplicadas |
| C5 | Operaciones | ≥10 operaciones comparables para fijar escenarios; 10–19 → `PROVISIONAL`; <10 → `INCONCLUSO` |
| C6 | Escenarios | Parámetros calculados por la regla de la sección 6, congelados y hasheados antes de mirar P&L |
| C7 | Incertidumbre | Bootstrap documentado; si el intervalo relevante >1 tick, marcar `PROVISIONAL` |
| C8 | Protocolo | `S0` intacto; ningún cambio de lock/protocolo; holdout sin ejecutar |

Si C1–C4 fallan, no se fija ningún escenario. Si C5–C7 quedan provisionales, se reporta la calibración como provisional y no se adopta un cambio de ejecución.

---

## 8. Entregables previstos

No se crean en esta tarea, pero la ejecución futura debe generar:

```text
reports/calibration/execution_sample.json
reports/calibration/download_quote.json
reports/calibration/tick_1m_validation.json
reports/calibration/execution_1m_reference.json
reports/calibration/execution_tick_paths.json
reports/calibration/execution_scenarios.json
reports/calibration/execution_calibration.md
```

Y conservar localmente:

```text
data/real/databento/tick/<snapshot_id>/
```

Cada entrega debe incluir hashes de datos crudos, CSV 1m, lista de señales, resultados 1m, resultados tick, escenarios y configuración usada. El informe final debe indicar claramente:

- sesiones usadas y exclusiones;
- número de señales y fills;
- diferencias 1m vs tick;
- escenarios y su nivel de confianza;
- si el slippage fijo de 1 tick es defendible, conservador o insuficiente;
- limitaciones y decisión propuesta;
- confirmación de que el holdout no se tocó.

---

## 9. Secuencia de trabajo

1. Congelar la lista de 24 sesiones y la lista de reserva.
2. Validar que el CSV 1m y el perfil del lock son los aceptados.
3. Ejecutar la referencia 1m y congelar señales y operaciones.
4. Estimar coste con `metadata.get_cost` y aprobar presupuesto.
5. Descargar `mbp-1` por sesión (no en esta tarea).
6. Reconstruir 1m desde tick y comparar.
7. Ejecutar los caminos tick por señal y secuencial.
8. Calcular distribuciones y bootstrap.
9. Fijar y hashear los escenarios.
10. Aplicar las sensibilidades al motor 1m.
11. Emitir el informe y la recomendación.
12. Detenerse antes del holdout.

---

## 10. Riesgos y limitaciones

- **MBP-1 no tiene prioridad de cola.** Un fill limit al toque puede ser demasiado optimista; por eso el escenario conservador exige atravieso y el base no promete cola.
- **No hay profundidad más allá del nivel 1.** El impacto de una orden mayor que el tamaño del BBO no se puede modelar con exactitud; se usa tamaño y fills parciales como aproximación.
- **`ts_event` y `ts_recv` no son lo mismo.** La disponibilidad local se modela con `ts_recv`; el orden económico se registra con `ts_event` y `sequence`. No se mezclan sin documentarlo.
- **La latencia no se mide con datos históricos.** Los valores 0/250/1.000 ms son supuestos de escenario y deben declararse como tales.
- **La muestra es pequeña.** 20–30 sesiones no demuestran una distribución estable; los cuantiles son una calibración operativa, no una garantía estadística.
- **El motor 1m no puede representar todos los matices.** La sensibilidad 1m con un único slippage es una aproximación; la comparación tick es la evidencia principal.
- **Riesgo de snooping.** Elegir sesiones, escenarios o fuentes después de ver P&L invalida la calibración. La lista y la regla se congelan antes.
- **Licencia y tamaño.** Los datos tick son locales, no se redistribuyen y pueden ser grandes; el coste se aprueba antes de descargar.
- **Holdout.** Ninguna parte de este plan puede usar, mirar ni inferir el holdout.

---

## 11. Referencias

- Protocolo: [`docs/PROTOCOLO_BACKTEST.md`](PROTOCOLO_BACKTEST.md).
- Lock: [`docs/protocolo_backtest.lock.json`](protocolo_backtest.lock.json).
- Pipeline de datos: [`docs/ESPECIFICACION_PIPELINE_DATABENTO.md`](ESPECIFICACION_PIPELINE_DATABENTO.md).
- Motor de ejecución: `server/execution.py`.
- Backtest y señales: `server/backtest.py`.
- Estrategia y niveles: `server/strategy/strategy.py`, `docs/ESTRATEGIA.md`.
- Databento MBP-1: <https://databento.com/docs/schemas-and-data-formats/mbp-1>.
- Databento GLBX.MDP3: <https://databento.com/docs/venues-and-datasets/glbx-mdp3>.
- Databento precios: <https://databento.com/pricing>.

---

**Fin del plan.** No se descarga ni se ejecuta nada en esta fase.
