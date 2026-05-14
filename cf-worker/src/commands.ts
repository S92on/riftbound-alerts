// Slash command handlers. Every "real work" handler defers (type 5) then runs
// inside ctx.waitUntil so the 3-second response budget is never an issue.

import { findCardByPid, findCards, loadCards } from "./cards";
import { editOriginal } from "./discord";
import {
  heatEmbed,
  multiMatchEmbed,
  noMatchEmbed,
  priceEmbed,
  topEmbed,
  watchAlertEmbed,
} from "./embeds";
import { getThbRate } from "./fx";
import { fetchAndCacheSummary, getSummary, indexByProductId, topItems } from "./magicalmeta";
import { fetchLatestSales, fetchProductDetail } from "./tcgplayer";
import {
  Env,
  InteractionResponseFlags,
  InteractionResponseType,
  Watch,
} from "./types";

interface AppCmdInteraction {
  id: string;
  token: string;
  application_id: string;
  guild_id?: string;
  channel_id?: string;
  member?: { user?: { id: string } };
  user?: { id: string };
  data: {
    id: string;
    name: string;
    type?: number;
    options?: Array<{ name: string; type: number; value: string | number | boolean }>;
  };
}

function userIdOf(i: AppCmdInteraction): string {
  return i.member?.user?.id || i.user?.id || "";
}

function getOpt(i: AppCmdInteraction, name: string): string | number | boolean | undefined {
  return i.data.options?.find((o) => o.name === name)?.value;
}

function deferred(ephemeral = false) {
  return new Response(
    JSON.stringify({
      type: InteractionResponseType.DEFERRED_CHANNEL_MESSAGE_WITH_SOURCE,
      data: ephemeral ? { flags: InteractionResponseFlags.EPHEMERAL } : {},
    }),
    { headers: { "Content-Type": "application/json" } },
  );
}

async function fail(env: Env, token: string, msg: string) {
  await editOriginal(env, token, { content: msg });
}

// ---- /ping ---------------------------------------------------------------

export async function handlePing(env: Env, i: AppCmdInteraction, ctx: ExecutionContext): Promise<Response> {
  ctx.waitUntil((async () => {
    const cards = await loadCards(env);
    await editOriginal(env, i.token, {
      content: `pong · ${cards.length} cards · running on Cloudflare Workers`,
      flags: InteractionResponseFlags.EPHEMERAL,
    });
  })());
  return deferred(true);
}

// ---- /price --------------------------------------------------------------

export async function handlePrice(env: Env, i: AppCmdInteraction, ctx: ExecutionContext): Promise<Response> {
  const query = String(getOpt(i, "query") ?? "");
  ctx.waitUntil((async () => {
    const cards = await loadCards(env);
    const matches = findCards(query, cards);
    if (!matches.length) {
      await editOriginal(env, i.token, { embeds: [noMatchEmbed(query)] });
      return;
    }
    const thb = await getThbRate(env);
    if (matches.length > 1) {
      await editOriginal(env, i.token, { embeds: [multiMatchEmbed(query, matches, thb)] });
      return;
    }
    const card = matches[0];
    let live = null;
    let sales: Array<{ orderDate?: string; quantity?: number; purchasePrice?: number; variant?: string }> = [];
    try {
      [live, sales] = await Promise.all([
        fetchProductDetail(card.product_id).catch(() => null),
        fetchLatestSales(card.product_id, 5).catch(() => []),
      ]);
    } catch {
      // best effort
    }
    const summary = await getSummary(env);
    const trends = summary ? indexByProductId(summary)[String(card.product_id)] || {} : {};
    await editOriginal(env, i.token, {
      embeds: [priceEmbed(card, live, sales, trends, thb)],
    });
  })());
  return deferred(false);
}

// ---- /top ----------------------------------------------------------------

export async function handleTop(env: Env, i: AppCmdInteraction, ctx: ExecutionContext): Promise<Response> {
  const range = String(getOpt(i, "range") ?? "d7");
  const kind = String(getOpt(i, "kind") ?? "gainers") as "gainers" | "losers" | "sellers";
  ctx.waitUntil((async () => {
    const summary = (await getSummary(env)) || (await fetchAndCacheSummary(env));
    const thb = await getThbRate(env);
    const items = summary ? topItems(summary, range, kind, 10) : [];
    await editOriginal(env, i.token, {
      embeds: [topEmbed(range, kind, items, thb, summary?.last_updated)],
    });
  })());
  return deferred(false);
}

