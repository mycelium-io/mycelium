// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { BarChart3, Boxes, Plus, Search, SearchX } from "lucide-react";
import { fetchRooms, getAppEventsSSEUrl, type Room } from "@/lib/api";
import { CreateRoomDialog } from "@/components/create-room-dialog";
import { ThemeToggle } from "@/components/theme-toggle";
import { NotificationBell } from "@/components/notification-bell";
import { useNotifications } from "@/components/notifications-provider";
import { EmptyState } from "@/components/empty-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { KeyBadge } from "@/components/key-badge";
import { useCommands, useKeyAction, useKeyCapture, useKeyReveal } from "@/components/keymap-provider";
import { chordFor, hintLabels } from "@/lib/keymap";
import type { PaletteCommand } from "@/lib/commands";

// The sidebar lives inside each page's AppShell, so navigation remounts it. A
// module-level cache lets a fresh mount paint the last-known rooms immediately
// (no count flashing 100 → 0 → 100 while the refetch is in flight).
let roomsCache: Room[] = [];

/** Two-letter monogram from a room name (mirrors the agent avatars). */
function monogram(name: string): string {
  const parts = name.split(/[^a-z0-9]+/i).filter(Boolean);
  const s = parts.length >= 2 ? parts[0][0] + parts[1][0] : (parts[0] ?? name).slice(0, 2);
  return s.toUpperCase();
}

/** Below this, a hint keypress reads as a tap that latches the overlay open;
 *  above it, as a hold that peeks and closes on release. */
const HOLD_TO_PEEK_MS = 250;

interface Props {
  /** The room currently open, so its row is highlighted. Null on the home view. */
  activeRoom?: string | null;
}

/** Hint mode: labels for the rooms on screen, plus what's been typed so far. */
interface Hints {
  labels: string[];
  typed: string;
}

