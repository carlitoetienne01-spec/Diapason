<#
.SYNOPSIS
    Register / unregister the Diapason Windows scheduled task.

.DESCRIPTION
    The Windows equivalent of deploy/systemd/diapason.service and
    deploy/launchd/com.diapason.plist.

    Registers a per-user scheduled task named "Diapason" that starts
    `diapason serve` at logon and restarts on failure. Loopback default
    (127.0.0.1) so no API key is required — matches launchd parity.

    Subcommands:
      install   — create or replace the task
      uninstall — remove the task
      status    — show task state

    Arguments (install only):
      -InstallRoot <path>  default: %LOCALAPPDATA%\Diapason (matches
                           install.ps1's default)
      -ListenHost <addr>   default: 127.0.0.1 (loopback). A NON-LOOPBACK
                           VALUE IS NOW REFUSED — see -MaillageReseau below.
      -ListenPort <int>    default: 8000
      -MaillageReseau      open a SECOND socket carrying only the ten mesh
                           routes, so your other devices can reach this PC.
                           The full application stays on 127.0.0.1.
      -LanPort <int>       default: 8001 (the mesh socket)

    WHY -ListenHost 0.0.0.0 IS NO LONGER ACCEPTED
    ---------------------------------------------
    It put the WHOLE application — chat, voice, Succes, tools, roughly two
    hundred and ten routes — on the network. That is how the developer's Mac
    ended up serving all of them over Wi-Fi until 26 August 2026: protected by
    the API key, but reachable, and one route forgetting its protection would
    have been exposed the same day.

    The legitimate need behind it — « my phone cannot reach 127.0.0.1 » — now
    has its own, narrower door: -MaillageReseau. Ten routes, each requiring
    a device signature, invitation or scoped transfer token rather than the
    API key. A chat request on that socket returns 404, not 401: the route
    does not exist there.

    Usage:
      powershell -ExecutionPolicy Bypass -File diapason-service.ps1 install
      powershell -ExecutionPolicy Bypass -File diapason-service.ps1 uninstall
      powershell -ExecutionPolicy Bypass -File diapason-service.ps1 status
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('install', 'uninstall', 'status')]
    [string] $Command = 'status',

    [string] $InstallRoot,
    [string] $ListenHost = '127.0.0.1',
    [int]    $ListenPort = 8000,
    [switch] $MaillageReseau,
    [int]    $LanPort = 8001
)

$ErrorActionPreference = 'Stop'
$TaskName = 'Diapason'

# Compatibility aliases retained through Diapason 1.x. New names win.
if (-not $env:DIAPASON_HOME -and $env:OPENJARVIS_HOME) { $env:DIAPASON_HOME = $env:OPENJARVIS_HOME }
if (-not $env:DIAPASON_API_KEY -and $env:OPENJARVIS_API_KEY) { $env:DIAPASON_API_KEY = $env:OPENJARVIS_API_KEY }

function Write-Info  ($msg) { Write-Host "[info]  $msg" -ForegroundColor Cyan }
function Write-Ok    ($msg) { Write-Host "[ok]    $msg" -ForegroundColor Green }
function Write-Warn2 ($msg) { Write-Host "[warn]  $msg" -ForegroundColor Yellow }
function Write-Fail  ($msg) {
    Write-Host "[fail]  $msg" -ForegroundColor Red
    exit 1
}

function Get-DefaultInstallRoot {
    # Use $script: prefix so this is robust to being called from any
    # function scope (PowerShell's default dynamic lookup would also
    # work today, but $script: is the explicit contract).
    if ($script:InstallRoot) { return $script:InstallRoot }
    if ($env:DIAPASON_HOME) { return $env:DIAPASON_HOME }
    return (Join-Path $env:LOCALAPPDATA 'Diapason')
}

# ---------------------------------------------------------------------------
# install
# ---------------------------------------------------------------------------

