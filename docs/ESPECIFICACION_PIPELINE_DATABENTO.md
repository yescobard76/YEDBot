# Especificación del pipeline determinista de Databento

**Versión:** 1.0  
**Fecha:** 2026-11-19  
**Estado:** especificación previa a implementación. No se ha ejecutado ninguna descarga, backtest ni holdout.  
**Ámbito:** adquisición, normalización, validación y procedencia del dataset de 1 minuto para MNQ, NQ y ES.  
**Autoridad:** [`docs/PROTOCOLO_BACKTEST.md`](PROTOCOLO_BACKTEST.md) versión 1.1 y [`docs/protocolo_backtest.lock.json`](protocolo_backtest.lock.json). Si esta especificación contradice el protocolo o el lock, mandan el protocolo y el lock.

> Esta especificación no modifica el protocolo, el lock, la configuración, el holdout ni el código existente. Define el contrato que deberá cumplir una implementación posterior. No se debe ejecutar el holdout como consecuencia de este documento.

---

## 0. Convenciones normativas

- **DEBE / NO DEBE**: requisito obligatorio.
- **PUEDE**: decisión permitida, siempre que quede registrada en el manifiesto.
- **SHA-256**: SHA-256 sobre bytes, salvo que se indique “canónico”.
- **JSON canónico**: UTF-8, claves ordenadas, separadores `,` y `:`, sin espacios decorativos, sin `NaN`/`Infinity`.
- **UTC**: tiempo con zona `+00:00`; los timestamps de Databento son nanosegundos desde la época Unix.
- **ET**: `America/New_York` (IANA), con horario de verano resuelto por la base de datos de zonas horarias. No se usan offsets fijos.
- **Sesión**: fecha ET de la vela, no fecha UTC.
- **`ts_event`**: inicio inclusivo del intervalo de la barra. Para `ohlcv-1m`, el instante de la barra es su minuto de inicio.
- **`instrument_id`**: identificador numérico de Databento. No se asume único globalmente: Databento solo garantiza unicidad dentro de un día y puede reutilizarlo o cambiarlo entre días.
- **Contrato canónico**: código estable del proyecto, por ejemplo `MNQZ25`. Es la clave semántica para rolls, CSV y resultados; `instrument_id` es la clave de unión con la respuesta de Databento, acotada por fecha de sesión.

---

## 1. Objetivo y límites

### 1.1 Objetivo

Producir, de forma reproducible y auditable, un CSV largo de velas de 1 minuto con:

- una fila por símbolo, minuto y contrato activo;
- contratos y vencimientos procedentes de `definition`;
- ventana de sesión RTH correcta, incluidos los cierres anticipados;
- relleno únicamente de minutos aislados sin operaciones;
- un manifiesto de procedencia que permita reconstruir qué se descargó, cómo se normalizó y qué se validó.

El resultado debe poder validarse con `server.market.csv_data` y congelarse con `server.confirmatory` sin modificar el protocolo.

### 1.2 No objetivos

Quedan fuera de esta especificación:

- ejecutar el backtest, el desarrollo o el holdout;
- descargar datos reales en esta tarea;
- modificar `docs/PROTOCOLO_BACKTEST.md` o el lock;
- construir una serie continua o ajustada por el proveedor;
- rellenar sesiones completas, interpolar precios o inventar barras;
- implementar el adaptador live;
- seleccionar parámetros de estrategia o evaluar resultados;
- comparar con una fuente secundaria real en esta tarea.

### 1.3 Dependencias de implementación

La implementación posterior podrá usar el cliente oficial de Databento (`databento>=0.40,<1.0`, ya declarado en `requirements.txt`) y el Python del proyecto. La versión exacta del cliente y de la API debe quedar registrada en el manifiesto.

---

## 2. Entradas y contrato de consulta

### 2.1 Fuente

| Parámetro | Valor obligatorio |
|---|---|
| Proveedor | Databento Historical |
| Dataset | `GLBX.MDP3` |
| Esquema de definiciones | `definition` |
| Esquema de barras | `ohlcv-1m` |
| Codificación de archivo | DBN, con compresión Zstandard cuando el cliente lo permita |
| Zona de petición | UTC |
| Zona de sesión | `America/New_York` |
| Símbolos raíz | `MNQ`, `NQ`, `ES` |
| Contratos | 24 contratos trimestrales: `H25, M25, U25, Z25, H26, M26, U26, Z26` por raíz |
| Serie | Contratos individuales; nunca continua ni ajustada por el proveedor |

La clave de API se lee exclusivamente de `DATABENTO_API_KEY` o de la variable indicada al invocar la herramienta. **Nunca** se escribe en el repositorio, en la configuración de la app, en el frontend, en logs o en el manifiesto.

### 2.2 Consulta de `definition`

La petición DEBE ser equivalente a:

```text
dataset     = GLBX.MDP3
schema      = definition
stype_in    = parent
symbols     = [MNQ.FUT, NQ.FUT, ES.FUT]
stype_out   = raw_symbol
start       = (start_et - 365 días) T00:00:00Z
end         = (end_et + 45 días) T00:00:00Z
encoding    = DBN
compression = zstd
```

Reglas:

