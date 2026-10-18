// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Room server state, fetched once per resource.
 *
 * Every read here is an SWR hook keyed by `["room", <name>, <resource>]`, so N
 * components asking for the same thing make one request and share one cache
 * entry: the composer and the Members rail read the same roster, the status bar
 * and the board read the same rows. SWR owns revalidation — polling,
 * refocus, reconnect, and request dedup — so components hold no `setInterval`
 * and no fetched-data `useState`, and a pushed event refreshes every reader
 * through `useRoomRevalidate` instead of a counter threaded down as a prop.
 *
 * Client state (which rail is open, what's selected) stays where it is: this
 * module is only for what the hub owns.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { EMPTY_LAYOUT, type RoomFolders } from "@/lib/room-folders";
import type { RoomStatus } from "@/lib/board/upstream";
import useSWR, { useSWRConfig, type SWRConfiguration } from "swr";
import {
  fetchA2aBridge,
  fetchEpisodes,
  fetchMyPaused,
  fetchMemories,
  fetchMessages,
  fetchNetworkStatus,
  fetchRoom,
  fetchRoomAgents,
  fetchRoomBoard,
  fetchWaiting,
  fetchRoomMembers,
  fetchRoomPeople,
  fetchRoomStatus,
  fetchRoomFolders,
  fetchProtocols,
  fetchRooms,
  fetchRoomSettings,
  fetchSchedules,
  fetchSkills,
  fetchUploads,
  fetchVerifierFlags,
  logFetchError,
  saveRoomFolders,
  searchMessages,
  type A2aBridgeState,
  type AgentPause,
  type AgentSummary,
  type BoardRead,
  type EpisodeSummary,
  type WaitingItem,
  type Memory,
  type NetworkStatus,
  type PresenceMember,
  type Protocol,
  type Room,
  type JoinedVia,
  type RoomFloor,
  type RoomOther,
  type RoomSubscription,
  type RoomPeople,
  type RoomPresence,
  type RoomMessage,
  type RoomSetting,
  type ScheduleList,
  type Skill,
  type UploadList,
  type VerifierFlag,
} from "@/lib/api";
import { floorsByHandle } from "@/lib/floors";
import { latestPreview } from "@/lib/room-preview";
import { memoryTitle } from "@/lib/memory-preview";
import { useCurrentUser, usePrincipal } from "@/components/current-user";

/**
 * One cadence per resource rather than one per component, picked from how fast
 * the thing actually moves: a live negotiation and compiled work are worth
 * watching closely; manifests, memories and skills change when someone changes
 * them, and a pushed event revalidates those the moment they do.
 */
const POLL = {
  rooms: 30_000,
  room: 30_000,
  agents: 30_000,
  members: 30_000,
  // Changes when someone joins or is taken out; the panel revalidates on its own changes.
  people: 30_000,
  messages: 30_000,
  memories: 30_000,
  skills: 30_000,
  // A change made here revalidates at once; this catches one made elsewhere.
  settings: 60_000,
  // A run is pushed (`schedule_changed`); this only catches a missed push.
  schedules: 30_000,
  // A flag and its dismissal arrive as `check` notices, which re-read this;
  // the poll only catches a missed one.
  verifierFlags: 60_000,
  uploads: 30_000,
  // Read only while a conductor summon is being written; a room's own flows
  // change about as often as its skills.
  protocols: 60_000,
  episodes: 5_000,
  coordination: 20_000,
  // The hub answers a status read from cache and refreshes behind it, so this
  // is how often a resolved answer reaches the board, not how often GitHub is
  // asked. Polling harder would not make anything fresher.
  status: 20_000,
  // A board move is pushed as a notice and the board revalidates on it; this
  // catches a thread's latest line, which moves without one.
  board: 15_000,
  waiting: 15_000,
  a2a: 15_000,
} as const;

/** The command center wants only the last thing said, and `latestPreview`
 *  scans a short window past any protocol ticks on top of it. */
const LATEST_LIMIT = 20;

/** A thread is one task's conversation, so its whole history is usually one
 *  read. Where it is not, the window grows by another of these. */
const THREAD_LIMIT = 200;

/** What a thread belongs to, for anything that has to name it. */
export interface ThreadOwner {
  /** Every row bound to this thread, in the order the room lists them. */
  keys: string[];
  /**
   * What to call it — the row's own title, but **only** where exactly one row
   * is bound. A negotiation compiles several tasks and binds all of them to the
   * episode it converged in, so naming one of those would be picking a row at
   * random and asserting it. Null means the thread is named by its short id,
   * which is what is actually true of it.
   */
  title: string | null;
}

// `memoryTitle` is shared with the board's projection (lib/memory-preview), so a
// task named in the channel and named on the board can never disagree.

// Stable empties: a fresh `[]` per render would break every downstream memo.
const NO_STATUS: RoomStatus = {
  room: "",
  field: "upstream",
  providers: [],
  refs: [],
  rows: {},
  refreshing: false,
};
const NO_ROOMS: Room[] = [];
const NO_AGENTS: AgentSummary[] = [];
const NO_PRESENCE: RoomPresence = { members: [], floors: [], subscriptions: [], paused: [] };
const NO_MESSAGES: RoomMessage[] = [];
const NO_PEOPLE: RoomPeople = { people: [], agents: [], engines: [], others: [] };
const NO_MEMORIES: Memory[] = [];
const NO_SKILLS: Skill[] = [];
const NO_SETTINGS: RoomSetting[] = [];
const NO_SCHEDULES: ScheduleList = { schedules: [], total: 0, checks: {} };
const NO_UPLOADS: UploadList = { uploads: [], total: 0, accepted: [], max_bytes: 0 };
const NO_PROTOCOLS: Protocol[] = [];
const NO_EPISODES: EpisodeSummary[] = [];

type RoomResource =
  | "room"
  | "agents"
  | "members"
  | "people"
  | "messages"
  | "memories"
  | "skills"
  | "settings"
  | "schedules"
  | "uploads"
  | "protocols"
  | "episodes"
  | "status"
  | "board"
  | "waiting"
  | "a2a"
  | "verifier-flags";

/** A null key parks the hook: a room-less render fetches nothing. */
function roomKey(room: string, resource: RoomResource, ...rest: (string | number)[]) {
  return room ? (["room", room, resource, ...rest] as const) : null;
}

/** Per-call-site overrides; refreshInterval: 0 skips polling in room grids. */
export interface RoomQueryOptions {
  refreshInterval?: number;
}

interface Query<T> {
  data: T;
  loading: boolean;
  error: unknown;
  refresh: () => void;
}

function useRoomQuery<T>(
  room: string,
  resource: RoomResource,
  load: (room: string) => Promise<T>,
  empty: T,
  fallbackInterval: number,
  opts: RoomQueryOptions = {},
  config: SWRConfiguration = {},
): Query<T> {
  const { data, isLoading, error, mutate } = useSWR(roomKey(room, resource), () => load(room), {
    refreshInterval: opts.refreshInterval ?? fallbackInterval,
    ...config,
  });
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  return { data: data ?? empty, loading: isLoading, error, refresh };
}

// ── Rooms ────────────────────────────────────────────────────────────────────

export function useRooms(opts: RoomQueryOptions = {}) {
  // Keyed by who is looking: the list includes their private rooms.
  const viewer = usePrincipal();
  const { data, isLoading, mutate } = useSWR(["rooms", viewer], () => fetchRooms(viewer), {
    refreshInterval: opts.refreshInterval ?? POLL.rooms,
  });
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  return { rooms: data ?? NO_ROOMS, loading: isLoading, refresh };
}

const LOCAL_FOLDERS = "mycelium.room-folders";

function readLocalFolders(): RoomFolders {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(LOCAL_FOLDERS) ?? "null");
    return parsed && Array.isArray(parsed.folders) ? parsed : EMPTY_LAYOUT;
  } catch {
    return EMPTY_LAYOUT;
  }
}

