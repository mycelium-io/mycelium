// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  Bell,
  BellOff,
  BellRing,
  Boxes,
  Check,
  Lock,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Search,
  SearchX,
  Trash2,
  type LucideIcon,
} from "lucide-react";
import { createRoom, type Room } from "@/lib/api";
import { useAppStream } from "@/lib/stream-hub";
import { useRooms } from "@/lib/room-data";
import { roomLevel, type RoomLevel } from "@/lib/notifications";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { usePrincipal } from "@/components/current-user";
import { CreateRoomDialog } from "@/components/create-room-dialog";
import { DeleteRoomDialog } from "@/components/delete-room-dialog";
import { useNotifications } from "@/components/notifications-provider";
import { EmptyState } from "@/components/empty-state";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Tooltip } from "@/components/ui/tooltip";
import { KeyBadge } from "@/components/key-badge";
import { RoomAvatar } from "@/components/ui/room-avatar";
import { useCommands, useKeyAction } from "@/components/keymap-provider";
import { useOpenInstallModal } from "@/components/install-modal";
import { chordFor, chordKey } from "@/lib/keymap";
import type { PaletteCommand } from "@/lib/commands";

/** "Collapse the rooms rail (⌥B)" — spelled into the title so the strip says
 *  how to get back without holding the reveal modifier first. */
function railToggleTitle(expanded: boolean): string {
  const chord = chordFor("rooms.toggle");
  const suffix = chord ? ` (${chordKey(chord)})` : "";
  return `${expanded ? "Collapse" : "Expand"} the rooms rail${suffix}`;
}

/** Which rooms the rail lists: all of them, or only the shared or private ones. */
type Scope = "all" | "shared" | "private";

const SCOPES: { scope: Scope; label: string }[] = [
  { scope: "all", label: "All" },
  { scope: "shared", label: "Shared" },
  { scope: "private", label: "Private" },
];

/** A private room is listed only for its owner and members; the hub has
 *  already filtered the list, so here it only decides where a room is drawn. */
export function isPrivateRoom(room: Room): boolean {
  return room.is_public === false;
}

interface Props {
  /** The room currently open, so its row is highlighted. Null on the home view. */
  activeRoom?: string | null;
  /** Draw the rail as a strip of room monograms rather than a list of names. */
  collapsed?: boolean;
  onCollapsedChange?: (collapsed: boolean) => void;
}