1. `start_et` y `end_et` son las fechas ET del rango pre-registrado (2025-01-10 a 2026-10-30 en el protocolo 1.1).
2. La ventana de definiciones es fija y no depende de `date.today()`. Si la fuente no tiene registros futuros, se conserva la respuesta disponible y se aplican las puertas de aceptación; no se cambia la ventana silenciosamente.
3. Se solicitan **todas** las definiciones del rango para las raíces. No se pide únicamente el contrato que parece activo: la definición de un contrato puede aparecer antes de su activación y los registros pueden tener acciones `A`, `M` o `D`.
4. Se conservan los registros crudos de definiciones y su orden de recepción para auditar la selección.
5. La consulta se puede dividir en fragmentos por fecha si el cliente lo requiere. La unión de fragmentos DEBE ser equivalente a la consulta única; cada fragmento y su hash se registran.

### 2.3 Consulta de `ohlcv-1m`

La petición DEBE ser equivalente a:

```text
dataset     = GLBX.MDP3
schema      = ohlcv-1m
stype_in    = raw_symbol
symbols     = los 24 raw_symbol resueltos desde definition
stype_out   = raw_symbol
start       = start_et T00:00:00Z
end         = (end_et + 1 día) T00:00:00Z
encoding    = DBN
compression = zstd
```

Reglas:

1. El rango de barras es **inclusivo en `start_et` y exclusivo en `end_et + 1 día`**; después se filtra por fecha y ventana ET.
2. Se piden contratos individuales. **No** se usa `continuous`, ni una serie ajustada, ni un símbolo continuo del proveedor.
3. La consulta por `raw_symbol` es la forma primaria porque `instrument_id` no es una clave global. Las barras descargadas incluyen `instrument_id`, que se usa para la unión diaria con `definition`.
4. Si se usa `stype_in="instrument_id"` en una implementación alternativa, la petición DEBE dividirse por fecha/sesión para no depender de una supuesta estabilidad global del ID. El resultado y las comprobaciones deben ser equivalentes.
5. No se usan barras de 5 minutos reagregadas ni datos sintéticos.
6. Cualquier fragmentación debe ser determinista y registrarse; no se permite reordenar fragmentos de forma que cambie la selección de duplicados.

### 2.4 Archivo crudo y snapshot

Antes de normalizar, la implementación DEBE conservar localmente:

```text
data/real/databento/raw/<snapshot_id>/
    definitions.dbn.zst
    bars.dbn.zst
    definitions.request.json
    bars.request.json
    download.json
```

- `snapshot_id` es un SHA-256 de la descripción canónica de la consulta y de los hashes de los archivos crudos. No se sobrescribe un snapshot existente.
- Los archivos crudos no se versionan en git ni se redistribuyen; se archivan localmente conforme a la licencia de Databento.
- `download.json` contiene fecha UTC de descarga, versión del cliente, endpoint lógico, parámetros y hashes. No contiene la clave de API.
- Si una nueva descarga produce un hash crudo distinto, se crea un snapshot nuevo y se repite la aceptación. No se mezclan filas de snapshots distintos.

---

## 3. `definition` y contratos por `instrument_id`

### 3.1 Modelo de una definición

Por cada registro de `definition` se conservan, como mínimo:

| Campo normalizado | Origen / regla |
|---|---|
| `source_record_index` | Índice estable dentro de la respuesta cruda, desde 0 |
| `source_ts_recv_ns` | `ts_recv` de Databento |
| `source_ts_event_ns` | `ts_event` de Databento |
| `instrument_id` | `instrument_id`, entero de 32 bits; no se trata como clave global |
| `raw_symbol` | `raw_symbol` original del proveedor |
| `canonical_contract` | raíz + mes + año de dos dígitos |
| `security_update_action` | `A`, `M` o `D` |
| `instrument_class` | Clase de instrumento; se exige futuro outright |
| `security_type` | Si existe, se conserva; no sustituye a la validación de clase |
| `expiration_ns` | `expiration` crudo en nanosegundos UTC |
| `activation_ns` | `activation` crudo en nanosegundos UTC, si existe |
| `expiration_utc` | Representación ISO-8601 UTC con nanosegundos |
| `expiration_et` | Representación ISO-8601 ET con offset |
| `expiration_precision` | `timestamp` o `date`, según la regla 3.3 |
| `expiry_date` | Fecha que se usará para el roll y para la columna `expiry` |
| `roll_date` | Sesión de roll: primera sesión hábil con fecha ≥ `expiry_date - 8 días`; última sesión del contrato saliente |
| `min_price_increment` | Tick nativo del proveedor, conservado |
| `currency`, `exchange`, `underlying`, `contract_multiplier` | Metadatos de procedencia, si existen |

Los precios de `ohlcv-1m` se reciben como enteros con escala 1e-9; no se convierten a `float` para calcular ni para comparar. La conversión a texto decimal se define en la sección 6.

### 3.2 Selección de las 24 definiciones

Algoritmo obligatorio:

1. Leer todos los registros de `definition` del snapshot, incluidos los que no son contratos outright.
2. Conservar únicamente registros de las raíces `MNQ`, `NQ` y `ES` cuyo `raw_symbol` coincida con:

   ```regex
   ^(MNQ|NQ|ES)([HMUZ])([0-9]{1,2})$
   ```

