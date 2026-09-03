// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// All fetches use relative `/api/*` paths. The Next.js server proxies them
// to the backend (see next.config.ts `rewrites()`), so the browser only ever
// talks to its own origin: no CORS, no second public port, no build-time
// URL baking. The internal backend URL is a server-side concern.

import type { SearchResponse } from "@/lib/search";
import { encodeMemoryKeyPath } from "@/lib/memory-routes";
import type { RoomStatus } from "@/lib/board/upstream";

/**
 * Attach to a fetch `.catch` to surface network failures in the browser console.
 */
export const logFetchError =
  (label: string) =>
  (err: unknown): undefined => {
    console.error(`[mycelium] fetch failed: ${label}`, err);
    return undefined;
  };

/** Thrown by `apiFetch` (no `fallback`) on a non-2xx response or a payload
 *  that fails its shape guard. `message` is the backend's FastAPI `detail`
 *  when present, else a status-line fallback. */
export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Best-effort human-readable message from a FastAPI error body. */
async function errorDetail(res: Response): Promise<string> {
  try {
    const data = await res.json();
    const d = data?.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d) && d[0]?.msg) return String(d[0].msg);
  } catch {
    // fall through to the status line
  }
  return `Request failed (${res.status})`;
}

interface ApiFetchOptions<T> extends RequestInit {
  /** Returned instead of throwing when the request fails (network error,
   *  non-2xx, or a shape-guard rejection). Omit to let the caller handle the
   *  rejected promise — the right choice for user-initiated mutations, where
   *  the failure needs to reach the UI rather than disappear into a default. */
  fallback?: T;
  /** Narrows/validates the parsed JSON. A payload that fails the guard is
   *  treated the same as a failed request (falls back, or throws). */
  guard?: (data: unknown) => data is T;
}

/**
 * The one fetch path every function below routes through: checks `res.ok`,
 * parses the backend's `{ detail: ... }` error shape, and optionally
 * validates the success shape. Callers pick one of two contracts:
 *   - pass `fallback` for a fire-and-forget read (state setter callers) that
 *     should degrade to a safe default instead of throwing;
 *   - omit it for a mutation or a read whose caller needs to see the failure
 *     (throws `ApiError` with the backend's message).
 */
async function apiFetch<T = unknown>(path: string, opts: ApiFetchOptions<T> = {}): Promise<T> {
  const { fallback, guard, ...init } = opts;
  const hasFallback = "fallback" in opts;

  let res: Response;
  try {
    res = await fetch(path, init);
  } catch (err) {
    logFetchError(path)(err);
    if (hasFallback) return fallback as T;
    throw err;
  }

  if (!res.ok) {
    // A gated hub answering 401 means the session lapsed (or never existed).
    // Signal the auth provider to re-check rather than letting a `fallback`
    // caller degrade to a silently-empty view. See components/auth-session.tsx.
    if (res.status === 401 && typeof window !== "undefined") {
      window.dispatchEvent(new Event("mycelium:auth-required"));
    }
    const message = await errorDetail(res);
    if (hasFallback) {
      logFetchError(path)(new Error(message));
      return fallback as T;
    }
    throw new ApiError(message, res.status);
  }

  let data: unknown = null;
  try {
    data = await res.json();
  } catch (err) {
    if (hasFallback) {
      logFetchError(path)(err);
      return fallback as T;
    }
    throw new ApiError(`Invalid JSON response from ${path}`, res.status);
  }

  if (guard && !guard(data)) {
    const message = `Unexpected response shape from ${path}`;
    if (hasFallback) {
      logFetchError(path)(new Error(message));
      return fallback as T;
    }
    throw new ApiError(message, res.status);
  }

  return data as T;
}

const isArray = (d: unknown): d is unknown[] => Array.isArray(d);

// ── Rooms ────────────────────────────────────────────────────────────────────

