// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Channel concern entry point.
 *
 * installChannel() wires together the room SSE subscription, session sub-room
 * discovery, and in-process agent dispatch. The actual routing decisions are
 * delegated to routeMessage() in ./route.ts — a pure function with zero
 * OpenClaw dependencies that returns a list of actions to execute. This
 * module is the executor: it runs each action against the live OpenClaw
 * runtime (dispatch agents, subscribe to session sub-rooms, etc).
 *
 * Call installChannel once from register() after the channel config has
 * been resolved.
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

import { CHANNEL_ID, type ChannelConfig } from "../config.js";
import { clearAllBindings, getAllBoundRooms } from "./bindings.js";
import { dispatchToAgent } from "./dispatch.js";
import { _ownMessageIds } from "./post-to-room.js";
import { routeMessage, type RouteAction } from "./route.js";
import { startRoomSSE } from "./room-sse.js";
import { clearSubscribedSessions, startSessionSSE } from "./session-sse.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };

let _abort: AbortController | null = null;

export function installChannel(
  api: OpenClawPluginApi,
  cfg: ChannelConfig,
  log: Logger,
): void {
  const runtime = api.runtime;

  api.on("gateway_start", async () => {
    log.info(`[${CHANNEL_ID}] gateway started — starting SSE for ${cfg.room}`);
    if (_abort) return;
    _abort = new AbortController();

    // Ensure the configured room exists before subscribing to SSE.
    try {
      const checkRes = await fetch(
        `${cfg.backendUrl}/rooms/${encodeURIComponent(cfg.room)}`,
      );
      if (checkRes.status === 404) {
        const createRes = await fetch(`${cfg.backendUrl}/rooms`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name: cfg.room,
            mode: "coordination",
            description: `Channel room created by mycelium-room plugin`,
          }),
        });
        if (createRes.ok) {
          log.info(`[${CHANNEL_ID}] created room "${cfg.room}"`);
        } else {
          log.warn(
            `[${CHANNEL_ID}] failed to create room "${cfg.room}": ${createRes.status}`,
          );
        }
      }
    } catch (err: any) {
      log.warn(
        `[${CHANNEL_ID}] room ensure check failed: ${err?.message ?? err}`,
      );
    }

    startRoomSSE(runtime, cfg, _abort, handleMessage, log);

    // Poll for session sub-rooms and subscribe to their SSE streams.
    // Coordination ticks live in session sub-rooms, not the parent room.
    //
    // We watch sub-rooms of `cfg.room` (the static channel default) AND any
    // room an agent has been bound to via the `message_received` hook
    // (channel/bindings.ts). The bindings registry gets populated when an
    // inbound channel message references `--room <name>` — typically the
    // dynamic per-test rooms (`dist-e2e-<uuid>`). Without this widening, the
    // push path was deaf to anything except cfg.room and agents fell back to
    // polling via `mycelium session await` (which deadlocks under exec/yield;
    // see plugin SKILL.md).
    //
    // We also subscribe to the parent room's own SSE on first sighting, so
    // broadcast messages and `coordination_join` messages from dynamic rooms
    // reach the router. Each call to startRoomSSE / startSessionSSE is
    // idempotent per (URL), so duplicates are fine.
    const _watchedParentRooms = new Set<string>([cfg.room]);
    const pollInterval = setInterval(async () => {
      try {
        const parentRooms = new Set<string>([cfg.room, ...getAllBoundRooms()]);
        // Open SSE on any new parent room we haven't watched yet so broadcasts
        // and coordination_join messages flow through the router.
        for (const parent of parentRooms) {
          if (!_watchedParentRooms.has(parent) && _abort) {
            _watchedParentRooms.add(parent);
            log.info(`[${CHANNEL_ID}] subscribing to bound parent room: ${parent}`);
            startRoomSSE(
              runtime,
              { ...cfg, room: parent },
              _abort,
              handleMessage,
              log,
            );
          }
        }

        const res = await fetch(`${cfg.backendUrl}/rooms`);
        if (!res.ok) return;
        const rooms: any[] = await res.json();
        for (const room of rooms) {
          const name: string | undefined = room.name;
          if (!name) continue;
          // Match against every parent room we know about, not just cfg.room.
          let matchedParent: string | null = null;
          for (const parent of parentRooms) {
            if (name.startsWith(parent + ":session:")) {
              matchedParent = parent;
              break;
            }
          }
          if (!matchedParent) continue;
          if (
            room.coordination_state === "waiting" ||
            room.coordination_state === "negotiating"
          ) {
            startSessionSSE(
              runtime,
              { ...cfg, room: matchedParent },
              name,
              _abort!,
              handleMessage,
              log,
            );
          }
        }
      } catch {
        /* polling failure is non-fatal */
      }
    }, 5000);

    _abort.signal.addEventListener("abort", () => clearInterval(pollInterval));
  });

  api.on("gateway_stop", async () => {
    _abort?.abort();
    _abort = null;
    clearSubscribedSessions();
    clearAllBindings();
    log.info(`[${CHANNEL_ID}] gateway stopping — SSE closed`);
  });
}

// ── Execute the routed actions ────────────────────────────────────────────

/**
 * Given a raw message from SSE, run it through the router and execute each
 * returned action. This function is side-effectful and mutates module state
 * (_ownMessageIds, _abort). Tests should target route.ts's routeMessage
 * directly, not this function.
 */
function handleMessage(
  runtime: any,
  cfg: ChannelConfig,
  msg: any,
  log: Logger,
): void {
  const actions = routeMessage(cfg, msg, _ownMessageIds);
  for (const action of actions) {
    executeAction(runtime, cfg, action, msg, log);
  }
}

function executeAction(
  runtime: any,
  cfg: ChannelConfig,
  action: RouteAction,
  msg: any,
  log: Logger,
): void {
  switch (action.kind) {
    case "dispatch": {
      if (action.sender === "CognitiveEngine") {
        // Tick or consensus — log with a distinguishing emoji
        log.info(
          `[${CHANNEL_ID}] ${msg.message_type === "coordination_consensus" ? "🤝" : "🎯"} → ${action.agentId}`,
        );
      } else {
        log.info(
          `[${CHANNEL_ID}] ← ${action.sender}: ${action.content.slice(0, 80)}${action.content.length > 80 ? "…" : ""}`,
        );
        log.info(`[${CHANNEL_ID}] addressed to: ${action.agentId}`);
      }
      void dispatchToAgent(
        runtime,
        cfg,
        action.agentId,
        action.sender,
        action.content,
        action.messageId,
        log,
      );
      return;
    }
    case "subscribe-session": {
      if (_abort) {
        startSessionSSE(runtime, cfg, action.roomName, _abort, handleMessage, log);
      }
      return;
    }
    case "ignore": {
      if (action.reason !== "own message" && action.reason !== "announce") {
        log.info(`[${CHANNEL_ID}] ${action.reason}`);
      }
      return;
    }
  }
}