function writeLocalFolders(layout: RoomFolders): RoomFolders {
  try {
    window.localStorage.setItem(LOCAL_FOLDERS, JSON.stringify(layout));
  } catch {
    // Storage blocked: the folders last until the page does.
  }
  return layout;
}

/**
 * How you organize your rooms list, and a way to change it. Kept on the hub
 * under your handle, so it follows you to another browser and into the app;
 * before you have a name, in this browser alone. A change shows at once and
 * rolls back if the hub refuses it.
 */
export function useRoomFolders() {
  const handle = usePrincipal();
  const { data, mutate } = useSWR(["room-folders", handle], () =>
    handle ? fetchRoomFolders(handle) : readLocalFolders(),
  );
  const layout = data ?? EMPTY_LAYOUT;
  // Two quick changes in a row both start from the newest layout, not the render's.
  const latest = useRef(layout);
  useEffect(() => {
    latest.current = layout;
  }, [layout]);
  const update = useCallback(
    (change: (layout: RoomFolders) => RoomFolders) => {
      const next = change(latest.current);
      latest.current = next;
      const save = handle ? saveRoomFolders(handle, next) : Promise.resolve(writeLocalFolders(next));
      void mutate(save, { optimisticData: next, rollbackOnError: true, revalidate: false }).catch(
        logFetchError("saveRoomFolders"),
      );
    },
    [handle, mutate],
  );
  return { layout, update };
}