export interface Room {
  id?: number;
  name: string;
  description?: string | null;
  is_public?: boolean;
  created_at: string;
  /** When the room was last active (transcript mtime); falls back to created_at. */
  last_activity?: string | null;
  is_persistent: boolean;
  mas_id?: string | null;
  workspace_id?: string | null;
  /** The room's display title — the italic hero above the board. */
  title?: string | null;
}

/** Rename a room. Throws `ApiError` so a caller can surface the reason rather
 *  than silently discarding the edit. */
export async function setRoomTitle(roomName: string, title: string): Promise<Room> {
  return apiFetch<Room>(`/api/rooms/${roomName}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

export async function fetchRooms(): Promise<Room[]> {
  return apiFetch<Room[]>(`/api/rooms`, { cache: "no-store", fallback: [], guard: isArray as (d: unknown) => d is Room[] });
}

export async function fetchRoom(name: string): Promise<Room> {
  return apiFetch<Room>(`/api/rooms/${name}`, { cache: "no-store" });
}

export async function createRoom(data: { name: string; is_persistent?: boolean }): Promise<Room> {
  return apiFetch<Room>(`/api/rooms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...data, is_public: true }),
  });
}

// ── Memory ───────────────────────────────────────────────────────────────────

export interface Memory {
  key: string;
  value: unknown;
  content_text?: string;
  version: number;
  created_by: string;
  updated_by?: string | null;
  updated_at: string;
  file_path?: string;
  tags?: string[];
  /** Mirrors the `expandable` frontmatter flag that opts a memory into `![[…]]`. */
  expandable?: boolean;
  /** Frontmatter the store doesn't own — whatever the writer put there. */
  meta?: Record<string, unknown> | null;
  /**
   * The episode URN this row's coordination happens in — what makes a task of
   * work a thread. Store-owned: minted by the backend, so it is absent from
   * `meta` and cannot be set by a write.
   */
  episode?: string | null;
}

/** Shape sent to POST /api/rooms/{room}/memory to create or upsert a memory. */
export interface MemoryCreate {
  key: string;
  /**
   * Prose, or an object for a memory that carries fields beyond its text
   * (a category entry's `logged_at`/`category`, or an arbitrary JSON value).
   */
  value: string | Record<string, unknown>;
  /** Text used for the embedding; derived from `value` when omitted. */
  content_text?: string;
  tags?: string[];
  embed?: boolean;
  created_by: string;
  base_version?: number;
  meta?: Record<string, unknown>;
}

