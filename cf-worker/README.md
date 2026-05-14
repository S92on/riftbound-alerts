# Riftbound Bot — Cloudflare Workers edition

24/7 free Discord bot for Riftbound TCG. Same features as the Python version:
`/price`, `/top`, `/heat`, `/digest`, `/setdigest`, `/watch`, `/unwatch`,
`/watchlist`, `/ping` — plus autocomplete, USD↔THB, magicalmeta trend
enrichment, daily digest, and DM alerts on watchlist moves.

Runs entirely on Cloudflare's free tier:

- **Workers** (100 k req/day, plenty)
- **Workers KV** (cards, watchlists, config, MM cache)
- **Cron Triggers** (Magical Meta refresh, daily digest, watchlist check, card refresh)

No Discord Gateway — uses Discord's HTTP Interactions endpoint instead, so the
bot is fully serverless. Your PC can be off.

## One-time setup

### 1. Prerequisites

```powershell
node -v           # v18 or newer
npm i -g wrangler # global wrangler CLI (or use `npx wrangler` everywhere)
```

You also need a free Cloudflare account: <https://dash.cloudflare.com/sign-up>.

### 2. Clone + install

```powershell
cd C:\riftbound-alerts\cf-worker
npm install
```

### 3. Cloudflare login

```powershell
wrangler login    # opens a browser tab; pick the Cloudflare account
```

### 4. Create the four KV namespaces

```powershell
wrangler kv namespace create CARDS
wrangler kv namespace create WATCHLISTS
wrangler kv namespace create CONFIG
wrangler kv namespace create MMCACHE
```

Each command prints an `id = "..."` line. Paste those IDs into `wrangler.toml`
in place of the four `REPLACE_WITH_*` placeholders.

### 5. Set Discord secrets

From the [Discord Developer Portal](https://discord.com/developers/applications):

- **Application ID** → General Information → Application ID
- **Public Key** → General Information → Public Key
- **Bot Token** → Bot → Reset Token (used by cron jobs only)

```powershell
wrangler secret put DISCORD_APPLICATION_ID
wrangler secret put DISCORD_PUBLIC_KEY
wrangler secret put DISCORD_TOKEN
```

### 6. Register slash commands (per guild, instant)

Create a `.dev.vars` file in `cf-worker/`:

```ini
DISCORD_APPLICATION_ID=...
DISCORD_TOKEN=...
DISCORD_GUILD_ID=...   # right-click your server → Copy Server ID (needs Developer Mode)
```

Then:

```powershell
npm run register
```

### 7. Upload the card catalogue

The bot needs Riftbound card metadata in KV. The easiest path is to reuse
the file the Python pipeline already produces at `..\data\cards.json`:

```powershell
npm run upload-cards
```

Once running in Workers, the daily cron at 03:30 UTC will refresh the
catalogue automatically from TCGplayer.

### 8. Deploy

```powershell
npm run deploy
```

Wrangler prints a public URL like `https://riftbound-bot.<your-subdomain>.workers.dev`.

### 9. Point Discord at the Worker

Discord Developer Portal → your application → **General Information** →
**Interactions Endpoint URL** → paste your Worker URL → Save.

Discord sends a PING to verify; the Worker replies PONG and Discord accepts.
Test in your server: `/heat`, `/price ahri`, `/top 7d gainers`.

## Operations

| Task | Command |
| --- | --- |
| Tail live logs | `npm run tail` |
| Re-deploy | `npm run deploy` |
| Re-register commands | `npm run register` |
| Re-upload cards from local | `npm run upload-cards` |
| Inspect a KV value | `wrangler kv key get --binding=CONFIG digest_channel_id` |

## Cron schedule

UTC (wrangler.toml `crons`):

| Cron | Job |
| --- | --- |
| `*/30 * * * *` | Refresh Magical Meta `summary.json` into MMCACHE |
| `15 * * * *`   | Check every user's watchlist, DM on threshold cross |
| `0 2 * * *`    | 09:00 Asia/Bangkok daily digest to `digest_channel_id` |
| `30 3 * * *`   | Refresh Riftbound card catalogue from TCGplayer |