3. Normalizar el año: un dígito `5` → `2025`; dos dígitos `25` → `2025`. El código canónico siempre lleva dos dígitos (`NQZ25`).
4. Descartar spreads, opciones, futuros de otro producto y símbolos no trimestrales. Los contratos trimestrales fuera de los 24 códigos del protocolo (por ejemplo `H27` o `Z24`) se descartan y se cuentan como `out_of_scope_quarterly`; **no** son un error. Un código esperado que falte, o un contrato que use el código de uno de los 24 pero no corresponda a su raíz/mes/año, sí es un error.
5. Agrupar por `(canonical_contract, instrument_id)`. Para cada grupo:
   - todas las definiciones deben declarar la misma `expiration`;
   - el `raw_symbol` debe corresponder a la raíz y al mes del código;
   - si hay varias versiones, se conserva la última versión efectiva con acción `A` o `M`, ordenando por `(ts_recv_ns, ts_event_ns, source_record_index)`; las versiones anteriores quedan en el archivo de auditoría;
   - una acción `D` no puede ser la última versión efectiva de un contrato que se va a usar;
   - si hay dos `expiration` distintas para el mismo contrato, se aborta;
   - no se colapsa un contrato a un único ID: si el mismo contrato canónico tiene varios `instrument_id` a lo largo del rango, se conserva un grupo por ID y la resolución se hace por sesión en 3.4.
6. Exigir exactamente:
   - 24 contratos canónicos;
   - 8 por raíz;
   - los códigos `H25, M25, U25, Z25, H26, M26, U26, Z26` por raíz;
   - ningún contrato esperado ausente.
7. Un `instrument_id` ausente o no entero en una definición utilizada es un error, salvo que la implementación demuestre que el proveedor no lo suministra; en ese caso el contrato queda marcado `instrument_id_missing` y no puede aceptarse para el backtest, porque la unión de barras dejaría de ser determinista.

### 3.3 `expiry` con timestamp

`expiration` es el **último instante elegible para operar**, no una mera etiqueta de fecha. Se conserva siempre el valor crudo y se derivan estos campos:

```text
expiration_ns          entero UTC, sin pérdida
expiration_utc         ISO-8601 UTC, con 9 dígitos fraccionarios
expiration_et          ISO-8601 America/New_York, con offset -04:00/-05:00
expiration_date_utc    fecha del instante en UTC
expiration_date_et     fecha del instante en ET
expiry_date            fecha usada para el contrato y el roll
expiration_precision   timestamp | date
```

Regla de derivación:

1. Si `expiration_ns` es `UNDEF_TIMESTAMP` (`2^64 - 1`) o no es un entero positivo, se aborta.
2. Si el instante UTC tiene una hora distinta de `00:00:00`, se considera precisión `timestamp` y:

   ```text
   expiry_date = expiration_date_et
   ```

   Esto es obligatorio para no desplazar un vencimiento que ocurre después de las 20:00 ET pero antes de medianoche UTC.

3. Si el instante UTC es exactamente `00:00:00`, se considera precisión `date` y:

   ```text
   expiry_date = expiration_date_utc
   ```

   Se registra `expiration_precision="date"` y una advertencia de que el proveedor solo dio precisión de fecha. CME suele publicar `13:30Z` o `14:30Z`; el caso de medianoche debe revisarse, no interpretarse como una hora de trading.

4. `expiry_date` DEBE pertenecer al mes y año del código canónico. Si no coincide, se aborta.
5. `expiration_ns` DEBE ser posterior a `activation_ns` cuando `activation` esté presente y tenga precisión de timestamp.
6. La regla de roll es la del protocolo:

   ```text
   roll_date = primera sesión hábil del calendario del proyecto
               con fecha >= expiry_date - 8 días naturales
   ```

7. El CSV solo lleva `expiry` como fecha ISO (`YYYY-MM-DD`). El timestamp completo, la precisión y la fuente quedan en el manifiesto. **No se pierde el timestamp** al normalizar.

### 3.4 Contratos por `instrument_id`

`instrument_id` se usa para unir cada barra con su definición, pero **no** como identidad global:

- La identidad estable para el protocolo es `canonical_contract`.
- La identidad de unión es `(instrument_id, session_date)`, donde `session_date` es la fecha ET de la barra.
- Para cada sesión y raíz se construye un mapa:

  ```text
  (instrument_id, session_date) -> canonical_contract
  ```

- La definición de un ID se considera efectiva para una sesión si es la última versión `A` o `M` con `ts_recv <= cierre de la sesión` y su `activation` no es posterior al inicio de la sesión.
- Si un `instrument_id` aparece asociado a dos contratos canónicos distintos en la misma sesión, se aborta.
- Si dos `instrument_id` distintos resuelven al mismo contrato canónico en la misma sesión, se aborta: el pipeline no fusiona IDs intra-sesión.
- Si un contrato canónico cambia de `instrument_id` entre sesiones, se permite y se registra la secuencia de IDs; las barras se unen por la fecha, no por el ID antiguo.
- Si una barra trae un `instrument_id` que no está en el mapa de su sesión, se aborta. No se intenta adivinar por `raw_symbol` ni por proximidad de precios.
- El `raw_symbol` de la barra, si existe, se usa solo como comprobación secundaria: debe resolver al mismo contrato canónico que el mapa.
- El CSV final no incluye `instrument_id`; el manifiesto sí incluye el mapa completo por sesión.

### 3.5 Contrato activo y roll

Para cada raíz y cada sesión `D`:

```text
activo(D) = contrato con el menor roll_date tal que roll_date >= D
```

Consecuencias:

- Antes del primer roll, el contrato inicial es el primero de la lista (`H25` para el rango del protocolo).
- En la sesión de roll se usa el contrato saliente; el entrante empieza la sesión siguiente.
- La sesión de roll se conserva en el CSV y en `all_sessions`, pero se excluye de la serie evaluada cuando `exclude_roll_sessions=true`.
- Los contratos de las tres raíces DEBEN tener exactamente las mismas 7 fechas de roll. Si una raíz difiere, se aborta: no se puede construir una barra SMT con contratos desalineados.
- Se verifica que:
  - una barra no sea anterior a `activation` (si hay precisión de timestamp);
  - una barra no sea posterior a `expiration` (si hay precisión de timestamp);
  - en precisión `date`, no haya barras en una sesión posterior a `expiry_date`;
  - un contrato inactivo no aporte filas a la serie; sus barras crudas se descartan y se cuentan;
  - un contrato desconocido o un ID no mapeado sea un error, no un descarte silencioso.

