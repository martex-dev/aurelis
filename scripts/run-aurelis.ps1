<#
.SYNOPSIS
    Keep the Aurelis service and station running, and restart them if they stop.

.DESCRIPTION
    The service used to run in one PowerShell window and die with it: when the
    window closed, the machine restarted for an update, or a wake raised, the
    company stopped recording until somebody noticed. This script is the
    supervisor. It starts the station in its own minimised window if it is
    not already running, then runs the service in a loop: when the service
    exits for any reason, it waits a minute and starts it again.

    Keys for free sources that need one (Reddit, CryptoPanic) are read from
    <workspace>\keys.ps1 if that file exists. It is a plain PowerShell file of
    lines like:

        $env:AURELIS_KEY_REDDIT_CLIENT_ID = "..."
        $env:AURELIS_KEY_REDDIT_CLIENT_SECRET = "..."

    The workspace folder is ignored by git, so the file never leaves the
    machine. Nothing in Aurelis writes a key's value to the record.

    Stop it with Ctrl-C, or by closing the window.

.EXAMPLE
    .\scripts\run-aurelis.ps1
.EXAMPLE
    .\scripts\run-aurelis.ps1 -Workspace live -CallsPerDay 1200 -CallsPerWake 100 -Port 8787
#>
param(
    [string]$Workspace = "live",
    [int]$CallsPerDay = 1200,
    [int]$CallsPerWake = 100,
    [int]$Cycles = 150,
    [int]$Port = 8787,
    [string]$Provider = "agent_sdk"
)

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$aurelis = Join-Path $root ".venv\Scripts\aurelis.exe"
if (-not (Test-Path $aurelis)) {
    Write-Host "No Aurelis installation at $aurelis. Run this from the Aurelis folder's scripts\." -ForegroundColor Red
    exit 1
}

$env:AURELIS_PROVIDER = $Provider
$keys = Join-Path (Join-Path $root $Workspace) "keys.ps1"
if (Test-Path $keys) {
    . $keys
    Write-Host "Loaded source keys from $keys (values are not printed)."
}

$station = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "station serve -w $Workspace" }
if (-not $station) {
    Start-Process -FilePath $aurelis -ArgumentList @("station", "serve", "-w", $Workspace, "--port", "$Port") `
        -WorkingDirectory $root -WindowStyle Minimized
    Write-Host "Station started on http://localhost:$Port"
} else {
    Write-Host "Station already running."
}

while ($true) {
    $running = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "service start -w $Workspace" -and $_.ProcessId -ne $PID }
    if ($running) {
        Write-Host "A service for '$Workspace' is already running (pid $($running[0].ProcessId)). Waiting for it to stop."
        Start-Sleep -Seconds 300
        continue
    }
    Write-Host "$(Get-Date -Format s)  starting the service: $CallsPerDay model calls a day, at most $CallsPerWake a wake, a wake every hour."
    & $aurelis service start -w $Workspace --every 1h --for 30d --calls-per-day $CallsPerDay `
        --calls-per-wake $CallsPerWake --cycles $Cycles
    Write-Host "$(Get-Date -Format s)  the service stopped (exit code $LASTEXITCODE). Restarting in 60 seconds; Ctrl-C to stop." -ForegroundColor Yellow
    Start-Sleep -Seconds 60
}
