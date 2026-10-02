// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Patterns: multi-agent design patterns as scenarios the hub loads into a room
// (`/api/patterns`). The explorer lists them, runs one, and watches the room it
// made. A scenario also says how a run reads to someone watching it: where it
// starts (`before`), what its result is about (`after`), and a short guide; the
// hub restates where a run stands after every step as `context/standing`.

import useSWR from "swr";
import { ApiError, type EpisodeFlow, type Memory, type Room } from "@/lib/api";

export interface PatternMember {
  handle: string;
  kind: string;
  description: string;
}

export interface PatternSummary {
  pattern: string;
  title: string;
  summary: string;
  flow: string | null;
  roles: string[];
  members: PatternMember[];
}

export type GuideAt = "before" | "after" | "members" | "flow" | "chat" | "turn";

export interface GuideStep {
  at: GuideAt;
  title: string;
  text: string;
}

export interface Scenario {
  pattern: string;
  title: string;
  summary: string;
  room: { title: string; description?: string };
  members: (PatternMember & { notes?: string })[];
  task: { title: string; body?: string };
  summon?: { flow: string; members: string[]; ask: string };
  before?: { headline: string; detail?: string };
  after?: { track: string };
  guide?: GuideStep[];
}

export interface PatternRead extends PatternSummary {
  scenario: Scenario;
  flow_body: string | null;
  /** The flow as steps, built in or the pattern's own, drawable before it runs. */
  flow_spec: EpisodeFlow | null;
}

export interface PatternLoaded {
  room: string;
  title: string;
  members: string[];
  key: string | null;
  episode: string | null;
  ran: boolean;
}

/** Where a run stands, as the hub last restated it. */
export interface Standing {
  headline: string;
  detail: string;
  /** `running`, or the outcome the run closed on. */
  state: string;
}

/** The memory the hub restates a run's standing into. */
export const STANDING_KEY = "context/standing";

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { cache: "no-store", ...init });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // The status line says enough.
    }
    throw new ApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export async function fetchPatterns(): Promise<PatternSummary[]> {
  return (await getJson<{ patterns: PatternSummary[] }>("/api/patterns")).patterns;
}

export async function fetchPattern(name: string): Promise<PatternRead> {
  return getJson<PatternRead>(`/api/patterns/${encodeURIComponent(name)}`);
}

/** Load a pattern as a new room, and with `run` start its flow. */
export async function loadPattern(
  name: string,
  data: { run: boolean; created_by: string },
): Promise<PatternLoaded> {
  return getJson<PatternLoaded>(`/api/patterns/${encodeURIComponent(name)}/load`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function usePatterns() {
  const { data, error, isLoading } = useSWR(["patterns"], fetchPatterns, { refreshInterval: 60_000 });
  return { patterns: data ?? [], error: error as Error | undefined, loading: isLoading };
}

export function usePattern(name: string | null) {
  const { data, error, isLoading } = useSWR(name ? ["pattern", name] : null, () => fetchPattern(name ?? ""));
  return { pattern: data ?? null, error: error as Error | undefined, loading: isLoading };
}

/** The room a pattern last ran in: the newest one loaded from it. */
export function latestRoomOf(rooms: Room[], pattern: string): Room | null {
  const mine = rooms.filter((r) => r.pattern === pattern);
  mine.sort((a, b) => (b.created_at ?? "").localeCompare(a.created_at ?? ""));
  return mine[0] ?? null;
}

/** The standing a memory carries, or null for one that carries none. */
export function standingOf(memory: Memory | null | undefined): Standing | null {
  const meta = memory?.meta ?? null;
  const headline = typeof meta?.headline === "string" ? meta.headline : "";
  if (!headline) return null;
  return {
    headline,
    detail: typeof meta?.detail === "string" ? meta.detail : "",
    state: typeof meta?.state === "string" ? meta.state : "running",
  };
}

/** The stance marker a person's approve or block carries, read by the conductor. */
export function withStance(text: string, stance: "accept" | "reject"): string {
  const said = text.trim() || (stance === "accept" ? "Approved." : "Blocked.");
  return `${said}\n\n[[mycelium: stance=${stance}]]`;
}
