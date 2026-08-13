// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// All fetches use relative `/api/*` paths. The Next.js server proxies them
// to the backend (see next.config.ts `rewrites()`), so the browser only ever
// talks to its own origin: no CORS, no second public port, no build-time
// URL baking. The internal backend URL is a server-side concern.

/**
 * Attach to a fetch `.catch` to surface network failures in the browser
 * console. Replaces the previous `.catch(() => {})` pattern that swallowed
 * every error and made cloud-install debugging impossible.
 */
export const logFetchError =
  (label: string) =>
  (err: unknown): undefined => {
    // eslint-disable-next-line no-console
    console.error(`[mycelium] fetch failed: ${label}`, err);
    return undefined;
  };

export async function fetchRooms() {
  const res = await fetch(`/api/rooms`, { cache: "no-store" });
  return res.json();
}

export async function fetchRoom(name: string) {
  const res = await fetch(`/api/rooms/${name}`, { cache: "no-store" });
  return res.json();
}

export async function createRoom(data: { name: string; is_persistent?: boolean }) {
  const res = await fetch(`/api/rooms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...data, is_public: true }),
  });
  if (!res.ok) {
    // Surface the backend's reason (FastAPI returns `{ detail: ... }`) so the
    // caller can show it instead of failing silently.
    let detail = `Failed to create room (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
      }
    } catch {
      /* non-JSON error body: keep the status-based message */
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function fetchMemories(roomName: string, prefix?: string) {
  const params = new URLSearchParams({ limit: "50" });
  if (prefix) params.set("prefix", prefix);
  const res = await fetch(`/api/rooms/${roomName}/memory?${params}`, { cache: "no-store" });
  return res.json();
}

export async function searchMemories(roomName: string, query: string) {
  const res = await fetch(`/api/rooms/${roomName}/memory/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit: 10 }),
  });
  return res.json();
}

// ── Plan ─────────────────────────────────────────────────────────────────────

export interface PlanTask {
  id: string;
  slug: string;
  line: number;
  text: string;
  done: boolean;
}

export interface PlanFile {
  slug: string;
  title: string;
  content: string;
  updated_at: string | null;
  updated_by: string | null;
  tasks: PlanTask[];
}

export interface PlanResponse {
  room: string;
  title: string | null;
  files: PlanFile[];
  tasks: PlanTask[];
  open_count: number;
  done_count: number;
}

export async function fetchPlan(roomName: string): Promise<PlanResponse> {
  const res = await fetch(`/api/rooms/${roomName}/plan`, { cache: "no-store" });
  if (!res.ok) {
    return { room: roomName, title: null, files: [], tasks: [], open_count: 0, done_count: 0 };
  }
  return res.json();
}

export async function setPlanTitle(roomName: string, text: string): Promise<string | null> {
  const res = await fetch(`/api/rooms/${roomName}/plan/title`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text }),
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.title ?? null;
}

export async function togglePlanTask(roomName: string, taskId: string, done: boolean): Promise<PlanTask> {
  const res = await fetch(
    `/api/rooms/${roomName}/plan/tasks/${encodeURIComponent(taskId)}/toggle`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ done }),
    },
  );
  return res.json();
}

export async function addPlanTask(roomName: string, text: string, slug = "tasks"): Promise<PlanTask> {
  const res = await fetch(`/api/rooms/${roomName}/plan/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, slug }),
  });
  return res.json();
}

export async function fetchMessages(roomName: string, limit?: number) {
  const url = limit
    ? `/api/rooms/${roomName}/messages?limit=${limit}`
    : `/api/rooms/${roomName}/messages`;
  const res = await fetch(url, { cache: "no-store" });
  return res.json();
}


export function getSSEUrl(roomName: string) {
  return `/api/rooms/${roomName}/messages/stream`;
}

/** SSE endpoint for global app events (room create/delete). */
export function getAppEventsSSEUrl() {
  return `/api/events/stream`;
}