// ---- /heat ---------------------------------------------------------------

export async function handleHeat(env: Env, i: AppCmdInteraction, ctx: ExecutionContext): Promise<Response> {
  ctx.waitUntil((async () => {
    const summary = (await getSummary(env)) || (await fetchAndCacheSummary(env));
    const thb = await getThbRate(env);
    if (!summary) {
      await editOriginal(env, i.token, { content: "Magical Meta data unavailable right now — try again in a minute." });
      return;
    }
    await editOriginal(env, i.token, { embeds: [heatEmbed(summary, thb)] });
  })());
  return deferred(false);
}

// ---- /setdigest ----------------------------------------------------------

export async function handleSetDigest(env: Env, i: AppCmdInteraction, ctx: ExecutionContext): Promise<Response> {
  ctx.waitUntil((async () => {
    if (!i.channel_id) {
      await fail(env, i.token, "Couldn't read this channel — try again from inside a server channel.");
      return;
    }
    await env.CONFIG.put("digest_channel_id", i.channel_id);
    await editOriginal(env, i.token, {
      content: `✅ Daily digest will post in <#${i.channel_id}> at 09:00 Asia/Bangkok.`,
      flags: InteractionResponseFlags.EPHEMERAL,
    });
  })());
  return deferred(true);
}

// ---- /digest -------------------------------------------------------------

export async function handleDigest(env: Env, i: AppCmdInteraction, ctx: ExecutionContext): Promise<Response> {
  ctx.waitUntil((async () => {
    const summary = (await getSummary(env)) || (await fetchAndCacheSummary(env));
    const thb = await getThbRate(env);
    if (!summary) {
      await fail(env, i.token, "Magical Meta data unavailable — try again in a minute.");
      return;
    }
    const embeds = [
      topEmbed("d7", "gainers", topItems(summary, "d7", "gainers", 5), thb, summary.last_updated),
      topEmbed("d7", "losers", topItems(summary, "d7", "losers", 5), thb, summary.last_updated),
      topEmbed("d7", "sellers", topItems(summary, "d7", "sellers", 5), thb, summary.last_updated),
    ];
    await editOriginal(env, i.token, { content: "**🗓️ Riftbound digest (7d)**", embeds });
  })());
  return deferred(false);
}

// ---- /watch /unwatch /watchlist -----------------------------------------

async function loadWatches(env: Env, uid: string): Promise<Watch[]> {
  const raw = await env.WATCHLISTS.get(uid, "json");
  return (raw as Watch[]) || [];
}
async function saveWatches(env: Env, uid: string, watches: Watch[]): Promise<void> {
  if (watches.length === 0) {
    await env.WATCHLISTS.delete(uid);
  } else {
    await env.WATCHLISTS.put(uid, JSON.stringify(watches));
  }
}

async function currentPriceFor(env: Env, pid: number): Promise<number | null> {
  const summary = await getSummary(env);
  if (summary) {
    const idx = indexByProductId(summary);
    const trend = idx[String(pid)] || {};
    for (const r of ["h24", "d7"]) {
      const rec = trend[r];
      if (rec && typeof rec.market_price === "number") return rec.market_price;
    }
  }
  try {
    const live = await fetchProductDetail(pid);
    if (live && typeof live.marketPrice === "number") return live.marketPrice;
  } catch {
    /* ignore */
  }
  return null;
}

