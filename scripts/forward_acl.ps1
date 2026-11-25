# ACL del forward.
#
# IMPORTANTE:
#   - "Operational" deja escribir SOLO a la cuenta que ejecuta el forward
#     (SYSTEM, Administradores y el operador). El resto de Users queda RX.
#     Es la ACL que debe usarse con los brazos vivos: necesitan escribir
#     SQLite, ledgers, heartbeats y sesiones.
#   - "ReadOnly" deja todo el árbol RX para el operador. Solo se aplica a una
#     COPIA sellada bajo $AuditRoot\sealed; nunca a data/forward, aunque no haya
#     puertos escuchando. Así no puede dejar el forward vivo sin escritura.
#
# Uso:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\forward_acl.ps1 `
#       -Mode Operational -Apply
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\forward_acl.ps1 `
#       -Mode ReadOnly -Root "$env:USERPROFILE\YEDBot-audit\sealed\FORWARD-..." -Apply
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\forward_acl.ps1 `
#       -Restore "$env:USERPROFILE\YEDBot-audit\acl\forward-acl-Operational-<fecha>.json"
#
# Sin -Apply solo imprime el plan y no cambia ninguna ACL. El backup es un JSON
# versionado con el SDDL completo de cada ruta; la restauración usa
# SetFileSecurity (solo DACL) y verifica el SDDL resultante ruta por ruta.

[CmdletBinding()]
param(
    [ValidateSet("Operational", "ReadOnly")]
    [string]$Mode = "Operational",
    [string]$Root = "",
    [string]$AuditRoot = (Join-Path $env:USERPROFILE "YEDBot-audit"),
    [string]$Restore = "",
    [switch]$Apply
)

$ErrorActionPreference = "Stop"

$Project = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$LiveRoot = [IO.Path]::GetFullPath((Join-Path $Project "data\forward"))
if ([string]::IsNullOrWhiteSpace($Root)) {
    $Root = $LiveRoot
}
$RootFull = [IO.Path]::GetFullPath($Root)
$AuditRootFull = [IO.Path]::GetFullPath($AuditRoot)
$ProjectFull = [IO.Path]::GetFullPath($Project)
$Separator = [IO.Path]::DirectorySeparatorChar
if ($AuditRootFull.Equals($ProjectFull, [StringComparison]::OrdinalIgnoreCase) -or
    $AuditRootFull.StartsWith($ProjectFull + $Separator, [StringComparison]::OrdinalIgnoreCase)) {
    throw "AuditRoot debe estar fuera del proyecto: $AuditRootFull"
}
$SealedRoot = [IO.Path]::GetFullPath((Join-Path $AuditRootFull "sealed"))
$Sid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$SystemSid = "S-1-5-18"
$AdministratorsSid = "S-1-5-32-544"
$UsersSid = "S-1-5-32-545"
$BackupSchema = "forward-acl-sddl-backup-v2"

if (-not ("ForwardAclNative" -as [type])) {
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class ForwardAclNative
{
    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode)]
    public static extern bool SetFileSecurity(
        string lpFileName,
        int securityInformation,
        IntPtr pSecurityDescriptor);
}
"@
}

function Invoke-Icacls {
    param([string[]]$Arguments)
    & icacls.exe @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "icacls falló (exit $LASTEXITCODE): icacls $($Arguments -join ' ')"
    }
}

