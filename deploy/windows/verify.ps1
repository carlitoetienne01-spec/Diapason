<#
.SYNOPSIS
    Verify a native Windows Diapason installation without changing it.

.DESCRIPTION
    Produces evidence for the exact boundaries needed by the desktop and Mesh:
      - the authenticated checkout and project venv exist;
      - the Diapason package imports from that venv;
      - optionally, the mandatory PyO3 extension imports;
      - the full API answers on loopback only;
      - optionally, the LAN socket exists and exposes Mesh but not chat,
        health, docs, or the React application.

    The script never starts, stops, installs, pairs, or transfers anything.
    Start the scheduled task before running it when server checks are wanted.

    Examples:
      .\verify.ps1
      .\verify.ps1 -RequireNative -RequireMesh
      .\verify.ps1 -RequireNative -RequireMesh -Json
#>

[CmdletBinding()]
param(
    [string] $InstallRoot,
    [int]    $ListenPort = 8000,
    [int]    $LanPort = 8001,
    [switch] $RequireNative,
    [switch] $RequireMesh,
    [switch] $Json
)

$ErrorActionPreference = 'Stop'
$checks = New-Object System.Collections.Generic.List[object]

function Add-Check {
    param(
        [string] $Name,
        [bool]   $Passed,
        [string] $Detail,
        [bool]   $Required = $true
    )
    $script:checks.Add([pscustomobject]@{
        name = $Name
        passed = $Passed
        required = $Required
        detail = $Detail
    })
}

function Get-HttpStatus {
    param(
        [string] $Uri,
        [ValidateSet('GET', 'POST')]
        [string] $Method = 'GET'
    )
    try {
        $arguments = @{
            Uri = $Uri
            Method = $Method
            UseBasicParsing = $true
            TimeoutSec = 5
        }
        if ($Method -eq 'POST') {
            $arguments.ContentType = 'application/json'
            $arguments.Body = '{}'
        }
        $response = Invoke-WebRequest @arguments
        return [int]$response.StatusCode
    } catch {
        $response = $_.Exception.Response
        if ($response -and $response.StatusCode) {
            return [int]$response.StatusCode
        }
        return 0
    }
}

function Get-Listeners {
    param([int] $Port)
    try {
        return @(
            Get-NetTCPConnection -State Listen -LocalPort $Port `
                -ErrorAction SilentlyContinue
        )
    } catch {
        return @()
    }
}

$root = if ($InstallRoot) {
    $InstallRoot
} elseif ($env:DIAPASON_HOME) {
    $env:DIAPASON_HOME
} else {
    Join-Path $env:LOCALAPPDATA 'Diapason'
}
$srcDir = Join-Path $root 'src'
$pyproject = Join-Path $srcDir 'pyproject.toml'
$pythonExe = Join-Path $srcDir '.venv\Scripts\python.exe'
$diapasonExe = Join-Path $srcDir '.venv\Scripts\diapason.exe'

Add-Check 'project.checkout' (Test-Path $pyproject -PathType Leaf) $pyproject
Add-Check 'venv.python' (Test-Path $pythonExe -PathType Leaf) $pythonExe
Add-Check 'venv.diapason' (Test-Path $diapasonExe -PathType Leaf) $diapasonExe

if (Test-Path $diapasonExe -PathType Leaf) {
    $version = (& $diapasonExe --version 2>&1 | Out-String).Trim()
    Add-Check 'cli.version' ($LASTEXITCODE -eq 0) $version
}

if (Test-Path $pythonExe -PathType Leaf) {
    $pythonImport = (& $pythonExe -c 'import diapason; print(diapason.__file__)' 2>&1 | Out-String).Trim()
    Add-Check 'python.import' ($LASTEXITCODE -eq 0) $pythonImport

    $nativeImport = (& $pythonExe -c 'import diapason_rust; print(diapason_rust.__file__)' 2>&1 | Out-String).Trim()
    Add-Check 'python.native' ($LASTEXITCODE -eq 0) $nativeImport ([bool]$RequireNative)
}

$task = Get-ScheduledTask -TaskName 'Diapason' -ErrorAction SilentlyContinue
if ($task) {
    Add-Check 'service.registered' $true "state=$($task.State)" $false
} else {
    Add-Check 'service.registered' $false 'scheduled task not registered' $false
}

$apiBase = "http://127.0.0.1:$ListenPort"
$apiHealth = Get-HttpStatus "$apiBase/health"
Add-Check 'api.health' ($apiHealth -eq 200) "HTTP $apiHealth from $apiBase/health"

$apiListeners = Get-Listeners $ListenPort
$foreignApiListeners = @(
    $apiListeners | Where-Object {
        $_.LocalAddress -notin @('127.0.0.1', '::1')
    }
)
Add-Check 'api.loopback_only' (
    $apiListeners.Count -gt 0 -and $foreignApiListeners.Count -eq 0
) "listeners=$($apiListeners.LocalAddress -join ',')"

$meshListeners = Get-Listeners $LanPort
$meshDetected = $meshListeners.Count -gt 0
if ($RequireMesh -or $meshDetected) {
    $publicMeshListeners = @(
        $meshListeners | Where-Object {
            $_.LocalAddress -in @('0.0.0.0', '::')
        }
    )
    Add-Check 'mesh.listener' ($publicMeshListeners.Count -gt 0) (
        "listeners=$($meshListeners.LocalAddress -join ',')"
    ) ([bool]$RequireMesh)

    $meshBase = "http://127.0.0.1:$LanPort"
    $chatStatus = Get-HttpStatus "$meshBase/v1/chat/completions" 'POST'
    $healthStatus = Get-HttpStatus "$meshBase/health"
    $docsStatus = Get-HttpStatus "$meshBase/docs"
    $presenceStatus = Get-HttpStatus "$meshBase/v1/mesh/presence" 'POST'

    Add-Check 'mesh.no_chat' ($chatStatus -eq 404) "HTTP $chatStatus"
    Add-Check 'mesh.no_health' ($healthStatus -eq 404) "HTTP $healthStatus"
    Add-Check 'mesh.no_docs' ($docsStatus -eq 404) "HTTP $docsStatus"
    # An empty beacon reaches the route but must be rejected by its Ed25519
    # credential gate. A 404 would mean the route is absent; 200 would be a
    # security defect; 422 would only prove that FastAPI saw a path.
    Add-Check 'mesh.has_signed_door' (
        $presenceStatus -eq 403
    ) "unsigned presence returned HTTP $presenceStatus"
}

if ($Json) {
    $checks | ConvertTo-Json -Depth 4
} else {
    foreach ($check in $checks) {
        $label = if ($check.passed) { '[ok]  ' } elseif ($check.required) { '[fail]' } else { '[warn]' }
        $color = if ($check.passed) { 'Green' } elseif ($check.required) { 'Red' } else { 'Yellow' }
        Write-Host "$label $($check.name): $($check.detail)" -ForegroundColor $color
    }
}

$failures = @($checks | Where-Object { $_.required -and -not $_.passed })
if ($failures.Count -gt 0) {
    exit 1
}
exit 0
