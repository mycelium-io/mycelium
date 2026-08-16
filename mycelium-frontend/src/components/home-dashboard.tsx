// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Boxes, Plus, Sparkles } from "lucide-react";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { CreateRoomDialog } from "@/components/create-room-dialog";
import {
  fetchRooms,
  fetchRoomAgents,
  fetchEpisodes,
  type EpisodeSummary,
  type Room,
} from "@/lib/api";

// The seeded sample room the "Run a sample coordination" onboarding routes into.
const SAMPLE_TOUR_HREF = "/room/pricing-model?tour=1";

/** Secondary onboarding CTA: see it work before building anything. */
function RunSampleLink({ className = "" }: { className?: string }) {
  return (
    <Link
      href={SAMPLE_TOUR_HREF}
      className={`inline-flex h-8 items-center gap-2 rounded-md border border-border px-3.5 text-label font-medium text-text transition-colors hover:border-border2 hover:bg-surface ${className}`}
    >
      <Sparkles className="size-4 text-accent" />
      Run a sample
    </Link>
  );
}

function relativeTime(iso: string): string {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "-";
  const min = Math.floor((Date.now() - t) / 60_000);
  if (min < 1) return "just now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.floor(hr / 24);
  if (d === 1) return "yesterday";
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toISOString().slice(0, 10);
}

function monogram(name: string): string {
  const parts = name.split(/[^a-z0-9]+/i).filter(Boolean);
  const s = parts.length >= 2 ? parts[0][0] + parts[1][0] : (parts[0] ?? name).slice(0, 2);
  return s.toUpperCase();
}

function episodeState(ep: EpisodeSummary): { label: string; color: string; live: boolean } {
  const state = ep.subkind ?? ep.outcome;
  if (state === "converged" || state === "resolved") return { label: "converged", color: "var(--green)", live: false };
  if (state === "rejected") return { label: "rejected", color: "var(--yellow)", live: false };
  return { label: "live", color: "var(--accent)", live: true };
}

/** The landing view: every room as a card. Named for where it sits, not for the
 *  heading it wears — "command palette" and "command center" are two different
 *  things, and only one of them is a command surface. */
export function HomeDashboard() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [showCreate, setShowCreate] = useState(false);

  // fetchRooms degrades to [] on failure (fire-and-forget list), so no
  // .catch is needed — `loaded` still flips so the skeleton clears either way.
  const load = useCallback(
    () => fetchRooms().then((data) => { setRooms(data); setLoaded(true); }),
    [],
  );

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, [load]);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="px-8 py-8">
        <header className="mb-6 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold text-text">Command center</h1>
            <p className="mt-1 text-label text-muted-foreground">
              Every coordination workspace, at a glance. Open one to negotiate, plan, and remember.
            </p>
          </div>
          <div className="mt-1 flex flex-shrink-0 items-center gap-2">
            <RunSampleLink />
            <Button onClick={() => setShowCreate(true)}>
              <Plus className="size-4" />
              New room
            </Button>
          </div>
        </header>

        {!loaded ? (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <RoomCardSkeleton key={i} />
            ))}
          </div>
        ) : rooms.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border2">
            <EmptyState
              icon={Boxes}
              title="No rooms yet"
              description="Create your first coordination room, or run a guided sample to see it work."
              action={
                <div className="flex items-center gap-2">
                  <Button onClick={() => setShowCreate(true)}>
                    <Plus className="size-4" />
                    New room
                  </Button>
                  <RunSampleLink />
                </div>
              }
            />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {rooms.map(room => (
              <RoomCard key={room.name} room={room} />
            ))}
          </div>
        )}
      </div>

      <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={load} />
    </div>
  );
}

/** Loading placeholder mirroring RoomCard's layout, so the grid doesn't jump. */
function RoomCardSkeleton() {
  return (
    <div className="flex flex-col rounded-xl border border-border bg-paper p-4">
      <div className="flex items-center gap-3">
        <Skeleton className="size-9 flex-shrink-0 rounded-lg" />
        <div className="min-w-0 flex-1">
          <Skeleton className="h-3.5 w-2/3" />
          <Skeleton className="mt-1.5 h-2.5 w-1/3" />
        </div>
      </div>
      <div className="mt-4 flex items-center gap-4">
        <Skeleton className="h-2.5 w-14" />
        <Skeleton className="h-2.5 w-16" />
      </div>
    </div>
  );
}

function RoomCard({ room }: { room: Room }) {
  const [agentCount, setAgentCount] = useState<number | null>(null);
  const [episodes, setEpisodes] = useState<EpisodeSummary[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchRoomAgents(room.name)
      .then(a => { if (!cancelled) setAgentCount(a.length); })
      .catch(() => { if (!cancelled) setAgentCount(0); });
    fetchEpisodes(room.name)
      .then(e => { if (!cancelled) setEpisodes(e); })
      .catch(() => { if (!cancelled) setEpisodes([]); });
    return () => { cancelled = true; };
  }, [room.name]);

  const live = (episodes ?? []).map(episodeState).filter(s => s.live).length;
  const latest = (episodes ?? [])[0];
  const latestState = latest ? episodeState(latest) : null;

  return (
    <Link
      href={`/room/${encodeURIComponent(room.name)}`}
      className="group flex flex-col rounded-xl border border-border bg-paper p-4 transition-colors hover:border-border2 hover:bg-elevated"
    >
      <div className="flex items-center gap-3">
        <span
          className="flex size-9 flex-shrink-0 items-center justify-center rounded-lg bg-surface font-mono text-label font-semibold text-muted-foreground group-hover:text-text"
          aria-hidden
        >
          {monogram(room.name)}
        </span>
        <div className="min-w-0 flex-1">
          <div className="truncate text-ui font-medium text-text">{room.name}</div>
          <div className="text-micro text-muted-foreground">{relativeTime(room.last_activity ?? room.created_at)}</div>
        </div>
        {live > 0 && (
          <span className="flex items-center gap-1.5 text-micro text-accent">
            <span className="inline-block size-1.5 rounded-full bg-accent" />
            {live} live
          </span>
        )}
      </div>

      <div className="mt-4 flex items-center gap-4 text-micro text-muted-foreground">
        <span className="tabular">
          <span className="text-text">{agentCount ?? "-"}</span> agent{agentCount === 1 ? "" : "s"}
        </span>
        <span className="tabular">
          <span className="text-text">{episodes?.length ?? "-"}</span> episode{episodes?.length === 1 ? "" : "s"}
        </span>
        {latestState && !latestState.live && (
          <span className="ml-auto flex items-center gap-1.5 capitalize" style={{ color: latestState.color }}>
            <span className="inline-block size-1.5 rounded-full" style={{ background: latestState.color }} />
            {latestState.label}
          </span>
        )}
      </div>
    </Link>
  );
}
