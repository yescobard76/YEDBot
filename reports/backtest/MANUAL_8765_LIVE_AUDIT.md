# Auditoría de la instancia viva 8765 y comparación con el baseline original

**Corte de la muestra:** 2026-11-24T03:40:03Z (2026-11-23 21:40, America/Chicago)
**Ámbito:** proceso que escucha en `127.0.0.1:8765`, su configuración efectiva, su propia DB y bitácora de eventos, y el baseline canónico `5/200/150/12` ya ejecutado en W1–W6.
**Naturaleza:** solo lectura. No se arrancó, reinició ni paró el bot; no se modificó configuración, DB, perfiles, CSV ni holdout; no se ejecutó ningún backtest nuevo.
**Veredicto corto:** con **6 trades** cerrados, la instancia viva muestra **+981,68 USD netos**, **PF 3,06** y **DD cerrado 239,68 USD**. En la misma ventana, el baseline canónico ya ejecutado habría hecho **2 trades** y perdido **619,42 USD**. La diferencia es real en esta muestra, pero **6 trades y 14 días no permiten concluir que la configuración viva sea superior hacia adelante**. El 8765 sigue corriendo con el mismo PID y el mismo `StartTime`.

---

## 1. Identidad y configuración efectiva del proceso vivo

### 1.1 Proceso, perfil y rutas

Lectura del sistema y de la API realizada durante la auditoría:

| Elemento | Valor observado |
|---|---|
| Listener | `127.0.0.1:8765` |
| PID | **15108** |
| Comando | `C:\Users\yesco\AppData\Local\Programs\Python\Python312\python.exe -u run.py` |
| Proceso padre | PID `9668` (`bash.exe`) |
| Lanzamiento | `YED_PORT=8765 YED_PROFILE_DIR="$PWD/profiles/live_8765" YED_OPEN=0 python -u run.py` |
| Inicio del proceso | **2026-11-24T02:12:49.101Z** |
| Uptime en el corte | **5.238,2 s** (1 h 27 min 18 s) |
| Estado HTTP | `running` |
| Modo | `paper` |
| Sesión de replay en el cierre | `2025-01-30` (corte; después avanzó a `2025-02-05`) |
| Posición abierta | ninguna; `/api/orders` devuelve 0 órdenes y `position: null` |
| Config activa | `profiles/live_8765/config.json` |
| DB activa | `profiles/live_8765/yedbot.db` |
| Feed | CSV histórico `data/bars.csv`, serie **adjusted**, 151.530 velas 1m, 362 sesiones, rango 2025-01-10 → 2026-06-30 |
| Motor | `running`; replay a **8,0 velas 1m/s**, `loop_sessions=true` |

`run.py` toma `YED_PORT` y `server/config.py` resuelve `PROFILE_DIR` desde `YED_PROFILE_DIR`; de ahí salen `CONFIG_PATH=profiles/live_8765/config.json` y `DB_PATH=profiles/live_8765/yedbot.db`. La API `GET /api/config` devuelve **exactamente** los mismos `settings` que el archivo (`api_equals_file=true`). La DB consultada en solo lectura es la que contiene los trades que la API reporta.

### 1.2 Hashes de identidad

