# Riftbound Market Alerts

Self-hosted Discord alerts for Riftbound TCG (League of Legends Trading Card Game).
Polls TCGplayer's public sales feed, detects "Deck Identity" buying activity, and
posts an embed to your Discord webhook — matching the look of
[Magical Meta](https://magicalmeta.ink/riftbound)'s alerts.

## How it works

1. **`src/refresh_cards.py`** (daily) — pulls every Riftbound card from TCGplayer's
   search API and caches metadata in `data/cards.json`.
2. **`src/check_signals.py`** (every 30 min) — for each card, fetches the 5 most
   recent sales and merges them into `data/sales_log.json` (deduped by timestamp,
   pruned to the last 7 days).
3. **Signal**: when a card clears **≥100 copies sold in 7d** and **≥2.5 avg copies
   per transaction**, it posts a Discord embed and records a 7-day cooldown in
   `data/state.json` so the same card doesn't re-fire.

Why polling? TCGplayer's public sales endpoint only returns the ~5 latest sales
per product — to get a real 7-day window you have to accumulate locally. After
~24–48h of running, the log has enough history for accurate signals.

## Setup

### 1. Create a Discord webhook

In your server: **Server Settings → Integrations → Webhooks → New Webhook**.
Pick the channel (e.g. `#riftbound-alerts`), copy the URL, treat it like a secret.

### 2. Push this folder to GitHub

```bash
cd C:\riftbound-alerts
git init
git add .
git commit -m "init: riftbound alerts"
git branch -M main
# Create an empty repo on github.com first, then:
git remote add origin git@github.com:<you>/<repo>.git
git push -u origin main
```

**Tip:** make the repo **public** to get unlimited GitHub Actions minutes.
A private repo will burn ~5,700 free minutes/month at the default 30-min cron
(well over the 2,000-minute free tier).

### 3. Add the webhook as a repo secret

GitHub → repo → **Settings → Secrets and variables → Actions → New repository
secret**:

- Name: `DISCORD_WEBHOOK_URL`
- Value: the Discord webhook URL from step 1

### 4. Run the first card refresh

In GitHub: **Actions → "Refresh Riftbound card list" → Run workflow**. Wait ~30s.
This populates `data/cards.json` (~1,100 cards). After that, the signal scanner
runs automatically every 30 minutes.

### 5. (Optional) Smoke-test the webhook locally

```bash
pip install -r requirements.txt
$env:DISCORD_WEBHOOK_URL = "https://discord.com/api/webhooks/..."
python src/test_alert.py
```

You should see a sample Ahri "Deck Identity Alert" embed appear in your channel.

## Tuning

Edit `src/check_signals.py`:

| Constant | Default | Meaning |
| --- | --- | --- |
| `MIN_SOLD_7D` | `100` | Copies sold in last 7 days |
| `MIN_AVG_COPIES` | `2.5` | Average copies per transaction (deck breadth) |
| `ALERT_COOLDOWN_DAYS` | `7` | Don't re-alert the same card for this many days |
| `PER_REQUEST_DELAY` | `0.4` | Seconds between TCGplayer requests (polite) |

Lower the thresholds for quieter cards / earlier detection. Raise them for fewer
but stronger signals.

## Project layout

```
.
├── .github/workflows/
│   ├── check-signals.yml      # cron every 30 min
│   └── refresh-cards.yml      # cron daily
├── data/
│   ├── cards.json             # all Riftbound product metadata
│   ├── sales_log.json         # 7-day rolling sales window
│   └── state.json             # alert cooldowns
├── src/
│   ├── tcgplayer.py           # TCGplayer API wrappers
│   ├── refresh_cards.py       # daily card-list refresh
│   ├── sales_log.py           # accumulating sales window + signal math
│   ├── check_signals.py       # main entrypoint (cron)
│   ├── discord_webhook.py     # embed builder + poster
│   └── test_alert.py          # one-shot webhook test
├── requirements.txt
└── README.md
```

## Troubleshooting

- **No alerts after a day** — most cards don't clear the thresholds. Try the test
  script (step 5) to confirm the webhook works, then lower `MIN_SOLD_7D` to ~50
  to see more signals while the log fills out.
- **GitHub Actions push conflicts** — the workflow retries 3 times with backoff.
  If it still fails, re-run the job manually.
- **403 from TCGplayer** — rate limiting. Raise `PER_REQUEST_DELAY` to `0.6`.
