// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors
import { CHANNEL_ID } from "../config.js";
import { buildSessionKey } from "../session-key.js";
import { fetchAgentContext, renderPlanBlock } from "./agent-context.js";
import { postToRoom } from "./post-to-room.js";
export async function dispatchToAgent(runtime, cfg, agentId, sender, content, messageId, log) {
    const openclawConfig = runtime.config.loadConfig();
    const sessionKey = buildSessionKey(agentId, cfg.room);
    const envelopeBody = `[${sender} in ${cfg.room}]: ${content}`;
    // Room plan briefing — best-effort, cached per-room. Prepended to the
    // agent-facing body so an @-mentioned agent is plan-aware, the same way
    // a coordination-session agent gets the plan via the tick payload.
    const plan = await fetchAgentContext(cfg.backendUrl, cfg.room, agentId);
    const planBlock = renderPlanBlock(plan.context, plan.generatedAt);
    const bodyForAgent = planBlock ? `${planBlock}${content}` : content;
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
                    const ok = await postToRoom(cfg, agentId, text);
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