| Objeto | SHA-256 |
|---|---|
| Archivo vivo `profiles/live_8765/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `data/config.json` | `9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f` |
| `config_sha256` canónico de la config viva | `d3cff10d7842af4ab29c571c1fb8554841dfc128b9454df55eb53933286dcd10` |
| Baseline canónico en memoria `5/200/150/12` | `87b8b9f18dbce9e4739112cf734850fe75de7e82e7548425d246027d2234e708` |
| Archivo base `profiles/backtest_real/config.json` | `8fd7cfa28fa0e0eb98a6ac283e7426ccc74fa6dc76845723fca4d335e7b4df4f` |

`profiles/backtest_real/config.json` contiene actualmente `210/24`, no la frecuencia original. El baseline canónico se fija en memoria con `ORIGINAL_FREQUENCY_PATCH` de `reports/backtest/_manual_common.py`, tal como documenta `reports/backtest/README.md`; **no se modificó ese archivo**. El `config_sha256` excluye `feed`, `mode` y `live`; por eso no coincide con el hash de bytes.

### 1.3 Configuración viva frente al baseline original

Referencia original: `docs/protocolo_backtest.lock.json` y `ORIGINAL_FREQUENCY_PATCH`: **5 contratos, SL 200 ticks, validez 150 min, tolerancia de retest 12 ticks**.

| Parámetro | Vivo 8765 | Original | Diferencia |
|---|---:|---:|---|
| `instrument` / referencia / comparación | MNQ / NQ / ES | MNQ / NQ / ES | igual |
| `mode` / `live.live_enabled` | paper / false | paper / false | igual |
| ORB | 09:00–10:00 ET, ancho máx. 1,2 % | 09:00–10:00 ET, 1,2 % | igual |
| SMT | activado; pivote 5; ventana 60; tolerancia 8 ticks; validez 120 min | igual | igual |
| `strategy.setup_validity_minutes` | **210** | **150** | **+60** |
| `strategy.retest_tolerance_ticks` | **24** | **12** | **+12** |
| `strategy.entry_reference` | `or_mid` | `or_mid` | igual |
| `strategy.tp_rr` | 3,0 | 3,0 | igual |
| `risk.min_stop_or_ratio` | **0,00** | 0,00 | igual: sin filtro |
| `risk.risk_per_trade_pct` | 1,0 % | 1,0 % | igual |
| `risk.initial_capital` | 25.000 USD | 25.000 USD | igual |
| `risk.max_contracts` | **10** | **5** | **×2** |
| `risk.max_sl_ticks` | **300** | **200** | **+100 ticks** |
| `risk.max_trades_per_day` | 3 | 3 | igual |
| `risk.max_concurrent_positions` | 1 | 1 | igual |
| `risk.max_daily_loss_pct` | 3,0 % | 3,0 % | igual |
| `risk.trade_window_start/end` | 09:00 / 15:30 ET | 09:00 / 15:30 ET | igual |
| `risk.close_at_session_end` / cierre | true / 15:55 ET | true / 15:55 ET | igual |
| `execution.tick_size` / `tick_value` | 0,25 / 0,50 USD | 0,25 / 0,50 USD | igual |
| `execution.point_value` | 2,00 USD | 2,00 USD | igual |
| `execution.commission_per_contract_side` | 0,62 USD | 0,62 USD | igual |
| `execution.slippage_ticks` | 1 | 1 | igual |
| `execution.fill_model` | `next_open` | `next_open` | igual |
| `feed.provider` / `csv_path` | csv / `data/bars.csv` | csv / `data/real/bars_mnq_nq_es_1m.csv` | feed distinto |
| `feed.series_mode` / rolls | adjusted / excluye rolls | raw / excluye rolls | feed distinto |
| `feed.loop_sessions` | true | true | igual |
| `feed.replay_speed` | **8,0** | 4,5 | operativo, no edge |
| `live.broker` | none | none | igual |

**Diff exacto de la configuración de trading (5 rutas):**

```text
risk.max_contracts:                 10    -> 5
risk.max_sl_ticks:                 300    -> 200
strategy.setup_validity_minutes:   210    -> 150
strategy.retest_tolerance_ticks:    24    -> 12
feed.replay_speed:                 8.0    -> 4.5   (operativo)
```

Los cambios manuales identificables son **10 contratos, SL 300, validez 210 y retest 24**. No hay un override oculto en la API: el perfil cargado y la API coinciden. El `data/config.json` es una copia idéntica del perfil vivo, pero el proceso usa explícitamente `profiles/live_8765` por el `YED_PROFILE_DIR` del lanzador.

### 1.4 Qué no se puede determinar desde fuera del proceso

- No hay log de consola de esta instancia en un archivo actual; `data/server.log` está vacío y los logs de `logs/` corresponden a otras instancias. La bitácora viva disponible es la tabla `events` de `profiles/live_8765/yedbot.db` (50 filas al cierre; 49 en el corte).
- No se inspecciona la memoria interna del proceso ni el entorno heredado completo. Se conoce el comando del padre y la configuración resuelta; no se puede demostrar que no exista una variable de entorno no visible que no cambie el resultado, aunque `CONFIG_PATH` y la DB observados son coherentes con el lanzador.
- No hay broker ni ejecución real: `live.live_enabled=false` y `broker=none`. No hay estado de órdenes externo que auditar.
- No se puede reconstruir un contrafactual del baseline sobre **las mismas señales** del vivo sin ejecutar un backtest; solo se puede usar el artefacto ya ejecutado del baseline en las mismas fechas. Esa limitación se explicita en la sección 3.

---

## 2. Muestra real de la instancia viva

### 2.1 Corte y fuentes

- **Corte:** 2026-11-24T03:40:03Z.
- **Fuente:** `profiles/live_8765/yedbot.db`, abierta con SQLite en modo `mode=ro`; tabla `trades` (6 filas), tabla `equity` (6 filas), tabla `events` (49 filas en el corte).
- **Sin backtest:** estas 6 operaciones son las que el proceso paper/replay ya cerró. El replay continuó después del corte (sesión 2025-01-30); las operaciones posteriores no se incluyen.
- **Ventana de muestra:** primera entrada **2025-01-13 11:28 ET**; última salida **2025-01-27 11:28 ET**. Son **14 días naturales** y **6 sesiones con operaciones**. La muestra no es forward: es un replay histórico de 2025, in-sample, a 8×.
- **Duración media por trade:** 9.560 s (2 h 39 min 20 s).
- **Observaciones:** 6 trades cerrados; 0 posiciones abiertas al corte; 0 órdenes pendientes.

### 2.2 Métricas de la muestra viva

| Métrica | Valor |
|---|---:|
| PnL neto | **+981,68 USD** |
| Trades cerrados | **6** |
| Ganadores / perdedores | 4 / 2 |
| Win rate | **66,67 %** |
| Expectancy por trade | **+163,61 USD** |
| Profit factor | **3,06** |
| Gross profit / gross loss | +1.457,56 / −475,88 USD |
| Comisiones | 22,32 USD |
| Media ganadora / perdedora | +364,39 / −237,94 USD |
| R total / R medio | +6,46 / +1,08 |
| Max drawdown cerrado | **239,68 USD (0,945 %)** |
| Max drawdown intradía abierto | 451,50 USD (1,806 %) |
| Mejor / peor trade | +432,52 / −239,68 USD |
| Equity final | 25.981,68 USD |
| Sharpe / Sortino | 9,07 / 18,91 (no interpretables con n=6) |

### 2.3 Trades que componen la muestra

| # | Entrada ET | Salida ET | Lado | Qty | Stop ticks | PnL USD | R | Salida |
|---:|---|---|---|---:|---:|---:|---:|---|
| 1 | 2025-01-13 11:28 | 2025-01-13 15:56 | long | 1 | 291,0 | +374,76 | +2,98 | session_close |
| 2 | 2025-01-15 11:46 | 2025-01-15 11:52 | long | 7 | 68,5 | −239,68 | −1,02 | stop_loss |
| 3 | 2025-01-16 11:06 | 2025-01-16 15:56 | short | 1 | 267,0 | +317,76 | +2,37 | session_close |
| 4 | 2025-01-23 11:13 | 2025-01-23 15:56 | long | 2 | 195,0 | +432,52 | +2,24 | session_close |
| 5 | 2025-01-24 11:59 | 2025-01-24 13:45 | short | 2 | 177,0 | +332,52 | +0,90 | take_profit |
| 6 | 2025-01-27 11:25 | 2025-01-27 11:28 | long | 5 | 89,8 | −236,20 | −1,01 | stop_loss |

Las horas son las de los timestamps de la DB en America/New_York; no se normalizan ni se estiman.

### 2.4 Lectura correcta de la muestra

- **Sí se puede afirmar:** en estas 6 operaciones, el proceso vivo ganó 981,68 USD netos, con 4 ganadoras y 2 perdedoras, PF 3,06 y DD cerrado 239,68 USD.
- **No se puede afirmar:** que la configuración sea rentable hacia adelante, que el PF 3,06 sea estable, ni que la expectancy de 163,61 USD/trade sea extrapolable. Con 6 observaciones no hay potencia estadística; el Sharpe de 9,07 es un artefacto de muestra minúscula, no una señal.
- La muestra es un replay de **enero de 2025**, no el régimen de mercado de noviembre de 2026. No es forward y no usa el holdout.
- Los dos trades con stop >200 ticks (291 y 267) fueron **ganadores** en esta muestra. Es una observación importante que **contradice** la mejora histórica de bajar el SL a 200; se trata abajo como conflicto, no como prueba.

---

## 3. Comparación contra el baseline original en la misma ventana

### 3.1 Método

No se ejecutó un backtest. Se usó el artefacto ya existente `reports/backtest/p2_w1_w6_confirm.json`, variante `original` (baseline canónico 5/200/150/12, W1, 54 sesiones), y se filtraron sus trades por la **misma ventana de calendario del vivo**: 2025-01-13 → 2025-01-27. El filtro se aplicó sobre `entry_ts` y `exit_ts`; no se simularon señales nuevas.

### 3.2 Resultado del baseline en la ventana

El baseline habría hecho **2 trades**, ambos perdedores por stop:

| Baseline | Fecha | Lado | Qty | PnL | R | Salida |
|---|---|---:|---:|---:|---:|---|
| `2025-01-15-long-1736953200` | 2025-01-15 | long | 5 | −168,70 | −1,01 | stop_loss |
| `2025-01-27-long-1737990900` | 2025-01-27 | long | 3 | −450,72 | −1,00 | stop_loss |

| Perfil | Trades | PnL neto | Win rate | PF | Expectancy | Max DD | DD % | R total |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| **Vivo 8765** | **6** | **+981,68** | **66,67 %** | **3,06** | **+163,61** | **239,68** | 0,945 % | +6,46 |
| **Baseline canónico** | **2** | **−619,42** | 0,00 % | 0,00 | −309,71 | 619,42 | 2,478 % | −2,01 |
| **Diferencia (vivo − baseline)** | **+4 trades** | **+1.601,10** | +66,67 pp | +3,06 | +473,32 | **−379,74** | −1,533 pp | +8,47 |

### 3.3 Qué hizo distinto el baseline y qué no se puede atribuir

- El baseline **no tomó** 4 de las 6 operaciones del vivo (2025-01-13, 2025-01-16, 2025-01-23 y 2025-01-24). En la ventana solo coincidió en las señales del 15 y del 27 de enero.
- En las dos señales compartidas: baseline **−619,42 USD** frente a vivo **−475,88 USD**; el vivo perdió **143,54 USD menos**, pero con tamaño distinto (baseline 5 y 3 contratos; vivo 7 y 5).
- La diferencia total de **+1.601,10 USD** no es un efecto causal limpio de “la configuración”: el vivo generó más señales y las sizeó distinto. El artefacto del baseline no expone el motivo de rechazo de cada señal no tomada; no se atribuye a `max_sl_ticks` ni a la frecuencia sin probarlo.
- El baseline completo de W1 (54 sesiones) hizo 8 trades, **+364,82 USD**, PF 1,35 y DD 619,42 USD. Esa cifra **no** es la comparación de la misma ventana y no se usa para el delta anterior; se incluye solo como contexto.
- No hay un contrafactual del baseline sobre las **mismas 6 señales** del vivo. Para obtenerlo habría que ejecutar un backtest, prohibido en este encargo. Por eso la conclusión es descriptiva, no causal.

### 3.4 Veredicto de la comparación

En la ventana 2025-01-13 → 2025-01-27, el vivo **ganó 981,68 USD** y el baseline ya ejecutado **perdió 619,42 USD**; el vivo también tuvo menor DD cerrado. La magnitud es **+1.601,10 USD** a favor del vivo, pero con **6 vs 2 trades**. Es evidencia de esta muestra, no una demostración de superioridad.

---

## 4. Propuestas de mejora ordenadas por impacto esperado en rentabilidad

No se implementa ninguna. La prioridad combina el delta histórico ya medido, la evidencia de la muestra viva y el riesgo de sobreajuste. Ninguna propuesta está validada forward.

### 4.1 Contexto histórico ya ejecutado (W1–W6, in-sample)

| Perfil | Configuración | Trades | Neto | PF | DD | DD % |
|---|---|---:|---:|---:|---:|---:|
| Original | 5/200/150/12 | 38 | +661,44 | 1,13 | 1.967,82 | 7,14 % |
| Vivo manual | 10/300/210/24 | 72 | +2.022,94 | 1,22 | 2.891,66 | 9,79 % |
| P2 | 10/200/210/24 | 46 | +2.471,78 | 1,39 | 2.304,46 | 7,84 % |
| P1 filtro 0,25 | 5/200/210/24 + 0,25 | 17 | +4.202,20 | 4,25 | 946,38 | 3,36 % |

Fuentes: `reports/backtest/_manual_w1_w6_analysis.log`, `reports/backtest/p2_w1_w6_confirm.json` y `reports/backtest/_manual_filter025_w1_w6.json`. Son datos in-sample; no se extrapolan.

### 4.2 Tabla priorizada

| # | Cambio concreto | Impacto esperado | Evidencia | Confianza | Riesgo / coste | Cómo medir |
|---:|---|---|---|---|---|---|
| **1** | `risk.min_stop_or_ratio: 0,00 → 0,25` | En la muestra viva habría rechazado los **2 perdedores** (ratios 0,108 y 0,094) y dejado +1.457,56 USD en 4 trades. Histórico: **+2.209,94 USD** y **−1.001,44 DD** frente a P1 control. | Histórico `filter025_max5`; aplicación directa a los 6 trades (no backtest). | Media: fuerte en muestra, pero **17 trades**, 4/6 trimestres, gates INCONCLUSO y cero aceptadas en 2026. Alto riesgo de sobreajuste. | Más rechazos y posible pérdida de regímenes; no promocionar sin forward. | P1 control vs P1 filtro, mismo forward, único diff; mínimo 60 trades baseline, 24 aceptadas, 5/6 trimestres; medir neto, PF, DD y Q3. |
| **2** | `risk.max_sl_ticks: 300 → 200`, manteniendo `max_contracts=10` | Histórico P2 vs vivo: **+448,84 USD** y **−587,20 DD**; PF 1,39 vs 1,22. En la muestra viva habría eliminado los dos trades con stop 291/267, que sumaron **+692,52 USD**: conflicto explícito. | `_manual_w1_w6_analysis.log` (46 vs 72 trades); muestra viva de 6. | Media: histórica amplia, pero la muestra corta la contradice. | Rechaza ganadores de stop ancho; el resultado forward puede ser peor. | P2 forward 10/200/210/24 vs vivo, mínimo 60 trades; comparar neto, PF, DD y distribución por stop. |
| **3** | Paquete `min_stop_or_ratio=0,25` **y** `max_sl_ticks=200`, manteniendo 10 contratos | Histórico `filter025_max10`: **+4.202,20 USD**, PF 4,25, DD 946,38; frente al vivo +2.179,26 USD y −1.945,28 DD. En la muestra viva dejaría 2 trades ganadores (+765,04) al filtrar los dos ganadores de stop ancho y los dos perdedores de ratio bajo. | `_manual_filter025_w1_w6.json`; aplicación ilustrativa a 6 trades. | Baja: misma muestra de 17 trades, ahora más restrictiva; alto riesgo de selección. | Puede quedarse sin operar en regímenes como 2026; no es una mejora robusta todavía. | Forward del paquete con pre-registro; exigir 60 trades, 24 aceptadas, 5/6 bloques y Q3 ≤80 %; no cambiar el umbral durante la prueba. |
| **4** | Reprecio de costes de estrés: comisión **0,62/lado** ya vigente y slippage **2 ticks** en la medición; no cambiar la estrategia | No aumenta el bruto; evita sobreestimar el neto. El PF observado puede bajar. | `FILTER025_PROFITABILITY.md`, `stress_costs.json`; comisiones vivas 22,32 USD en 6 trades. | Alta para la necesidad de medir; no es una mejora de rentabilidad por sí sola. | Puede convertir un PF alto en mediocre; es deseable para decidir. | Repreciar los mismos fills con coste exacto; evaluar P6/E3; no promocionar sin P6. |

### 4.3 Lo que **no** se propone como mejora de rentabilidad

- **Subir contratos por encima de 10:** no hay evidencia; el histórico muestra que 10 vs 5 añade +479,52 USD de neto pero +356,64 USD de DD. Es apalancamiento, no edge.
- **Bajar a 5 contratos para “mejorar rentabilidad”:** reduce el neto absoluto en la muestra histórica; solo tendría sentido como control de DD, no como prioridad de rentabilidad.
- **Revertir la frecuencia 210/24 al original 150/12:** el histórico muestra que 210/24 añadió +1.330,82 USD y −20,00 DD frente al original; no hay motivo para revertir.
- **Relajar el filtro 0,25 o probar 0,20/0,30:** sería una nueva búsqueda in-sample; los gates ya están INCONCLUSO y el filtro no tiene forward.
- **Cobertura de regímenes o diversificación:** el problema existe (cero aceptadas en 2026, concentración Q3 85,28 %), pero no hay un parámetro concreto con evidencia suficiente; no se inventa una propuesta.

### 4.4 Orden de implantación si se autoriza un forward

1. Medir **filtro 0,25** y **SL 200** por separado y como paquete, sin tocar la instancia viva.
2. Usar los perfiles P1 congelados para el filtro; para SL200 con 10 contratos hace falta un perfil P2 forward, que hoy no existe.
3. Exigir muestra forward mínima y pre-registro; no usar los 6 trades actuales como validación.
4. Mantener la configuración viva actual hasta que el forward demuestre mejora; no cambiar el 8765 en caliente.

---

## 5. Verificación de no intervención y reproducibilidad

### 5.1 Proceso antes / después

| Comprobación | Antes (corte) | Después (cierre) |
|---|---|---|
| PID | 15108 | **15108** |
| `StartTime` UTC | 2026-11-24T02:12:49.101Z | **2026-11-24T02:12:49.101Z** |
| Uptime | 5.238,2 s | **5.525,5 s** |
| Estado | running | **running** |
| Config SHA-256 | 9bf4f9c7… | **9bf4f9c7…** |
| Posición / órdenes | 0 / 0 | **0 / 0** |

Comprobación final: **2026-11-24T03:44:54Z**. El PID y el `StartTime` siguen siendo exactamente los mismos; el uptime pasó de 5.238,2 s a 5.525,5 s, como corresponde a un proceso que no se reinició. La sesión de replay había avanzado a `2025-02-05`, seguía `running`, sin posición y con la misma configuración (SHA-256 `9bf4f9c7…`). La DB cambia porque el bot sigue escribiendo trades; la auditoría la abrió en `mode=ro` y no ejecutó `INSERT`, `UPDATE`, `DELETE` ni migraciones.

### 5.2 Restricciones cumplidas

- **Sin backtests:** no se ejecutó `_simulate`, `prepare_dataset` ni ningún runner de backtest. El baseline se filtró de un JSON ya existente.
- **Sin cambios de configuración:** hashes de `profiles/live_8765/config.json` y `data/config.json` sin cambios; `profiles/backtest_real/config.json` no se tocó.
- **Sin cambios de DB:** solo lecturas SQLite en modo `ro`; la DB viva siguió creciendo por el propio bot.
- **Holdout:** no se accedió a H1 `2026-07-01 → 2026-10-30` ni se ejecutó el forward.
- **Único archivo escrito por esta auditoría:** este informe.

### 5.3 Reproducir la evidencia viva

```bash
# Proceso y listener
netstat -ano | findstr :8765
powershell -NoProfile -Command 'Get-Process -Id 15108 | Select-Object Id,StartTime,Responding'

