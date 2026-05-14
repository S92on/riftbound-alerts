// One-shot: PUT the command list to Discord, scoped to a single guild for
// instant propagation (global takes up to 1h). Run with `npm run register`.
//
// Requires env vars (read from .dev.vars or shell):
//   DISCORD_APPLICATION_ID
//   DISCORD_TOKEN
//   DISCORD_GUILD_ID

import fs from "node:fs";
import path from "node:path";

function loadDevVars(): Record<string, string> {
  const out: Record<string, string> = { ...process.env } as Record<string, string>;
  const p = path.join(process.cwd(), ".dev.vars");
  if (fs.existsSync(p)) {
    for (const line of fs.readFileSync(p, "utf8").split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
      if (!m) continue;
      let v = m[2];
      if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
        v = v.slice(1, -1);
      }
      out[m[1]] = v;
    }
  }
  return out;
}

const env = loadDevVars();
const APP_ID = env.DISCORD_APPLICATION_ID;
const TOKEN = env.DISCORD_TOKEN;
const GUILD_ID = env.DISCORD_GUILD_ID;
if (!APP_ID || !TOKEN || !GUILD_ID) {
  console.error("Missing DISCORD_APPLICATION_ID / DISCORD_TOKEN / DISCORD_GUILD_ID");
  process.exit(1);
}

const RANGE_CHOICES = [
  { name: "24h",  value: "h24" },
  { name: "7d",   value: "d7" },
  { name: "30d",  value: "d30" },
  { name: "60d",  value: "d60" },
  { name: "90d",  value: "d90" },
  { name: "180d", value: "d180" },
  { name: "1y",   value: "y1" },
];

const KIND_CHOICES = [
  { name: "📈 Gainers", value: "gainers" },
  { name: "📉 Losers",  value: "losers" },
  { name: "🔥 Sellers", value: "sellers" },
];

const commands = [
  { name: "ping", description: "Health check" },
  {
    name: "price",
    description: "Look up Riftbound card price + recent sales + trend",
    options: [{ name: "query", description: "Card name or TCGplayer product ID", type: 3, required: true, autocomplete: true }],
  },
  {
    name: "top",
    description: "Top movers / sellers across the Riftbound market",
    options: [
      { name: "range", description: "Time range", type: 3, required: true, choices: RANGE_CHOICES },
      { name: "kind",  description: "What to rank by", type: 3, required: true, choices: KIND_CHOICES },
    ],
  },
  { name: "heat",      description: "Market direction, heat counts, totals" },
  { name: "setdigest", description: "Use this channel for the 09:00 Bangkok daily digest" },
  { name: "digest",    description: "Post the 7-day digest right now (manual trigger)" },
  {
    name: "watch",
    description: "Add a card to your watchlist (DM alert on price move)",
    options: [
      { name: "query", description: "Card name or product ID", type: 3, required: true, autocomplete: true },
      { name: "threshold_pct", description: "Alert when |% change| ≥ this (default 10)", type: 10, required: false, min_value: 1, max_value: 100 },
    ],
  },
  {
    name: "unwatch",
    description: "Remove a card from your watchlist",
    options: [{ name: "query", description: "Card name or product ID", type: 3, required: true, autocomplete: true }],
  },
  { name: "watchlist", description: "Show your current watchlist" },
];

async function main() {
  const url = `https://discord.com/api/v10/applications/${APP_ID}/guilds/${GUILD_ID}/commands`;
  const r = await fetch(url, {
    method: "PUT",
    headers: { Authorization: `Bot ${TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify(commands),
  });
  if (!r.ok) {
    console.error(`Registration failed: ${r.status} ${await r.text()}`);
    process.exit(1);
  }
  const arr = (await r.json()) as Array<{ name: string }>;
  console.log(`Registered ${arr.length} commands to guild ${GUILD_ID}:`);
  for (const c of arr) console.log(`  /${c.name}`);
}
main();
