/**
 * mycelium-knowledge-extract
 *
 * Reads the session JSONL and ships structured conversation turns to
 * mycelium-backend (POST /api/knowledge/ingest), which forwards them to
 * CFN's shared-memories endpoint. A per-session state file tracks the
 * last-sent turn index so only new turns travel each time.
 *
 * Configuration lives in ~/.mycelium/config.toml under [knowledge_ingest]
 * and is read via getIngestConfig() in knowledge-env.js. Every knob is
 * also overridable via MYCELIUM_INGEST_* env vars for ephemeral changes.
 *
 * Falls back to a local log file if Mycelium is not configured.
 */

import fs from "fs";
import fsPromises from "fs/promises";
import path from "path";
import os from "os";

import { getIngestConfig, getIngestTarget } from "./knowledge-env.js";
import { postKnowledgeIngest } from "./knowledge-http.js";

const STATE_DIR = path.join(os.homedir(), ".openclaw");
const LOG_FILE = path.join(STATE_DIR, "mycelium-knowledge-extract.log");
const DELTA_STATE_DIR = path.join(STATE_DIR, "mycelium-extract-state");

// ── Session file resolution ──────────────────────────────────────────────────

function resolveSessionFile(agentId, sessionId) {
  return path.join(
    STATE_DIR,
    "agents",
    agentId,
    "sessions",
    `${sessionId}.jsonl`,
  );
}

function resolveSessionsIndexPath(agentId) {
  return path.join(STATE_DIR, "agents", agentId, "sessions", "sessions.json");
}

/**
 * Resolve {agentId, sessionId} from a hook event. agent:bootstrap supplies
 * both in ctx. message:sent / message:received only carry sessionKey, so
 * we parse agentId from there and look up the active agent session UUID
 * in ~/.openclaw/agents/<agentId>/sessions/sessions.json.
 *
 * Returns null when anything needed is missing — callers treat null as
 * "skip this fire silently."
 */
export function resolveAgentSession(event) {
  const ctx = event.context ?? {};
  if (ctx.agentId && ctx.sessionId) {
    return { agentId: ctx.agentId, sessionId: ctx.sessionId };
  }

  const sessionKey = event.sessionKey ?? ctx.sessionKey ?? "";
  const parts = sessionKey.split(":");
  if (parts[0] !== "agent" || !parts[1]) return null;
  const agentId = parts[1];

  try {
    const indexPath = resolveSessionsIndexPath(agentId);
    const raw = fs.readFileSync(indexPath, "utf-8");
    const index = JSON.parse(raw);
    const sessionId = index?.[sessionKey]?.sessionId;
    if (sessionId) return { agentId, sessionId };
  } catch {
    // sessions.json missing or malformed — nothing we can do
  }
  return null;
}

async function readSessionEntries(filePath) {
  try {
    const raw = await fsPromises.readFile(filePath, "utf-8");
    return raw
      .trim()
      .split("\n")
      .filter(Boolean)
      .flatMap((line) => {
        try {
          return [JSON.parse(line)];
        } catch {
          return [];
        }
      });
  } catch {
    return [];
  }
}

// ── Conversation turn extraction ─────────────────────────────────────────────

function extractTextFromContent(content) {
  if (!content) return "";
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content
      .filter((b) => b?.type === "text")
      .map((b) => b.text || "")
      .join("");
  }
  return "";
}

function addUsage(acc, usage) {
  if (!usage) return acc;
  return {
    input: (acc.input ?? 0) + (usage.input ?? 0),
    output: (acc.output ?? 0) + (usage.output ?? 0),
    cacheRead: (acc.cacheRead ?? 0) + (usage.cacheRead ?? 0),
    cacheWrite: (acc.cacheWrite ?? 0) + (usage.cacheWrite ?? 0),
    totalTokens: (acc.totalTokens ?? 0) + (usage.totalTokens ?? 0),
    cost: {
      input: (acc.cost?.input ?? 0) + (usage.cost?.input ?? 0),
      output: (acc.cost?.output ?? 0) + (usage.cost?.output ?? 0),
      cacheRead: (acc.cost?.cacheRead ?? 0) + (usage.cost?.cacheRead ?? 0),
      cacheWrite: (acc.cost?.cacheWrite ?? 0) + (usage.cost?.cacheWrite ?? 0),
      total: (acc.cost?.total ?? 0) + (usage.cost?.total ?? 0),
    },
  };
}

