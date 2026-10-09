// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import {
  AlertTriangle,
  Command,
  Laptop,
  Plus,
  Search,
  Lock,
  Sparkles,
  SquareTerminal,
  Terminal,
  type LucideIcon,
} from "lucide-react";
import { Skeleton } from "@/components/ui/skeleton";
import { RoomAvatar } from "@/components/ui/room-avatar";
import { KbdChord } from "@/components/ui/kbd";
import { CreateRoomDialog } from "@/components/create-room-dialog";
import { useOpenInstallModal } from "@/components/install-modal";
import { useOpenSearch } from "@/components/global-search";
import { useOpenPalette } from "@/components/keymap-provider";
import { type EpisodeSummary, type Room } from "@/lib/api";
import { desktopMachine, terminalLink, useIsDesktop } from "@/lib/desktop";
import { useRoomEpisodes, useRoomLatest, useRooms, type RoomQueryOptions } from "@/lib/room-data";
import { useBackendHealth } from "@/lib/use-status";

/** The rows read the shared caches but don't drive them: a list of rooms is a
 *  glance, not a watch. Opening a room is what starts watching it. */
const NO_POLL: RoomQueryOptions = { refreshInterval: 0 };

/** The tour runs in a room, since a room is where nearly everything is: the one
 *  you were in last, so it points at your own work rather than a made-up one. */
function tourHref(room: string): string {
  return `/room/${encodeURIComponent(room)}?tour=1`;
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
  const when = new Date(iso);
  return when.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    ...(when.getFullYear() === new Date().getFullYear() ? {} : { year: "numeric" }),
  });
}

function episodeState(ep: EpisodeSummary): { label: string; color: string; live: boolean } {
  const state = ep.subkind ?? ep.outcome;
  if (state === "converged" || state === "resolved") return { label: "converged", color: "var(--green)", live: false };
  if (state === "rejected") return { label: "rejected", color: "var(--yellow)", live: false };
  return { label: "negotiating", color: "var(--accent)", live: true };
}

/** One line of the welcome list: what it does, and the key that does it too. */
function ActionRow({
  icon: Icon,
  label,
  action,
  onClick,
  href,
}: {
  icon: LucideIcon;
  label: string;
  action?: string;
  onClick?: () => void;
  href?: string;
}) {
  const cls =
    "flex h-8 w-full items-center gap-2.5 rounded px-2 text-label text-muted-foreground transition-colors hover:bg-hairline hover:text-text";
  const inner = (
    <>
      <Icon className="size-4 flex-shrink-0 text-faint" />
      <span className="flex-1 text-left">{label}</span>
      {action && <KbdChord size="xs" tone="muted" action={action} />}
    </>
  );
  // A link the app answers (`mycelium://`) is a plain anchor, not a route.
  if (href && !href.startsWith("/")) {
    return (
      <a href={href} className={cls}>
        {inner}
      </a>
    );
  }
  return href ? (
    <Link href={href} className={cls}>
      {inner}
    </Link>
  ) : (
    <button type="button" onClick={onClick} className={cls}>
      {inner}
    </button>
  );
}

/** A small label over a list, as the rest of the app draws one. */
function ListLabel({ children }: { children: React.ReactNode }) {
  return <h2 className="mb-1 px-2 text-micro font-medium text-faint">{children}</h2>;
}

/** The landing view, the way an editor opens: what you can start, then where
 *  things moved. The rooms themselves are in the sidebar; this lists them by
 *  what was last said in each, newest first, which the sidebar can't. */
