# Watchdog del 8765 (PID + listener)

`scripts/watchdog_8765.ps1` vigila que el proceso del 8765 siga vivo y que el listener de `127.0.0.1:8765` siga siendo suyo. Si desaparece, avisa. **No reinicia nada, no llama a la API y no abre SQLite.**

> **Estado:** creado y probado contra un objetivo de laboratorio (puerto 8790), **no arrancado contra el 8765**. No hay proceso ni tarea programada activa. Para ponerlo en marcha hace falta el OK del operador.

## Qué comprueba

Cada `IntervalSeconds` (30 s por defecto):

1. Lee el PID de `logs/server_8765.pid`.
2. Comprueba que ese proceso existe (`Get-Process`).
3. Comprueba que el listener de `127.0.0.1:8765` pertenece exactamente a ese PID (`Get-NetTCPConnection`, con fallback a `netstat -ano`).

No hace peticiones HTTP: así no escribe líneas de acceso en `logs/server_8765_20261125.log`. Es una comprobación de sistema operativo, no de salud de la aplicación; si el proceso vive pero el motor está parado, el watchdog lo considera correcto (el motor se para solo al agotar el CSV, y eso no es una caída del servicio).

## Qué hace si falla

- A los **2 fallos consecutivos** (~1 minuto con el intervalo por defecto):
  - escribe `logs/WATCHDOG_8765_ALERT.txt` con fecha, PID esperado, motivo y qué revisar;
  - registra `[ERROR] ALERTA: …` en `logs/watchdog_8765.log`;
  - muestra un aviso de Windows (`MessageBox`) en la sesión interactiva.
- Mientras siga caído, repite el aviso cada `PopupEveryMinutes` (30 min) y deja el fichero de alerta.
- Al recuperarse: registra `[INFO] Recuperado…` y **borra** el fichero de alerta.
- Cada 15 minutos escribe un `Heartbeat` en el log para que se vea que el propio watchdog sigue vivo.

## Uso

```powershell
# Bucle continuo (foreground)
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\watchdog_8765.ps1"

# Comprobación única: 0 = sano, 2 = caído o no verificable
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\watchdog_8765.ps1" -Once
```

Parámetros:

| Parámetro | Defecto | Uso |
|---|---|---|
| `-PidFile` | `logs/server_8765.pid` | PID que debe existir y ser dueño del listener |
| `-Port` | `8765` | Puerto a vigilar |
| `-Address` | `127.0.0.1` | Dirección del listener |
| `-IntervalSeconds` | `30` | Cadencia |
| `-FailureThreshold` | `2` | Fallos consecutivos antes de alertar |
| `-PopupEveryMinutes` | `30` | Repetición del aviso mientras siga caído |
| `-LogPath` | `logs/watchdog_8765.log` | Log del watchdog |
| `-AlertFile` | `logs/WATCHDOG_8765_ALERT.txt` | Fichero de alerta |
| `-StopFile` | `logs/watchdog_8765.stop` | Crear el fichero para que termine |
| `-Once` | — | Una sola comprobación y salir |
| `-NoPopup` | — | Sin MessageBox (útil para pruebas o tareas) |

## Cómo ponerlo en marcha (cuando lo autorices)

Foreground:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\watchdog_8765.ps1"
```

Desacoplado, con log propio:

```powershell
Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -ArgumentList @(
  "-NoProfile","-ExecutionPolicy","Bypass","-File","scripts\watchdog_8765.ps1"
)
```

Tarea programada cada minuto, sin bucle (la opción más resistente a cierres de terminal; **no registrada**):

```powershell
# EJEMPLO, no ejecutado. Requiere el OK del operador.
$action  = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument '-NoProfile -ExecutionPolicy Bypass -File "C:\Users\yesco\Freebuff\projects\YEDBot\scripts\watchdog_8765.ps1" -Once'
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName "YEDBot-8765-Watchdog" -Action $action -Trigger $trigger
```

En modo `-Once`, el aviso visible es el MessageBox y el código de salida (`2`); el fichero de alerta queda escrito. Para no repetir el popup cada minuto, usar `-NoPopup` y revisar el fichero/exit code desde la tarea.

## Cómo se detiene

```powershell
# Bucle: crear el stop file
New-Item -ItemType File -Path "logs\watchdog_8765.stop" -Force

# Tarea programada (si algún día se registra)
Stop-ScheduledTask -TaskName "YEDBot-8765-Watchdog"
```

## Pruebas realizadas (sin tocar el 8765)

Se ejecutó el script contra el listener 8790 (PID 10672), no contra el 8765:

| Caso | Resultado |
|---|---|
| PID correcto y listener propio | exit **0**, sin alerta |
| PID muerto (`999999`) | exit **2**, alerta «el proceso 999999 ya no existe» |
| PID vivo pero listener ajeno (`4` vs 8790) | exit **2**, alerta «el listener pertenece al PID 10672» |
| Sin fichero de PID | exit **2**, alerta «no hay PID en …» |
| Bucle + stop file | arranca, detecta el stop y sale con **0** |

El 8765 no se tocó: su PID 16016 siguió escuchando y su log no cambió (580 B) durante las pruebas.

## Limitaciones

- **No reinicia** el 8765: solo avisa. Un reinicio automático necesita una decisión aparte.
- Si el watchdog corre en una sesión interactiva, un cierre de sesión lo mata; la variante de tarea programada evita eso.
- El PID file debe ser el que escribe el lanzador del 8765; si se queda obsoleto, el watchdog alerta aunque el puerto esté ocupado por otro proceso (es intencionado: no puede verificar la identidad).
- El MessageBox requiere sesión interactiva; en una sesión de servicio no se verá y el aviso queda en el fichero y el exit code.
- No sustituye a la monitorización de salud de la aplicación: un proceso vivo con el motor parado se considera sano.
