<#
.SYNOPSIS
    Update the real Windows installation from its self-hosted runner.

.DESCRIPTION
    This script is intentionally narrower than install.ps1. It is called only
    by a manually dispatched workflow after a validation MSI has built on the
    same PC. It fast-forwards the existing clean checkout from the runner's
    local checkout, force-repairs the same-version MSI, restarts the scheduled
    task, and runs the native + Mesh verifier.

    No network credential is copied into the installed checkout. The commit is
    fetched from GITHUB_WORKSPACE over the local filesystem.
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[0-9a-fA-F]{40}$')]
    [string] $CheckoutSha,

    [Parameter(Mandatory = $true)]
    [string] $MsiPath,

    [string] $TaskName = 'Diapason'
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Step([string] $Message) {
    Write-Host "[deploy] $Message" -ForegroundColor Cyan
}

function Fail([string] $Message) {
    throw "Windows local deployment refused: $Message"
}

function Invoke-Git([string[]] $Arguments) {
    & git @Arguments
    if ($LASTEXITCODE -ne 0) {
        Fail "git $($Arguments -join ' ') exited $LASTEXITCODE"
    }
}

function Invoke-DependencySync(
    [string] $UvExe,
    [string[]] $Arguments,
    [string] $ProjectRoot,
    [string] $Purpose
) {
    Write-Step "$Purpose in $ProjectRoot"
    Push-Location $ProjectRoot
    try {
        & $UvExe @Arguments
        if ($LASTEXITCODE -ne 0) {
            Fail "uv sync failed during $Purpose (exit $LASTEXITCODE)"
        }
    } finally {
        Pop-Location
    }
}

function Find-InstalledSource {
    $candidates = New-Object System.Collections.Generic.List[string]
    if ($env:LOCALAPPDATA) {
        [void] $candidates.Add((Join-Path $env:LOCALAPPDATA 'Diapason\src'))
    }
    foreach ($profile in (Get-ChildItem 'C:\Users' -Directory -ErrorAction SilentlyContinue)) {
        [void] $candidates.Add(
            (Join-Path $profile.FullName 'AppData\Local\Diapason\src')
        )
    }

    $found = @(
        $candidates |
            Select-Object -Unique |
            Where-Object {
                (Test-Path (Join-Path $_ '.git')) -and
                (Test-Path (Join-Path $_ '.venv\Scripts\diapason.exe'))
            }
    )
    if ($found.Count -ne 1) {
        Fail "expected one installed checkout, found $($found.Count): $($found -join ', ')"
    }
    return $found[0]
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal] $identity
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Wait-TaskStopped([string] $Name) {
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        $state = (Get-ScheduledTask -TaskName $Name -ErrorAction Stop).State
        if ($state -ne 'Running') { return }
        Start-Sleep -Milliseconds 250
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "scheduled task '$Name' did not stop within 20 seconds"
}

