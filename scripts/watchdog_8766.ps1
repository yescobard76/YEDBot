[CmdletBinding()]
param(
    [string]$HealthUrl = "http://127.0.0.1:8766/api/health",
    [string]$TaskName = "YEDBot-8766",
    [int]$IntervalSeconds = 15,
    [int]$FailureThreshold = 3,
    [int]$StartupGraceSeconds = 120,
    [int]$StartTimeoutSeconds = 180,
    [int]$MaxRestartsPerHour = 5,
    [string]$LogPath = "",
    [string]$StopFile = "",
    [switch]$Once,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $PSScriptRoot "..\logs\watchdog_8766.log"
}
if ([string]::IsNullOrWhiteSpace($StopFile)) {
    $StopFile = Join-Path $PSScriptRoot "..\logs\watchdog_8766.stop"
}
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$StopFile = [System.IO.Path]::GetFullPath($StopFile)

function Write-WatchdogLog {
    param([string]$Level, [string]$Message)
    $line = "{0} [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    try {
        $dir = Split-Path -Parent $LogPath
        if ($dir -and -not (Test-Path $dir)) {
            New-Item -ItemType Directory -Path $dir -Force | Out-Null
        }
        Add-Content -Path $LogPath -Value $line -Encoding UTF8
    } catch { }
    Write-Host $line
}

function Initialize-WatchdogLog {
    $dir = Split-Path -Parent $LogPath
    if ($dir -and -not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir -Force | Out-Null
    }
    if ((Test-Path $LogPath) -and ((Get-Item $LogPath).Length -gt 5MB)) {
        Move-Item -Path $LogPath -Destination "$LogPath.1" -Force
    }
}

function Test-Health {
    try {
        $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 5 -ErrorAction Stop
        if ([int]$resp.StatusCode -ne 200) { return $false }
        $payload = $resp.Content | ConvertFrom-Json
        return ($payload.status -eq "ok")
    } catch {
        return $false
    }
}

function Get-ServerTask {
    try { return Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop } catch { return $null }
}

function Get-ServerTaskInfo {
    try { return Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop } catch { return $null }
}

function Wait-Health {
    param([int]$TimeoutSeconds)
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Path $StopFile) {
            Write-WatchdogLog "INFO" "Stop file detectado durante la espera; watchdog termina"
            return $false
        }
        Start-Sleep -Seconds 3
        if (Test-Health) { return $true }
    }
    return $false
}

function Restart-Server {
    param([string]$Reason)

    if (Test-Path $StopFile) {
        Write-WatchdogLog "INFO" "Stop file presente; no se relanza $TaskName"
        return $false
    }

    if ($DryRun) {
        Write-WatchdogLog "WARN" "DRY-RUN: relanzaria $TaskName (motivo: $Reason)"
        return $true
    }

    $task = Get-ServerTask
    if (-not $task) {
        Write-WatchdogLog "ERROR" "No existe la tarea $TaskName; no se puede relanzar"
        return $false
    }
    if ($task.State -eq "Disabled") {
        Write-WatchdogLog "ERROR" "La tarea $TaskName esta deshabilitada; habilitala manualmente"
        return $false
    }

    if ($task.State -eq "Running" -or $task.State -eq "Queued") {
        $info = Get-ServerTaskInfo
        if ($info -and $info.LastRunTime -and ((Get-Date) - $info.LastRunTime).TotalSeconds -lt $StartupGraceSeconds) {
            Write-WatchdogLog "INFO" "La tarea $TaskName esta en arranque (desde $($info.LastRunTime)); esperando gracia"
            return $false
        }

        $now = Get-Date
        $script:RestartTimes = @($script:RestartTimes | Where-Object { ($now - $_).TotalHours -lt 1 })
        if ($script:RestartTimes.Count -ge $MaxRestartsPerHour) {
            Write-WatchdogLog "ERROR" "Limite de $MaxRestartsPerHour reinicios/hora alcanzado; esperando 10 min"
            Start-Sleep -Seconds 600
            return $false
        }
        $script:RestartTimes += $now

        Write-WatchdogLog "WARN" "Deteniendo la tarea $TaskName para relanzarla"
        try {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
        } catch {
            Write-WatchdogLog "ERROR" "No se pudo detener ${TaskName}: $($_.Exception.Message)"
            return $false
        }

        $stopped = $false
        for ($i = 0; $i -lt 20; $i++) {
            Start-Sleep -Seconds 1
            $current = Get-ServerTask
            if (-not $current -or ($current.State -ne "Running" -and $current.State -ne "Queued")) {
                $stopped = $true
                break
            }
        }
        if (-not $stopped) {
            Write-WatchdogLog "ERROR" "La tarea $TaskName no termino de detenerse"
            return $false
        }
    } else {
        $now = Get-Date
        $script:RestartTimes = @($script:RestartTimes | Where-Object { ($now - $_).TotalHours -lt 1 })
        if ($script:RestartTimes.Count -ge $MaxRestartsPerHour) {
            Write-WatchdogLog "ERROR" "Limite de $MaxRestartsPerHour reinicios/hora alcanzado; esperando 10 min"
            Start-Sleep -Seconds 600
            return $false
        }
        $script:RestartTimes += $now
    }

    Write-WatchdogLog "INFO" "Iniciando la tarea $TaskName"
    try {
        Start-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    } catch {
        Write-WatchdogLog "ERROR" "No se pudo iniciar ${TaskName}: $($_.Exception.Message)"
        return $false
    }

    if (Wait-Health -TimeoutSeconds $StartTimeoutSeconds) {
        Write-WatchdogLog "INFO" "Health OK tras relanzar $TaskName"
        return $true
    }
    Write-WatchdogLog "ERROR" "Health sigue fallando tras $StartTimeoutSeconds s de espera"
    return $false
}

