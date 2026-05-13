"""Post Deck Identity alerts to a Discord webhook."""
from __future__ import annotations

import os
from typing import Any

import requests

WEBHOOK_ENV = "DISCORD_WEBHOOK_URL"
ALERT_COLOR = 0xE74C3C  # red, matching Magical Meta's left bar
TCGPLAYER_PRODUCT_URL = "https://www.tcgplayer.com/product/{product_id}"


def _money(v: float | None) -> str:
    return f"${v:.2f}" if isinstance(v, (int, float)) else "—"


def build_embed(card: dict, signal: dict) -> dict[str, Any]:
    pid = card["product_id"]
    name = card.get("name") or f"Product {pid}"
    set_name = card.get("set_name") or "—"
    rarity = card.get("rarity") or "—"
    market = card.get("market_price")
    low = card.get("lowest_price")
    image = f"https://product-images.tcgplayer.com/fit-in/437x437/{pid}.jpg"

    sold = signal["sold_7d"]
    tx = signal["tx_7d"]
    avg = signal["avg_copies"]
    window_end = signal.get("window_end") or ""

    description_lines = [
        f"**{sold} sold · {tx} tx (7d)**",
        f"Avg **{avg:.2f}** copies/tx",
        "Deck-identity breadth gate cleared",
    ]

    fields = [
        {
            "name": "Market",
            "value": f"{_money(market)} · Low: {_money(low)}",
            "inline": False,
        },
        {
            "name": "Signal Type",
            "value": "**Deck Identity Alert**\nBuyer activity detected",
            "inline": False,
        },
        {
            "name": "Buyer Activity",
            "value": (
                f"Transactions: **{tx}**\n"
                f"Avg/order: **{avg:.2f}** copies"
            ),
            "inline": False,
        },
        {
            "name": "Copies Sold",
            "value": f"**{sold}** in 7 days\nOne-per-deck buyer breadth confirmed.",
            "inline": False,
        },
        {
            "name": "Card",
            "value": (
                f"**Riftbound**\n"
                f"Set: **{set_name}**\n"
                f"Rarity: **{rarity}**\n"
                f"TCGplayer #: `{pid}`"
            ),
            "inline": False,
        },
    ]

    return {
        "title": f"\U0001F6A8 Deck Identity Alert · Riftbound",
        "url": TCGPLAYER_PRODUCT_URL.format(product_id=pid),
        "color": ALERT_COLOR,
        "description": f"**{name}**\n\n" + "\n".join(description_lines),
        "thumbnail": {"url": image},
        "fields": fields,
        "footer": {
            "text": (
                f"MagicalMeta-style Alert · TCGplayer #{pid} · Market Data · 7d"
                + (f" | {window_end}" if window_end else "")
            )
        },
    }


def post_alert(webhook_url: str, card: dict, signal: dict) -> None:
    embed = build_embed(card, signal)
    payload = {
        "username": "Riftbound Market Alerts",
        "embeds": [embed],
    }
    r = requests.post(webhook_url, json=payload, timeout=15)
    if r.status_code == 429:
        # Discord rate limit — log and skip; the cron will retry next run
        print(f"  rate-limited by Discord, skipping {card['product_id']}", flush=True)
        return
    r.raise_for_status()


def webhook_from_env() -> str:
    url = os.environ.get(WEBHOOK_ENV)
    if not url:
        raise SystemExit(
            f"Set {WEBHOOK_ENV} (Discord webhook URL) before running."
        )
    return url