/** Create or upsert one or more memories. Throws `ApiError` on failure. */
export async function createMemories(
  roomName: string,
  items: MemoryCreate[],
): Promise<void> {
  await apiFetch<unknown>(`/api/rooms/${roomName}/memory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
}

// ── Assignments ──────────────────────────────────────────────────────────────────

/** One row's assignment, as `/rooms/{room}/assignments/*` answers it. */
export interface AssignmentState {
  key: string;
  assignment: string;
  owner: string | null;
  claimed_at: string | null;
  ttl_minutes: number | null;
  freshness: string | null;
  version: number | null;
  assignment_note: string | null;
  assignment_note_by: string | null;
}

/**
 * Take, hand back, or close out assignment of a `work/` row.
 *
 * The write lands as frontmatter through the room's canonical memory upsert, so
 * a claim made from the browser is the same versioned, indexed change a claim
 * made from the CLI is — there is no second store for what the board knows.
 */
export async function writeAssignment(
  roomName: string,
  action: "claim" | "release" | "resolve",
  body: { key: string; handle: string; ttl_minutes?: number; note?: string },
): Promise<AssignmentState> {
  return apiFetch<AssignmentState>(`/api/rooms/${roomName}/assignments/${action}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export interface FieldState {
  key: string;
  fields: Record<string, unknown>;
  version: number | null;
}

/**
 * Put fields on a row — the write behind every board action that is not assignment.
 *
 * The same upsert a `memory set --meta` goes through, so a status changed by
 * dragging a card is the same versioned, indexed, broadcast change an agent
 * writing frontmatter makes. A board that moved a card in the browser and
 * nowhere else was a surface asserting something the room had never been told.
 */
export async function writeFields(
  roomName: string,
  body: { key: string; handle: string; fields: Record<string, unknown> },
): Promise<FieldState> {
  return apiFetch<FieldState>(`/api/rooms/${roomName}/fields`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** `fetchMemories`'s page size — exported so a caller showing a raw count
 *  (the dashboard's room cards) can tell "exactly this many" apart from
 *  "at least this many" instead of reporting the cap as a true total. */
export const MEMORIES_PAGE_LIMIT = 50;

export async function fetchMemories(roomName: string, prefix?: string): Promise<Memory[]> {
  const params = new URLSearchParams({ limit: String(MEMORIES_PAGE_LIMIT) });
  if (prefix) params.set("prefix", prefix);
  return apiFetch<Memory[]>(`/api/rooms/${roomName}/memory?${params}`, {
    cache: "no-store",
    fallback: [],
    guard: isArray as (d: unknown) => d is Memory[],
  });
}

/** One memory by key. Returns null when it isn't there (or the read failed), so
 *  a caller jumping to a since-deleted key lands on the room rather than an
 *  error. */
export async function fetchMemory(roomName: string, key: string): Promise<Memory | null> {
  const path = encodeMemoryKeyPath(key);
  return apiFetch<Memory | null>(`/api/rooms/${roomName}/memory/${path}`, {
    cache: "no-store",
    fallback: null,
  });
}

export interface MemorySearchResult {
  memory: Memory;
  similarity: number;
}

/** Semantic search, triggered by a user action — throws (rather than falling
 *  back to empty) so the search UI can distinguish "no results" from "the
 *  request failed" and show the latter instead of silently showing nothing. */
export async function searchMemories(roomName: string, query: string): Promise<MemorySearchResult[]> {
  const data = await apiFetch<{ results?: MemorySearchResult[] }>(`/api/rooms/${roomName}/memory/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, limit: 10 }),
  });
  return data.results ?? [];
}

// ── Cross-entity search ──────────────────────────────────────────────────────

/** One ranked query across memories, episodes, messages, rooms and members.
 *
 *  Throws (rather than falling back to empty) so the search surface can tell
 *  "nothing matched" from "the hub is unreachable" and say which. */
export async function searchEverything(query: string, limit = 20): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  return apiFetch<SearchResponse>(`/api/search?${params}`, { cache: "no-store" });
}

// ── Memory links ─────────────────────────────────────────────────────────────

/** One edge between two memories, plus what it resolves to right now. */
export interface MemoryLink {
  target: string;
  kind: "wikilink" | "uri" | "transclusion" | "relation";
  anchor?: string | null;
  label?: string | null;
  relation?: string | null;
  raw: string;
  /** Set on a backlink: the memory the edge came from. */
  source?: string | null;
  resolved: boolean;
  error?: string | null;
}

export interface MemoryLinks {
  key: string;
  outbound: MemoryLink[];
  backlinks: MemoryLink[];
}

const EMPTY_LINKS = { outbound: [], backlinks: [] };

/** A memory's links in both directions. Degrades to empty — a room with no
 *  link index yet is the normal unlinked case, not an error worth surfacing. */
export async function fetchMemoryLinks(roomName: string, key: string): Promise<MemoryLinks> {
  const params = new URLSearchParams({ key });
  const data = await apiFetch<Omit<MemoryLinks, "key">>(
    `/api/rooms/${roomName}/links?${params}`,
    { cache: "no-store", fallback: EMPTY_LINKS },
  );
  return { key, outbound: data.outbound ?? [], backlinks: data.backlinks ?? [] };
}

