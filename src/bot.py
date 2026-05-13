"""Discord slash-command bot for on-demand Riftbound price lookups.

Slash commands:
  /price <query>   query = card name (e.g. "ahri") or TCGplayer product ID

Requires the DISCORD_BOT_TOKEN environment variable. Card metadata is loaded
from data/cards.json (kept fresh by scripts/run-refresh.ps1 once a day).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import discord
import requests
from discord import app_commands

from tcgplayer import _session, fetch_latest_sales, fetch_product, image_url

ROOT = Path(__file__).resolve().parents[1]
CARDS_PATH = ROOT / "data" / "cards.json"

TOKEN_ENV = "DISCORD_BOT_TOKEN"
MAX_MULTI_MATCH = 8
EMBED_COLOR_OK = 0x2ECC71
EMBED_COLOR_INFO = 0x3498DB
EMBED_COLOR_MISS = 0xE74C3C
TCGPLAYER_PRODUCT_URL = "https://www.tcgplayer.com/product/{product_id}"


# ---------- Card index ---------------------------------------------------

def load_cards() -> list[dict]:
    if not CARDS_PATH.exists():
        return []
    return json.loads(CARDS_PATH.read_text(encoding="utf-8"))


def find_cards(query: str, cards: list[dict]) -> list[dict]:
    """Match by product ID (exact, if all digits) or by name substring."""
    q = query.strip()
    if not q:
        return []
    if q.isdigit():
        pid = int(q)
        return [c for c in cards if c["product_id"] == pid]
    needle = q.lower()
    return [c for c in cards if c.get("name") and needle in c["name"].lower()]


# ---------- Embeds -------------------------------------------------------

def _money(v) -> str:
    return f"${v:.2f}" if isinstance(v, (int, float)) else "—"


def _parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_no_match_embed(query: str) -> discord.Embed:
    return discord.Embed(
        title="No match",
        description=(
            f"No Riftbound card found for `{query}`.\n\n"
            f"Try a partial name (e.g. `ahri`) or a TCGplayer product ID "
            f"(e.g. `653053`)."
        ),
        color=EMBED_COLOR_MISS,
    )


def build_multi_match_embed(query: str, matches: list[dict]) -> discord.Embed:
    shown = matches[:MAX_MULTI_MATCH]
    overflow = max(len(matches) - len(shown), 0)
    lines = []
    for c in shown:
        pid = c["product_id"]
        url = TCGPLAYER_PRODUCT_URL.format(product_id=pid)
        line = (
            f"[`{pid}`]({url}) — **{c.get('name', '?')}** "
            f"· {c.get('set_name') or '—'} · {c.get('rarity') or '—'} "
            f"· {_money(c.get('market_price'))}"
        )
        lines.append(line)
    title = f"{len(matches)} match{'es' if len(matches) != 1 else ''} for `{query}`"
    description = "\n".join(lines)
    if overflow:
        description += f"\n\n… and **{overflow}** more. Refine your query, or pass a TCGplayer product ID."
    else:
        description += "\n\nUse the product ID for a detailed lookup."
    return discord.Embed(
        title=title,
        description=description,
        color=EMBED_COLOR_INFO,
    )


def _trend_arrow(recent_avg: float | None, market: float | None) -> str:
    if recent_avg is None or market is None:
        return ""
    if market <= 0:
        return ""
    delta = (recent_avg - market) / market
    if delta >= 0.05:
        return f"↑ +{delta * 100:.0f}% vs market"
    if delta <= -0.05:
        return f"↓ {delta * 100:.0f}% vs market"
    return f"~ flat vs market ({delta * 100:+.0f}%)"


def build_price_embed(card: dict, live: dict | None, sales: list[dict]) -> discord.Embed:
    pid = card["product_id"]
    name = card.get("name") or f"Product {pid}"
    set_name = (live and live.get("setName")) or card.get("set_name") or "—"
    rarity = (live and live.get("rarityName")) or card.get("rarity") or "—"
    market = (live and live.get("marketPrice")) or card.get("market_price")
    low = (live and live.get("lowestPrice")) or card.get("lowest_price")
    listings = live and live.get("totalListings")
    number = card.get("number")

    # Sales summary
    recent_lines: list[str] = []
    prices: list[float] = []
    for s in sales[:5]:
        ts = _parse_dt(s.get("orderDate", ""))
        when = ts.strftime("%m-%d %H:%M") if ts else "?"
        qty = s.get("quantity")
        price = s.get("purchasePrice")
        variant = s.get("variant") or "Normal"
        if isinstance(price, (int, float)):
            prices.append(float(price))
        recent_lines.append(
            f"• `{when}` · qty **{qty}** @ {_money(price)} · {variant}"
        )
    avg_price = sum(prices) / len(prices) if prices else None
    trend = _trend_arrow(avg_price, market)

    description_lines = [
        f"**{set_name}** · {rarity}"
        + (f" · #{number}" if number else ""),
        "",
        f"💰 Market **{_money(market)}** · Low **{_money(low)}**"
        + (f" · {listings} listings" if listings else ""),
    ]
    if recent_lines:
        description_lines.append("")
        description_lines.append("**Recent sales (latest 5):**")
        description_lines.extend(recent_lines)
        if avg_price is not None:
            description_lines.append(
                f"\nAvg: **{_money(avg_price)}**"
                + (f" · {trend}" if trend else "")
            )
    else:
        description_lines.append("")
        description_lines.append("_No recent sales on TCGplayer._")

    embed = discord.Embed(
        title=name,
        url=TCGPLAYER_PRODUCT_URL.format(product_id=pid),
        description="\n".join(description_lines),
        color=EMBED_COLOR_OK,
    )
    embed.set_thumbnail(url=image_url(pid))
    embed.set_footer(text=f"TCGplayer #{pid} · data as of {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}")
    return embed


# ---------- Bot ----------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("riftbound-bot")


class PriceBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.cards: list[dict] = []
        self.session: requests.Session | None = None

    async def setup_hook(self) -> None:
        self.cards = load_cards()
        log.info("Loaded %d cards from %s", len(self.cards), CARDS_PATH)
        # Warm session in a thread so the bot doesn't block on TCGplayer's
        # homepage during startup.
        self.session = await asyncio.to_thread(_session)
        await self.tree.sync()
        log.info("Slash commands synced.")

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user and self.user.id)


bot = PriceBot()


def _refresh_session_if_needed(exc: Exception) -> bool:
    """If we got a 403, drop the session so the next call rewarms cookies."""
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        if exc.response.status_code == 403:
            bot.session = None
            return True
    return False


async def _fetch_live(card: dict) -> tuple[dict | None, list[dict]]:
    """Pull live product info + recent sales for one card, in a worker thread."""
    pid = card["product_id"]
    if bot.session is None:
        bot.session = await asyncio.to_thread(_session)
    try:
        live = await asyncio.to_thread(fetch_product, pid, bot.session)
        sales = await asyncio.to_thread(fetch_latest_sales, pid, 5, bot.session)
        return live, sales
    except requests.HTTPError as e:
        if _refresh_session_if_needed(e):
            # one retry with fresh cookies
            bot.session = await asyncio.to_thread(_session)
            live = await asyncio.to_thread(fetch_product, pid, bot.session)
            sales = await asyncio.to_thread(fetch_latest_sales, pid, 5, bot.session)
            return live, sales
        raise


@bot.tree.command(name="price", description="Look up Riftbound card price + recent sales")
@app_commands.describe(query="Card name (e.g. ahri) or TCGplayer product ID (e.g. 653053)")
async def price_cmd(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer(thinking=True)
    if not bot.cards:
        bot.cards = load_cards()
    matches = find_cards(query, bot.cards)
    if not matches:
        await interaction.followup.send(embed=build_no_match_embed(query))
        return
    if len(matches) > 1:
        await interaction.followup.send(
            embed=build_multi_match_embed(query, matches)
        )
        return
    card = matches[0]
    try:
        live, sales = await _fetch_live(card)
    except requests.RequestException as e:
        log.exception("Live fetch failed for %s", card.get("product_id"))
        await interaction.followup.send(
            embed=discord.Embed(
                title="TCGplayer lookup failed",
                description=f"Couldn't reach TCGplayer for `{card['product_id']}`: {e}",
                color=EMBED_COLOR_MISS,
            )
        )
        return
    await interaction.followup.send(embed=build_price_embed(card, live, sales))


@bot.tree.command(name="ping", description="Health check")
async def ping_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.send_message(
        f"pong · {len(bot.cards)} cards indexed · "
        f"latency {bot.latency * 1000:.0f} ms",
        ephemeral=True,
    )


def main() -> int:
    token = os.environ.get(TOKEN_ENV)
    if not token:
        print(f"Set {TOKEN_ENV} to your Discord bot token.", file=sys.stderr)
        return 1
    bot.run(token, log_handler=None)
    return 0


if __name__ == "__main__":
    sys.exit(main())