function extractTurns(entries) {
  const turns = [];
  let current = null;
  const pendingToolCalls = {};

  for (const entry of entries) {
    if (entry.type !== "message" || !entry.message) continue;
    const { role, content } = entry.message;

    if (role === "user") {
      if (current) turns.push(finalizeTurn(current));
      current = {
        index: turns.length,
        timestamp: entry.timestamp ?? null,
        userMessage: extractTextFromContent(content),
        thinking: [],
        toolCalls: [],
        response: "",
        model: null,
        stopReason: null,
        usage: {},
      };
    } else if (role === "assistant" && current) {
      current.usage = addUsage(current.usage, entry.message.usage);
      if (entry.message.model) current.model = entry.message.model;
      if (entry.message.stopReason)
        current.stopReason = entry.message.stopReason;

      const blocks = Array.isArray(content) ? content : [];
      for (const block of blocks) {
        if (!block?.type) continue;
        switch (block.type) {
          case "thinking":
            if (block.thinking) current.thinking.push(block.thinking);
            break;
          case "toolCall":
          case "tool_use": {
            const tc = {
              id: block.id ?? null,
              name: block.name ?? block.toolName ?? "unknown",
              input: block.arguments ?? block.input ?? block.parameters ?? {},
              result: null,
              isError: null,
            };
            current.toolCalls.push(tc);
            if (tc.id) pendingToolCalls[tc.id] = tc;
            break;
          }
          case "text":
            current.response += block.text ?? "";
            break;
        }
      }
    } else if (role === "toolResult" && current) {
      const id = entry.message.toolCallId ?? entry.message.toolUseId ?? null;
      const tc = id ? pendingToolCalls[id] : null;
      if (tc) {
        tc.result = extractTextFromContent(content);
        tc.isError = entry.message.isError ?? false;
        delete pendingToolCalls[id];
      }
    }
  }

  if (current) turns.push(finalizeTurn(current));
  return turns;
}

function finalizeTurn(turn) {
  return {
    ...turn,
    thinking: turn.thinking.join("\n\n"),
    usage: Object.keys(turn.usage).length ? turn.usage : null,
  };
}

// ── Session metadata ──────────────────────────────────────────────────────────

/**
 * Build session metadata for the payload. Prefers the caller-supplied
 * ``resolved`` (which has the sessionKey fallback for channel-dispatched
 * turns) over ``event.context``; the hook otherwise loses agent attribution
 * on every turn the agent didn't dispatch from its own CLI session.
 */
export function resolveSessionMeta(event, entries, resolved) {
  const ctx = event.context ?? {};
  const agentId = resolved?.agentId ?? ctx.agentId ?? null;
  const sessionId = resolved?.sessionId ?? ctx.sessionId ?? null;
  const sessionKey = event.sessionKey ?? ctx.sessionKey ?? null;

  const channelFromKey =
    sessionKey && agentId
      ? sessionKey.replace(`agent:${agentId}:`, "").split(":")[0]
      : null;

  const sessionEntry = entries.find((e) => e.type === "session");
  const cwd = sessionEntry?.cwd ?? null;

  return { agentId, sessionId, sessionKey, channel: channelFromKey, cwd };
}

// ── Payload ───────────────────────────────────────────────────────────────────