function Install-Task {
    $root = Get-DefaultInstallRoot
    $srcDir = Join-Path $root 'src'
    if (-not (Test-Path $srcDir)) {
        Write-Fail "Diapason source not found at $srcDir. Run install.ps1 first."
    }

    $diapasonPath = Join-Path $srcDir '.venv\Scripts\diapason.exe'
    if (-not (Test-Path $diapasonPath)) {
        Write-Fail "Diapason executable not found at $diapasonPath. Re-run install.ps1."
    }

    # The full application never leaves this machine. The escape hatch that
    # allowed it existed for one real need — reaching this PC from another
    # device — and that need now has its own, narrower door.
    $isLoopback = ($ListenHost -eq '127.0.0.1' -or $ListenHost -eq 'localhost')
    if (-not $isLoopback) {
        Write-Fail @"
-ListenHost $ListenHost is refused: it would put the WHOLE application — chat,
voice, Succes, tools — on the network.

For your other devices to reach this PC, keep 127.0.0.1 and add:

    -MaillageReseau

That opens a second socket carrying only the ten mesh routes, each requiring
a device credential. A chat request there returns 404, not 401.
"@
    }

    if ($MaillageReseau -and $LanPort -eq $ListenPort) {
        Write-Fail "-LanPort and -ListenPort are both $LanPort. Two servers on one port bind silently on some systems and fail on others."
    }

    Write-Info "Registering scheduled task '$TaskName'..."
    Write-Info "  Working dir : $srcDir"
    Write-Info "  Listen      : $ListenHost`:$ListenPort"
    Write-Info "  User        : $env:USERNAME"

    # If a previous task exists, remove it first (idempotent install).
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Info "Existing task found — replacing."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    # Do not use `uv run` at every logon. It synchronizes before launching and
    # can remove extras that were deliberately installed (including the
    # native extension). The installer already created this executable in the
    # project venv; the scheduled task executes exactly that environment.
    $serveArgs = "serve --host $ListenHost --port $ListenPort"
    if ($MaillageReseau) {
        $serveArgs = "$serveArgs --lan-host 0.0.0.0 --lan-port $LanPort"
        Write-Info "  Maillage    : 0.0.0.0`:$LanPort (ten routes, device credential required)"
        Write-Info "  A shared network stays a shared network — see deploy/windows/README.md."
    }

    $action = New-ScheduledTaskAction `
        -Execute $diapasonPath `
        -Argument $serveArgs `
        -WorkingDirectory $srcDir

    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

    $principal = New-ScheduledTaskPrincipal `
        -UserId $env:USERNAME `
        -LogonType Interactive `
        -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Description 'Diapason API server (loopback default — see deploy/windows/README.md)' | Out-Null

    Write-Ok "Task '$TaskName' registered."
    Write-Info "It will start automatically at next logon."
    Write-Info "To start it now: Start-ScheduledTask -TaskName $TaskName"
}

# ---------------------------------------------------------------------------
# uninstall
# ---------------------------------------------------------------------------

function Uninstall-Task {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $existing) {
        Write-Warn2 "Task '$TaskName' is not registered — nothing to remove."
        return
    }
    Write-Info "Stopping '$TaskName' (if running)..."
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Write-Info "Unregistering '$TaskName'..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Ok "Task '$TaskName' removed."
}

# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------

function Show-Status {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Host "Task '$TaskName' is not registered."
        Write-Host "Install it with:"
        Write-Host "  powershell -ExecutionPolicy Bypass -File `"$PSCommandPath`" install"
        return
    }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    Write-Host "Task    : $TaskName"
    Write-Host "State   : $($task.State)"
    Write-Host "LastRun : $($info.LastRunTime)"
    Write-Host "LastRes : 0x$('{0:X8}' -f $info.LastTaskResult)"
    Write-Host "NextRun : $($info.NextRunTime)"
}

# ---------------------------------------------------------------------------
# dispatch
# ---------------------------------------------------------------------------

switch ($Command) {
    'install'   { Install-Task }
    'uninstall' { Uninstall-Task }
    'status'    { Show-Status }
}
