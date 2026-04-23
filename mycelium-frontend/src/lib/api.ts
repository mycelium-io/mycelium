// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

export async function fetchRooms() {
  const res = await fetch(`${API}/rooms`, { cache: "no-store" });
  return res.json();
}

export async function fetchRoom(name: string) {
  const res = await fetch(`${API}/rooms/${name}`, { cache: "no-store" });
  return res.json();
}

export async function createRoom(data: { name: string; trigger_config?: object; is_persistent?: boolean }) {
  const res = await fetch(`${API}/rooms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...data, is_public: true }),
  });
  return res.json();
}

export async function fetchMemories(roomName: string, prefix?: string) {
  const params = new URLSearchParams({ limit: "50" });
  if (prefix) params.set("prefix", prefix);
  const res = await fetch(`${API}/rooms/${roomName}/memory?${params}`, { cache: "no-store" });
  return res.json();
}

export async function searchMemories(roomName: string, query: string) {
  const res = await fetch(`${API}/rooms/${roomName}/memory/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit: 10 }),
  });
  return res.json();
}

export async function fetchCatchup(roomName: string) {
  const res = await fetch(`${API}/rooms/${roomName}/catchup`, { cache: "no-store" });
  return res.json();
}

export async function reindexRoom(roomName: string) {
  const res = await fetch(`${API}/rooms/${roomName}/reindex`, { method: "POST" });
  return res.json();
}

export async function fetchMessages(roomName: string) {
  const res = await fetch(`${API}/rooms/${roomName}/messages`, { cache: "no-store" });
  return res.json();
}

export async function fetchSessions(roomName: string) {
  const res = await fetch(`${API}/rooms/${roomName}/sessions`, { cache: "no-store" });
  if (!res.ok) return { sessions: [], total: 0 };
  return res.json();
}

export async function fetchChildRooms(parentName: string) {
  const res = await fetch(`${API}/rooms?name=${encodeURIComponent(parentName + ":session:")}`, { cache: "no-store" });
  if (!res.ok) return [];
  const rooms = await res.json();
  return rooms.filter((r: any) => r.parent_namespace === parentName);
}

export function getSSEUrl(roomName: string) {
  return `${API}/rooms/${roomName}/messages/stream`;
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
