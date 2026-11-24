param(
    [string]$WindowId = "2026-12-01_p1_filter025"
)

# Alta real en el Programador de tareas: una sola tarea lanza el autorun, que a
# su vez arranca los dos brazos aislados (8775/8776) y el panel (8778).
# No referencia al 8765 ni al 8766.
# Baja: Unregister-ScheduledTask -TaskName "YEDBot-Forward-Autorun" -Confirm:$false

$root = "C:\Users\yesco\Freebuff\projects\YEDBot"
$python = "C:\Users\yesco\AppData\Local\Programs\Python\Python312\python.exe"
$arguments = "-m server.forward.autorun --window-id $WindowId --ports 8775,8776 --panel"

$action = New-ScheduledTaskAction `
    -Execute $python `
    -Argument $arguments `
    -WorkingDirectory $root

$triggers = @(
    (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"),
    (New-ScheduledTaskTrigger -Daily -At "08:00")
)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "YEDBot-Forward-Autorun" `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description "Forward ${WindowId}: brazos aislados 8775/8776 + panel 8778 (solo lectura)" `
    -Force | Out-Null

$task = Get-ScheduledTask -TaskName "YEDBot-Forward-Autorun"
$info = Get-ScheduledTaskInfo -TaskName "YEDBot-Forward-Autorun"
[pscustomobject]@{
    TaskName = $task.TaskName
    State = $task.State
    Execute = $task.Actions[0].Execute
    Arguments = $task.Actions[0].Arguments
    WorkingDirectory = $task.Actions[0].WorkingDirectory
    Triggers = ($task.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ", "
    NextRunTime = $info.NextRunTime
    LastRunTime = $info.LastRunTime
    LastTaskResult = $info.LastTaskResult
} | Format-List
