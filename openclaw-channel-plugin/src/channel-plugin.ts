/**
 * mycelium-channel — OpenClaw Channel Plugin (experimental)
 *
 * Lets agents communicate through Mycelium rooms instead of Discord/Slack.
 *
 * Inbound: SSE from mycelium room → spawn `openclaw agent --local` → agent processes message
 * Outbound: llm_output hook → POST agent reply back to mycelium room
 *
 * This is a plugin (not a full channel adapter) — it hooks into the gateway
 * event system rather than implementing the full ChannelPlugin interface.
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const CHANNEL_ID = "mycelium-room";

type ChannelConfig = {
  backendUrl: string;
  room: string;
  handle: string;
};

function readChannelConfig(): ChannelConfig | null {
  try {
    const configPath = join(homedir(), ".openclaw", "openclaw.json");
    const raw = JSON.parse(readFileSync(configPath, "utf-8"));
    const cfg = raw?.channels?.[CHANNEL_ID];
    if (!cfg?.backendUrl || !cfg?.room) return null;
    return {
      backendUrl: String(cfg.backendUrl).replace(/\/$/, ""),
      room: String(cfg.room),
      handle: String(cfg.handle ?? "main"),
    };
  } catch {
    return null;
  }
}

let _abort: AbortController | null = null;

// Track message IDs we posted ourselves to prevent echo loops
const _ownMessageIds = new Set<string>();

async function postToRoom(cfg: ChannelConfig, senderHandle: string, content: string): Promise<boolean> {
  const url = `${cfg.backendUrl}/rooms/${encodeURIComponent(cfg.room)}/messages`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content,
        message_type: "broadcast",
        sender_handle: senderHandle,
      }),
    });
    if (res.ok) {
      // Track the message ID so SSE listener skips it (loop prevention)
      try {
        const body = await res.json();
        if (body?.id) _ownMessageIds.add(body.id);
      } catch { /* response parse failure is non-fatal */ }
    }
    return res.ok;
  } catch {
    return false;
  }
}

function startRoomSSE(
  cfg: ChannelConfig,
  log: { info: (s: string) => void; warn: (s: string) => void },
) {
  if (_abort) return;
  _abort = new AbortController();
  const signal = _abort.signal;
  const sseUrl = `${cfg.backendUrl}/rooms/${encodeURIComponent(cfg.room)}/messages/stream`;

  (async () => {
    while (!signal.aborted) {
      try {
        const res = await fetch(sseUrl, {
          headers: { Accept: "text/event-stream" },
          signal,
        });
        if (!res.ok || !res.body) {
          log.warn(`[${CHANNEL_ID}] SSE ${res.status} — retry 5s`);
          await new Promise((r) => setTimeout(r, 5000));
          continue;
        }

        log.info(`[${CHANNEL_ID}] SSE connected: ${cfg.room}`);
        const reader = (res.body as any).getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (!signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const blocks = buffer.split("\n\n");
          buffer = blocks.pop() ?? "";

          for (const block of blocks) {
            const dataLine = block.split("\n").find((l: string) => l.startsWith("data: "));
            if (!dataLine) continue;
            const raw = dataLine.slice(6).trim();
            if (!raw || raw === "{}") continue;

            let msg: any;
            try { msg = JSON.parse(raw); } catch { continue; }

            // Skip own messages (by tracked ID or by handle match)
            if (msg.id && _ownMessageIds.has(msg.id)) {
              _ownMessageIds.delete(msg.id);  // clean up
              continue;
            }
            if (msg.sender_handle === cfg.handle) continue;
            // Skip coordination system messages
            if (msg.message_type?.startsWith("coordination_")) continue;
            if (msg.message_type === "announce") continue;

            const sender = msg.sender_handle ?? "unknown";
            const content = msg.content ?? "";
            if (!content.trim()) continue;

            log.info(`[${CHANNEL_ID}] ← ${sender}: ${content.slice(0, 80)}${content.length > 80 ? "…" : ""}`);

            // Deliver to agent via openclaw CLI and capture response
            const { spawn } = require("node:child_process");
            const envelope = `[Message from ${sender} in room ${cfg.room}]: ${content}`;
            const child = spawn("openclaw", [
              "agent",
              "--agent", cfg.handle,
              "--session-id", `${CHANNEL_ID}-${cfg.room}`,
              "--local",
              "-m", envelope,
              "--timeout", "120",
            ], {
              detached: true,
              stdio: ["ignore", "pipe", "ignore"],
            });
            child.unref();
            log.info(`[${CHANNEL_ID}] dispatched to ${cfg.handle} (pid=${child.pid})`);

            // Capture stdout and post agent's reply back to room
            let agentOutput = "";
            child.stdout.on("data", (chunk: Buffer) => {
              agentOutput += chunk.toString();
            });
            child.on("close", async () => {
              // Strip ANSI codes and plugin log lines, extract the actual reply
              const lines = agentOutput
                .replace(/\x1b\[[0-9;]*m/g, "")
                .split("\n")
                .filter((l: string) => !l.startsWith("[plugins]") && !l.startsWith("[") && l.trim())
                .join("\n")
                .trim();
              if (!lines) return;

              const handle = cfg.handle;
              const ok = await postToRoom(cfg, handle, lines);
              if (ok) {
                log.info(`[${CHANNEL_ID}] → ${handle}: ${lines.slice(0, 80)}${lines.length > 80 ? "…" : ""}`);
              } else {
                log.warn(`[${CHANNEL_ID}] outbound POST failed for ${handle}`);
              }
            });
          }
        }
      } catch (err: any) {
        if (signal.aborted) return;
        log.warn(`[${CHANNEL_ID}] SSE error: ${err?.message ?? err} — retry 5s`);
        await new Promise((r) => setTimeout(r, 5000));
      }
    }
  })();
}

const plugin = {
  id: "mycelium-channel",
  name: "Mycelium Channel",
  description: "Room-based agent coordination via Mycelium rooms",
  register(api: any) {
    const log = api.logger;
    const cfg = readChannelConfig();

    if (!cfg) {
      log.warn(`[${CHANNEL_ID}] not configured (set channels.mycelium-room in openclaw.json)`);
      return;
    }

    log.info(`[${CHANNEL_ID}] configured — room: ${cfg.room}, backend: ${cfg.backendUrl}`);

    // Outbound: when the LLM responds in a mycelium-channel session,
    // post the reply back to the room so other agents can see it
    api.on("llm_output", async (event: any, ctx: any) => {
      const sessionKey: string = ctx?.sessionKey ?? "";
      if (!sessionKey.includes(CHANNEL_ID)) return;

      const texts: string[] = event?.assistantTexts ?? [];
      const reply = texts.join("\n").trim();
      if (!reply) return;

      const handle = ctx?.agentId ?? cfg.handle;
      const ok = await postToRoom(cfg, handle, reply);
      if (ok) {
        log.info(`[${CHANNEL_ID}] → ${handle}: ${reply.slice(0, 80)}${reply.length > 80 ? "…" : ""}`);
      } else {
        log.warn(`[${CHANNEL_ID}] outbound POST failed for ${handle}`);
      }
    });

    // Start SSE on gateway start
    api.on("gateway_start", async () => {
      log.info(`[${CHANNEL_ID}] gateway started — starting SSE for ${cfg.room}`);
      startRoomSSE(cfg, log);
    });
  },
};

export default plugin;
