// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Forward agent output to the Mycelium knowledge graph.
 *
 * Listens on `message_sent` and POSTs the agent's reply content to
 * `/api/knowledge/ingest`. Separate from the mycelium-knowledge-extract HOOK
 * (which runs out-of-process via OpenClaw's hook system) — this is the
 * in-process plugin-level shim that handles the happy path when an agent
 * sends a message to a channel.
 *
 * Also POSTs broadcast replies to the configured Mycelium room if one exists
 * in the session entry (so agents writing to e.g. Discord also land in the
 * linked Mycelium room).
 */

import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

import {
  type ChannelConfig,
  getAgentId,
  resolveHandle,
} from "../config.js";
import { apiPost } from "../http.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };

export function installKnowledgeIngest(
  api: OpenClawPluginApi,
  channelCfg: ChannelConfig | null,
  log: Logger,
): void {
  api.on(
    "message_sent",
    async (
      event: { to: string; content: string; success: boolean },
      ctx: any,
    ) => {
      if (!event.success) return;
      if (!event.content?.trim() || event.content.trim().length < 5) return;

      const agentId: string | undefined = ctx?.agentId;
      const handle = resolveHandle(agentId);

      if (channelCfg?.room) {
        await apiPost(
          `/rooms/${channelCfg.room}/messages`,
          {
            sender_handle: handle,
            recipient_handle: null,
            message_type: "broadcast",
            content: event.content,
          },
          log,
        );
      }

      // Prefer the per-turn agentId from the OpenClaw context — it's
      // present for channel-dispatched turns, where the process env
      // (which getAgentId reads) belongs to the gateway, not the agent.
      // Falling back to getAgentId() keeps direct `openclaw agent --agent`
      // invocations attributed. See issue #144.
      //
      // Leaf nodes only send room_name — the backend resolves workspace_id
      // and mas_id from the room's DB record or its own settings (#139).
      const ingestAgentId = agentId?.trim() || getAgentId() || undefined;
      apiPost(
        "/api/knowledge/ingest",
        {
          room_name: channelCfg?.room || undefined,
          agent_id: ingestAgentId,
          records: [{ response: event.content }],
        },
        log,
      ).catch((err) => log.warn(`[mycelium] ingest failed: ${err}`));
    },
  );
}