export function HomeDashboard() {
  const openSearch = useOpenSearch();
  const openPalette = useOpenPalette();
  const desktop = useIsDesktop();
  const openInstallModal = useOpenInstallModal();
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
      <div className="mx-auto max-w-xl px-6 pt-16 pb-10">
        {/* The mark, the name, one line: stacked and centered, the way an
            editor greets you, above lists that read left to right. */}
        <header className="mb-10 flex flex-col items-center text-center">
          <Image src="/logo.png" alt="" width={40} height={40} className="opacity-90" />
          <h1
            className="mt-3 text-[40px] leading-none text-text"
            style={{ fontFamily: "'Cormorant Garamond', Georgia, serif", fontStyle: "italic", fontWeight: 600 }}
          >
            mycelium
          </h1>
          <p className="mt-2 text-label text-muted-foreground">
            {disconnected ? "The hub isn't answering." : "Rooms where people and agents work together."}
          </p>
        </header>

        {!disconnected && (
          <section className="mb-8">
            <ListLabel>Start</ListLabel>
            <ActionRow icon={Plus} label="New room" onClick={() => setShowCreate(true)} />
            <ActionRow icon={Search} label="Search everything" action="search.open" onClick={() => openSearch?.()} />
            <ActionRow icon={Command} label="All commands" action="palette.open" onClick={openPalette} />
            <ActionRow icon={Laptop} label={desktop ? `This ${desktopMachine()}'s agents` : "Machines"} href="/machines" />
            {desktop && <ActionRow icon={SquareTerminal} label="Agents terminal" href={terminalLink()} />}
            {/* With no room yet there is nothing to show around, so it starts one. */}
            {ordered.length > 0 ? (
              <ActionRow icon={Sparkles} label="Take a tour" href={tourHref(ordered[0].name)} />
            ) : (
              <ActionRow icon={Sparkles} label="Take a tour" onClick={() => setShowCreate(true)} />
            )}
            {!desktop && <ActionRow icon={Terminal} label="Install the CLI" onClick={openInstallModal} />}
          </section>
        )}

        {disconnected ? (
          <p className="flex items-start gap-2 px-2 text-label text-muted-foreground">
            <AlertTriangle className="mt-0.5 size-4 flex-shrink-0 text-yellow" />
            Nothing here can load until the hub answers again. It may be restarting; this page
            picks up on its own when it&apos;s back.
          </p>
        ) : loading ? (
          <section>
            <ListLabel>Recent</ListLabel>
            {Array.from({ length: 4 }, (_, i) => (
              <RoomRowSkeleton key={i} />
            ))}
          </section>
        ) : rooms.length === 0 ? (
          <p className="px-2 text-label text-muted-foreground">
            No rooms yet. Make one, and take the tour from inside it.
          </p>
        ) : (
          <section>
            <ListLabel>Recent</ListLabel>
            {ordered.map(room => (
              <RoomRow key={room.name} room={room} />
            ))}
          </section>
        )}
      </div>

      <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={refresh} />
    </div>
  );
}

/** Loading placeholder mirroring a row's shape, so the list doesn't jump. */
function RoomRowSkeleton() {
  return (
    <div className="flex h-9 items-center gap-2.5 px-2">
      <Skeleton className="size-[18px] flex-shrink-0 rounded" />
      <Skeleton className="h-2.5 w-24" />
      <Skeleton className="h-2.5 flex-1" />
    </div>
  );
}

function RoomRow({ room }: { room: Room }) {
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

  // One line per room: its name, whether it is mid-negotiation, what was last
  // said there, and when.
  return (
    <Link
      href={`/room/${encodeURIComponent(room.name)}`}
      className="flex h-9 items-center gap-2.5 rounded px-2 text-label transition-colors hover:bg-hairline"
    >
      <RoomAvatar name={room.name} className="size-[18px] rounded-[4px] text-[8px]" />
      <span className="flex-shrink-0 font-medium text-text">{room.name}</span>
      {room.is_public === false && <Lock aria-label="private" className="size-3 flex-shrink-0 text-faint" />}
      {state?.live && (
        <span
          aria-label={state.label}
          title={state.label}
          className="inline-block size-1.5 flex-shrink-0 animate-pulse rounded-full"
          style={{ background: state.color }}
        />
      )}
      <span className="min-w-0 flex-1 truncate text-muted-foreground">
        {latestLoading ? (
          <Skeleton className="inline-block h-2.5 w-40 align-middle" />
        ) : latest ? (
          <>
            {latest.sender && <span className="text-faint">{latest.sender}: </span>}
            {latest.text}
          </>
        ) : (
          <span className="text-faint">No messages yet</span>
        )}
      </span>
      <span className="flex-shrink-0 text-micro tabular text-faint">{stamp}</span>
    </Link>
  );
}
