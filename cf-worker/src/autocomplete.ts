// Autocomplete handlers. The response must be a single JSON object with
// type=8 and data.choices[]. Each choice has name (≤100 chars) and value.

import { findCards, loadCards } from "./cards";
import { InteractionResponseType } from "./types";
import type { Env, Watch } from "./types";

interface AutoInteraction {
  data: {
    name: string;
    options?: Array<{ name: string; type: number; value: string; focused?: boolean }>;
  };
  member?: { user?: { id: string } };
  user?: { id: string };
}

function jsonResponse(choices: Array<{ name: string; value: string }>): Response {
  return new Response(
    JSON.stringify({ type: InteractionResponseType.APPLICATION_COMMAND_AUTOCOMPLETE_RESULT, data: { choices } }),
    { headers: { "Content-Type": "application/json" } },
  );
}

function focusedQuery(i: AutoInteraction, paramName: string): string {
  const opt = (i.data.options || []).find((o) => o.name === paramName && o.focused);
  return opt ? String(opt.value || "") : "";
}

export async function handlePriceAutocomplete(env: Env, i: AutoInteraction): Promise<Response> {
  const query = focusedQuery(i, "query");
  const cards = await loadCards(env);
  const matches = query.trim() ? findCards(query, cards) : cards.slice(0, 25);
  const choices = matches.slice(0, 25).map((c) => {
    const price = typeof c.market_price === "number" ? ` · $${c.market_price.toFixed(2)}` : "";
    const label = `${c.name} · ${c.set_name || "—"}${price}`.slice(0, 100);
    return { name: label, value: String(c.product_id) };
  });
  return jsonResponse(choices);
}

export async function handleUnwatchAutocomplete(env: Env, i: AutoInteraction): Promise<Response> {
  const query = focusedQuery(i, "query").trim().toLowerCase();
  const uid = i.member?.user?.id || i.user?.id || "";
  const watches = ((await env.WATCHLISTS.get(uid, "json")) as Watch[] | null) || [];
  const matches = watches.filter((w) =>
    !query || (w.name || "").toLowerCase().includes(query) || query === String(w.product_id),
  );
  const choices = matches.slice(0, 25).map((w) => ({
    name: `${w.name} (#${w.product_id})`.slice(0, 100),
    value: String(w.product_id),
  }));
  return jsonResponse(choices);
}
