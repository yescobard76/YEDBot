# Operación del blindaje forward

> **Aviso de vigencia (2026-11-25):** este runbook describe el arnés forward
> P2/filtro del 2026-11-24, no el plan vigente original vs P1
> (`docs/FORWARD_ORIGINAL_VS_P1.md`). No lo uses para crear la ventana actual:
> `server.forward.init_window` todavía fija 5/200 y aplica el filtro por nombre
> de brazo. Se conserva como referencia histórica hasta que el arnés soporte
> los brazos del plan vigente.

Runbook para arrancar, recuperar y auditar el forward aislado de YEDBot sin
tocar el 8765, su base de datos ni el holdout.

## 0. Contrato operativo

- Puertos del forward: **8775** (control), **8776** (treatment) y **8778** (panel).
- El **8765** no se arranca, no se reinicia, no se para y su SQLite no se abre.
- El holdout H1 no se usa. Las fechas de sesión válidas empiezan el **2026-12-01**.
- El único proceso que se registra en el Programador es
  `python -m server.forward.autorun --window-id <ID> --ports 8775,8776 --panel`.
- El forward escribe en `data/forward`; el 8765 escribe en `data/yedbot.db` y
  `profiles/live_8765/yedbot.db`. Son dominios separados.
- El digest diario se escribe **fuera del proyecto** y se encadena con
  `prev_digest_sha256`; no se guardan credenciales en el repositorio.

### Estado comprobado al preparar este runbook

```text
8765 PID:                       15108
data/config.json SHA-256:       9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f
profiles/live_8765/config.json: 9bf4f9c7e1dce51bcb27e59f421d5adc28f342574f8ce2469d5250405e29479f
```

La ventana `2026-12-01_p1_filter025` **no se reutiliza**: sus snapshots esperan
el código `6e23d4c6…` y el código actual es `998fd6ce…`. Hay que crear una
ventana T0 nueva después de congelar código y tests.

## 1. Variables de la sesión

Ejecutar en PowerShell desde el proyecto:

```powershell
$ErrorActionPreference = "Stop"
$Project = (Get-Location).Path
if (-not (Test-Path -LiteralPath (Join-Path $Project "server\forward\autorun.py"))) {
    throw "Ejecuta este runbook desde la raíz de YEDBot: $Project"
}
$Python = (Get-Command python.exe -ErrorAction Stop).Source
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "No se encontró python.exe: $Python"
}
$WindowId = "FORWARD-2026-12-01-A"
if ($WindowId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
    throw "WindowId inválido: $WindowId"
}
$ForwardRoot = Join-Path $Project "data\forward"
$AuditRoot = Join-Path $env:USERPROFILE "YEDBot-audit"
$Task = "YEDBot-Forward-Autorun"
$DigestTask = "YEDBot-Forward-Digest"
Set-Location -LiteralPath $Project
```

`$WindowId` debe ser una ventana **nueva**. No reutilizar
`2026-12-01_p1_filter025`, `HARNESS-*` ni una ventana ya sellada.

## 2. Preflight, sin escribir nada

### 2.1 Suite completa

```powershell
& $Python -m pytest -q
```

No continuar si no termina en verde. En este repositorio la referencia es
`675 passed` (el warning de `starlette.testclient` es preexistente).

### 2.2 Huella del 8765 antes de operar

No se abre SQLite: solo se leen PID y hashes de configuración.

```powershell
function Get-8765Fingerprint {
    $conn = Get-NetTCPConnection -State Listen -LocalPort 8765 -ErrorAction Stop |
        Select-Object -First 1
    [pscustomobject]@{
        Pid              = [int]$conn.OwningProcess
        DataConfigHash   = (Get-FileHash -LiteralPath (Join-Path $Project "data\config.json") -Algorithm SHA256).Hash.ToLowerInvariant()
        LiveConfigHash   = (Get-FileHash -LiteralPath (Join-Path $Project "profiles\live_8765\config.json") -Algorithm SHA256).Hash.ToLowerInvariant()
    }
}

$Before8765 = Get-8765Fingerprint
$Before8765 | Format-List
```

