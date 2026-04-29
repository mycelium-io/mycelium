// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Room SSE subscription — the single inbound surface for the channel plugin.
 *
 * This is the ONE SSE subscription per gateway instance. All events flow through
 * here: broadcast messages, coordination ticks (from session sub-rooms, discovered
 * lazily), and consensus events. Per-agent /agents/{handle}/stream subscriptions
 * are gone.
 *
 * Unlike session-sse.ts, the parent room SSE uses the gateway-lifetime
 * AbortController directly — each plugin installation binds to a single
 * parent room (cfg.room), and that subscription should live for the full
 * gateway lifetime. A 404 still breaks the loop (the room was deleted)
 * rather than retrying forever (#175).
 */

import { CHANNEL_ID, type ChannelConfig } from "../config.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };
type HandleMessageFn = (runtime: any, cfg: ChannelConfig, msg: any, log: Logger) => void;

const MAX_CONSECUTIVE_ERRORS = 6;

export function startRoomSSE(
  runtime: any,
  cfg: ChannelConfig,
  abort: AbortController,
  handleMessage: HandleMessageFn,
  log: Logger,
): void {
  const signal = abort.signal;
  const sseUrl = `${cfg.backendUrl}/rooms/${encodeURIComponent(cfg.room)}/messages/stream`;

  (async () => {
    let consecutiveErrors = 0;

    while (!signal.aborted) {
      try {
        const res = await fetch(sseUrl, {
          headers: { Accept: "text/event-stream" },
          signal,
        });
        if (!res.ok || !res.body) {
          if (res.status === 404) {
            log.warn(
              `[${CHANNEL_ID}] room SSE 404 for ${cfg.room} — room gone, stopping`,
            );
            return;
          }
          consecutiveErrors++;
          if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
            log.warn(
              `[${CHANNEL_ID}] room SSE for ${cfg.room}: ${consecutiveErrors} consecutive errors — giving up`,
            );
            return;
          }
          const backoff = Math.min(5000 * 2 ** (consecutiveErrors - 1), 30_000);
          log.warn(
            `[${CHANNEL_ID}] SSE ${res.status} — retry ${backoff / 1000}s (${consecutiveErrors}/${MAX_CONSECUTIVE_ERRORS})`,
          );
          await new Promise((r) => setTimeout(r, backoff));
          continue;
        }

        consecutiveErrors = 0;
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
          }
        }
      } catch (err: any) {
        if (signal.aborted) return;
        consecutiveErrors++;
        if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
          log.warn(
            `[${CHANNEL_ID}] room SSE for ${cfg.room}: ${consecutiveErrors} consecutive errors — giving up`,
          );
          return;
        }
        const backoff = Math.min(5000 * 2 ** (consecutiveErrors - 1), 30_000);
        log.warn(
          `[${CHANNEL_ID}] SSE error: ${err?.message ?? err} — retry ${backoff / 1000}s (${consecutiveErrors}/${MAX_CONSECUTIVE_ERRORS})`,
        );
        await new Promise((r) => setTimeout(r, backoff));
      }
    }
  })();
}
