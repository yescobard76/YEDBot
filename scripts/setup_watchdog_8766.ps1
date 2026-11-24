$watchdog = Join-Path $PSScriptRoot "watchdog_8766.ps1"
if (-not (Test-Path $watchdog)) {
    throw "No existe $watchdog"
}

$action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument ('-NoProfile -ExecutionPolicy Bypass -File "' + $watchdog + '"')

$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "YEDBot-8766-Watchdog" `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Watchdog YEDBot 8766: GET /api/health; si falla, relanza YEDBot-8766. Detener: Stop-ScheduledTask -TaskName 'YEDBot-8766-Watchdog'." `
    -Force | Out-Null

Get-ScheduledTask -TaskName "YEDBot-8766-Watchdog" | Select-Object TaskName, State
(Get-ScheduledTask -TaskName "YEDBot-8766-Watchdog").Settings |
    Select-Object ExecutionTimeLimit, MultipleInstances, RestartCount, RestartInterval, DisallowStartIfOnBatteries, StopIfGoingOnBatteries |
    Format-List
