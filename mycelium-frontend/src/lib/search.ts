// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** Command-style search: the content counterpart to the command palette.
 *
 *  ⌘K runs *actions*; this finds *things* — memories, episodes, messages, rooms
 *  and members — and takes you to the one you pick.
 *
 *  The query grammar (`#room`, `@handle`, `memory:`, `kind:`) is parsed on the
 *  backend, not here, and echoed back on every response. So the chips this UI
 *  draws are the scope the search actually ran under: there is one grammar, and
 *  a client copy can't drift from it.
 *
 *  Ranking is the backend's too, across all five types at once — which is why
 *  results render as one ordered list with a type on each row, rather than five
 *  per-type sections that would throw that ordering away. */

export type SearchResultType = "room" | "agent" | "episode" | "memory" | "message";

/** The server's reading of the query's scoping tokens. */
export interface SearchScope {
  text: string;
  rooms: string[];
  actors: string[];
  types: SearchResultType[];
  kinds: string[];
}

export interface SearchHit {
  type: SearchResultType;
  room: string;
  /** Type-specific identifier to navigate by: memory key, episode short id,
   *  message uuid, room name, agent handle. */
  id: string;
  title: string;
  subtitle: string;
  snippet: string;
  kind: string | null;
  timestamp: string;
  score: number;
}

export interface SearchResponse {
  query: string;
  scope: SearchScope;
  results: SearchHit[];
  /** Matches per type before the result list was trimmed. */
  counts: Partial<Record<SearchResultType, number>>;
}

/** What each type is called on a result row, in the app's own vocabulary
 *  (an agent is a "member" in the inspector, so it is one here too). */
export const TYPE_LABELS: Record<SearchResultType, string> = {
  room: "room",
  agent: "member",
  episode: "episode",
  memory: "memory",
  message: "message",
};

export const EMPTY_SCOPE: SearchScope = { text: "", rooms: [], actors: [], types: [], kinds: [] };

/** True when the scope carries something worth drawing a chip for. */
export function hasScope(scope: SearchScope): boolean {
  return (
    scope.rooms.length > 0 ||
    scope.actors.length > 0 ||
    scope.types.length > 0 ||
    scope.kinds.length > 0
  );
}

/** The chips shown above the results, in the order the tokens are documented. */
export function scopeChips(scope: SearchScope): string[] {
  return [
    ...scope.rooms.map(r => `#${r}`),
    ...scope.actors.map(a => `@${a}`),
    ...scope.types.map(t => `${t}:`),
    ...scope.kinds.map(k => `kind:${k}`),
  ];
}

// ── Jumping to a result ──────────────────────────────────────────────────────
//
// A hit becomes a room URL carrying one `focus` parameter, `<type>:<id>`. The
// room page reads it, reveals the surface the item lives on, and hands the id to
// the panel that owns the row — so a result opens the item, not just the room it
// is in. It is a URL rather than in-memory state so the jump is shareable and
// survives a reload.

export interface FocusTarget {
  type: SearchResultType;
  id: string;
}

export function focusParam(hit: SearchHit): string {
  return `${hit.type}:${hit.id}`;
}

/** Read a `focus` parameter back. Unknown types and empty ids are ignored, so a
 *  hand-edited URL degrades to opening the room rather than throwing. */
export function parseFocus(raw: string | null | undefined): FocusTarget | null {
  if (!raw) return null;
  const at = raw.indexOf(":");
  if (at <= 0) return null;
  const type = raw.slice(0, at);
  const id = raw.slice(at + 1);
  if (!id || !(type in TYPE_LABELS)) return null;
  return { type: type as SearchResultType, id };
}

/** Where picking `hit` navigates to. A room is its own target and needs no
 *  focus; everything else opens its room with the item selected. */
export function resultHref(hit: SearchHit): string {
  const room = `/room/${encodeURIComponent(hit.room)}`;
  if (hit.type === "room") return `/room/${encodeURIComponent(hit.id)}`;
  return `${room}?focus=${encodeURIComponent(focusParam(hit))}`;
}
