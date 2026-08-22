// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import { Activity } from "lucide-react";
import { fetchEpisode, type EpisodeSummary } from "@/lib/api";
import { useRoomEpisodes } from "@/lib/room-data";
import { DetailDrawer } from "@/components/detail-drawer";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";
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
  /** An episode short id to open, arrived at from search. */
  focusShortId?: string | null;
  onFocusConsumed?: () => void;
  /** Open an episode by short id (e.g. a clicked chat episode tag). The nonce
   *  makes a second click on the same tag a request of its own, so reopening a
   *  drawer you just closed works. */
  focusEpisode?: { shortId: string; nonce: number } | null;
}

export function EpisodesRail({
  roomName,
  focusShortId = null,
  onFocusConsumed,
  focusEpisode = null,
}: EpisodesRailProps) {
  const [selected, setSelected] = useState<EpisodeSummary | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const { episodes, loading } = useRoomEpisodes(roomName);

  // A clicked episode tag holds until the list can answer it; `focusEpisode`
  // changes identity only when the parent bumps the nonce.
  useEffect(() => {
    if (focusEpisode) setPending(focusEpisode.shortId);
  }, [focusEpisode]);

  const wanted = focusShortId ?? pending;

  // Open the named episode's drawer. The list is the primary source because an
  // episode still *running* has no `log/episodes/*` record yet — it exists only
  // in the moderator's lifecycle, which the list synthesizes and the detail
  // endpoint has nothing to serve for. The fetch is the fallback for a closed
  // episode sitting past the list's limit.
  useEffect(() => {
    if (!wanted) return;
    const known = episodes.find((ep) => ep.short_id === wanted);
    if (known) {
      // The selection outlives focusShortId, which is cleared once consumed.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSelected(known);
      setPending(null);
      onFocusConsumed?.();
      return;
    }
    if (loading) return;
    fetchEpisode(roomName, wanted).then((detail) => {
      if (detail) setSelected(detail);
      // Answered either way: a since-deleted episode leaves you in the room
      // rather than leaving the request pending forever.
      setPending(null);
      onFocusConsumed?.();
    });
  }, [roomName, wanted, episodes, loading, onFocusConsumed]);

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
        {loading ? (
          Array.from({ length: 3 }, (_, i) => (
            <div key={i} className="flex flex-col gap-1.5 px-4 py-2.5">
              <div className="flex items-center gap-2">
                <Skeleton className="size-1.5 flex-shrink-0 rounded-full" />
                <Skeleton className="h-2.5 w-20" />
                <Skeleton className="ml-auto h-2.5 w-10" />
              </div>
              <div className="pl-3.5">
                <Skeleton className="h-4 w-24 rounded" />
              </div>
            </div>
          ))
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
                  <Tooltip content={ep.episode || ep.short_id} side="left">
                    <span
                      className="font-mono text-micro text-muted-foreground truncate"
                      aria-description={ep.episode || ep.short_id}
                    >
                      {ep.short_id}
                    </span>
                  </Tooltip>
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
