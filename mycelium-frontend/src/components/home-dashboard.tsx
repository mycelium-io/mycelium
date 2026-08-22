// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { AlertTriangle, Boxes, Plus, Sparkles, Terminal } from "lucide-react";
import { EmptyState } from "@/components/empty-state";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { RoomAvatar } from "@/components/ui/room-avatar";
import { Monogram } from "@/components/ui/monogram";
import { CreateRoomDialog } from "@/components/create-room-dialog";
import { useOpenInstallModal } from "@/components/install-modal";
import { type EpisodeSummary, type Room } from "@/lib/api";
import { avatarTint } from "@/lib/avatar-color";
import { useRoomAgents, useRoomEpisodes, useRoomLatest, useRooms, type RoomQueryOptions } from "@/lib/room-data";
import { useBackendHealth } from "@/lib/use-status";

/** The rows read the shared caches but don't drive them: a list of rooms is a
 *  glance, not a watch. Opening a room is what starts watching it. */
const NO_POLL: RoomQueryOptions = { refreshInterval: 0 };

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

/** Onboarding escape hatch from a connected workspace: the install flow, for a
 *  second machine or an agent that still needs the CLI. */
function InstallLink() {
  const openInstallModal = useOpenInstallModal();
  return (
    <button
      type="button"
      onClick={openInstallModal}
      className="inline-flex items-center gap-1.5 text-label font-medium text-muted-foreground transition-colors hover:text-text"
    >
      <Terminal className="size-3.5" />
      Install the CLI
    </button>
  );
}

function relativeTime(iso: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const min = Math.floor((Date.now() - t) / 60_000);
  if (min < 1) return "now";
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  const d = Math.floor(hr / 24);
  if (d < 7) return `${d}d`;
  return new Date(iso).toISOString().slice(5, 10);
}

function episodeState(ep: EpisodeSummary): { label: string; color: string; live: boolean } {
  const state = ep.subkind ?? ep.outcome;
  if (state === "converged" || state === "resolved") return { label: "converged", color: "var(--green)", live: false };
  if (state === "rejected") return { label: "rejected", color: "var(--yellow)", live: false };
  return { label: "negotiating", color: "var(--accent)", live: true };
}

/** The landing view: every room as a conversation.
 *
 *  A room *is* a conversation — with agents rather than people, but the shape
 *  is the same — so this reads like an inbox: who is in it, what was last said,
 *  how long ago. It was a grid of stat cards, which answered "how many
 *  memories does this room have" (a question nobody opens a laptop with) and
 *  not "what happened while I was away". */
export function HomeDashboard() {
  const [showCreate, setShowCreate] = useState(false);
  const { rooms, loading, refresh } = useRooms();
  // Newest first, the way an inbox is read. The hub serves the list in its own
  // order, which is stable but says nothing about what moved while you were
  // away — and that is the only thing this page is for.
  const ordered = useMemo(
    () =>
      [...rooms].sort(
        (a, b) =>
          Date.parse(b.last_activity || b.created_at) - Date.parse(a.last_activity || a.created_at),
      ),
    [rooms],
  );
  // A room list read off an unreachable backend is empty rather than absent, so
  // the health probe, not the list, is what tells "nothing here yet" apart
  // from "nothing to talk to". This page is served by a hub, so an unreachable
  // backend is an operator problem, not something the viewer's own CLI can
  // fix. It's an error state, not onboarding.
  const disconnected = useBackendHealth() === false;

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl px-8 py-8">
        <header className="mb-5 flex flex-wrap items-start justify-between gap-x-4 gap-y-3">
          <div className="min-w-0">
            <h1 className="text-2xl font-semibold text-text">Command center</h1>
            <p className="mt-1 text-label text-muted-foreground">
              {disconnected ? "Hub unreachable." : "Your rooms. Open one to coordinate."}
            </p>
          </div>
          {!disconnected && (
            <div className="mt-1 flex flex-shrink-0 items-center gap-2">
              <RunSampleLink />
              <Button onClick={() => setShowCreate(true)}>
                <Plus className="size-4" />
                New room
              </Button>
            </div>
          )}
        </header>

        {disconnected ? (
          <div className="rounded-xl border border-dashed border-border2">
            <EmptyState
              icon={AlertTriangle}
              title="Hub unreachable"
              description="The hub isn't answering right now, so the CLI may not be able to connect."
            />
          </div>
        ) : loading ? (
          <div className="flex flex-col gap-1.5">
            {Array.from({ length: 4 }, (_, i) => (
              <RoomRowSkeleton key={i} />
            ))}
          </div>
        ) : rooms.length === 0 ? (
          <div className="rounded-xl border border-dashed border-border2">
            <EmptyState
              icon={Boxes}
              title="No rooms yet"
              description="Create your first coordination room, or run a guided sample to see it work."
              action={
                <div className="flex flex-col items-center gap-3">
                  <div className="flex items-center gap-2">
                    <Button onClick={() => setShowCreate(true)}>
                      <Plus className="size-4" />
                      New room
                    </Button>
                    <RunSampleLink />
                  </div>
                  <InstallLink />
                </div>
              }
            />
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {ordered.map(room => (
              <RoomRow key={room.name} room={room} />
            ))}
          </div>
        )}
      </div>

      <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={refresh} />
    </div>
  );
}

