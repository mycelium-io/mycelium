// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * In-process agent dispatch via runtime.channel.reply.
 *
 * This is the core of how the channel plugin runs agents. Each inbound
 * message builds a MsgContext (via finalizeInboundContext) and hands it to
 * dispatchReplyWithBufferedBlockDispatcher, which runs the agent through
 * OpenClaw's reply pipeline and invokes our deliver callback with a clean
 * ReplyPayload — no subprocess, no stdout parsing, no ANSI stripping.
 */

import type { ReplyPayload } from "openclaw/plugin-sdk";

import { CHANNEL_ID, type ChannelConfig } from "../config.js";
import { buildSessionKey } from "../session-key.js";
import { fetchAgentContext, renderPlanBlock } from "./agent-context.js";
import { postToRoom } from "./post-to-room.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };

export async function dispatchToAgent(
  runtime: any,
  cfg: ChannelConfig,
  agentId: string,
  sender: string,
  content: string,
  messageId: string | undefined,
  sessionRoom: string,
  log: Logger,
): Promise<void> {
  const openclawConfig = runtime.config.loadConfig();
  // sessionKey stays pinned to cfg.room (the agent's one persistent OpenClaw
  // conversation) deliberately — see channel/index.ts's participant-gating
  // comment. Room-specific routing/attribution below uses sessionRoom
  // instead, which is the actual mycelium room this dispatch is about.
  const sessionKey = buildSessionKey(agentId, cfg.room);
  const envelopeBody = `[${sender} in ${cfg.room}]: ${content}`;

  // Room plan briefing — best-effort, cached per-room. Prepended to the
  // agent-facing body so an @-mentioned agent is plan-aware, the same way
  // a coordination-session agent gets the plan via the tick payload.
  const plan = await fetchAgentContext(cfg.backendUrl, cfg.room, agentId);
  const planBlock = renderPlanBlock(plan.context, plan.generatedAt);
  // Room marker: InsightClaw captures this body verbatim as span content
  // (openclaw.session.key can't carry it — see session-key.ts — because it's
  // pinned to the agent's persistent conversation, not the coordination room
  // the tick is actually about). The mycelium-collector's CFN forwarder reads
  // this marker back out of the captured content to resolve the correct
  // mas_id before forwarding, instead of misattributing extraction to
  // cfg.room. Placed first so it survives content truncation (which slices
  // from the end — see openclaw-deep-observability's truncateCapturedContent).
  const roomMarker = sessionRoom ? `[[mycelium-room:${sessionRoom}]]\n` : "";
  const bodyForAgent = `${roomMarker}${planBlock ? planBlock : ""}${content}`;

  const ctx = runtime.channel.reply.finalizeInboundContext({
    Body: envelopeBody,
    BodyForAgent: bodyForAgent,
    RawBody: content,
    CommandBody: content,
    From: `${CHANNEL_ID}:${sender}`,
    To: `${CHANNEL_ID}:${cfg.room}`,
    SessionKey: sessionKey,
    AccountId: "default",
    ChatType: "group",
    ConversationLabel: cfg.room,
    SenderName: sender,
    SenderId: sender,
    GroupSubject: cfg.room,
    Provider: CHANNEL_ID,
    Surface: CHANNEL_ID,
    MessageSid: messageId ?? `${CHANNEL_ID}-${Date.now()}`,
    Timestamp: Date.now(),
    OriginatingChannel: CHANNEL_ID,
    OriginatingTo: `${CHANNEL_ID}:${cfg.room}`,
  });

  log.info(`[${CHANNEL_ID}] → dispatching to ${agentId} (sessionKey=${sessionKey})`);

  try {
    await runtime.channel.reply.dispatchReplyWithBufferedBlockDispatcher({
      ctx,
      cfg: openclawConfig,
      replyOptions: { sourceReplyDeliveryMode: "automatic" },
      dispatcherOptions: {
        deliver: async (payload: ReplyPayload) => {
          const text = payload.text?.trim();
          if (!text) return;
          const ok = await postToRoom(cfg, agentId, text, sessionRoom || cfg.room);
          if (ok) {
            log.info(
              `[${CHANNEL_ID}] ← ${agentId}: ${text.slice(0, 80)}${text.length > 80 ? "…" : ""}`,
            );
          } else {
            log.warn(`[${CHANNEL_ID}] outbound POST failed for ${agentId}`);
          }
        },
        onError: (err: unknown, info: { kind: string }) => {
          log.warn(
            `[${CHANNEL_ID}] ${info.kind} reply failed for ${agentId}: ${String(err)}`,
          );
        },
      },
    });
  } catch (err: any) {
    log.warn(`[${CHANNEL_ID}] dispatch failed for ${agentId}: ${err?.message ?? err}`);
  }
}
