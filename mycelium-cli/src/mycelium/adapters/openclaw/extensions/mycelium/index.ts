// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * mycelium — OpenClaw Plugin
 *
 * Bridges OpenClaw agents to the Mycelium coordination backend.
 * Uses prependSystemContext (cached) for static instructions and prependContext (per-turn) for dynamic coordination state.
 *
 * Env vs HTTP are split across `mycelium-env.ts` and `mycelium-http.ts` (OpenClaw install scan).
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

import {
  getAgentId,
  getApiUrl,
  getMasId,
  getWorkspaceId,
  loadMyceliumConfig,
  readMemoryFileContent,
  resolveHandle,
} from "./mycelium-env.js";
import {
  apiGet,
  apiPost,
  fetchAgentEventStream,
  fetchBackendHealth,
  wakeAgent,
} from "./mycelium-http.js";
import type { SubagentRuntime } from "./mycelium-http.js";

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

**If action is "propose"** — you are being asked to make a counter-offer. Pick one value per issue from the options listed and run:
\`\`\`
mycelium message propose ISSUE=VALUE ISSUE=VALUE ... --room <room-name> --handle <your-agent-id>
\`\`\`
Example:
\`\`\`
mycelium message propose budget=medium timeline=standard scope=standard quality=standard --room <room-name> --handle <your-agent-id>
\`\`\`

**If action is "respond"** — evaluate the current offer in \`current_offer\` and run one of:
\`\`\`
mycelium message respond accept --room <room-name> --handle <your-agent-id>
mycelium message respond reject --room <room-name> --handle <your-agent-id>
\`\`\`

Each command returns immediately. Wait for the next CognitiveEngine message.

## Step 4 — Repeat until consensus

Repeat steps 2–3 until you receive a \`[consensus]\` message containing your assignment.

## Room discipline

- Only run \`message propose\` or \`message respond\` when CognitiveEngine has just addressed you.
- Before each command, briefly narrate your reasoning in chat so the human can follow along (e.g., "Rejecting — the timeline is too aggressive. Proposing 6 months instead.").
- Do not echo or confirm receipt of CognitiveEngine messages — just explain your choice and act.
`;

// ── Per-session tracking ───────────────────────────────────────────────────

type SessionEntry = {
  sessionKey: string;
  sessionId?: string;
  handle: string;
  room?: string;
};
const _sessions = new Map<string, SessionEntry>();

const _sseByHandle = new Map<string, AbortController>();

// ── Plugin ────────────────────────────────────────────────────────────────────