/** Loading placeholder mirroring a row's shape, so the list doesn't jump. */
function RoomRowSkeleton() {
  return (
    <div className="flex items-center gap-3.5 rounded-xl border border-border bg-paper px-4 py-3.5">
      <Skeleton className="size-10 flex-shrink-0 rounded-xl" />
      <div className="min-w-0 flex-1">
        <Skeleton className="h-3.5 w-40" />
        <Skeleton className="mt-2 h-2.5 w-3/5" />
      </div>
      <Skeleton className="h-6 w-20 rounded-full" />
    </div>
  );
}

/** How many faces the pile shows before it starts counting instead. */
const FACES = 4;

/** The room's agents as an overlapping pile of their own avatars. Says who is
 *  in the room, which is what a count of them never did. */
function FacePile({ handles }: { handles: string[] }) {
  if (handles.length === 0) return null;
  const shown = handles.slice(0, FACES);
  const rest = handles.length - shown.length;
  return (
    // Dropped on a phone, where it would squeeze the preview line to a few
    // characters — what was said matters more there than who is in the room.
    <span className="hidden flex-shrink-0 items-center sm:flex" aria-label={`${handles.length} agents`}>
      {shown.map(handle => (
        <span
          key={handle}
          // The ring cuts each face out of the one behind it, so it has to be
          // the row's own background — including the colour it hovers to.
          className="-ml-1.5 inline-block rounded-full ring-2 ring-paper first:ml-0 group-hover:ring-elevated"
        >
          <Monogram handle={handle} className="size-6 text-[10px]" />
        </span>
      ))}
      {rest > 0 && <span className="ml-1.5 text-micro tabular text-muted-foreground">+{rest}</span>}
    </span>
  );
}

function RoomRow({ room }: { room: Room }) {
  const { agents } = useRoomAgents(room.name, NO_POLL);
  const { episodes } = useRoomEpisodes(room.name, NO_POLL);
  const { latest, loading: latestLoading } = useRoomLatest(room.name, NO_POLL);

  const live = episodes.some(ep => episodeState(ep).live);
  const latestState = episodes[0] ? episodeState(episodes[0]) : null;
  // A room mid-negotiation outranks how its last one ended: that's the row you
  // came to this page to find.
  const state = live ? { label: "negotiating", color: "var(--accent)", live: true } : latestState;
  // The preview carries its own timestamp; the room's last-activity is the
  // standby for a room whose transcript has nothing readable in it.
  const stamp = relativeTime(latest?.at || room.last_activity || room.created_at);

  return (
    <Link
      href={`/room/${encodeURIComponent(room.name)}`}
      className="group flex items-center gap-3.5 rounded-xl border border-border bg-paper px-4 py-3.5 transition-colors hover:border-border2 hover:bg-elevated"
    >
      <RoomAvatar name={room.name} className="size-10 rounded-xl text-label" />

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="truncate text-ui font-medium text-text">{room.name}</span>
          {state?.live && (
            <span
              className="flex flex-shrink-0 items-center gap-1.5 text-micro"
              style={{ color: state.color }}
            >
              <span
                className="inline-block size-1.5 animate-pulse rounded-full"
                style={{ background: state.color }}
              />
              {state.label}
            </span>
          )}
          <span className="ml-auto flex-shrink-0 text-micro tabular text-faint">{stamp}</span>
        </div>

        <div className="mt-1 flex items-center gap-2">
          <span className="min-w-0 flex-1 truncate text-label text-muted-foreground">
            {latestLoading ? (
              <Skeleton className="inline-block h-2.5 w-48 align-middle" />
            ) : latest ? (
              <>
                {latest.sender && (
                  <span className="font-medium" style={{ color: avatarTint(latest.sender) }}>
                    {latest.sender}
                  </span>
                )}
                {latest.sender && <span className="text-faint"> · </span>}
                {latest.text}
              </>
            ) : (
              <span className="text-faint">No messages yet</span>
            )}
          </span>
          <FacePile handles={agents.map(a => a.handle)} />
        </div>
      </div>
    </Link>
  );
}