export interface MemoryExpanded {
  key: string;
  rendered: string;
  expansions: Array<{ raw: string; target: string; resolved: boolean; error?: string | null }>;
  found: boolean;
}

const EMPTY_EXPAND: MemoryExpanded = { key: "", rendered: "", expansions: [], found: false };

/** Body with `![[…]]` transclusions expanded (depth 1). Returns empty when missing. */
export async function fetchMemoryExpanded(roomName: string, key: string): Promise<MemoryExpanded> {
  const params = new URLSearchParams({ key });
  const data = await apiFetch<MemoryExpanded>(
    `/api/rooms/${roomName}/links/expand?${params}`,
    { cache: "no-store", fallback: { ...EMPTY_EXPAND, key } },
  );
  return { ...EMPTY_EXPAND, ...data, key };
}

// ── Memory graph ─────────────────────────────────────────────────────────────
// The whole room as a graph — one node per memory, one edge per link — for the
// full-page graph view (#599). A thin read over the same link index that backs
// `fetchMemoryLinks`, so graph-role facts (orphan = `inbound===0 &&
// outbound===0`, root = `inbound===0 && outbound>0`, leaf = `inbound>0 &&
// outbound===0`) and broken-link facts (`resolved === false`) are derived
// client-side from this one payload.

export interface MemoryGraphNode {
  key: string;
  expandable: boolean;
  outbound: number;
  inbound: number;
}

export interface MemoryGraphEdge {
  source: string;
  target: string;
  kind: MemoryLink["kind"];
  relation?: string | null;
  resolved: boolean;
  error?: string | null;
}

export interface MemoryGraph {
  nodes: MemoryGraphNode[];
  edges: MemoryGraphEdge[];
}

const EMPTY_GRAPH: MemoryGraph = { nodes: [], edges: [] };

/** The room's whole link graph. Degrades to empty — a room with no link index
 *  yet (or an unreachable hub) is the normal unlinked case, not a hard error. */
export async function fetchMemoryGraph(roomName: string): Promise<MemoryGraph> {
  const data = await apiFetch<Partial<MemoryGraph>>(`/api/rooms/${roomName}/links/graph`, {
    cache: "no-store",
    fallback: EMPTY_GRAPH,
  });
  return { nodes: data.nodes ?? [], edges: data.edges ?? [] };
}

// ── Skills ───────────────────────────────────────────────────────────────────
// A skill is a memory under the room's `skills/` namespace, promoted into its
// own surface (like `agents/` → the members panel). Room-scoped, like memory.
// Backs the chat composer's `/` trigger and the Skills rail. See #617.

export interface Skill {
  name: string;
  description: string;
  body: string;
  tags?: string[] | null;
  created_by: string;
  updated_by?: string | null;
  version: number;
  created_at: string;
  updated_at: string;
}

/** List a room's skills, for the composer's `/` autocomplete. Skills are just
 *  `skills/…` memories; in the GUI they surface as memories (with a tag), so this
 *  read is the only skill-specific frontend call. Degrades to empty on failure. */
export async function fetchSkills(roomName: string): Promise<Skill[]> {
  const data = await apiFetch<{ skills?: Skill[] }>(`/api/rooms/${roomName}/skills`, {
    cache: "no-store",
    fallback: { skills: [] },
  });
  return data.skills ?? [];
}

/** What the tools a room points at say about the work its rows mention.
 *  A read is answered from the hub's cache and never fetches, so polling this
 *  costs a cache lookup rather than a round trip to GitHub. */
export async function fetchRoomStatus(roomName: string): Promise<RoomStatus> {
  return apiFetch<RoomStatus>(`/api/rooms/${roomName}/status`, {
    cache: "no-store",
    fallback: {
      room: roomName,
      field: "upstream",
      providers: [],
      refs: [],
      rows: {},
      refreshing: false,
    },
  });
}

// ── Messages ─────────────────────────────────────────────────────────────────

