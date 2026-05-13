# Riftbound Price Bot

On-demand Discord slash-command bot for Riftbound TCG (League of Legends
Trading Card Game) prices. Type `/price <name or product #>` in any channel
the bot can see; the bot replies with market price, low/listings, and the
five most recent sales pulled live from TCGplayer.

> Runs on your Windows PC. The bot starts at user logon via Task Scheduler
> and stays online while the PC is awake.

## Commands

| Command | Example | What it does |
| --- | --- | --- |
| `/price <query>` | `/price ahri` | Search by name. If multiple matches, lists the top 8 with prices. |
| `/price <query>` | `/price 653053` | Exact lookup by TCGplayer product ID — returns full embed with recent sales. |
| `/ping` | `/ping` | Health check: card count + bot latency. |

The reply embed shows:
- Set, rarity, card number, thumbnail
- Live market price, lowest active listing, listing count
- Last 5 sales with date, quantity, price, variant
- Average of those sales + a `↑ / ↓ / ~` trend arrow vs market
- Direct link to the TCGplayer product page

## How it works

```
+-----------------+      slash command       +---------------------+
| Discord client  | -----------------------> | discord.py gateway  |
+-----------------+                          |    (src/bot.py)     |
                                             |                     |
+-----------------+   live product + sales   |   TCGplayer API     |
| data/cards.json | <----------------------- |   (mp-search-api,   |
| (daily refresh) |                          |    mpapi/latestsales)|
+-----------------+                          +---------------------+
```

`data/cards.json` is a local index of every Riftbound product on TCGplayer
(~1,100 cards), refreshed once a day. Slash commands match against it for
name/ID resolution, then hit the live endpoints for current pricing.

## Setup (one-time)

### 1. Create a Discord bot application

- https://discord.com/developers/applications → **New Application**
- **Bot** tab → **Reset Token** → copy the token (starts with `MT…`)
- **Installation** tab:
  - Default Install Settings → Guild Install
  - Scopes: `bot`, `applications.commands`
  - Permissions: `Send Messages`, `Use Slash Commands`
- Copy the **Install Link** → open in browser → invite the bot to your server

### 2. Clone, install, configure

```powershell
git clone https://github.com/<you>/riftbound-alerts.git C:\riftbound-alerts
cd C:\riftbound-alerts
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

[System.Environment]::SetEnvironmentVariable(
    "DISCORD_BOT_TOKEN", "<paste token>", "User"
)
```

### 3. Install the scheduled tasks

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\install-tasks.ps1
```

Registers two tasks under your user (no admin needed):

| Task | Trigger | What it does |
| --- | --- | --- |
| `Riftbound-Bot` | At logon | Starts the Discord bot daemon |
| `Riftbound-Refresh-Cards` | Daily 09:00 | Refreshes `data/cards.json` |

### 4. Start the bot now (don't wait for next logon)

```powershell
Start-ScheduledTask -TaskName "Riftbound-Bot"
Get-Content .\logs\bot.log -Wait
```

Look for `Slash commands synced.` and `Logged in as <bot> (id=…)`. In Discord,
type `/` in any channel — the bot's commands should appear.

## Operations

```powershell
# Inspect tasks
Get-ScheduledTask "Riftbound-*" | Format-Table TaskName, State

# Tail logs
Get-Content .\logs\bot.log -Wait

# Restart the bot
Stop-ScheduledTask  "Riftbound-Bot"
Start-ScheduledTask "Riftbound-Bot"

# Pause the bot
Disable-ScheduledTask "Riftbound-Bot"

# Refresh the card list manually
Start-ScheduledTask "Riftbound-Refresh-Cards"

# Uninstall
Unregister-ScheduledTask "Riftbound-Bot"           -Confirm:$false
Unregister-ScheduledTask "Riftbound-Refresh-Cards" -Confirm:$false
```

## Project layout

```
.
├── scripts/
│   ├── install-tasks.ps1      # registers the two scheduled tasks
│   ├── run-bot.ps1            # wrapper invoked At-Logon
│   └── run-refresh.ps1        # wrapper invoked daily
├── src/
│   ├── tcgplayer.py           # TCGplayer API wrappers (cookie warmup, search, latestsales)
│   ├── refresh_cards.py       # daily card-list refresh
│   └── bot.py                 # Discord slash-command bot
├── data/
│   └── cards.json             # Riftbound product metadata (~1,100 items)
├── logs/                      # rolling logs (gitignored)
├── requirements.txt
└── README.md
```

## Troubleshooting

- **Slash commands don't appear in Discord** — the bot needs `applications.commands`
  scope in the invite URL. Re-invite from Developer Portal → Installation.
- **`Improper token has been passed`** — the `DISCORD_BOT_TOKEN` env var isn't set,
  or the token was rotated. Reset under Bot tab → repeat step 2.
- **`/price` returns `Couldn't reach TCGplayer`** — your IP is rate-limited.
  The bot transparently retries once with a fresh cookie session; if the second
  attempt still fails, wait a few minutes.
- **Bot is offline in Discord** — your PC is asleep or the task was disabled.
  Wake the PC; the At-Logon trigger reconnects automatically.
