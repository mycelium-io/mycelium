// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export async function fetchRooms() {
  const res = await fetch(`${API}/api/rooms`, { cache: "no-store" });
  return res.json();
}

export async function fetchRoom(name: string) {
  const res = await fetch(`${API}/api/rooms/${name}`, { cache: "no-store" });
  return res.json();
}

export async function createRoom(data: { name: string; trigger_config?: object; is_persistent?: boolean }) {
  const res = await fetch(`${API}/api/rooms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...data, is_public: true }),
  });
  return res.json();
}

export async function fetchMemories(roomName: string, prefix?: string) {
  const params = new URLSearchParams({ limit: "50" });
  if (prefix) params.set("prefix", prefix);
  const res = await fetch(`${API}/api/rooms/${roomName}/memory?${params}`, { cache: "no-store" });
  return res.json();
}

export async function searchMemories(roomName: string, query: string) {
  const res = await fetch(`${API}/api/rooms/${roomName}/memory/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit: 10 }),
  });
  return res.json();
}

export async function fetchCatchup(roomName: string) {
  const res = await fetch(`${API}/api/rooms/${roomName}/catchup`, { cache: "no-store" });
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
  const res = await fetch(`${API}/api/rooms/${roomName}/plan`, { cache: "no-store" });
  if (!res.ok) {
    return { room: roomName, title: null, files: [], tasks: [], open_count: 0, done_count: 0 };
  }
  return res.json();
}

export async function setPlanTitle(roomName: string, text: string): Promise<string | null> {
  const res = await fetch(`${API}/api/rooms/${roomName}/plan/title`, {
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
    `${API}/api/rooms/${roomName}/plan/tasks/${encodeURIComponent(taskId)}/toggle`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ done }),
    },
  );
  return res.json();
}

export async function addPlanTask(roomName: string, text: string, slug = "tasks"): Promise<PlanTask> {
  const res = await fetch(`${API}/api/rooms/${roomName}/plan/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, slug }),
  });
  return res.json();
}

export async function reindexRoom(roomName: string) {
  const res = await fetch(`${API}/api/rooms/${roomName}/reindex`, { method: "POST" });
  return res.json();
}

export async function fetchMessages(roomName: string, limit?: number) {
  const url = limit
    ? `${API}/api/rooms/${roomName}/messages?limit=${limit}`
    : `${API}/api/rooms/${roomName}/messages`;
  const res = await fetch(url, { cache: "no-store" });
  return res.json();
}

export async function fetchSessions(roomName: string) {
  const res = await fetch(`${API}/api/rooms/${roomName}/sessions`, { cache: "no-store" });
  if (!res.ok) return { sessions: [], total: 0 };
  return res.json();
}

export async function fetchChildRooms(parentName: string) {
  // Sessions live in coordination_sessions. Return the per-session display
  // name + state so callers that previously walked rooms by name pattern
  // keep working with minimal changes.
  const res = await fetch(
    `${API}/api/coordination-sessions?parent_room=${encodeURIComponent(parentName)}&limit=200`,
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
  return `${API}/api/rooms/${roomName}/messages/stream`;
}

// ── Metrics ──────────────────────────────────────────────────────────────────

export async function fetchBackendMetrics() {
  const res = await fetch(`${API}/api/observability`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchCollectorMetrics() {
  const res = await fetch(`${API}/api/observability/collector`, { cache: "no-store" });
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
  const res = await fetch(`${API}/api/observability/traces/recent?${params}`, { cache: "no-store" });
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
  const res = await fetch(`${API}/api/observability/hosts`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchRoundTraces(limit?: number): Promise<{ traces: unknown[]; count: number } | null> {
  const params = limit != null ? `?limit=${limit}` : "";
  const res = await fetch(`${API}/api/internal/coordination/round-traces${params}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchIngestLog(limit = 50) {
  const res = await fetch(`${API}/api/knowledge/ingest/log?limit=${limit}`, { cache: "no-store" });
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
  const res = await fetch(`${API}/api/cfn/knowledge/list?${params}`, { cache: "no-store" });
  if (!res.ok) return null;
  return res.json();
}

export async function fetchCfnNeighbors(masId: string, conceptId: string): Promise<CfnNeighborsResponse | null> {
  const params = new URLSearchParams({ mas_id: masId });
  const res = await fetch(
    `${API}/api/cfn/knowledge/concepts/${encodeURIComponent(conceptId)}/neighbors?${params}`,
    { cache: "no-store" },
  );
  if (!res.ok) return null;
  return res.json();
}
