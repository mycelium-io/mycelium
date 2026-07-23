// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors
import { CHANNEL_ID } from "../config.js";
import { buildSessionKey } from "../session-key.js";
import { fetchAgentContext, renderPlanBlock } from "./agent-context.js";
import { postToRoom } from "./post-to-room.js";
export async function dispatchToAgent(runtime, cfg, agentId, sender, content, messageId, sessionRoom, log) {
    const openclawConfig = runtime.config.loadConfig();
    // sessionKey is keyed by the actual coordination room (sessionRoom), not
    // cfg.room — each negotiation gets its own isolated OpenClaw conversation,
    // per SKILL.md's documented guarantee ("none of your home-channel
    // short-term memory carries over" once a negotiation session starts).
    // Previously pinned to cfg.room for every dispatch, which caused two
    // separate bugs: cross-negotiation context bleeding into unrelated
    // sessions (confirmed on af364e85 — an agent's reply referenced an
    // unrelated prior session instead of answering its actual tick), and
    // knowledge-extraction misattribution (every room's CFN extraction landed
    // in cfg.room's mas_id — see the [[mycelium-room:...]] marker below, added
    // as a narrower fix for that before this one; still covers tool-call/LLM
    // sub-spans, which don't carry the marker — see collector.py).
    const sessionKey = buildSessionKey(agentId, sessionRoom || cfg.room);
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
                deliver: async (payload) => {
                    const text = payload.text?.trim();
                    if (!text)
                        return;
                    const ok = await postToRoom(cfg, agentId, text, sessionRoom || cfg.room);
                    if (ok) {
                        log.info(`[${CHANNEL_ID}] ← ${agentId}: ${text.slice(0, 80)}${text.length > 80 ? "…" : ""}`);
                    }
                    else {
                        log.warn(`[${CHANNEL_ID}] outbound POST failed for ${agentId}`);
                    }
                },
                onError: (err, info) => {
                    log.warn(`[${CHANNEL_ID}] ${info.kind} reply failed for ${agentId}: ${String(err)}`);
                },
            },
        });
    }
    catch (err) {
        log.warn(`[${CHANNEL_ID}] dispatch failed for ${agentId}: ${err?.message ?? err}`);
    }
}
