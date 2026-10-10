// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// All fetches use relative `/api/*` paths. The Next.js server proxies them
// to the backend (see next.config.ts `rewrites()`), so the browser only ever
// talks to its own origin: no CORS, no second public port, no build-time
// URL baking. The internal backend URL is a server-side concern.

import type { SearchResponse } from "@/lib/search";
import type { MessageSearchResponse } from "@/lib/message-search";
import { encodeMemoryKeyPath } from "@/lib/memory-routes";
import type { RoomStatus } from "@/lib/board/upstream";
import type { RoomFolders } from "@/lib/room-folders";
import type { LockRecord, TallyRecord } from "@/lib/conductor-line";

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

  if (res.status === 204) return undefined as T;

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

/** Canonical API path for a room whose name may contain spaces. */
function roomApiPath(name: string): string {
  return `/api/rooms/${encodeURIComponent(name)}`;
}

// ── Rooms ────────────────────────────────────────────────────────────────────

export interface Room {
  id?: number;
  name: string;
  description?: string | null;
  is_public?: boolean;
  /** Who created it; a private room is listed only for its owner and members. */
  owner?: string | null;
  members?: string[];
  created_at: string;
  /** When the room was last active (transcript mtime); falls back to created_at. */
  last_activity?: string | null;
  is_persistent: boolean;
  mas_id?: string | null;
  workspace_id?: string | null;
  /** The room's display title — the italic hero above the board. */
  title?: string | null;
  /** The pattern the room was loaded from, and the task its flow runs in. */
  pattern?: string | null;
  pattern_task?: string | null;
}

/** Rename a room. Throws `ApiError` on failure. */
export async function setRoomTitle(roomName: string, title: string): Promise<Room> {
  return apiFetch<Room>(roomApiPath(roomName), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title }),
  });
}

/** The rooms listed for `viewer`: every shared room, and their private ones. */
export async function fetchRooms(viewer = ""): Promise<Room[]> {
  const path = viewer ? `/api/rooms?${new URLSearchParams({ viewer })}` : "/api/rooms";
  return apiFetch<Room[]>(path, { cache: "no-store", fallback: [], guard: isArray as (d: unknown) => d is Room[] });
}

/** Make a room private (listed only for its owner and members) or shared again. */
export async function setRoomPrivate(roomName: string, isPrivate: boolean, by: string): Promise<Room> {
  return apiFetch<Room>(roomApiPath(roomName), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_public: !isPrivate, by: by || undefined }),
  });
}

export async function fetchRoom(name: string): Promise<Room> {
  return apiFetch<Room>(roomApiPath(name), { cache: "no-store" });
}

export async function createRoom(data: {
  name: string;
  is_persistent?: boolean;
  /** Private rooms are listed only for their owner (and members). */
  private?: boolean;
  owner?: string;
}): Promise<Room> {
  const { private: isPrivate = false, ...rest } = data;
  return apiFetch<Room>(`/api/rooms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...rest, owner: rest.owner || undefined, is_public: !isPrivate }),
  });
}

export async function deleteRoom(roomName: string): Promise<void> {
  await apiFetch<void>(roomApiPath(roomName), { method: "DELETE" });
}

/** Put a task on a room's board, with its thread minted (the app's `board new`). */
export async function createTask(
  roomName: string,
  data: {
    title: string;
    /** What the task is, in markdown: written into the row under its title. */
    content?: string;
    handle: string;
    assignee?: string;
    key?: string;
    parent?: string;
  },
): Promise<Memory> {
  return apiFetch<Memory>(`${roomApiPath(roomName)}/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

/** Where a swarm is running: its room, its task's key, and the task's thread. */
export interface Swarm {
  room: string;
  key: string;
  episode: string;
  members: string[];
  /** The runner job starting the members, when they run on a machine. */
  job?: string | null;
}

/** Put a team of agents on a task in a room: a conductor, the members, the
 *  task and the kickoff, in one write. The members are workers on the hub, or
 *  with `runner` set, agent CLIs on that machine in a herdr workspace. */
export async function startSwarm(
  room: string,
  data: {
    task: string;
    size?: number;
    /** A repository for the hub to clone; each agent works on its own branch of it. */
    repo?: string;
    created_by?: string;
    /** The machine whose agent CLIs are the members (`mycelium runner`). */
    runner?: string;
    /** Which of that machine's frameworks to start. */
    framework?: string;
    /** The folder on that machine the members work in. */
    cwd?: string;
    /** Give each member its own git worktree of `cwd`. */
    worktree?: boolean;
    /** With runner: from a device paired with it, starts without asking there. */
    signature?: DeviceSignature;
  },
): Promise<Swarm> {
  return apiFetch<Swarm>(`${roomApiPath(room)}/swarms`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
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
  await apiFetch<unknown>(`${roomApiPath(roomName)}/memory`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items }),
  });
}

