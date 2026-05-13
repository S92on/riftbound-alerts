"""Post one sample alert to the Discord webhook to verify setup.

Usage:
    DISCORD_WEBHOOK_URL=https://... python src/test_alert.py
"""
from __future__ import annotations

from datetime import datetime, timezone

from discord_webhook import post_alert, webhook_from_env


def main() -> int:
    fake_card = {
        "product_id": 653053,
        "name": "Ahri - Nine-Tailed Fox",
        "set_name": "Origins",
        "rarity": "Rare",
        "market_price": 1.11,
        "lowest_price": 0.99,
    }
    fake_signal = {
        "sold_7d": 128,
        "tx_7d": 42,
        "avg_copies": 3.05,
        "window_end": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    url = webhook_from_env()
    print(f"Posting sample alert to {url[:50]}...", flush=True)
    post_alert(url, fake_card, fake_signal)
    print("Posted.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
