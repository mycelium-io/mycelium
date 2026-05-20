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
 * Call installChannel once from register() after the channel configs have
 * been resolved. It accepts a LIST of per-room configs and fans out one
 * room-SSE subscription per entry, all sharing a single AbortController so
 * gateway_stop tears every subscription down at once. OpenClaw still only
 * sees the single `mycelium-room` channel id — the multi-room multiplexing
 * is internal here, so no plugin-manifest regen / reinstall is needed when
 * a room is added.
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

import { CHANNEL_ID, type ChannelConfig } from "../config.js";
import { enqueueDispatch } from "./dispatch-chain.js";
import { dispatchToAgent } from "./dispatch.js";
import { executeNotifyHome } from "./notify-home.js";
import { _ownMessageIds } from "./post-to-room.js";
import { lookupReturnAddress, stashReturnAddress } from "./return-address.js";
import { routeMessage, type RouteAction } from "./route.js";
import { startRoomSSE } from "./room-sse.js";
import {
  clearSubscribedSessions,
  startSessionSSE,
  stopSessionSSE,
  subscribedSessionRooms,
} from "./session-sse.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };

let _abort: AbortController | null = null;

async function ensureRoom(cfg: ChannelConfig, log: Logger): Promise<void> {
  try {
    const checkRes = await fetch(
      `${cfg.backendUrl}/api/rooms/${encodeURIComponent(cfg.room)}`,
    );
    if (checkRes.status === 404) {
      const createRes = await fetch(`${cfg.backendUrl}/api/rooms`, {
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
    log.warn(`[${CHANNEL_ID}] room ensure check failed: ${err?.message ?? err}`);
  }
}

export function installChannel(
  api: OpenClawPluginApi,
  cfgs: ChannelConfig[],
  log: Logger,
): void {
  const runtime = api.runtime;

  // Session sub-rooms (coordination ticks) are room-agnostic — the poll loop
  // discovers them backend-wide. routeTick gates on cfg.agents, so the
  // session cfg must carry the UNION of every room's agents, or a tick for
  // an agent in room B would be dropped while we're iterating room A's cfg.
  const mergedAgents = [...new Set(cfgs.flatMap((c) => c.agents))];
  const sessionCfg: ChannelConfig = { ...cfgs[0], agents: mergedAgents };

  api.on("gateway_start", async () => {
    log.info(
      `[${CHANNEL_ID}] gateway started — starting SSE for ${cfgs.length} room(s): [${cfgs
        .map((c) => c.room)
        .join(", ")}]`,
    );
    if (_abort) return;
    _abort = new AbortController();

    for (const cfg of cfgs) {
      await ensureRoom(cfg, log);
      startRoomSSE(runtime, cfg, _abort, handleMessage, log);
    }

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
    const TERMINAL_STATES = new Set(["agreed", "failed", "idle"]);

    const pollInterval = setInterval(async () => {
      try {
        // Poll the first-class coord-sessions endpoint instead of /api/rooms
        // (which no longer surfaces sessions). Display names are returned by
        // the API so the rest of the SSE-by-display-name flow stays the same.
        const res = await fetch(
          `${sessionCfg.backendUrl}/api/coordination-sessions?limit=200`,
        );
        if (!res.ok) return;
        const sessions: any[] = await res.json();

        const activeSessionRooms = new Set<string>();

        for (const s of sessions) {
          const name: string | undefined = s.display_name;
          if (!name) continue;
          const state: string | undefined = s.state;

          activeSessionRooms.add(name);

          if (state === "waiting" || state === "negotiating") {
            startSessionSSE(runtime, sessionCfg, name, _abort!, handleMessage, log);
          } else if (state && TERMINAL_STATES.has(state)) {
            stopSessionSSE(name, log);
          }
        }

        // Unsubscribe from sessions that are no longer in the active list
        // (removed by coordination teardown or parent-room delete).
        for (const subbed of subscribedSessionRooms()) {
          if (!activeSessionRooms.has(subbed)) {
            stopSessionSSE(subbed, log);
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
      // Per-agent serialization: even though `dispatchReplyWithBufferedBlockDispatcher`
      // is supposed to be safe to call concurrently, openclaw's lane queue has
      // wedged under bursts (openclaw/openclaw#48488). Holding the queue depth
      // at ≤ 1 per agent at our layer keeps that bug out of reach. See
      // dispatch-chain.ts for the full rationale.
      void enqueueDispatch(
        action.agentId,
        () =>
          dispatchToAgent(
            runtime,
            cfg,
            action.agentId,
            action.sender,
            action.content,
            action.messageId,
            log,
          ),
        { log },
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
