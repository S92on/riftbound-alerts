"""Poll TCGplayer for new sales, accumulate a 7-day window, and alert on Deck Identity signals.

Run on a cron (every ~30 min) — the TCGplayer public sales endpoint returns
only the ~5 most-recent sales per product, so we accumulate a local window.

Signal definition (matches Magical Meta's "Deck Identity Alert"):
  - >= 100 copies sold in the last 7 days
  - >= 2.5 average copies per transaction (one-per-deck breadth)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import sales_log
from discord_webhook import post_alert, webhook_from_env
from tcgplayer import _session, fetch_latest_sales

ROOT = Path(__file__).resolve().parents[1]
CARDS_PATH = ROOT / "data" / "cards.json"
SALES_PATH = ROOT / "data" / "sales_log.json"
STATE_PATH = ROOT / "data" / "state.json"

MIN_SOLD_7D = 100
MIN_AVG_COPIES = 2.5
ALERT_COOLDOWN_DAYS = 7
PER_REQUEST_DELAY = 1.0  # 1 req/s — TCGplayer's WAF bans faster rates after ~100 req
BAIL_AFTER_CONSECUTIVE_403 = 8  # stop the run if the WAF locks us out
BACKOFF_ON_403_SECONDS = 12  # one-shot pause after a 403 before continuing
BATCH_SIZE = 100  # cards per run; library covered every ~12 runs (~6h at 30min cron)
CURSOR_KEY = "_cursor"  # state.json field storing where to resume next run


def _load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _save_state(state: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def _parse_dt(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _on_cooldown(state_entry: dict | None, now: datetime) -> bool:
    if not state_entry:
        return False
    last = _parse_dt(state_entry.get("last_alert_at", ""))
    if not last:
        return False
    return (now - last) < timedelta(days=ALERT_COOLDOWN_DAYS)


def run(dry_run: bool, max_cards: int | None) -> int:
    cards = _load_json(CARDS_PATH, default=[])
    if not cards:
        print(
            f"No cards in {CARDS_PATH}. Run refresh_cards.py first.",
            file=sys.stderr,
        )
        return 1

    log = sales_log.load(SALES_PATH)
    state = _load_json(STATE_PATH, default={})
    webhook_url = None if dry_run else webhook_from_env()
    session = _session()
    now = datetime.now(timezone.utc)

    fired = 0
    skipped_cooldown = 0
    scanned = 0
    new_sales_total = 0
    failures = 0
    consecutive_403 = 0
    bailed = False

    if max_cards is not None:
        iterable = cards[:max_cards]
        cursor_start: int | None = None
    else:
        total = len(cards)
        cursor_start = int(state.get(CURSOR_KEY, 0)) % total
        end = cursor_start + BATCH_SIZE
        if end <= total:
            iterable = cards[cursor_start:end]
        else:
            iterable = cards[cursor_start:] + cards[: end - total]
    print(
        f"Scanning {len(iterable)} cards "
        f"(start={cursor_start}, dry_run={dry_run}, "
        f"thresholds: >={MIN_SOLD_7D} sold / 7d, >={MIN_AVG_COPIES} avg copies)",
        flush=True,
    )

    for card in iterable:
        pid = card["product_id"]
        key = str(pid)
        scanned += 1
        try:
            new_sales = fetch_latest_sales(pid, limit=25, session=session)
            consecutive_403 = 0
        except requests.HTTPError as e:
            failures += 1
            status = e.response.status_code if e.response is not None else "?"
            print(f"  [{pid}] HTTP {status}", flush=True)
            if status == 403:
                consecutive_403 += 1
                if consecutive_403 >= BAIL_AFTER_CONSECUTIVE_403:
                    print(
                        f"  bailing: {consecutive_403} consecutive 403s "
                        f"(IP rate-limited by TCGplayer WAF)",
                        flush=True,
                    )
                    bailed = True
                    break
                time.sleep(BACKOFF_ON_403_SECONDS)
                continue
            time.sleep(PER_REQUEST_DELAY)
            continue
        except requests.RequestException as e:
            failures += 1
            print(f"  [{pid}] {e}", flush=True)
            time.sleep(PER_REQUEST_DELAY)
            continue

        before = len(log.get(key, []))
        merged = sales_log.merge(log.get(key, []), new_sales, now=now)
        new_count = len(merged) - before
        if new_count > 0:
            new_sales_total += max(new_count, 0)
        if merged:
            log[key] = merged
        elif key in log:
            del log[key]

        signal = sales_log.signal_from_log(merged, now=now)
        if signal:
            if _on_cooldown(state.get(key), now):
                skipped_cooldown += 1
            else:
                print(
                    f"  [HIT] {card['name']} (#{pid}): "
                    f"{signal['sold_7d']} sold / {signal['tx_7d']} tx / "
                    f"avg {signal['avg_copies']:.2f}",
                    flush=True,
                )
                if not dry_run:
                    try:
                        post_alert(webhook_url, card, signal)
                    except requests.RequestException as e:
                        print(f"    discord post failed: {e}", flush=True)
                state[key] = {
                    "last_alert_at": now.isoformat(),
                    "last_sold_7d": signal["sold_7d"],
                    "last_avg_copies": round(signal["avg_copies"], 2),
                }
                fired += 1

        time.sleep(PER_REQUEST_DELAY)

    if cursor_start is not None and not bailed:
        state[CURSOR_KEY] = (cursor_start + BATCH_SIZE) % len(cards)

    if not dry_run:
        sales_log.save(SALES_PATH, log)
        _save_state(state)

    print(
        f"\nDone{' (bailed)' if bailed else ''}. scanned={scanned} "
        f"new_sales={new_sales_total} fired={fired} "
        f"cooldown_skip={skipped_cooldown} failures={failures}",
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Riftbound Deck Identity alert scanner")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't post to Discord or update state (but DO update sales log).",
    )
    parser.add_argument(
        "--max-cards",
        type=int,
        default=None,
        help="Limit number of cards scanned (for testing).",
    )
    args = parser.parse_args()
    return run(dry_run=args.dry_run, max_cards=args.max_cards)


if __name__ == "__main__":
    sys.exit(main())