/**
 * Truncate a tool-call input/result to maxBytes UTF-8, replacing the tail
 * with a count marker. Objects are JSON-serialized before measurement.
 * maxBytes <= 0 disables truncation.
 *
 * The extractor on CFN's side pulls concepts and relationships, not
 * verbatim text, so losing the tail of a 200KB Read output costs nothing
 * on extraction quality and a lot on LLM input spend.
 */
function truncateToolContent(value, maxBytes) {
  if (maxBytes <= 0 || value == null) return value;
  if (typeof value === "string") {
    const bytes = Buffer.byteLength(value, "utf-8");
    if (bytes <= maxBytes) return value;
    return `${value.slice(0, maxBytes)}...[truncated ${bytes - maxBytes} bytes]`;
  }
  if (typeof value === "object") {
    const serialized = JSON.stringify(value);
    const bytes = Buffer.byteLength(serialized, "utf-8");
    if (bytes <= maxBytes) return value;
    return `${serialized.slice(0, maxBytes)}...[truncated ${bytes - maxBytes} bytes of JSON]`;
  }
  return value;
}

function buildPayload(sessionMeta, turns, entries, maxToolContentBytes) {
  const totalCost = turns.reduce(
    (sum, t) => sum + (t.usage?.cost?.total ?? 0),
    0,
  );

  let truncatedBytes = 0;
  const measureAndTruncate = (value) => {
    if (maxToolContentBytes <= 0) return value;
    const before = Buffer.byteLength(
      typeof value === "string" ? value : JSON.stringify(value ?? ""),
      "utf-8",
    );
    const truncated = truncateToolContent(value, maxToolContentBytes);
    const after = Buffer.byteLength(
      typeof truncated === "string" ? truncated : JSON.stringify(truncated ?? ""),
      "utf-8",
    );
    if (after < before) truncatedBytes += before - after;
    return truncated;
  };

  const payload = {
    schema: "openclaw-conversation-v1",
    extractedAt: new Date().toISOString(),
    session: sessionMeta,
    stats: {
      totalEntries: entries.length,
      turns: turns.length,
      toolCallCount: turns.reduce((n, t) => n + t.toolCalls.length, 0),
      thinkingTurnCount: turns.filter((t) => t.thinking.length > 0).length,
      totalCost,
    },
    turns: turns.map((t) => ({
      index: t.index,
      timestamp: t.timestamp,
      model: t.model,
      stopReason: t.stopReason,
      usage: t.usage,
      userMessage: t.userMessage,
      thinking: t.thinking || null,
      toolCalls: t.toolCalls.map((tc) => ({
        id: tc.id,
        name: tc.name,
        input: measureAndTruncate(tc.input),
        result: measureAndTruncate(tc.result),
        isError: tc.isError,
      })),
      response: t.response || null,
    })),
  };

  if (truncatedBytes > 0) {
    payload.stats.truncatedBytes = truncatedBytes;
  }
  return payload;
}

// ── Mycelium knowledge ingest ─────────────────────────────────────────────────

/**
 * Build the POST body for /api/knowledge/ingest. Pure function so the
 * agent_id precedence (resolved > env > null) is trivially testable.
 *
 * ``resolvedAgentId`` comes from ``resolveAgentSession`` in the handler,
 * which parses the agent handle out of the sessionKey for channel-dispatched
 * turns where ``event.context.agentId`` is absent. Without this fallback,
 * every ingest from a mycelium-room turn lands under agent ``(none)`` in
 * ``mycelium cfn stats`` (issue #144).
 */
export function buildIngestBody(target, resolvedAgentId, payload) {
  return {
    workspace_id: target.workspaceId,
    mas_id: target.masId,
    agent_id: resolvedAgentId ?? target.agentId ?? null,
    records: [payload],
  };
}

async function ingestToMycelium(payload, resolvedAgentId) {
  const target = getIngestTarget();
  if (!target.apiUrl || !target.workspaceId || !target.masId) return false;

  return postKnowledgeIngest(
    target.apiUrl,
    buildIngestBody(target, resolvedAgentId, payload),
  );
}