/** Every agent you own that is paused, across rooms, for the status rail. */
export function useMyPaused() {
  const handle = usePrincipal();
  const { data, mutate } = useSWR(["my-paused", handle], () => fetchMyPaused(handle), {
    refreshInterval: POLL.members,
  });
  const refresh = useCallback(() => void mutate(), [mutate]);
  return { paused: data ?? [], refresh };
}

/** fetchRoom failure logged; returns null for caller to render. */
export function useRoom(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, error, refresh } = useRoomQuery(
    room,
    "room",
    fetchRoom,
    null as Room | null,
    POLL.room,
    opts,
    { onError: logFetchError(`fetchRoom(${room})`) },
  );
  return { room: data, loading, error, refresh };
}

// ── Room resources ───────────────────────────────────────────────────────────

export function useRoomAgents(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "agents", fetchRoomAgents, NO_AGENTS, POLL.agents, opts,
  );
  return { agents: data, loading, refresh };
}

/** Live presence: SLIM-connected members plus server-held `await` leases, and
 *  the floors held in the room's threads right now. */
export function useRoomMembers(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "members", fetchRoomMembers, NO_PRESENCE, POLL.members, opts,
  );
  return {
    members: data.members,
    floors: data.floors,
    // Absent from a members read older than subscriptions.
    subscriptions: data.subscriptions ?? [],
    // Absent from a hub older than pausing.
    paused: data.paused ?? [],
    loading,
    refresh,
  };
}

/** Everyone in a room from the hub's records: its people (recorded when they
 *  joined), and the handles that hold a task or are present but are neither a
 *  person nor an agent. */
export function useRoomPeople(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "people", fetchRoomPeople, NO_PEOPLE, POLL.people, opts,
  );
  return { people: data.people, others: data.others, loading, refresh };
}

/** Recent chat, for surfaces that read the room's history rather than tail it.
 *  Shares one cache entry with every other reader of the same page size. */
export function useRoomMessages(room: string, limit = 200, opts: RoomQueryOptions = {}) {
  const { data, isLoading, mutate } = useSWR(
    room ? (["room", room, "messages", limit] as const) : null,
    () => fetchMessages(room, limit),
    { refreshInterval: opts.refreshInterval ?? POLL.messages },
  );
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  return { messages: data?.messages ?? NO_MESSAGES, loading: isLoading, refresh };
}

/**
 * A search over the room's whole history, for the channel's find bar.
 *
 * Keyed by the query, so going back to an earlier one is instant, and under
 * the `["room", <name>]` prefix so a pushed write refreshes an open search with
 * everything else. The previous answer stays on screen while the next query is
 * in flight: a find bar that blanks on every keystroke reads as "no matches".
 * An empty query parks it: an empty find bar asks the hub nothing.
 */
