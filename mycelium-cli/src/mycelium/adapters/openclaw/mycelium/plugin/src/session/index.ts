// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Session lifecycle + per-turn context injection.
 *
 * This concern is independent of the channel — it runs for every agent session,
 * whether or not channels.mycelium-room is configured. It handles:
 *
 *   - session_start         — log + track per-agent session state
 *   - session_end           — log + announce departure to the room (if configured)
 *   - before_agent_start    — inject MYCELIUM_INSTRUCTIONS + latest tick context +
 *                             per-turn memory file contents into the agent prompt
 *   - gateway_start/stop    — health check + logging
 *
 * Note: the agent wake-up code (wakeAgent, per-agent SSE) is gone — agent dispatch
 * happens through the channel path now, not session. This module is purely about
 * tracking session lifecycle and injecting context, not moving messages.
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

import {
  bindAgentToRoom,
  getMostRecentRoomForAgent,
} from "../channel/bindings.js";
import { type ChannelConfig, getApiUrl, readMemoryFileContent, resolveHandle } from "../config.js";
import { apiGet, apiPost, fetchBackendHealth } from "../http.js";
import { MYCELIUM_INSTRUCTIONS } from "../instructions.js";

/**
 * Extract a Mycelium room name from inbound prompt text.
 *
 * Recognises (in priority order):
 *   1. `--room <name>`  or  `--room=<name>`     — the canonical CLI flag
 *      that test prompts and the SKILL examples both use. Captures the
 *      same character set as Mycelium room names: alphanumeric + `_-:`.
 *   2. `Mycelium room: <name>` / `Room: <name>` — narrative form, useful
 *      for human-authored Matrix prompts.
 *
 * Returns null when no room mention is found, so callers can leave any
 * existing binding (or fallback to channelCfg.room) intact.
 */
export function extractMyceliumRoomFromText(text: string): string | null {
  if (!text) return null;
  const flag = text.match(/--room[=\s]+([A-Za-z0-9_:-]+)/);
  if (flag) return flag[1];
  const labeled = text.match(/(?:^|[\n\s—–-])\s*(?:Mycelium\s+)?Room:\s*([A-Za-z0-9_:-]+)/i);
  if (labeled) return labeled[1];
  return null;
}

type Logger = { info: (s: string) => void; warn: (s: string) => void };

type SessionEntry = {
  sessionKey: string;
  sessionId?: string;
  handle: string;
  room?: string;
};

const _sessions = new Map<string, SessionEntry>();

