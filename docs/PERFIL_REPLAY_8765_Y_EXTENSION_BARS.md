# Perfil de replay 8765 y extensión de `bars.csv`

**Fecha:** 2026-11-25
**Objeto:** preparar un perfil y una DB nuevos para volver a generar señal sin tocar `profiles/live_8765`, y documentar qué haría falta para extender `data/bars.csv` como experimento nuevo.
**Naturaleza:** se creó un perfil aislado y una DB vacía; **no se arrancó, paró ni reinició el 8765**, no se ejecutó ningún backtest, no se tocó el holdout y no hubo commits.

---

## 0. Resumen

- El replay del 8765 es **de una sola pasada**: `CSVFeed.next_tick()` devuelve `None` al llegar al final del CSV y el motor se detiene. `loop_sessions=true` no lo evita porque `CSVFeed` no lo implementa.
- **Perfil nuevo:** `profiles/live_8765_replay/`, copia exacta de la config manual con **un solo cambio**: `feed.start_date = "2026-04-01"`. Conserva la estrategia y el riesgo del 8765.
- **DB nueva:** `profiles/live_8765_replay/yedbot.db`, esquema inicializado y **0 trades / 0 eventos / 0 kv**. No se copió ni se borró nada de `profiles/live_8765`.
- **Verificado:** el feed arranca en la primera vela del **2026-04-01 09:00 ET** (índice 125.910 de 151.530) y cubre **61 sesiones** hasta el 2026-06-30. En el backtest controlado, esa ventana (W6) produjo **10 operaciones** con la config manual; el replay debe generar actividad similar, no necesariamente idéntica.
- **Extensión de `bars.csv`:** se hace con `server/market/massive_fetch.py` en una ruta nueva y con validación `python -m server.market.csv_data`. La ventana no puede entrar en el holdout (`2026-07-01 → 2026-10-30`): el descargador la rechaza. Extender hacia atrás (antes del 2025-01-10) es lo único permitido hoy sin protocolo de holdout.

---

## 1. Por qué el replay actual no genera señal

`CSVFeed` (en `server/market/feed.py`) hace una pasada única:

```python
async def next_tick(self) -> Tick | None:
    # Pasada única: repetir las mismas sesiones reabriría señales ya evaluadas...
    if self.index >= len(self.dataset):
        return None
    ...
```

El motor interpreta `None` como fin de datos y pasa a `stopped` (evento 729 del perfil vivo). `feed.loop_sessions` solo lo usa `SimulatedFeed`; en CSV no tiene efecto. La única palanca para volver a generar señal es **empezar más tarde** dentro del CSV con `feed.start_date`, o **traer datos nuevos**.

---

## 2. Perfil y DB nuevos

| Elemento | Valor |
|---|---|
| Directorio | `profiles/live_8765_replay/` |
| Config | `profiles/live_8765_replay/config.json` (SHA-256 `16648def57e1a3e77863e45d7b62f59ae6cbeb3cee4ba6d06041e31455c5d984`) |
| Cambio vs `profiles/live_8765/config.json` | **solo** `feed.start_date`: `""` → `"2026-04-01"` |
| DB | `profiles/live_8765_replay/yedbot.db` (126.976 B; esquema completo, 0 trades / 0 eventos / 0 kv) |
| Estrategia / riesgo | Idénticos al 8765: `10/300/210/24`, filtro 0,00, `tp_rr 3,0`, 1 % por trade, 3 trades/día, `paper`, `live_enabled=false` |
| Feed | `data/bars.csv` (mismo CSV, serie `adjusted`) |
| Puerto sugerido | **8767** (8765 ocupado por el proceso vivo; 8766 reservado por la tarea del otro perfil) |

### 2.1 Cómo arrancarlo

```powershell
$env:YED_PROFILE_DIR = "profiles/live_8765_replay"
$env:YED_OPEN = "0"
python -m uvicorn server.main:app --host 127.0.0.1 --port 8767 --log-level info
```