# Configuración efectiva y estado
curl http://127.0.0.1:8765/api/config
curl http://127.0.0.1:8765/api/status

# Trades: el endpoint usa 30d por defecto y el replay es de 2025; para ver todos:
curl 'http://127.0.0.1:8765/api/trades?period=all&limit=100'
curl 'http://127.0.0.1:8765/api/stats?period=all'

# DB en solo lectura (no usar el Store, que migra/escribe)
python - <<'PY'
import sqlite3
from pathlib import Path
p = Path('profiles/live_8765/yedbot.db').resolve()
con = sqlite3.connect(f'file:{p.as_posix()}?mode=ro', uri=True)
print(con.execute('select count(*) from trades').fetchone())
print(con.execute('select id, exit_ts, pnl, r_multiple, exit_reason from trades order by exit_ts').fetchall())
con.close()
PY
```

### 5.4 Fuentes

| Fuente | Uso |
|---|---|
| `profiles/live_8765/config.json` | Configuración cargada por el proceso |
| `server/config.py`, `run.py` | Resolución de perfil/DB y variables de lanzamiento |
| `docs/protocolo_backtest.lock.json` | Baseline canónico 5/200/150/12 |
| `reports/backtest/_manual_common.py` | `ORIGINAL_FREQUENCY_PATCH` 150/12 |
| `reports/backtest/p2_w1_w6_confirm.json` | Trades del baseline W1 usados para la misma ventana |
| `reports/backtest/_manual_w1_w6_analysis.log` | Histórico vivo/P2/P1 |
| `reports/backtest/_manual_filter025_w1_w6.json` | Filtro 0,25; 17 trades |
| `profiles/live_8765/yedbot.db` | Trades, equity y eventos de la instancia viva |

---

## 6. Conclusión operativa

La instancia viva del 8765 usa el perfil manual **10/300/210/24**, con feed CSV adjusted a 8×, en paper y sin broker. Su muestra actual es **6 trades, +981,68 USD, PF 3,06, DD cerrado 239,68 USD**; el baseline canónico ya ejecutado habría hecho **2 trades y −619,42 USD** en la misma ventana. El vivo va por delante en esta muestra, pero la muestra es demasiado pequeña y es un replay histórico in-sample: **no autoriza a declarar superioridad ni a cambiar la configuración viva**.

La propuesta con mayor impacto histórico es el filtro `min_stop_or_ratio=0,25`; la más robusta en número de operaciones es `max_sl_ticks=200`, aunque la muestra viva de 6 trades la contradice. El paquete de ambas es la variante con mayor resultado in-sample, pero también la de mayor riesgo de sobreajuste. Todas deben probarse en forward, no aplicarse en caliente. La configuración viva se mantiene intacta.
