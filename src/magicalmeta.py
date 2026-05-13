"""Magical Meta market trend data.

`https://magicalmeta.ink/riftbound/data/summary.json` is a ~240 KB JSON that
ships per-card trend stats (movers, sellers, % change, qty sold) across seven
time ranges (24h / 7d / 30d / 60d / 90d / 180d / 1y). It's refreshed on their
side every few hours; we refetch every 30 min and serve from memory.

We never touch their per-set files — those return 0 bytes for non-browser
fetches anyway, and summary.json has everything we need for /price + /top
+ /heat + daily digest.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import requests

log = logging.getLogger("riftbound-bot")

SUMMARY_URL = "https://magicalmeta.ink/riftbound/data/summary.json"
REFRESH_INTERVAL_SECONDS = 1800  # 30 min

RANGES = ["h24", "d7", "d30", "d60", "d90", "d180", "y1"]
RANGE_LABEL = {
    "h24": "24h", "d7": "7d", "d30": "30d", "d60": "60d",
    "d90": "90d", "d180": "180d", "y1": "1y",
}
KINDS = ["gainers", "losers", "sellers"]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://magicalmeta.ink/riftbound",
}


class MMData:
    def __init__(self) -> None:
        self.summary: dict | None = None
        self.last_fetch: float = 0.0
        # product_id -> {range_name -> {"mover": item, "seller": item}}
        self._by_pid: dict[str, dict[str, dict[str, Any]]] = {}

    async def ensure_fresh(self) -> bool:
        """Refetch summary if it's missing or stale. Returns True on success."""
        if self.summary and (time.time() - self.last_fetch) < REFRESH_INTERVAL_SECONDS:
            return True
        try:
            data = await asyncio.to_thread(self._fetch_sync)
        except Exception as e:
            log.warning("magicalmeta fetch failed: %s", e)
            return False
        self.summary = data
        self.last_fetch = time.time()
        self._rebuild_index()
        log.info(
            "magicalmeta: refreshed (%d cards tracked, last_updated=%s)",
            data.get("trading_card_count", 0),
            data.get("last_updated"),
        )
        return True

    def _fetch_sync(self) -> dict:
        r = requests.get(SUMMARY_URL, timeout=30, headers=_HEADERS)
        r.raise_for_status()
        return r.json()

    def _rebuild_index(self) -> None:
        self._by_pid.clear()
        if not self.summary:
            return
        ranges = (self.summary.get("dashboard_aggregates") or {}).get("by_range") or {}
        for range_name, range_data in ranges.items():
            for item in (range_data.get("top_movers") or {}).get("gainers") or []:
                self._stash(item, range_name, "mover")
            for item in (range_data.get("top_movers") or {}).get("losers") or []:
                self._stash(item, range_name, "mover")
            for item in (range_data.get("top_sellers") or {}).get("items") or []:
                self._stash(item, range_name, "seller")

    def _stash(self, item: dict, range_name: str, kind: str) -> None:
        pid = str(item.get("product_id") or "")
        if not pid:
            return
        self._by_pid.setdefault(pid, {}).setdefault(range_name, {})[kind] = item

    # ---- queries ------------------------------------------------------

    def trend_for(self, product_id: int) -> dict[str, dict]:
        """Return {range_name: combined_record} for one product."""
        records = self._by_pid.get(str(product_id), {})
        out: dict[str, dict] = {}
        for range_name, by_kind in records.items():
            merged = {}
            for r in by_kind.values():
                merged.update(r)
            out[range_name] = merged
        return out

    def top(self, range_name: str, kind: str, n: int = 10) -> list[dict]:
        if not self.summary:
            return []
        d = (self.summary.get("dashboard_aggregates") or {}).get("by_range", {}).get(range_name, {})
        if kind == "gainers":
            return ((d.get("top_movers") or {}).get("gainers") or [])[:n]
        if kind == "losers":
            return ((d.get("top_movers") or {}).get("losers") or [])[:n]
        if kind == "sellers":
            return ((d.get("top_sellers") or {}).get("items") or [])[:n]
        return []

    def market_health(self) -> dict:
        if not self.summary:
            return {}
        ms = self.summary.get("market_summary") or {}
        return {
            "total_value": ms.get("total_market_value"),
            "cards_tracked": ms.get("total_cards_tracked"),
            "sets_tracked": ms.get("total_sets_tracked"),
            "total_qty_sold": ms.get("total_quantity_sold"),
            "total_tx": ms.get("total_transaction_count"),
            "avg_daily_qty": ms.get("avg_daily_quantity_sold"),
            "avg_daily_tx": ms.get("avg_daily_transaction_count"),
            "set_breakdown": ms.get("set_breakdown") or {},
            "last_updated": self.summary.get("last_updated"),
        }

    def market_direction(self, range_name: str = "d7") -> dict:
        if not self.summary:
            return {}
        d = (self.summary.get("dashboard_aggregates") or {}).get("by_range", {}).get(range_name, {})
        return {
            "direction": d.get("market_direction"),
            "heat_count": d.get("heat_count"),
            "heat_by_tier": d.get("heat_by_tier"),
        }


mm = MMData()
