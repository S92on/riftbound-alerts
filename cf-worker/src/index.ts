// Worker entrypoint: routes Discord interactions and cron triggers.

import {
  handleDigest,
  handleHeat,
  handlePing,
  handlePrice,
  handleSetDigest,
  handleTop,
  handleUnwatch,
  handleWatch,
  handleWatchlist,
} from "./commands";
import { handlePriceAutocomplete, handleUnwatchAutocomplete } from "./autocomplete";
import {
  checkWatchlists,
  postDailyDigest,
  refreshCards,
  refreshMagicalMeta,
} from "./scheduled";
import { Env, InteractionResponseType, InteractionType } from "./types";
import { verifyDiscordRequest } from "./verify";

export default {
  async fetch(request: Request, env: Env, ctx: ExecutionContext): Promise<Response> {
    if (request.method !== "POST") {
      return new Response("OK", { status: 200 });
    }
    const { valid, body } = await verifyDiscordRequest(request, env.DISCORD_PUBLIC_KEY);
    if (!valid) return new Response("invalid request signature", { status: 401 });
    const interaction = JSON.parse(body);
    if (interaction.type === InteractionType.PING) {
      return new Response(JSON.stringify({ type: InteractionResponseType.PONG }), {
        headers: { "Content-Type": "application/json" },
      });
    }
    if (interaction.type === InteractionType.APPLICATION_COMMAND) {
      const name = interaction.data?.name;
      switch (name) {
        case "ping":       return handlePing(env, interaction, ctx);
        case "price":      return handlePrice(env, interaction, ctx);
        case "top":        return handleTop(env, interaction, ctx);
        case "heat":       return handleHeat(env, interaction, ctx);
        case "setdigest":  return handleSetDigest(env, interaction, ctx);
        case "digest":     return handleDigest(env, interaction, ctx);
        case "watch":      return handleWatch(env, interaction, ctx);
        case "unwatch":    return handleUnwatch(env, interaction, ctx);
        case "watchlist":  return handleWatchlist(env, interaction, ctx);
      }
      return new Response(JSON.stringify({
        type: InteractionResponseType.CHANNEL_MESSAGE_WITH_SOURCE,
        data: { content: `Unknown command: ${name}` },
      }), { headers: { "Content-Type": "application/json" } });
    }
    if (interaction.type === InteractionType.APPLICATION_COMMAND_AUTOCOMPLETE) {
      const name = interaction.data?.name;
      if (name === "price" || name === "watch") return handlePriceAutocomplete(env, interaction);
      if (name === "unwatch") return handleUnwatchAutocomplete(env, interaction);
      return new Response(JSON.stringify({ type: InteractionResponseType.APPLICATION_COMMAND_AUTOCOMPLETE_RESULT, data: { choices: [] } }), { headers: { "Content-Type": "application/json" } });
    }
    return new Response("unhandled interaction type", { status: 400 });
  },

  async scheduled(event: ScheduledController, env: Env, ctx: ExecutionContext): Promise<void> {
    // wrangler.toml crons in declaration order:
    //   "*/30 * * * *"   → refresh Magical Meta
    //   "15 * * * *"     → check watchlists
    //   "0 2 * * *"      → daily digest (09:00 Asia/Bangkok)
    //   "30 3 * * *"     → refresh Riftbound card catalogue from TCGplayer
    switch (event.cron) {
      case "*/30 * * * *":
        ctx.waitUntil(refreshMagicalMeta(env));
        return;
      case "15 * * * *":
        ctx.waitUntil(checkWatchlists(env));
        return;
      case "0 2 * * *":
        ctx.waitUntil(postDailyDigest(env));
        return;
      case "30 3 * * *":
        ctx.waitUntil(refreshCards(env).catch(() => 0));
        return;
    }
  },
};
