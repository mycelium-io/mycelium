/**
 * mycelium-channel — OpenClaw Channel Plugin
 *
 * Lets multiple OpenClaw agents communicate through a shared Mycelium room.
 *
 * Architecture: uses OpenClaw's in-process dispatch via
 *   `runtime.channel.reply.dispatchReplyWithBufferedBlockDispatcher`.
 * No subprocess spawning, no stdout parsing. The agent runs inside the gateway
 * and its clean reply payload is POSTed back to the Mycelium room from the
 * `deliver` callback.
 *
 * Inbound flow:
 *   1. SSE from Mycelium room (+ session sub-rooms for coordination ticks)
 *   2. For each agent in cfg.agents (minus sender), build a MsgContext and
 *      call dispatchReplyWithBufferedBlockDispatcher.
 *   3. The `deliver` callback captures the agent's normalized ReplyPayload
 *      and POSTs the text back to the room.
 *
 * Config (in openclaw.json):
 *   channels: {
 *     "mycelium-room": {
 *       enabled: true,
 *       backendUrl: "http://localhost:8001",
 *       room: "test-room",
 *       agents: ["julia-agent", "selina-agent"]
 *     }
 *   }
 */

import type {
  OpenClawPluginApi,
  ReplyPayload,
} from "openclaw/plugin-sdk";

const CHANNEL_ID = "mycelium-room";

type ChannelConfig = {
  backendUrl: string;
  room: string;
  agents: string[];
  /**
   * When true (default), agents only respond to messages that explicitly @-mention them.
   * This prevents cascade chatter (agent A replies → triggers agent B → triggers agent A).
   * Coordination ticks always dispatch to their participant_id regardless of this flag.
   * Set to false only if you genuinely want broadcast chat (not recommended — use the CLI
   * for structured negotiation instead).
   */
  requireMention: boolean;
};

function readChannelConfig(cfg: any): ChannelConfig | null {
  const entry = cfg?.channels?.[CHANNEL_ID];
  if (!entry?.backendUrl || !entry?.room) return null;

  let agents: string[];
  if (Array.isArray(entry.agents) && entry.agents.length > 0) {
    agents = entry.agents.map(String);
  } else if (entry.handle) {
    agents = [String(entry.handle)];
  } else {
    agents = ["main"];
  }

  return {
    backendUrl: String(entry.backendUrl).replace(/\/$/, ""),
    room: String(entry.room),
    agents,
    requireMention: entry.requireMention !== false,  // default true
  };
}

/**
 * Return the subset of `agents` that are @-mentioned in `content`.
 * Matches `@agent-id` as a word (case-insensitive). `@julia-agent` matches,
 * bare `julia-agent` does not — must use the `@` prefix to be a mention.
 */
function resolveMentions(content: string, agents: string[]): string[] {
  const lower = content.toLowerCase();
  return agents.filter((agentId) => {
    const needle = `@${agentId.toLowerCase()}`;
    const idx = lower.indexOf(needle);
    if (idx === -1) return false;
    // Require a word boundary after the handle so `@julia-agent-bot` doesn't match `@julia-agent`.
    const nextChar = lower[idx + needle.length];
    return !nextChar || !/[a-z0-9_-]/.test(nextChar);
  });
}

// Build a sessionKey matching buildAgentPeerSessionKey format (group peer).
// See openclaw src/routing/session-key.ts:buildAgentPeerSessionKey.
function buildSessionKey(agentId: string, room: string): string {
  return `agent:${agentId.toLowerCase()}:${CHANNEL_ID}:group:${room.toLowerCase()}`;
}

let _abort: AbortController | null = null;

// Track message IDs we posted to prevent echo loops
const _ownMessageIds = new Set<string>();

// Track session sub-rooms we're already subscribed to
const _subscribedSessions = new Set<string>();

async function postToRoom(
  cfg: ChannelConfig,
  senderHandle: string,
  content: string,
): Promise<boolean> {
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
      try {
        const body = await res.json();
        if (body?.id) _ownMessageIds.add(body.id);
      } catch { /* non-fatal */ }
    }
    return res.ok;
  } catch {
    return false;
  }
}