Si el comando falla porque el 8765 no escucha, **no lo arranques**: el
procedimiento no es el adecuado para ese estado.

### 2.3 Puertos forward libres

```powershell
$BusyForward = @(8775, 8776, 8778) | Where-Object {
    Get-NetTCPConnection -State Listen -LocalPort $_ -ErrorAction SilentlyContinue
}
if ($BusyForward) { throw "Puertos forward ocupados: $($BusyForward -join ', ')" }
```

No usar `Stop-Process -Name python` ni matar por patrón. Si hay un proceso
forward previo, detenerlo con el comando ordenado de la sección 5.

### 2.4 La ventana nueva no existe

```powershell
if (Test-Path -LiteralPath (Join-Path $ForwardRoot $WindowId)) {
    throw "La ventana $WindowId ya existe; elige un ID nuevo"
}
```

## 3. Crear la ventana T0 y la captura

La ventana se crea **una sola vez**, después del último cambio en `server/` o
`tests/`. El snapshot incluye el hash del árbol de código; cualquier cambio
posterior invalida el arranque.

```powershell
& $Python -m server.forward.init_window `
    --window-id $WindowId `
    --kind forward `
    --arms control,treatment `
    --base-config profiles/p2_freq/config.json `
    --start-date 2026-12-01 `
    --sessions-target 378 `
    --note "Forward operativo P1; T0 congelado el 2026-11-24. Sin holdout."
