[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern("^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")]
    [string]$WindowId,
    [string]$TaskName = "YEDBot-Forward-Autorun"
)

# Alta real en el Programador de tareas: una sola tarea lanza el autorun, que a
# su vez arranca los dos brazos aislados (8775/8776) y el panel (8778).
# No referencia al 8765 ni al 8766.
# Baja: Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false

$ErrorActionPreference = "Stop"
$Project = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$Python = (Get-Command python.exe -ErrorAction Stop).Source
if (-not $Python -or -not (Test-Path -LiteralPath $Python -PathType Leaf)) {
    throw "No se encontró python.exe ejecutable: $Python"
}
$window = Join-Path $Project "data\forward\$WindowId"
if (-not (Test-Path -LiteralPath $window -PathType Container)) {
    throw "No existe la ventana forward: $window. Créala antes de registrar la tarea."
}
$busy = @(8775, 8776, 8778) | Where-Object {
    Get-NetTCPConnection -State Listen -LocalPort $_ -ErrorAction SilentlyContinue
}
if (@($busy).Count -gt 0) {
    throw "Puertos forward ocupados: $($busy -join ', '). No se registra la tarea."
}

# `sys.argv[1]` evita interpolar el ID en código Python. El ValidatePattern del
# parámetro ya impide separadores, comillas y traversal.
$check = @'
import sys
from server.forward.identity import read_snapshot, verify_snapshot
from server.forward.paths import profile_dir
window = sys.argv[1]
problems = {
    arm: verify_snapshot(profile_dir(window, arm), read_snapshot(profile_dir(window, arm)))
    for arm in ("control", "treatment")
}
print(problems)
sys.exit(1 if any(problems.values()) else 0)
'@
Push-Location $Project
try {
    & $Python -c $check $WindowId
    $verifyCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
if ($verifyCode -ne 0) {
    throw "La ventana $WindowId no verifica config/código contra su snapshot T0. No se registra la tarea."
}

$arguments = "-m server.forward.autorun --window-id $WindowId --ports 8775,8776 --panel"
if ($arguments -match "(?i)8765|8766|server\.main|uvicorn") {
    throw "La acción del forward no está acotada: $arguments"
}
$action = New-ScheduledTaskAction `
    -Execute $Python `
    -Argument $arguments `
    -WorkingDirectory $Project

$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"),
    (New-ScheduledTaskTrigger -Daily -At "08:00")
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -RestartCount 5 `
    -RestartInterval (New-TimeSpan -Minutes 2) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description "Forward ${WindowId}: brazos aislados 8775/8776 + panel 8778 (solo lectura)" `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName $TaskName
$taskArguments = [string]$task.Actions[0].Arguments
if ($taskArguments -ne $arguments) {
    throw "La acción registrada no coincide con la esperada. Revisa la tarea $TaskName antes de arrancarla."
}
$info = Get-ScheduledTaskInfo -TaskName $TaskName
[pscustomobject]@{
    TaskName = $task.TaskName
    State = $task.State
    Execute = $task.Actions[0].Execute
    Arguments = $taskArguments
    WorkingDirectory = $task.Actions[0].WorkingDirectory
    Triggers = ($task.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ", "
    NextRunTime = $info.NextRunTime
    LastRunTime = $info.LastRunTime
    LastTaskResult = $info.LastTaskResult
} | Format-List