async function dispatchToAgent(
  runtime: any,
  cfg: ChannelConfig,
  agentId: string,
  sender: string,
  content: string,
  messageId: string | undefined,
  log: { info: (s: string) => void; warn: (s: string) => void },
): Promise<void> {
  const openclawConfig = runtime.config.loadConfig();
  const sessionKey = buildSessionKey(agentId, cfg.room);

  const envelopeBody = `[${sender} in ${cfg.room}]: ${content}`;

  const ctx = runtime.channel.reply.finalizeInboundContext({
    Body: envelopeBody,
    BodyForAgent: content,
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
      dispatcherOptions: {
        deliver: async (payload: ReplyPayload) => {
          const text = payload.text?.trim();
          if (!text) return;
          const ok = await postToRoom(cfg, agentId, text);
          if (ok) {
            log.info(`[${CHANNEL_ID}] ← ${agentId}: ${text.slice(0, 80)}${text.length > 80 ? "…" : ""}`);
          } else {
            log.warn(`[${CHANNEL_ID}] outbound POST failed for ${agentId}`);
          }
        },
        onError: (err: unknown, info: { kind: string }) => {
          log.warn(`[${CHANNEL_ID}] ${info.kind} reply failed for ${agentId}: ${String(err)}`);
        },
      },
    });
  } catch (err: any) {
    log.warn(`[${CHANNEL_ID}] dispatch failed for ${agentId}: ${err?.message ?? err}`);
  }
}

function startSessionSSE(
  runtime: any,
  cfg: ChannelConfig,
  sessionRoom: string,
  log: { info: (s: string) => void; warn: (s: string) => void },
) {
  if (_subscribedSessions.has(sessionRoom)) return;
  _subscribedSessions.add(sessionRoom);

  const signal = _abort?.signal;
  if (!signal) return;

  const sseUrl = `${cfg.backendUrl}/rooms/${encodeURIComponent(sessionRoom)}/messages/stream`;
  log.info(`[${CHANNEL_ID}] subscribing to session room: ${sessionRoom}`);

  (async () => {
    while (signal && !signal.aborted) {
      try {
        const res = await fetch(sseUrl, { headers: { Accept: "text/event-stream" }, signal });
        if (!res.ok || !res.body) {
          log.warn(`[${CHANNEL_ID}] session SSE ${res.status} for ${sessionRoom} — retry 5s`);
          await new Promise((r) => setTimeout(r, 5000));
          continue;
        }

        log.info(`[${CHANNEL_ID}] session SSE connected: ${sessionRoom}`);
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

            handleMessage(runtime, cfg, msg, log);
          }
        }
      } catch (err: any) {
        if (signal.aborted) return;
        log.warn(`[${CHANNEL_ID}] session SSE error: ${err?.message} — retry 5s`);
        await new Promise((r) => setTimeout(r, 5000));
      }
    }
  })();
}

