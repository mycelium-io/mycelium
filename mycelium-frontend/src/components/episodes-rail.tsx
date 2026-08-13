// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity } from "lucide-react";
import { fetchEpisodes, logFetchError, type EpisodeSummary } from "@/lib/api";
import { DetailDrawer } from "@/components/detail-drawer";
import { EmptyState } from "@/components/empty-state";
import { EpisodeDetail } from "@/components/episode-detail";

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
  const [selected, setSelected] = useState<EpisodeSummary | null>(null);

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
        <span className="text-label font-semibold text-text">Episodes</span>
        <span className="ml-auto text-micro text-muted-foreground tabular">
          {counts.total}
          {counts.live > 0 && <span className="text-accent"> · {counts.live} live</span>}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto py-1">
        {!loaded ? (
          <div className="px-4 py-8 text-center text-label text-muted-foreground">loading…</div>
        ) : episodes.length === 0 ? (
          <EmptyState
            size="sm"
            icon={Activity}
            title="No episodes yet"
            description="Summon the aligner to open a negotiation."
          />
        ) : (
          episodes.map((ep) => {
            const color = outcomeColor(ep);
            const live = isLive(ep);
            const state = ep.subkind ?? ep.outcome;
            return (
              <button
                key={ep.short_id}
                onClick={() => setSelected(ep)}
                className="flex w-full flex-col gap-1.5 px-4 py-2.5 text-left transition-colors hover:bg-hairline"
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`inline-block size-1.5 flex-shrink-0 rounded-full ${live ? "" : "opacity-60"}`}
                    style={{ background: color }}
                  />
                  <span
                    className="font-mono text-micro text-muted-foreground truncate"
                    title={ep.episode || ep.short_id}
                  >
                    {ep.short_id}
                  </span>
                  <span className="ml-auto text-micro text-muted-foreground tabular">{ep.message_count} msg</span>
                </div>
                <div className="flex items-center gap-2 pl-3.5">
                  <span
                    className="rounded px-1.5 py-0.5 text-micro font-medium capitalize"
                    style={{ color, background: `color-mix(in srgb, ${color} 12%, transparent)` }}
                  >
                    {state}
                  </span>
                  {ep.participants.length > 0 && (
                    <span className="text-micro text-muted-foreground truncate">
                      {ep.participants.join(", ")}
                    </span>
                  )}
                </div>
              </button>
            );
          })
        )}
      </div>

      <DetailDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected ? `episode ${selected.short_id}` : undefined}
        subtitle={selected?.topic}
      >
        {selected && <EpisodeDetail roomName={roomName} shortId={selected.short_id} />}
      </DetailDrawer>
    </div>
  );
}
