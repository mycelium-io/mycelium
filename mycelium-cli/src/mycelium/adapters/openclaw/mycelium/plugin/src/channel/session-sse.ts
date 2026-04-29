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
 * or the room is deleted — fixing the connection leak described in #175.
 */

import { CHANNEL_ID, type ChannelConfig } from "../config.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };
type HandleMessageFn = (runtime: any, cfg: ChannelConfig, msg: any, log: Logger) => void;

const MAX_CONSECUTIVE_ERRORS = 6;

const _sessionControllers = new Map<string, AbortController>();

export function getSessionControllers(): Map<string, AbortController> {
  return _sessionControllers;
}

export function abortSession(sessionRoom: string, log: Logger): void {
  const ctrl = _sessionControllers.get(sessionRoom);
  if (ctrl) {
    ctrl.abort();
    _sessionControllers.delete(sessionRoom);
    log.info(`[${CHANNEL_ID}] session SSE torn down: ${sessionRoom}`);
  }
}

export function abortAllSessions(): void {
  for (const ctrl of _sessionControllers.values()) {
    ctrl.abort();
  }
  _sessionControllers.clear();
}

export function isSessionSubscribed(sessionRoom: string): boolean {
  return _sessionControllers.has(sessionRoom);
}

export function startSessionSSE(
  runtime: any,
  cfg: ChannelConfig,
  sessionRoom: string,
  gatewayAbort: AbortController,
  handleMessage: HandleMessageFn,
  log: Logger,
): void {
  if (_sessionControllers.has(sessionRoom)) return;

  const sessionCtrl = new AbortController();
  _sessionControllers.set(sessionRoom, sessionCtrl);

  const onGatewayAbort = () => sessionCtrl.abort();
  gatewayAbort.signal.addEventListener("abort", onGatewayAbort);

  const signal = sessionCtrl.signal;
  if (signal.aborted) return;

  const sseUrl = `${cfg.backendUrl}/rooms/${encodeURIComponent(sessionRoom)}/messages/stream`;
  log.info(`[${CHANNEL_ID}] subscribing to session sub-room: ${sessionRoom}`);

  (async () => {
    let consecutiveErrors = 0;

    try {
      while (!signal.aborted) {
        try {
          const res = await fetch(sseUrl, {
            headers: { Accept: "text/event-stream" },
            signal,
          });
          if (!res.ok || !res.body) {
            if (res.status === 404) {
              log.info(
                `[${CHANNEL_ID}] session SSE 404 for ${sessionRoom} — room gone, stopping`,
              );
              break;
            }
            consecutiveErrors++;
            if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
              log.warn(
                `[${CHANNEL_ID}] session SSE for ${sessionRoom}: ${consecutiveErrors} consecutive errors — giving up`,
              );
              break;
            }
            const backoff = Math.min(5000 * 2 ** (consecutiveErrors - 1), 30_000);
            log.warn(
              `[${CHANNEL_ID}] session SSE ${res.status} for ${sessionRoom} — retry ${backoff / 1000}s (${consecutiveErrors}/${MAX_CONSECUTIVE_ERRORS})`,
            );
            await new Promise((r) => setTimeout(r, backoff));
            continue;
          }

          consecutiveErrors = 0;
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
          consecutiveErrors++;
          if (consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
            log.warn(
              `[${CHANNEL_ID}] session SSE for ${sessionRoom}: ${consecutiveErrors} consecutive errors — giving up`,
            );
            break;
          }
          const backoff = Math.min(5000 * 2 ** (consecutiveErrors - 1), 30_000);
          log.warn(
            `[${CHANNEL_ID}] session SSE error for ${sessionRoom}: ${err?.message} — retry ${backoff / 1000}s (${consecutiveErrors}/${MAX_CONSECUTIVE_ERRORS})`,
          );
          await new Promise((r) => setTimeout(r, backoff));
        }
      }
    } finally {
      _sessionControllers.delete(sessionRoom);
      gatewayAbort.signal.removeEventListener("abort", onGatewayAbort);
    }
  })();
}