function handleMessage(
  runtime: any,
  cfg: ChannelConfig,
  msg: any,
  log: { info: (s: string) => void; warn: (s: string) => void },
) {
  // Skip messages we posted (loop prevention)
  if (msg.id && _ownMessageIds.has(msg.id)) {
    _ownMessageIds.delete(msg.id);
    return;
  }
  if (msg.message_type === "announce") return;

  // ── Coordination ticks: CognitiveEngine addressing a specific agent ──
  if (msg.message_type === "coordination_tick") {
    try {
      const tickData = typeof msg.content === "string" ? JSON.parse(msg.content) : msg.content;
      const payload = tickData?.payload ?? tickData;
      const targetAgent = payload?.participant_id;
      if (!targetAgent || !cfg.agents.includes(targetAgent)) return;

      const action = payload?.action ?? "respond";
      const canCounter = payload?.can_counter_offer === true;
      const currentOffer = payload?.current_offer ?? {};
      const round = payload?.round ?? "?";
      const roomName = msg.room_name ?? cfg.room;

      const offerSummary = Object.entries(currentOffer)
        .map(([k, v]) => `  ${k}: ${v}`)
        .join("\n");

      const instruction = [
        `[CognitiveEngine — Round ${round}]`,
        `You are in a structured negotiation in room ${roomName}.`,
        `Action required: ${action}`,
        canCounter ? "You CAN propose a counter-offer." : "You can only accept or reject.",
        "",
        "Current offer on the table:",
        offerSummary,
        "",
        canCounter
          ? "To counter-propose, run: mycelium message propose ISSUE=VALUE ISSUE=VALUE ... --room " + roomName + " --handle " + targetAgent
          : "",
        "To accept: mycelium message respond accept --room " + roomName + " --handle " + targetAgent,
        "To reject: mycelium message respond reject --room " + roomName + " --handle " + targetAgent,
        "",
        "Explain your reasoning before running the command.",
      ].filter(Boolean).join("\n");

      log.info(`[${CHANNEL_ID}] 🎯 tick r${round} → ${targetAgent} (${action}, counter=${canCounter})`);
      void dispatchToAgent(runtime, cfg, targetAgent, "CognitiveEngine", instruction, msg.id, log);
    } catch (err: any) {
      log.warn(`[${CHANNEL_ID}] tick parse error: ${err?.message}`);
    }
    return;
  }

  // ── Coordination consensus ──
  if (msg.message_type === "coordination_consensus") {
    try {
      const consensusData = typeof msg.content === "string" ? JSON.parse(msg.content) : msg.content;
      const plan = consensusData?.plan ?? "No plan details";
      const assignments = consensusData?.assignments ?? {};
      const broken = consensusData?.broken === true;

      const summary = broken
        ? `[CognitiveEngine — Negotiation FAILED]\n${plan}`
        : [
            "[CognitiveEngine — Consensus Reached!]",
            "",
            typeof plan === "string" ? plan : JSON.stringify(plan, null, 2),
            "",
            "Assignments:",
            ...Object.entries(assignments).map(([agent, task]) => `  ${agent}: ${task}`),
          ].join("\n");

      log.info(`[${CHANNEL_ID}] 🤝 consensus ${broken ? "BROKEN" : "reached"}`);

      for (const agentId of cfg.agents) {
        void dispatchToAgent(runtime, cfg, agentId, "CognitiveEngine", summary, msg.id, log);
      }
    } catch (err: any) {
      log.warn(`[${CHANNEL_ID}] consensus parse error: ${err?.message}`);
    }
    return;
  }

  // ── Coordination join: detect session sub-room and subscribe ──
  if (msg.message_type === "coordination_join" || msg.message_type === "coordination_start") {
    const roomName = msg.room_name;
    if (roomName && roomName.includes(":session:")) {
      startSessionSSE(runtime, cfg, roomName, log);
    }
    return;
  }

  // ── Regular messages ──
  const sender = msg.sender_handle ?? "unknown";
  const content = msg.content ?? "";
  if (!content.trim()) return;

  log.info(`[${CHANNEL_ID}] ← ${sender}: ${content.slice(0, 80)}${content.length > 80 ? "…" : ""}`);

  // Build the recipient list based on requireMention policy.
  let recipients: string[];
  if (cfg.requireMention) {
    // Addressed-only: only agents explicitly @-mentioned (excluding sender).
    const mentioned = resolveMentions(content, cfg.agents);
    recipients = mentioned.filter((agentId) => agentId !== sender);
    if (recipients.length === 0) {
      log.info(`[${CHANNEL_ID}] no addressed recipients — ignoring (requireMention=true)`);
      return;
    }
    log.info(`[${CHANNEL_ID}] addressed to: ${recipients.join(", ")}`);
  } else {
    // Broadcast mode: everyone except sender (legacy behavior, not recommended).
    recipients = cfg.agents.filter((agentId) => agentId !== sender);
  }

  for (const agentId of recipients) {
    void dispatchToAgent(runtime, cfg, agentId, sender, content, msg.id, log);
  }
}

function startRoomSSE(
  runtime: any,
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

        log.info(`[${CHANNEL_ID}] SSE connected: ${cfg.room} (agents: ${cfg.agents.join(", ")})`);
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

            handleMessage(runtime, cfg, msg, log);
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
  description: "Room-based multi-agent coordination via Mycelium rooms",
  register(api: OpenClawPluginApi) {
    const log = api.logger;
    const runtime = api.runtime;
    const cfg = readChannelConfig(api.config);

    if (!cfg) {
      log.warn(`[${CHANNEL_ID}] not configured (set channels.mycelium-room in openclaw.json)`);
      return;
    }

    log.info(`[${CHANNEL_ID}] configured — room: ${cfg.room}, agents: [${cfg.agents.join(", ")}], backend: ${cfg.backendUrl}, requireMention: ${cfg.requireMention}`);

    api.on("gateway_start", async () => {
      log.info(`[${CHANNEL_ID}] gateway started — starting SSE for ${cfg.room}`);
      startRoomSSE(runtime, cfg, log);

      // Poll for session sub-rooms and subscribe to their SSE
      const pollInterval = setInterval(async () => {
        try {
          const res = await fetch(`${cfg.backendUrl}/rooms`);
          if (!res.ok) return;
          const rooms: any[] = await res.json();
          for (const room of rooms) {
            if (
              room.name?.startsWith(cfg.room + ":session:") &&
              (room.coordination_state === "waiting" || room.coordination_state === "negotiating")
            ) {
              startSessionSSE(runtime, cfg, room.name, log);
            }
          }
        } catch { /* polling failure is non-fatal */ }
      }, 5000);

      _abort?.signal.addEventListener("abort", () => clearInterval(pollInterval));
    });

    api.on("gateway_stop", async () => {
      _abort?.abort();
      _abort = null;
      _subscribedSessions.clear();
      log.info(`[${CHANNEL_ID}] gateway stopping — SSE closed`);
    });
  },
};

export default plugin;
