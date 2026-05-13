# Wrapper invoked by Windows Task Scheduler to launch the Discord bot.
#
# Supervises the bot in a restart loop with exponential backoff: if the Python
# process exits (crash, OOM, unhandled exception), we wait briefly and respawn.
# Cap: 6 restarts per rolling 1h window — after that we exit and let Task
# Scheduler take over (it's configured to re-run the task on failure).

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root "logs"
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "bot.log"

function Append-Log([string]$msg) {
    "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] $msg" | Out-File -Append -Encoding utf8 $logFile
}

if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 5MB)) {
    Move-Item -Force $logFile "$logFile.1"
}

$env:PYTHONIOENCODING = "utf-8"

$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) { $pythonExe = "python" }

$maxRestartsPerHour = 6
$restarts = 0
$windowStart = Get-Date

Append-Log "supervisor: starting (pid=$PID)"

while ($true) {
    Append-Log "supervisor: launching bot"
    # Python writes the bot.log directly via FileHandler (UTF-8). Discard the
    # bot's own stdout/stderr — anything that escapes the logger ends up in
    # supervisor entries via $LASTEXITCODE only.
    & $pythonExe "src\bot.py" 2>$null | Out-Null
    $exit = $LASTEXITCODE
    Append-Log "supervisor: bot exited code=$exit"

    if (((Get-Date) - $windowStart).TotalHours -ge 1) {
        $restarts = 0
        $windowStart = Get-Date
    }
    $restarts++
    if ($restarts -gt $maxRestartsPerHour) {
        Append-Log "supervisor: hit $maxRestartsPerHour restarts in 1h, giving up"
        exit 1
    }

    $backoff = [Math]::Min(60, [Math]::Pow(2, $restarts))
    Append-Log "supervisor: restart #$restarts in ${backoff}s"
    Start-Sleep -Seconds $backoff
}
