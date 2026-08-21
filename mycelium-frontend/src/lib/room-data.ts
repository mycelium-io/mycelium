// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Room server state, fetched once per resource.
 *
 * Every read here is an SWR hook keyed by `["room", <name>, <resource>]`, so N
 * components asking for the same thing make one request and share one cache
 * entry: the composer and the Members rail read the same roster, the status bar
 * and the plan header read the same plan. SWR owns revalidation — polling,
 * refocus, reconnect, and request dedup — so components hold no `setInterval`
 * and no fetched-data `useState`, and a pushed event refreshes every reader
 * through `useRoomRevalidate` instead of a counter threaded down as a prop.
 *
 * Client state (which rail is open, what's selected) stays where it is: this
 * module is only for what the hub owns.
 */

import { useCallback, useMemo } from "react";
import useSWR, { useSWRConfig, type SWRConfiguration } from "swr";
import {
  fetchEpisodes,
  fetchMemories,
  fetchMemoryIntegrity,
  fetchMessages,
  fetchNetworkStatus,
  fetchPlan,
  fetchRoom,
  fetchRoomAgents,
  fetchRoomMembers,
  fetchRooms,
  fetchSkills,
  logFetchError,
  type AgentSummary,
  type EpisodeSummary,
  type Memory,
  type MemoryLinksIntegrity,
  type NetworkStatus,
  type PlanResponse,
  type PresenceMember,
  type Room,
  type Skill,
} from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";

/**
 * One cadence per resource rather than one per component, picked from how fast
 * the thing actually moves: a live negotiation and a compiled plan are worth
 * watching closely; manifests, memories and skills change when someone changes
 * them, and a pushed event revalidates those the moment they do.
 */
const POLL = {
  rooms: 30_000,
  room: 30_000,
  agents: 30_000,
  members: 30_000,
  messages: 30_000,
  memories: 30_000,
  skills: 30_000,
  plan: 8_000,
  episodes: 5_000,
  coordination: 20_000,
} as const;

/** Messages are read here only to find who has posted; one page is plenty. */
const POSTER_LIMIT = 200;

// Stable empties: a fresh `[]` per render would break every downstream memo.
const NO_ROOMS: Room[] = [];
const NO_AGENTS: AgentSummary[] = [];
const NO_MEMBERS: PresenceMember[] = [];
const NO_POSTERS: string[] = [];
const NO_MEMORIES: Memory[] = [];
const NO_SKILLS: Skill[] = [];
const NO_EPISODES: EpisodeSummary[] = [];

type RoomResource =
  | "room"
  | "agents"
  | "members"
  | "messages"
  | "memories"
  | "skills"
  | "plan"
  | "episodes"
  | "integrity";

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
  const { data, isLoading, mutate } = useSWR("rooms", fetchRooms, {
    refreshInterval: opts.refreshInterval ?? POLL.rooms,
  });
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  return { rooms: data ?? NO_ROOMS, loading: isLoading, refresh };
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

/** Live presence: SLIM-connected members plus server-held `await` leases. */
export function useRoomMembers(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "members", fetchRoomMembers, NO_MEMBERS, POLL.members, opts,
  );
  return { members: data, loading, refresh };
}

/** Handles that have broadcast — reachable by `@` even when not present. */
export function useRoomPosters(room: string, opts: RoomQueryOptions = {}) {
  const { data, isLoading, mutate } = useSWR(
    room ? (["room", room, "messages", POSTER_LIMIT] as const) : null,
    () => fetchMessages(room, POSTER_LIMIT),
    { refreshInterval: opts.refreshInterval ?? POLL.messages },
  );
  const posters = useMemo(() => {
    if (!data) return NO_POSTERS;
    return data.messages
      .filter((m) => m.message_type === "broadcast")
      .map((m) => m.sender_handle ?? "")
      .filter(Boolean);
  }, [data]);
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  return { posters, loading: isLoading, refresh };
}