export default function register(api: {
  logger: { info: (s: string) => void; warn: (s: string) => void };
  on: (event: string, handler: (...args: any[]) => any, opts?: object) => void;
  runtime: { subagent: SubagentRuntime };
}): void {
  const log = api.logger;
  const subagent = api.runtime.subagent;

  function subscribeHandle(handle: string): void {
    if (_sseByHandle.has(handle)) return;

    const base = getApiUrl();
    if (!base) {
      log.warn(`[mycelium] SSE skipped for ${handle} — no API URL configured (set MYCELIUM_API_URL or check ~/.mycelium/config.toml)`);
      return;
    }

    const abort = new AbortController();
    _sseByHandle.set(handle, abort);
    const signal = abort.signal;

    log.info(`[mycelium] SSE subscribing for ${handle}`);

    (async () => {
      while (!signal.aborted) {
        try {
          const res = await fetchAgentEventStream(handle, signal);

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
              let tickAction: string | undefined;
              if (!isConsensus) {
                try {
                  const parsed = JSON.parse(content);
                  if (Array.isArray(parsed.addressed_to)) {
                    addressed_to = parsed.addressed_to;
                  }
                  // Support both top-level participant_id (NegMAS) and payload.participant_id (CFN)
                  const payload = parsed?.payload ?? parsed;
                  const pid: string | undefined = payload?.participant_id;
                  if (pid && !addressed_to) {
                    addressed_to = [pid];
                  }
                  tickAction = payload?.action;
                } catch { /* wake all on parse failure */ }
              }

              const label = isConsensus ? "[Mycelium consensus]" : "[Mycelium tick]";
              const wakeText = isConsensus
                ? `${label} room:${room_name ?? "unknown"}\n\n${content}`
                : `${label} room:${room_name ?? "unknown"}\n\n${content}\n\n` +
                  `**ACTION REQUIRED**: Respond immediately using the mycelium CLI.\n` +
                  (tickAction === "propose"
                    ? `- Run \`mycelium message propose ISSUE=VALUE ... --room ${room_name ?? "unknown"} --handle ${handle}\`\n`
                    : `- Run \`mycelium message respond accept|reject --room ${room_name ?? "unknown"} --handle ${handle}\`\n`) +
                  `Do NOT reply conversationally. Run the command now.`;

              for (const [agentId, entry] of _sessions) {
                if (entry.handle !== handle) continue;
                if (!isConsensus && addressed_to && !addressed_to.includes(handle)) continue;

                if (room_name && !entry.room) {
                  entry.room = room_name;
                  _sessions.set(agentId, entry);
                  log.info(`[mycelium] ${handle} room discovered: ${room_name}`);
                }

                log.info(`[mycelium] ${message_type} → waking ${handle} (sessionKey:${entry.sessionKey})`);
                wakeAgent(
                  {
                    sessionKey: entry.sessionKey,
                    message: wakeText,
                    idempotencyKey: `mycelium:${message_type}:${handle}:${Date.now()}`,
                  },
                  subagent,
                  log,
                  handle
                );
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

  api.on("gateway_start", async () => {
    loadMyceliumConfig();
    if (!getApiUrl()) {
      log.warn("[mycelium] No API URL found in config or env — plugin inactive");
      return;
    }
    try {
      const res = await fetchBackendHealth();
      if (res.ok) {
        log.info(`[mycelium] Ready | backend: ${getApiUrl()}`);
      } else {
        log.warn(`[mycelium] Backend unhealthy (${res.status}) — will retry per call`);
      }
    } catch {
      log.warn(`[mycelium] Cannot reach ${getApiUrl()} — will retry per call`);
    }
  });

  api.on("gateway_stop", async () => {
    for (const abort of _sseByHandle.values()) abort.abort();
    _sseByHandle.clear();
    log.info("[mycelium] Gateway stopping — plugin shutdown");
  });

  api.on("session_start", async (event: { sessionId: string; resumedFrom?: string }, ctx: any) => {
    const agentId: string | undefined = ctx?.agentId;
    const sessionKey: string | undefined = ctx?.sessionKey;
    const handle = resolveHandle(agentId);

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

  api.on("before_agent_start", async (_event: any, ctx: any): Promise<{ prependSystemContext?: string; prependContext?: string } | undefined> => {
    const agentId: string | undefined = ctx?.agentId;
    const sessionKey: string | undefined = ctx?.sessionKey;
    const handle = resolveHandle(agentId);

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

    const systemParts: string[] = [
      MYCELIUM_INSTRUCTIONS,
      `Your Mycelium handle for this session is: \`${handle}\`\nUse this exact value for \`--handle\` when joining a room.`,
    ];

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

    const memory = readMemoryFileContent();
    if (memory) {
      contextParts.push(`# Injected Memory (per-turn)\n\n${memory}`);
      log.info(`[mycelium] Injected ${memory.length} bytes from memory file`);
    }

    log.info(`[mycelium] prependSystemContext: ${systemParts.join("\n\n").length} chars (cached), prependContext: ${contextParts.length ? contextParts.join("\n\n").length : 0} chars (dynamic)`);

    return {
      prependSystemContext: systemParts.join("\n\n"),
      prependContext: contextParts.length ? contextParts.join("\n\n") : undefined,
    };
  });

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

      const ws = getWorkspaceId();
      const ms = getMasId();
      if (ws && ms) {
        apiPost("/api/knowledge/ingest", {
          workspace_id: ws,
          mas_id: ms,
          agent_id: getAgentId() || undefined,
          records: [{ response: event.content }],
        }, log).catch((err) => log.warn(`[mycelium] ingest failed: ${err}`));
      }
    }
  );
}