export async function sendRoomMessage(
  roomName: string,
  data: { sender_handle: string; content: string; message_type?: string },
) {
  const res = await fetch(`/api/rooms/${roomName}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message_type: "broadcast", ...data }),
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`send failed (${res.status}): ${detail.slice(0, 200)}`);
  }
  return res.json();
}

/**
 * A consent-gated invite. Raised when a human `@`-mentions an agent
 * that is not yet on the room's channel: the backend surfaces an accept/decline
 * prompt ("someone's agent wants to reach yours") instead of joining directly.
 */
export interface PendingInvite {
  id: string;
  room: string;
  agent: string;
  requested_by: string;
  trigger_text: string;
  status: string;
  created_at: string;
}

/** Open (pending or queued) consent requests for a room. */
export async function fetchPendingInvites(roomName: string): Promise<PendingInvite[]> {
  const res = await fetch(`/api/rooms/${roomName}/invites`, { cache: "no-store" });
  if (!res.ok) return [];
  const data = await res.json();
  return (data.invites || []) as PendingInvite[];
}

/** Accept or decline a consent prompt. Only `accept` invites (or queues) the agent. */
export async function respondToInvite(
  roomName: string,
  inviteId: string,
  decision: "accept" | "decline",
): Promise<PendingInvite | null> {
  const res = await fetch(`/api/rooms/${roomName}/invites/${inviteId}/${decision}`, {
    method: "POST",
  });
  if (!res.ok) return null;
  return res.json();
}

export interface AgentSummary {
  handle: string;
  description: string;
  adapter: string;
}

/**
 * List addressable agents in a room. Each agent is a memory entry under
 * `agents/<handle>` (without further path segments; `agents/<handle>/notes`
 * and `agents/<handle>/log/...` are filtered out). Used to drive the
 * `@`-mention autocomplete in the room chat box.
 */
export async function fetchRoomAgents(roomName: string): Promise<AgentSummary[]> {
  const res = await fetch(
    `/api/rooms/${roomName}/memory?prefix=agents/&limit=200`,
    { cache: "no-store" },
  );
  if (!res.ok) return [];
  const data = await res.json();
  const items = Array.isArray(data) ? data : data.items || data.memories || [];
  const agents: AgentSummary[] = [];
  for (const item of items) {
    const key: string = item.key || "";
    const rest = key.replace(/^agents\//, "");
    if (!rest || rest.includes("/")) continue;
    // The manifest is YAML. The memory API may hand it back as a raw string,
    // a structured dict, OR (what the backend actually does) wrapped as
    // `{text: "<yaml>"}`. Normalize to one YAML string and parse that.
    const value = item.value;
    let raw = "";
    let structured: Record<string, unknown> | null = null;
    if (typeof value === "string") {
      raw = value;
    } else if (value && typeof value === "object") {
      const v = value as Record<string, unknown>;
      if (typeof v.text === "string") raw = v.text;
      else if (typeof v.content === "string") raw = v.content;
      else structured = v;
    }

    let description = "";
    let adapter = "claude_code";
    if (structured) {
      description = String(structured.description || "");
      adapter = String(structured.adapter || "claude_code");
    } else {
      const descMatch = raw.match(/description:\s*(.+)/);
      if (descMatch) description = descMatch[1].trim().replace(/^["']|["']$/g, "");
      const adMatch = raw.match(/adapter:\s*(\S+)/);
      if (adMatch) adapter = adMatch[1].trim();
    }
    agents.push({ handle: rest, description, adapter });
  }
  agents.sort((a, b) => a.handle.localeCompare(b.handle));
  return agents;
}

// ── Metrics ──────────────────────────────────────────────────────────────────

export async function fetchBackendMetrics() {
  const res = await fetch(`/api/observability`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchCollectorMetrics() {
  const res = await fetch(`/api/observability/collector`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

// ── Traces & Logs ────────────────────────────────────────────────────────────

export interface HostInfo {
  host: string;
  span_count: number;
  trace_count: number;
  last_seen: string;
  agents: string[];
  error_count: number;
}

export async function fetchHosts(): Promise<{ hosts: HostInfo[] } | null> {
  const res = await fetch(`/api/observability/hosts`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

// ── L9 protocol / episodes ─────────────────────────────────────────────────────
// Episodes are the persisted, causally-linked L9 record of a coordination
// session (one markdown file per session under `log/episodes/`). The protocol
// inspector reads them for the rich causal chain + consensus metrics; the wire
// envelopes deliberately carry empty `message.parents`, so the chain lives here.

export interface L9Actor {
  id: string;
  role: string;
}

export interface L9Envelope {
  header: {
    protocol?: string;
    subprotocol?: string;
    version?: string;
    kind: string;
    subkind?: string | null;
    participants?: { actors?: L9Actor[]; groups?: Record<string, unknown> | null };
    message?: { id: string; parents?: string[]; episode?: string };
    context?: { topic?: string } | null;
  };
  payload?: { type?: string; data?: Record<string, unknown> };
}

export interface EpisodeMetrics {
  mpc: number;
  gar: number;
  scr: number;
  provenance_weight: number;
  participants?: number;
}

export interface EpisodeSummary {
  short_id: string;
  episode: string;
  topic: string;
  outcome: string;
  subkind: string | null;
  participants: string[];
  metrics: EpisodeMetrics | null;
  assignments: Record<string, string> | null;
  plan_file: string | null;
  message_count: number;
  updated_at: string;
  updated_by: string;
}

export interface EpisodeDetail extends EpisodeSummary {
  messages: L9Envelope[];
}

/** Episode summaries for a room, newest first. */
export async function fetchEpisodes(roomName: string): Promise<EpisodeSummary[]> {
  const res = await fetch(`/api/rooms/${roomName}/episodes`, { cache: "no-store" });
  if (!res.ok) return [];
  const data = await res.json();
  return (data.episodes || []) as EpisodeSummary[];
}

/** One episode plus its full L9 envelope chain, or null if unknown. */
export async function fetchEpisode(
  roomName: string,
  shortId: string,
): Promise<EpisodeDetail | null> {
  const res = await fetch(
    `/api/rooms/${roomName}/episodes/${encodeURIComponent(shortId)}`,
    { cache: "no-store" },
  );
  if (!res.ok) return null;
  return res.json();
}
