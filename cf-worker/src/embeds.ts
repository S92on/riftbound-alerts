// Discord embed builders. Mirror the Python version's layout 1:1.

import { IMAGE_URL, TCGPLAYER_PRODUCT_URL } from "./tcgplayer";
import { marketDirection, marketHealth, topItems } from "./magicalmeta";
import type { Card, MMItem, MMSummary } from "./types";
import { RANGE_LABEL } from "./types";

const COLOR_OK = 0x2ecc71;
const COLOR_INFO = 0x3498db;
const COLOR_MISS = 0xe74c3c;
const COLOR_WARN = 0xf39c12;

function money(v: unknown, thb: number | null): string {
  if (typeof v !== "number" || !isFinite(v)) return "—";
  let s = `$${v.toFixed(2)}`;
  if (thb) s += ` (฿${Math.round(v * thb).toLocaleString("en-US")})`;
  return s;
}

function pctGlyph(p: unknown): string {
  if (typeof p !== "number") return "—";
  const arrow = p > 0 ? "↑" : p < 0 ? "↓" : "~";
  const sign = p > 0 ? "+" : "";
  return `${arrow} ${sign}${p.toFixed(1)}%`;
}

function trendArrow(recentAvg: number | null, market: number | null): string {
  if (recentAvg === null || market === null || market <= 0) return "";
  const delta = (recentAvg - market) / market;
  if (delta >= 0.05) return `↑ +${(delta * 100).toFixed(0)}% vs market`;
  if (delta <= -0.05) return `↓ ${(delta * 100).toFixed(0)}% vs market`;
  return `~ flat vs market (${(delta * 100).toFixed(0)}%)`;
}

function parseDt(s: string | undefined): Date | null {
  if (!s) return null;
  const d = new Date(s);
  return isNaN(+d) ? null : d;
}

export function noMatchEmbed(query: string) {
  return {
    title: "No match",
    description:
      `No Riftbound card found for \`${query}\`.\n\n` +
      "Try a partial name (e.g. `ahri`) or a TCGplayer product ID (e.g. `653053`).",
    color: COLOR_MISS,
  };
}

export function multiMatchEmbed(query: string, matches: Card[], thb: number | null) {
  const shown = matches.slice(0, 8);
  const overflow = Math.max(matches.length - shown.length, 0);
  const lines = shown.map((c) => {
    const url = TCGPLAYER_PRODUCT_URL(c.product_id);
    return (
      `[\`${c.product_id}\`](${url}) — **${c.name}** · ${c.set_name || "—"} · ${c.rarity || "—"} · ${money(c.market_price, thb)}`
    );
  });
  let desc = lines.join("\n");
  desc += overflow
    ? `\n\n… and **${overflow}** more. Refine your query, or pass a TCGplayer product ID.`
    : "\n\nUse the product ID for a detailed lookup, or pick from autocomplete.";
  return {
    title: `${matches.length} match${matches.length === 1 ? "" : "es"} for \`${query}\``,
    description: desc,
    color: COLOR_INFO,
  };
}

export function priceEmbed(
  card: Card,
  live: { setName?: string; rarityName?: string; marketPrice?: number; lowestPrice?: number; totalListings?: number } | null,
  sales: Array<{ orderDate?: string; quantity?: number; purchasePrice?: number; variant?: string }>,
  mmTrends: Record<string, MMItem>,
  thb: number | null,
) {
  const pid = card.product_id;
  const name = card.name;
  const setName = live?.setName || card.set_name || "—";
  const rarity = live?.rarityName || card.rarity || "—";
  const market = live?.marketPrice ?? card.market_price ?? null;
  const low = live?.lowestPrice ?? card.lowest_price ?? null;
  const listings = live?.totalListings;
  const number = card.number;

  const recentLines: string[] = [];
  const prices: number[] = [];
  for (const s of sales.slice(0, 5)) {
    const ts = parseDt(s.orderDate);
    const when = ts ? `${String(ts.getUTCMonth() + 1).padStart(2, "0")}-${String(ts.getUTCDate()).padStart(2, "0")} ${String(ts.getUTCHours()).padStart(2, "0")}:${String(ts.getUTCMinutes()).padStart(2, "0")}` : "?";
    const qty = s.quantity;
    const price = s.purchasePrice;
    const variant = s.variant || "Normal";
    if (typeof price === "number") prices.push(price);
    recentLines.push(`• \`${when}\` · qty **${qty}** @ ${money(price, thb)} · ${variant}`);
  }
  const avgPrice = prices.length ? prices.reduce((a, b) => a + b, 0) / prices.length : null;
  const arrow = trendArrow(avgPrice, market);

  const desc: string[] = [
    `**${setName}** · ${rarity}${number ? ` · #${number}` : ""}`,
    "",
    `💰 Market **${money(market, thb)}** · Low **${money(low, thb)}**` + (listings ? ` · ${listings} listings` : ""),
  ];
  if (recentLines.length) {
    desc.push("", "**Recent sales (latest 5):**", ...recentLines);
    if (avgPrice !== null) desc.push(`\nAvg: **${money(avgPrice, thb)}**${arrow ? " · " + arrow : ""}`);
  } else {
    desc.push("", "_No recent sales on TCGplayer._");
  }

  const trendLines: string[] = [];
  for (const rangeKey of ["h24", "d7", "d30", "d90"]) {
    const rec = mmTrends[rangeKey];
    if (!rec) continue;
    const bits: string[] = [`**${RANGE_LABEL[rangeKey]}**: ${pctGlyph(rec.percent_change)}`];
    if (typeof rec.quantity_sold === "number" && rec.quantity_sold) bits.push(`qty ${rec.quantity_sold}`);
    if (typeof rec.avg_daily_quantity_sold === "number" && rec.avg_daily_quantity_sold)
      bits.push(`avg/day ${rec.avg_daily_quantity_sold.toFixed(1)}`);
    trendLines.push(bits.join(" · "));
  }
  if (trendLines.length) desc.push("", "**Trend (Magical Meta):**", ...trendLines);

  const footerParts: string[] = [`TCGplayer #${pid}`];
  const now = new Date();
  footerParts.push(`${now.toISOString().slice(0, 16).replace("T", " ")} UTC`);
  if (thb) footerParts.push(`USD→THB ${thb.toFixed(2)}`);
  if (Object.keys(mmTrends).length) footerParts.push("trend via magicalmeta.ink");

  return {
    title: name,
    url: TCGPLAYER_PRODUCT_URL(pid),
    description: desc.join("\n"),
    color: COLOR_OK,
    thumbnail: { url: IMAGE_URL(pid) },
    footer: { text: footerParts.join(" · ") },
  };
}

