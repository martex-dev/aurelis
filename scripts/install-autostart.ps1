<#
.SYNOPSIS
    Start Aurelis automatically every time you log in to Windows.

.DESCRIPTION
    Registers a Windows scheduled task named "Aurelis" that runs
    scripts\run-aurelis.ps1 at logon, in its own window. After a restart for a
    Windows update, the company starts recording again as soon as you log in,
    instead of waiting for somebody to notice it stopped.

    This changes a setting on your machine, so it is a script you run yourself
    rather than something Aurelis does on its own. Remove it at any time with:

        Unregister-ScheduledTask -TaskName Aurelis -Confirm:$false

.EXAMPLE
    .\scripts\install-autostart.ps1
#>
param(
    [string]$Workspace = "live",
    [int]$CallsPerDay = 1200
)

$script = Join-Path $PSScriptRoot "run-aurelis.ps1"
$arguments = "-NoProfile -ExecutionPolicy Bypass -NoExit -File `"$script`" -Workspace $Workspace -CallsPerDay $CallsPerDay"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arguments -WorkingDirectory (Split-Path -Parent $PSScriptRoot)
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "Aurelis" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Keeps the Aurelis service and station running." -Force | Out-Null
Write-Host "Registered the scheduled task 'Aurelis': it starts at every logon." -ForegroundColor Green
Write-Host "Start it now without logging out:  Start-ScheduledTask -TaskName Aurelis"
Write-Host "Remove it:                         Unregister-ScheduledTask -TaskName Aurelis -Confirm:`$false"