export function useMessageSearch(room: string, query: string, limit = 50) {
  const q = query.trim();
  const { data, error, isLoading, isValidating } = useSWR(
    room && q ? (["room", room, "message-search", q, limit] as const) : null,
    () => searchMessages(room, q, { limit }),
    { keepPreviousData: true, revalidateOnFocus: false },
  );
  return { result: q ? data ?? null : null, error: error as Error | undefined, loading: isLoading || isValidating };
}

/**
 * One thread's messages, and nothing else.
 *
 * Its own cache entry — `["room", <name>, "messages", "thread", <urn>]` — so a
 * thread pane never overwrites the room's own feed with a filtered slice of it,
 * which is what a shared key would do the moment both are open. Still under the
 * `["room", <name>]` prefix, so `useRoomRevalidate` reaches it: an SSE write
 * into a thread refreshes the thread and the room together.
 *
 * A null episode parks the hook, so a closed pane fetches nothing.
 *
 * **Older messages arrive by widening the window, not by paging behind a
 * cursor.** The read is newest-first, so the newest N always contains the
 * newest M before it: widening is idempotent against the live stream in the way
 * an offset is not, and it stays one cache entry — which is what keeps a pushed
 * write reaching every reader through `useRoomRevalidate`. The channel pages by
 * cursor instead because it assembles its feed by hand from two reads plus the
 * SSE tail, and re-reading the head each time would throw that away. Here the
 * whole conversation is the read. `hasOlder` is exact: the room answers with
 * how many messages matched, not just the page it returned.
 */
export function useThreadMessages(
  room: string,
  episode: string | null,
  limit = THREAD_LIMIT,
  opts: RoomQueryOptions = {},
) {
  const [depth, setDepth] = useState(limit);
  // A different thread, or a caller changing its page size, starts the walk over.
  const [scope, setScope] = useState(`${episode}:${limit}`);
  if (scope !== `${episode}:${limit}`) {
    setScope(`${episode}:${limit}`);
    setDepth(limit);
  }
  const { data, isLoading, isValidating, mutate } = useSWR(
    room && episode ? (["room", room, "messages", "thread", episode, depth] as const) : null,
    () => fetchMessages(room, depth, { episode }),
    {
      refreshInterval: opts.refreshInterval ?? POLL.messages,
      // Widening changes the key, and without this the conversation would blank
      // out and re-enter on its own skeleton every time someone asked for more
      // of it. The narrower window is a prefix of the wider one, so the messages
      // already on screen are the right thing to keep showing.
      keepPreviousData: true,
    },
  );
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  const messages = data?.messages ?? NO_MESSAGES;
  const hasOlder = (data?.total ?? 0) > messages.length;
  const loadOlder = useCallback(() => setDepth((d) => d + limit), [limit]);
  return {
    messages,
    loading: isLoading,
    refresh,
    hasOlder,
    loadOlder,
    // A widened window that the answer has not caught up with yet. A poll of a
    // window already filled is not this, which is why the length is compared.
    loadingOlder: isValidating && hasOlder && depth > messages.length,
  };
}

/**
 * Every thread the room's rows are bound to, keyed by URN.
 *
 * The binding is the task's (`Memory.episode`), so this is that same edge read
 * the other way round — what a bare URN in a ping is a thread *of*. Derived off
 * the shared memories cache, so naming a thread costs no request.
 *
 * Two ways a thread ends up without a name here, both honest rather than
 * missing: an episode no row mentions (a coordination phase opens its own and
 * records no back-link to the task that summoned it), and an episode several
 * rows share (a converged negotiation binds every task it compiled to itself).
 */
export function useRoomThreads(room: string): Map<string, ThreadOwner> {
  const { memories } = useRoomMemories(room);
  return useMemo(() => {
    const index = new Map<string, ThreadOwner>();
    for (const memory of memories) {
      if (!memory.episode) continue;
      const known = index.get(memory.episode);
      if (known) {
        known.keys.push(memory.key);
        known.title = null;
      } else {
        index.set(memory.episode, { keys: [memory.key], title: memoryTitle(memory) });
      }
    }
    return index;
  }, [memories]);
}