---

## 4. Ventana de sesión

### 4.1 Calendario

Se usa el calendario del proyecto (`server/market/sessions.py`), no un calendario implícito del proveedor:

- días hábiles de lunes a viernes;
- feriados de mercado del proyecto;
- cierres anticipados oficiales de CME para índices;
- fechas del protocolo: 2025-01-10 a 2026-10-30;
- 454 sesiones de calendario, 447 evaluadas después de excluir 7 sesiones de roll.

Cierres anticipados del rango completo:

| Fecha | Cierre RTH | Barras por raíz |
|---|---:|---:|
| 2025-07-03 | 13:00 ET | 240 |
| 2025-11-28 | 13:15 ET | 255 |
| 2025-12-24 | 13:15 ET | 255 |

La lista se deriva del calendario y se contrasta con la tabla; no se codifican offsets fijos. El 2026-07-03 es feriado observado y no es una sesión del dataset.

### 4.2 Ventana de una barra

Para cada barra:

```text
session_date = fecha ET de ts_event
minuto       = hora*60 + minuto ET de ts_event
cierre       = 16:00, o el cierre anticipado oficial de session_date
ventana      = 09:00 <= minuto < cierre
```

- `09:00` es inclusivo; `16:00` es exclusivo. Una barra de 09:00 pertenece a la sesión; una de 16:00 no.
- En cierre anticipado, el último minuto incluido es el anterior al cierre: 12:59 o 13:14.
- Se descartan y se cuentan las barras de premarket, afterhours, días no hábiles y minutos fuera de la ventana. Un día no hábil no se convierte en sesión.
- `ts_event` DEBE estar alineado al minuto y tener `rtype` de `OHLCV-1m` (33). Un timestamp con segundos distintos de cero o nanosegundos residuales se rechaza.
- La zona horaria se resuelve con IANA. No se usan offsets fijos; se prueban explícitamente los cambios de horario de 2025 y 2026.
- Por cada `(session_date, raíz, minuto)` debe existir exactamente una barra después de la selección de contrato activo. Un duplicado conflictivo se aborta; un duplicado idéntico solo puede colapsarse si queda registrado y no altera el hash lógico.

### 4.3 Conteos esperados

| Bloque | Sesiones calendario | Sesiones evaluadas | Barras por raíz |
|---|---:|---:|---:|
| Desarrollo total | 368 | 362 | 154 050 (incluye 3 cierres anticipados) |
| W1 | 55 | 54 | — |
| W2 | 62 | 61 | — |
| W3 | 64 | 63 | — |
| W4 | 64 | 63 | — |
| W5 | 61 | 60 | — |
| W6 | 62 | 61 | — |
| Holdout | 86 | 85 | — |
| Total | 454 | 447 | 190 170 |

Los totales exactos se obtienen del lock y del calendario; la tabla anterior es de control, no una fuente de verdad independiente. El total de minutos de las tres raíces es 570 510.

---

## 5. Relleno de minutos

### 5.1 Regla

Databento no imprime una barra si no hubo operaciones en el intervalo. Para que cada sesión tenga la ventana completa:

1. Construir el conjunto de minutos esperados para `(session_date, raíz)` según la sección 4.
2. Indexar las barras observadas del contrato activo por minuto ET.
3. Verificar que no haya minutos fuera de la ventana.
4. Calcular los minutos faltantes.
5. Agrupar los faltantes en runs consecutivos.
6. Si un run tiene longitud mayor que 1, **abortar**. No se rellena un hueco de dos o más minutos.
7. Si falta el primer minuto de la sesión (09:00), **abortar**: no existe cierre anterior del mismo contrato dentro de la sesión y no se permite usar una sesión anterior.
8. Para cada minuto aislado faltante, crear una barra plana:

   ```text
   timestamp = inicio exacto del minuto ET
   open = high = low = close = cierre de la barra inmediatamente anterior
   volume = 0
   contract = contrato de la barra anterior
   expiry = expiry de la barra anterior
   ```

9. La barra anterior debe pertenecer al mismo contrato y a la misma sesión. No se cruza un roll, una sesión ni un contrato.
10. Registrar el relleno en el CSV auxiliar con, al menos:

    ```text
    timestamp,symbol,contract,expiry,previous_close
    ```

11. Ordenar el CSV auxiliar por `(timestamp, symbol, contract)`.

### 5.2 Límites

- Cada relleno es un minuto aislado: no puede haber dos rellenos consecutivos en la misma raíz/sesión.
- El total de barras planas del dataset completo no puede superar **570** (0,1 % de 570 510 minutos).
- La proporción de relleno debe ser ≤ 0,1 %.
- Una sesión sin ninguna barra no se rellena: es un error de cobertura.
- No se rellena el primer minuto, no se interpola, no se usa el precio de otra raíz, no se usa el cierre de la sesión anterior y no se rellena una sesión completa.
- Si el relleno supera cualquier límite, se aborta y no se escribe el CSV final.

### 5.3 Diferencia entre relleno y hueco real

Un relleno válido solo representa un minuto sin operaciones. Un hueco de varios minutos, una sesión ausente o una barra faltante al inicio son **huecos reales** y bloquean el dataset. El manifiesto debe distinguir:

- `filled_minutes`: filas planas creadas;
- `missing_minutes_before_fill`: minutos ausentes en la respuesta;
- `unfilled_gaps`: grupos no rellenables (debe ser 0 para aceptar);
- `first_minute_missing`: debe ser 0 para aceptar.

---

## 6. Salida CSV

### 6.1 Esquema

El archivo final DEBE ser:

```text
data/real/bars_mnq_nq_es_1m.csv
```

con esta cabecera exacta y en este orden:

```text
timestamp,symbol,open,high,low,close,volume,contract,expiry
```

- `timestamp`: ISO-8601 con zona ET y segundos (`YYYY-MM-DDTHH:MM:SS-05:00` o `-04:00`), sin milisegundos, sin `Z`.
- `symbol`: `MNQ`, `NQ` o `ES`.
- `open`, `high`, `low`, `close`: decimal exacto derivado del entero de Databento, sin notación científica, con al menos dos decimales y sin perder precisión; no se usan `float` para el cálculo.
- `volume`: entero no negativo; no se usa notación decimal si el volumen es integral.
- `contract`: código canónico de dos dígitos de año.
- `expiry`: `YYYY-MM-DD`, derivado del timestamp de `expiration` según la sección 3.3.

El CSV no incluye `instrument_id`; esa relación queda en el manifiesto. No se añaden columnas no previstas por el protocolo.

### 6.2 Orden y escritura

- Encoding UTF-8 sin BOM; salto de línea `\n`.
- Orden: `timestamp` ascendente y, dentro del mismo minuto, `MNQ`, `NQ`, `ES`.
- Una fila por `(timestamp, symbol)`; sin duplicados.
- La escritura final es atómica: se escribe en un archivo temporal dentro del mismo directorio, se valida y se renombra al nombre final. Nunca se deja un CSV parcial con nombre definitivo.
- Si el archivo final ya existe, la ejecución se detiene salvo que se trate de una nueva versión explícita del pipeline y un snapshot distinto; no se sobrescribe silenciosamente.

### 6.3 Validación obligatoria

Después de escribir:

```text
python -m server.market.csv_data data/real/bars_mnq_nq_es_1m.csv --series raw
```

Se exige:

- `ok=true` y `aligned=true`;
- `session_validation.invalid_sessions=0`;
- `session_validation.missing_session_count=0`;
- 454 sesiones de calendario y 447 evaluadas;
- 24 contratos declarados, 24 expiraciones y 21 rolls;
- 190 170 barras comunes y 570 510 minutos de las tres raíces;
- 3 cierres anticipados;
- `series_mode=raw` y `exclude_roll_sessions=true`.

El validador actual calcula `gaps.count` sobre la serie común e incluye el hueco nocturno entre sesiones. Por eso **no se usa `gaps.count=0` como comprobación literal de huecos intra-sesión**. La puerta efectiva es la validación por sesión (`session_validation`) y el conteo de huecos intra-sesión del QA. Esta salvedad debe quedar explícita; si se quiere exigir el literal del protocolo, hace falta una revisión editorial del protocolo antes de ejecutar el holdout. No se cambia el protocolo en esta especificación.

---

## 7. Manifiesto de procedencia

### 7.1 Principios

- Un manifiesto por snapshot aceptado: `reports/backtest/databento_provenance.json`.
- Es inmutable una vez emitido; una nueva descarga produce un snapshot nuevo y un manifiesto nuevo.
- No contiene claves, tokens, cabeceras de autorización ni rutas de secretos.
- Se escribe con JSON canónico y un hash de contenido.
- Enlaza la cadena completa:

  ```text
  consulta -> archivos DBN crudos -> definitions normalizadas
           -> contratos/expiry/rolls -> barras seleccionadas
           -> rellenos -> CSV/fills/summary
           -> validador -> QA de segunda fuente
           -> dataset_manifest.json del modo confirmatorio
  ```

### 7.2 Campos mínimos

| Sección | Campos obligatorios |
|---|---|
| `schema_version` | `databento-provenance-v1` |
| `snapshot_id` | SHA-256 determinista de consulta + hashes crudos |
| `created_at_utc` | Fecha de emisión; excluida del hash de contenido |
| `pipeline` | Versión de la especificación, versión del código, commit o hash de árbol, versión de Python y del cliente Databento |
| `source` | Proveedor, dataset, endpoint lógico, esquemas, encoding, versión de API |
| `queries.definitions` | Todos los parámetros exactos, incluidos `stype_in`, `stype_out`, `symbols`, `start`, `end`, límites y fragmentos |
| `queries.bars` | Todos los parámetros exactos y la lista de 24 `raw_symbol` |
| `raw` | Ruta local, bytes, SHA-256, número de registros y fecha de descarga de cada archivo DBN |
| `definitions` | Conteo, 24 contratos, registros fuente conservados, hashes por registro y reglas de selección |
| `contracts` | `canonical_contract`, raíz, `instrument_ids_by_session`, `raw_symbols`, `expiration_ns`, `expiration_utc`, `expiration_et`, `expiration_precision`, `expiry_date`, `activation_ns`, `roll_date` |
| `rolls` | 7 fechas por raíz, verificación de igualdad entre raíces y sesiones excluidas |
| `sessions` | Rango, 454/447/368/362/86/85, lista de sesiones, cierres anticipados y conteos por sesión/raíz |
| `bars` | Filas por raíz, filas descartadas por motivo (`premarket`, `afterhours`, `non_trading_day`, `inactive_contract`), duplicados y huecos no rellenables |
| `fills` | Ruta, SHA-256, conteo, proporción, máximo permitido, `max_consecutive=1` y lista de minutos rellenados |
| `outputs` | Rutas, bytes, SHA-256 y conteos de `bars.csv`, `fills.csv` y `summary.json` |
| `validation` | Ruta y SHA-256 de `validator.json`, `ok`, `aligned`, `dataset_id`, `series_id`, conteos y errores/advertencias |
| `qa` | `PASS`/`FAIL`/`PENDING`, fuente secundaria, versión, hashes, muestra, métricas y enlace al informe |
| `hashes` | `content_sha256` e `manifest_sha256` con la regla de exclusión indicada |
| `warnings` | Lista de advertencias no bloqueantes, con código y contexto |