export function RoomsSidebar({ activeRoom = null, collapsed = false, onCollapsedChange }: Props) {
  const [query, setQuery] = useState("");
  const [scope, setScope] = useState<Scope>("all");
  const [showCreate, setShowCreate] = useState(false);
  const [creatingInline, setCreatingInline] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  // The rooms list is a shared cache entry that outlives this mount — the
  // sidebar sits inside each page's AppShell, so navigation remounts it, and a
  // warm cache paints the last-known rooms instead of flashing an empty rail.
  const { rooms, refresh } = useRooms();

  // Push keeps the list instant; the hook's slow poll is the fail-soft fallback
  // for a dropped connection.
  useAppStream((data) => {
    const msg = data as { type?: string };
    if (msg.type === "room_created" || msg.type === "room_deleted" || msg.type === "room_updated") refresh();
  });

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

  // The filter only earns its row once there is something private to filter.
  const hasPrivate = rooms.some(isPrivateRoom);
  const activeScope: Scope = hasPrivate ? scope : "all";

  // Filter by the query and scope, then order by recency (last active first) so
  // rooms with fresh activity float up — the same ordering the command palette
  // uses. Private rooms are drawn as their own group below the shared ones, and
  // the list is that concatenation, so ⌥1..9 and next/prev follow the screen.
  const { shared, mine } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const base = q ? rooms.filter(r => r.name.toLowerCase().includes(q)) : rooms;
    const recency = (r: Room) => r.last_activity ?? r.created_at ?? "";
    const sorted = [...base].sort((a, b) => recency(b).localeCompare(recency(a)));
    return {
      shared: activeScope === "private" ? [] : sorted.filter(r => !isPrivateRoom(r)),
      mine: activeScope === "shared" ? [] : sorted.filter(isPrivateRoom),
    };
  }, [rooms, query, activeScope]);
  const filtered = useMemo(() => [...shared, ...mine], [shared, mine]);

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

  const handleDeleted = useCallback(
    (roomName: string) => {
      refresh();
      if (roomName === activeRoom) router.push("/");
    },
    [activeRoom, refresh, router],
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

  const openInstallModal = useOpenInstallModal();

  // Every room by name, plus what this rail can reach. Rooms come from
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
      {
        id: "nav.machines",
        title: "Machines",
        group: "Navigate",
        keywords: ["runner", "computer", "agents", "start", "herdr"],
        run: () => router.push("/machines"),
      },
      {
        id: "nav.install",
        title: "Install the CLI",
        group: "Navigate",
        keywords: ["setup", "onboarding", "cli"],
        run: openInstallModal,
      },
    ],
    [rooms, go, router, openInstallModal],
  );
  useCommands(commands);

  // Collapsed: the same rail as a strip of room monograms — every room still
  // one click away, the filter and the names traded for the 48px the window
  // can spare. The dialogs stay mounted here so the create/notification flows
  // work from the strip too.
  if (collapsed) {
    return (
      <aside data-tour="rooms" className="flex w-full min-w-0 flex-col items-center overflow-hidden bg-surface/50">
        <Tooltip content={railToggleTitle(false)} side="right">
          <button
            onClick={() => onCollapsedChange?.(false)}
            aria-label={railToggleTitle(false)}
            className="relative mt-1 flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
          >
            <PanelLeftOpen className="size-3.5" />
            <KeyBadge action="rooms.toggle" overlay />
          </button>
        </Tooltip>
        <div className="mt-1 h-px w-5 bg-border" />

        <ScrollArea className="min-h-0 w-full flex-1">
          <nav className="flex flex-col items-center gap-1 py-2">
            {filtered.map((room, i) => {
              const active = room.name === activeRoom;
              const unread = active ? 0 : unreadByRoom.get(room.name) ?? 0;
              const label = isPrivateRoom(room) ? `${room.name} (private)` : room.name;
              return (
                <div key={room.name} className="flex flex-col items-center">
                  {i === shared.length && shared.length > 0 && (
                    <div aria-hidden className="mb-2 mt-1 h-px w-5 bg-border" />
                  )}
                  <div className="group/room relative">
                  <Tooltip
                    content={unread > 0 ? `${label} — ${unread} unread` : label}
                    side="right"
                  >
                    <Link
                      href={`/room/${encodeURIComponent(room.name)}`}
                      className="relative flex size-6 flex-shrink-0 items-center justify-center"
                    >
                      {active && (
                        <span
                          aria-hidden
                          className="absolute -left-2 top-1/2 h-4 w-0.5 -translate-y-1/2 rounded-full bg-accent"
                        />
                      )}
                      <RoomAvatar
                        name={room.name}
                        className="size-6 rounded text-[9px] hover:brightness-125"
                      />
                      <span className="sr-only">{room.name}</span>
                      {unread > 0 && (
                        <span
                          aria-label={`${unread} unread`}
                          className="absolute -right-0.5 -top-0.5 size-2 rounded-full bg-accent ring-2 ring-surface"
                        />
                      )}
                      {i < 9 && <KeyBadge chord={`alt+${i + 1}`} overlay />}
                    </Link>
                  </Tooltip>
                  <button
                    type="button"
                    aria-label={`Delete room ${room.name}`}
                    onClick={() => setDeleteTarget(room.name)}
                    className="absolute -right-1 -top-1 z-10 flex size-4 items-center justify-center rounded-full bg-elevated text-faint opacity-0 shadow transition-opacity hover:text-red group-hover/room:opacity-100"
                  >
                    <Trash2 className="size-2.5" />
                  </button>
                  </div>
                </div>
              );
            })}
          </nav>
        </ScrollArea>

        <Tooltip content="New room" side="right">
          <button
            onClick={() => setShowCreate(true)}
            aria-label="New room"
            className="mb-1 flex size-6 flex-shrink-0 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
          >
            <Plus className="size-3.5" />
          </button>
        </Tooltip>

        <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={refresh} />
        {deleteTarget && (
          <DeleteRoomDialog
            roomName={deleteTarget}
            open
            onClose={() => setDeleteTarget(null)}
            onDeleted={() => handleDeleted(deleteTarget)}
          />
        )}
      </aside>
    );
  }

  return (
    <aside data-tour="rooms" className="flex min-w-0 flex-1 flex-col overflow-hidden bg-surface/50">
      {/* A dock, as an editor draws one: a small header, then the list. The
          way home and who you are live in the title bar above it. */}
      <div className="mb-1 flex h-8 flex-shrink-0 items-center gap-2 border-b border-border bg-surface px-3">
        <span className="text-micro font-medium text-muted-foreground">Rooms</span>
        <span className="text-micro tabular text-muted-foreground">{rooms.length}</span>
        <Tooltip content="New room">
          <button
            // Here the name is typed where the room will appear, as an
            // editor's file tree does; the palette and home ask in a prompt.
            onClick={() => setCreatingInline(true)}
            aria-label="New room"
            className="ml-auto flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
          >
            <Plus className="size-4" />
          </button>
        </Tooltip>
        <Tooltip content={railToggleTitle(true)}>
          <button
            onClick={() => onCollapsedChange?.(true)}
            aria-label={railToggleTitle(true)}
            className="relative flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
          >
            <PanelLeftClose className="size-4" />
            <KeyBadge action="rooms.toggle" overlay />
          </button>
        </Tooltip>
      </div>
      <div className="px-2 pb-1">
        <div className="flex h-7 items-center gap-2 rounded px-1.5 transition-colors focus-within:bg-bg hover:bg-hairline">
          <Search className="size-3.5 flex-shrink-0 text-faint" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Filter rooms…"
            className="w-full bg-transparent text-label text-text placeholder:text-faint focus:outline-none"
          />
        </div>
        {hasPrivate && (
          <div role="radiogroup" aria-label="Show rooms" className="mt-1 flex gap-0.5 px-0.5">
            {SCOPES.map(({ scope: s, label }) => (
              <button
                key={s}
                type="button"
                role="radio"
                aria-checked={activeScope === s}
                onClick={() => setScope(s)}
                className={`flex h-5 items-center gap-1 rounded px-1.5 text-micro transition-colors ${
                  activeScope === s
                    ? "bg-hairline font-medium text-text"
                    : "text-muted-foreground hover:text-text"
                }`}
              >
                {s === "private" && <Lock className="size-2.5" />}
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      <ScrollArea className="min-h-0 flex-1">
        <nav className="px-2 pb-2">
        {creatingInline && (
          <InlineNewRoom
            private={activeScope === "private"}
            onCancel={() => setCreatingInline(false)}
            onCreated={name => {
              setCreatingInline(false);
              refresh();
              router.push(`/room/${encodeURIComponent(name)}`);
            }}
          />
        )}
        {filtered.length === 0 ? (
          creatingInline ? null : rooms.length === 0 ? (
            <EmptyState size="sm" icon={Boxes} title="No rooms yet" description="Create one with the + above." />
          ) : activeScope === "private" && !query.trim() ? (
            <EmptyState size="sm" icon={Lock} title="No private rooms" />
          ) : (
            <EmptyState size="sm" icon={SearchX} title="No matches" />
          )
        ) : (
          filtered.map((room, i) => {
            const active = room.name === activeRoom;
            const priv = isPrivateRoom(room);
            // The private group gets a heading where it starts, when it sits
            // below the shared rooms rather than being the whole list.
            const heading = priv && i === shared.length && shared.length > 0;
            // Don't badge the room you're already looking at — being here is
            // reading it. Elsewhere, unread activity draws the name brighter too.
            const unread = active ? 0 : unreadByRoom.get(room.name) ?? 0;
            const level = roomLevel(settings, room.name);
            return (
              <div key={room.name}>
              {heading && (
                <div className="mt-2 flex h-6 items-center gap-1.5 px-1.5 text-micro font-medium text-faint">
                  <Lock className="size-3" />
                  Private
                </div>
              )}
              <div className="group/room relative">
              <Link
                href={`/room/${encodeURIComponent(room.name)}`}
                className={`group flex h-7 items-center gap-2 rounded px-1.5 transition-colors ${
                  active ? "bg-hairline" : "hover:bg-hairline"
                }`}
              >
                <RoomAvatar name={room.name} className="size-[18px] rounded-[4px] text-[8px]">
                  {i < 9 && <KeyBadge chord={`alt+${i + 1}`} overlay />}
                </RoomAvatar>
                <span
                  className={`min-w-0 flex-1 truncate text-label ${
                    active || unread > 0
                      ? "font-medium text-text"
                      : "text-muted-foreground group-hover:text-text"
                  }`}
                >
                  {room.name}
                </span>
                {/* Every room here is private and nothing heads the group, so
                    the row says it. */}
                {priv && shared.length === 0 && activeScope === "all" && (
                  <Lock
                    aria-label="private"
                    className="size-3 flex-shrink-0 text-faint transition-opacity group-hover/room:opacity-0"
                  />
                )}
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
              <button
                type="button"
                aria-label={`Delete room ${room.name}`}
                onClick={() => setDeleteTarget(room.name)}
                className="pointer-events-none absolute right-9 top-1/2 flex size-5 -translate-y-1/2 items-center justify-center rounded text-muted-foreground opacity-0 transition-opacity hover:text-red group-hover/room:pointer-events-auto group-hover/room:opacity-100"
              >
                <Trash2 className="size-3.5" />
              </button>
              </div>
              </div>
            );
          })
        )}
        </nav>
      </ScrollArea>

      <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={refresh} />
      {deleteTarget && (
        <DeleteRoomDialog
          roomName={deleteTarget}
          open
          onClose={() => setDeleteTarget(null)}
          onDeleted={() => handleDeleted(deleteTarget)}
        />
      )}
    </aside>
  );
}

/**
 * A new room's row, typed into the list where the room will appear: Enter
 * creates it, Esc or clicking away leaves it. A name the hub refuses stays in
 * the field with the reason under it.
 */
function InlineNewRoom({
  private: isPrivate = false,
  onCancel,
  onCreated,
}: {
  /** Typed while the rail shows only private rooms, so that is what it makes. */
  private?: boolean;
  onCancel: () => void;
  onCreated: (name: string) => void;
}) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const principal = usePrincipal();

  const create = async () => {
    const clean = name.trim();
    if (!clean || busy) return;
    setBusy(true);
    setError(null);
    try {
      await createRoom({ name: clean, is_persistent: true, private: isPrivate, owner: principal });
      onCreated(clean);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't create the room");
      setBusy(false);
    }
  };

  return (
    <div className="mb-0.5">
      <div className="flex h-7 items-center gap-2 rounded bg-hairline px-1.5 ring-1 ring-border">
        <RoomAvatar name={name.trim() || "?"} className="size-[18px] rounded-[4px] text-[8px]" />
        <input
          autoFocus
          value={name}
          onChange={e => {
            setName(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={e => {
            if (e.key === "Enter") void create();
            if (e.key === "Escape") onCancel();
          }}
          onBlur={() => {
            if (!name.trim() && !busy) onCancel();
          }}
          placeholder={isPrivate ? "Private room name" : "Room name"}
          aria-label="New room name"
          spellCheck={false}
          className="min-w-0 flex-1 bg-transparent text-label text-text placeholder:text-faint focus:outline-none"
        />
      </div>
      {error && <p role="alert" className="px-1.5 pt-1 text-micro break-words text-red">{error}</p>}
    </div>
  );
}

const LEVEL_OPTIONS: { level: RoomLevel; label: string; hint: string; Icon: LucideIcon }[] = [
  { level: "all", label: "All messages", hint: "badge + bell + sound", Icon: BellRing },
  { level: "mentions", label: "Only mentions", hint: "badge; bell on @you", Icon: Bell },
  { level: "muted", label: "Muted", hint: "nothing", Icon: BellOff },
];

/** Discord-style notification level picker for one room. The trigger is always a
 *  bell — it's the notification control, not a readout of the level; the level
 *  lives in the menu it opens (and the row's own BellOff marks a muted room). */
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
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger
        aria-label={`Notifications for ${room}: ${level}`}
        onClick={(e) => e.preventDefault()}
        className="flex size-5 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-surface hover:text-text"
      >
        <Bell className="size-3.5" />
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