```

Crear el esqueleto de captura (no ejecuta backtests ni descarga datos):

```powershell
& $Python -m server.forward.capture init --window-id $WindowId
```

Verificar que ambos brazos tienen config, snapshot y código alineados. Este
comando **no abre la DB**:

```powershell
$Verify = @'
import sys
from server.forward.identity import read_snapshot, verify_snapshot
from server.forward.paths import profile_dir
window = sys.argv[1]
problems = {
    arm: verify_snapshot(profile_dir(window, arm), read_snapshot(profile_dir(window, arm)))
    for arm in ('control', 'treatment')
}
print(problems)
sys.exit(1 if any(problems.values()) else 0)
'@
$verifyCode = 1
Push-Location $Project
try {
    & $Python -c $Verify $WindowId
    $verifyCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
if ($verifyCode -ne 0) { throw "T0 no verifica; no continues" }
```

Comprobar que el esqueleto de captura es válido:

```powershell
& $Python -m server.forward.capture verify --window-id $WindowId
```

No modificar `server/` ni `tests/` después de este punto. Los scripts y la
documentación no forman parte del hash de código, pero cualquier cambio en
`server` o `tests` sí.

## 4. ACL de mínimo privilegio

### 4.1 Por qué no se aplica RX total al forward vivo

Los brazos necesitan escribir:

- `arms/*/profile/yedbot.db` y sus `-wal`/`-shm`;
- `arms/*/ledger.jsonl`, `supervisor.jsonl`, `heartbeat.json`, `signals.jsonl`;
- `arms/*/sessions/**`, `capture/**` y `logs/**`.

Un `icacls` con solo RX para el operador **rompe el forward**. El modo
`Operational` deja al operador en `Modify` y al resto de usuarios locales en
`ReadOnly`:

```text
SYSTEM:                       Full
BUILTIN\Administrators:       Full
<cuenta que ejecuta el bot>:  Modify
BUILTIN\Users:                Read & execute
```

El dueño del árbol sigue pudiendo cambiar la ACL; es una barrera contra otros
usuarios y escrituras accidentales, no contra un administrador.

### 4.2 Aplicar la ACL operativa

Primero el plan, sin cambios:

```powershell
& (Join-Path $Project "scripts\forward_acl.ps1") `
    -Mode Operational -AuditRoot $AuditRoot
```

Aplicar (hace backup externo antes de tocar la ACL):

```powershell
& (Join-Path $Project "scripts\forward_acl.ps1") `
    -Mode Operational -Apply -AuditRoot $AuditRoot
```

Salida esperada (los SID pueden variar):

```text
... NT AUTHORITY\SYSTEM:(OI)(CI)(F)
... BUILTIN\Administrators:(OI)(CI)(F)
... <SID-del-operador>:(OI)(CI)(M)
... BUILTIN\Users:(OI)(CI)(RX)
```

El script crea una prueba de escritura en el root operativo y falla si el
operador no puede escribir. El backup queda en:

```text
$AuditRoot\acl\forward-acl-Operational-<fecha>.json
```

Restauración exacta si hay que revertir:

```powershell
# Usa la ruta exacta que imprimió el script; termina en .json.
$AclBackup = "$AuditRoot\acl\forward-acl-Operational-<fecha>.json"
& (Join-Path $Project "scripts\forward_acl.ps1") `
    -Restore $AclBackup -AuditRoot $AuditRoot
```

No usar `icacls /restore` directamente: el backup es JSON SDDL. `-Restore`
valida que la raíz sea el forward vivo o una copia bajo `$AuditRoot\sealed`, y
bloquea la restauración del forward vivo si hay puertos forward escuchando.

### 4.3 ACL ReadOnly para una copia sellada

Solo sobre una copia, nunca sobre `data/forward` vivo:

```powershell
$SealedWindow = Join-Path $AuditRoot "sealed\$WindowId"
if (Test-Path -LiteralPath $SealedWindow) {
    throw "Ya existe la copia sellada: $SealedWindow"
}
New-Item -ItemType Directory -Force -Path (Split-Path -Parent $SealedWindow) | Out-Null
Copy-Item -LiteralPath (Join-Path $ForwardRoot $WindowId) -Destination $SealedWindow -Recurse
& (Join-Path $Project "scripts\forward_acl.ps1") `
    -Mode ReadOnly -Root $SealedWindow -AuditRoot $AuditRoot -Apply
```

El script rechaza `ReadOnly` si detecta 8775, 8776 u 8778 escuchando o si el
destino no está bajo `$AuditRoot\sealed`; nunca debe apuntar a `data/forward`.

## 5. Tarea programada de arranque y recuperación

### 5.1 Registrar la tarea

```powershell
& (Join-Path $Project "scripts\setup_forward_task.ps1") -WindowId $WindowId
```

La tarea resultante debe tener exactamente esta acción:

```text
$Python
  -m server.forward.autorun --window-id <ID> --ports 8775,8776 --panel
```

El alta verifica la acción registrada y la elimina si contiene 8765, 8766,
`server.main` o `uvicorn`.

Comprobación:

```powershell
$t = Get-ScheduledTask -TaskName $Task
$t.Actions[0] | Format-List Execute,Arguments,WorkingDirectory
$t.Triggers | Format-Table
Get-ScheduledTaskInfo -TaskName $Task | Format-List
```

Debe incluir `server.forward.autorun`, `--ports 8775,8776`, `--panel`, el
`$WindowId` nuevo y **ninguna** referencia a 8765, 8766, `server.main` o
`uvicorn`.

La tarea tiene dos disparadores: **al iniciar sesión** y **diario a las 08:00**;
`MultipleInstances IgnoreNew`, `StartWhenAvailable`, `RestartCount 5` y
`RestartInterval 2 min`. El autorun y los supervisores añaden la recuperación
de los brazos.

> Si la sesión de Windows está cerrada, una tarea registrada sin credenciales
> guardadas puede no ejecutarse. Para operación 24/7 hay que registrarla con
> una cuenta de servicio; no guardar la contraseña en el repositorio.

### 5.2 Arrancar y verificar

```powershell
Start-ScheduledTask -TaskName $Task
Start-Sleep -Seconds 15

Invoke-RestMethod http://127.0.0.1:8775/api/health
Invoke-RestMethod http://127.0.0.1:8776/api/health
Invoke-RestMethod http://127.0.0.1:8778/api/forward/summary |
    ConvertTo-Json -Depth 8
```

Condiciones de aceptación:

- health 200 en 8775 y 8776;
- panel 8778 con `read_only=true`;
- `GET /api/forward/summary` muestra la ventana `$WindowId`;
- las sesiones aún pueden ser 0; la captura puede estar en
  `skeleton_awaiting_capture` hasta que llegue el feed;
- el 8765 sigue con el mismo PID y hashes (sección 8).

### 5.3 Recuperación ordenada

El orden importa: primero se pide al autorun que pare los brazos, luego se
detiene la tarea y se vuelve a arrancar.

```powershell
& $Python -m server.forward.autorun `
    --window-id $WindowId --ports 8775,8776 --stop

Stop-ScheduledTask -TaskName $Task
Start-ScheduledTask -TaskName $Task
Start-Sleep -Seconds 15
Invoke-RestMethod http://127.0.0.1:8775/api/health
Invoke-RestMethod http://127.0.0.1:8776/api/health
```

Verificar que la recuperación quedó registrada en el ledger del supervisor:

```powershell
Get-Content (Join-Path $ForwardRoot "$WindowId\arms\control\supervisor.jsonl") -Tail 12
Get-Content (Join-Path $ForwardRoot "$WindowId\arms\treatment\supervisor.jsonl") -Tail 12
```

Debe aparecer una secuencia con `ARM_EXIT`, `ARM_RESTART` y `ARM_SPAWN` cuando
se ha producido una caída real. No se debe reiniciar el 8765 para "recuperar"
el forward.

## 6. Cierre de sesión

El cierre se hace por brazo y por fecha ET, después del cierre de mercado:

```powershell
$SessionDate = (Get-Date).ToString("yyyy-MM-dd")
& $Python -m server.forward.session --window-id $WindowId --arm control --date $SessionDate
& $Python -m server.forward.session --window-id $WindowId --arm treatment --date $SessionDate
```

Si el config o el código cambiaron, el cierre queda `valid=false` y la ventana
`NO_VALIDA`; no se debe "arreglar" editando el snapshot o la sesión.

## 7. Digest diario fuera del proyecto

### 7.1 Generar el digest

```powershell
New-Item -ItemType Directory -Force -Path "$AuditRoot\forward-digests" | Out-Null
& $Python (Join-Path $Project "scripts\forward_digest.py") `
    --window-id $WindowId `
    --out-dir "$AuditRoot\forward-digests"
```

El script:

- escribe `digest-YYYY-MM-DD.json` fuera del proyecto;
- incluye hashes de todos los archivos de la ventana, estado del panel,
  PID y hashes de configuración del 8765;
- **no abre SQLite**;
- encadena cada digest con el anterior mediante `prev_digest_sha256`;
- se niega a escribir si `--out-dir` está dentro del proyecto.

Verificar la cadena:

```powershell
& $Python (Join-Path $Project "scripts\forward_digest.py") `
    --verify --out-dir "$AuditRoot\forward-digests"
```

### 7.2 Programar el digest diario

```powershell
& (Join-Path $Project "scripts\setup_forward_digest_task.ps1") `
    -WindowId $WindowId `
    -Project $Project -Python $Python -AuditRoot $AuditRoot
```

Comprobar la tarea:

```powershell
Get-ScheduledTask -TaskName $DigestTask | Format-List TaskName,State
Get-ScheduledTaskInfo -TaskName $DigestTask | Format-List NextRunTime,LastRunTime,LastTaskResult
```

Sin `-SshHost`/`-RemoteDir`, la tarea **solo genera** el digest local. Para
generarlo y publicarlo en la misma ejecución, añade los dos parámetros de la
sección 7.3. La tarea sigue siendo diaria a las **23:55**, con
`StartWhenAvailable`, `MultipleInstances IgnoreNew` y límite de 15 minutos.
No guarda credenciales de red.

### 7.3 Transporte real fuera de la máquina: scp sobre OpenSSH

Se usa **scp** con el cliente OpenSSH ya instalado en esta máquina. No se usa
`rclone` porque no está instalado. El transporte no guarda credenciales: usa
un alias SSH con clave y `known_hosts` en `%USERPROFILE%\.ssh`, fuera del
repositorio. El remoto debe ser POSIX y tener `sha256sum`, `mkdir`, `mv` y
`rm`.

#### Configuración única, fuera del repositorio

Crear la clave y autorizarla en el remoto (sustituye los placeholders):

```powershell
$SshDir = Join-Path $env:USERPROFILE ".ssh"
New-Item -ItemType Directory -Force -Path $SshDir | Out-Null
$Key = Join-Path $SshDir "yedbot_digest_ed25519"
ssh-keygen -t ed25519 -a 100 -f $Key -C "yedbot-digest"

# Alternativa si el remoto ya tiene sshd y prefieres ssh-copy-id:
# ssh-copy-id -i "$Key.pub" "<usuario>@<host>"
# Si no está disponible, copia la clave pública por el canal que ya uses:
Get-Content "$Key.pub" | ssh "<usuario>@<host>" "umask 077; mkdir -p ~/.ssh; cat >> ~/.ssh/authorized_keys"
```

Añadir este bloque a `%USERPROFILE%\.ssh\config` (también fuera del repo):

```text
Host yedbot-digest
    HostName <host>
    User <usuario>
    IdentityFile ~/.ssh/yedbot_digest_ed25519
    IdentitiesOnly yes
    BatchMode yes
    StrictHostKeyChecking yes
```

Verificar la huella del host por un canal independiente y añadir su clave a
`known_hosts`. No desactivar la comprobación de host para que la tarea
desatendida funcione:

```powershell
ssh-keyscan -H "<host>" | Out-File -Append -Encoding ascii (Join-Path $env:USERPROFILE ".ssh\known_hosts")
ssh yedbot-digest "sha256sum --version"
```

El alias sustituye a usuario, host, contraseña y ruta de clave privada:
**no se pasan credenciales a la tarea**. La clave privada y el `config` de SSH
quedan fuera del proyecto; `.gitignore` bloquea `.ssh/`, `*.pem`, `*.key`,
`*.ppk` y `rclone.conf` por si alguien intenta copiarlos.

#### Prueba manual y verificación

```powershell
$DigestDir = Join-Path $AuditRoot "forward-digests"
& $Python (Join-Path $Project "scripts\forward_digest_publish.py") `
    --ssh-host yedbot-digest `
    --remote-dir /srv/yedbot-audit/forward-digests `
    --out-dir "$DigestDir" --dry-run

# Sin --dry-run: sube el último digest y verifica el hash remoto.
& $Python (Join-Path $Project "scripts\forward_digest_publish.py") `
    --ssh-host yedbot-digest `
    --remote-dir /srv/yedbot-audit/forward-digests `
    --out-dir "$DigestDir"
```

`--dry-run` valida la cadena y calcula el SHA-256 local sin contactar con el
remoto. La ejecución real hace `mkdir`, sube a un temporal, compara el hash
del temporal, lo promueve con `mv` y vuelve a comparar el archivo final. Si
el destino ya existe con otro contenido, **aborta sin sobrescribirlo**. La
salida y el recibo `transport-YYYY-MM-DD.json` (en `$DigestDir`) incluyen
`local_sha256`, `remote_sha256` y `matches=true`; no contienen credenciales.

Para comprobar un envío ya hecho sin escribir nada:

```powershell
& $Python (Join-Path $Project "scripts\forward_digest_publish.py") `
    --ssh-host yedbot-digest `
    --remote-dir /srv/yedbot-audit/forward-digests `
    --out-dir "$DigestDir" --verify-only
```

#### Programar generación y envío juntos

```powershell
& (Join-Path $Project "scripts\setup_forward_digest_task.ps1") `
    -WindowId $WindowId `
    -Project $Project -Python $Python -AuditRoot $AuditRoot `
    -SshHost "yedbot-digest" `
    -RemoteDir "/srv/yedbot-audit/forward-digests"
```

La acción de la tarea pasa a `scripts\forward_digest_daily.py`, que genera el
digest y solo después llama al publicador. Si la generación o la verificación
remota fallan, la tarea termina con código distinto de cero y no se considera
un envío válido. Sin los dos parámetros, la tarea sigue generando solo el
archivo externo local.

Si no hay transporte configurado, el digest queda en
`$AuditRoot\forward-digests`: externo al proyecto, pero no a la máquina. Eso
no cumple el requisito de continuidad; no lo llames copia fuera de máquina.

## 8. Comprobación final del 8765

Repetir la huella y comparar **PID y ambos hashes**:

```powershell
$After8765 = Get-8765Fingerprint
if ($After8765.Pid -ne $Before8765.Pid -or
    $After8765.DataConfigHash -ne $Before8765.DataConfigHash -or
    $After8765.LiveConfigHash -ne $Before8765.LiveConfigHash) {
    throw "El 8765 cambió durante la operación. Detener el forward e investigar; no reiniciar el 8765."
}
$After8765 | Format-List
```

No se ejecuta ningún `SELECT`, `VACUUM`, backup ni apertura de
`data/yedbot.db`. La comprobación es de proceso y archivos de configuración.

## 9. Rollback

```powershell
# 1. Parar el forward de forma ordenada.
& $Python -m server.forward.autorun --window-id $WindowId --ports 8775,8776 --stop

# 2. Bajar las tareas.
Stop-ScheduledTask -TaskName $Task -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $Task -Confirm:$false
Stop-ScheduledTask -TaskName $DigestTask -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName $DigestTask -Confirm:$false

# 3. Restaurar la ACL desde el backup externo (JSON SDDL).
# Sustituye <fecha> por el timestamp que imprimió el script.
$AclBackup = "$AuditRoot\acl\forward-acl-Operational-<fecha>.json"
& (Join-Path $Project "scripts\forward_acl.ps1") `
    -Restore $AclBackup -AuditRoot $AuditRoot
```

El rollback no toca el 8765 ni su SQLite.

## 10. Checklist de aceptación

- [ ] Suite completa en verde antes de crear el T0.
- [ ] `$WindowId` es nuevo; la ventana vieja no se reutiliza.
- [ ] `verify_snapshot` vacío para control y treatment.
- [ ] `capture verify` devuelve `ok=true` o el estado de esqueleto esperado.
- [ ] ACL operativa aplicada y prueba de escritura del operador superada.
- [ ] Tarea `YEDBot-Forward-Autorun` apunta solo a 8775/8776/8778.
- [ ] Health 200 en ambos brazos y panel read-only.
- [ ] Recuperación ordenada probada y registrada en `supervisor.jsonl`.
- [ ] Digest generado fuera del proyecto y cadena verificada.
- [ ] Transporte scp probado con `--dry-run` y `--verify-only`; recibo con
      `matches=true`.
- [ ] Clave privada, `config` SSH y `known_hosts` fuera del repositorio; nada
      de credenciales en la tarea ni en el árbol de trabajo.
- [ ] Digest diario registrado y con próximo disparo.
- [ ] 8765 con el mismo PID y los mismos hashes antes/después.
- [ ] Sin commit ni push de artefactos de datos.