function deltaStatePath(agentId, sessionId) {
  return path.join(DELTA_STATE_DIR, `${agentId}-${sessionId}.json`);
}

function readLastSentIndex(agentId, sessionId) {
  try {
    const raw = fs.readFileSync(deltaStatePath(agentId, sessionId), "utf-8");
    return JSON.parse(raw)?.lastSentIndex ?? -1;
  } catch {
    return -1;
  }
}

function writeLastSentIndex(agentId, sessionId, index) {
  try {
    fs.mkdirSync(DELTA_STATE_DIR, { recursive: true });
    fs.writeFileSync(
      deltaStatePath(agentId, sessionId),
      JSON.stringify({ lastSentIndex: index }),
    );
  } catch {
    // Non-fatal — worst case we re-send on next fire
  }
}

// ── Local log fallback ────────────────────────────────────────────────────────

function appendLog(filePath, data) {
  fs.appendFileSync(filePath, JSON.stringify(data) + "\n");
}

// ── Handler ───────────────────────────────────────────────────────────────────

// Module-level set, shared across all handler invocations in the gateway
// process. Keyed on `${agentId}:${sessionId}`. A fire that finds its key
// already present returns immediately — backend dedupe (via content hash)
// covers any re-sends that slip through a restart.
const pendingSessions = new Set();

export default async function HookHandler(event) {
  const cfg = getIngestConfig();

  // Master kill switch — zero I/O when disabled.
  if (!cfg.enabled) return;

  // Event allowlist — config-driven so users can drop agent:bootstrap
  // without a code change if they still see restart amplification.
  const eventKey = `${event.type}:${event.action}`;
  if (!cfg.events.includes(eventKey)) return;

  const resolved = resolveAgentSession(event);
  if (!resolved) return;
  const { agentId, sessionId } = resolved;

  const sessionKey = `${agentId}:${sessionId}`;
  if (pendingSessions.has(sessionKey)) return;

  const sessionFile = resolveSessionFile(agentId, sessionId);
  const entries = await readSessionEntries(sessionFile);
  if (entries.length === 0) return;

  const allTurns = extractTurns(entries);
  if (allTurns.length === 0) return;

  // skip_in_progress_turn only applies to catch-up fires (agent:bootstrap)
  // where the agent may genuinely be mid-turn. For message:sent the last
  // turn is the one that just finalized — slicing it off would silently
  // drop the only thing we came here to extract.
  const shouldSkipInProgress =
    cfg.skipInProgressTurn && eventKey === "agent:bootstrap";
  const eligible = shouldSkipInProgress ? allTurns.slice(0, -1) : allTurns;

  const lastSentIndex = readLastSentIndex(agentId, sessionId);
  const newTurns = eligible.filter((t) => t.index > lastSentIndex);
  if (newTurns.length === 0) return;

  const meta = resolveSessionMeta(event, entries, { agentId, sessionId });
  const payload = buildPayload(meta, newTurns, entries, cfg.maxToolContentBytes);

  const nextLastIndex = newTurns[newTurns.length - 1].index;

  // Optimistic write: advance the baseline BEFORE the POST so concurrent
  // fires compute their diff against the correct state. Trade-off is
  // at-least-once semantics on POST failure — the backend dedupe cache
  // absorbs any duplicates, and a failed POST drops those turns from the
  // CFN graph but preserves audit_events (the durable record).
  writeLastSentIndex(agentId, sessionId, nextLastIndex);
  pendingSessions.add(sessionKey);

  ingestToMycelium(payload, agentId)
    .then((ok) => {
      if (!ok) appendLog(LOG_FILE, payload);
    })
    .catch((err) => {
      appendLog(LOG_FILE, {
        error: err?.message ?? String(err),
        payload,
      });
    })
    .finally(() => {
      pendingSessions.delete(sessionKey);
    });
}
