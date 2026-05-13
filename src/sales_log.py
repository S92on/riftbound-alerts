"""Accumulating sales log.

TCGplayer's public `latestsales` endpoint returns at most ~5 most-recent sales
per product, regardless of the requested `limit`. To get a real 7-day window we
poll it on a cron and merge new sales into a local log, deduplicated by the
sale's `orderDate` timestamp (precise to milliseconds — effectively unique).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

WINDOW_DAYS = 7


def _parse(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def load(path: Path) -> dict[str, list[dict]]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, log: dict[str, list[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(log, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )


def merge(
    existing: list[dict],
    new_sales: list[dict],
    *,
    now: datetime,
) -> list[dict]:
    """Return a deduplicated, pruned list of sales for one product.

    Each sale is stored compactly as: {"d": orderDate, "q": qty, "p": price,
    "v": variant}. We dedupe by `d` (millisecond timestamps are unique per
    sale). We keep only sales newer than `now - WINDOW_DAYS`.
    """
    cutoff = now - timedelta(days=WINDOW_DAYS)
    by_date: dict[str, dict] = {}
    for s in existing:
        ts = _parse(s.get("d", ""))
        if ts and ts >= cutoff:
            by_date[s["d"]] = s
    for raw in new_sales:
        d = raw.get("orderDate", "")
        ts = _parse(d)
        if not ts or ts < cutoff:
            continue
        by_date[d] = {
            "d": d,
            "q": int(raw.get("quantity", 0) or 0),
            "p": float(raw.get("purchasePrice", 0) or 0),
            "v": raw.get("variant") or "",
        }
    return sorted(by_date.values(), key=lambda s: s["d"], reverse=True)


def signal_from_log(sales: list[dict], *, now: datetime) -> dict | None:
    """Compute the Deck Identity signal from accumulated sales."""
    from check_signals import MIN_AVG_COPIES, MIN_SOLD_7D  # avoid circular

    cutoff = now - timedelta(days=WINDOW_DAYS)
    qty = 0
    tx = 0
    for s in sales:
        ts = _parse(s.get("d", ""))
        if not ts or ts < cutoff:
            continue
        qty += int(s.get("q", 0))
        tx += 1
    if tx == 0:
        return None
    avg = qty / tx
    if qty < MIN_SOLD_7D or avg < MIN_AVG_COPIES:
        return None
    return {
        "sold_7d": qty,
        "tx_7d": tx,
        "avg_copies": avg,
        "window_end": now.strftime("%Y-%m-%d %H:%M UTC"),
    }
