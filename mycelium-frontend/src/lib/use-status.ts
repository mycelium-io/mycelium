// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import {
  fetchRoomAgents,
  fetchEpisodes,
  fetchPlan,
  fetchCollectorMetrics,
  type EpisodeSummary,
} from "@/lib/api";

export interface RoomStatus {
  agents: number | null;
  episodes: EpisodeSummary[] | null;
  openTasks: number | null;
}

/** Lightweight per-room counts for the status bar (polled, fail-soft). */
export function useRoomStatus(roomName: string): RoomStatus {
  const [agents, setAgents] = useState<number | null>(null);
  const [episodes, setEpisodes] = useState<EpisodeSummary[] | null>(null);
  const [openTasks, setOpenTasks] = useState<number | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetchRoomAgents(roomName).then(a => { if (!cancelled) setAgents(a.length); }).catch(() => {});
      fetchEpisodes(roomName).then(e => { if (!cancelled) setEpisodes(e); }).catch(() => {});
      fetchPlan(roomName).then(p => { if (!cancelled) setOpenTasks(p.open_count ?? 0); }).catch(() => {});
    };
    load();
    const t = setInterval(load, 8000);
    return () => { cancelled = true; clearInterval(t); };
  }, [roomName]);

  return { agents, episodes, openTasks };
}

export interface GlobalStatus {
  model: string | null;
  spend: number | null;
  healthy: boolean | null;
}

/** Global workspace status for the status bar: primary LLM model, spend, and
 *  backend health (polled slowly, fail-soft). */
export function useGlobalStatus(): GlobalStatus {
  const [model, setModel] = useState<string | null>(null);
  const [spend, setSpend] = useState<number | null>(null);
  const [healthy, setHealthy] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const col = await fetchCollectorMetrics();
        if (!cancelled && col) {
          const cost = col.counters?.cost_usd;
          setSpend(typeof cost?.total === "number" ? cost.total : null);
          // Primary model = the one that burned the most tokens.
          const byModel: Record<string, { total?: number }> = col.counters?.tokens?.by_model ?? {};
          let top: string | null = null;
          let max = -1;
          for (const [m, v] of Object.entries(byModel)) {
            const tot = v?.total ?? 0;
            if (tot > max) { max = tot; top = m; }
          }
          setModel(top);
        }
      } catch { /* fail-soft */ }
      try {
        const res = await fetch("/api/health", { cache: "no-store" });
        if (!cancelled) setHealthy(res.ok);
      } catch { if (!cancelled) setHealthy(false); }
    };
    load();
    const t = setInterval(load, 20_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return { model, spend, healthy };
}
