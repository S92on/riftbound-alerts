# Wrapper invoked by Windows Task Scheduler to run the signal scan.
# Reads DISCORD_WEBHOOK_URL from the user environment (set during install).
# Writes a rotating log to logs\signals.log.

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "signals.log"

# Cap log size at ~2 MB; rotate to .1 when exceeded.
if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 2MB)) {
    Move-Item -Force $logFile "$logFile.1"
}

$timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
"`n===== $timestamp =====" | Out-File -Append -Encoding utf8 $logFile

# Ensure Python sees the webhook URL even if launched without user profile.
if (-not $env:DISCORD_WEBHOOK_URL) {
    $env:DISCORD_WEBHOOK_URL = [System.Environment]::GetEnvironmentVariable("DISCORD_WEBHOOK_URL", "User")
}
$env:PYTHONIOENCODING = "utf-8"

# Use the project-local venv so Task Scheduler isn't dependent on user PATH
# or user site-packages (APPDATA may be unset in its env).
$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

& $pythonExe "src\check_signals.py" *>&1 | Out-File -Append -Encoding utf8 $logFile
$exit = $LASTEXITCODE
"exit=$exit" | Out-File -Append -Encoding utf8 $logFile
exit $exit
