// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Room plan briefing for `@handle` dispatch.
 *
 * Fetches `GET /api/rooms/{room}/agent-context` and renders it into a block
 * prepended to the agent's prompt, so an `@`-mentioned agent sees the room's
 * title + open tasks the same way a coordination-session agent sees them via
 * the tick payload.
 *
 * The endpoint is read on every dispatch, so results are cached per-room for
 * a short TTL. The staleness line baked into the rendered block keeps a cache
 * hit honest — the agent always knows how old the snapshot is.
 */

const TTL_MS = 60_000;

interface CacheEntry {
  fetchedMs: number;
  context: string | null;
  generatedAt: string;
}

const _cache = new Map<string, CacheEntry>();

/** Fetch (cached) the room's agent-context. Never throws — best-effort. */
export async function fetchAgentContext(
  backendUrl: string,
  room: string,
  handle: string,
): Promise<CacheEntry> {
  const now = Date.now();
  const cached = _cache.get(room);
  if (cached && now - cached.fetchedMs < TTL_MS) return cached;

  try {
    const url =
      `${backendUrl}/api/rooms/${encodeURIComponent(room)}/agent-context` +
      `?handle=${encodeURIComponent(handle)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`status ${res.status}`);
    const data = (await res.json()) as {
      context?: string | null;
      generated_at?: string;
    };
    const entry: CacheEntry = {
      fetchedMs: now,
      context: data.context ?? null,
      generatedAt: data.generated_at ?? "",
    };
    _cache.set(room, entry);
    return entry;
  } catch {
    // Stale cache beats nothing; nothing beats a failed dispatch.
    if (cached) return cached;
    return { fetchedMs: now, context: null, generatedAt: "" };
  }
}

/** "(as of HH:MM UTC, ~N min ago)" from an ISO-8601 timestamp. */
export function humanizeAge(generatedAtIso: string): string {
  if (!generatedAtIso) return "";
  const ts = Date.parse(generatedAtIso);
  if (Number.isNaN(ts)) return "";
  const ageMin = Math.max(0, Math.floor((Date.now() - ts) / 60_000));
  const when = new Date(ts).toISOString().slice(11, 16) + " UTC";
  return ageMin < 1
    ? ` (as of ${when}, just now)`
    : ` (as of ${when}, ~${ageMin} min ago)`;
}

/** Render the plan block, or "" when the room has no plan. */
export function renderPlanBlock(
  context: string | null,
  generatedAtIso: string,
): string {
  if (!context) return "";
  return (
    `## Room plan${humanizeAge(generatedAtIso)}\n\n${context}\n\n` +
    "This snapshot may be stale — run `mycelium plan tasks` for live state.\n\n"
  );
}

/** Test-only: clear the per-room cache between vitest cases. */
export function _resetAgentContextCacheForTest(): void {
  _cache.clear();
}