### 7.3 Ejemplo de estructura

Los valores son marcadores, no datos reales:

```json
{
  "schema_version": "databento-provenance-v1",
  "snapshot_id": "<sha256>",
  "created_at_utc": "2026-11-19T00:00:00Z",
  "pipeline": {
    "spec_version": "1.0",
    "code_sha256": "<sha256>",
    "databento_client": "<version>"
  },
  "source": {
    "provider": "databento",
    "dataset": "GLBX.MDP3",
    "definition_schema": "definition",
    "bar_schema": "ohlcv-1m"
  },
  "queries": {
    "definitions": {
      "stype_in": "parent",
      "stype_out": "raw_symbol",
      "symbols": ["MNQ.FUT", "NQ.FUT", "ES.FUT"],
      "start": "2024-01-11T00:00:00Z",
      "end": "2026-12-14T00:00:00Z"
    },
    "bars": {
      "stype_in": "raw_symbol",
      "stype_out": "raw_symbol",
      "start": "2025-01-10T00:00:00Z",
      "end": "2026-10-31T00:00:00Z"
    }
  },
  "raw": {
    "definitions": {"path": "<local>", "sha256": "<sha256>", "bytes": 0},
    "bars": {"path": "<local>", "sha256": "<sha256>", "bytes": 0}
  },
  "definitions": {
    "expected": 24,
    "found": 24,
    "contracts": []
  },
  "contracts": [],
  "rolls": {},
  "sessions": {},
  "bars": {},
  "fills": {},
  "outputs": {},
  "validation": {"status": "pending"},
  "qa": {"status": "PENDING"},
  "hashes": {
    "content_sha256": "<sha256>",
    "manifest_sha256": "<sha256>"
  }
}
```

### 7.4 Hash de contenido

- `content_sha256` se calcula sobre el JSON canónico del manifiesto **excluyendo** `created_at_utc`, `hashes.content_sha256` y `hashes.manifest_sha256`, y cualquier campo declarado como volátil.
- `manifest_sha256` se calcula sobre el JSON canónico completo, incluido `content_sha256`, excluyendo solo `hashes.manifest_sha256` para evitar recursión.
- Los hashes de los archivos crudos son SHA-256 de sus bytes exactos. Los hashes de estructuras normalizadas usan JSON canónico.
- El mismo snapshot debe producir el mismo `content_sha256` y los mismos hashes de salida en dos ejecuciones. `created_at_utc` puede cambiar; no se usa como identidad.

### 7.5 Relación con el manifiesto confirmatorio

`reports/backtest/dataset_manifest.json` sigue siendo el manifiesto que exige el modo confirmatorio. El manifiesto de procedencia es evidencia de adquisición y normalización y debe archivarse junto a él. La implementación futura debe hacer que el manifiesto confirmatorio incluya, como mínimo, el SHA-256 de:

- el CSV;
- el CSV de rellenos;
- `databento_provenance.json`;
- `databento_qa.json`;
- `validator.json`.

No se debe ejecutar `run-holdout` como parte de la aceptación del pipeline.

---

## 8. Criterios de aceptación

Todas las puertas son **duras**. Si una falla, no se escribe o no se acepta el CSV final, no se congela el dataset y no se ejecuta el holdout.

| ID | Criterio | Evidencia / umbral |
|---|---|---|
| P1 | Fuente correcta | `GLBX.MDP3`, `definition` y `ohlcv-1m`, contratos individuales, sin continuo ni ajustado |
| P2 | Definiciones completas | 24 contratos, 8 por raíz, sin faltantes, spreads ni opciones; sin conflictos de `expiration`; IDs mapeados por sesión |
| P3 | Expiry y rolls | Timestamp completo conservado; `expiry_date` correcto; 7 rolls por raíz; mismas 7 fechas en MNQ/NQ/ES |
| P4 | Calendario | 454 sesiones, 447 evaluadas, 368/362 desarrollo y 86/85 holdout; 3 cierres anticipados |
| P5 | Cobertura de barras | 420/240/255 según sesión; 190 170 por raíz; 570 510 en total; sin duplicados ni barras fuera de ventana |
| P6 | Relleno | Solo minutos aislados; sin dos consecutivos; máximo 570 y ≤0,1 %; sin relleno del primer minuto ni de sesiones completas |
| P7 | Validación del CSV | Validador con `ok=true`, `aligned=true`, `invalid_sessions=0`, `missing_session_count=0`; D1-D8 con la salvedad de `gaps.count` de la sección 6.3 |
| P8 | Procedencia | Manifiesto completo, hashes de crudos y salidas, sin secretos, con consulta reproducible |
| P9 | Determinismo | Dos ejecuciones desde el mismo snapshot producen bytes idénticos en CSV/fills/summary y el mismo `content_sha256` |
| P10 | QA segunda fuente | `qa.status=PASS` y todas las puertas QA de la sección 9 |
| P11 | Congelación | `confirmatory.freeze` y `confirmatory.verify` pasan; no se ejecuta el holdout |
| P12 | Fallo seguro | Cualquier puerta fallida aborta antes de publicar archivos finales; no se corrige a mano ni se reintenta con parámetros distintos |

