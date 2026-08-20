// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import useSWR from "swr";
import { fetchCollectorMetrics, type EpisodeSummary } from "@/lib/api";
import { useRoomAgents, useRoomEpisodes, useRoomPlan } from "@/lib/room-data";

/** The slice of the collector's metrics payload the status bar reads: total
 *  spend and per-model token totals (to find the primary model). */
interface CollectorSpendShape {
  counters?: {
    cost_usd?: { total?: number };
    tokens?: { by_model?: Record<string, { total?: number }> };
  };
}

export interface RoomStatus {
  agents: number | null;
  episodes: EpisodeSummary[] | null;
  openTasks: number | null;
}

/** Lightweight per-room counts for the status bar. Reads the room's shared
 *  agent / episode / plan caches, so the bar costs no requests of its own and
 *  never disagrees with the rails showing the same numbers. `null` until the
 *  first read lands, so a count renders only once it means something. */
export function useRoomStatus(roomName: string): RoomStatus {
  const { agents, loading: agentsLoading } = useRoomAgents(roomName);
  const { episodes, loading: episodesLoading } = useRoomEpisodes(roomName);
  const { plan } = useRoomPlan(roomName);

  return {
    agents: agentsLoading ? null : agents.length,
    episodes: episodesLoading ? null : episodes,
    openTasks: plan ? plan.open_count ?? 0 : null,
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

/** Global workspace status for the status bar: primary LLM model, spend, and
 *  backend health (polled slowly, fail-soft). The status bar renders on every
 *  page, so both reads are shared cache entries like the room ones. */
export function useGlobalStatus(): GlobalStatus {
  const { data: collector } = useSWR<CollectorSpendShape | null>(
    "collector-metrics",
    () => fetchCollectorMetrics<CollectorSpendShape>(),
    { refreshInterval: 20_000 },
  );
  const { data: healthy } = useSWR("health", probeHealth, { refreshInterval: 20_000 });

  const cost = collector?.counters?.cost_usd;
  return {
    model: primaryModel(collector ?? null),
    spend: typeof cost?.total === "number" ? cost.total : null,
    healthy: healthy ?? null,
  };
}