/** What a row is called, and the thread that opens it. */
export interface RowNaming {
  title: string;
  episode: string | null;
  /** What the row is waiting on (`blocked_by`), else what whoever last moved it
   *  said about it (`assignment_note`); null when neither was written. */
  note: string | null;
}

/**
 * Every row the room holds, keyed by its own key.
 *
 * The sibling of {@link useRoomThreads}, read the other way round: a notice and
 * a memory push both name the *row* they are about, so a feed that wants to
 * print a task's name rather than its `work/…` slug asks here. Off the same
 * memories cache, so naming a row costs no request either.
 */
export function useRoomRowNames(room: string): Map<string, RowNaming> {
  const { memories } = useRoomMemories(room);
  return useMemo(() => {
    const index = new Map<string, RowNaming>();
    for (const memory of memories) {
      const said = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : null);
      index.set(memory.key, {
        title: memoryTitle(memory),
        episode: memory.episode ?? null,
        note: said(memory.meta?.blocked_by) ?? said(memory.meta?.assignment_note),
      });
    }
    return index;
  }, [memories]);
}

/** The last readable line in a room, for an inbox-style row. Its own SWR key,
 *  so it never collides with a longer page of the same messages. */
export function useRoomLatest(room: string, opts: RoomQueryOptions = {}) {
  const { data, isLoading, mutate } = useSWR(
    room ? (["room", room, "messages", LATEST_LIMIT] as const) : null,
    () => fetchMessages(room, LATEST_LIMIT),
    { refreshInterval: opts.refreshInterval ?? POLL.messages },
  );
  const latest = useMemo(() => (data ? latestPreview(data.messages) : null), [data]);
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  return { latest, loading: isLoading, refresh };
}

/** What the tools a room's rows point at say. One cache entry shared by every
 *  view that shows an upstream state, so the board reads it once. */
export function useRoomStatus(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, error, refresh } = useRoomQuery(
    room, "status", fetchRoomStatus, NO_STATUS, POLL.status, opts,
  );
  return { status: data, loading, error, refresh };
}

const NO_BOARD: BoardRead = { epics: [], tasks: [] };
const NO_WAITING: WaitingItem[] = [];

/** The room's open epics and other open tasks, as the hub works them out. */
export function useRoomBoard(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "board", fetchRoomBoard, NO_BOARD, POLL.board, opts,
  );
  return { board: data, loading, refresh };
}

/** What is waiting on `handle` in the room. Parked until there is a handle. */
export function useRoomWaiting(room: string, handle: string, opts: RoomQueryOptions = {}) {
  const key = handle ? roomKey(room, "waiting", handle) : null;
  const { data, isLoading, mutate } = useSWR(key, () => fetchWaiting(room, handle), {
    refreshInterval: opts.refreshInterval ?? POLL.waiting,
  });
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  return { items: data?.items ?? NO_WAITING, loading: isLoading, refresh };
}

export function useRoomMemories(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "memories", fetchMemories, NO_MEMORIES, POLL.memories, opts,
  );
  return { memories: data, loading, refresh };
}

/** A room's settings, with where each value comes from. One cache entry for the
 *  settings page and every view that acts on a setting (the channel reads which
 *  board moves to show from it). */
export function useRoomSettings(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "settings", fetchRoomSettings, NO_SETTINGS, POLL.settings, opts,
  );
  return { settings: data, loading, refresh };
}

export function useRoomSkills(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "skills", fetchSkills, NO_SKILLS, POLL.skills, opts,
  );
  return { skills: data, loading, refresh };
}

/** The room's schedules, and the pre-checks its hub runs. One cache entry, so
 *  the Schedules tab and the Members rail's clock badges share one read. */
export function useRoomSchedules(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "schedules", fetchSchedules, NO_SCHEDULES, POLL.schedules, opts,
  );
  return { schedules: data.schedules, checks: data.checks ?? {}, loading, refresh };
}

const NO_FLAGS: VerifierFlag[] = [];