function Wait-TaskRunning([string] $Name) {
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    do {
        $state = (Get-ScheduledTask -TaskName $Name -ErrorAction Stop).State
        if ($state -eq 'Running') { return }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "scheduled task '$Name' did not start within 45 seconds"
}

function Wait-ApiHealthy([int] $Port) {
    $deadline = [DateTime]::UtcNow.AddSeconds(45)
    do {
        try {
            $response = Invoke-WebRequest `
                -Uri "http://127.0.0.1:$Port/health" `
                -UseBasicParsing `
                -TimeoutSec 2
            if ([int]$response.StatusCode -eq 200) { return }
        } catch {
            # The scheduled task is still importing the application.
        }
        Start-Sleep -Milliseconds 500
    } while ([DateTime]::UtcNow -lt $deadline)
    Fail "Diapason did not answer on 127.0.0.1:$Port within 45 seconds"
}

if ([Environment]::OSVersion.Platform -ne [PlatformID]::Win32NT) {
    Fail 'this script only runs on Windows'
}
if (-not (Test-IsAdministrator)) {
    Fail 'the runner is not elevated; restart run.cmd from an Administrator PowerShell'
}
if (-not (Test-Path $MsiPath -PathType Leaf)) {
    Fail "validation MSI not found at $MsiPath"
}
if (-not $env:GITHUB_WORKSPACE -or -not (Test-Path (Join-Path $env:GITHUB_WORKSPACE '.git'))) {
    Fail 'GITHUB_WORKSPACE is not a Git checkout'
}

$source = Find-InstalledSource
$remote = [string](& git -C $source remote get-url origin 2>$null | Select-Object -First 1)
$remote = $remote.Trim()
$allowedRemotes = @(
    'https://github.com/carlitoetienne01-spec/Diapason.git',
    'https://github.com/carlitoetienne01-spec/Diapason',
    'git@github.com:carlitoetienne01-spec/Diapason.git',
    'ssh://git@github.com/carlitoetienne01-spec/Diapason.git'
)
if ($LASTEXITCODE -ne 0 -or $remote -notin $allowedRemotes) {
    Fail "installed checkout has an unexpected origin: $remote"
}

$dirty = @(& git -C $source status --porcelain --untracked-files=no)
if ($LASTEXITCODE -ne 0) { Fail 'could not inspect the installed checkout' }
if ($dirty.Count -gt 0) {
    Fail 'the installed checkout has tracked local changes; nothing was overwritten'
}

$oldHead = (& git -C $source rev-parse HEAD).Trim()
if ($LASTEXITCODE -ne 0) { Fail 'could not read the installed commit' }
Write-Step "installed checkout: $source"
Write-Step "fast-forward: $oldHead -> $CheckoutSha"

Invoke-Git @('-C', $source, 'fetch', '--no-tags', $env:GITHUB_WORKSPACE, 'HEAD')
$fetchedHead = (& git -C $source rev-parse FETCH_HEAD).Trim()
if ($LASTEXITCODE -ne 0 -or $fetchedHead -ne $CheckoutSha) {
    Fail "runner checkout is $fetchedHead instead of $CheckoutSha"
}
& git -C $source merge-base --is-ancestor $oldHead $CheckoutSha
if ($LASTEXITCODE -ne 0) {
    Fail 'the requested commit is not a fast-forward of the installed checkout'
}

$dependencyChanges = @(
    & git -C $source diff --name-only "$oldHead..$CheckoutSha" -- pyproject.toml uv.lock
)
if ($LASTEXITCODE -ne 0) { Fail 'could not inspect dependency changes' }
$projectChanged = $dependencyChanges -contains 'pyproject.toml'
$lockChanged = $dependencyChanges -contains 'uv.lock'
if ($projectChanged) {
    Fail 'pyproject.toml changed; rerun install.ps1 -Force instead'
}

$uvExe = ''
$syncArgs = @(
    'sync',
    '--locked',
    '--extra', 'desktop',
    '--extra', 'dictation',
    '--extra', 'voice-local',
    '--extra', 'inference-cloud',
    '--extra', 'inference-google',
    '--group', 'desktop-native'
)
if ($lockChanged) {
    $uvCommand = Get-Command uv -ErrorAction SilentlyContinue
    if (-not $uvCommand) {
        Fail 'uv.lock changed but uv is not available on the runner'
    }
    $uvExe = $uvCommand.Source
    # On 28 August 2026, Python 3.13 compiled the old tokenizer because no
    # wheel existed and left the real environment partially synchronized. The
    # runner checkout is disposable: the same locked plan must succeed there
    # BEFORE Carlito's service or environment is touched.
    Invoke-DependencySync $uvExe $syncArgs $env:GITHUB_WORKSPACE `
        'preflighting the locked desktop dependencies'
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $task) { Fail "scheduled task '$TaskName' is not installed" }
$taskWasRunning = $task.State -eq 'Running'
$desktopProcesses = @(
    Get-Process -ErrorAction SilentlyContinue |
        Where-Object { $_.ProcessName -in @('diapason-desktop', 'Diapason') }
)
$desktopWasRunning = $desktopProcesses.Count -gt 0
$serviceRestarted = $false

try {
    if ($desktopWasRunning) {
        Write-Step 'closing the desktop app for the MSI repair'
        $desktopProcesses | Stop-Process -Force
    }
    if ($taskWasRunning) {
        Write-Step 'stopping the Diapason scheduled task'
        Stop-ScheduledTask -TaskName $TaskName
        Wait-TaskStopped $TaskName
    }

    Invoke-Git @('-C', $source, 'merge', '--ff-only', $CheckoutSha)
    $installedHead = (& git -C $source rev-parse HEAD).Trim()
    if ($installedHead -ne $CheckoutSha) {
        Fail "checkout stopped at $installedHead instead of $CheckoutSha"
    }

    if ($lockChanged) {
        Invoke-DependencySync $uvExe $syncArgs $source `
            'synchronizing the installed desktop dependencies'
    }

    $logPath = Join-Path $env:RUNNER_TEMP 'Diapason-local-update-msi.log'
    Write-Step "repairing the installed MSI: $MsiPath"
    $msi = Start-Process msiexec.exe -Wait -PassThru -ArgumentList @(
        '/fvomus',
        "`"$MsiPath`"",
        '/qn',
        '/norestart',
        '/L*v',
        "`"$logPath`""
    )
    if ($msi.ExitCode -notin @(0, 3010)) {
        Fail "msiexec exited $($msi.ExitCode); log: $logPath"
    }

    if ($taskWasRunning) {
        Write-Step 'starting the Diapason scheduled task'
        Start-ScheduledTask -TaskName $TaskName
        Wait-TaskRunning $TaskName
        Wait-ApiHealthy 8000
        $serviceRestarted = $true
    }

    $verify = Join-Path $source 'deploy\windows\verify.ps1'
    $installRoot = Split-Path $source -Parent
    & powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass `
        -File $verify -InstallRoot $installRoot -RequireNative -RequireMesh
    if ($LASTEXITCODE -ne 0) {
        Fail "verify.ps1 exited $LASTEXITCODE"
    }
}
finally {
    if ($taskWasRunning -and -not $serviceRestarted) {
        Write-Step 'recovering the scheduled task after a failed update'
        Start-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    }
}

if ($desktopWasRunning) {
    Write-Step 'the desktop app was closed for the update; reopen Diapason from Start'
}
Write-Step "Windows installation updated to $CheckoutSha"
