// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import useSWR from "swr";
import { fetchCollectorMetrics, type EpisodeSummary } from "@/lib/api";
import { useRoomAgents, useRoomEpisodes, useRoomMemories } from "@/lib/room-data";

/** The slice of the collector's metrics payload the status bar reads: total
 *  spend and per-model token totals (to find the primary model). */
interface CollectorSpendShape {
  counters?: {
    cost_usd?: { total?: number };
    tokens?: { by_model?: Record<string, { total?: number }> };
  };
}

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
  spend: number | null;
  healthy: boolean | null;
}

/** Primary model = the one that burned the most tokens. */
function primaryModel(col: CollectorSpendShape | null): string | null {
  const byModel: Record<string, { total?: number }> = col?.counters?.tokens?.by_model ?? {};
  let top: string | null = null;
  let max = -1;
  for (const [m, v] of Object.entries(byModel)) {
    const total = v?.total ?? 0;
    if (total > max) { max = total; top = m; }
  }
  return top;
}

async function probeHealth(): Promise<boolean> {
  try {
    const res = await fetch("/api/health", { cache: "no-store" });
    return res.ok;
  } catch {
    return false;
  }
}

/** How often the status bar re-checks the hub. */
const HEALTH_POLL = 20_000;

/** Is the hub answering? One shared cache entry (`health`) for every caller, so
 *  the status bar and the install panel agree and cost one request between
 *  them — the install panel just watches it faster while it waits for the hub
 *  to come up. `null` until the first probe lands. */
export function useBackendHealth(refreshInterval: number = HEALTH_POLL): boolean | null {
  const { data } = useSWR("health", probeHealth, { refreshInterval });
  return data ?? null;
}

/** Global workspace status for the status bar: primary LLM model, spend, and
 *  backend health (polled slowly, fail-soft). The status bar renders on every
 *  page, so both reads are shared cache entries like the room ones. */
export function useGlobalStatus(): GlobalStatus {
  const { data: collector } = useSWR<CollectorSpendShape | null>(
    "collector-metrics",
    () => fetchCollectorMetrics<CollectorSpendShape>(),
    { refreshInterval: 20_000 },
  );
  const healthy = useBackendHealth();

  const cost = collector?.counters?.cost_usd;
  return {
    model: primaryModel(collector ?? null),
    spend: typeof cost?.total === "number" ? cost.total : null,
    healthy,
  };
}