export async function handleWatch(env: Env, i: AppCmdInteraction, ctx: ExecutionContext): Promise<Response> {
  const query = String(getOpt(i, "query") ?? "");
  const threshold = Number(getOpt(i, "threshold_pct") ?? 10);
  ctx.waitUntil((async () => {
    const uid = userIdOf(i);
    if (!uid) {
      await fail(env, i.token, "Couldn't identify your user — try again.");
      return;
    }
    const cards = await loadCards(env);
    const matches = findCards(query, cards);
    if (!matches.length) {
      await editOriginal(env, i.token, { embeds: [noMatchEmbed(query)] });
      return;
    }
    if (matches.length > 1) {
      await editOriginal(env, i.token, { embeds: [multiMatchEmbed(query, matches, null)] });
      return;
    }
    const card = matches[0];
    const baseline = await currentPriceFor(env, card.product_id);
    if (baseline === null) {
      await fail(env, i.token, `Couldn't get a baseline price for \`${card.product_id}\` — try again in a moment.`);
      return;
    }
    const watches = await loadWatches(env, uid);
    const filtered = watches.filter((w) => w.product_id !== card.product_id);
    filtered.push({
      product_id: card.product_id,
      name: card.name,
      baseline_price: baseline,
      threshold_pct: threshold,
      added_at: new Date().toISOString(),
    });
    await saveWatches(env, uid, filtered);
    await editOriginal(env, i.token, {
      content: `👀 Watching **${card.name}** (\`${card.product_id}\`) from baseline **$${baseline.toFixed(2)}** — alert when ≥ ${threshold.toFixed(0)}% move. You'll get a DM.`,
      flags: InteractionResponseFlags.EPHEMERAL,
    });
  })());
  return deferred(true);
}

export async function handleUnwatch(env: Env, i: AppCmdInteraction, ctx: ExecutionContext): Promise<Response> {
  const query = String(getOpt(i, "query") ?? "").trim();
  ctx.waitUntil((async () => {
    const uid = userIdOf(i);
    const watches = await loadWatches(env, uid);
    if (!watches.length) {
      await editOriginal(env, i.token, { content: "Your watchlist is empty.", flags: InteractionResponseFlags.EPHEMERAL });
      return;
    }
    const before = watches.length;
    let next: Watch[];
    if (/^\d+$/.test(query)) {
      const pid = parseInt(query, 10);
      next = watches.filter((w) => w.product_id !== pid);
    } else {
      const needle = query.toLowerCase();
      next = watches.filter((w) => !(w.name || "").toLowerCase().includes(needle));
    }
    const removed = before - next.length;
    await saveWatches(env, uid, next);
    await editOriginal(env, i.token, {
      content: `Removed **${removed}** card${removed === 1 ? "" : "s"} from your watchlist.`,
      flags: InteractionResponseFlags.EPHEMERAL,
    });
  })());
  return deferred(true);
}

export async function handleWatchlist(env: Env, i: AppCmdInteraction, ctx: ExecutionContext): Promise<Response> {
  ctx.waitUntil((async () => {
    const uid = userIdOf(i);
    const watches = await loadWatches(env, uid);
    if (!watches.length) {
      await editOriginal(env, i.token, {
        content: "Your watchlist is empty. Use `/watch <name>` to add cards.",
        flags: InteractionResponseFlags.EPHEMERAL,
      });
      return;
    }
    const thb = await getThbRate(env);
    const lines: string[] = [];
    for (const w of watches) {
      const current = await currentPriceFor(env, w.product_id);
      let pctStr = "";
      if (typeof current === "number" && typeof w.baseline_price === "number" && w.baseline_price) {
        const pct = ((current - w.baseline_price) / w.baseline_price) * 100;
        const arrow = pct > 0 ? "↑" : pct < 0 ? "↓" : "~";
        pctStr = ` · ${arrow} ${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`;
      }
      const baseStr = `$${w.baseline_price.toFixed(2)}${thb ? ` (฿${Math.round(w.baseline_price * thb)})` : ""}`;
      const curStr = current === null ? "—" : `$${current.toFixed(2)}${thb ? ` (฿${Math.round(current * thb)})` : ""}`;
      lines.push(
        `• [${w.name}](https://www.tcgplayer.com/product/${w.product_id}) (\`${w.product_id}\`) — baseline ${baseStr} → now ${curStr}${pctStr} · @ ${w.threshold_pct.toFixed(0)}%`,
      );
    }
    await editOriginal(env, i.token, {
      embeds: [
        { title: "📋 Your watchlist", description: lines.join("\n"), color: 0x3498db },
      ],
      flags: InteractionResponseFlags.EPHEMERAL,
    });
  })());
  return deferred(true);
}

export { watchAlertEmbed, currentPriceFor, loadWatches, saveWatches };