export interface RoomMessage {
  id?: string;
  message_type?: string;
  type?: string;
  content?: unknown;
  sender_handle?: string;
  updated_by?: string;
  recipient_handle?: string | null;
  created_at?: string;
  key?: string;
  version?: number;
  episode?: string | null;
  [key: string]: unknown;
}

export interface MessagesResponse {
  messages: RoomMessage[];
  total?: number;
}

const isMessagesResponse = (d: unknown): d is MessagesResponse =>
  !!d && typeof d === "object" && Array.isArray((d as { messages?: unknown }).messages);

/** Narrow a read to one conversation. Without it the room answers with all of
 *  them — its own and every thread inside it. */
export interface MessageQuery {
  /** An episode URN: a task's thread, or the room's own `live` URN. */
  episode?: string | null;
  /**
   * The backward cursor: only messages created strictly before this stamp.
   * A page defined relative to content rather than position, so walking back
   * through a room does not shift under messages arriving live — which is
   * exactly what an offset does.
   */
  before?: string | null;
}

export async function fetchMessages(
  roomName: string,
  limit?: number,
  query: MessageQuery = {},
): Promise<MessagesResponse> {
  const params = new URLSearchParams();
  if (limit) params.set("limit", String(limit));
  if (query.episode) params.set("episode", query.episode);
  if (query.before) params.set("before", query.before);
  const qs = params.toString();
  return apiFetch<MessagesResponse>(
    `/api/rooms/${roomName}/messages${qs ? `?${qs}` : ""}`,
    {
      cache: "no-store",
      fallback: { messages: [] },
      guard: isMessagesResponse,
    },
  );
}

/** The room's L9 wire history (transcript replay), for backfilling the live
 *  inspector on mount. Frames match the SSE bus shape, so the client projects
 *  backfill + live identically. Returns [] on any error (best-effort). */
export async function fetchL9History(
  roomName: string,
  limit = 200,
  before?: string | null,
): Promise<Record<string, unknown>[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (before) params.set("before", before);
  return apiFetch<Record<string, unknown>[]>(
    `/api/rooms/${roomName}/messages/l9?${params.toString()}`,
    {
      cache: "no-store",
      fallback: [],
      guard: isArray as (d: unknown) => d is Record<string, unknown>[],
    },
  );
}

