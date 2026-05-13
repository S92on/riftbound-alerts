# Idempotent installer: registers two Windows scheduled tasks.
#   Riftbound-Alerts-Signals  -> every 30 min (signal scan)
#   Riftbound-Alerts-Refresh  -> daily at 09:00 local (card list refresh)
#
# Tasks run as the current user, in the background, regardless of login state.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$pwshExe = (Get-Command powershell.exe).Source

function Register-RiftboundTask {
    param(
        [string] $Name,
        [string] $Script,
        [Microsoft.Management.Infrastructure.CimInstance[]] $Triggers,
        [string] $Description
    )

    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Write-Host "Removing existing task '$Name'..."
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }

    $action = New-ScheduledTaskAction `
        -Execute $pwshExe `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`"" `
        -WorkingDirectory $root

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 25) `
        -MultipleInstances IgnoreNew

    Register-ScheduledTask `
        -TaskName $Name `
        -Action $action `
        -Trigger $Triggers `
        -Settings $settings `
        -Description $Description | Out-Null

    Write-Host "Registered '$Name'."
}

# Signals: every 30 minutes, indefinitely
$signalTriggers = @(
    New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
        -RepetitionInterval (New-TimeSpan -Minutes 30)
)
Register-RiftboundTask `
    -Name "Riftbound-Alerts-Signals" `
    -Script (Join-Path $root "scripts\run-signals.ps1") `
    -Triggers $signalTriggers `
    -Description "Polls TCGplayer every 30 min and posts Riftbound Deck Identity alerts to Discord."

# Refresh: daily at 09:00 local time
$refreshTriggers = @(
    New-ScheduledTaskTrigger -Daily -At "09:00"
)
Register-RiftboundTask `
    -Name "Riftbound-Alerts-Refresh" `
    -Script (Join-Path $root "scripts\run-refresh.ps1") `
    -Triggers $refreshTriggers `
    -Description "Refreshes the Riftbound card list from TCGplayer once a day."

Write-Host ""
Write-Host "Done. Run 'Get-ScheduledTask Riftbound-Alerts-*' to inspect."