### 8.1 Comprobaciones obligatorias de P5

- Una fila por `(timestamp, symbol)`; cero duplicados.
- `high >= max(open, close)` y `low <= min(open, close)`.
- Precios positivos y finitos; volumen entero no negativo.
- `contract` y `expiry` presentes en todas las filas.
- `expiry` no anterior a la sesión de la barra.
- Las tres raíces comparten exactamente los mismos timestamps.
- Ninguna barra de un contrato inactivo, desconocido o vencido.
- Ninguna barra en día no hábil.
- Ningún timestamp en milisegundos; ninguno sin zona.

### 8.2 Comprobaciones obligatorias de P9

- El orden de definiciones y barras se fija por claves explícitas, nunca por orden de un `dict` o de llegada de red.
- Los precios se convierten desde enteros de 1e-9 usando aritmética decimal exacta.
- Las consultas no usan la fecha actual como límite oculto; las ventanas son las registradas.
- Los hashes de los archivos crudos deben coincidir con los del snapshot; si no, se aborta.
- La repetición desde el caché crudo no debe volver a consultar la red.

---

## 9. QA contra una segunda fuente

### 9.1 Fuente secundaria

La QA se hace contra **una única fuente independiente**, fijada antes de descargar y antes de mirar resultados del backtest. Requisitos:

- proveedor distinto de Databento y que no revenda el mismo feed;
- barras de 1 minuto por contrato individual, no una serie continua;
- timestamps convertibles a `America/New_York`;
- contratos y vencimientos identificables;
- licencia que permita el uso local para investigación;
- hash y fecha de descarga archivados.

Candidatas válidas según [`docs/PROVEEDORES.md`](PROVEEDORES.md): Kibot o FirstRate. Se elige **una** y se congela; no se cambia después de ver discrepancias. No se aceptan Yahoo, Kaggle, series continuas ni datos sin procedencia.

Si no hay segunda fuente disponible, el dataset queda `qa.status=PENDING` y no se acepta para el backtest confirmatorio. Un `PENDING` no es un `PASS`.

### 9.2 Muestra

La muestra se genera una sola vez, antes de descargar la segunda fuente, y se guarda en el manifiesto:

1. Todas las sesiones de roll (7).
2. Todas las sesiones con cierre anticipado (3).
3. Primera y última sesión del rango.
4. Una sesión por mes calendario del rango.
5. El 10 % restante de las sesiones, seleccionado determinísticamente por:

   ```text
   ordenar SHA256("databento-qa-v1|<seed>|<fecha>")
   y tomar las primeras ceil(0.10 * restantes)
   ```

   con `seed=20250102`, la semilla del bootstrap del protocolo.

La lista final, sin duplicados, se archiva con su hash. No se permite ampliar ni reducir la muestra después de ver los resultados de la comparación.

### 9.3 Comparaciones y tolerancias

La segunda fuente se normaliza a contrato canónico y a inicio de barra. Si usa barras con timestamp de cierre, se desplaza al inicio y se documenta. Si no se puede normalizar, se rechaza la QA.

| ID | Comparación | Tolerancia / puerta |
|---|---|---|
| QA1 | Cobertura de sesiones y minutos | 100 % de las sesiones de la muestra; 420/240/255 por raíz; 0 faltantes y 0 extra |
| QA2 | Contrato activo, `expiry` y rolls | 100 % de coincidencia; cualquier diferencia bloquea |
| QA3 | Timestamps | 100 % de instantes idénticos; sin duplicados ni desalineación |
| QA4 | Precios OHLC | `close` y `open` dentro de 1 tick en ≥99,9 % de barras y máximo 2 ticks; `high`/`low` dentro de 2 ticks en ≥99,9 % y máximo 3 ticks |
| QA5 | Volumen | Total por sesión/raíz dentro de ±2 %; mediana del error relativo por barra ≤5 % |
| QA6 | Rellenos | Mismo conjunto de minutos ausentes/rellenados; 100 % de coincidencia; sin rellenos consecutivos |
| QA7 | Agregados de sesión | Cierre dentro de 1 tick; máximo/mínimo dentro de 2 ticks; volumen total dentro de ±2 % |
| QA8 | Sesiones de roll y cierre anticipado | Deben estar presentes todas y con la ventana correcta; 100 % |
| QA9 | Procedencia de la QA | Fuente, versión, hash crudo, fecha y muestra archivados; sin secretos |

Definiciones:

- `tick = 0.25` para MNQ, NQ y ES, salvo que la definición del instrumento indique otro tick; en ese caso se usa el tick de la definición y se registra.
- `p99.9` se calcula por el método de rango más cercano sobre las barras comparadas.
- Para QA4, una diferencia de precio se mide en ticks del contrato, no en porcentaje.

### 9.4 Disposición de discrepancias

- QA1, QA2, QA3, QA6 u QA8 con una sola discrepancia: **FAIL**.
- QA4 o QA5 fuera de tolerancia: **FAIL** hasta reconciliación documentada; no se corrigen precios a mano.
- Una diferencia sistemática (por ejemplo, sesgo medio > 0,25 tick) es **FAIL**, aunque el porcentaje global esté dentro del límite.
- Si la diferencia se debe a una convención de la fuente secundaria, se documenta y se renormaliza; si no se puede demostrar, se rechaza.
- Cualquier cambio en el pipeline después de ver la QA exige una nueva versión de la especificación y una nueva QA; no se reutiliza el `PASS`.

