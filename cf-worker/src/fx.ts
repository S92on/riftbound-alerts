// USD -> THB rate from frankfurter.app (ECB, free, no key). Cached in KV.

import type { Env } from "./types";

const FX_URL = "https://api.frankfurter.app/latest?from=USD&to=THB";
const KV_KEY = "usd_thb";
const TTL_SECONDS = 60 * 60; // 1h

export async function getThbRate(env: Env): Promise<number | null> {
  const cached = await env.CONFIG.get(KV_KEY);
  if (cached) {
    const n = parseFloat(cached);
    if (!isNaN(n)) return n;
  }
  try {
    const r = await fetch(FX_URL);
    if (!r.ok) return null;
    const j = (await r.json()) as { rates?: { THB?: number } };
    const rate = j.rates?.THB;
    if (typeof rate !== "number") return null;
    await env.CONFIG.put(KV_KEY, String(rate), { expirationTtl: TTL_SECONDS });
    return rate;
  } catch {
    return null;
  }
}
