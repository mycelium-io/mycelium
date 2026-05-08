// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

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