/** The verifier's lines still showing, by the message each goes under. A flag
 *  someone said is fine is left out.
 *
 *  Keyed by both of a message's ids: the one the room's history read gives it,
 *  and its envelope id, which is what a message that arrived live over the
 *  stream carries until a reload reads it from history. */
export function useRoomVerifierFlags(room: string, opts: RoomQueryOptions = {}) {
  const { data, refresh } = useRoomQuery(
    room, "verifier-flags", fetchVerifierFlags, NO_FLAGS, POLL.verifierFlags, opts,
  );
  const byMessage = useMemo(() => verifierFlagsByMessage(data), [data]);
  return { byMessage, refresh };
}

export function verifierFlagsByMessage(flags: VerifierFlag[]): Map<string, VerifierFlag[]> {
  const out = new Map<string, VerifierFlag[]>();
  for (const flag of flags) {
    if (flag.state !== "shown") continue;
    for (const id of new Set([flag.message_id, flag.envelope_id].filter(Boolean) as string[])) {
      out.set(id, [...(out.get(id) ?? []), flag]);
    }
  }
  return out;
}

/** Handles that own a live (not expired) schedule, for the Members rail's clock. */
export function useScheduledHandles(room: string): Map<string, number> {
  const { schedules } = useRoomSchedules(room);
  return useMemo(() => {
    const out = new Map<string, number>();
    for (const s of schedules) {
      if (s.state === "expired") continue;
      out.set(s.owner, (out.get(s.owner) ?? 0) + 1);
    }
    return out;
  }, [schedules]);
}

/** The room's uploads, and what its hub takes. One cache entry, so every
 *  message drawing an attachment and the composer checking a file share it. */
export function useRoomUploads(room: string, opts: RoomQueryOptions = {}) {
  // Every message renders this hook, most with no room to read (they link no
  // file), so the loader is only reached once SWR has a key to fetch.
  const { data, loading, refresh } = useRoomQuery<UploadList>(
    room, "uploads", (r) => fetchUploads(r), NO_UPLOADS, POLL.uploads, opts,
  );
  return { ...data, loading, refresh };
}

/** The flows the room's conductor can run. Pass `""` as the room to read nothing,
 *  for a surface that needs them only while a summon is being written. */
export function useRoomProtocols(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading } = useRoomQuery(room, "protocols", fetchProtocols, NO_PROTOCOLS, POLL.protocols, opts);
  return { protocols: data, loading };
}

export function useRoomEpisodes(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "episodes", fetchEpisodes, NO_EPISODES, POLL.episodes, opts,
  );
  return { episodes: data, loading, refresh };
}

/** The room's A2A bridge: bridged members, exposure, and recent exchanges.
 *  Null until it loads, and for a hub that can't serve it. */
export function useA2aBridge(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "a2a", fetchA2aBridge, null as A2aBridgeState | null, POLL.a2a, opts,
  );
  return { bridge: data, loading, refresh };
}

/** Fabric-wide `/health` diagnostics — SLIM telemetry plus the hub's identity
 *  tier and auth gate — as one read shared by every reader. */
export function useNetworkStatus(opts: RoomQueryOptions = {}) {
  const { data, isLoading } = useSWR<NetworkStatus | null>("network-status", fetchNetworkStatus, {
    refreshInterval: opts.refreshInterval ?? POLL.coordination,
  });
  return { network: data ?? null, loading: isLoading };
}

// ── Revalidation ─────────────────────────────────────────────────────────────

/** Refetch all room resources; one call reaches every reader without prop-threading. */
export function useRoomRevalidate(room: string): () => void {
  const { mutate } = useSWRConfig();
  return useCallback(() => {
    void mutate((key) => Array.isArray(key) && key[0] === "room" && key[1] === room);
  }, [mutate, room]);
}

// ── Roster ───────────────────────────────────────────────────────────────────

/** One of the room's people, as the hub recorded them joining. Never an agent,
 *  and never someone only guessed from having posted. */
