"""Refresh the local cache of Riftbound card metadata from TCGplayer.

Run on a slow cadence (e.g. once a day) — card list rarely changes.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from tcgplayer import iter_riftbound_cards

CARDS_PATH = Path(__file__).resolve().parents[1] / "data" / "cards.json"


def _slim(item: dict) -> dict:
    """Keep only the fields the rest of the pipeline needs."""
    attrs = item.get("customAttributes") or {}
    return {
        "product_id": int(item["productId"]),
        "name": item.get("productName"),
        "set_name": item.get("setName"),
        "set_url": item.get("setUrlName"),
        "rarity": item.get("rarityName") or attrs.get("rarityDbName"),
        "market_price": item.get("marketPrice"),
        "lowest_price": item.get("lowestPrice"),
        "number": attrs.get("number"),
        "release_date": attrs.get("releaseDate"),
        "product_url_name": item.get("productUrlName"),
    }


def main() -> int:
    started = time.time()
    print(f"Refreshing Riftbound card list from TCGplayer...", flush=True)
    cards: list[dict] = []
    for item in iter_riftbound_cards():
        cards.append(_slim(item))
        if len(cards) % 100 == 0:
            print(f"  fetched {len(cards)} cards...", flush=True)
    cards.sort(key=lambda c: c["product_id"])
    CARDS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CARDS_PATH.write_text(json.dumps(cards, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(cards)} cards to {CARDS_PATH} in {time.time() - started:.1f}s",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
