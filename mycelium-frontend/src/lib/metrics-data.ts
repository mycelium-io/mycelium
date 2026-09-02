// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The reads behind the metrics screen, and the rollups drawn from them.
 *
 * Three sources, each of which the running stack actually produces:
 *
 *   `/api/observability`  the backend's in-process counters and histograms
 *                         (`app/services/metrics.py`) — memory, embeddings,
 *                         indexer, and Pi cognition calls.
 *   `/api/health`         the coordination fabric and the hub's posture, read
 *                         through the shared `useNetworkStatus` cache.
 *   the per-room episodes route  one record per convening of the aligner,
 *                         fanned out across the rooms the hub holds.
 *
 * Server state is SWR-keyed like every other read in the app, so the metrics
 * screen shares its `/health` entry with the Network rail and its room list
 * with the sidebar rather than opening reads of its own. The screen owns only
 * the cadence, which it passes down as `refreshInterval`.
 */

import useSWR from "swr";
import { fetchBackendMetrics, fetchEpisodes, type EpisodeSummary } from "@/lib/api";
import type { BackendHistogram } from "@/lib/metrics-format";

// ── Backend metrics ──────────────────────────────────────────────────────────

/**
 * The namespaces `app/services/metrics.py` files counters under. Each is a flat
 * `key -> number` map because the backend flattens dimensions into the key
 * (`by_operation.task_compile`), so the payload stays loose by design and
 * `subCounters` does the reading.
 */
export interface BackendCounters {
  memory?: Record<string, number>;
  embeddings?: Record<string, number>;
  indexer?: Record<string, number>;
  llm?: Record<string, number>;
}

export interface BackendMetrics {
  started_at?: string;
  updated_at?: string;
  counters?: BackendCounters;
  histograms?: Record<string, BackendHistogram>;
}

/** The backend counter snapshot. `null` means the hub did not answer — which the
 *  screen reports as unreachable rather than drawing zeros. */
export function useBackendMetrics(refreshInterval: number) {
  const { data, isLoading } = useSWR<BackendMetrics | null>(
    "backend-metrics",
    () => fetchBackendMetrics<BackendMetrics>(),
    { refreshInterval, keepPreviousData: true },
  );
  return { metrics: data ?? null, loading: isLoading };
}

// ── Episodes across the fleet ────────────────────────────────────────────────

/** An episode plus the room whose channel it convened on. */
export interface FleetEpisode extends EpisodeSummary {
  room: string;
}

/** How an episode ended. The commit subkind is authoritative when there is one;
 *  an episode with no commit envelope yet is still open. */
export function episodeState(ep: EpisodeSummary): string {
  return ep.subkind ?? ep.outcome;
}

export interface EpisodeRollup {
  total: number;
  converged: number;
  rejected: number;
  open: number;
  /** `work/` rows the agreements compiled into. */
  tasks: number;
  /** Mean distinct agents per episode, or null with nothing to average. */
  avgParticipants: number | null;
  /** Means over the episodes that carry L9 quality metrics — only converged
   *  episodes do, so `scored` is the honest denominator, not `total`. */
  scored: number;
  mpc: number | null;
  gar: number | null;
  scr: number | null;
  provenance: number | null;
  /** Newest first, for the short list on the panel. */
  recent: FleetEpisode[];
}

const EMPTY_ROLLUP: EpisodeRollup = {
  total: 0, converged: 0, rejected: 0, open: 0, tasks: 0,
  avgParticipants: null, scored: 0, mpc: null, gar: null, scr: null, provenance: null,
  recent: [],
};

function mean(values: number[]): number | null {
  if (values.length === 0) return null;
  return values.reduce((s, v) => s + v, 0) / values.length;
}

/** Roll a fleet's episodes up into the counts the panel draws. */
export function rollupEpisodes(episodes: FleetEpisode[]): EpisodeRollup {
  if (episodes.length === 0) return EMPTY_ROLLUP;
  const scored = episodes.filter((e) => e.metrics != null);
  const recent = [...episodes].sort((a, b) =>
    (b.updated_at ?? "").localeCompare(a.updated_at ?? ""),
  );
  const states = episodes.map(episodeState);
  return {
    total: episodes.length,
    converged: states.filter((s) => s === "converged" || s === "resolved").length,
    rejected: states.filter((s) => s === "rejected").length,
    open: states.filter((s) => s !== "converged" && s !== "resolved" && s !== "rejected").length,
    tasks: episodes.reduce((s, e) => s + (e.tasks?.length ?? 0), 0),
    avgParticipants: mean(episodes.map((e) => e.participants?.length ?? 0)),
    scored: scored.length,
    mpc: mean(scored.map((e) => e.metrics!.mpc)),
    gar: mean(scored.map((e) => e.metrics!.gar)),
    scr: mean(scored.map((e) => e.metrics!.scr)),
    provenance: mean(scored.map((e) => e.metrics!.provenance_weight)),
    recent,
  };
}

/**
 * Every room's episodes in one keyed read.
 *
 * The hub has no fleet-wide episode route, so this fans out over the rooms it
 * reports and tags each record with the room it came from. A room whose read
 * fails contributes nothing rather than failing the panel — a metrics screen
 * that goes blank because one room is unreadable is worse than one that is
 * short a room and says so through the counts.
 *
 * This is the one read on the page that costs a request per room, so it is
 * floored at `EPISODE_FLOOR_MS` however fast the screen is set to refresh — an
 * episode closes on the order of minutes, and a 5s cadence chosen to watch a
 * latency figure move should not turn into a fan-out at 5s. Pausing still stops
 * it outright.
 */
const EPISODE_FLOOR_MS = 15_000;

export function useFleetEpisodes(rooms: string[], refreshInterval: number) {
  const names = [...rooms].sort();
  const { data, isLoading } = useSWR<FleetEpisode[]>(
    names.length > 0 ? ["episodes-fleet", names.join(",")] : null,
    async () => {
      const lists = await Promise.all(
        names.map((room) =>
          fetchEpisodes(room)
            .then((eps) => eps.map((ep) => ({ ...ep, room })))
            .catch(() => [] as FleetEpisode[]),
        ),
      );
      return lists.flat();
    },
    {
      refreshInterval: refreshInterval === 0 ? 0 : Math.max(refreshInterval, EPISODE_FLOOR_MS),
      keepPreviousData: true,
    },
  );
  return {
    episodes: data ?? [],
    loading: names.length > 0 && isLoading,
  };
}