Para dejarlo desacoplado, el mismo patrón que el 8765: `Start-Process`/`Popen` con `DETACHED_PROCESS`, log en `logs/server_8767_replay.log` y PID en `logs/server_8767_replay.pid`. El motor **no arranca solo**: tras comprobar el feed con `/api/status`, hay que pulsar Iniciar o llamar a `/api/start`.

**No usar `--activate` de los descargadores**: escribe `data/config.json` y cambiaría la config viva. **No apuntar este perfil a `profiles/live_8765/yedbot.db`**: la DB tiene que ser la del directorio nuevo.

### 2.2 Qué se espera

- Inicio: primera vela del **2026-04-01** (09:00 ET); fin: **2026-06-30**.
- **61 sesiones**, **25.620 velas** restantes (índice inicial 125.910 de 151.530).
- A `replay_speed=8.0` (0,125 s por vela), unas **0,9 h** de reloj para agotarlo.
- Actividad esperada: la ventana W6 del backtest controlado tuvo **10 operaciones** y **−1.006,82 USD** con la manual. Es una ventana **negativa** en la muestra: sirve para comprobar que el replay vuelve a generar señal, **no** como test de rentabilidad.

---

## 3. Verificación realizada

| Comprobación | Resultado |
|---|---|
| Diff de configs | `feed.start_date: "" → "2026-04-01"`; ningún otro cambio |
| Tipo de feed | `CSVFeed`, índice inicial **125.910** |
| Primera vela | `2026-04-01` 09:00 ET, MNQ 24.615,75 |
| Última vela | `2026-06-30` |
| Sesiones desde el inicio | **61** (2026-04-01 → 2026-06-30) |
| DB nueva | 0 trades, 0 eventos, 0 kv; tablas `trades`, `events`, `kv`, `equity`, `backtests`, `backtest_*` |
| Perfil vivo | `profiles/live_8765/config.json` intacto (`9bf4f9c7…`), DB con **72 trades / 730 eventos**, mtime 2026-11-24 03:27:55 |
| Proceso 8765 | PID **16016** sigue escuchando; no se paró, reinició ni llamó a `/api/start` |

---

## 4. Extender `bars.csv` como experimento nuevo

### 4.1 Dataset actual

| Propiedad | Valor |
|---|---|
| Fichero | `data/bars.csv` (38.312.629 B) |
| Filas | 462.150 (3 símbolos × 154.050 velas) |
| Velas 1m alineadas | **151.530** |
| Rango | 2025-01-10 09:00 ET → 2026-06-30 15:59 ET |
| Sesiones | **362** |
| Serie | `adjusted`; 6 rolls, sesiones de roll excluidas |
| Columnas | `timestamp,symbol,open,high,low,close,volume,contract,expiry` |
| Símbolos | MNQ, NQ, ES |

### 4.2 Reglas que debe cumplir un CSV nuevo

Las impone `server/market/csv_data.py`:

- `timestamp` ISO-8601 **con offset** (o epoch en segundos) y alineado al minuto.
- Una fila por símbolo, contrato y timestamp; **sin duplicados**.
- MNQ, NQ y ES deben compartir **exactamente** los mismos timestamps.
- `contract` y `expiry` son necesarios para reconstruir rolls; `expiry` exige `contract`.
- La serie `adjusted` debe venir ya ajustada; las sesiones de roll se excluyen con `exclude_roll_sessions=true`.
- Faltantes: solo se admite rellenar **minutos aislados** con barra plana (el protocolo limita a 570 en total); dos minutos consecutivos ausentes abortan la descarga.
- El cargador **rechaza el holdout por defecto**: si el CSV contiene velas entre `2026-07-01` y `2026-10-30`, `CsvDataset.load` falla salvo `allow_holdout=True`, que no debe usarse fuera de un protocolo autorizado.

### 4.3 Descargar una ventana nueva

El pipeline real es `server/market/massive_fetch.py` (API de futuros de Massive; plan gratuito 5 peticiones/minuto). Descubre contratos trimestrales de MNQ/NQ/ES, descarga agregados de 1 minuto y escribe el CSV largo, un `_fills.csv` y un `_summary.json`.

```bash
export MASSIVE_API_KEY="..."   # nunca se escribe en el repo
python -m server.market.massive_fetch \
  --start 2024-07-01 --end 2025-01-09 \
  --out data/experiments/bars_2024H2.csv \
  --cache data/experiments/bars_2024H2.jsonl.gz
```

