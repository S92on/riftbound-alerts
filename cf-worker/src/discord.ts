// Thin Discord REST helpers used by deferred replies, DMs, and cron jobs.

import type { Env } from "./types";

const API = "https://discord.com/api/v10";

interface FetchOpts {
  method?: string;
  body?: unknown;
  authBot?: boolean;
}

/** Strip BOM, surrounding whitespace, and trailing CR/LF that PowerShell pipes
 * love to inject into wrangler secret values. */
function clean(s: string | undefined): string {
  if (!s) return "";
  return s.replace(/^﻿/, "").replace(/[\s\r\n]+$/, "").trim();
}

export async function discordFetch(env: Env, path: string, opts: FetchOpts = {}): Promise<Response> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    "User-Agent": "RiftboundBot (Cloudflare Worker, +https://github.com/S92on/riftbound-alerts)",
  };
  if (opts.authBot) headers["Authorization"] = `Bot ${clean(env.DISCORD_TOKEN)}`;
  return fetch(`${API}${path}`, {
    method: opts.method || "GET",
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
}

/** Edit the deferred response we already acked with type 5. */
export async function editOriginal(
  env: Env,
  interactionToken: string,
  payload: { content?: string; embeds?: unknown[]; flags?: number },
): Promise<Response> {
  const appId = clean(env.DISCORD_APPLICATION_ID);
  const r = await discordFetch(
    env,
    `/webhooks/${appId}/${clean(interactionToken)}/messages/@original`,
    { method: "PATCH", body: payload },
  );
  if (!r.ok) {
    const text = await r.text().catch(() => "");
    console.log("[editOriginal] %d %s", r.status, text.slice(0, 200));
  }
  return r;
}

/** Send a non-interaction message to a channel (used by daily digest). */
export async function postChannelMessage(
  env: Env,
  channelId: string,
  payload: { content?: string; embeds?: unknown[] },
): Promise<Response> {
  return discordFetch(env, `/channels/${channelId}/messages`, {
    method: "POST",
    body: payload,
    authBot: true,
  });
}

/** Open a DM channel with a user (returns the channel ID). */
export async function openDM(env: Env, userId: string): Promise<string | null> {
  const r = await discordFetch(env, `/users/@me/channels`, {
    method: "POST",
    body: { recipient_id: userId },
    authBot: true,
  });
  if (!r.ok) return null;
  const j = (await r.json()) as { id?: string };
  return j.id || null;
}

export async function dmUser(env: Env, userId: string, payload: { content?: string; embeds?: unknown[] }): Promise<boolean> {
  const channelId = await openDM(env, userId);
  if (!channelId) return false;
  const r = await postChannelMessage(env, channelId, payload);
  return r.ok;
}