/** What kind of member a set of notes is for: it changes what they need to say. */
export type NotesKind = "agent" | "persona" | "worker";

/**
 * A member's notes, expanded by the hub's model from the line a person typed
 * about it. Writes nothing; the person edits the draft before adding the
 * member. Throws `ApiError` (502 when the model could not answer).
 */
export async function draftMemberNotes(
  roomName: string,
  data: { brief: string; handle?: string; kind?: NotesKind },
): Promise<string> {
  const res = await apiFetch<{ notes: string }>(`${roomApiPath(roomName)}/agents/draft-notes`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return res.notes;
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
  return apiFetch<AssignmentState>(`${roomApiPath(roomName)}/assignments/${action}`, {
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
  return apiFetch<FieldState>(`${roomApiPath(roomName)}/fields`, {
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
  return apiFetch<Memory[]>(`${roomApiPath(roomName)}/memory?${params}`, {
    cache: "no-store",
    fallback: [],
    guard: isArray as (d: unknown) => d is Memory[],
  });
}

/** One memory by key. Returns null when it isn't there (or the read failed). */
export async function fetchMemory(roomName: string, key: string): Promise<Memory | null> {
  const path = encodeMemoryKeyPath(key);
  return apiFetch<Memory | null>(`${roomApiPath(roomName)}/memory/${path}`, {
    cache: "no-store",
    fallback: null,
  });
}

/** Delete one memory by key. Throws on failure (404 included). */
export async function deleteMemory(roomName: string, key: string): Promise<void> {
  await apiFetch<void>(`${roomApiPath(roomName)}/memory/${encodeMemoryKeyPath(key)}`, {
    method: "DELETE",
  });
}

export interface MemorySearchResult {
  memory: Memory;
  similarity: number;
}

/** Semantic search. Throws on failure so the UI can distinguish "no results"
 *  from "the request failed". */
export async function searchMemories(roomName: string, query: string): Promise<MemorySearchResult[]> {
  const data = await apiFetch<{ results?: MemorySearchResult[] }>(`${roomApiPath(roomName)}/memory/search`, {
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
export async function searchEverything(query: string, limit = 20, viewer = ""): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, limit: String(limit) });
  // Who is asking, so their private rooms are searched too.
  if (viewer) params.set("viewer", viewer);
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

/** A memory's links in both directions. Degrades to empty when the room has
 *  no link index yet. */
export async function fetchMemoryLinks(roomName: string, key: string): Promise<MemoryLinks> {
  const params = new URLSearchParams({ key });
  const data = await apiFetch<Omit<MemoryLinks, "key">>(
    `${roomApiPath(roomName)}/links?${params}`,
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
    `${roomApiPath(roomName)}/links/expand?${params}`,
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

/** The room's whole link graph. Degrades to empty when the room has no link
 *  index yet, or the hub is unreachable. */
export async function fetchMemoryGraph(roomName: string): Promise<MemoryGraph> {
  const data = await apiFetch<Partial<MemoryGraph>>(`${roomApiPath(roomName)}/links/graph`, {
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
  const data = await apiFetch<{ skills?: Skill[] }>(`${roomApiPath(roomName)}/skills`, {
    cache: "no-store",
    fallback: { skills: [] },
  });
  return data.skills ?? [];
}

// ── Schedules ────────────────────────────────────────────────────────────────
// An agent's recurring check-in, kept and fired by the hub. Each run asks a
// cheap pre-check first; only one that finds something wakes the agent (a
// model turn), and nothing a run does is said in the room.

export type ScheduleResult = "woke" | "quiet" | "held" | "busy" | "error";

export interface ScheduleRun {
  at: string;
  result: ScheduleResult;
  trigger: "schedule" | "manual";
  missed?: number;
  found?: string[];
  found_total?: number;
  detail?: string | null;
}

export interface Schedule {
  name: string;
  owner: string;
  every?: string | null;
  cron?: string | null;
  prompt?: string;
  check: string;
  task?: string | null;
  state: "active" | "paused" | "expired";
  paused: boolean;
  created_by: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  next_run?: string | null;
  last_run?: string | null;
  last_result?: ScheduleResult | null;
  runs?: number;
  wakes?: number;
  quiet?: number;
  history?: ScheduleRun[];
}

export interface ScheduleList {
  schedules: Schedule[];
  total: number;
  checks?: Record<string, string>;
}

export interface ScheduleEdit {
  every?: string;
  cron?: string;
  prompt?: string;
  check?: string;
  task?: string;
  paused?: boolean;
  renew?: boolean;
  renew_days?: number;
}

function schedulePath(roomName: string, name?: string): string {
  const base = `${roomApiPath(roomName)}/schedules`;
  return name ? `${base}/${encodeURIComponent(name)}` : base;
}

export async function fetchSchedules(roomName: string): Promise<ScheduleList> {
  return apiFetch<ScheduleList>(schedulePath(roomName), {
    cache: "no-store",
    fallback: { schedules: [], total: 0, checks: {} },
  });
}

export async function createSchedule(
  roomName: string,
  body: ScheduleEdit & { name: string; owner: string; prompt: string; created_by?: string },
): Promise<Schedule> {
  return apiFetch<Schedule>(schedulePath(roomName), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function updateSchedule(roomName: string, name: string, body: ScheduleEdit): Promise<Schedule> {
  return apiFetch<Schedule>(schedulePath(roomName, name), {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function runSchedule(roomName: string, name: string, wake = false): Promise<ScheduleRun> {
  return apiFetch<ScheduleRun>(`${schedulePath(roomName, name)}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ wake }),
  });
}

export async function deleteSchedule(roomName: string, name: string): Promise<void> {
  await apiFetch<void>(schedulePath(roomName, name), { method: "DELETE" });
}

// ── Uploads ──────────────────────────────────────────────────────────────────
// A file the room keeps: an `uploads/<name>` memory plus the bytes it names.
// Linked from chat as `[[uploads/<name>]]`; the bytes are at `url`, sandboxed.

export type UploadKind = "image" | "pdf" | "text" | "audio" | "video";

export interface Upload {
  name: string;
  key: string;
  /** The name the file had when it was added; what a download saves it as. */
  filename: string;
  kind: UploadKind;
  content_type: string;
  size: number;
  sha256: string;
  created_by: string;
  created_at: string;
  episode?: string | null;
  /** The file's bytes, under `/api`. Add `?download=1` to save rather than show. */
  url: string;
}

export interface UploadList {
  uploads: Upload[];
  total: number;
  /** Extensions this hub takes, lowercase, no dot. */
  accepted: string[];
  max_bytes: number;
}

export async function fetchUploads(roomName: string): Promise<UploadList> {
  return apiFetch<UploadList>(`${roomApiPath(roomName)}/uploads`, {
    cache: "no-store",
    fallback: { uploads: [], total: 0, accepted: [], max_bytes: 0 },
  });
}

/**
 * Add one file to the room. XHR rather than fetch, because fetch reports no
 * upload progress and a chip with a bar is what tells someone a large file is
 * on its way. Rejects with an `ApiError` carrying the hub's reason (a type it
 * can't preview, a file over the cap). `signal` cancels it.
 */
export function uploadFile(
  roomName: string,
  file: File,
  createdBy: string,
  opts: { onProgress?: (fraction: number) => void; signal?: AbortSignal } = {},
): Promise<Upload> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${roomApiPath(roomName)}/uploads`);
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) opts.onProgress?.(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(xhr.response as Upload);
        return;
      }
      if (xhr.status === 401) window.dispatchEvent(new Event("mycelium:auth-required"));
      const detail = (xhr.response as { detail?: unknown } | null)?.detail;
      reject(new ApiError(typeof detail === "string" ? detail : `Upload failed (${xhr.status})`, xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("Couldn't reach the hub", 0));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    opts.signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    const form = new FormData();
    form.append("file", file);
    form.append("created_by", createdBy);
    xhr.send(form);
  });
}

export async function deleteUpload(roomName: string, name: string): Promise<void> {
  await apiFetch(`${roomApiPath(roomName)}/uploads/${encodeURIComponent(name)}`, { method: "DELETE" });
}

/** A text upload's contents, for its preview. */
export async function fetchUploadText(upload: Upload): Promise<string> {
  const res = await fetch(upload.url, { cache: "no-store" });
  if (!res.ok) throw new ApiError(await errorDetail(res), res.status);
  return res.text();
}

/** A flow the room's conductor can run: `@conductor <name> @a @b: …`. */
export interface Protocol {
  name: string;
  description: string;
  /** Bound in order to the members a summon names; empty means everyone named. */
  roles: string[];
  /** `room` when the room's `protocols/<name>` memory defines or reshapes it. */
  source: "builtin" | "room";
}

/** The flows a summon in this room can name, for the composer's help while
 *  writing one. Degrades to empty on failure. */
export async function fetchProtocols(roomName: string): Promise<Protocol[]> {
  return apiFetch<Protocol[]>(`${roomApiPath(roomName)}/protocols`, {
    cache: "no-store",
    fallback: [],
    guard: isArray as (d: unknown) => d is Protocol[],
  });
}

/** What the tools a room points at say about the work its rows mention.
 *  A read is answered from the hub's cache and never fetches, so polling this
 *  costs a cache lookup rather than a round trip to GitHub. */
export async function fetchRoomStatus(roomName: string): Promise<RoomStatus> {
  return apiFetch<RoomStatus>(`${roomApiPath(roomName)}/status`, {
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
    `${roomApiPath(roomName)}/messages${qs ? `?${qs}` : ""}`,
    {
      cache: "no-store",
      fallback: { messages: [] },
      guard: isMessagesResponse,
    },
  );
}

/** Search every message in a room by any field (`from:` `task:` `after:` …).
 *
 *  Throws rather than falling back, so the find bar can tell "nothing matched"
 *  from "the hub didn't answer" and say which. */
export async function searchMessages(
  roomName: string,
  q: string,
  opts: { limit?: number; cursor?: string | null; context?: number } = {},
): Promise<MessageSearchResponse> {
  const params = new URLSearchParams({ q, limit: String(opts.limit ?? 50) });
  if (opts.cursor) params.set("cursor", opts.cursor);
  if (opts.context) params.set("context", String(opts.context));
  return apiFetch<MessageSearchResponse>(`${roomApiPath(roomName)}/messages/search?${params}`, {
    cache: "no-store",
  });
}

/** The room's wire history (transcript replay), for backfilling the live
 *  inspector on mount. Frames match the SSE bus shape, so the client projects
 *  backfill + live identically. Returns [] on any error (best-effort). */
export async function fetchWireHistory(
  roomName: string,
  limit = 200,
  before?: string | null,
): Promise<Record<string, unknown>[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (before) params.set("before", before);
  return apiFetch<Record<string, unknown>[]>(
    `${roomApiPath(roomName)}/messages/wire?${params.toString()}`,
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
  return apiFetch<RoomMessage>(`${roomApiPath(roomName)}/messages`, {
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
  /** The machine (runner id) this agent was started on from the app. */
  runner?: string | null;
  /** Which agent CLI it runs (a runner framework id, or herdr's kind for it). */
  framework?: string | null;
}

/** List addressable agents in a room. Used to drive `@`-mention autocomplete. */
export async function fetchRoomAgents(roomName: string): Promise<AgentSummary[]> {
  return apiFetch<AgentSummary[]>(`${roomApiPath(roomName)}/agents`, {
    cache: "no-store",
    fallback: [],
    guard: isArray as (d: unknown) => d is AgentSummary[],
  });
}

export type EngineKind =
  | "aligner"
  | "synthesizer"
  | "hello"
  | "conductor"
  | "persona"
  | "worker";

/** Invite a first-party cognition engine (aligner / synthesizer / hello) into a room.
 *  Engines are backend-owned — registration is just a manifest write with no
 *  machine-local side effects — so the UI can do this natively (no CLI). */
export async function createEngine(
  roomName: string,
  data: { handle: string; kind: EngineKind; description?: string; created_by?: string },
): Promise<AgentSummary> {
  return apiFetch<AgentSummary>(`${roomApiPath(roomName)}/engines`, {
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
  return apiFetch<AgentSummary>(`${roomApiPath(roomName)}/a2a-agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

// ── Runners (the machines agents run on) ─────────────────────────────────────
//
// A runner is `mycelium runner` on someone's computer. It dials out to the hub,
// reports which agent CLIs it found, and takes the jobs queued here. The
// browser never talks to the machine: every call below goes through the hub.

/** One agent CLI the runner knows about, found on the machine or not. */
export interface Framework {
  id: string;
  name: string;
  command: string;
  path: string | null;
  version: string | null;
  /** False for a known framework the scan did not find. */
  installed: boolean;
  /** herdr can start it in a terminal pane. A runner starts agents no other way. */
  launchable: boolean;
  /** Why an installed framework can't be started, or anything else worth saying. */
  note: string | null;
}

export type RunnerAgentStatus =
  | "starting"
  | "running"
  | "idle"
  | "working"
  | "blocked"
  | "stopped"
  | "failed";

/** An agent the runner started in a herdr pane and is keeping track of. */
export interface RunnerAgent {
  handle: string;
  room: string;
  framework: string;
  status: RunnerAgentStatus;
  /** The herdr pane it runs in. */
  pane: string | null;
  cwd: string | null;
  started_at: string;
  detail: string | null;
}

export interface Runner {
  id: string;
  label: string;
  owner: string | null;
  platform: string;
  version: string;
  /** Its host is running there. Without it the machine can start nothing.
   *  (Named for herdr, which was the only host when this field was added.) */
  herdr: boolean;
  /** The host it starts agents on, by name (see `hostOf`). Absent means herdr. */
  host?: string;
  /** Folders agents may be started in. The first is the default. */
  roots: string[];
  frameworks: Framework[];
  agents: RunnerAgent[];
  /** Every agent on the machine, whoever started it, and what's wrong (`mycelium machine`).
   *  Absent from a runner from before it sent one. */
  machine?: MachineReport | null;
  /** How its sync pass (presence up, wakes down) is doing. Absent from a runner from before it sent one. */
  sync?: RunnerSync | null;
  /** Devices whose signed requests it starts without asking (`mycelium runner pair`). */
  pairings?: RunnerPairing[];
  /** False once the machine's heartbeat is stale. */
  connected: boolean;
  last_seen: string;
  started_at: string;
}

/** One herdr agent on a machine, however it got there. */
export interface MachineAgent {
  handle: string;
  room: string;
  pane: string;
  /** `stopped`: its pane is open with nothing running in it. `gone`: the pane closed. */
  state: "working" | "idle" | "blocked" | "stopped" | "gone" | "unknown";
  /** The agent CLI, as herdr names its kind. */
  kind: string | null;
  folder: string | null;
  workspace: string | null;
  /** Whether herdr brings it back after herdr restarts; null when unknown. */
  restores: boolean | null;
  /** Stopped or gone, with a folder and CLI to restart it. */
  restartable: boolean;
}

export interface MachineWorkspace {
  id: string;
  label: string;
  room: string | null;
  agents: MachineAgent[];
}

export interface MachineProblem {
  kind:
    | "stopped"
    | "lost"
    | "runner_down"
    | "wakes_stalled"
    | "binding_failing"
    | "no_restore"
    | "herdr_update"
    | "herdr_down";
  text: string;
  /** The command that fixes it, run on the machine. */
  fix: string | null;
  handles: string[];
}

export interface RunnerSync {
  /** When the last pass finished, by the runner's clock. */
  last_pass_at: string | null;
  last_pass_ms: number | null;
  /** How long the pass running now has run; past `stall_s` no wakes go out. */
  running_s: number | null;
  stall_s: number | null;
  /** Why the last pass failed, when it did. */
  error: string | null;
}

export interface MachineReport {
  machine: string;
  herdr: boolean;
  herdr_server: string | null;
  herdr_client: string | null;
  herdr_minimum: string | null;
  /** Whether its runner is running, which keeps every bound workspace synced. */
  runner: boolean;
  missing_integrations: string[];
  workspaces: MachineWorkspace[];
  problems: MachineProblem[];
}

/** A device paired with a machine, and what the pairing covers (set on that machine). */
export interface RunnerPairing {
  name: string;
  /** The device key's id; this browser's is `useDeviceKeyId()`. */
  key: string;
  paired_at: string;
  /** Null: it doesn't end. */
  expires_at: string | null;
  /** Empty: every folder the runner allows. */
  folders: string[];
  /** Empty: any agent CLI. */
  clis: string[];
  swarms: boolean;
}

/** A paired device's signature over a job, which the hub only carries (`device-key.ts`). */
export interface DeviceSignature {
  key: string;
  body: string;
  sig: string;
}

/** Whether a signed job started under a pairing, or why it waits for a yes after all. */
export interface PairingOutcome {
  accepted: boolean;
  name?: string | null;
  reason?: string | null;
}

export type RunnerJobKind = "launch" | "stop" | "scan" | "swarm" | "restart" | "pair";
/** `waiting`: the machine's runner is asking the person there before it starts anything. */
export type RunnerJobStatus = "queued" | "running" | "waiting" | "done" | "failed";

export interface RunnerJob {
  id: string;
  runner: string;
  kind: RunnerJobKind;
  spec: Record<string, unknown>;
  status: RunnerJobStatus;
  result: Record<string, unknown> | null;
  /** A sentence saying what went wrong, when `status` is failed. */
  error: string | null;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** Set once the machine has looked at a signed job. */
  pairing?: PairingOutcome | null;
}

function runnerApiPath(id: string): string {
  return `/api/runners/${encodeURIComponent(id)}`;
}

/** The machines that have checked in with this hub recently. */
export async function fetchRunners(): Promise<Runner[]> {
  return apiFetch<Runner[]>(`/api/runners`, {
    cache: "no-store",
    fallback: [],
    guard: isArray as (d: unknown) => d is Runner[],
  });
}

export async function fetchRunner(id: string): Promise<Runner> {
  return apiFetch<Runner>(runnerApiPath(id), { cache: "no-store" });
}

/** A machine's recent jobs, newest first. */
export async function fetchRunnerJobs(id: string): Promise<RunnerJob[]> {
  return apiFetch<RunnerJob[]>(`${runnerApiPath(id)}/jobs`, {
    cache: "no-store",
    fallback: [],
    guard: isArray as (d: unknown) => d is RunnerJob[],
  });
}

export async function fetchRunnerJob(id: string, jobId: string): Promise<RunnerJob> {
  return apiFetch<RunnerJob>(`${runnerApiPath(id)}/jobs/${encodeURIComponent(jobId)}`, {
    cache: "no-store",
  });
}

/** Ask the machine to look for agent CLIs again. */
export async function rescanRunner(id: string): Promise<RunnerJob> {
  return apiFetch<RunnerJob>(`${runnerApiPath(id)}/scan`, { method: "POST" });
}

export interface RunnerAgentLaunch {
  room: string;
  handle: string;
  framework: string;
  /** Saved as the agent's notes (`agents/<handle>/notes`), which it reads first. */
  instructions?: string;
  description?: string;
  cwd?: string;
  /** Start it in its own git worktree of `cwd`, on a branch of its own. */
  worktree?: boolean;
  created_by?: string;
  /** From a device paired with the machine: it starts without asking there. */
  signature?: DeviceSignature;
}

/** Register an agent in a room and start it in a herdr pane on a machine. Throws `ApiError`. */
export async function launchRunnerAgent(id: string, data: RunnerAgentLaunch): Promise<RunnerJob> {
  return apiFetch<RunnerJob>(`${runnerApiPath(id)}/agents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

/** Restart stopped agents on a machine, as themselves; the machine asks first. Throws `ApiError`. */
export async function restartMachineAgents(
  id: string,
  agents: { handle: string; room: string }[],
  signature?: DeviceSignature,
): Promise<RunnerJob> {
  return apiFetch<RunnerJob>(`${runnerApiPath(id)}/restart`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ agents, signature }),
  });
}

/** Ask the machine that printed a pairing code to pair this device; follow the job it returns. */
export async function pairRunner(body: {
  code_id: string;
  name: string;
  key: { x: string; y: string };
  proof: string;
}): Promise<RunnerJob> {
  return apiFetch<RunnerJob>(`/api/runners/pair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

/** Stop an agent a machine started. Its registration in the room stays. */
export async function stopRunnerAgent(id: string, room: string, handle: string): Promise<RunnerJob> {
  return apiFetch<RunnerJob>(
    `${runnerApiPath(id)}/agents/${encodeURIComponent(room)}/${encodeURIComponent(handle)}/stop`,
    { method: "POST" },
  );
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
  /** Always true. A bridged A2A agent is proxied by the hub, holds no group
   *  key, and is not a member of the room's MLS group. */
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

/** Read a room's A2A bridge state. Returns null when the hub is unreachable
 *  or too old to serve the route. */
export async function fetchA2aBridge(roomName: string): Promise<A2aBridgeState | null> {
  return apiFetch<A2aBridgeState | null>(`${roomApiPath(roomName)}/a2a/state`, {
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
    `${roomApiPath(roomName)}/sessions/members`,
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

/** How `handle` organizes their rooms list. None yet reads as no folders. */
export async function fetchRoomFolders(handle: string): Promise<RoomFolders> {
  const data = await apiFetch<RoomFolders | null>(`/api/users/${encodeURIComponent(handle)}/room-folders`, {
    cache: "no-store",
    fallback: null,
  });
  return data && Array.isArray(data.folders) ? data : { folders: [] };
}

/** Replace `handle`'s folders with `layout`. Throws `ApiError` on failure. */
export async function saveRoomFolders(handle: string, layout: RoomFolders): Promise<RoomFolders> {
  return apiFetch<RoomFolders>(`/api/users/${encodeURIComponent(handle)}/room-folders`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(layout),
  });
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

// Counter payload is loosely structured: the backend flattens a counter's
// dimensions into its key, so callers supply the slice they read.
// `null` means the hub did not answer.
export async function fetchBackendMetrics<T = Record<string, unknown>>(): Promise<T | null> {
  return apiFetch<T | null>(`/api/observability`, { cache: "no-store", fallback: null });
}

/** What the hub is used for, from the usage events it records (counts only). */
export interface UsageKpis {
  days: number;
  /** Whether this hub also sends its usage events to its analytics destination. */
  sharing: boolean;
  tasks: {
    filed: number;
    resolved: number;
    filed_by: Record<string, number>;
    median_hours_open: number | null;
    /** Median hours open, by who resolved the task (person, agent, engine). */
    median_hours_open_by: Record<string, number>;
  };
  /** Flow name (built-in, or "custom") → outcome → runs. */
  flows: Record<string, Record<string, number>>;
  negotiations: Record<string, number>;
  agents_joined: Record<string, number>;
  active_days: number;
  daily: { day: string; filed: number; resolved: number }[];
  work_total: number;
  first_value_hours: number | null;
}

export async function fetchUsage(days = 30): Promise<UsageKpis | null> {
  return apiFetch<UsageKpis | null>(`/api/observability/usage?days=${days}`, {
    cache: "no-store",
    fallback: null,
  });
}

// ── Messages / episodes ─────────────────────────────────────────────────────
// Episodes are the persisted, causally-linked message record of a coordination
// session (one markdown file per session under `log/episodes/`). The protocol
// inspector reads them for the rich causal chain + consensus metrics; wire
// envelopes carry empty `message.parents` — the chain lives here instead.

export interface MessageActor {
  id: string;
  role: string;
}

export interface MyceliumMessage {
  header: {
    protocol?: string;
    subprotocol?: string;
    version?: string;
    kind: string;
    subkind?: string | null;
    participants?: { actors?: MessageActor[]; groups?: Record<string, unknown> | null };
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
  /** A flow that picks (concord): each member's rating of the pick, out of 1. */
  satisfaction?: Record<string, number>;
  /** And the least happy member's. */
  min_satisfaction?: number;
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
  /** `select` picks among the options by the ratings given, `tally` counts
   *  the points or the words given so far, `lock` merges the points into a
   *  shared summary and saves it; none of the three asks anybody. Absent
   *  means an ordinary step that asks someone. */
  kind?: "ask" | "select" | "tally" | "lock";
  /** A role, or each / all / workers / bottleneck / contested (everyone who
   *  gave a meaning to a word used in different senses). Absent on an end or
   *  a step that asks nobody. */
  to?: string | null;
  prompt?: string;
  wait?: "reply" | "none";
  rounds?: number;
  /** What the replies add to the run: suggestions, ratings of them, or
   *  pieces of the shared summary (points and the meanings of words). */
  collect?: "options" | "scores" | "pieces" | null;
  /** What every reply must carry; a reply without it is asked once more. */
  require?: "stance" | "scores" | "pieces" | null;
  /** A select step's bar, 0-1, and how many fixes it sends for. */
  threshold?: number | null;
  max_repairs?: number | null;
  /** What a tally step counts, and how many times it may send back for more. */
  of?: "points" | "terms" | null;
  max_rounds?: number | null;
  /** One step id, or a branch by stance (accept / reject / silent / default),
   *  or, on a select, by how the pick went (feasible / infeasible / stuck),
   *  on a tally of points by grew / settled / empty, on a tally of terms by
   *  contested / clear, and on a lock by locked / empty. */
  next?: string | Record<string, string> | null;
  /** `converged` is an agreement a select step certified. */
  end?: "resolved" | "rejected" | "converged" | null;
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
  /** A select step's pick: how it went, and who is short. */
  select?: {
    outcome: "feasible" | "infeasible" | "stuck";
    pick: string | null;
    lowest: number | null;
    missing: string[];
    least_happy: string | null;
  };
  /** A tally step's count, as its conductor line carries it. */
  tally?: TallyRecord;
  /** A lock step's shared summary, as its conductor line carries it. */
  lock?: LockRecord;
  /** A second asking of the members who replied without what the step requires. */
  again?: boolean;
  next: string;
  at?: string;
}

export interface EpisodeDetail extends EpisodeSummary {
  messages: MyceliumMessage[];
}

/** Episode summaries for a room, newest first. */
export async function fetchEpisodes(roomName: string): Promise<EpisodeSummary[]> {
  const data = await apiFetch<{ episodes?: EpisodeSummary[] }>(`${roomApiPath(roomName)}/episodes`, {
    cache: "no-store",
    fallback: {},
  });
  return data.episodes ?? [];
}

/** One episode plus its full message chain, or null if unknown. */
export async function fetchEpisode(
  roomName: string,
  shortId: string,
): Promise<EpisodeDetail | null> {
  return apiFetch<EpisodeDetail | null>(
    `${roomApiPath(roomName)}/episodes/${encodeURIComponent(shortId)}`,
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
  /** The hub's release, stamped from the tag it was built from (About reads it). */
  version?: string | null;
}

/** Read the network diagnostics blocks from the backend `/health` endpoint.
 *  Fail-soft: returns null when the backend is unreachable; an individual block
 *  the backend didn't report is null rather than fabricated. */
export async function fetchNetworkStatus(): Promise<NetworkStatus | null> {
  const data = await apiFetch<{
    coordination?: CoordinationStatus;
    identity?: IdentityStatus;
    auth?: AuthStatus;
    version?: string;
  } | null>(`/api/health`, {
    cache: "no-store",
    fallback: null,
  });
  if (!data) return null;
  return {
    coordination: data.coordination ?? null,
    identity: data.identity ?? null,
    auth: data.auth ?? null,
    version: data.version ?? null,
  };
}
