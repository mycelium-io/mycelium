// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Room SSE subscription — the single inbound surface for the channel plugin.
 *
 * This is the ONE SSE subscription per gateway instance. All events flow through
 * here: broadcast messages, coordination ticks (from session sub-rooms, discovered
 * lazily), and consensus events. Per-agent /agents/{handle}/stream subscriptions
 * are gone.
 */

import { CHANNEL_ID, type ChannelConfig } from "../config.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };
type HandleMessageFn = (runtime: any, cfg: ChannelConfig, msg: any, log: Logger) => void;

export function startRoomSSE(
  runtime: any,
  cfg: ChannelConfig,
  abort: AbortController,
  handleMessage: HandleMessageFn,
  log: Logger,
): void {
  const signal = abort.signal;
  const sseUrl = `${cfg.backendUrl}/api/rooms/${encodeURIComponent(cfg.room)}/messages/stream`;

  // Tombstone only after this many consecutive 404s — mirrors the Python daemon's
  // _404_MAX_RETRIES logic so both delivery paths behave identically on deletion.
  const NOT_FOUND_MAX_RETRIES = 3;
  let notFoundRetries = 0;

  (async () => {
    while (!signal.aborted) {
      try {
        const res = await fetch(sseUrl, {
          headers: { Accept: "text/event-stream" },
          signal,
        });
        if (res.status === 404) {
          notFoundRetries++;
          if (notFoundRetries < NOT_FOUND_MAX_RETRIES) {
            log.warn(
              `[${CHANNEL_ID}] room SSE 404 for ${cfg.room} (attempt ${notFoundRetries}/${NOT_FOUND_MAX_RETRIES}) — retry 15s`,
            );
            await new Promise((r) => setTimeout(r, 15_000));
            continue;
          }
          log.warn(
            `[${CHANNEL_ID}] room SSE 404 for ${cfg.room} after ${notFoundRetries} attempts — room deleted, stopping`,
          );
          return;
        }
        if (!res.ok || !res.body) {
          // Non-404 error: reset the counter so interleaved 5xx responses
          // during a rolling restart don't accumulate toward the 404 threshold.
          notFoundRetries = 0;
          log.warn(`[${CHANNEL_ID}] SSE ${res.status} — retry 5s`);
          await new Promise((r) => setTimeout(r, 5000));
          continue;
        }

        notFoundRetries = 0;
        log.info(
          `[${CHANNEL_ID}] SSE connected: ${cfg.room} (agents: ${cfg.agents.join(", ")})`,
        );
        const reader = (res.body as any).getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split("\n\n");
          buffer = blocks.pop() ?? "";

          for (const block of blocks) {
            const dataLine = block.split("\n").find((l: string) => l.startsWith("data: "));
            if (!dataLine) continue;
            const raw = dataLine.slice(6).trim();
            if (!raw || raw === "{}") continue;

            let msg: any;
            try {
              msg = JSON.parse(raw);
            } catch {
              continue;
            }

            handleMessage(runtime, cfg, msg, log);
            // Stop the subscription loop permanently on room deletion.
            // The room no longer exists on the hub; retrying would 404-loop.
            if (msg.message_type === "room_deleted") {
              log.info(
                `[${CHANNEL_ID}] room "${cfg.room}" deleted — stopping SSE subscription`,
              );
              return;
            }
          }
        }
      } catch (err: any) {
        if (signal.aborted) return;
        log.warn(`[${CHANNEL_ID}] SSE error: ${err?.message ?? err} — retry 5s`);
        await new Promise((r) => setTimeout(r, 5000));
      }
    }
  })();
}
