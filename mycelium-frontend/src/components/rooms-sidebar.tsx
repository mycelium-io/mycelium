// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  ArrowDown,
  ArrowRight,
  ArrowUp,
  Bell,
  BellOff,
  BellRing,
  Boxes,
  Check,
  ChevronRight,
  Copy,
  ExternalLink,
  Folder,
  FolderInput,
  FolderMinus,
  FolderOpen,
  FolderPlus,
  Link2,
  Lock,
  Pencil,
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
import { useRoomFolders, useRooms } from "@/lib/room-data";
import {
  addFolder,
  deleteFolder,
  folderOf,
  groupRooms,
  moveFolder,
  moveRoom,
  newFolderId,
  renameFolder,
  toggleFolder,
  type RoomFolder,
} from "@/lib/room-folders";
import { roomLevel, type RoomLevel } from "@/lib/notifications";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { usePrincipal } from "@/components/current-user";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuRadioGroup,
  ContextMenuRadioItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { copyText, absoluteUrl } from "@/lib/clipboard";
import { terminalLink, useIsDesktop } from "@/lib/desktop";
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

  // Your folders, yours alone: how you've filed rooms, not how the rooms are.
  const { layout, update: updateFolders } = useRoomFolders();
  const [creatingFolder, setCreatingFolder] = useState(false);
  const [renamingFolder, setRenamingFolder] = useState<string | null>(null);
  const [newRoomIn, setNewRoomIn] = useState<string | null>(null);
  const [dropTarget, setDropTarget] = useState<string | null>(null);
  const searching = query.trim().length > 0;

  // Filter by the query and scope, then order by recency (last active first) so
  // rooms with fresh activity float up — the same ordering the command palette
  // uses. Your folders come first, in your order; the rooms filed in none
  // follow, with the private ones as their own group below the shared ones.
  // The list is that concatenation, so ⌥1..9 and next/prev follow the screen.
  const { groups, shared, mine } = useMemo(() => {
    const q = query.trim().toLowerCase();
    const scoped = rooms.filter(r =>
      activeScope === "private" ? isPrivateRoom(r) : activeScope === "shared" ? !isPrivateRoom(r) : true,
    );
    const base = q ? scoped.filter(r => r.name.toLowerCase().includes(q)) : scoped;
    const recency = (r: Room) => r.last_activity ?? r.created_at ?? "";
    const sorted = [...base].sort((a, b) => recency(b).localeCompare(recency(a)));
    const { groups, loose } = groupRooms(sorted, layout);
    return {
      // While narrowing the list, a folder with nothing to show gets out of the way.
      groups: q || activeScope !== "all" ? groups.filter(g => g.rooms.length > 0) : groups,
      shared: loose.filter(r => !isPrivateRoom(r)),
      mine: loose.filter(isPrivateRoom),
    };
  }, [rooms, query, activeScope, layout]);
  // A folded folder hides its rooms, except from a search.
  const filtered = useMemo(
    () => [...groups.flatMap(g => (g.folder.collapsed && !searching ? [] : g.rooms)), ...shared, ...mine],
    [groups, shared, mine, searching],
  );
  // The strip has no folds to hide behind, so every room in it is reachable.
  const stripRooms = useMemo(() => [...groups.flatMap(g => g.rooms), ...shared, ...mine], [groups, shared, mine]);
  const onScreen = collapsed ? stripRooms : filtered;
  const indexOf = useMemo(() => new Map(onScreen.map((r, i) => [r.name, i])), [onScreen]);

  // ---- Keyboard navigation -------------------------------------------------
  // The rooms on screen are the switchable set, in the order they're listed, so
  // the digit fast path and next/prev agree with what the user is looking at.
  const router = useRouter();
  const roomsRef = useRef(onScreen);
  useEffect(() => {
    roomsRef.current = onScreen;
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
  useKeyAction("rooms.digit", chord => go(onScreen[Number(chord.split("+").pop()) - 1]));
  useKeyAction("nav.home", () => router.push("/"));

  const openInstallModal = useOpenInstallModal();
  const desktop = useIsDesktop();

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
      {
        id: "room.folder",
        title: "Create a folder for rooms",
        group: "Rooms",
        keywords: ["new", "group", "organize", "sidebar"],
        run: () => {
          onCollapsedChange?.(false);
          setCreatingFolder(true);
        },
      },
      { id: "nav.metrics", title: "Metrics", group: "Navigate", run: () => router.push("/metrics") },
      {
        id: "nav.machines",
        title: "Machines",
        group: "Navigate",
        keywords: ["runner", "computer", "agents", "start", "herdr"],
        run: () => router.push("/machines"),
      },
      ...(desktop
        ? [
            {
              id: "nav.terminal",
              title: "Open the agents terminal",
              group: "Navigate",
              keywords: ["terminal", "herdr", "pane", "agents", "shell"],
              run: () => {
                window.location.href = terminalLink();
              },
            },
          ]
        : []),
      {
        id: "nav.install",
        title: "Install the CLI",
        group: "Navigate",
        keywords: ["setup", "onboarding", "cli"],
        run: openInstallModal,
      },
    ],
    [rooms, go, router, openInstallModal, onCollapsedChange, desktop],
  );
  useCommands(commands);

  // What a room row's menu needs to file it, shared by the list and the strip.
  const fileRoom = {
    folders: layout.folders,
    onMove: (room: string, to: string | null) => updateFolders(l => moveRoom(l, room, to)),
    onNewFolder: (room: string) => {
      const id = newFolderId();
      updateFolders(l => moveRoom(addFolder(l, "New folder", id), room, id));
      onCollapsedChange?.(false);
      setRenamingFolder(id);
    },
  };

  /** One room's row in the list. `markPrivate` puts the lock on the row itself,
   *  where no Private heading above it says so already. */
  const row = (room: Room, markPrivate: boolean) => {
    const active = room.name === activeRoom;
    const i = indexOf.get(room.name) ?? -1;
    // Don't badge the room you're already looking at — being here is
    // reading it. Elsewhere, unread activity draws the name brighter too.
    const unread = active ? 0 : unreadByRoom.get(room.name) ?? 0;
    const level = roomLevel(settings, room.name);
    return (
      <RoomContextMenu
        key={room.name}
        room={room}
        level={level}
        onSetLevel={setRoomLevel}
        onOpen={() => go(room)}
        onDelete={() => setDeleteTarget(room.name)}
        {...fileRoom}
      >
        <div className="group/room relative">
          <Link
            href={`/room/${encodeURIComponent(room.name)}`}
            // Dragged onto a folder to file it there.
            onDragStart={e => {
              e.dataTransfer.setData(ROOM_DRAG, room.name);
              e.dataTransfer.effectAllowed = "move";
            }}
            onDragEnd={() => setDropTarget(null)}
            className={`group flex h-7 items-center gap-2 rounded px-1.5 transition-colors ${
              active ? "bg-hairline" : "hover:bg-hairline"
            }`}
          >
            <RoomAvatar name={room.name} className="size-[18px] rounded-[4px] text-[8px]">
              {i >= 0 && i < 9 && <KeyBadge chord={`alt+${i + 1}`} overlay />}
            </RoomAvatar>
            <span
              className={`min-w-0 flex-1 truncate text-label ${
                active || unread > 0 ? "font-medium text-text" : "text-muted-foreground group-hover:text-text"
              }`}
            >
              {room.name}
            </span>
            {markPrivate && isPrivateRoom(room) && (
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
          {/* Discord-style per-room controls, revealed on hover, overlaying the
              badge slot. Outside the Link so they never navigate. The backing
              blurs and fades in from the left, so a long name runs under the
              icons and fades out rather than showing through them. */}
          <div className="pointer-events-none absolute inset-y-0 right-0 flex items-center gap-2 rounded-r pl-6 pr-2 opacity-0 backdrop-blur-[2px] transition-opacity [background:linear-gradient(var(--hairline),var(--hairline)),color-mix(in_srgb,var(--surface)_50%,var(--bg))] [mask-image:linear-gradient(to_right,transparent,black_1.5rem)] group-hover/room:pointer-events-auto group-hover/room:opacity-100">
            <button
              type="button"
              aria-label={`Delete room ${room.name}`}
              onClick={() => setDeleteTarget(room.name)}
              className="flex size-5 items-center justify-center rounded text-muted-foreground transition-colors hover:text-red"
            >
              <Trash2 className="size-3.5" />
            </button>
            <RoomLevelMenu room={room.name} level={level} onSet={setRoomLevel} />
          </div>
        </div>
      </RoomContextMenu>
    );
  };

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
            {stripRooms.map((room, i) => {
              const active = room.name === activeRoom;
              const unread = active ? 0 : unreadByRoom.get(room.name) ?? 0;
              const label = isPrivateRoom(room) ? `${room.name} (private)` : room.name;
              // A rule where one group of the list ends and the next begins:
              // a folder, the rooms filed nowhere, the private ones.
              const section = (r: Room) =>
                folderOf(layout, r.name)?.id ?? (isPrivateRoom(r) ? "private" : "shared");
              const breaks = i > 0 && section(stripRooms[i - 1]) !== section(room);
              return (
                <div key={room.name} className="flex flex-col items-center">
                  {breaks && <div aria-hidden className="mb-2 mt-1 h-px w-5 bg-border" />}
                  <RoomContextMenu
                    room={room}
                    level={roomLevel(settings, room.name)}
                    onSetLevel={setRoomLevel}
                    onOpen={() => go(room)}
                    onDelete={() => setDeleteTarget(room.name)}
                    {...fileRoom}
                  >
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
                  </RoomContextMenu>
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
        {/* A room or a folder. Either way the name is typed where it will
            appear, as an editor's file tree does; the palette and home ask
            in a prompt. */}
        <AddMenu
          onRoom={() => setCreatingInline(true)}
          onFolder={() => setCreatingFolder(true)}
        />
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
        {creatingFolder && (
          <InlineNewFolder
            onCancel={() => setCreatingFolder(false)}
            onCreate={name => {
              setCreatingFolder(false);
              updateFolders(l => addFolder(l, name));
            }}
          />
        )}
        {groups.map(({ folder, rooms: filed }) => {
          const open = !folder.collapsed || searching;
          return (
            <DropZone
              key={folder.id}
              id={folder.id}
              active={dropTarget === folder.id}
              onHover={setDropTarget}
              onDropRoom={room => updateFolders(l => moveRoom(l, room, folder.id))}
              className="mb-0.5"
            >
              <FolderHeader
                folder={folder}
                count={filed.length}
                open={open}
                renaming={renamingFolder === folder.id}
                onToggle={() => updateFolders(l => toggleFolder(l, folder.id))}
                onRename={name => {
                  setRenamingFolder(null);
                  updateFolders(l => renameFolder(l, folder.id, name));
                }}
                onStartRename={() => setRenamingFolder(folder.id)}
                onCancelRename={() => setRenamingFolder(null)}
                onNewRoom={() => {
                  if (folder.collapsed) updateFolders(l => toggleFolder(l, folder.id));
                  setNewRoomIn(folder.id);
                }}
                onMove={delta => updateFolders(l => moveFolder(l, folder.id, delta))}
                onDelete={() => updateFolders(l => deleteFolder(l, folder.id))}
              />
              {open && (
                <div className="ml-3 border-l border-border pl-1">
                  {newRoomIn === folder.id && (
                    <InlineNewRoom
                      private={activeScope === "private"}
                      onCancel={() => setNewRoomIn(null)}
                      onCreated={name => {
                        setNewRoomIn(null);
                        updateFolders(l => moveRoom(l, name, folder.id));
                        refresh();
                        router.push(`/room/${encodeURIComponent(name)}`);
                      }}
                    />
                  )}
                  {filed.map(room => row(room, true))}
                  {filed.length === 0 && newRoomIn !== folder.id && (
                    <p className="flex h-7 items-center px-1.5 text-micro text-faint">Drag rooms here</p>
                  )}
                </div>
              )}
            </DropZone>
          );
        })}
        <DropZone
          id=""
          active={dropTarget === "" && layout.folders.length > 0}
          onHover={setDropTarget}
          onDropRoom={room => updateFolders(l => moveRoom(l, room, null))}
          className={groups.length > 0 ? "mt-1 min-h-7" : ""}
        >
          {filtered.length === 0 && groups.length === 0 ? (
            creatingInline || creatingFolder ? null : rooms.length === 0 ? (
              <EmptyState size="sm" icon={Boxes} title="No rooms yet" description="Create one with the + above." />
            ) : activeScope === "private" && !query.trim() ? (
              <EmptyState size="sm" icon={Lock} title="No private rooms" />
            ) : (
              <EmptyState size="sm" icon={SearchX} title="No matches" />
            )
          ) : (
            <>
              {shared.map(room => row(room, false))}
              {mine.length > 0 && (shared.length > 0 || groups.length > 0) && (
                <div className="mt-2 flex h-6 items-center gap-1.5 px-1.5 text-micro font-medium text-faint">
                  <Lock className="size-3" />
                  Private
                </div>
              )}
              {/* A private room says so on its own row wherever no heading
                  above it already does. */}
              {mine.map(room => row(room, shared.length === 0 && groups.length === 0 && activeScope === "all"))}
            </>
          )}
        </DropZone>
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

/** The drag payload a room row carries, so a drop knows it is a room. */
const ROOM_DRAG = "application/x-mycelium-room";

/** The header's +: a room, or a folder to put rooms in. */
function AddMenu({ onRoom, onFolder }: { onRoom: () => void; onFolder: () => void }) {
  const [open, setOpen] = useState(false);
  const item =
    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-label text-text transition-colors hover:bg-hairline";
  const pick = (run: () => void) => () => {
    setOpen(false);
    run();
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <Tooltip content="New room or folder">
        <PopoverTrigger
          aria-label="New room or folder"
          className="ml-auto flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text data-[popup-open]:bg-surface data-[popup-open]:text-text"
        >
          <Plus className="size-4" />
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent align="end" className="w-44 p-1">
        <button type="button" onClick={pick(onRoom)} className={item}>
          <Plus className="size-3.5 text-muted-foreground" />
          New room
        </button>
        <button type="button" onClick={pick(onFolder)} className={item}>
          <FolderPlus className="size-3.5 text-muted-foreground" />
          New folder
        </button>
      </PopoverContent>
    </Popover>
  );
}

/** A name typed in place: Enter keeps it, Esc (or leaving it empty) doesn't. */
function NameField({
  initial = "",
  placeholder,
  label,
  onSubmit,
  onCancel,
}: {
  initial?: string;
  placeholder: string;
  label: string;
  onSubmit: (name: string) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(initial);
  const submit = () => (name.trim() ? onSubmit(name.trim()) : onCancel());
  return (
    <input
      autoFocus
      value={name}
      onChange={e => setName(e.target.value)}
      onFocus={e => e.currentTarget.select()}
      onKeyDown={e => {
        if (e.key === "Enter") submit();
        if (e.key === "Escape") onCancel();
      }}
      onBlur={submit}
      placeholder={placeholder}
      aria-label={label}
      spellCheck={false}
      className="min-w-0 flex-1 bg-transparent text-label text-text placeholder:text-faint focus:outline-none"
    />
  );
}

function InlineNewFolder({ onCreate, onCancel }: { onCreate: (name: string) => void; onCancel: () => void }) {
  return (
    <div className="mb-0.5 flex h-7 items-center gap-2 rounded bg-hairline px-1.5 ring-1 ring-border">
      <Folder className="size-3.5 flex-shrink-0 text-muted-foreground" />
      <NameField placeholder="Folder name" label="New folder name" onSubmit={onCreate} onCancel={onCancel} />
    </div>
  );
}

/**
 * Where a dragged room can land: a folder, to file it there, or the rest of
 * the list, to take it out of its folder. Only a room's drag is accepted.
 */
function DropZone({
  id,
  active,
  onHover,
  onDropRoom,
  className = "",
  children,
}: {
  id: string;
  active: boolean;
  onHover: (id: string | null) => void;
  onDropRoom: (room: string) => void;
  className?: string;
  children: React.ReactNode;
}) {
  const carriesRoom = (e: React.DragEvent) => e.dataTransfer.types.includes(ROOM_DRAG);
  return (
    <div
      onDragOver={e => {
        if (!carriesRoom(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        onHover(id);
      }}
      onDragLeave={e => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) onHover(null);
      }}
      onDrop={e => {
        const room = e.dataTransfer.getData(ROOM_DRAG);
        onHover(null);
        if (!room) return;
        e.preventDefault();
        onDropRoom(room);
      }}
      className={`rounded transition-colors ${active ? "bg-accent-soft ring-1 ring-accent/40" : ""} ${className}`}
    >
      {children}
    </div>
  );
}

/** A folder's row: click to fold it, double-click (or its menu) to rename it. */
function FolderHeader({
  folder,
  count,
  open,
  renaming,
  onToggle,
  onRename,
  onStartRename,
  onCancelRename,
  onNewRoom,
  onMove,
  onDelete,
}: {
  folder: RoomFolder;
  count: number;
  open: boolean;
  renaming: boolean;
  onToggle: () => void;
  onRename: (name: string) => void;
  onStartRename: () => void;
  onCancelRename: () => void;
  onNewRoom: () => void;
  onMove: (delta: -1 | 1) => void;
  onDelete: () => void;
}) {
  if (renaming) {
    return (
      <div className="flex h-7 items-center gap-1.5 rounded bg-hairline px-1.5 ring-1 ring-border">
        <Folder className="size-3.5 flex-shrink-0 text-muted-foreground" />
        <NameField
          initial={folder.name}
          placeholder="Folder name"
          label="Folder name"
          onSubmit={onRename}
          onCancel={onCancelRename}
        />
      </div>
    );
  }
  const Icon = open ? FolderOpen : Folder;
  return (
    <ContextMenu>
      <ContextMenuTrigger>
        <button
          type="button"
          onClick={onToggle}
          onDoubleClick={onStartRename}
          aria-expanded={open}
          aria-label={`${folder.name} folder, ${count} ${count === 1 ? "room" : "rooms"}`}
          className="group flex h-7 w-full items-center gap-1.5 rounded px-1.5 text-left transition-colors hover:bg-hairline"
        >
          <ChevronRight
            className={`size-3 flex-shrink-0 text-faint transition-transform ${open ? "rotate-90" : ""}`}
          />
          <Icon className="size-3.5 flex-shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-label font-medium text-muted-foreground group-hover:text-text">
            {folder.name}
          </span>
          <span className="text-micro tabular text-faint">{count}</span>
        </button>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem icon={Plus} onClick={onNewRoom}>
          New room in this folder
        </ContextMenuItem>
        <ContextMenuItem icon={Pencil} onClick={onStartRename}>
          Rename
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem icon={ArrowUp} onClick={() => onMove(-1)}>
          Move up
        </ContextMenuItem>
        <ContextMenuItem icon={ArrowDown} onClick={() => onMove(1)}>
          Move down
        </ContextMenuItem>
        <ContextMenuSeparator />
        <ContextMenuItem icon={FolderMinus} destructive onClick={onDelete}>
          Delete folder (keeps its rooms)
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/**
 * A room's right-click menu: what its row's hover controls and the room's own
 * `…` menu already do, in one place. Right-clicking the row's link replaces the
 * browser's own menu, so opening in a new tab is offered here too. Filing it
 * in one of your folders is here as well.
 */
function RoomContextMenu({
  room,
  level,
  onSetLevel,
  onOpen,
  onDelete,
  folders,
  onMove,
  onNewFolder,
  children,
}: {
  room: Room;
  level: RoomLevel;
  onSetLevel: (room: string, level: RoomLevel) => void;
  onOpen: () => void;
  onDelete: () => void;
  folders: RoomFolder[];
  onMove: (room: string, to: string | null) => void;
  onNewFolder: (room: string) => void;
  children: React.ReactElement;
}) {
  const desktop = useIsDesktop();
  const path = `/room/${encodeURIComponent(room.name)}`;
  const current = folders.find(f => f.rooms.includes(room.name))?.id ?? null;
  return (
    <ContextMenu>
      <ContextMenuTrigger>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem icon={ArrowRight} onClick={onOpen}>
          Open
        </ContextMenuItem>
        {!desktop && (
          <ContextMenuItem icon={ExternalLink} onClick={() => window.open(path, "_blank", "noopener")}>
            Open in new tab
          </ContextMenuItem>
        )}
        <ContextMenuSub label="Notifications" icon={Bell}>
          <ContextMenuRadioGroup value={level} onValueChange={(value) => onSetLevel(room.name, value as RoomLevel)}>
            {LEVEL_OPTIONS.map(({ level: l, label }) => (
              <ContextMenuRadioItem key={l} value={l}>
                {label}
              </ContextMenuRadioItem>
            ))}
          </ContextMenuRadioGroup>
        </ContextMenuSub>
        <ContextMenuSub label="Move to folder" icon={FolderInput}>
          {folders.map(f => (
            <ContextMenuItem
              key={f.id}
              icon={f.id === current ? Check : Folder}
              disabled={f.id === current}
              onClick={() => onMove(room.name, f.id)}
            >
              {f.name}
            </ContextMenuItem>
          ))}
          {folders.length > 0 && <ContextMenuSeparator />}
          <ContextMenuItem icon={FolderPlus} onClick={() => onNewFolder(room.name)}>
            New folder…
          </ContextMenuItem>
          {current && (
            <ContextMenuItem icon={FolderMinus} onClick={() => onMove(room.name, null)}>
              Take out of folder
            </ContextMenuItem>
          )}
        </ContextMenuSub>
        <ContextMenuSeparator />
        <ContextMenuItem icon={Link2} onClick={() => void copyText(absoluteUrl(path))}>
          Copy link
        </ContextMenuItem>
        {room.mas_id && (
          <ContextMenuItem icon={Copy} onClick={() => void copyText(room.mas_id ?? "")}>
            Copy room ID
          </ContextMenuItem>
        )}
        <ContextMenuSeparator />
        <ContextMenuItem icon={Trash2} destructive onClick={onDelete}>
          Delete room…
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
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
