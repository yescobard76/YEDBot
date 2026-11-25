[CmdletBinding()]
param(
    [string]$PidFile = "",
    [int]$Port = 8765,
    [string]$Address = "127.0.0.1",
    [int]$IntervalSeconds = 30,
    [int]$FailureThreshold = 2,
    [int]$PopupEveryMinutes = 30,
    [string]$LogPath = "",
    [string]$AlertFile = "",
    [string]$StopFile = "",
    [switch]$Once,
    [switch]$NoPopup
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

if ([string]::IsNullOrWhiteSpace($PidFile)) {
    $PidFile = Join-Path $PSScriptRoot "..\logs\server_8765.pid"
}
if ([string]::IsNullOrWhiteSpace($LogPath)) {
    $LogPath = Join-Path $PSScriptRoot "..\logs\watchdog_8765.log"
}
if ([string]::IsNullOrWhiteSpace($AlertFile)) {
    $AlertFile = Join-Path $PSScriptRoot "..\logs\WATCHDOG_8765_ALERT.txt"
}
if ([string]::IsNullOrWhiteSpace($StopFile)) {
    $StopFile = Join-Path $PSScriptRoot "..\logs\watchdog_8765.stop"
}
$PidFile = [System.IO.Path]::GetFullPath($PidFile)
$LogPath = [System.IO.Path]::GetFullPath($LogPath)
$AlertFile = [System.IO.Path]::GetFullPath($AlertFile)
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

function Get-ExpectedPid {
    if (-not (Test-Path $PidFile)) { return $null }
    $raw = (Get-Content -Path $PidFile -ErrorAction SilentlyContinue | Select-Object -First 1)
    if ([string]::IsNullOrWhiteSpace($raw)) { return $null }
    $value = 0
    if ([int]::TryParse($raw.Trim(), [ref]$value) -and $value -gt 0) { return $value }
    return $null
}

function Get-ListenerPid {
    # Solo tabla TCP; no se hace ninguna peticion HTTP para no tocar el log del servidor.
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        $match = $conns |
            Where-Object {
                $_.LocalAddress -eq $Address -or
                $_.LocalAddress -eq "0.0.0.0" -or
                $_.LocalAddress -eq "::"
            } |
            Select-Object -First 1
        if ($match) { return [int]$match.OwningProcess }
        return $null
    } catch {
        try {
            foreach ($line in (netstat -ano -p TCP)) {
                if ($line -match "LISTENING" -and $line -match "[:.]$Port\s+\S+\s+LISTENING\s+(\d+)") {
                    return [int]$Matches[1]
                }
            }
        } catch { }
        return $null
    }
}

function Test-Instance {
    param([Nullable[int]]$ExpectedPid)
    $process = $null
    if ($null -ne $ExpectedPid) {
        $process = Get-Process -Id $ExpectedPid -ErrorAction SilentlyContinue
    }
    $listenerPid = Get-ListenerPid

    if ($null -eq $ExpectedPid) {
        return [pscustomobject]@{
            Healthy = $false
            ExpectedPid = $null
            ProcessAlive = $false
            ListenerPid = $listenerPid
            Reason = "no hay PID en $PidFile"
        }
    }
    if ($null -eq $process) {
        return [pscustomobject]@{
            Healthy = $false
            ExpectedPid = $ExpectedPid
            ProcessAlive = $false
            ListenerPid = $listenerPid
            Reason = "el proceso $ExpectedPid ya no existe"
        }
    }
    if ($listenerPid -ne $ExpectedPid) {
        $detail = if ($null -eq $listenerPid) { "nadie escucha en ${Address}:$Port" } else { "el listener pertenece al PID $listenerPid" }
        return [pscustomobject]@{
            Healthy = $false
            ExpectedPid = $ExpectedPid
            ProcessAlive = $true
            ListenerPid = $listenerPid
            Reason = $detail
        }
    }
    return [pscustomobject]@{
        Healthy = $true
        ExpectedPid = $ExpectedPid
        ProcessAlive = $true
        ListenerPid = $listenerPid
        Reason = "PID y listener correctos"
    }
}

function Write-AlertFile {
    param([string]$Reason)
    $text = @(
        "ALERTA - 8765 sin servicio",
        "Fecha: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')",
        "PID esperado: $(if ($null -eq (Get-ExpectedPid)) { 'desconocido' } else { Get-ExpectedPid })",
        "Motivo: $Reason",
        "Listener esperado: ${Address}:$Port",
        "",
        "El proceso del 8765 desaparecio o perdio el puerto.",
        "Comprueba 'logs/server_8765_20261125.log' y 'logs/server_8765.pid'.",
        "Para relanzarlo: usar el lanzador del perfil profiles/live_8765.",
        "Este watchdog NO reinicia nada por si solo."
    ) -join [Environment]::NewLine
    try {
        Set-Content -Path $AlertFile -Value $text -Encoding UTF8
    } catch { }
}

