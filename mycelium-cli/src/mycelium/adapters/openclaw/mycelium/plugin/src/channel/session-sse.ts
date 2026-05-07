// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Session sub-room SSE subscription.
 *
 * When a coordination session spawns inside a room, the backend creates a
 * sub-room named `{room}:session:{id}`. Coordination ticks, proposals, and
 * consensus events are posted to that sub-room — not the parent room.
 *
 * This module subscribes to sub-room SSE streams (idempotent per sub-room)
 * and forwards every message to handleMessage for dispatch.
 *
 * Each session gets its own AbortController so it can be torn down
 * independently when the session reaches a terminal state (agreed/failed)
 * or the room is deleted. This prevents the leaked-connection accumulation
 * described in #175.
 */

import { CHANNEL_ID, type ChannelConfig } from "../config.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };
type HandleMessageFn = (runtime: any, cfg: ChannelConfig, msg: any, log: Logger) => void;

const MAX_TRANSIENT_RETRIES = 6;

interface SessionHandle {
  ctrl: AbortController;
  detach: () => void;
}

const _sessions = new Map<string, SessionHandle>();

export function clearSubscribedSessions(): void {
  for (const [, h] of _sessions) {
    h.detach();
    h.ctrl.abort();
  }
  _sessions.clear();
}

/** Abort and remove a single session subscription. */
export function stopSessionSSE(sessionRoom: string, log?: Logger): void {
  const h = _sessions.get(sessionRoom);
  if (h) {
    h.detach();
    h.ctrl.abort();
    _sessions.delete(sessionRoom);
    log?.info(`[${CHANNEL_ID}] session SSE stopped: ${sessionRoom}`);
  }
}

/** Returns the set of currently-subscribed session room names. */
export function subscribedSessionRooms(): ReadonlySet<string> {
  return new Set(_sessions.keys());
}

export function startSessionSSE(
  runtime: any,
  cfg: ChannelConfig,
  sessionRoom: string,
  _gatewayAbort: AbortController,
  handleMessage: HandleMessageFn,
  log: Logger,
): void {
  if (_sessions.has(sessionRoom)) return;

  const sessionAbort = new AbortController();
  const onGatewayAbort = () => sessionAbort.abort();
  _gatewayAbort.signal.addEventListener("abort", onGatewayAbort);

  _sessions.set(sessionRoom, {
    ctrl: sessionAbort,
    detach: () => _gatewayAbort.signal.removeEventListener("abort", onGatewayAbort),
  });

  const signal = sessionAbort.signal;
  if (signal.aborted) return;

  const sseUrl = `${cfg.backendUrl}/api/rooms/${encodeURIComponent(sessionRoom)}/messages/stream`;
  log.info(`[${CHANNEL_ID}] subscribing to session sub-room: ${sessionRoom}`);

  (async () => {
    let transientFailures = 0;

    while (!signal.aborted) {
      try {
        const res = await fetch(sseUrl, {
          headers: { Accept: "text/event-stream" },
          signal,
        });

        if (res.status === 404) {
          log.info(
            `[${CHANNEL_ID}] session room gone (404): ${sessionRoom} — unsubscribing`,
          );
          stopSessionSSE(sessionRoom);
          return;
        }

        if (!res.ok || !res.body) {
          transientFailures++;
          if (transientFailures >= MAX_TRANSIENT_RETRIES) {
            log.warn(
              `[${CHANNEL_ID}] session SSE gave up after ${MAX_TRANSIENT_RETRIES} failures for ${sessionRoom}`,
            );
            stopSessionSSE(sessionRoom);
            return;
          }
          const backoff = Math.min(5000 * 2 ** (transientFailures - 1), 30_000);
          log.warn(
            `[${CHANNEL_ID}] session SSE ${res.status} for ${sessionRoom} — retry ${transientFailures}/${MAX_TRANSIENT_RETRIES} in ${backoff}ms`,
          );
          await new Promise((r) => setTimeout(r, backoff));
          continue;
        }

        transientFailures = 0;
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
        transientFailures++;
        if (transientFailures >= MAX_TRANSIENT_RETRIES) {
          log.warn(
            `[${CHANNEL_ID}] session SSE gave up after ${MAX_TRANSIENT_RETRIES} errors for ${sessionRoom}`,
          );
          stopSessionSSE(sessionRoom);
          return;
        }
        const backoff = Math.min(5000 * 2 ** (transientFailures - 1), 30_000);
        log.warn(
          `[${CHANNEL_ID}] session SSE error: ${err?.message} — retry ${transientFailures}/${MAX_TRANSIENT_RETRIES} in ${backoff}ms`,
        );
        await new Promise((r) => setTimeout(r, backoff));
      }
    }
  })();
}
