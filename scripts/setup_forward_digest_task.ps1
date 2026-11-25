[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
    [string]$WindowId,
    [string]$Project = "",
    [string]$Python = "",
    [string]$AuditRoot = "",
    [string]$TaskName = "YEDBot-Forward-Digest",
    [ValidatePattern("^(?:[01]\d|2[0-3]):[0-5]\d$")]
    [string]$At = "23:55",
    [string]$SshHost = "",
    [string]$RemoteDir = ""
)

# El digest se escribe fuera del proyecto. Con -SshHost/-RemoteDir, la misma
# tarea genera y publica por scp, usando un alias SSH configurado fuera del
# repositorio. La tarea no guarda claves, contraseñas ni tokens.
$ErrorActionPreference = "Stop"
if ([string]::IsNullOrWhiteSpace($Project)) {
    $Project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
}
else {
    $Project = (Resolve-Path -LiteralPath $Project).Path
}
if ([string]::IsNullOrWhiteSpace($Python)) {
    $Python = (Get-Command python.exe -ErrorAction Stop).Source
}
if ([string]::IsNullOrWhiteSpace($AuditRoot)) {
    $AuditRoot = Join-Path $env:USERPROFILE "YEDBot-audit"
}
$AuditRoot = [IO.Path]::GetFullPath($AuditRoot)
$projectFull = [IO.Path]::GetFullPath($Project)
$separator = [IO.Path]::DirectorySeparatorChar
if ($AuditRoot.Equals($projectFull, [StringComparison]::OrdinalIgnoreCase) -or
    $AuditRoot.StartsWith($projectFull + $separator, [StringComparison]::OrdinalIgnoreCase)) {
    throw "AuditRoot debe estar fuera del proyecto: $AuditRoot"
}

$hasTransport = -not [string]::IsNullOrWhiteSpace($SshHost) -or
    -not [string]::IsNullOrWhiteSpace($RemoteDir)
if ($hasTransport) {
    if ([string]::IsNullOrWhiteSpace($SshHost) -or
        [string]::IsNullOrWhiteSpace($RemoteDir)) {
        throw "SshHost y RemoteDir deben pasarse juntos"
    }
    if ($SshHost -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$') {
        throw "SshHost debe ser un alias SSH simple: $SshHost"
    }
    if ($RemoteDir -notmatch '^/[A-Za-z0-9._/-]+$' -or
        $RemoteDir -match '//' -or
        $RemoteDir -match '(^|/)\.\.?(/|$)') {
        throw "RemoteDir debe ser una ruta POSIX absoluta sin '..': $RemoteDir"
    }
    foreach ($tool in @("ssh", "scp")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "No se encontró $tool en PATH; el transporte scp no está disponible"
        }
    }
    $dailyScript = Join-Path $Project "scripts\forward_digest_daily.py"
    if (-not (Test-Path -LiteralPath $dailyScript -PathType Leaf)) {
        throw "No existe $dailyScript"
    }
}

$digestScript = Join-Path $Project "scripts\forward_digest.py"
$digestDir = Join-Path $AuditRoot "forward-digests"
$window = Join-Path $Project "data\forward\$WindowId"
if (-not (Test-Path -LiteralPath $digestScript -PathType Leaf)) {
    throw "No existe $digestScript"
}
if (-not (Test-Path -LiteralPath $window -PathType Container)) {
    throw "No existe la ventana forward: $window"
}
if (-not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "No existe python.exe: $Python"
}

New-Item -ItemType Directory -Force -Path $digestDir | Out-Null

# Las tres rutas van entre comillas porque Project/AuditRoot pueden contener
# espacios. WindowId está restringido por ValidatePattern.
if ($hasTransport) {
    $dailyScript = Join-Path $Project "scripts\forward_digest_daily.py"
    $arguments = '"{0}" --window-id "{1}" --out-dir "{2}" --ssh-host "{3}" --remote-dir "{4}"' -f $dailyScript, $WindowId, $digestDir, $SshHost, $RemoteDir
    $transportDescription = "Genera y publica por scp en ${SshHost}:${RemoteDir}, verificando SHA-256 remoto."
}
else {
    $arguments = '"{0}" --window-id "{1}" --out-dir "{2}"' -f $digestScript, $WindowId, $digestDir
    $transportDescription = "Solo digest local; sin transporte remoto configurado."
}
$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument $arguments `
    -WorkingDirectory $Project

$trigger = New-ScheduledTaskTrigger -Daily -At $At
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Digest diario encadenado del forward ${WindowId}; escribe en $digestDir. $transportDescription No toca el 8765 ni su SQLite." `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$info = Get-ScheduledTaskInfo -TaskName $TaskName
[pscustomobject]@{
    TaskName = $task.TaskName
    State = $task.State
    Execute = $task.Actions[0].Execute
    Arguments = $task.Actions[0].Arguments
    WorkingDirectory = $task.Actions[0].WorkingDirectory
    NextRunTime = $info.NextRunTime
    LastRunTime = $info.LastRunTime
    LastTaskResult = $info.LastTaskResult
    DigestDir = $digestDir
    Transport = if ($hasTransport) { "scp" } else { "none" }
    SshHost = if ($hasTransport) { $SshHost } else { "" }
    RemoteDir = if ($hasTransport) { $RemoteDir } else { "" }
} | Format-List