function Test-PortListening {
    param([int]$Port)
    return [bool](Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Get-AclEntries {
    param([string]$Root)
    $rootItem = Get-Item -LiteralPath $Root -Force
    $rootPrefix = $rootItem.FullName.TrimEnd("\") + "\"
    $items = @($rootItem) + @(Get-ChildItem -LiteralPath $Root -Recurse -Force -ErrorAction Stop)
    $entries = @()
    foreach ($item in $items) {
        $relative = if ($item.FullName.Equals($rootItem.FullName, [StringComparison]::OrdinalIgnoreCase)) {
            "."
        } else {
            $item.FullName.Substring($rootPrefix.Length)
        }
        $relative = $relative -replace "\\", "/"
        $acl = Get-Acl -LiteralPath $item.FullName
        $entries += [pscustomobject]@{
            path = $relative
            type = if ($item.PSIsContainer) { "directory" } else { "file" }
            sddl = $acl.Sddl
        }
    }
    return @($entries | Sort-Object path)
}

function Write-AclBackup {
    param(
        [string]$Root,
        [string]$Mode,
        [string]$Path
    )
    $entries = Get-AclEntries -Root $Root
    $payload = [ordered]@{
        schema = $BackupSchema
        created_at = (Get-Date).ToUniversalTime().ToString("o")
        mode = $Mode
        root = $Root
        entries = @($entries)
    }
    $json = $payload | ConvertTo-Json -Depth 8
    $utf8 = New-Object System.Text.UTF8Encoding($false)
    [IO.File]::WriteAllText($Path, $json, $utf8)
    return $entries
}

function Set-AclSddl {
    param(
        [string]$Path,
        [string]$Sddl
    )
    $raw = New-Object System.Security.AccessControl.RawSecurityDescriptor($Sddl)
    if ($null -eq $raw.DiscretionaryAcl) {
        throw "El SDDL no contiene DACL: $Path"
    }
    $bytes = New-Object byte[] $raw.BinaryLength
    $raw.GetBinaryForm($bytes, 0)
    $control = [BitConverter]::ToUInt16($bytes, 2)
    if (($control -band 0x0400) -ne 0) {
        # SE_DACL_AUTO_INHERITED: SetFileSecurity no conserva AI por sí solo.
        # SE_DACL_AUTO_INHERIT_REQ hace que el sistema lo reponga sin reordenar
        # las ACEs ni exigir SeRestorePrivilege.
        $control = $control -bor 0x0100
        $bytes[2] = [byte]($control -band 0xff)
        $bytes[3] = [byte](($control -shr 8) -band 0xff)
    }
    $ptr = [Runtime.InteropServices.Marshal]::AllocHGlobal($bytes.Length)
    try {
        [Runtime.InteropServices.Marshal]::Copy($bytes, 0, $ptr, $bytes.Length)
        # DACL_SECURITY_INFORMATION. El descriptor completo conserva orden,
        # herencia y flags de control sin tocar owner, group ni SACL, por lo
        # que no requiere SeSecurityPrivilege ni SeRestorePrivilege.
        $ok = [ForwardAclNative]::SetFileSecurity($Path, 0x4, $ptr)
        if (-not $ok) {
            $code = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
            throw "SetFileSecurity falló en $Path (Win32 $code)"
        }
    }
    finally {
        [Runtime.InteropServices.Marshal]::FreeHGlobal($ptr)
    }
}

function Restore-AclBackup {
    param([string]$BackupPath)
    $resolved = (Resolve-Path -LiteralPath $BackupPath).Path
    $document = Get-Content -LiteralPath $resolved -Raw | ConvertFrom-Json
    if ($document.schema -ne $BackupSchema) {
        throw "Backup inválido: schema $($document.schema), se esperaba $BackupSchema"
    }
    $root = [IO.Path]::GetFullPath([string]$document.root)
    if (-not (Test-Path -LiteralPath $root -PathType Container)) {
        throw "No existe la raíz del backup: $root"
    }
    $rootIsLive = $root.Equals($LiveRoot, [StringComparison]::OrdinalIgnoreCase)
    $rootIsSealed = $root.StartsWith($SealedRoot + $Separator, [StringComparison]::OrdinalIgnoreCase)
    if (-not ($rootIsLive -or $rootIsSealed)) {
        throw "Restore solo acepta $LiveRoot o una copia bajo $SealedRoot (recibido: $root)"
    }
    if ($rootIsLive) {
        $busy = @(8775, 8776, 8778) | Where-Object { Test-PortListening $_ }
        if (@($busy).Count -gt 0) {
            throw "Restore del forward vivo bloqueado: hay puertos escuchando ($($busy -join ', ')). Detén el autorun primero."
        }
    }
    $entries = @($document.entries)
    if ($entries.Count -eq 0) {
        throw "El backup no contiene rutas: $resolved"
    }

    $rootPrefix = $root.TrimEnd("\") + "\"
    $validated = @()
    foreach ($entry in $entries) {
        $relative = [string]$entry.path
        if ([string]::IsNullOrWhiteSpace($relative)) {
            throw "Entrada sin path en $resolved"
        }
        if ([IO.Path]::IsPathRooted($relative) -or $relative -match '(^|[\\/])\.\.([\\/]|$)') {
            throw "Path no relativo o con traversal: $relative"
        }
        $relativeFs = $relative -replace "/", "\"
        $full = [IO.Path]::GetFullPath((Join-Path $root $relativeFs))
        if (-not $full.Equals($root, [StringComparison]::OrdinalIgnoreCase) -and
            -not $full.StartsWith($rootPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Path fuera de la raíz: $relative"
        }
        if (-not (Test-Path -LiteralPath $full)) {
            throw "Falta la ruta del backup: $full"
        }
        $item = Get-Item -LiteralPath $full -Force
        $expectedDirectory = ([string]$entry.type -eq "directory")
        if ($item.PSIsContainer -ne $expectedDirectory) {
            throw "Tipo distinto al backup: $full"
        }
        $depth = if ($relative -eq ".") { 0 } else { ($relative -split "/").Count }
        $validated += [pscustomobject]@{
            Full = $full
            Relative = $relative
            Sddl = [string]$entry.sddl
            Depth = $depth
        }
    }

    Write-Host "Restaurando backup: $resolved"
    Write-Host "Raíz:               $root"
    Write-Host "Entradas:           $($validated.Count)"
    Write-Host ""

    foreach ($entry in ($validated | Sort-Object Depth, Relative)) {
        Set-AclSddl -Path $entry.Full -Sddl $entry.Sddl
        $actual = (Get-Acl -LiteralPath $entry.Full).Sddl
        if ($actual -ne $entry.Sddl) {
            throw "ACL no restaurada en $($entry.Full)`nEsperado: $($entry.Sddl)`nActual:   $actual"
        }
        Write-Host "[PASS] ACL restaurada: $($entry.Relative)"
    }
}

if (-not [string]::IsNullOrWhiteSpace($Restore)) {
    try {
        Restore-AclBackup -BackupPath $Restore
    }
    catch {
        Write-Error "FORWARD_ACL_RESTORE_FAIL: $($_.Exception.Message)"
        exit 2
    }
    exit 0
}

if (-not (Test-Path -LiteralPath $RootFull -PathType Container)) {
    throw "No existe el directorio: $RootFull"
}

if ($Mode -eq "Operational") {
    if (-not $RootFull.Equals($LiveRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Operational solo se aplica a $LiveRoot (recibido: $RootFull)"
    }
}
else {
    if ($RootFull.Equals($LiveRoot, [StringComparison]::OrdinalIgnoreCase) -or
        $RootFull.StartsWith($LiveRoot + $Separator, [StringComparison]::OrdinalIgnoreCase)) {
        throw "ReadOnly no se aplica al forward vivo ni a sus hijos. Detén la tarea y copia la ventana a $SealedRoot."
    }
    if (-not $RootFull.StartsWith($SealedRoot + $Separator, [StringComparison]::OrdinalIgnoreCase)) {
        throw "ReadOnly solo se aplica a una copia bajo $SealedRoot (recibido: $RootFull)"
    }
    $busy = @(8775, 8776, 8778) | Where-Object { Test-PortListening $_ }
    if (@($busy).Count -gt 0) {
        throw "ReadOnly bloqueado: hay puertos forward escuchando ($($busy -join ', ')). Detén el autorun primero."
    }
}

$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $AuditRootFull "acl\forward-acl-$Mode-$stamp.json"
if ($Apply) {
    New-Item -ItemType Directory -Force -Path (Join-Path $AuditRootFull "acl") | Out-Null
}

if ($Mode -eq "Operational") {
    $grants = @(
        "*${SystemSid}:(OI)(CI)F",
        "*${AdministratorsSid}:(OI)(CI)F",
        "*${Sid}:(OI)(CI)M",
        "*${UsersSid}:(OI)(CI)RX"
    )
}
else {
    $grants = @(
        "*${SystemSid}:(OI)(CI)F",
        "*${AdministratorsSid}:(OI)(CI)F",
        "*${Sid}:(OI)(CI)RX",
        "*${UsersSid}:(OI)(CI)RX"
    )
}

Write-Host "Proyecto:   $Project"
Write-Host "Raíz ACL:   $RootFull"
Write-Host "Modo:       $Mode"
Write-Host "Backup ACL: $backup"
Write-Host "Reglas:     $($grants -join ' ')"
Write-Host ""
Write-Host "Comandos que se aplicarán:"
Write-Host "  Captura SDDL recursiva en: $backup"
Write-Host "  icacls `"$RootFull`" /reset /T /C"
Write-Host "  icacls `"$RootFull`" /inheritance:r"
Write-Host "  icacls `"$RootFull`" /grant:r $($grants -join ' ')"
Write-Host ""

if (-not $Apply) {
    Write-Host "DRY-RUN: no se ha cambiado ninguna ACL. Repite con -Apply."
    exit 0
}

$null = Write-AclBackup -Root $RootFull -Mode $Mode -Path $backup

Invoke-Icacls @($RootFull, "/reset", "/T", "/C")
Invoke-Icacls @($RootFull, "/inheritance:r")
Invoke-Icacls (@($RootFull, "/grant:r") + $grants)

$aclText = (& icacls.exe $RootFull) -join "`n"
if ($LASTEXITCODE -ne 0) {
    throw "No se pudo leer la ACL resultante."
}
if ($aclText -notmatch "\(RX\)") {
    throw "La ACL resultante no contiene una entrada RX; revisa la salida de icacls."
}
if ($Mode -eq "Operational" -and $aclText -notmatch "\(M\)") {
    throw "La ACL operativa no contiene la entrada Modify del operador; el forward no podría escribir."
}

if ($Mode -eq "Operational") {
    $probe = Join-Path $RootFull ".acl-probe-$PID"
    try {
        Set-Content -LiteralPath $probe -Value "ok" -Encoding ASCII -ErrorAction Stop
        Remove-Item -LiteralPath $probe -Force -ErrorAction Stop
        Write-Host "[PASS] El operador puede escribir en el root operativo."
    }
    catch {
        throw "El operador no puede escribir en $RootFull; se habría roto el forward. Restaura la ACL con: powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Restore `"$backup`""
    }
}
else {
    Write-Host "[PASS] Árbol RX preparado. No se probó escritura porque ReadOnly debe denegarla."
}

Write-Host ""
Write-Host "ACL final:"
& icacls.exe $RootFull
Write-Host ""
Write-Host "Restauración:"
Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`" -Restore `"$backup`""
Write-Host "Backup: $backup"
