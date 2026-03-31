// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { readFileSync } from "node:fs";
import { execSync } from "node:child_process";
import { homedir } from "node:os";
import { join } from "node:path";

/**
 * mycelium — OpenClaw Plugin
 *
 * Bridges OpenClaw agents to the Mycelium coordination backend.
 * Uses prependSystemContext (cached) for static instructions and prependContext (per-turn) for dynamic coordination state.
 *
 * Hook surface:
 *   gateway_start      — verify backend connectivity on startup
 *   gateway_stop       — graceful shutdown log
 *   session_start      — open per-agent SSE stream; register in room if already known
 *   session_end        — close SSE when last session for a handle ends; post departure
 *   before_agent_start — inject coordination instructions + latest tick context
 *   message_sent       — forward agent output to coordination room
 *
 * Room discovery (no MYCELIUM_ROOM_ID required):
 *   Each session subscribes to GET /agents/{handle}/stream on session_start.
 *   The backend delivers coordination_tick / coordination_consensus events
 *   for whatever room the agent has joined. The room name is extracted from
 *   the first event and stored per-session, enabling context fetching and
 *   message forwarding without any static room configuration.
 *
 * Handle resolution:
 *   MYCELIUM_AGENT_HANDLE env var → fixed handle for all sessions (Docker Compose)
 *   Otherwise → OpenClaw agentId (single gateway, multiple agents)
 */

// ── Coordination instructions ─────────────────────────────────────────────────

const MYCELIUM_INSTRUCTIONS = `\
# Mycelium Multi-Agent Coordination

You are operating in a shared coordination session with other AI agents managed by Mycelium.
Use the \`mycelium\` CLI to participate. Never write JSON by hand.

## Step 1 — Join the coordination backchannel

\`\`\`
mycelium session join --handle <your-agent-id> --room <room-name> -m "<your position>"
\`\`\`

This command returns immediately. CognitiveEngine will address you directly in this
room when the session starts and when it is your turn to respond.

## Step 2 — Wait for CognitiveEngine

Do nothing. CognitiveEngine will send you a message when it is your turn.

## Step 3 — Respond

The tick message will say either \`action: "propose"\` or \`action: "respond"\`.

**If action is "propose"** — pick one value per issue from the options listed and run:
\`\`\`
mycelium message propose ISSUE=VALUE ISSUE=VALUE ... --room <room-name> --handle <your-agent-id>
\`\`\`
Example:
\`\`\`
mycelium message propose budget=medium timeline=standard scope=standard quality=standard --room <room-name> --handle <your-agent-id>
\`\`\`

**If action is "respond"** — evaluate the offer and run one of:
\`\`\`
mycelium message respond accept --room <room-name> --handle <your-agent-id>
mycelium message respond reject --room <room-name> --handle <your-agent-id>
mycelium message respond end    --room <room-name> --handle <your-agent-id>
\`\`\`

Each command returns immediately. Wait for the next CognitiveEngine message.

## Step 4 — Repeat until consensus

Repeat steps 2–3 until you receive a \`[consensus]\` message containing your assignment.

## Room discipline

- Speak only when directly addressed by CognitiveEngine.
- Do not echo, acknowledge, or confirm receipt of messages.
- Do not call \`message propose\` or \`message respond\` unless CognitiveEngine has just addressed you.
- Default to silence.
`;

// ─────────────────────────────────────────────────────────────────────────────

// Config loaded from `mycelium --json config show` at gateway_start.
// Falls back to env vars so Docker/CI overrides still work.
let API_URL = (process.env.MYCELIUM_API_URL ?? "").replace(/\/$/, "");
let WORKSPACE_ID = process.env.MYCELIUM_WORKSPACE_ID ?? "";
let MAS_ID = process.env.MYCELIUM_MAS_ID ?? "";
const AGENT_ID = process.env.MYCELIUM_AGENT_ID ?? "";

function loadMyceliumConfig(): void {
  try {
    const raw = execSync("mycelium --json config show", { encoding: "utf-8", timeout: 5000 });
    const cfg = JSON.parse(raw);
    if (!process.env.MYCELIUM_API_URL && cfg?.server?.api_url) {
      API_URL = cfg.server.api_url.replace(/\/$/, "");
    }
    if (!process.env.MYCELIUM_WORKSPACE_ID && cfg?.server?.workspace_id) {
      WORKSPACE_ID = cfg.server.workspace_id;
    }
    if (!process.env.MYCELIUM_MAS_ID && cfg?.server?.mas_id) {
      MAS_ID = cfg.server.mas_id;
    }
  } catch {
    // mycelium CLI not installed or config unreadable — fall back to env vars
  }
}

