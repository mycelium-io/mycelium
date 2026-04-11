/**
 * mycelium-channel — OpenClaw Channel Plugin
 *
 * Lets multiple OpenClaw agents communicate through a shared Mycelium room.
 *
 * Inbound: SSE from room → dispatch to all agents except the sender
 * Outbound: capture agent stdout → POST reply back to room
 *
 * Config (in openclaw.json):
 *   channels: {
 *     "mycelium-room": {
 *       enabled: true,
 *       backendUrl: "http://localhost:8001",
 *       room: "test-room",
 *       agents: ["julia-agent", "selina-agent"]  // openclaw agent IDs
 *     }
 *   }
 *
 * Single-agent shorthand still works:
 *   channels: { "mycelium-room": { backendUrl: "...", room: "...", handle: "main" } }
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const CHANNEL_ID = "mycelium-room";

type ChannelConfig = {
  backendUrl: string;
  room: string;
  agents: string[];  // openclaw agent IDs participating in this room
};

function readChannelConfig(): ChannelConfig | null {
  try {
    const configPath = join(homedir(), ".openclaw", "openclaw.json");
    const raw = JSON.parse(readFileSync(configPath, "utf-8"));
    const cfg = raw?.channels?.[CHANNEL_ID];
    if (!cfg?.backendUrl || !cfg?.room) return null;

    // Support both "agents" array and legacy "handle" string
    let agents: string[];
    if (Array.isArray(cfg.agents) && cfg.agents.length > 0) {
      agents = cfg.agents.map(String);
    } else if (cfg.handle) {
      agents = [String(cfg.handle)];
    } else {
      agents = ["main"];
    }

    return {
      backendUrl: String(cfg.backendUrl).replace(/\/$/, ""),
      room: String(cfg.room),
      agents,
    };
  } catch {
    return null;
  }
}

let _abort: AbortController | null = null;

// Track message IDs we posted to prevent echo loops
const _ownMessageIds = new Set<string>();

// Track agents currently processing a message to prevent overlap
const _busyAgents = new Set<string>();

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

function dispatchToAgent(
  cfg: ChannelConfig,
  agentId: string,
  sender: string,
  content: string,
  log: { info: (s: string) => void; warn: (s: string) => void },
) {
  if (_busyAgents.has(agentId)) {
    log.info(`[${CHANNEL_ID}] ${agentId} busy — skipping message from ${sender}`);
    return;
  }
  _busyAgents.add(agentId);
  // Safety: auto-clear busy state after 90s in case process hangs or gets killed
  setTimeout(() => _busyAgents.delete(agentId), 90_000);

  const { spawn } = require("node:child_process");
  const envelope = `[Message from ${sender} in room ${cfg.room}]: ${content}`;
  const child = spawn("openclaw", [
    "agent",
    "--agent", agentId,
    "--session-id", `${CHANNEL_ID}-${cfg.room}`,
    "-m", envelope,
    "--timeout", "30",
  ], {
    detached: true,
    stdio: ["ignore", "pipe", "ignore"],
  });
  child.unref();
  log.info(`[${CHANNEL_ID}] dispatched to ${agentId} (pid=${child.pid})`);

  let agentOutput = "";
  child.stdout.on("data", (chunk: Buffer) => {
    agentOutput += chunk.toString();
  });
  child.on("close", async () => {
    _busyAgents.delete(agentId);

    // Strip ANSI codes and plugin log lines
    const reply = agentOutput
      .replace(/\x1b\[[0-9;]*m/g, "")
      .split("\n")
      .filter((l: string) => !l.startsWith("[plugins]") && !l.startsWith("[") && l.trim())
      .join("\n")
      .trim();
    if (!reply) return;

    const ok = await postToRoom(cfg, agentId, reply);
    if (ok) {
      log.info(`[${CHANNEL_ID}] → ${agentId}: ${reply.slice(0, 80)}${reply.length > 80 ? "…" : ""}`);
    } else {
      log.warn(`[${CHANNEL_ID}] outbound POST failed for ${agentId}`);
    }
  });
}

// Track session sub-rooms we're already subscribed to
const _subscribedSessions = new Set<string>();

function startSessionSSE(
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

            // Route coordination ticks and consensus from session room
            handleMessage(cfg, msg, log);
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
      dispatchToAgent(cfg, targetAgent, "CognitiveEngine", instruction, log);
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
        dispatchToAgent(cfg, agentId, "CognitiveEngine", summary, log);
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
      startSessionSSE(cfg, roomName, log);
    }
    return;
  }

  // ── Regular messages ──
  const sender = msg.sender_handle ?? "unknown";
  const content = msg.content ?? "";
  if (!content.trim()) return;

  log.info(`[${CHANNEL_ID}] ← ${sender}: ${content.slice(0, 80)}${content.length > 80 ? "…" : ""}`);

  for (const agentId of cfg.agents) {
    if (agentId === sender) continue;
    dispatchToAgent(cfg, agentId, sender, content, log);
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

            handleMessage(cfg, msg, log);
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
  register(api: any) {
    const log = api.logger;
    const cfg = readChannelConfig();

    if (!cfg) {
      log.warn(`[${CHANNEL_ID}] not configured (set channels.mycelium-room in openclaw.json)`);
      return;
    }

    log.info(`[${CHANNEL_ID}] configured — room: ${cfg.room}, agents: [${cfg.agents.join(", ")}], backend: ${cfg.backendUrl}`);

    api.on("gateway_start", async () => {
      if (process.env.MYCELIUM_CHANNEL_ONESHOT === "1") {
        log.info(`[${CHANNEL_ID}] oneshot mode — skipping SSE`);
        return;
      }
      log.info(`[${CHANNEL_ID}] gateway started — starting SSE for ${cfg.room}`);
      startRoomSSE(cfg, log);

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
              startSessionSSE(cfg, room.name, log);
            }
          }
        } catch { /* polling failure is non-fatal */ }
      }, 5000);  // poll every 5s

      // Clean up on abort
      _abort?.signal.addEventListener("abort", () => clearInterval(pollInterval));
    });
  },
};

export default plugin;