### 9.5 Informe

El resultado se guarda en:

```text
reports/backtest/databento_qa.json
```

Debe incluir:

- `status`: `PASS`, `FAIL` o `PENDING`;
- fuente, versión, fecha y SHA-256 del archivo secundario;
- `seed` y lista/hash de la muestra;
- conteos por sesión, raíz y contrato;
- métricas QA1-QA9 y percentiles;
- lista de discrepancias con timestamp, símbolo, contrato, valores y clasificación;
- decisión y justificación;
- hashes de los archivos comparados.

El `databento_provenance.json` debe incluir el SHA-256 de este informe y su estado. El CSV no se considera aceptado hasta que `qa.status=PASS`.

---

## 10. Determinismo y reproducibilidad

El pipeline DEBE cumplir:

1. **Misma entrada, misma salida**: mismo snapshot crudo + misma versión de código + misma configuración => mismos bytes de CSV, fills y summary.
2. **Consulta fija**: no se usan rangos relativos a “hoy” ni aleatoriedad no sembrada.
3. **Orden explícito**:
   - definiciones: `(ts_recv_ns, ts_event_ns, source_record_index)`;
   - barras: `(ts_event_ns, orden de raíz MNQ, NQ, ES, instrument_id)`;
   - fills: `(timestamp, raíz, contract)`;
   - JSON: claves ordenadas.
4. **Sin `float` para precios**: se usan enteros de 1e-9 y `Decimal` para la representación decimal.
5. **Sin estado oculto**: no se depende de la hora local, del orden de un `dict`, de paginación no registrada ni de reintentos que cambien la respuesta.
6. **Caché verificable**: si se reutiliza el snapshot, se comprueban sus hashes antes de normalizar.
7. **Escritura atómica**: los archivos finales solo aparecen tras pasar las puertas.
8. **Doble ejecución**: la aceptación incluye ejecutar dos veces desde el mismo snapshot y comparar hashes de salida.

---

## 11. Secuencia de implementación futura

La implementación posterior deberá seguir este orden, sin saltos:

1. Resolver y registrar la consulta de `definition`.
2. Descargar y archivar las definiciones crudas.
3. Seleccionar las 24 definiciones y construir contratos, timestamps de expiración y rolls.
4. Resolver los 24 `raw_symbol`.
5. Descargar y archivar `ohlcv-1m`.
6. Unir barras por `(instrument_id, session_date)`.
7. Filtrar ventana y contrato activo.
8. Rellenar solo minutos aislados.
9. Escribir CSV, fills y summary de forma atómica.
10. Ejecutar el validador.
11. Emitir el manifiesto de procedencia.
12. Ejecutar la QA contra la segunda fuente y emitir su informe.
13. Congelar el dataset con el modo confirmatorio.
14. Detenerse: **no ejecutar el holdout**.

---

## 12. Riesgos y observaciones bloqueantes

1. **`instrument_id` no es una clave global.** La implementación que lo use como identidad única producirá uniones incorrectas si el proveedor cambia o reutiliza IDs. Es obligatorio el mapa `(instrument_id, session_date)`.
2. **`expiration` puede tener solo precisión de fecha.** No se debe inventar una hora de trading ni aplicar la conversión ET a un valor de medianoche UTC sin marcarlo.
3. **`gaps.count` del validador incluye el hueco nocturno.** No es un criterio intra-sesión. La aceptación usa `session_validation` y un conteo específico de huecos intra-sesión. El protocolo 1.1 mantiene la redacción original; si se exige el literal `gaps.count=0`, debe corregirse editorialmente antes de ejecutar el holdout.
4. **La segunda fuente no está seleccionada en esta tarea.** Hasta fijarla y obtener `PASS`, el pipeline no es apto para el backtest confirmatorio.
5. **La versión de la API puede cambiar la respuesta.** El snapshot crudo y la versión del cliente son parte de la identidad; una nueva descarga no se mezcla con la anterior.
6. **Licencia y residencia de datos.** Los archivos crudos y el CSV no se versionan ni se redistribuyen; se conservan localmente con sus hashes.

---

## 13. Referencias

- Protocolo del proyecto: [`docs/PROTOCOLO_BACKTEST.md`](PROTOCOLO_BACKTEST.md), versión 1.1.
- Lock del protocolo: [`docs/protocolo_backtest.lock.json`](protocolo_backtest.lock.json).
- Comparativa de proveedores: [`docs/PROVEEDORES.md`](PROVEEDORES.md).
- Validador existente: `server/market/csv_data.py`.
- Calendario y cierres: `server/market/sessions.py`.
- Contratos y expiraciones de respaldo: `server/market/contracts.py`.
- Referencia de Databento, `definition`: <https://databento.com/docs/schemas-and-data-formats/instrument-definitions>.
- Referencia de Databento, `ohlcv-1m`: <https://databento.com/docs/schemas-and-data-formats/ohlcv>.
- Referencia de Databento, identificadores de instrumento: <https://databento.com/docs/standards-and-conventions/common-fields-enums-types>.
- Referencia de Databento, simbología: <https://databento.com/docs/standards-and-conventions/symbology>.
- Referencia de Databento, `timeseries.get_range`: <https://databento.com/docs/api-reference-historical/timeseries/timeseries-get-range>.

---

**Fin de la especificación.** No se implementa ni se ejecuta en esta fase.