- `--end` **no puede ser ≥ 2026-07-01**: el comando aborta con el aviso del holdout sellado.
- `--request-interval 12` (por defecto) respeta el plan gratuito.
- Salidas: el CSV, `bars_2024H2_fills.csv` y `bars_2024H2_summary.json`.
- **No usar `--activate`**: escribe `data/config.json`. El CSV nuevo se activa solo en el perfil del experimento.
- Alternativa: `server/market/databento_fetch.py` (mismo contrato de salida y misma guarda de holdout); `fetch_data.py` es solo el lanzador de Massive.

**Ventanas posibles hoy:** hacia atrás (por ejemplo `2024-07-01 → 2025-01-09`) es lo limpio; hacia delante obliga a cruzar el holdout, así que queda prohibido hasta que exista un protocolo de holdout autorizado. El CSV actual ya cubre 2025-01-10 → 2026-06-30.

### 4.4 Validar antes de usarlo

```bash
python -m server.market.csv_data data/experiments/bars_2024H2.csv
```

Debe devolver `"ok": true` con el recuento de sesiones, contratos, rolls y rellenos planos. Después:

1. Crear un perfil nuevo (no reutilizar `live_8765_replay`): copiar `config.json`, cambiar `feed.csv_path` al CSV nuevo y `feed.start_date` a su primera sesión.
2. Crear una DB nueva en ese directorio (el `Store` la inicializa al arrancar).
3. Anotar el `dataset_id`/`file_sha256` que calcula el cargador y el hash del CSV.

### 4.5 Diseño del experimento

- **Pre-registro nuevo** (`docs/…lock.json`) con: dataset y hash, config y hash, ventanas, costes 0,62/lado + 1 tick y estrés 1,24/lado + 2 ticks, gates del protocolo (`dev_min_trades 80`, `PF ≥ 1,25`, `expectancy_r ≥ 0,1`, `DD ≤ 8 %`, top-5 ≤ 50 % del gross profit, bootstrap 80 %) y regla de parada.
- **No reutilizar H1**: `2026-07-01 → 2026-10-30` sigue sellado. Un experimento que lo incluya necesita autorización explícita y no es este.
- **Solapamiento:** si la ventana nueva pisa W1–W6, declararlo; no cuenta como confirmación independiente.
- **Costes y tamaño:** con 80+ operaciones mínimo; si la ventana nueva es corta, el experimento puede quedar `INCONCLUSO` por participación y no se baja el mínimo después de ver el resultado.

### 4.6 Recursos

- El CSV se carga **entero** en memoria al arrancar: 37 MB → ~30 s y ~390 MB de RSS. Un CSV del doble de tamaño duplica aproximadamente ambos.
- El replay es de una pasada y no paraleliza: 0,125 s por vela a 8×. 61 sesiones ≈ 50 min; 362 sesiones ≈ 5 h.
- La DB del perfil crece con los trades; al ser un directorio nuevo no compite con el 8765.

---

## 5. Integridad

| Comprobación | Valor |
|---|---|
| `profiles/live_8765/config.json` | SHA-256 `9bf4f9c7…e29479f`, mtime 2026-11-23 19:59:39, sin cambios |
| `profiles/live_8765/yedbot.db` | 319.488 B, mtime 2026-11-24 03:27:55, **72 trades / 730 eventos**; no se abrió en escritura |
| 8765 | PID **16016** escuchando en `127.0.0.1:8765`; sin parada, reinicio ni `/api/start` |
| Holdout | H1 `2026-07-01 → 2026-10-30` sin ejecutar; no se descargó ni se cargó |
| Commits | Ninguno (`HEAD 8b9cd6a`) |
| Cambios en el repo | Solo `profiles/live_8765_replay/` y este documento |

**Limitación:** el replay nuevo reproduce la misma muestra in-sample; no es forward ni una validación de rentabilidad. La extensión de `bars.csv` tampoco crea un holdout nuevo por sí sola: solo añade datos de desarrollo si la ventana no toca H1.