export function useRoomMemories(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "memories", fetchMemories, NO_MEMORIES, POLL.memories, opts,
  );
  return { memories: data, loading, refresh };
}

/** Not polled; memory writes revalidate the room. */
export function useRoomMemoryIntegrity(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "integrity", fetchMemoryIntegrity, null as MemoryLinksIntegrity | null, 0, opts,
  );
  return { integrity: data, loading, refresh };
}

export function useRoomSkills(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "skills", fetchSkills, NO_SKILLS, POLL.skills, opts,
  );
  return { skills: data, loading, refresh };
}

export function useRoomPlan(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "plan", fetchPlan, null as PlanResponse | null, POLL.plan, opts,
  );
  return { plan: data, loading, refresh };
}

export function useRoomEpisodes(room: string, opts: RoomQueryOptions = {}) {
  const { data, loading, refresh } = useRoomQuery(
    room, "episodes", fetchEpisodes, NO_EPISODES, POLL.episodes, opts,
  );
  return { episodes: data, loading, refresh };
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

/** A person in the room: an agent's owner, someone who has posted, someone
 *  present, or you. Never an agent — those are listed as agents. */
export interface RosterPerson {
  handle: string;
  /** Team slugs, unioned from the agents this person owns. */
  teams: string[];
  /** True when this is the handle the browser is acting as. */
  you: boolean;
  /** True when they own ≥1 agent here (vs. only having posted). */
  owns: boolean;
  presence?: PresenceMember;
}

export interface RoomRoster {
  agents: AgentSummary[];
  people: RosterPerson[];
  /** handle (lowercased) → presence, for badging a row live or awaiting. */
  presence: Map<string, PresenceMember>;
  loading: boolean;
  refresh: () => void;
}

/**
 * Everyone in a room, computed once: agents from the manifests, people from
 * agent owners ∪ posters ∪ present members ∪ you. The Members rail and the
 * composer's `@` popover are two views of this one answer.
 */
export function useRoomRoster(room: string, opts: RoomQueryOptions = {}): RoomRoster {
  const { agents, loading, refresh: refreshAgents } = useRoomAgents(room, opts);
  const { members, refresh: refreshMembers } = useRoomMembers(room, opts);
  const { posters, refresh: refreshPosters } = useRoomPosters(room, opts);
  const { principal } = useCurrentUser();
  const me = principal.trim().toLowerCase();

  const presence = useMemo(
    () => new Map(members.map((m) => [m.handle.toLowerCase(), m])),
    [members],
  );

  const people = useMemo(() => {
    const agentHandles = new Set(agents.map((a) => a.handle.toLowerCase()));
    const byHandle = new Map<string, RosterPerson>();
    const add = (raw: string, owns: boolean) => {
      const handle = raw.trim().replace(/^@/, "").toLowerCase();
      if (!handle || agentHandles.has(handle)) return;
      const existing = byHandle.get(handle);
      if (existing) {
        existing.owns = existing.owns || owns;
        return;
      }
      byHandle.set(handle, {
        handle,
        teams: [],
        you: handle === me,
        owns,
        presence: presence.get(handle),
      });
    };
    for (const a of agents) if (a.owner) add(a.owner, true);
    for (const p of posters) add(p, false);
    for (const m of members) add(m.handle, false);
    if (me) add(me, false);

    for (const person of byHandle.values()) {
      person.teams = [
        ...new Set(
          agents
            .filter((a) => (a.owner ?? "").toLowerCase() === person.handle && a.team)
            .map((a) => a.team as string),
        ),
      ];
    }
    return [...byHandle.values()].sort((x, y) => x.handle.localeCompare(y.handle));
  }, [agents, members, posters, presence, me]);

  const refresh = useCallback(() => {
    refreshAgents();
    refreshMembers();
    refreshPosters();
  }, [refreshAgents, refreshMembers, refreshPosters]);

  return { agents, people, presence, loading, refresh };
}
