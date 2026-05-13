"""Discord slash-command bot for Riftbound TCG prices + market trends.

Commands:
  /price <query>              — live price + 5 recent sales + trend (Magical Meta)
  /top <range> <kind>         — top movers / sellers across 7 time ranges
  /heat                       — market direction + heat counts
  /watch <query> [threshold]  — add to your personal watchlist
  /unwatch <query>            — remove from your watchlist
  /watchlist                  — show your current watchlist
  /setdigest                  — designate this channel for the 09:00 Bangkok daily digest
  /digest                     — post the daily digest right now (manual trigger)
  /ping                       — health check

Token from Windows Credential Manager (service=riftbound-bot, user=discord_token),
or env var DISCORD_BOT_TOKEN as a fallback. Card metadata is loaded from
data/cards.json (kept fresh by scripts/run-refresh.ps1).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any

import discord
import requests
from discord import app_commands
from discord.ext import tasks

from magicalmeta import KINDS, RANGE_LABEL, RANGES, mm
from tcgplayer import _session, fetch_latest_sales, fetch_product, image_url

ROOT = Path(__file__).resolve().parents[1]
CARDS_PATH = ROOT / "data" / "cards.json"
CONFIG_PATH = ROOT / "data" / "config.json"
WATCHLISTS_PATH = ROOT / "data" / "watchlists.json"

TOKEN_ENV = "DISCORD_BOT_TOKEN"
KEYRING_SERVICE = "riftbound-bot"
KEYRING_USERNAME = "discord_token"

MAX_MULTI_MATCH = 8
EMBED_COLOR_OK = 0x2ECC71
EMBED_COLOR_INFO = 0x3498DB
EMBED_COLOR_MISS = 0xE74C3C
EMBED_COLOR_WARN = 0xF39C12

TCGPLAYER_PRODUCT_URL = "https://www.tcgplayer.com/product/{product_id}"

# Bangkok timezone (UTC+7). discord.py tasks.loop wants a tzinfo, so we hand it
# this rather than using the system local time which may not be Bangkok.
BANGKOK = timezone(timedelta(hours=7))
DIGEST_TIME_LOCAL = dtime(hour=9, minute=0, tzinfo=BANGKOK)

# USD→THB FX (ECB rate, cached 1h)
FX_URL = "https://api.frankfurter.app/latest?from=USD&to=THB"
FX_TTL_SECONDS = 3600
_fx_cache: dict[str, tuple[float, float]] = {}

# Watchlist tuning
WATCHLIST_DEFAULT_THRESHOLD_PCT = 10.0
WATCHLIST_CHECK_INTERVAL_MINUTES = 60

# ---------- Logging ------------------------------------------------------

_LOG_PATH = ROOT / "logs" / "bot.log"
_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[logging.FileHandler(_LOG_PATH, encoding="utf-8")],
)
log = logging.getLogger("riftbound-bot")


def _log_unhandled(exc_type, exc, tb) -> None:
    log.critical("UNCAUGHT EXCEPTION → bot exiting", exc_info=(exc_type, exc, tb))


sys.excepthook = _log_unhandled


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


# ---------- FX -----------------------------------------------------------

def get_thb_rate() -> float | None:
    cached = _fx_cache.get("THB")
    if cached and (time.time() - cached[1]) < FX_TTL_SECONDS:
        return cached[0]
    try:
        r = requests.get(FX_URL, timeout=10)
        r.raise_for_status()
        rate = float(r.json()["rates"]["THB"])
        _fx_cache["THB"] = (rate, time.time())
        return rate
    except Exception as e:
        log.warning("FX fetch failed: %s", e)
        return cached[0] if cached else None


# ---------- Embeds -------------------------------------------------------

def _money(v: Any, thb_rate: float | None = None) -> str:
    if not isinstance(v, (int, float)):
        return "—"
    s = f"${v:.2f}"
    if thb_rate:
        s += f" (฿{v * thb_rate:,.0f})"
    return s


def _parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _trend_arrow(recent_avg: float | None, market: float | None) -> str:
    if recent_avg is None or market is None or market <= 0:
        return ""
    delta = (recent_avg - market) / market
    if delta >= 0.05:
        return f"↑ +{delta * 100:.0f}% vs market"
    if delta <= -0.05:
        return f"↓ {delta * 100:.0f}% vs market"
    return f"~ flat vs market ({delta * 100:+.0f}%)"


def _pct_glyph(pct: Any) -> str:
    if not isinstance(pct, (int, float)):
        return "—"
    arrow = "↑" if pct > 0 else ("↓" if pct < 0 else "~")
    return f"{arrow} {pct:+.1f}%"


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


def build_multi_match_embed(query: str, matches: list[dict], thb_rate: float | None) -> discord.Embed:
    shown = matches[:MAX_MULTI_MATCH]
    overflow = max(len(matches) - len(shown), 0)
    lines = []
    for c in shown:
        pid = c["product_id"]
        url = TCGPLAYER_PRODUCT_URL.format(product_id=pid)
        line = (
            f"[`{pid}`]({url}) — **{c.get('name', '?')}** "
            f"· {c.get('set_name') or '—'} · {c.get('rarity') or '—'} "
            f"· {_money(c.get('market_price'), thb_rate)}"
        )
        lines.append(line)
    title = f"{len(matches)} match{'es' if len(matches) != 1 else ''} for `{query}`"
    description = "\n".join(lines)
    if overflow:
        description += f"\n\n… and **{overflow}** more. Refine your query, or pass a TCGplayer product ID."
    else:
        description += "\n\nUse the product ID for a detailed lookup, or pick from autocomplete."
    return discord.Embed(title=title, description=description, color=EMBED_COLOR_INFO)


def build_price_embed(
    card: dict, live: dict | None, sales: list[dict], thb_rate: float | None
) -> discord.Embed:
    pid = card["product_id"]
    name = card.get("name") or f"Product {pid}"
    set_name = (live and live.get("setName")) or card.get("set_name") or "—"
    rarity = (live and live.get("rarityName")) or card.get("rarity") or "—"
    market = (live and live.get("marketPrice")) or card.get("market_price")
    low = (live and live.get("lowestPrice")) or card.get("lowest_price")
    listings = live and live.get("totalListings")
    number = card.get("number")

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
            f"• `{when}` · qty **{qty}** @ {_money(price, thb_rate)} · {variant}"
        )
    avg_price = sum(prices) / len(prices) if prices else None
    arrow = _trend_arrow(avg_price, market)

    description_lines = [
        f"**{set_name}** · {rarity}" + (f" · #{number}" if number else ""),
        "",
        f"💰 Market **{_money(market, thb_rate)}** · Low **{_money(low, thb_rate)}**"
        + (f" · {listings} listings" if listings else ""),
    ]
    if recent_lines:
        description_lines.append("")
        description_lines.append("**Recent sales (latest 5):**")
        description_lines.extend(recent_lines)
        if avg_price is not None:
            description_lines.append(
                f"\nAvg: **{_money(avg_price, thb_rate)}**"
                + (f" · {arrow}" if arrow else "")
            )
    else:
        description_lines.append("")
        description_lines.append("_No recent sales on TCGplayer._")

    # ---- Magical Meta trend enrichment -------------------------------
    mm_trends = mm.trend_for(pid)
    trend_lines: list[str] = []
    for range_key in ("h24", "d7", "d30", "d90"):
        rec = mm_trends.get(range_key)
        if not rec:
            continue
        pct = rec.get("percent_change")
        qty_sold = rec.get("quantity_sold")
        avg_daily = rec.get("avg_daily_quantity_sold")
        bits = [f"**{RANGE_LABEL[range_key]}**: {_pct_glyph(pct)}"]
        if isinstance(qty_sold, (int, float)) and qty_sold:
            bits.append(f"qty {int(qty_sold)}")
        if isinstance(avg_daily, (int, float)) and avg_daily:
            bits.append(f"avg/day {avg_daily:.1f}")
        trend_lines.append(" · ".join(bits))
    if trend_lines:
        description_lines.append("")
        description_lines.append("**Trend (Magical Meta):**")
        description_lines.extend(trend_lines)

    embed = discord.Embed(
        title=name,
        url=TCGPLAYER_PRODUCT_URL.format(product_id=pid),
        description="\n".join(description_lines),
        color=EMBED_COLOR_OK,
    )
    embed.set_thumbnail(url=image_url(pid))
    footer_parts = [f"TCGplayer #{pid}", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")]
    if thb_rate:
        footer_parts.append(f"USD→THB {thb_rate:.2f}")
    if mm_trends:
        footer_parts.append("trend via magicalmeta.ink")
    embed.set_footer(text=" · ".join(footer_parts))
    return embed


def build_top_embed(range_key: str, kind: str, items: list[dict], thb_rate: float | None) -> discord.Embed:
    rng = RANGE_LABEL.get(range_key, range_key)
    kind_title = {"gainers": "📈 Top Gainers", "losers": "📉 Top Losers", "sellers": "🔥 Top Sellers"}[kind]
    if not items:
        return discord.Embed(
            title=f"{kind_title} · {rng}",
            description="_No data from Magical Meta yet — refresh in a few minutes._",
            color=EMBED_COLOR_WARN,
        )
    lines = []
    for i, it in enumerate(items[:10], 1):
        pid = it.get("product_id")
        name = it.get("name") or "?"
        set_name = it.get("set_name") or "—"
        market = it.get("market_price")
        url = TCGPLAYER_PRODUCT_URL.format(product_id=pid) if pid else None
        head = f"`{i:>2}.` [{name}]({url})" if url else f"`{i:>2}.` {name}"
        meta_bits = [set_name, _money(market, thb_rate)]
        if kind in ("gainers", "losers"):
            pct = it.get("percent_change")
            meta_bits.append(_pct_glyph(pct))
            dollar = it.get("dollar_change")
            if isinstance(dollar, (int, float)):
                meta_bits.append(f"{'+' if dollar >= 0 else ''}{_money(dollar, thb_rate)}")
        elif kind == "sellers":
            qty = it.get("quantity_sold")
            if isinstance(qty, (int, float)):
                meta_bits.append(f"qty **{int(qty)}**")
            avg = it.get("avg_daily_quantity_sold")
            if isinstance(avg, (int, float)):
                meta_bits.append(f"avg/day {avg:.1f}")
        lines.append(head + "\n   " + " · ".join(meta_bits))
    embed = discord.Embed(
        title=f"{kind_title} · {rng}",
        description="\n".join(lines),
        color=EMBED_COLOR_OK,
    )
    last = (mm.summary or {}).get("last_updated") or ""
    embed.set_footer(text=f"Source: magicalmeta.ink · data as of {last}")
    return embed


def build_heat_embed(thb_rate: float | None) -> discord.Embed:
    health = mm.market_health()
    if not health:
        return discord.Embed(
            title="Market heat unavailable",
            description="Magical Meta data hasn't loaded yet — try again in a minute.",
            color=EMBED_COLOR_WARN,
        )
    direction = mm.market_direction("d7")
    md = direction.get("direction") or {}  # actually a dict: gainers/decliners/flat/breadth/...
    heat_count = direction.get("heat_count")
    heat_by_tier = direction.get("heat_by_tier") or {}

    desc = [
        f"🌐 **Total market value:** {_money(health.get('total_value'), thb_rate)}",
        f"🎴 **Cards tracked:** {health.get('cards_tracked') or 0:,} across "
        f"{health.get('sets_tracked') or 0} sets",
        f"📦 **Total qty sold (period):** {int(health.get('total_qty_sold') or 0):,} "
        f"in {int(health.get('total_tx') or 0):,} transactions",
        f"📅 **Avg daily:** {health.get('avg_daily_qty') or 0:.0f} qty · "
        f"{health.get('avg_daily_tx') or 0:.0f} tx",
    ]
    if isinstance(md, dict) and md:
        breadth = md.get("breadth")
        bits = [
            f"📈 gainers **{md.get('gainers', 0):,}**",
            f"📉 decliners **{md.get('decliners', 0):,}**",
            f"↔️ flat **{md.get('flat', 0):,}**",
        ]
        if isinstance(breadth, (int, float)):
            bits.append(f"breadth **{breadth}%**")
        desc.append("")
        desc.append("**Direction (7d):** " + " · ".join(bits))
    if isinstance(heat_count, (int, float)):
        bits = [f"🔥 **{int(heat_count):,}** hot listings"]
        if heat_by_tier:
            tier_bits = [
                f"{label} **{int(heat_by_tier[label])}**"
                for label in ("high", "mid", "low")
                if isinstance(heat_by_tier.get(label), (int, float))
            ]
            if tier_bits:
                bits.append("(" + " · ".join(tier_bits) + ")")
        desc.append("**Heat (7d):** " + " ".join(bits))

    embed = discord.Embed(title="📊 Riftbound Market Heat", description="\n".join(desc), color=EMBED_COLOR_INFO)
    embed.set_footer(text=f"Source: magicalmeta.ink · last_updated {health.get('last_updated')}")
    return embed


# ---------- Config & watchlists ------------------------------------------

def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_config(cfg: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def _load_watchlists() -> dict[str, list[dict]]:
    if not WATCHLISTS_PATH.exists():
        return {}
    try:
        return json.loads(WATCHLISTS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_watchlists(wl: dict[str, list[dict]]) -> None:
    WATCHLISTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    WATCHLISTS_PATH.write_text(json.dumps(wl, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


# ---------- Bot ----------------------------------------------------------

class PriceBot(discord.Client):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.cards: list[dict] = []
        self.session: requests.Session | None = None
        self.config: dict = {}
        self.watchlists: dict[str, list[dict]] = {}

    async def setup_hook(self) -> None:
        self.cards = load_cards()
        self.config = _load_config()
        self.watchlists = _load_watchlists()
        log.info(
            "Loaded %d cards · %d users in watchlist · digest_channel=%s",
            len(self.cards), len(self.watchlists),
            self.config.get("digest_channel_id"),
        )
        self.session = await asyncio.to_thread(_session)
        # Prime Magical Meta data so the first /price call already has trend info.
        try:
            await mm.ensure_fresh()
        except Exception:
            log.exception("Initial magicalmeta fetch failed")

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user and self.user.id)
        app_id = self.application_id
        if app_id:
            try:
                await self.http.bulk_upsert_global_commands(app_id, [])
                log.info("Cleared global commands on Discord side.")
            except Exception:
                log.exception("Failed clearing global commands")
            for guild in self.guilds:
                try:
                    await self.http.bulk_upsert_guild_commands(app_id, guild.id, [])
                except Exception:
                    log.exception("Failed clearing guild %s", guild.id)
        for guild in self.guilds:
            try:
                self.tree.clear_commands(guild=guild)
                self.tree.copy_global_to(guild=guild)
                synced = await self.tree.sync(guild=guild)
                log.info(
                    "Synced %d commands to guild %s (%s)",
                    len(synced), guild.name, guild.id,
                )
            except Exception:
                log.exception("Sync failed for guild %s", guild.id)
        # Start background loops (safe to call repeatedly — guarded inside).
        if not magicalmeta_refresh.is_running():
            magicalmeta_refresh.start()
        if not daily_digest.is_running():
            daily_digest.start()
        if not watchlist_check.is_running():
            watchlist_check.start()
        if not heartbeat.is_running():
            heartbeat.start()


bot = PriceBot()


# ---------- TCGplayer live fetch helper ---------------------------------

def _refresh_session_if_needed(exc: Exception) -> bool:
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        if exc.response.status_code == 403:
            bot.session = None
            return True
    return False


async def _fetch_live(card: dict) -> tuple[dict | None, list[dict]]:
    pid = card["product_id"]
    if bot.session is None:
        bot.session = await asyncio.to_thread(_session)
    try:
        live = await asyncio.to_thread(fetch_product, pid, bot.session)
        sales = await asyncio.to_thread(fetch_latest_sales, pid, 5, bot.session)
        return live, sales
    except requests.HTTPError as e:
        if _refresh_session_if_needed(e):
            bot.session = await asyncio.to_thread(_session)
            live = await asyncio.to_thread(fetch_product, pid, bot.session)
            sales = await asyncio.to_thread(fetch_latest_sales, pid, 5, bot.session)
            return live, sales
        raise


# ---------- Background loops --------------------------------------------

@tasks.loop(minutes=30)
async def magicalmeta_refresh() -> None:
    try:
        await mm.ensure_fresh()
    except Exception:
        log.exception("magicalmeta refresh failed")


@magicalmeta_refresh.before_loop
async def _wait_mm_ready() -> None:
    await bot.wait_until_ready()


@tasks.loop(minutes=5)
async def heartbeat() -> None:
    """Periodic 'I'm alive' log so we can tell at a glance whether the bot
    actually survived between restarts vs. died silently."""
    ws_latency_ms = bot.latency * 1000 if bot.latency else float("nan")
    log.info(
        "heartbeat · ws=%.0fms · guilds=%d · mm_age=%ds · watchlists=%d",
        ws_latency_ms,
        len(bot.guilds),
        int(time.time() - mm.last_fetch) if mm.last_fetch else -1,
        len(bot.watchlists),
    )


@heartbeat.before_loop
async def _wait_heartbeat_ready() -> None:
    await bot.wait_until_ready()


@tasks.loop(time=DIGEST_TIME_LOCAL)
async def daily_digest() -> None:
    channel_id = bot.config.get("digest_channel_id")
    if not channel_id:
        return
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        log.warning("daily_digest: configured channel %s not found", channel_id)
        return
    try:
        await mm.ensure_fresh()
        thb_rate = await asyncio.to_thread(get_thb_rate)
        embeds = [
            build_top_embed("d7", "gainers", mm.top("d7", "gainers", 5), thb_rate),
            build_top_embed("d7", "losers", mm.top("d7", "losers", 5), thb_rate),
            build_top_embed("d7", "sellers", mm.top("d7", "sellers", 5), thb_rate),
        ]
        await channel.send(content="**🗓️ Riftbound daily digest (7d)**", embeds=embeds)
    except Exception:
        log.exception("daily_digest failed")


@daily_digest.before_loop
async def _wait_digest_ready() -> None:
    await bot.wait_until_ready()


@tasks.loop(minutes=WATCHLIST_CHECK_INTERVAL_MINUTES)
async def watchlist_check() -> None:
    if not bot.watchlists:
        return
    try:
        await mm.ensure_fresh()
    except Exception:
        log.warning("watchlist_check: mm refresh failed, skipping cycle")
        return
    dirty = False
    for uid, watches in list(bot.watchlists.items()):
        for w in list(watches):
            pid = w["product_id"]
            current = _watch_current_price(pid)
            baseline = w.get("baseline_price")
            threshold = float(w.get("threshold_pct") or WATCHLIST_DEFAULT_THRESHOLD_PCT)
            if not isinstance(current, (int, float)) or not isinstance(baseline, (int, float)) or baseline <= 0:
                continue
            pct = (current - baseline) / baseline * 100.0
            if abs(pct) < threshold:
                continue
            user = bot.get_user(int(uid)) or await bot.fetch_user(int(uid))
            if user is None:
                continue
            try:
                emb = discord.Embed(
                    title=f"🔔 {w.get('name', '?')} moved {pct:+.1f}%",
                    description=(
                        f"Baseline **${baseline:.2f}** → now **${current:.2f}**\n"
                        f"Threshold was **{threshold:.1f}%**\n\n"
                        f"[Open on TCGplayer]({TCGPLAYER_PRODUCT_URL.format(product_id=pid)})"
                    ),
                    color=EMBED_COLOR_WARN if pct < 0 else EMBED_COLOR_OK,
                )
                emb.set_thumbnail(url=image_url(pid))
                await user.send(embed=emb)
                # Re-baseline so we don't keep alerting on the same move.
                w["baseline_price"] = current
                w["last_alert_at"] = datetime.now(timezone.utc).isoformat()
                dirty = True
            except discord.Forbidden:
                log.warning("Cannot DM user %s (DMs closed)", uid)
            except Exception:
                log.exception("watchlist DM failed for %s", uid)
    if dirty:
        _save_watchlists(bot.watchlists)


@watchlist_check.before_loop
async def _wait_watch_ready() -> None:
    await bot.wait_until_ready()


def _watch_current_price(product_id: int) -> float | None:
    """Cheapest price source we have for a single product: Magical Meta first
    (no extra requests), fall back to a single TCGplayer search call."""
    trends = mm.trend_for(product_id)
    for r in ("h24", "d7"):
        rec = trends.get(r)
        if rec and isinstance(rec.get("market_price"), (int, float)):
            return float(rec["market_price"])
    # Fallback: live TCGplayer (1 request)
    try:
        live = fetch_product(product_id, bot.session) if bot.session else None
    except Exception:
        return None
    if live and isinstance(live.get("marketPrice"), (int, float)):
        return float(live["marketPrice"])
    return None


# ---------- Slash commands ----------------------------------------------

@bot.tree.command(name="price", description="Look up Riftbound card price + recent sales + trend")
@app_commands.describe(query="Card name (e.g. ahri) or TCGplayer product ID (e.g. 653053)")
async def price_cmd(interaction: discord.Interaction, query: str) -> None:
    await interaction.response.defer(thinking=True)
    if not bot.cards:
        bot.cards = load_cards()
    matches = find_cards(query, bot.cards)
    if not matches:
        await interaction.followup.send(embed=build_no_match_embed(query))
        return
    thb_rate = await asyncio.to_thread(get_thb_rate)
    if len(matches) > 1:
        await interaction.followup.send(embed=build_multi_match_embed(query, matches, thb_rate))
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
    await interaction.followup.send(embed=build_price_embed(card, live, sales, thb_rate))


@price_cmd.autocomplete("query")
async def price_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not bot.cards:
        bot.cards = load_cards()
    matches = find_cards(current, bot.cards) if current.strip() else bot.cards[:25]
    choices: list[app_commands.Choice[str]] = []
    for c in matches[:25]:
        name = c.get("name") or f"#{c['product_id']}"
        set_name = c.get("set_name") or "—"
        market = c.get("market_price")
        price_tag = f" · ${market:.2f}" if isinstance(market, (int, float)) else ""
        label = f"{name} · {set_name}{price_tag}"[:100]
        choices.append(app_commands.Choice(name=label, value=str(c["product_id"])))
    return choices


_RANGE_CHOICES = [app_commands.Choice(name=RANGE_LABEL[r], value=r) for r in RANGES]
_KIND_CHOICES = [
    app_commands.Choice(name="📈 Gainers", value="gainers"),
    app_commands.Choice(name="📉 Losers",  value="losers"),
    app_commands.Choice(name="🔥 Sellers", value="sellers"),
]


@bot.tree.command(name="top", description="Top movers / sellers across the Riftbound market")
@app_commands.describe(range="Time range", kind="What to rank by")
@app_commands.choices(range=_RANGE_CHOICES, kind=_KIND_CHOICES)
async def top_cmd(
    interaction: discord.Interaction,
    range: app_commands.Choice[str],
    kind: app_commands.Choice[str],
) -> None:
    await interaction.response.defer(thinking=True)
    if not (mm.summary):
        await mm.ensure_fresh()
    thb_rate = await asyncio.to_thread(get_thb_rate)
    items = mm.top(range.value, kind.value, 10)
    await interaction.followup.send(embed=build_top_embed(range.value, kind.value, items, thb_rate))


@bot.tree.command(name="heat", description="Market heat: direction, hot/cold counts, totals")
async def heat_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    if not mm.summary:
        await mm.ensure_fresh()
    thb_rate = await asyncio.to_thread(get_thb_rate)
    await interaction.followup.send(embed=build_heat_embed(thb_rate))


@bot.tree.command(name="setdigest", description="Designate this channel for the 09:00 Bangkok daily digest")
async def setdigest_cmd(interaction: discord.Interaction) -> None:
    bot.config["digest_channel_id"] = interaction.channel_id
    _save_config(bot.config)
    await interaction.response.send_message(
        f"✅ Daily digest will post in <#{interaction.channel_id}> at 09:00 Asia/Bangkok.",
        ephemeral=True,
    )


@bot.tree.command(name="digest", description="Post the 7-day digest right now (manual trigger)")
async def digest_cmd(interaction: discord.Interaction) -> None:
    await interaction.response.defer(thinking=True)
    await mm.ensure_fresh()
    thb_rate = await asyncio.to_thread(get_thb_rate)
    embeds = [
        build_top_embed("d7", "gainers", mm.top("d7", "gainers", 5), thb_rate),
        build_top_embed("d7", "losers", mm.top("d7", "losers", 5), thb_rate),
        build_top_embed("d7", "sellers", mm.top("d7", "sellers", 5), thb_rate),
    ]
    await interaction.followup.send(content="**🗓️ Riftbound digest (7d)**", embeds=embeds)


@bot.tree.command(name="watch", description="Add a card to your personal watchlist (DM alert on price move)")
@app_commands.describe(
    query="Card name or product ID",
    threshold_pct="Alert when |% change| ≥ this (default 10)",
)
async def watch_cmd(
    interaction: discord.Interaction,
    query: str,
    threshold_pct: app_commands.Range[float, 1.0, 100.0] = WATCHLIST_DEFAULT_THRESHOLD_PCT,
) -> None:
    await interaction.response.defer(thinking=True, ephemeral=True)
    matches = find_cards(query, bot.cards)
    if not matches:
        await interaction.followup.send(embed=build_no_match_embed(query))
        return
    if len(matches) > 1:
        await interaction.followup.send(embed=build_multi_match_embed(query, matches, None))
        return
    card = matches[0]
    pid = card["product_id"]
    baseline = await asyncio.to_thread(_watch_current_price, pid)
    if not isinstance(baseline, (int, float)):
        await interaction.followup.send(f"Couldn't get a baseline price for `{pid}` — try again in a moment.")
        return
    uid = str(interaction.user.id)
    watches = bot.watchlists.setdefault(uid, [])
    # Replace existing entry for the same product
    watches[:] = [w for w in watches if w["product_id"] != pid]
    watches.append({
        "product_id": pid,
        "name": card.get("name"),
        "baseline_price": float(baseline),
        "threshold_pct": float(threshold_pct),
        "added_at": datetime.now(timezone.utc).isoformat(),
    })
    _save_watchlists(bot.watchlists)
    await interaction.followup.send(
        f"👀 Watching **{card.get('name')}** (`{pid}`) from baseline **${baseline:.2f}** "
        f"— alert when ≥ {threshold_pct:.0f}% move. You'll get a DM."
    )


@watch_cmd.autocomplete("query")
async def watch_autocomplete(interaction, current):
    return await price_autocomplete(interaction, current)


@bot.tree.command(name="unwatch", description="Remove a card from your watchlist")
@app_commands.describe(query="Card name or product ID")
async def unwatch_cmd(interaction: discord.Interaction, query: str) -> None:
    uid = str(interaction.user.id)
    watches = bot.watchlists.get(uid, [])
    if not watches:
        await interaction.response.send_message("Your watchlist is empty.", ephemeral=True)
        return
    q = query.strip().lower()
    before = len(watches)
    if q.isdigit():
        pid = int(q)
        watches[:] = [w for w in watches if w["product_id"] != pid]
    else:
        watches[:] = [w for w in watches if q not in (w.get("name") or "").lower()]
    removed = before - len(watches)
    bot.watchlists[uid] = watches
    _save_watchlists(bot.watchlists)
    await interaction.response.send_message(
        f"Removed **{removed}** card{'s' if removed != 1 else ''} from your watchlist.",
        ephemeral=True,
    )


@unwatch_cmd.autocomplete("query")
async def unwatch_autocomplete(interaction, current):
    uid = str(interaction.user.id)
    watches = bot.watchlists.get(uid, [])
    needle = current.strip().lower()
    matches = [
        w for w in watches
        if not needle or needle in (w.get("name") or "").lower() or needle == str(w["product_id"])
    ]
    return [
        app_commands.Choice(name=f"{w.get('name','?')} (#{w['product_id']})"[:100], value=str(w["product_id"]))
        for w in matches[:25]
    ]


@bot.tree.command(name="watchlist", description="Show your current watchlist")
async def watchlist_cmd(interaction: discord.Interaction) -> None:
    uid = str(interaction.user.id)
    watches = bot.watchlists.get(uid, [])
    if not watches:
        await interaction.response.send_message("Your watchlist is empty. Use `/watch <name>` to add cards.", ephemeral=True)
        return
    thb_rate = await asyncio.to_thread(get_thb_rate)
    lines = []
    for w in watches:
        pid = w["product_id"]
        current = _watch_current_price(pid)
        baseline = w.get("baseline_price")
        pct_str = ""
        if isinstance(current, (int, float)) and isinstance(baseline, (int, float)) and baseline:
            pct_str = " · " + _pct_glyph((current - baseline) / baseline * 100.0)
        lines.append(
            f"• [{w.get('name', '?')}]({TCGPLAYER_PRODUCT_URL.format(product_id=pid)}) "
            f"(`{pid}`) — baseline {_money(baseline, thb_rate)} "
            f"→ now {_money(current, thb_rate)}{pct_str} "
            f"· @ {w.get('threshold_pct', WATCHLIST_DEFAULT_THRESHOLD_PCT):.0f}%"
        )
    embed = discord.Embed(
        title="📋 Your watchlist",
        description="\n".join(lines),
        color=EMBED_COLOR_INFO,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="ping", description="Health check")
async def ping_cmd(interaction: discord.Interaction) -> None:
    mm_age = ""
    if mm.last_fetch:
        age = int(time.time() - mm.last_fetch)
        mm_age = f" · mm cache age {age // 60}m{age % 60}s"
    await interaction.response.send_message(
        f"pong · {len(bot.cards)} cards · {len(bot.watchlists)} watchlists · "
        f"latency {bot.latency * 1000:.0f}ms{mm_age}",
        ephemeral=True,
    )


# ---------- Entry --------------------------------------------------------

def _resolve_token() -> str | None:
    try:
        import keyring
        token = keyring.get_password(KEYRING_SERVICE, KEYRING_USERNAME)
        if token:
            return token
    except Exception as e:
        log.warning("keyring unavailable, falling back to %s: %s", TOKEN_ENV, e)
    return os.environ.get(TOKEN_ENV)


def main() -> int:
    token = _resolve_token()
    if not token:
        log.error(
            "No Discord bot token. keyring service=%s user=%s, or env var %s.",
            KEYRING_SERVICE, KEYRING_USERNAME, TOKEN_ENV,
        )
        return 1
    log.info("bot.main() entering bot.run() — anything below this line means we exited the event loop")
    try:
        bot.run(token, log_handler=None)
    except BaseException:
        log.exception("bot.run() raised — exiting")
        return 2
    log.info("bot.run() returned cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