export interface RosterPerson {
  handle: string;
  /** How they joined: made the room, were added, posted, or were there before
   *  rooms kept a list. */
  via: JoinedVia;
  joinedAt: string;
  /** Team slugs, unioned from the agents this person owns. */
  teams: string[];
  /** True when this is the handle the browser is acting as. */
  you: boolean;
  /** True when they own ≥1 agent here. */
  owns: boolean;
  presence?: PresenceMember;
}

export interface RoomRoster {
  agents: AgentSummary[];
  people: RosterPerson[];
  /** Handles that hold a task or are present but are neither a person nor an
   *  agent here, such as an agent with no manifest in this room. */
  others: RoomOther[];
  /** handle (lowercased) → presence, for badging a row live or awaiting. */
  presence: Map<string, PresenceMember>;
  /** handle (lowercased) → the floor it holds or was given, for badging whose turn it is. */
  floors: Map<string, RoomFloor>;
  /** handle (lowercased) → what it subscribed to, for its hover card. */
  subscriptions: Map<string, RoomSubscription[]>;
  /** handle (lowercased) → its pause, for a paused agent. */
  paused: Map<string, AgentPause>;
  loading: boolean;
  refresh: () => void;
}

/**
 * Everyone in a room, computed once: agents from the manifests, people from the
 * hub's record of who joined (`GET /rooms/{room}/members`), never from who has
 * posted. The Members rail and the composer's `@` popover are two views of this
 * one answer.
 */
export function useRoomRoster(room: string, opts: RoomQueryOptions = {}): RoomRoster {
  const { agents, loading, refresh: refreshAgents } = useRoomAgents(room, opts);
  const {
    members,
    floors: floorList,
    subscriptions: subscriptionList,
    paused: pausedList,
    refresh: refreshMembers,
  } = useRoomMembers(room, opts);
  const { people: joined, others, refresh: refreshPeople } = useRoomPeople(room, opts);
  const { principal } = useCurrentUser();
  const me = principal.trim().toLowerCase();

  const presence = useMemo(
    () => new Map(members.map((m) => [m.handle.toLowerCase(), m])),
    [members],
  );
  const floors = useMemo(() => floorsByHandle(floorList), [floorList]);
  const subscriptions = useMemo(() => {
    const byHandle = new Map<string, RoomSubscription[]>();
    for (const s of subscriptionList) {
      const handle = s.handle.toLowerCase();
      byHandle.set(handle, [...(byHandle.get(handle) ?? []), s]);
    }
    return byHandle;
  }, [subscriptionList]);
  const paused = useMemo(
    () => new Map(pausedList.map((p) => [p.handle.toLowerCase(), p])),
    [pausedList],
  );

  const agentHandles = useMemo(() => new Set(agents.map((a) => a.handle.toLowerCase())), [agents]);

  const people = useMemo(() => {
    const owned = (handle: string) => agents.filter((a) => (a.owner ?? "").toLowerCase() === handle);
    return joined
      // The hub never records an agent as a person; this keeps a manifest
      // written since the last read from being drawn twice.
      .filter((p) => !agentHandles.has(p.handle.toLowerCase()))
      .map((p): RosterPerson => {
        const handle = p.handle.toLowerCase();
        const mine = owned(handle);
        return {
          handle,
          via: p.via,
          joinedAt: p.joined_at,
          teams: [...new Set(mine.flatMap((a) => (a.team ? [a.team] : [])))],
          you: handle === me,
          owns: mine.length > 0,
          presence: presence.get(handle),
        };
      })
      .sort((x, y) => x.handle.localeCompare(y.handle));
  }, [agents, agentHandles, joined, presence, me]);

  const otherHandles = useMemo(
    () => others.filter((o) => !agentHandles.has(o.handle.toLowerCase())),
    [others, agentHandles],
  );

  const refresh = useCallback(() => {
    refreshAgents();
    refreshMembers();
    refreshPeople();
  }, [refreshAgents, refreshMembers, refreshPeople]);

  return {
    agents,
    people,
    others: otherHandles,
    presence,
    floors,
    subscriptions,
    paused,
    loading,
    refresh,
  };
}
