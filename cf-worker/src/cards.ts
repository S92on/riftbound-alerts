// Card catalogue: stored as a single JSON blob in KV under the key "all".
// We keep an in-memory cache per worker isolate so /price autocomplete doesn't
// pay the KV read latency on every keystroke.

import type { Card, Env } from "./types";

let _cache: { cards: Card[]; fetchedAt: number } | null = null;
const MEMORY_TTL_MS = 10 * 60 * 1000;

export async function loadCards(env: Env): Promise<Card[]> {
  if (_cache && Date.now() - _cache.fetchedAt < MEMORY_TTL_MS) return _cache.cards;
  const raw = await env.CARDS.get("all", "json");
  const cards = (raw as Card[] | null) || [];
  _cache = { cards, fetchedAt: Date.now() };
  return cards;
}

export function findCards(query: string, cards: Card[]): Card[] {
  const q = query.trim();
  if (!q) return [];
  if (/^\d+$/.test(q)) {
    const pid = parseInt(q, 10);
    return cards.filter((c) => c.product_id === pid);
  }
  const needle = q.toLowerCase();
  return cards.filter((c) => c.name && c.name.toLowerCase().includes(needle));
}

export function findCardByPid(pid: number, cards: Card[]): Card | undefined {
  return cards.find((c) => c.product_id === pid);
}
