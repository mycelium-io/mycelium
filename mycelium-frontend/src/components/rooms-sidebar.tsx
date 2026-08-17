// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { AtSign, BarChart3, Bell, BellOff, Boxes, Check, Plus, Search, SearchX, type LucideIcon } from "lucide-react";
import { fetchRooms, getAppEventsSSEUrl, type Room } from "@/lib/api";
import { roomLevel, type RoomLevel } from "@/lib/notifications";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { CreateRoomDialog } from "@/components/create-room-dialog";
import { ThemeToggle } from "@/components/theme-toggle";
import { NotificationBell } from "@/components/notification-bell";
import { useNotifications } from "@/components/notifications-provider";
import { EmptyState } from "@/components/empty-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { KeyBadge } from "@/components/key-badge";
import { useCommands, useKeyAction } from "@/components/keymap-provider";
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

interface Props {
  /** The room currently open, so its row is highlighted. Null on the home view. */
  activeRoom?: string | null;
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
  // bell reads. Any non-muted message counts (broadcasts badge here even though
  // they never ring the bell); a muted room never wears a badge.
  const { notifications, settings, setRoomLevel, markRoomRead } = useNotifications();
  const unreadByRoom = useMemo(() => {
    const m = new Map<string, number>();
    for (const n of notifications) {
      if (n.read || roomLevel(settings, n.room) === "muted") continue;
      m.set(n.room, (m.get(n.room) ?? 0) + 1);
    }
    return m;
  }, [notifications, settings]);

  // Opening a room reads it — clear its badge (and its bell entries) on arrival.
  useEffect(() => {
    if (activeRoom) markRoomRead(activeRoom);
  }, [activeRoom, markRoomRead]);

  // Filter by the query, then order by recency (last active first) so rooms with
  // fresh activity float up — the same ordering the command palette uses.
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q ? rooms.filter(r => r.name.toLowerCase().includes(q)) : rooms;
    const recency = (r: Room) => r.last_activity ?? r.created_at ?? "";
    return [...base].sort((a, b) => recency(b).localeCompare(recency(a)));
  }, [rooms, query]);

  // ---- Keyboard navigation -------------------------------------------------
  // The rooms on screen are the switchable set, in the order they're listed, so
  // the digit fast path and next/prev agree with what the user is looking at.
  const router = useRouter();
  const roomsRef = useRef(filtered);
  useEffect(() => {
    roomsRef.current = filtered;
  });

  const go = useCallback(
    (room: Room | undefined) => {
      if (room) router.push(`/room/${encodeURIComponent(room.name)}`);
    },
    [router],
  );

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
            // Don't badge the room you're already looking at — being here is
            // reading it. Elsewhere, unread activity draws the name brighter too.
            const unread = active ? 0 : unreadByRoom.get(room.name) ?? 0;
            const level = roomLevel(settings, room.name);
            return (
              <div key={room.name} className="group/room relative">
              <Link
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
                    className="flex h-4 min-w-4 flex-shrink-0 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold tabular leading-none text-accent-fg transition-opacity group-hover/room:opacity-0"
                  >
                    {unread > 9 ? "9+" : unread}
                  </span>
                )}
                {unread === 0 && level === "muted" && (
                  <BellOff aria-label="muted" className="size-3 flex-shrink-0 text-faint transition-opacity group-hover/room:opacity-0" />
                )}
              </Link>
              {/* Discord-style per-room control, revealed on hover, overlaying the
                  badge slot. Outside the Link so it never navigates. */}
              <div className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 opacity-0 transition-opacity group-hover/room:pointer-events-auto group-hover/room:opacity-100">
                <RoomLevelMenu room={room.name} level={level} onSet={setRoomLevel} />
              </div>
              </div>
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

const LEVEL_OPTIONS: { level: RoomLevel; label: string; hint: string; Icon: LucideIcon }[] = [
  { level: "all", label: "All messages", hint: "badge + bell + sound", Icon: Bell },
  { level: "mentions", label: "Only mentions", hint: "badge; bell on @you", Icon: AtSign },
  { level: "muted", label: "Muted", hint: "nothing", Icon: BellOff },
];

/** Discord-style notification level picker for one room. The trigger wears the
 *  current level's glyph; the menu sets it. */
function RoomLevelMenu({
  room,
  level,
  onSet,
}: {
  room: string;
  level: RoomLevel;
  onSet: (room: string, level: RoomLevel) => void;
}) {
  const [open, setOpen] = useState(false);
  const Current = LEVEL_OPTIONS.find((o) => o.level === level)?.Icon ?? Bell;
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={`Notifications for ${room}: ${level}`}
        onClick={(e) => e.preventDefault()}
        className="flex size-5 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-surface hover:text-text"
      >
        <Current className="size-3.5" />
      </PopoverTrigger>
      <PopoverContent className="w-48 p-1">
        {LEVEL_OPTIONS.map(({ level: l, label, hint, Icon }) => (
          <button
            key={l}
            type="button"
            onClick={() => {
              onSet(room, l);
              setOpen(false);
            }}
            className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hairline"
          >
            <Icon className="size-3.5 flex-shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1">
              <span className="block text-label text-text">{label}</span>
              <span className="block text-micro text-muted-foreground">{hint}</span>
            </span>
            {level === l && <Check className="size-3.5 flex-shrink-0 text-accent" />}
          </button>
        ))}
      </PopoverContent>
    </Popover>
  );
}
