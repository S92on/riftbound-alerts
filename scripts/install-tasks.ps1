# Idempotent installer: registers two Windows scheduled tasks.
#   Riftbound-Bot            -> at user logon (starts the Discord slash-command bot)
#   Riftbound-Refresh-Cards  -> daily at 09:00 local (refreshes the card list)
#
# Tasks run as the current user, in the background, no admin needed.

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

$pwshExe = (Get-Command powershell.exe).Source

function Register-RiftboundTask {
    param(
        [string] $Name,
        [string] $Script,
        [Microsoft.Management.Infrastructure.CimInstance[]] $Triggers,
        [string] $Description,
        [Nullable[int]] $ExecutionTimeLimitMinutes = $null,
        [switch] $RestartOnFailure
    )

    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Write-Host "Removing existing task '$Name'..."
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false
    }

    $action = New-ScheduledTaskAction `
        -Execute $pwshExe `
        -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$Script`"" `
        -WorkingDirectory $root

    $settingsArgs = @{
        AllowStartIfOnBatteries    = $true
        DontStopIfGoingOnBatteries = $true
        StartWhenAvailable         = $true
        MultipleInstances          = "IgnoreNew"
    }
    if ($ExecutionTimeLimitMinutes) {
        $settingsArgs["ExecutionTimeLimit"] = New-TimeSpan -Minutes $ExecutionTimeLimitMinutes
    } else {
        # For long-running daemons (the bot), disable Task Scheduler's timeout.
        $settingsArgs["ExecutionTimeLimit"] = (New-TimeSpan -Seconds 0)
    }
    if ($RestartOnFailure) {
        $settingsArgs["RestartCount"]    = 3
        $settingsArgs["RestartInterval"] = (New-TimeSpan -Minutes 1)
    }
    $settings = New-ScheduledTaskSettingsSet @settingsArgs

    Register-ScheduledTask `
        -TaskName $Name `
        -Action $action `
        -Trigger $Triggers `
        -Settings $settings `
        -Description $Description | Out-Null

    Write-Host "Registered '$Name'."
}

# Bot: start at user logon, keep running, restart on failure.
$botTriggers = @(New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME")
Register-RiftboundTask `
    -Name "Riftbound-Bot" `
    -Script (Join-Path $root "scripts\run-bot.ps1") `
    -Triggers $botTriggers `
    -Description "Discord slash-command bot for on-demand Riftbound price lookups." `
    -RestartOnFailure

# Refresh: daily at 09:00 local time. ~30s typical runtime.
$refreshTriggers = @(New-ScheduledTaskTrigger -Daily -At "09:00")
Register-RiftboundTask `
    -Name "Riftbound-Refresh-Cards" `
    -Script (Join-Path $root "scripts\run-refresh.ps1") `
    -Triggers $refreshTriggers `
    -Description "Refreshes the Riftbound card list from TCGplayer once a day." `
    -ExecutionTimeLimitMinutes 10

Write-Host ""
Write-Host "Done. Run 'Get-ScheduledTask Riftbound-*' to inspect."
