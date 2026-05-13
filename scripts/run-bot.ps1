# Wrapper invoked by Windows Task Scheduler to launch the Discord bot.
# Pulls DISCORD_BOT_TOKEN from the user environment.

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "bot.log"

if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 5MB)) {
    Move-Item -Force $logFile "$logFile.1"
}

if (-not $env:DISCORD_BOT_TOKEN) {
    $env:DISCORD_BOT_TOKEN = [System.Environment]::GetEnvironmentVariable("DISCORD_BOT_TOKEN", "User")
}
$env:PYTHONIOENCODING = "utf-8"

$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

# Long-running. Append to log; Task Scheduler keeps the process alive.
& $pythonExe "src\bot.py" *>> $logFile
exit $LASTEXITCODE
