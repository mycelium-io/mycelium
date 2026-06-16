// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors
/**
 * Room SSE subscription — the single inbound surface for the channel plugin.
 *
 * This is the ONE SSE subscription per gateway instance. All events flow through
 * here: broadcast messages, coordination ticks (from session sub-rooms, discovered
 * lazily), and consensus events. Per-agent /agents/{handle}/stream subscriptions
 * are gone.
 */
import { CHANNEL_ID } from "../config.js";
export function startRoomSSE(runtime, cfg, abort, handleMessage, log) {
    const signal = abort.signal;
    const sseUrl = `${cfg.backendUrl}/api/rooms/${encodeURIComponent(cfg.room)}/messages/stream`;
    (async () => {
        while (!signal.aborted) {
            try {
                const res = await fetch(sseUrl, {
                    headers: { Accept: "text/event-stream" },
                    signal,
                });
                if (res.status === 404) {
                    log.warn(`[${CHANNEL_ID}] room SSE 404 for ${cfg.room} — room may not exist yet, retry 15s`);
                    await new Promise((r) => setTimeout(r, 15_000));
                    continue;
                }
                if (!res.ok || !res.body) {
                    log.warn(`[${CHANNEL_ID}] SSE ${res.status} — retry 5s`);
                    await new Promise((r) => setTimeout(r, 5000));
                    continue;
                }
                log.info(`[${CHANNEL_ID}] SSE connected: ${cfg.room} (agents: ${cfg.agents.join(", ")})`);
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let buffer = "";
                while (!signal.aborted) {
                    const { done, value } = await reader.read();
                    if (done)
                        break;
                    buffer += decoder.decode(value, { stream: true });
                    const blocks = buffer.split("\n\n");
                    buffer = blocks.pop() ?? "";
                    for (const block of blocks) {
                        const dataLine = block.split("\n").find((l) => l.startsWith("data: "));
                        if (!dataLine)
                            continue;
                        const raw = dataLine.slice(6).trim();
                        if (!raw || raw === "{}")
                            continue;
                        let msg;
                        try {
                            msg = JSON.parse(raw);
                        }
                        catch {
                            continue;
                        }
                        handleMessage(runtime, cfg, msg, log);
                    }
                }
            }
            catch (err) {
                if (signal.aborted)
                    return;
                log.warn(`[${CHANNEL_ID}] SSE error: ${err?.message ?? err} — retry 5s`);
                await new Promise((r) => setTimeout(r, 5000));
            }
        }
    })();
}