function Remove-AlertFile {
    if (Test-Path $AlertFile) {
        try { Remove-Item -Path $AlertFile -Force -ErrorAction Stop } catch { }
    }
}

function Show-AlertPopup {
    param([string]$Reason)
    if ($NoPopup) { return }
    $message = "El 8765 no esta disponible: $Reason.`n`nVer $AlertFile y logs/server_8765_20261125.log."
    $escaped = $message.Replace("'", "''")
    try {
        Start-Process -FilePath "powershell.exe" -WindowStyle Hidden -ArgumentList @(
            "-NoProfile",
            "-Command",
            "Add-Type -AssemblyName System.Windows.Forms; [System.Windows.Forms.MessageBox]::Show('$escaped','YEDBot 8765 - watchdog','OK','Warning')"
        ) | Out-Null
    } catch { }
}

function Invoke-Alert {
    param([string]$Reason)
    Write-WatchdogLog "ERROR" "ALERTA: $Reason"
    Write-AlertFile -Reason $Reason
    Show-AlertPopup -Reason $Reason
}

$mutex = New-Object -TypeName System.Threading.Mutex -ArgumentList $false, "Local\YEDBot-8765-Watchdog"
$hasMutex = $false
try {
    try { $hasMutex = $mutex.WaitOne(0) } catch [System.Threading.AbandonedMutexException] { $hasMutex = $true }
} catch { }
if (-not $hasMutex) {
    Write-Host "Otra instancia del watchdog 8765 ya esta en ejecucion."
    exit 0
}

$exitCode = 0
try {
    Initialize-WatchdogLog

    if (Test-Path $StopFile) {
        Write-WatchdogLog "INFO" "Stop file presente; watchdog termina"
        $exitCode = 0
    }
    elseif ($Once) {
        $state = Test-Instance -ExpectedPid (Get-ExpectedPid)
        if ($state.Healthy) {
            Write-WatchdogLog "INFO" "OK: PID $($state.ExpectedPid), listener $Address`:$Port"
            Remove-AlertFile
            $exitCode = 0
        } else {
            Write-WatchdogLog "WARN" "Comprobacion unica: $($state.Reason)"
            Invoke-Alert -Reason $state.Reason
            $exitCode = 2
        }
    }
    else {
        Write-WatchdogLog "INFO" "Watchdog iniciado (PID $PID, fichero $PidFile, listener $Address`:$Port, intervalo ${IntervalSeconds}s, umbral $FailureThreshold)"
        $consecutiveFailures = 0
        $wasHealthy = $null
        $lastAlert = [datetime]::MinValue
        $lastHeartbeat = Get-Date

        while ($true) {
            if (Test-Path $StopFile) {
                Write-WatchdogLog "INFO" "Stop file detectado; watchdog termina"
                break
            }

            $state = Test-Instance -ExpectedPid (Get-ExpectedPid)
            if ($state.Healthy) {
                if ($wasHealthy -eq $false) {
                    Write-WatchdogLog "INFO" "Recuperado: PID $($state.ExpectedPid) escuchando en $Address`:$Port"
                    Remove-AlertFile
                }
                $wasHealthy = $true
                $consecutiveFailures = 0
                if (((Get-Date) - $lastHeartbeat).TotalMinutes -ge 15) {
                    Write-WatchdogLog "INFO" "Heartbeat: PID $($state.ExpectedPid) y listener OK"
                    $lastHeartbeat = Get-Date
                }
            } else {
                $consecutiveFailures++
                if ($wasHealthy -ne $false) {
                    Write-WatchdogLog "WARN" "Fallo ($consecutiveFailures/$FailureThreshold): $($state.Reason)"
                } elseif (($consecutiveFailures % 10) -eq 0) {
                    Write-WatchdogLog "WARN" "Sigue caido ($consecutiveFailures comprobaciones): $($state.Reason)"
                }
                $wasHealthy = $false
                $alertDue = ((Get-Date) - $lastAlert).TotalMinutes -ge $PopupEveryMinutes
                if ($consecutiveFailures -eq $FailureThreshold -or ($consecutiveFailures -gt $FailureThreshold -and $alertDue)) {
                    Invoke-Alert -Reason $state.Reason
                    $lastAlert = Get-Date
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