// Custom memory file — read fresh on every before_agent_start invocation
const MEMORY_FILE = join(
  homedir(),
  ".openclaw/workspace/memory/mycelium-context.md"
);

// ── Per-session tracking ───────────────────────────────────────────────────
// room is populated dynamically from the first SSE tick event

type SessionEntry = {
  sessionKey: string;
  sessionId?: string;
  handle: string;
  room?: string;
};
const _sessions = new Map<string, SessionEntry>(); // agentId → entry

// One SSE connection per handle (shared across sessions with the same handle)
const _sseByHandle = new Map<string, AbortController>(); // handle → abort

// ── Helpers ───────────────────────────────────────────────────────────────────

function resolveHandle(agentId?: string | null): string {
  if (process.env.MYCELIUM_AGENT_HANDLE) {
    return process.env.MYCELIUM_AGENT_HANDLE;
  }
  if (agentId?.trim()) {
    return agentId.trim();
  }
  const matrixId = process.env.MATRIX_USER_ID ?? "";
  if (matrixId.startsWith("@")) {
    return matrixId.slice(1).split(":")[0];
  }
  return matrixId || "unknown-agent";
}

async function apiPost(
  path: string,
  body: unknown,
  log: { warn: (s: string) => void }
): Promise<boolean> {
  try {
    const res = await fetch(`${API_URL}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      log.warn(`[mycelium] POST ${path} → ${res.status}`);
      return false;
    }
    return true;
  } catch (e) {
    log.warn(`[mycelium] POST ${path} error: ${e}`);
    return false;
  }
}

async function apiGet(
  path: string,
  log: { warn: (s: string) => void }
): Promise<unknown> {
  try {
    const res = await fetch(`${API_URL}${path}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (e) {
    log.warn(`[mycelium] GET ${path} error: ${e}`);
    return null;
  }
}

// ── Plugin ────────────────────────────────────────────────────────────────────

export default function register(api: {
  logger: { info: (s: string) => void; warn: (s: string) => void };
  on: (event: string, handler: (...args: any[]) => any, opts?: object) => void;
}): void {
  const log = api.logger;

  // ── SSE subscription helper ────────────────────────────────────────────────
  // Opens a persistent SSE connection to /agents/{handle}/stream.
  // On tick/consensus: stores room in session entries, wakes matching sessions.
  // Reconnects automatically on error.

  function subscribeHandle(handle: string): void {
    if (_sseByHandle.has(handle)) return;

    const abort = new AbortController();
    _sseByHandle.set(handle, abort);
    const signal = abort.signal;

    log.info(`[mycelium] SSE subscribing for ${handle}`);

    (async () => {
      while (!signal.aborted) {
        try {
          const res = await fetch(`${API_URL}/agents/${encodeURIComponent(handle)}/stream`, {
            headers: { Accept: "text/event-stream" },
            signal,
          });

          if (!res.ok || !res.body) {
            log.warn(`[mycelium] SSE connect failed for ${handle} (${res.status}) — retrying in 5s`);
            await new Promise(r => setTimeout(r, 5000));
            continue;
          }

          log.info(`[mycelium] SSE connected for ${handle}`);

          const reader = (res.body as any).getReader();
          const decoder = new TextDecoder();
          let buffer = "";

          while (!signal.aborted) {
            let chunk: { done: boolean; value?: Uint8Array };
            try {
              chunk = await reader.read();
            } catch (e: any) {
              if (signal.aborted || e?.name === "AbortError") return;
              throw e;
            }
            if (chunk.done) break;

            buffer += decoder.decode(chunk.value, { stream: true });
            const blocks = buffer.split("\n\n");
            buffer = blocks.pop() ?? "";

            for (const block of blocks) {
              const dataLine = block.split("\n").find(l => l.startsWith("data: "));
              if (!dataLine) continue;
              const raw = dataLine.slice(6).trim();
              if (!raw || raw === "{}") continue;

              let msg: any;
              try { msg = JSON.parse(raw); } catch { continue; }

              const { message_type, room_name, content } = msg;
              if (
                message_type !== "coordination_tick" &&
                message_type !== "coordination_consensus"
              ) continue;

              const isConsensus = message_type === "coordination_consensus";

              let addressed_to: string[] | undefined;
              if (!isConsensus) {
                try {
                  const parsed = JSON.parse(content);
                  if (Array.isArray(parsed.addressed_to)) {
                    addressed_to = parsed.addressed_to;
                  }
                } catch { /* wake all on parse failure */ }
              }

              const label = isConsensus ? "[Mycelium consensus]" : "[Mycelium tick]";
              const wakeText = isConsensus
                ? `${label} room:${room_name ?? "unknown"}\n\n${content}`
                : `${label} room:${room_name ?? "unknown"}\n\n${content}\n\n` +
                  `**ACTION REQUIRED**: Respond immediately using the mycelium CLI.\n` +
                  `- If the tick action is "propose": run \`mycelium message propose ISSUE=VALUE ... --room ${room_name ?? "unknown"} --handle ${handle}\`\n` +
                  `- If the tick action is "respond": run \`mycelium message respond accept|reject|end --room ${room_name ?? "unknown"} --handle ${handle}\`\n` +
                  `Do NOT reply conversationally. Run the command now.`;

              for (const [agentId, entry] of _sessions) {
                if (entry.handle !== handle) continue;
                if (!isConsensus && addressed_to && !addressed_to.includes(handle)) continue;

                // Store room for context fetching / message forwarding
                if (room_name && !entry.room) {
                  entry.room = room_name;
                  _sessions.set(agentId, entry);
                  log.info(`[mycelium] ${handle} room discovered: ${room_name}`);
                }

                log.info(`[mycelium] ${message_type} → waking ${handle} (sessionKey:${entry.sessionKey})`);
                const agentParams = JSON.stringify({
                  sessionKey: entry.sessionKey,
                  message: wakeText,
                  deliver: true,
                  idempotencyKey: `mycelium:${message_type}:${handle}:${Date.now()}`,
                });
                void import("node:child_process").then(({ spawn }) => {
                  const child = spawn(
                    "openclaw",
                    ["gateway", "call", "agent", "--params", agentParams, "--timeout", "10000"],
                    { detached: true, stdio: "ignore" },
                  );
                  child.unref();
                  log.info(`[mycelium] gateway call dispatched for ${handle} (pid ${child.pid})`);
                }).catch((err: unknown) => {
                  log.warn(`[mycelium] dispatch failed for ${handle}: ${err}`);
                });
              }
            }
          }
        } catch (e: any) {
          if (signal.aborted || e?.name === "AbortError") return;
          log.warn(`[mycelium] SSE error for ${handle}: ${e} — retrying in 5s`);
          await new Promise(r => setTimeout(r, 5000));
        }
      }
    })();
  }

  function unsubscribeHandle(handle: string): void {
    const remaining = [..._sessions.values()].some(e => e.handle === handle);
    if (!remaining) {
      _sseByHandle.get(handle)?.abort();
      _sseByHandle.delete(handle);
      log.info(`[mycelium] SSE closed for ${handle}`);
    }
  }

  // ── gateway_start ──────────────────────────────────────────────────────────

  api.on("gateway_start", async () => {
    loadMyceliumConfig();
    if (!API_URL) {
      log.warn("[mycelium] No API URL found in config or env — plugin inactive");
      return;
    }
    try {
      const res = await fetch(`${API_URL}/health`);
      if (res.ok) {
        log.info(`[mycelium] Ready | backend: ${API_URL}`);
      } else {
        log.warn(`[mycelium] Backend unhealthy (${res.status}) — will retry per call`);
      }
    } catch {
      log.warn(`[mycelium] Cannot reach ${API_URL} — will retry per call`);
    }
  });

  // ── gateway_stop ───────────────────────────────────────────────────────────

  api.on("gateway_stop", async () => {
    for (const abort of _sseByHandle.values()) abort.abort();
    _sseByHandle.clear();
    log.info("[mycelium] Gateway stopping — plugin shutdown");
  });

  // ── session_start ──────────────────────────────────────────────────────────

  api.on("session_start", async (event: { sessionId: string; resumedFrom?: string }, ctx: any) => {
    const agentId: string | undefined = ctx?.agentId;
    const sessionKey: string | undefined = ctx?.sessionKey;
    const handle = resolveHandle(agentId);

    // Store sessionId for any channel-originated session.
    // CLI sessions end with ":main" — don't overwrite an existing channel sessionId with them.
    const isCliSession = sessionKey?.endsWith(":main");
    log.info(`[mycelium] session_start handle:${handle} sessionId:${event.sessionId} sessionKey:${sessionKey ?? "none"} isCliSession:${isCliSession}`);
    if (sessionKey) {
      const existing = _sessions.get(agentId ?? "default");
      const sessionId = isCliSession ? existing?.sessionId : event.sessionId;
      _sessions.set(agentId ?? "default", { sessionKey, sessionId, handle, room: existing?.room });
    }

    subscribeHandle(handle);

    if (event.resumedFrom) {
      log.info(`[mycelium] Session resumed (${event.sessionId})`);
    } else {
      log.info(`[mycelium] Session started — ${handle} (${event.sessionId})`);
    }
  });

  // ── session_end ────────────────────────────────────────────────────────────

  api.on("session_end", async (event: { sessionId: string; messageCount: number }, ctx: any) => {
    const agentId: string | undefined = ctx?.agentId;
    const handle = resolveHandle(agentId);
    const entry = _sessions.get(agentId ?? "default");

    if (agentId) _sessions.delete(agentId);

    log.info(`[mycelium] Session ${event.sessionId} ended (${event.messageCount} messages)`);

    if (entry?.room) {
      await apiPost(`/rooms/${entry.room}/messages`, {
        sender_handle: handle,
        recipient_handle: null,
        message_type: "announce",
        content: "agent offline (session ended)",
      }, log);
    }

    unsubscribeHandle(handle);
  });

  // ── before_agent_start ─────────────────────────────────────────────────────

  api.on("before_agent_start", async (_event: any, ctx: any): Promise<{ prependSystemContext?: string; prependContext?: string } | undefined> => {
    const agentId: string | undefined = ctx?.agentId;
    const sessionKey: string | undefined = ctx?.sessionKey;
    const handle = resolveHandle(agentId);

    // Keep session map fresh; ensure SSE is subscribed even if session_start was missed.
    // Don't overwrite a channel sessionId with a CLI one (CLI keys end with ":main").
    const sessionId: string | undefined = ctx?.sessionId;
    const isCliSession = sessionKey?.endsWith(":main");
    log.info(`[mycelium] before_agent_start handle:${handle} sessionKey:${sessionKey ?? "none"} isCliSession:${isCliSession}`);
    let existing = _sessions.get(agentId ?? "default");
    if (!existing && sessionKey) {
      existing = { sessionKey, sessionId: isCliSession ? undefined : sessionId, handle };
      _sessions.set(agentId ?? "default", existing);
    } else if (existing) {
      if (sessionKey) existing.sessionKey = sessionKey;
      if (sessionId && !existing.sessionId && !isCliSession) existing.sessionId = sessionId;
    }

    subscribeHandle(handle);

    // STATIC — cached in system prompt, cheap after turn 1
    const systemParts: string[] = [
      MYCELIUM_INSTRUCTIONS,
      `Your Mycelium handle for this session is: \`${handle}\`\nUse this exact value for \`--handle\` when joining a room.`,
    ];

    // DYNAMIC — fresh each turn, injected into user prompt
    const contextParts: string[] = [];

    const room = existing?.room;
    if (room) {
      const data = await apiGet(`/rooms/${room}/messages?limit=30`, log) as any;
      const coord = data?.messages?.find(
        (m: any) =>
          m.message_type === "coordination_consensus" ||
          m.message_type === "coordination_tick"
      );

      if (coord) {
        const label = coord.message_type === "coordination_consensus"
          ? "[Mycelium — consensus]"
          : "[Mycelium — coordination tick]";
        contextParts.push(`${label}\nRoom: ${room}\n\n${coord.content}`);
      }
    }

    // Read custom memory file (fresh each turn)
    try {
      const memory = readFileSync(MEMORY_FILE, "utf-8").trim();
      if (memory) {
        contextParts.push(`# Injected Memory (per-turn)\n\n${memory}`);
        log.info(`[mycelium] Injected ${memory.length} bytes from ${MEMORY_FILE}`);
      }
    } catch {
      // Memory file doesn't exist yet — skip
    }

    log.info(`[mycelium] prependSystemContext: ${systemParts.join("\n\n").length} chars (cached), prependContext: ${contextParts.length ? contextParts.join("\n\n").length : 0} chars (dynamic)`);

    return {
      prependSystemContext: systemParts.join("\n\n"),
      prependContext: contextParts.length ? contextParts.join("\n\n") : undefined,
    };
  });

  // ── message_sent ───────────────────────────────────────────────────────────

  api.on(
    "message_sent",
    async (event: { to: string; content: string; success: boolean }, ctx: any) => {
      if (!event.success) return;
      if (!event.content?.trim() || event.content.trim().length < 5) return;

      const agentId: string | undefined = ctx?.agentId;
      const handle = resolveHandle(agentId);
      const room = _sessions.get(agentId ?? "default")?.room;

      if (room) {
        await apiPost(`/rooms/${room}/messages`, {
          sender_handle: handle,
          recipient_handle: null,
          message_type: "broadcast",
          content: event.content,
        }, log);
      }

      if (WORKSPACE_ID && MAS_ID) {
        apiPost("/api/knowledge/ingest", {
          workspace_id: WORKSPACE_ID,
          mas_id: MAS_ID,
          agent_id: AGENT_ID || undefined,
          records: [{ response: event.content }],
        }, log).catch((err) => log.warn(`[mycelium] ingest failed: ${err}`));
      }
    }
  );
}
