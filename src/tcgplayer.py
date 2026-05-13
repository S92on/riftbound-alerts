"""TCGplayer marketplace API wrappers for Riftbound."""
from __future__ import annotations

import time
from typing import Iterator

import requests

PRODUCT_LINE = "riftbound-league-of-legends-trading-card-game"

SEARCH_URL = "https://mp-search-api.tcgplayer.com/v1/search/request?q=&isList=false"
SALES_URL = "https://mpapi.tcgplayer.com/v2/product/{product_id}/latestsales"
IMAGE_URL = "https://product-images.tcgplayer.com/fit-in/437x437/{product_id}.jpg"

_HEADERS = {
    "Origin": "https://www.tcgplayer.com",
    "Referer": "https://www.tcgplayer.com/",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update(_HEADERS)
    return s


def iter_riftbound_cards(session: requests.Session | None = None) -> Iterator[dict]:
    """Yield every Riftbound single-card product on TCGplayer."""
    s = session or _session()
    page_size = 50
    offset = 0
    while True:
        body = {
            "algorithm": "",
            "from": offset,
            "size": page_size,
            "filters": {
                "term": {
                    "productLineName": [PRODUCT_LINE],
                    "productTypeName": ["Cards"],
                },
                "range": {},
                "match": {},
            },
            "context": {"cart": {}, "shippingCountry": "US"},
            "sort": {},
        }
        r = s.post(SEARCH_URL, json=body, timeout=30)
        r.raise_for_status()
        payload = r.json()["results"][0]
        results = payload.get("results", [])
        if not results:
            return
        for item in results:
            yield item
        offset += page_size
        if offset >= payload.get("totalResults", 0):
            return
        time.sleep(0.25)


def fetch_latest_sales(
    product_id: int,
    limit: int = 25,
    session: requests.Session | None = None,
) -> list[dict]:
    """Return up to `limit` most recent sales for a product."""
    s = session or _session()
    body = {"sortBy": "order", "limit": limit, "offset": 0}
    r = s.post(SALES_URL.format(product_id=product_id), json=body, timeout=30)
    r.raise_for_status()
    return r.json().get("data", [])


def image_url(product_id: int) -> str:
    return IMAGE_URL.format(product_id=product_id)