export async function sendRoomMessage(
  roomName: string,
  data: {
    sender_handle: string;
    content: string;
    message_type?: string;
    /** The thread this lands in. Omitted, it lands in the room itself. */
    episode?: string | null;
  },
): Promise<RoomMessage> {
  return apiFetch<RoomMessage>(`/api/rooms/${roomName}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message_type: "broadcast", ...data }),
  });
}

export interface AgentSummary {
  handle: string;
  adapter: string;
  kind: string | null;
  description: string;
  cwd: string | null;
  owner: string | null;
  team: string | null;
  allow_from: string[];
  /** For `adapter === "a2a"` agents: the agent card base URL, resolved endpoint,
   *  and advertised skills. Null/empty for every other adapter. */
  a2a_card?: string | null;
  a2a_endpoint?: string | null;
  a2a_skills?: string[];
}

/** List addressable agents in a room. Used to drive `@`-mention autocomplete. */
export async function fetchRoomAgents(roomName: string): Promise<AgentSummary[]> {
  return apiFetch<AgentSummary[]>(`/api/rooms/${roomName}/agents`, {
    cache: "no-store",
    fallback: [],
    guard: isArray as (d: unknown) => d is AgentSummary[],
  });
}

export type EngineKind = "aligner" | "synthesizer" | "hello" | "conductor" | "persona";

/** Invite a first-party cognition engine (aligner / synthesizer / hello) into a room.
 *  Engines are backend-owned — registration is just a manifest write with no
 *  machine-local side effects — so the UI can do this natively (no CLI). */
export async function createEngine(
  roomName: string,
  data: { handle: string; kind: EngineKind; description?: string; created_by?: string },
): Promise<AgentSummary> {
  return apiFetch<AgentSummary>(`/api/rooms/${roomName}/engines`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

/** Register an external A2A agent as a room member. The backend resolves the
 *  agent card at `card` (a base URL) to discover its endpoint + skills; a
 *  bad/unreachable card surfaces as a 502 whose detail we let propagate. */
export async function registerA2aAgent(
  roomName: string,
  data: { handle: string; card: string; description?: string },
): Promise<AgentSummary> {
  return apiFetch<AgentSummary>(`/api/rooms/${roomName}/a2a-agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

// ── A2A bridge (the Network pane's off-channel half) ─────────────────────────
//
// A bridged agent is reached over HTTP by the hub, not over the room's SLIM
// channel, so none of it shows up in the coordination telemetry above. This is
// the read that makes a bridged turn legible next to SLIM traffic.

/** A room member the hub reaches over A2A instead of the room's channel. */
export interface A2aBridgedAgent {
  handle: string;
  description: string;
  card: string | null;
  endpoint: string | null;
  skills: string[];
  calls_ok: number;
  calls_failed: number;
  last_call_at: string | null;
  /** Always true, and stated rather than implied: proxied by the hub, so it
   *  holds no group key and is not a member of the room's MLS group. */
  proxied: boolean;
}

/** One bridged turn: a call the hub made out, or a message that arrived in. */
export interface A2aExchange {
  id: string;
  handle: string;
  direction: "outbound" | "inbound";
  status: "ok" | "error";
  at: string;
  endpoint: string | null;
  /** Whose `@`-mention triggered the call (outbound only). */
  peer: string | null;
  prompt: string;
  reply: string;
  detail: string | null;
  duration_ms: number | null;
}

/** The inbound half: this room served as an A2A agent of its own. */
export interface A2aExposure {
  card_url: string;
  rpc_url: string;
  skills: string[];
  card_fetches: number;
  messages: number;
  last_card_fetch_at: string | null;
  last_message_at: string | null;
}

export interface A2aBridgeState {
  room: string;
  agents: A2aBridgedAgent[];
  exposure: A2aExposure;
  exchanges: A2aExchange[];
  outbound_ok: number;
  outbound_failed: number;
}

/** Read a room's A2A bridge state. Fail-soft: null when the hub is unreachable
 *  or too old to serve the route, which the pane renders as "no bridge". */
export async function fetchA2aBridge(roomName: string): Promise<A2aBridgeState | null> {
  return apiFetch<A2aBridgeState | null>(`/api/rooms/${roomName}/a2a/state`, {
    cache: "no-store",
    fallback: null,
  });
}

export type PresenceKind = "slim" | "lease" | "herdr";

export interface PresenceMember {
  handle: string;
  /** "slim" = active SLIM socket; "lease" = server-held await/reply (no socket);
   *  "herdr" = alive in a herdr-managed pane but not joined (pushed by the host
   *  `mycelium herdr sync` bridge). */
  kind: PresenceKind;
  /** ISO wall-clock of a lease member's last poll; null for SLIM (always now). */
  last_seen: string | null;
  /** herdr live agent state (idle/working/blocked/done) when the handle is mapped
   *  to a live herdr pane; null otherwise. */
  status?: string | null;
  /** True when a room mention is queued for this handle but held until it goes
   *  idle (the hold-until-idle doorbell), surfaced as a "wake queued" indicator. */
  wake_pending?: boolean;
  /** herdr's terminal title, the agent's current task ("Review PR comments").
   *  Shown as the roster's activity line for herdr-hosted members. */
  title?: string | null;
}

/** A thread whose floor a run of backend code holds: who holds it and who it
 *  was given to. A thread fact, not a presence one — a member the floor was
 *  given to may not be present at all (a persona engine never is). */
export interface RoomFloor {
  /** The thread's short id, as the board prints it. */
  thread: string;
  episode: string;
  /** The task the thread belongs to, when a row carries it; null for a thread
   *  no row does. A badge names the task, and falls back to the thread id. */
  key: string | null;
  title: string | null;
  holder: string;
  speakers: string[];
}

export interface RoomPresence {
  members: PresenceMember[];
  floors: RoomFloor[];
}

/** Live presence set for a room: SLIM-connected + server-held lease members,
 *  and the floors held in its threads right now. */
export async function fetchRoomMembers(roomName: string): Promise<RoomPresence> {
  const data = await apiFetch<{ members?: PresenceMember[]; floors?: RoomFloor[] }>(
    `/api/rooms/${roomName}/sessions/members`,
    { cache: "no-store", fallback: {} },
  );
  return {
    members: Array.isArray(data.members) ? data.members : [],
    floors: Array.isArray(data.floors) ? data.floors : [],
  };
}

// ── Principals (self-asserted user store) ─────────────────────────────────────

export interface OwnedAgent {
  room: string;
  handle: string;
  adapter: string;
  team: string | null;
}

export interface User {
  handle: string;
  display_name: string;
  teams: string[];
  notify: string | null;
  owns: OwnedAgent[];
}

export interface Team {
  team: string;
  members: string[];
  agent_count: number;
}

/** List registered users with their owned-agent roll-up. */
export async function fetchUsers(): Promise<User[]> {
  const data = await apiFetch<{ users?: User[] }>(`/api/users`, { cache: "no-store", fallback: {} });
  return Array.isArray(data.users) ? data.users : [];
}

/** Teams rolled up from agent manifests and user memberships. */
export async function fetchTeams(): Promise<Team[]> {
  const data = await apiFetch<{ teams?: Team[] }>(`/api/teams`, { cache: "no-store", fallback: {} });
  return Array.isArray(data.teams) ? data.teams : [];
}

/** Create or upsert a user in the global store. Throws `ApiError` with a
 *  readable message on failure so callers can surface it instead of
 *  swallowing it. */
export async function createUser(payload: {
  handle: string;
  display_name?: string;
  teams?: string[];
  notify?: string | null;
}): Promise<User> {
  return apiFetch<User>(`/api/users`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

// ── Metrics ──────────────────────────────────────────────────────────────────

// The counter payload is loosely structured by design — the backend flattens a
// counter's dimensions into its key — so this stays generic rather than forcing
// one shared interface, and the caller supplies the slice it reads.
// Fail-soft: `null` means the hub did not answer.
export async function fetchBackendMetrics<T = Record<string, unknown>>(): Promise<T | null> {
  return apiFetch<T | null>(`/api/observability`, { cache: "no-store", fallback: null });
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
  /** Memory keys of the `work/` rows the agreement compiled into. */
  tasks: string[];
  message_count: number;
  updated_at: string;
  updated_by: string;
  /** The thread this episode was opened from, when it runs inside a task. */
  within?: string | null;
  /** The interaction flow this episode runs; null for a negotiation or a thread. */
  flow?: EpisodeFlow | null;
  /** The steps taken so far, in order. */
  trace?: FlowTraceEntry[];
  /** Where an open run stands, read off the trace. */
  current_step?: string | null;
}

/** One step of an episode's interaction flow, as the record carries it. */
export interface FlowStep {
  id: string;
  /** A role, or each / all / workers. Absent on an end step. */
  to?: string | null;
  prompt?: string;
  wait?: "reply" | "none";
  rounds?: number;
  /** One step id, or a branch by stance (accept / reject / silent / default). */
  next?: string | Record<string, string> | null;
  end?: "resolved" | "rejected" | null;
}

/** The interaction flow an episode runs: the graph the conductor walks, plus
 *  who was bound to each role and what was asked. */
export interface EpisodeFlow {
  name: string;
  description?: string;
  roles?: string[];
  steps: FlowStep[];
  max_steps?: number;
  bound?: Record<string, string>;
  /** Everyone the run was summoned with, in order: the pool a group step asks. */
  cast?: string[];
  ask?: string;
}

/** One step taken in a flow episode. */
export interface FlowTraceEntry {
  step: string;
  turn: number;
  asked?: string[];
  stances?: Record<string, string | null>;
  stance?: string | null;
  next: string;
  at?: string;
}

export interface EpisodeDetail extends EpisodeSummary {
  messages: L9Envelope[];
}

/** Episode summaries for a room, newest first. */
export async function fetchEpisodes(roomName: string): Promise<EpisodeSummary[]> {
  const data = await apiFetch<{ episodes?: EpisodeSummary[] }>(`/api/rooms/${roomName}/episodes`, {
    cache: "no-store",
    fallback: {},
  });
  return data.episodes ?? [];
}

/** One episode plus its full L9 envelope chain, or null if unknown. */
export async function fetchEpisode(
  roomName: string,
  shortId: string,
): Promise<EpisodeDetail | null> {
  return apiFetch<EpisodeDetail | null>(
    `/api/rooms/${roomName}/episodes/${encodeURIComponent(shortId)}`,
    { cache: "no-store", fallback: null },
  );
}

// ── Network diagnostics (the `/health` coordination + identity + auth blocks) ─

/** Per-room channel telemetry: present members (SLIM + server-held `await`
 *  leases), invites deferred by a live episode, episode state, and
 *  durable-inbox counters. */
export interface CoordinationRoom {
  room: string;
  provisioned: boolean;
  persister_alive: boolean;
  members: string[];
  deferred_invites: number;
  episode_active: boolean;
  reserves: number;
  reserve_failures: number;
  reserve_skipped: number;
  receive_errors: number;
  transient_errors: number;
}

/** The fabric-wide view: SLIM node endpoint, live-channel + provision counters,
 *  and one entry per provisioned room. */
export interface CoordinationStatus {
  endpoint: string;
  slim_enabled: boolean;
  channels_live: number;
  provisions_ok: number;
  provisions_failed: number;
  invite_failures: number;
  rooms: CoordinationRoom[];
}

/** The SLIM channel identity tier this hub runs on (`psk` / `signerjwt`).
 *  `status` carries the honest degrade: a selected tier with no resolvable
 *  signing key/roster is `degraded` (falling back to the PSK) or `error`
 *  (required, failing closed). */
export interface IdentityStatus {
  status: string;
  mode: string;
  message: string;
}

/** The HTTP-API JWT gate: whether this hub is gated at all, and against what.
 *  `warnings` carries the backend's own configuration complaints (e.g. no
 *  audience set), so an operator sees the same text `/health` reports. */
export interface AuthStatus {
  enabled: boolean;
  issuers: string[];
  localhost_bypass: boolean;
  audience?: string | null;
  warnings?: string[];
}

/** The three `/health` blocks the Network tab reads. They arrive in one
 *  response, so the deployment's posture (identity tier, auth gate) costs no
 *  extra call beyond the coordination telemetry the tab already polls. */
export interface NetworkStatus {
  coordination: CoordinationStatus | null;
  identity: IdentityStatus | null;
  auth: AuthStatus | null;
}

/** Read the network diagnostics blocks from the backend `/health` endpoint.
 *  Fail-soft: returns null when the backend is unreachable; an individual block
 *  the backend didn't report is null rather than fabricated. */
export async function fetchNetworkStatus(): Promise<NetworkStatus | null> {
  const data = await apiFetch<{
    coordination?: CoordinationStatus;
    identity?: IdentityStatus;
    auth?: AuthStatus;
  } | null>(`/api/health`, {
    cache: "no-store",
    fallback: null,
  });
  if (!data) return null;
  return {
    coordination: data.coordination ?? null,
    identity: data.identity ?? null,
    auth: data.auth ?? null,
  };
}
