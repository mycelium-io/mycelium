// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// All fetches use relative `/api/*` paths. The Next.js server proxies them
// to the backend (see next.config.ts `rewrites()`), so the browser only ever
// talks to its own origin — no CORS, no second public port, no build-time
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
      /* non-JSON error body — keep the status-based message */
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

export async function reindexRoom(roomName: string) {
  const res = await fetch(`/api/rooms/${roomName}/reindex`, { method: "POST" });
  return res.json();
}

export async function fetchMessages(roomName: string, limit?: number) {
  const url = limit
    ? `/api/rooms/${roomName}/messages?limit=${limit}`
    : `/api/rooms/${roomName}/messages`;
  const res = await fetch(url, { cache: "no-store" });
  return res.json();
}

export async function fetchSessions(roomName: string) {
  const res = await fetch(`/api/rooms/${roomName}/sessions`, { cache: "no-store" });
  if (!res.ok) return { sessions: [], total: 0 };
  return res.json();
}

export async function fetchChildRooms(parentName: string) {
  // Sessions live in coordination_sessions. Return the per-session display
  // name + state so callers that previously walked rooms by name pattern
  // keep working with minimal changes.
  const res = await fetch(
    `/api/coordination-sessions?parent_room=${encodeURIComponent(parentName)}&limit=200`,
    { cache: "no-store" },
  );
  if (!res.ok) return [];
  const sessions = await res.json();
  return sessions.map((s: any) => ({
    name: s.display_name,
    coordination_session_id: s.id,
    coordination_state: s.state,
    parent_namespace: s.parent_room_name,
    created_at: s.created_at,
  }));
}

export function getSSEUrl(roomName: string) {
  return `/api/rooms/${roomName}/messages/stream`;
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

export interface AgentSummary {
  handle: string;
  description: string;
  adapter: string;
}

/**
 * List addressable agents in a room. Each agent is a memory entry under
 * `agents/<handle>` (without further path segments — `agents/<handle>/notes`
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
    // a structured dict, OR — what the backend actually does — wrapped as
    // `{text: "<yaml>"}`. Normalize to one YAML string and parse that; the
    // old code missed the {text} shape and defaulted every agent to
    // claude_code.
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

export interface TraceSpan {
  trace_id: string;
  span_id: string;
  parent_span_id: string;
  name: string;
  kind: string;
  service: string;
  host: string;
  start_time: string;
  duration_ms: number;
  status: string;
  status_message: string;
  attributes: Record<string, string | number | boolean>;
}

export interface TraceSummary {
  trace_id: string;
  root_span: string;
  service: string;
  agent: string;
  host: string;
  hosts: string[];
  start_time: string;
  duration_ms: number;
  span_count: number;
  has_error: boolean;
  spans: TraceSpan[];
}

export async function fetchRecentTraces(limit = 100, host?: string): Promise<{ traces: TraceSummary[]; count: number } | null> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (host) params.set("host", host);
  const res = await fetch(`/api/observability/traces/recent?${params}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

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

export async function fetchRoundTraces(limit?: number): Promise<{ traces: unknown[]; count: number } | null> {
  const params = limit != null ? `?limit=${limit}` : "";
  const res = await fetch(`/api/internal/coordination/round-traces${params}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchIngestLog(limit = 50) {
  const res = await fetch(`/api/knowledge/ingest/log?limit=${limit}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

// ── CFN knowledge graph ──────────────────────────────────────────────────────
// Backs the `mycelium cfn` CLI; see fastapi-backend/app/routes/cfn_proxy.py.

export interface CfnConcept {
  label?: string | null;
  vid?: string | null;
  id: string;
  name?: string | null;
  properties?: Record<string, unknown>;
}

export interface CfnConceptListResponse {
  mas_id: string;
  limit: number;
  count: number;
  nodes: CfnConcept[];
}

export interface CfnNeighborsResponse {
  concept_id?: string;
  neighbors?: Array<Record<string, unknown>>;
  [key: string]: unknown;
}

export async function fetchCfnConcepts(masId: string, limit = 50): Promise<CfnConceptListResponse | null> {
  const params = new URLSearchParams({ mas_id: masId, limit: String(limit) });
  const res = await fetch(`/api/cfn/knowledge/list?${params}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchCfnNeighbors(masId: string, conceptId: string): Promise<CfnNeighborsResponse | null> {
  const params = new URLSearchParams({ mas_id: masId });
  const res = await fetch(
    `/api/cfn/knowledge/concepts/${encodeURIComponent(conceptId)}/neighbors?${params}`,
    { cache: "no-store" },
  );
  if (!res.ok) return null;
  return res.json();
}
