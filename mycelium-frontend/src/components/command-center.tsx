// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Boxes, Sparkles } from "lucide-react";
import { EmptyState } from "@/components/empty-state";

// The seeded sample room the "Run a sample coordination" onboarding routes into.
const SAMPLE_TOUR_HREF = "/room/pricing-model?tour=1";

function RunSampleButton({ className = "" }: { className?: string }) {
  return (
    <Link
      href={SAMPLE_TOUR_HREF}
      className={`inline-flex items-center gap-2 rounded-md bg-accent px-3.5 py-2 text-label font-medium text-accent-fg transition-opacity hover:opacity-90 ${className}`}
    >
      <Sparkles className="size-4" />
      Run a sample coordination
    </Link>
  );
}
import {
  fetchRooms,
  fetchRoomAgents,
  fetchEpisodes,
  logFetchError,
  type EpisodeSummary,
} from "@/lib/api";

interface Room {
  name: string;
  created_at: string;
  is_persistent: boolean;
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

export function CommandCenter() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchRooms()
        .then((data: Room[]) => { if (!cancelled) { setRooms(data); setLoaded(true); } })
        .catch((e) => { logFetchError("fetchRooms")(e); if (!cancelled) setLoaded(true); });
    load();
    const t = setInterval(load, 10_000);
    return () => { cancelled = true; clearInterval(t); };
  }, []);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-5xl px-8 py-8">
        <header className="mb-6 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold text-text">Command center</h1>
            <p className="mt-1 text-label text-muted-foreground">
              Every coordination workspace, at a glance. Open one to negotiate, plan, and remember.
            </p>
          </div>
          <RunSampleButton className="mt-1 flex-shrink-0" />
        </header>

        {loaded && rooms.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border2">
            <EmptyState
              icon={Boxes}
              title="No rooms yet"
              description="See it work first: run a guided sample coordination, or create a room from the sidebar."
              action={<RunSampleButton />}
            />
          </div>
        ) : (
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {rooms.map(room => (
              <RoomCard key={room.name} room={room} />
            ))}
          </div>
        )}
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
          <div className="text-micro text-muted-foreground">{relativeTime(room.created_at)}</div>
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
