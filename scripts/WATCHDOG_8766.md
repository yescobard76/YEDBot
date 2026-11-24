# Watchdog de la instancia 8766

`watchdog_8766.ps1` comprueba `GET http://127.0.0.1:8766/api/health` cada 15 segundos.
Si fallan 3 comprobaciones seguidas, detiene y arranca la tarea `YEDBot-8766`.

No llama a endpoints del motor ni abre la base de datos: solo consulta `/api/health` y usa Task Scheduler. El arranque del servidor, como cualquier arranque, registra su evento habitual en la DB; el watchdog no escribe ni resetea nada.

## Tarea

- Nombre: `YEDBot-8766-Watchdog`
- Se inicia al iniciar sesión.
- Log: `logs/watchdog_8766.log`
- La tarea del servidor que vigila: `YEDBot-8766`

Para volver a registrar la tarea (desde la raíz del proyecto):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\setup_watchdog_8766.ps1"
```

## Cómo se detiene

Todos los comandos se ejecutan desde la raíz del proyecto.

Parar solo el watchdog (el servidor sigue funcionando):

```powershell
Stop-ScheduledTask -TaskName "YEDBot-8766-Watchdog"
```

Evitar que vuelva a arrancar al iniciar sesión:

```powershell
Disable-ScheduledTask -TaskName "YEDBot-8766-Watchdog"
```

Parada temporal desde el propio script: crear el fichero `logs/watchdog_8766.stop`. El watchdog lo detecta en la siguiente comprobación y termina. Borrarlo para permitir que vuelva a arrancar.

Volver a arrancarlo:

```powershell
Remove-Item "logs/watchdog_8766.stop" -ErrorAction SilentlyContinue
Enable-ScheduledTask -TaskName "YEDBot-8766-Watchdog"
Start-ScheduledTask -TaskName "YEDBot-8766-Watchdog"
```

Parar también el servidor:

```powershell
Stop-ScheduledTask -TaskName "YEDBot-8766"
```

Eliminar el watchdog:

```powershell
Unregister-ScheduledTask -TaskName "YEDBot-8766-Watchdog" -Confirm:$false
```

## Importante

- Si vas a parar el servidor para mantenimiento, para antes el watchdog o crea `logs/watchdog_8766.stop`; si no, lo relanzará.
- La tarea es interactiva: al cerrar sesión, Windows la detiene igual que la del servidor. Para que sobreviva a logoff/reboot hace falta un servicio o una tarea configurada para ejecutarse aunque el usuario no haya iniciado sesión.
- El watchdog solo consulta `/api/health` y usa Task Scheduler. No llama a `/api/bot/*`, no ejecuta resets y no abre SQLite. Si relanza el servidor, este arranca como siempre y el motor queda en `stopped` hasta que se pulse Iniciar.