export function topEmbed(rangeKey: string, kind: "gainers" | "losers" | "sellers", items: MMItem[], thb: number | null, lastUpdated?: string) {
  const rng = RANGE_LABEL[rangeKey] || rangeKey;
  const titles: Record<string, string> = {
    gainers: "📈 Top Gainers",
    losers: "📉 Top Losers",
    sellers: "🔥 Top Sellers",
  };
  if (!items.length) {
    return {
      title: `${titles[kind]} · ${rng}`,
      description: "_No data from Magical Meta yet — refresh in a few minutes._",
      color: COLOR_WARN,
    };
  }
  const lines = items.slice(0, 10).map((it, i) => {
    const pid = it.product_id;
    const url = pid ? TCGPLAYER_PRODUCT_URL(Number(pid)) : null;
    const head = url ? `\`${String(i + 1).padStart(2, " ")}.\` [${it.name || "?"}](${url})` : `\`${String(i + 1).padStart(2, " ")}.\` ${it.name || "?"}`;
    const bits: string[] = [it.set_name || "—", money(it.market_price, thb)];
    if (kind === "gainers" || kind === "losers") {
      bits.push(pctGlyph(it.percent_change));
      if (typeof it.dollar_change === "number") {
        bits.push(`${it.dollar_change >= 0 ? "+" : ""}${money(it.dollar_change, thb)}`);
      }
    } else {
      if (typeof it.quantity_sold === "number") bits.push(`qty **${it.quantity_sold}**`);
      if (typeof it.avg_daily_quantity_sold === "number") bits.push(`avg/day ${it.avg_daily_quantity_sold.toFixed(1)}`);
    }
    return head + "\n   " + bits.join(" · ");
  });
  return {
    title: `${titles[kind]} · ${rng}`,
    description: lines.join("\n"),
    color: COLOR_OK,
    footer: { text: `Source: magicalmeta.ink · data as of ${lastUpdated || "—"}` },
  };
}

export function heatEmbed(summary: MMSummary, thb: number | null) {
  const health = marketHealth(summary);
  const direction = marketDirection(summary, "d7");
  const md = direction.direction || {};
  const heatCount = direction.heat_count;
  const heatByTier = direction.heat_by_tier || {};

  const desc: string[] = [
    `🌐 **Total market value:** ${money(health.total_value, thb)}`,
    `🎴 **Cards tracked:** ${(health.cards_tracked || 0).toLocaleString("en-US")} across ${health.sets_tracked || 0} sets`,
    `📦 **Total qty sold (period):** ${Math.floor(health.total_qty_sold || 0).toLocaleString("en-US")} in ${Math.floor(health.total_tx || 0).toLocaleString("en-US")} transactions`,
    `📅 **Avg daily:** ${Math.round(health.avg_daily_qty || 0)} qty · ${Math.round(health.avg_daily_tx || 0)} tx`,
  ];
  if (md && typeof md === "object" && Object.keys(md).length) {
    const bits = [
      `📈 gainers **${(md.gainers || 0).toLocaleString("en-US")}**`,
      `📉 decliners **${(md.decliners || 0).toLocaleString("en-US")}**`,
      `↔️ flat **${(md.flat || 0).toLocaleString("en-US")}**`,
    ];
    if (typeof md.breadth === "number") bits.push(`breadth **${md.breadth}%**`);
    desc.push("", `**Direction (7d):** ${bits.join(" · ")}`);
  }
  if (typeof heatCount === "number") {
    const tierBits = (["high", "mid", "low"] as const)
      .filter((k) => typeof heatByTier[k] === "number")
      .map((k) => `${k} **${heatByTier[k]}**`);
    let line = `**Heat (7d):** 🔥 **${heatCount.toLocaleString("en-US")}** hot listings`;
    if (tierBits.length) line += ` (${tierBits.join(" · ")})`;
    desc.push(line);
  }
  return {
    title: "📊 Riftbound Market Heat",
    description: desc.join("\n"),
    color: COLOR_INFO,
    footer: { text: `Source: magicalmeta.ink · last_updated ${health.last_updated || "—"}` },
  };
}

export function watchAlertEmbed(name: string, pid: number, baseline: number, current: number, threshold: number, pct: number) {
  return {
    title: `🔔 ${name} moved ${pct >= 0 ? "+" : ""}${pct.toFixed(1)}%`,
    description:
      `Baseline **$${baseline.toFixed(2)}** → now **$${current.toFixed(2)}**\n` +
      `Threshold was **${threshold.toFixed(1)}%**\n\n` +
      `[Open on TCGplayer](${TCGPLAYER_PRODUCT_URL(pid)})`,
    color: pct < 0 ? COLOR_WARN : COLOR_OK,
    thumbnail: { url: IMAGE_URL(pid) },
  };
}

export { topItems };