$mutex = New-Object -TypeName System.Threading.Mutex -ArgumentList $false, "Local\YEDBot-8766-Watchdog"
$hasMutex = $false
try {
    try {
        $hasMutex = $mutex.WaitOne(0)
    } catch [System.Threading.AbandonedMutexException] {
        $hasMutex = $true
    }
} catch { }
if (-not $hasMutex) {
    Write-Host "Otra instancia del watchdog ya esta en ejecucion."
    exit 0
}

$exitCode = 0
try {
    Initialize-WatchdogLog
    $script:RestartTimes = @()
    Write-WatchdogLog "INFO" "Watchdog iniciado (PID $PID, health $HealthUrl, tarea $TaskName, intervalo ${IntervalSeconds}s)"

    if (Test-Path $StopFile) {
        Write-WatchdogLog "INFO" "Stop file presente al arrancar; watchdog termina"
        $exitCode = 0
    }
    elseif ($Once) {
        if (Test-Health) {
            Write-WatchdogLog "INFO" "Health OK"
            $exitCode = 0
        } else {
            Write-WatchdogLog "WARN" "Health fallo en comprobacion unica"
            $ok = Restart-Server -Reason "comprobacion unica"
            if ($ok) { $exitCode = 0 } else { $exitCode = 1 }
        }
    }
    else {
        $initialHealthy = Test-Health
        if ($initialHealthy) {
            Write-WatchdogLog "INFO" "Health OK; vigilando $TaskName"
        } else {
            Write-WatchdogLog "WARN" "Health no responde al arrancar; iniciando conteo"
        }
        $consecutiveFailures = 0
        if (-not $initialHealthy) { $consecutiveFailures = 1 }
        $wasHealthy = $initialHealthy
        $lastHeartbeat = Get-Date

        while ($true) {
            if (Test-Path $StopFile) {
                Write-WatchdogLog "INFO" "Stop file detectado; watchdog termina"
                break
            }

            if (Test-Health) {
                if (-not $wasHealthy) {
                    Write-WatchdogLog "INFO" "Health recuperado; servidor operativo"
                }
                $wasHealthy = $true
                $consecutiveFailures = 0
                if (((Get-Date) - $lastHeartbeat).TotalMinutes -ge 15) {
                    Write-WatchdogLog "INFO" "Heartbeat: health OK"
                    $lastHeartbeat = Get-Date
                }
            } else {
                $wasHealthy = $false
                $consecutiveFailures++
                Write-WatchdogLog "WARN" "Health fallo ($consecutiveFailures/$FailureThreshold)"
                if ($consecutiveFailures -ge $FailureThreshold) {
                    $ok = Restart-Server -Reason "$consecutiveFailures fallos consecutivos"
                    if ($ok) {
                        $consecutiveFailures = 0
                        $wasHealthy = $true
                        $lastHeartbeat = Get-Date
                    } else {
                        Start-Sleep -Seconds 30
                    }
                }
            }
            Start-Sleep -Seconds $IntervalSeconds
        }
    }
} catch {
    Write-WatchdogLog "ERROR" "Excepcion no controlada: $($_.Exception.Message)"
    $exitCode = 1
} finally {
    if ($hasMutex) {
        try { $mutex.ReleaseMutex() } catch { }
    }
    $mutex.Dispose()
}
exit $exitCode
