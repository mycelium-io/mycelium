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
import { dispatchToAgent } from "./dispatch.js";
import { executeNotifyHome } from "./notify-home.js";
import { _ownMessageIds } from "./post-to-room.js";
import { lookupReturnAddress, stashReturnAddress } from "./return-address.js";
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

    // Poll for active session sub-rooms (anywhere in the backend) and
    // subscribe to each one's SSE stream. Coordination ticks live in session
    // sub-rooms, not parent rooms.
    //
    // We deliberately do NOT filter by `cfg.room` here — that scoping was the
    // root cause of "agents go silent" when a negotiation was kicked off in a
    // room name different from the channel's configured `room` (per-test
    // ad-hoc rooms, teammate's room, dynamic topic rooms). All gating on
    // "is this tick relevant to one of our agents?" already happens in
    // routeTick (`cfg.agents.includes(participant_id)`) and in notify-home
    // (per-session-sub-room stash). Subscribing broadly and filtering narrowly
    // is safer than the reverse: irrelevant ticks become cheap ignored events;
    // missed ticks become silent failures.
    //
    // startSessionSSE's subscribed-set is idempotent, so re-evaluating each
    // poll tick is a no-op for already-subscribed rooms.
    const pollInterval = setInterval(async () => {
      try {
        const res = await fetch(`${cfg.backendUrl}/rooms`);
        if (!res.ok) return;
        const rooms: any[] = await res.json();
        for (const room of rooms) {
          const name: string | undefined = room.name;
          if (!name || !name.includes(":session:")) continue;
          const state = room.coordination_state;
          if (state !== "waiting" && state !== "negotiating") continue;
          startSessionSSE(runtime, cfg, name, _abort!, handleMessage, log);
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
      // Consensus dispatch needs participant gating: now that we subscribe
      // to every active session sub-room (not just sub-rooms of cfg.room),
      // a coordination_consensus from a session our agents weren't part of
      // would otherwise wake their mycelium-room sessions with someone
      // else's outcome. The stash is our authoritative "did this agent
      // participate in this session" signal — populated on first tick.
      // Tick dispatch is already gated upstream by `cfg.agents.includes(participant_id)`
      // in routeTick; only consensus needs this extra check.
      if (
        action.sender === "CognitiveEngine" &&
        msg.message_type === "coordination_consensus" &&
        msg.room_name &&
        !lookupReturnAddress(msg.room_name, action.agentId)
      ) {
        log.info(
          `[${CHANNEL_ID}] consensus skipped for ${action.agentId} — not a participant in ${msg.room_name}`,
        );
        return;
      }
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
    case "stash-return-address": {
      stashReturnAddress(action.sessionRoom, action.agentId, log);
      return;
    }
    case "notify-home": {
      log.info(
        `[${CHANNEL_ID}] 📬 notify-home for [${action.agentIds.join(", ")}] in ${action.sessionRoom}`,
      );
      void executeNotifyHome(
        runtime,
        cfg,
        action.sessionRoom,
        action.agentIds,
        action.consensusSummary,
        log,
      );
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
