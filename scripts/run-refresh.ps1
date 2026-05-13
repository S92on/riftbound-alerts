# Wrapper invoked by Windows Task Scheduler to refresh the Riftbound card list.

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "refresh.log"

if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 1MB)) {
    Move-Item -Force $logFile "$logFile.1"
}

$timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
"`n===== $timestamp =====" | Out-File -Append -Encoding utf8 $logFile

$env:PYTHONIOENCODING = "utf-8"

$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

& $pythonExe "src\refresh_cards.py" *>&1 | Out-File -Append -Encoding utf8 $logFile
$exit = $LASTEXITCODE
"exit=$exit" | Out-File -Append -Encoding utf8 $logFile
exit $exit
