// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchEpisodes, logFetchError, type EpisodeSummary } from "@/lib/api";

// The room's episodes at a glance: each convening of the aligner is one episode
// (a scoped, recorded negotiation on the room's channel). This rail lists them;
// the L9 inspector tab expands any one into its full causal envelope chain.

function outcomeColor(ep: EpisodeSummary): string {
  const state = ep.subkind ?? ep.outcome;
  if (state === "converged" || state === "resolved") return "var(--green)";
  if (state === "rejected") return "var(--yellow)";
  return "var(--accent)"; // open / in-progress
}

function isLive(ep: EpisodeSummary): boolean {
  const state = ep.subkind ?? ep.outcome;
  return state !== "converged" && state !== "resolved" && state !== "rejected";
}

interface EpisodesRailProps {
  roomName: string;
}

export function EpisodesRail({ roomName }: EpisodesRailProps) {
  const [episodes, setEpisodes] = useState<EpisodeSummary[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchEpisodes(roomName)
        .then((data) => {
          if (!cancelled) {
            setEpisodes(data);
            setLoaded(true);
          }
        })
        .catch((err) => {
          logFetchError("fetchEpisodes")(err);
          if (!cancelled) setLoaded(true);
        });
    load();
    const t = setInterval(load, 5000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, [roomName]);

  const counts = useMemo(() => {
    const live = episodes.filter(isLive).length;
    return { total: episodes.length, live };
  }, [episodes]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface/40">
      <div className="flex items-center gap-2 border-b border-border bg-paper px-4 py-2.5">
        <span className="caps-mono-sm text-muted">EPISODES</span>
        <span className="ml-auto text-micro text-muted tabular">
          {counts.total}
          {counts.live > 0 && <span className="text-accent"> · {counts.live} live</span>}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {!loaded ? (
          <div className="px-4 py-8 text-center caps-mono-sm text-muted italic">loading…</div>
        ) : episodes.length === 0 ? (
          <div className="px-4 py-8 text-center caps-mono-sm text-muted italic">no episodes yet</div>
        ) : (
          episodes.map((ep) => {
            const color = outcomeColor(ep);
            const live = isLive(ep);
            const state = ep.subkind ?? ep.outcome;
            return (
              <div key={ep.short_id} className="flex w-full flex-col gap-1 px-4 py-2 text-left">
                <div className="flex items-center gap-2">
                  <span
                    className={`square-dot filled ${live ? "pulse" : ""}`}
                    style={{ width: 6, height: 6, color }}
                  />
                  <span
                    className="font-mono text-label text-text2 truncate"
                    title={ep.episode || ep.short_id}
                  >
                    {ep.short_id}
                  </span>
                  <span className="ml-auto text-micro text-muted tabular">{ep.message_count} msg</span>
                </div>
                <div className="flex items-center gap-1.5 pl-3">
                  <span className="caps-mono-sm" style={{ color, fontSize: "var(--text-micro)" }}>
                    {state}
                  </span>
                  {ep.participants.length > 0 && (
                    <span className="text-micro text-muted truncate">
                      {ep.participants.join(", ")}
                    </span>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
