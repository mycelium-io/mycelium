// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

/**
 * Session sub-room SSE subscription.
 *
 * When a coordination session spawns inside a room, the backend creates a
 * sub-room named `{room}:session:{id}`. Coordination ticks, proposals, and
 * consensus events are posted to that sub-room — not the parent room.
 *
 * This module subscribes to sub-room SSE streams (idempotent per sub-room)
 * and forwards every message to handleMessage for dispatch.
 */

import { CHANNEL_ID, type ChannelConfig } from "../config.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };
type HandleMessageFn = (runtime: any, cfg: ChannelConfig, msg: any, log: Logger) => void;

const _subscribedSessions = new Set<string>();

export function clearSubscribedSessions(): void {
  _subscribedSessions.clear();
}

export function startSessionSSE(
  runtime: any,
  cfg: ChannelConfig,
  sessionRoom: string,
  abort: AbortController,
  handleMessage: HandleMessageFn,
  log: Logger,
): void {
  if (_subscribedSessions.has(sessionRoom)) return;
  _subscribedSessions.add(sessionRoom);

  const signal = abort.signal;
  if (signal.aborted) return;

  const sseUrl = `${cfg.backendUrl}/rooms/${encodeURIComponent(sessionRoom)}/messages/stream`;
  log.info(`[${CHANNEL_ID}] subscribing to session sub-room: ${sessionRoom}`);

  (async () => {
    while (!signal.aborted) {
      try {
        const res = await fetch(sseUrl, {
          headers: { Accept: "text/event-stream" },
          signal,
        });
        if (!res.ok || !res.body) {
          log.warn(
            `[${CHANNEL_ID}] session SSE ${res.status} for ${sessionRoom} — retry 5s`,
          );
          await new Promise((r) => setTimeout(r, 5000));
          continue;
        }

        log.info(`[${CHANNEL_ID}] session SSE connected: ${sessionRoom}`);
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
        log.warn(`[${CHANNEL_ID}] session SSE error: ${err?.message} — retry 5s`);
        await new Promise((r) => setTimeout(r, 5000));
      }
    }
  })();
}