export function installSession(
  api: OpenClawPluginApi,
  channelCfg: ChannelConfig | null,
  log: Logger,
): void {
  api.on("gateway_start", async () => {
    if (!getApiUrl()) {
      log.warn("[mycelium] no API URL found in config or env — plugin inactive");
      return;
    }
    try {
      const res = await fetchBackendHealth();
      if (res.ok) {
        log.info(`[mycelium] ready | backend: ${getApiUrl()}`);
      } else {
        log.warn(`[mycelium] backend unhealthy (${res.status}) — will retry per call`);
      }
    } catch {
      log.warn(`[mycelium] cannot reach ${getApiUrl()} — will retry per call`);
    }
  });

  api.on("gateway_stop", async () => {
    log.info("[mycelium] gateway stopping — session state cleared");
    _sessions.clear();
  });

  api.on(
    "session_start",
    async (
      event: { sessionId: string; resumedFrom?: string },
      ctx: any,
    ) => {
      const agentId: string | undefined = ctx?.agentId;
      const sessionKey: string | undefined = ctx?.sessionKey;
      const handle = resolveHandle(agentId);

      const isCliSession = sessionKey?.endsWith(":main");
      log.info(
        `[mycelium] session_start handle:${handle} sessionId:${event.sessionId} sessionKey:${sessionKey ?? "none"} isCliSession:${isCliSession}`,
      );
      if (sessionKey) {
        const existing = _sessions.get(agentId ?? "default");
        const sessionId = isCliSession ? existing?.sessionId : event.sessionId;
        _sessions.set(agentId ?? "default", {
          sessionKey,
          sessionId,
          handle,
          room: existing?.room ?? channelCfg?.room,
        });
      }

      if (event.resumedFrom) {
        log.info(`[mycelium] session resumed (${event.sessionId})`);
      } else {
        log.info(`[mycelium] session started — ${handle} (${event.sessionId})`);
      }
    },
  );

  api.on(
    "session_end",
    async (
      event: { sessionId: string; messageCount: number },
      ctx: any,
    ) => {
      const agentId: string | undefined = ctx?.agentId;
      const handle = resolveHandle(agentId);
      const entry = _sessions.get(agentId ?? "default");

      if (agentId) _sessions.delete(agentId);

      log.info(
        `[mycelium] session ${event.sessionId} ended (${event.messageCount} messages)`,
      );

      if (entry?.room) {
        await apiPost(
          `/rooms/${entry.room}/messages`,
          {
            sender_handle: handle,
            recipient_handle: null,
            message_type: "announce",
            content: "agent offline (session ended)",
          },
          log,
        );
      }
    },
  );

  // ── Inbound message hook ────────────────────────────────────────────────
  //
  // Fires for every message a channel plugin (e.g. matrix) routes to one of
  // our agents, *before* before_agent_start. We use it solely to learn which
  // Mycelium room the agent was just told to join — by extracting `--room
  // <name>` from the message body — and record that as a per-agent binding.
  // The channel module's session-sub-room poll consults the same registry to
  // decide which `:session:` sub-rooms to subscribe to, so the push-based
  // tick path now works for any room mentioned in the inbound prompt, not
  // just the static channelCfg.room.
  //
  // We deliberately don't mutate prompt content here — message rewriting is
  // the channel plugin's job. We're just sniffing for a room name.
  api.on(
    "message_received",
    async (
      event: { from: string; content: string; metadata?: Record<string, unknown> },
      ctx: { channelId: string; accountId?: string; conversationId?: string },
    ) => {
      const agentId = ctx?.accountId;
      if (!agentId) return;
      const room = extractMyceliumRoomFromText(event?.content ?? "");
      if (!room) return;
      const fresh = bindAgentToRoom(agentId, room);
      if (fresh) {
        log.info(
          `[mycelium] bound agent ${agentId} -> room "${room}" (from ${ctx.channelId}/${ctx.conversationId ?? "?"})`,
        );
        // Reflect the binding into _sessions so before_agent_start picks it
        // up immediately for tick-context injection.
        const entry = _sessions.get(agentId);
        if (entry) entry.room = room;
      }
    },
  );

  api.on(
    "before_agent_start",
    async (
      event: { prompt?: string },
      ctx: any,
    ): Promise<
      { prependSystemContext?: string; prependContext?: string } | undefined
    > => {
      const agentId: string | undefined = ctx?.agentId;
      const sessionKey: string | undefined = ctx?.sessionKey;
      const handle = resolveHandle(agentId);

      const sessionId: string | undefined = ctx?.sessionId;
      const isCliSession = sessionKey?.endsWith(":main");
      log.info(
        `[mycelium] before_agent_start handle:${handle} sessionKey:${sessionKey ?? "none"} isCliSession:${isCliSession}`,
      );

      // Belt-and-braces: also try to extract a room from the prompt text we
      // were given. message_received covers the normal Matrix path, but some
      // agent activations (e.g. CLI-driven sessions, replays) bypass it and
      // come straight here.
      if (agentId && event?.prompt) {
        const promptRoom = extractMyceliumRoomFromText(event.prompt);
        if (promptRoom && bindAgentToRoom(agentId, promptRoom)) {
          log.info(
            `[mycelium] bound agent ${agentId} -> room "${promptRoom}" (from before_agent_start prompt)`,
          );
        }
      }

      let existing = _sessions.get(agentId ?? "default");
      // Prefer a binding learned from inbound messages over the static default.
      const boundRoom = agentId ? getMostRecentRoomForAgent(agentId) : undefined;
      const effectiveRoom = boundRoom ?? existing?.room ?? channelCfg?.room;

      if (!existing && sessionKey) {
        existing = {
          sessionKey,
          sessionId: isCliSession ? undefined : sessionId,
          handle,
          room: effectiveRoom,
        };
        _sessions.set(agentId ?? "default", existing);
      } else if (existing) {
        if (sessionKey) existing.sessionKey = sessionKey;
        if (sessionId && !existing.sessionId && !isCliSession) {
          existing.sessionId = sessionId;
        }
        // Promote a freshly-discovered binding into the live entry so
        // session_end's "agent offline" announce hits the right room.
        if (boundRoom && existing.room !== boundRoom) {
          existing.room = boundRoom;
        }
      }

      const systemParts: string[] = [
        MYCELIUM_INSTRUCTIONS,
        `Your Mycelium handle for this session is: \`${handle}\`\nUse this exact value for \`--handle\` when joining a room.`,
      ];

      const contextParts: string[] = [];

      const room = effectiveRoom;
      if (room) {
        // Look first in any active session sub-room of this parent — that's
        // where coordination ticks actually live. Fall back to the parent
        // room itself for legacy / non-coordination contexts.
        const candidateRooms: string[] = [];
        try {
          const allRooms = (await apiGet(`/rooms`, log)) as any[];
          if (Array.isArray(allRooms)) {
            const subs = allRooms
              .filter(
                (r) =>
                  typeof r?.name === "string" &&
                  r.name.startsWith(`${room}:session:`) &&
                  (r.coordination_state === "negotiating" ||
                    r.coordination_state === "waiting" ||
                    r.coordination_state === "complete"),
              )
              .sort((a, b) => (a.created_at < b.created_at ? 1 : -1));
            for (const s of subs) candidateRooms.push(s.name);
          }
        } catch {
          /* fall through to parent-room scan */
        }
        candidateRooms.push(room);

        for (const candidate of candidateRooms) {
          const data = (await apiGet(
            `/rooms/${candidate}/messages?limit=30`,
            log,
          )) as any;
          // Prefer ticks addressed to *this* agent's handle, then any
          // consensus, then any tick. (Ticks are per-participant.)
          const messages: any[] = data?.messages ?? [];
          const myTick = messages.find((m: any) => {
            if (m.message_type !== "coordination_tick") return false;
            try {
              const parsed =
                typeof m.content === "string" ? JSON.parse(m.content) : m.content;
              const pid = parsed?.payload?.participant_id ?? parsed?.participant_id;
              return pid === handle;
            } catch {
              return false;
            }
          });
          const consensus = messages.find(
            (m: any) => m.message_type === "coordination_consensus",
          );
          const anyTick = messages.find(
            (m: any) => m.message_type === "coordination_tick",
          );
          const coord = myTick ?? consensus ?? anyTick;
          if (coord) {
            const label =
              coord.message_type === "coordination_consensus"
                ? "[Mycelium — consensus]"
                : "[Mycelium — coordination tick]";
            contextParts.push(
              `${label}\nRoom: ${candidate}\n\n${coord.content}`,
            );
            break;
          }
        }
      }

      const memory = readMemoryFileContent();
      if (memory) {
        contextParts.push(`# Injected Memory (per-turn)\n\n${memory}`);
        log.info(`[mycelium] injected ${memory.length} bytes from memory file`);
      }

      log.info(
        `[mycelium] prependSystemContext: ${systemParts.join("\n\n").length} chars (cached), prependContext: ${contextParts.length ? contextParts.join("\n\n").length : 0} chars (dynamic)`,
      );

      return {
        prependSystemContext: systemParts.join("\n\n"),
        prependContext: contextParts.length ? contextParts.join("\n\n") : undefined,
      };
    },
  );
}
