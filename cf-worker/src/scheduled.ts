// Cron handlers. Wrangler dispatches scheduled events with a `cron` field
// matching the schedule string we configured in wrangler.toml.

import { loadWatches, saveWatches, watchAlertEmbed, currentPriceFor } from "./commands";
import { dmUser, postChannelMessage } from "./discord";
import { topEmbed } from "./embeds";
import { getThbRate } from "./fx";
import { fetchAndCacheSummary, getSummary, topItems } from "./magicalmeta";
import { iterRiftboundCards } from "./tcgplayer";
import type { Card, Env } from "./types";

export async function refreshMagicalMeta(env: Env): Promise<void> {
  await fetchAndCacheSummary(env);
}

export async function postDailyDigest(env: Env): Promise<void> {
  const channelId = await env.CONFIG.get("digest_channel_id");
  if (!channelId) return;
  const summary = (await getSummary(env)) || (await fetchAndCacheSummary(env));
  if (!summary) return;
  const thb = await getThbRate(env);
  const embeds = [
    topEmbed("d7", "gainers", topItems(summary, "d7", "gainers", 5), thb, summary.last_updated),
    topEmbed("d7", "losers", topItems(summary, "d7", "losers", 5), thb, summary.last_updated),
    topEmbed("d7", "sellers", topItems(summary, "d7", "sellers", 5), thb, summary.last_updated),
  ];
  await postChannelMessage(env, channelId, { content: "**🗓️ Riftbound daily digest (7d)**", embeds });
}

export async function checkWatchlists(env: Env): Promise<void> {
  // List all user IDs (KV list is cursor-paged). The free tier list limit is
  // generous for a personal bot — we don't expect more than a few users.
  let cursor: string | undefined;
  do {
    const page = await env.WATCHLISTS.list({ cursor });
    for (const k of page.keys) {
      const uid = k.name;
      const watches = await loadWatches(env, uid);
      let dirty = false;
      for (const w of watches) {
        const current = await currentPriceFor(env, w.product_id);
        if (typeof current !== "number" || !w.baseline_price) continue;
        const pct = ((current - w.baseline_price) / w.baseline_price) * 100;
        if (Math.abs(pct) < w.threshold_pct) continue;
        const ok = await dmUser(env, uid, {
          embeds: [watchAlertEmbed(w.name, w.product_id, w.baseline_price, current, w.threshold_pct, pct)],
        });
        if (ok) {
          w.baseline_price = current;
          w.last_alert_at = new Date().toISOString();
          dirty = true;
        }
      }
      if (dirty) await saveWatches(env, uid, watches);
    }
    cursor = page.list_complete ? undefined : page.cursor;
  } while (cursor);
}

export async function refreshCards(env: Env): Promise<number> {
  const out: Card[] = [];
  for await (const raw of iterRiftboundCards()) {
    const r = raw as Record<string, unknown>;
    const attrs = (r.customAttributes as Record<string, unknown> | undefined) || {};
    const pid = Number(r.productId);
    if (!pid) continue;
    out.push({
      product_id: pid,
      name: String(r.productName ?? `#${pid}`),
      set_name: (r.setName as string | null) ?? null,
      rarity: (r.rarityName as string | null) ?? (attrs.rarityDbName as string | null) ?? null,
      market_price: typeof r.marketPrice === "number" ? r.marketPrice : null,
      lowest_price: typeof r.lowestPrice === "number" ? r.lowestPrice : null,
      number: (attrs.number as string | null) ?? null,
    });
  }
  out.sort((a, b) => a.product_id - b.product_id);
  await env.CARDS.put("all", JSON.stringify(out));
  return out.length;
}