export function RoomsSidebar({ activeRoom = null }: Props) {
  const [rooms, setRooms] = useState<Room[]>(roomsCache);
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  // fetchRooms degrades to [] on failure (fire-and-forget list), so no
  // .catch is needed — a failed poll just leaves the last-known rooms in place.
  const load = () => fetchRooms().then((data) => { roomsCache = data; setRooms(roomsCache); });

  useEffect(() => {
    load();
    // Push keeps the list instant; the slow poll is a fail-soft fallback for a
    // dropped SSE connection.
    const t = setInterval(load, 30_000);

    let es: EventSource | undefined;
    let retry: ReturnType<typeof setTimeout>;
    function connect() {
      es = new EventSource(getAppEventsSSEUrl());
      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "room_created" || msg.type === "room_deleted") load();
        } catch {}
      };
      es.onerror = () => { es?.close(); retry = setTimeout(connect, 5000); };
    }
    connect();

    return () => { clearInterval(t); es?.close(); clearTimeout(retry); };
  }, []);

  // Unread activity per room, from the same client-side notification store the
  // bell reads — muted rooms don't count, so a muted room never wears a badge.
  const { notifications, settings } = useNotifications();
  const unreadByRoom = useMemo(() => {
    const m = new Map<string, number>();
    for (const n of notifications) {
      if (n.read || settings.mutedRooms.includes(n.room)) continue;
      m.set(n.room, (m.get(n.room) ?? 0) + 1);
    }
    return m;
  }, [notifications, settings.mutedRooms]);

  // Filter by the query, then order by recency (last active first) so rooms with
  // fresh activity float up — the same ordering the command palette uses.
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q ? rooms.filter(r => r.name.toLowerCase().includes(q)) : rooms;
    const recency = (r: Room) => r.last_activity ?? r.created_at ?? "";
    return [...base].sort((a, b) => recency(b).localeCompare(recency(a)));
  }, [rooms, query]);

  // ---- Keyboard navigation -------------------------------------------------
  // The rooms on screen are the switchable set, in the order they're listed: a
  // filtered sidebar switches among what it shows, so hint labels, the digit
  // fast path and next/prev all agree with what the user is looking at.
  const router = useRouter();
  const captureKeys = useKeyCapture();
  const [hints, setHints] = useState<Hints | null>(null);
  const hintsRef = useRef<Hints | null>(null);
  const roomsRef = useRef(filtered);
  const releaseKeys = useRef<(() => void) | null>(null);
  const hintKey = useRef<string>("");
  const hintOpenedAt = useRef(0);
  // The capture handler is installed once but reads live state; mirror it so it
  // never acts on the list or the typed prefix from an earlier render.
  useEffect(() => {
    hintsRef.current = hints;
    roomsRef.current = filtered;
  });

  const go = useCallback(
    (room: Room | undefined) => {
      if (room) router.push(`/room/${encodeURIComponent(room.name)}`);
    },
    [router],
  );

  const exitHints = useCallback(() => {
    releaseKeys.current?.();
    releaseKeys.current = null;
    setHints(null);
  }, []);

  // Hint mode owns the keyboard while it's up, so a label char is read as a
  // label and never as the binding it would otherwise fire.
  const onHintKey = useCallback(
    (e: KeyboardEvent) => {
      const current = hintsRef.current;
      if (!current) return;
      e.preventDefault();
      if (e.key === "Escape") {
        exitHints();
        return;
      }
      if (e.key === "Backspace") {
        setHints({ ...current, typed: current.typed.slice(0, -1) });
        return;
      }
      if (/^[1-9]$/.test(e.key)) {
        const room = roomsRef.current[Number(e.key) - 1];
        exitHints();
        go(room);
        return;
      }
      if (e.key.length !== 1) return;
      const typed = (current.typed + e.key).toLowerCase();
      const exact = current.labels.indexOf(typed);
      if (exact >= 0) {
        exitHints();
        go(roomsRef.current[exact]);
        return;
      }
      // A char that starts no label is a typo, not a jump: swallow it and
      // leave the overlay as it was.
      if (current.labels.some(l => l.startsWith(typed))) setHints({ ...current, typed });
    },
    [exitHints, go],
  );

  useKeyAction("rooms.hints", (sequence) => {
    if (filtered.length === 0) return;
    hintKey.current = sequence;
    hintOpenedAt.current = Date.now();
    setHints({ labels: hintLabels(filtered.length), typed: "" });
    releaseKeys.current = captureKeys(onHintKey);
  });

  // Hold-to-peek: releasing the hint key closes the overlay again, unless it
  // was a quick tap (latched open) or a label is already part-typed.
  useEffect(() => {
    if (!hints) return;
    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key !== hintKey.current) return;
      if (Date.now() - hintOpenedAt.current < HOLD_TO_PEEK_MS) return;
      if (hintsRef.current?.typed) return;
      exitHints();
    };
    window.addEventListener("keyup", onKeyUp);
    return () => window.removeEventListener("keyup", onKeyUp);
  }, [hints, exitHints]);

  useEffect(() => () => releaseKeys.current?.(), []);

  const cycle = useCallback(
    (delta: number) => {
      const list = roomsRef.current;
      if (list.length === 0) return;
      const at = list.findIndex(r => r.name === activeRoom);
      const next = at < 0 ? (delta > 0 ? 0 : list.length - 1) : (at + delta + list.length) % list.length;
      go(list[next]);
    },
    [activeRoom, go],
  );

  useKeyAction("rooms.next", () => cycle(1));
  useKeyAction("rooms.prev", () => cycle(-1));
  useKeyAction("rooms.digit", chord => go(filtered[Number(chord.split("+").pop()) - 1]));
  useKeyAction("nav.home", () => router.push("/"));

  // Every room by name, plus the two things this rail can do. Rooms come from
  // the full list, not the filtered one: the palette has a query of its own,
  // and a sidebar filter left set would silently hide rooms from it.
  const commands = useMemo<PaletteCommand[]>(
    () => [
      // Recency order (last_activity, falling back to created_at) so the palette,
      // which shows only the recent head at rest, leads with the rooms you're in.
      ...[...rooms]
        .sort((a, b) =>
          (b.last_activity ?? b.created_at ?? "").localeCompare(a.last_activity ?? a.created_at ?? ""),
        )
        .map(room => ({
          id: `room:${room.name}`,
          title: room.name,
          group: "Rooms",
          keywords: ["room", "switch", "open"],
          run: () => go(room),
        })),
      {
        id: "room.create",
        title: "Create a room",
        group: "Rooms",
        keywords: ["new", "add"],
        run: () => setShowCreate(true),
      },
      { id: "nav.metrics", title: "Metrics", group: "Navigate", run: () => router.push("/metrics") },
    ],
    [rooms, go, router],
  );
  useCommands(commands);

  // While the reveal modifier is held the first nine rooms wear their own digit;
  // `f` labels the whole list, which is the answer past nine.
  const revealed = useKeyReveal();
  const hintsChord = chordFor("rooms.hints");

  return (
    <aside data-tour="rooms" className="flex w-[236px] flex-shrink-0 flex-col border-r border-border bg-surface/50">
      {/* Brand */}
      <Link
        href="/"
        className="relative flex h-[52px] flex-shrink-0 items-center gap-2.5 border-b border-border px-4 transition-colors hover:bg-hairline"
      >
        <Image src="/logo.png" alt="Mycelium" width={20} height={20} className="translate-y-[2px] opacity-90" />
        {/* The badge pins to the wordmark, not the header row, so it has room
            to sit above the baseline instead of clipping at the top edge. */}
        <span className="relative">
          <span
            className="text-display leading-none text-text"
            style={{ fontFamily: "'Cormorant Garamond', Georgia, serif", fontStyle: "italic", fontWeight: 600 }}
          >
            mycelium
          </span>
          <KeyBadge action="nav.home" />
        </span>
      </Link>

      {/* Rooms header + search */}
      <div className="flex items-center gap-2 px-3 pt-3 pb-2">
        <span className="text-micro font-semibold uppercase tracking-wide text-muted-foreground">Rooms</span>
        <span className="text-micro tabular text-muted-foreground">{rooms.length}</span>
        <button
          onClick={() => setShowCreate(true)}
          aria-label="New room"
          title="New room"
          className="ml-auto flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
        >
          <Plus className="size-4" />
        </button>
      </div>
      <div className="px-3 pb-2">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-bg px-2.5 py-1.5 focus-within:border-accent">
          <Search className="size-3.5 flex-shrink-0 text-faint" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Filter rooms…"
            className="w-full bg-transparent text-label text-text placeholder:text-muted-foreground focus:outline-none"
          />
        </div>
      </div>

      {hints ? (
        <div role="status" aria-live="polite" className="px-3 pb-2 text-micro text-muted-foreground">
          Press a hint label to jump{hints.typed ? ` · ${hints.typed}…` : ""}
        </div>
      ) : (
        // Nine digits only go so far; say where the rest are while the badges
        // are on screen and the question is being asked.
        revealed && filtered.length > 9 && (
          <div className="px-3 pb-2 text-micro text-muted-foreground">
            <kbd className="font-sans">{hintsChord}</kbd> to label them all
          </div>
        )
      )}

      {/* Rooms list */}
      <ScrollArea className="min-h-0 flex-1">
        <nav className="px-2 pb-2">
        {filtered.length === 0 ? (
          rooms.length === 0 ? (
            <EmptyState size="sm" icon={Boxes} title="No rooms yet" description="Create one with the + above." />
          ) : (
            <EmptyState size="sm" icon={SearchX} title="No matches" />
          )
        ) : (
          filtered.map((room, i) => {
            const active = room.name === activeRoom;
            const label = hints?.labels[i];
            // Don't badge the room you're already looking at — being here is
            // reading it. Elsewhere, unread activity draws the name brighter too.
            const unread = active ? 0 : unreadByRoom.get(room.name) ?? 0;
            return (
              <Link
                key={room.name}
                href={`/room/${encodeURIComponent(room.name)}`}
                className={`group flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors ${
                  active ? "bg-elevated ring-1 ring-border" : "hover:bg-hairline"
                }`}
              >
                <span
                  className={`relative flex size-7 flex-shrink-0 items-center justify-center rounded-md font-mono text-micro font-semibold ${
                    active ? "bg-accent text-accent-fg" : "bg-surface text-muted-foreground group-hover:text-text"
                  }`}
                  aria-hidden
                >
                  {monogram(room.name)}
                  {i < 9 && <KeyBadge chord={`alt+${i + 1}`} overlay />}
                  {label && (
                    <span
                      data-hint={label}
                      className="absolute inset-0 flex items-center justify-center rounded-md bg-yellow font-mono text-micro font-bold text-bg motion-safe:animate-in motion-safe:fade-in-0"
                    >
                      {[...label].map((c, ci) => (
                        <span key={ci} className={ci < (hints?.typed.length ?? 0) ? "opacity-40" : undefined}>
                          {c}
                        </span>
                      ))}
                    </span>
                  )}
                </span>
                <span
                  className={`min-w-0 flex-1 truncate text-label ${
                    active || unread > 0
                      ? "font-medium text-text"
                      : "text-muted-foreground group-hover:text-text"
                  }`}
                >
                  {room.name}
                </span>
                {unread > 0 && (
                  <span
                    aria-label={`${unread} unread`}
                    className="flex h-4 min-w-4 flex-shrink-0 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold tabular leading-none text-accent-fg"
                  >
                    {unread > 9 ? "9+" : unread}
                  </span>
                )}
              </Link>
            );
          })
        )}
        </nav>
      </ScrollArea>

      {/* Footer */}
      <div className="flex items-center gap-1 border-t border-border px-3 py-2">
        <Link
          href="/metrics"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-label font-medium text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          <BarChart3 className="size-4" />
          Metrics
        </Link>
        <div className="ml-auto flex items-center gap-0.5">
          <NotificationBell />
          <ThemeToggle />
        </div>
      </div>

      <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={load} />
    </aside>
  );
}
