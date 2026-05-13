# Riftbound Market Alerts

Self-hosted Discord alerts for Riftbound TCG (League of Legends Trading Card Game).
Polls TCGplayer's public sales feed every 30 minutes, detects "Deck Identity"
buying activity, and posts an embed to your Discord webhook — matching the
look of [Magical Meta](https://magicalmeta.ink/riftbound)'s alerts.

> **Runs on your Windows PC via Task Scheduler.** TCGplayer's WAF blocks GitHub
> Actions runner IPs and rate-limits any caller that bursts >100 requests
> quickly, so we scan in rotating 100-card batches from a residential IP.

## How it works

1. **`src/refresh_cards.py`** (daily) — pulls every Riftbound card from
   TCGplayer's search API into `data/cards.json` (~1,100 cards).
2. **`src/check_signals.py`** (every 30 min) — scans a rolling **batch of 100
   cards** per run (cursor stored in `state.json`), fetches each card's 5 most
   recent sales, and merges them into `data/sales_log.json` (deduped by
   timestamp, pruned to a 7-day window). The full library is covered every
   ~6 hours; small batches stay under TCGplayer's WAF rate threshold.
3. **Signal**: a card fires an alert when it clears **≥100 copies sold in 7d**
   and **≥2.5 avg copies per transaction**. A 7-day cooldown is recorded in
   `data/state.json` so the same card doesn't re-fire.

Why polling? TCGplayer's public sales endpoint returns only the ~5 latest sales
per product — to get a real 7-day window you have to accumulate locally. After
~24–48h of running, the log has enough history for accurate signals.

## Setup (one-time)

### 1. Create a Discord webhook

In your Discord server: **channel → cog → Integrations → Webhooks → New Webhook**.
Pick the alert channel, copy the URL, treat it like a secret.

### 2. Clone and install

```powershell
git clone https://github.com/<you>/riftbound-alerts.git C:\riftbound-alerts
cd C:\riftbound-alerts
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
```

### 3. Store the webhook URL as a user environment variable

```powershell
[System.Environment]::SetEnvironmentVariable(
    "DISCORD_WEBHOOK_URL",
    "https://discord.com/api/webhooks/...",
    "User"
)
```

### 4. Smoke-test the webhook

```powershell
$env:DISCORD_WEBHOOK_URL = [System.Environment]::GetEnvironmentVariable("DISCORD_WEBHOOK_URL","User")
.\.venv\Scripts\python.exe src\test_alert.py
```

A sample "Deck Identity Alert" should appear in your Discord channel.

### 5. Install the scheduled tasks

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-tasks.ps1
```

This registers two tasks under your user account (no admin needed):

| Task | Cadence | What it does |
| --- | --- | --- |
| `Riftbound-Alerts-Signals` | Every 30 min | Polls TCGplayer, fires alerts |
| `Riftbound-Alerts-Refresh` | Daily at 09:00 | Refreshes the card list |

### 6. Run once manually to verify

```powershell
Start-ScheduledTask -TaskName "Riftbound-Alerts-Signals"
Get-Content .\logs\signals.log -Wait
```

Look for `Done. scanned=100 ...`. Each run takes ~2 minutes (100 cards × 1s).
Subsequent runs rotate through the next 100 cards; the full library is covered
every ~6 hours.

## Tuning

Edit `src/check_signals.py`:

| Constant | Default | Meaning |
| --- | --- | --- |
| `MIN_SOLD_7D` | `100` | Copies sold in last 7 days |
| `MIN_AVG_COPIES` | `2.5` | Average copies per transaction (deck breadth) |
| `ALERT_COOLDOWN_DAYS` | `7` | Don't re-alert the same card for this many days |
| `PER_REQUEST_DELAY` | `1.0` | Seconds between TCGplayer requests |
| `BATCH_SIZE` | `100` | Cards scanned per run (smaller = safer vs. WAF) |

Lower the thresholds for quieter cards / earlier detection. Raise them for
fewer but stronger signals.

## Project layout

```
.
├── scripts/
│   ├── install-tasks.ps1      # one-shot installer (registers scheduled tasks)
│   ├── run-signals.ps1        # wrapper called by Task Scheduler
│   └── run-refresh.ps1        # wrapper called by Task Scheduler
├── src/
│   ├── tcgplayer.py           # TCGplayer API wrappers
│   ├── refresh_cards.py       # daily card-list refresh
│   ├── sales_log.py           # accumulating sales window + signal math
│   ├── check_signals.py       # main entrypoint
│   ├── discord_webhook.py     # embed builder + poster
│   └── test_alert.py          # one-shot webhook smoke test
├── data/
│   ├── cards.json             # Riftbound product metadata
│   ├── sales_log.json         # 7-day rolling sales window
│   └── state.json             # alert cooldowns
├── logs/                      # rolling logs (gitignored)
├── requirements.txt
└── README.md
```

## Operations

```powershell
# Inspect tasks
Get-ScheduledTask "Riftbound-Alerts-*" | Format-Table TaskName, State

# Tail the live log
Get-Content .\logs\signals.log -Wait

# Force a run
Start-ScheduledTask "Riftbound-Alerts-Signals"

# Pause alerts
Disable-ScheduledTask "Riftbound-Alerts-Signals"

# Uninstall
Unregister-ScheduledTask "Riftbound-Alerts-Signals" -Confirm:$false
Unregister-ScheduledTask "Riftbound-Alerts-Refresh" -Confirm:$false
```

## Troubleshooting

- **No alerts after a day** — most cards don't clear the thresholds. Run the
  smoke test (`src/test_alert.py`) to confirm the webhook works, then consider
  lowering `MIN_SOLD_7D` to ~50 while the log fills out.
- **`ModuleNotFoundError: requests`** — the venv is missing. Recreate with
  `python -m venv .venv && .\.venv\Scripts\pip install -r requirements.txt`.
- **HTTP 403 from TCGplayer** — your IP is being rate-limited. Raise
  `PER_REQUEST_DELAY` to `0.8` and wait an hour for the block to clear.
- **Task didn't fire** — Task Scheduler only runs tasks while the user is
  logged in. Leave the PC awake, or use **Settings → System → Power & battery**
  to prevent sleep on AC power.
