// Magical Meta summary.json fetcher with KV-backed cache.

import type { Env, MMItem, MMRange, MMSummary } from "./types";

const SUMMARY_URL = "https://magicalmeta.ink/riftbound/data/summary.json";
const KV_KEY = "summary";
const KV_TTL_SECONDS = 60 * 30; // KV expirationTtl matches our refresh cadence

const HEADERS = {
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
  "Accept": "application/json",
  "Referer": "https://magicalmeta.ink/riftbound",
};

export async function fetchAndCacheSummary(env: Env): Promise<MMSummary | null> {
  try {
    const r = await fetch(SUMMARY_URL, { headers: HEADERS });
    if (!r.ok) return null;
    const data = (await r.json()) as MMSummary;
    await env.MMCACHE.put(KV_KEY, JSON.stringify(data), { expirationTtl: KV_TTL_SECONDS });
    return data;
  } catch {
    return null;
  }
}

export async function getSummary(env: Env): Promise<MMSummary | null> {
  const cached = await env.MMCACHE.get(KV_KEY, "json");
  if (cached) return cached as MMSummary;
  return fetchAndCacheSummary(env);
}

/** Build {product_id: {range_key: merged_record}} from a summary. */
export function indexByProductId(summary: MMSummary): Record<string, Record<string, MMItem>> {
  const byPid: Record<string, Record<string, MMItem>> = {};
  const ranges = summary.dashboard_aggregates?.by_range || {};
  for (const [rangeKey, rangeData] of Object.entries(ranges)) {
    const stash = (item: MMItem) => {
      const pid = item.product_id ? String(item.product_id) : "";
      if (!pid) return;
      byPid[pid] ||= {};
      byPid[pid][rangeKey] = { ...(byPid[pid][rangeKey] || {}), ...item };
    };
    for (const it of rangeData.top_movers?.gainers || []) stash(it);
    for (const it of rangeData.top_movers?.losers || []) stash(it);
    for (const it of rangeData.top_sellers?.items || []) stash(it);
  }
  return byPid;
}

export function topItems(summary: MMSummary, rangeKey: string, kind: "gainers" | "losers" | "sellers", n = 10): MMItem[] {
  const r: MMRange | undefined = summary.dashboard_aggregates?.by_range?.[rangeKey];
  if (!r) return [];
  if (kind === "gainers") return (r.top_movers?.gainers || []).slice(0, n);
  if (kind === "losers") return (r.top_movers?.losers || []).slice(0, n);
  return (r.top_sellers?.items || []).slice(0, n);
}

export function marketHealth(summary: MMSummary) {
  const ms = summary.market_summary || {};
  return {
    total_value: ms.total_market_value,
    cards_tracked: ms.total_cards_tracked,
    sets_tracked: ms.total_sets_tracked,
    total_qty_sold: ms.total_quantity_sold,
    total_tx: ms.total_transaction_count,
    avg_daily_qty: ms.avg_daily_quantity_sold,
    avg_daily_tx: ms.avg_daily_transaction_count,
    last_updated: summary.last_updated,
  };
}

export function marketDirection(summary: MMSummary, rangeKey = "d7") {
  const r: MMRange | undefined = summary.dashboard_aggregates?.by_range?.[rangeKey];
  return {
    direction: r?.market_direction,
    heat_count: r?.heat_count,
    heat_by_tier: r?.heat_by_tier,
  };
}
