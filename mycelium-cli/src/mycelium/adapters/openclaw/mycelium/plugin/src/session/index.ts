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

import { type ChannelConfig, getApiUrl, readMemoryFileContent, resolveHandle } from "../config.js";
import { apiGet, apiPost, fetchBackendHealth } from "../http.js";
import { MYCELIUM_INSTRUCTIONS } from "../instructions.js";

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

  api.on(
    "before_agent_start",
    async (
      _event: any,
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

      let existing = _sessions.get(agentId ?? "default");
      if (!existing && sessionKey) {
        existing = {
          sessionKey,
          sessionId: isCliSession ? undefined : sessionId,
          handle,
          room: channelCfg?.room,
        };
        _sessions.set(agentId ?? "default", existing);
      } else if (existing) {
        if (sessionKey) existing.sessionKey = sessionKey;
        if (sessionId && !existing.sessionId && !isCliSession) {
          existing.sessionId = sessionId;
        }
      }

      const systemParts: string[] = [
        MYCELIUM_INSTRUCTIONS,
        `Your Mycelium handle for this session is: \`${handle}\`\nUse this exact value for \`--handle\` when joining a room.`,
      ];

      const contextParts: string[] = [];

      const room = existing?.room;
      if (room) {
        const data = (await apiGet(`/rooms/${room}/messages?limit=30`, log)) as any;
        const coord = data?.messages?.find(
          (m: any) =>
            m.message_type === "coordination_consensus" ||
            m.message_type === "coordination_tick",
        );
        if (coord) {
          const label =
            coord.message_type === "coordination_consensus"
              ? "[Mycelium — consensus]"
              : "[Mycelium — coordination tick]";
          contextParts.push(`${label}\nRoom: ${room}\n\n${coord.content}`);
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
