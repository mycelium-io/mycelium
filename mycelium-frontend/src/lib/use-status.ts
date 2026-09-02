// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import useSWR from "swr";
import { type EpisodeSummary } from "@/lib/api";
import { useRoomAgents, useRoomEpisodes, useRoomMemories } from "@/lib/room-data";

/** A `work/` row nobody has closed. The board's own definition of outstanding. */
function isOpenWork(memory: { key: string; meta?: Record<string, unknown> | null }): boolean {
  if (!memory.key.startsWith("work/")) return false;
  const status = memory.meta?.status;
  return status !== "resolved" && status !== "dismissed";
}

export interface RoomStatus {
  agents: number | null;
  episodes: EpisodeSummary[] | null;
  openTasks: number | null;
}

/** Lightweight per-room counts for the status bar. Reads the room's shared
 *  agent / episode / memory caches, so the bar costs no requests of its own and
 *  never disagrees with the rails showing the same numbers. `null` until the
 *  first read lands, so a count renders only once it means something. */
export function useRoomStatus(roomName: string): RoomStatus {
  const { agents, loading: agentsLoading } = useRoomAgents(roomName);
  const { episodes, loading: episodesLoading } = useRoomEpisodes(roomName);
  // Open work is counted off the same rows the board draws, so the bar and the
  // board can never disagree about how much is outstanding.
  const { memories, loading: memoriesLoading } = useRoomMemories(roomName);

  return {
    agents: agentsLoading ? null : agents.length,
    episodes: episodesLoading ? null : episodes,
    openTasks: memoriesLoading ? null : memories.filter(isOpenWork).length,
  };
}

export interface GlobalStatus {
  model: string | null;
  healthy: boolean | null;
}

/** The slice of `/health` the status bar reads: the hub answered at all, and
 *  which model its cognition is configured against. */
interface HubHealth {
  llm?: { model?: string | null } | null;
}

/** One `/health` read, shared by every caller. Resolves to `null` when the hub
 *  does not answer, which is what "backend unreachable" means on the bar. */
async function readHealth(): Promise<HubHealth | null> {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    if (!res.ok) return null;
    return (await res.json()) as HubHealth;
  } catch {
    return null;
  }
}

/** How often the status bar re-checks the hub. */
const HEALTH_POLL = 20_000;

function useHubHealth(refreshInterval: number) {
  return useSWR<HubHealth | null>("health", readHealth, { refreshInterval });
}

/** Is the hub answering? One shared cache entry (`health`) for every caller, so
 *  the status bar and the install panel agree and cost one request between
 *  them — the install panel just watches it faster while it waits for the hub
 *  to come up. `null` until the first probe lands. */
export function useBackendHealth(refreshInterval: number = HEALTH_POLL): boolean | null {
  const { data } = useHubHealth(refreshInterval);
  return data === undefined ? null : data !== null;
}

/** Global workspace status for the status bar: the configured cognition model
 *  and whether the hub is answering. Both come off the one shared `/health`
 *  entry, so the bar renders on every page for one request. */
export function useGlobalStatus(): GlobalStatus {
  const { data } = useHubHealth(HEALTH_POLL);
  return {
    model: data?.llm?.model ?? null,
    healthy: data === undefined ? null : data !== null,
  };
}
