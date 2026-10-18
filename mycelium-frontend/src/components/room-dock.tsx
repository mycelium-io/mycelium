// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import "dockview-react/dist/styles/dockview.css";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  DockviewReact,
  type DockviewApi,
  type DockviewReadyEvent,
  type DockviewTheme,
  type IDockviewHeaderActionsProps,
  type IDockviewPanelHeaderProps,
  type IDockviewPanelProps,
} from "dockview-react";
import { ChevronDown, Copy, FileText, Link2, MessageSquare, Plus, X } from "lucide-react";
import { KbdChord } from "@/components/ui/kbd";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { iconButtonClass } from "@/components/ui/icon-button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { EventStream } from "@/components/event-stream";
import { RoomBoard } from "@/components/board/room-board";
import { RoomSchedules } from "@/components/schedules/room-schedules";
import { RoomStream } from "@/components/stream/room-stream";
import { RoomFiles } from "@/components/files/room-files";
import { RoomChatBox } from "@/components/room-chat-box";
import { MemoryView, type GuardHandle } from "@/components/memory-view";
import { ThreadView } from "@/components/thread-view";
import { KeyBadge } from "@/components/key-badge";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { copyText } from "@/lib/clipboard";
import { useRoomThreads } from "@/lib/room-data";
import { threadShortId } from "@/lib/threads";
import {
  VIEW_LABELS,
  isClosable,
  loadLayout,
  memoryPanelId,
  parsePanelId,
  restorableLayout,
  saveLayout,
  threadPanelId,
  type View,
} from "@/lib/room-dock";

/** A memory's name on its tab: the last part of its key (`cutover` for `decisions/cutover`). */
export function memoryTabLabel(key: string): string {
  return key.split("/").pop() || key;
}

/** Colors come from the app's own tokens (globals.css), so it follows light and dark. */
const THEME: DockviewTheme = { name: "mycelium", className: "dockview-theme-mycelium" };

interface DockContextValue {
  roomName: string;
  onOpenMemory: (key: string) => void;
  onOpenThread: (episode: string) => void;
  onOpenMessage: (id: string) => void;
  onMemoryChanged: () => void;
  onConnectionChange: (connected: boolean) => void;
  focusMessageId: string | null;
  onFocusConsumed: () => void;
  openFind: number;
  onMemoryGuard: (key: string, guard: GuardHandle | null) => void;
  requestClose: (id: string) => void;
  channelCount: number | null;
  setChannelCount: (n: number) => void;
  /** Open one of the room's views, as a tab if it isn't one already. */
  showView: (view: View) => void;
}

const DockContext = createContext<DockContextValue | null>(null);

function useDock(): DockContextValue {
  const value = useContext(DockContext);
  if (!value) throw new Error("useDock outside RoomDock");
  return value;
}

// ── Panels ──────────────────────────────────────────────────────────────────

function ChannelPanel() {
  const d = useDock();
  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden bg-bg">
      <div className="min-h-0 flex-1 overflow-hidden">
        <EventStream
          roomName={d.roomName}
          onMemoryChanged={d.onMemoryChanged}
          onConnectionChange={d.onConnectionChange}
          onOpenMemory={d.onOpenMemory}
          onOpenThread={d.onOpenThread}
          focusMessageId={d.focusMessageId}
          onFocusConsumed={d.onFocusConsumed}
          openFind={d.openFind}
          onCountChange={d.setChannelCount}
        />
      </div>
      <RoomChatBox roomName={d.roomName} onOpenMemory={d.onOpenMemory} onOpenView={d.showView} receivesInserts />
    </div>
  );
}

function StreamPanel() {
  const d = useDock();
  return <RoomStream roomName={d.roomName} onOpenThread={d.onOpenThread} onOpenMemory={d.onOpenMemory} />;
}

function FilesPanel() {
  const d = useDock();
  return (
    <RoomFiles
      roomName={d.roomName}
      onOpenThread={d.onOpenThread}
      onOpenMessage={d.onOpenMessage}
      onOpenMemory={d.onOpenMemory}
    />
  );
}

function BoardPanel() {
  const d = useDock();
  return (
    <div className="h-full min-h-0">
      <RoomBoard roomName={d.roomName} onOpenThread={d.onOpenThread} onOpenMessage={d.onOpenMessage} />
    </div>
  );
}

function SchedulesPanel() {
  const d = useDock();
  return (
    <div className="h-full min-h-0">
      <RoomSchedules roomName={d.roomName} />
    </div>
  );
}

function MemoryPanel({ params }: IDockviewPanelProps<{ key: string }>) {
  const d = useDock();
  return (
    <MemoryView
      key={params.key}
      roomName={d.roomName}
      memoryKey={params.key}
      onOpenMemory={d.onOpenMemory}
      onGuard={d.onMemoryGuard}
    />
  );
}

function ThreadPanel({ params, api }: IDockviewPanelProps<{ episode: string }>) {
  const d = useDock();
  const threads = useRoomThreads(d.roomName);
  const target = useMemo(
    () => ({ episode: params.episode, title: threads.get(params.episode)?.title ?? null }),
    [params.episode, threads],
  );
  return (
    <div className="flex h-full min-w-0">
      <ThreadView roomName={d.roomName} target={target} onClose={() => api.close()} showClose={false} onOpenMemory={d.onOpenMemory} />
    </div>
  );
}

const COMPONENTS = {
  channel: ChannelPanel,
  stream: StreamPanel,
  board: BoardPanel,
  files: FilesPanel,
  schedules: SchedulesPanel,
  memory: MemoryPanel,
  thread: ThreadPanel,
} as unknown as Record<string, React.FunctionComponent<IDockviewPanelProps>>;

// ── Tabs ────────────────────────────────────────────────────────────────────

/** Whether a tab is the one its group shows. */
function useShown(api: IDockviewPanelHeaderProps["api"]): boolean {
  const [shown, setShown] = useState(api.isVisible);
  useEffect(() => {
    const sub = api.onDidVisibilityChange(e => setShown(e.isVisible));
    return () => sub.dispose();
  }, [api]);
  return shown;
}

function ThreadTabLabel({ episode }: { episode: string }) {
  const d = useDock();
  const threads = useRoomThreads(d.roomName);
  const title = threads.get(episode)?.title;
  return <>{title || `Thread ${threadShortId(episode) ?? ""}`.trim()}</>;
}

/** How a tab names itself, the same in the strip and in its overflow menu. */
function tabFace(id: string, fallback: string | undefined) {
  const parsed = parsePanelId(id);
  let icon: React.ReactNode = null;
  let label: React.ReactNode = fallback ?? id;
  let title: string | undefined;
  if (parsed?.kind === "memory") {
    icon = <FileText className="size-3.5 flex-shrink-0 text-faint" />;
    label = memoryTabLabel(parsed.key);
    title = parsed.key;
  } else if (parsed?.kind === "thread") {
    icon = <MessageSquare className="size-3.5 flex-shrink-0 text-accent" strokeWidth={1.9} />;
    label = <ThreadTabLabel episode={parsed.episode} />;
    title = parsed.episode;
  } else if (parsed) {
    label = VIEW_LABELS[parsed.kind];
  }
  const view = parsed && parsed.kind !== "memory" && parsed.kind !== "thread" ? (parsed.kind as View) : null;
  return { parsed, icon, label, title, view };
}

/**
 * One tab, for every kind: the room's own views wear the key that selects them
 * (shown while the reveal modifier is held) and the Channel its count; a memory
 * or a thread closes with its ×, a middle click, or its menu. Dragging it is
 * dockview's: onto another tab bar to move it, onto an edge to split.
 */
function DockTab({ api, containerApi }: IDockviewPanelHeaderProps) {
  const d = useDock();
  const shown = useShown(api);
  const { parsed, icon, label, title, view } = tabFace(api.id, api.title);
  const closable = isClosable(api.id);
  const close = () => d.requestClose(api.id);

  const others = () => api.group.panels.filter(p => p.id !== api.id && isClosable(p.id)).map(p => p.id);

  return (
    <ContextMenu>
      <ContextMenuTrigger>
        <div
          role="tab"
          aria-selected={shown}
          title={title}
          data-panel-id={api.id}
          data-tour={view ? `tab-${view}` : undefined}
          onMouseDown={e => {
            if (e.button === 1 && closable) {
              e.preventDefault();
              close();
            }
          }}
          className={`group/tab flex h-full items-center gap-1.5 border-r border-border text-label transition-colors ${
            closable ? "pl-3 pr-1.5" : "px-3"
          } ${shown ? "bg-paper text-text" : "text-muted-foreground hover:bg-hairline hover:text-text"}`}
        >
          {icon}
          <span className="max-w-40 truncate">{label}</span>
          {view && <KeyBadge action={`pane.${view}`} />}
          {view === "channel" && d.channelCount !== null && (
            <span className={`text-micro tabular ${shown ? "text-accent" : "text-muted-foreground"}`}>
              {d.channelCount}
            </span>
          )}
          {closable && (
            <button
              type="button"
              aria-label={`Close ${title ?? label}`}
              // Not a drag start, and not a click on the tab under it.
              onMouseDown={e => e.stopPropagation()}
              onClick={e => {
                e.stopPropagation();
                close();
              }}
              className={`flex size-4 items-center justify-center rounded transition-opacity hover:bg-hairline ${
                shown ? "opacity-100" : "opacity-0 group-hover/tab:opacity-100"
              }`}
            >
              <X className="size-3" />
            </button>
          )}
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        {closable && (
          <ContextMenuItem icon={X} onClick={close}>
            Close
          </ContextMenuItem>
        )}
        <ContextMenuItem disabled={others().length === 0} onClick={() => others().forEach(d.requestClose)}>
          Close others
        </ContextMenuItem>
        <ContextMenuItem onClick={() => splitRight(containerApi, api.id)} disabled={api.group.panels.length < 2}>
          Split right
        </ContextMenuItem>
        {parsed?.kind === "memory" && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem icon={Copy} onClick={() => void copyText(parsed.key)}>
              Copy key
            </ContextMenuItem>
            <ContextMenuItem icon={Link2} onClick={() => void copyText(`[[${parsed.key}]]`)}>
              Copy as [[link]]
            </ContextMenuItem>
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
}

// ── The strip's overflow ────────────────────────────────────────────────────

/** The panels whose tabs aren't wholly in view in `strip`, in strip order. A
 *  tab cut by a pixel or less at either edge counts as shown, and so does a
 *  tab wider than the strip whose start is in view: it can't show more. */
export function clippedTabs(strip: Element): string[] {
  const box = strip.getBoundingClientRect();
  const out: string[] = [];
  for (const tab of strip.querySelectorAll<HTMLElement>("[data-panel-id]")) {
    const r = tab.getBoundingClientRect();
    const startShown = r.left >= box.left - 1;
    const endShown = r.right <= box.right + 1 || (r.width > box.width && Math.abs(r.left - box.left) <= 1);
    if (!startShown || !endShown) out.push(tab.dataset.panelId as string);
  }
  return out;
}

const sameIds = (a: string[], b: string[]) => a.length === b.length && a.every((id, i) => id === b[i]);

/**
 * At the right of a group's strip, while some of its tabs are scrolled out of
 * view: a count of them, opening the app's own menu of those tabs. Picking one
 * shows it and scrolls it into the strip. (Dockview's own overflow list is off,
 * `disableTabsOverflowList`: it kept its own type and spacing, and moved tabs
 * out of the strip rather than letting it scroll.)
 */
function GroupOverflow({ group }: IDockviewHeaderActionsProps) {
  const anchor = useRef<HTMLDivElement>(null);
  const strip = useRef<HTMLElement | null>(null);
  const [hidden, setHidden] = useState<string[]>([]);
  const [active, setActive] = useState<string | undefined>(group.activePanel?.id);

  const reveal = useCallback((id: string | undefined) => {
    if (!id) return;
    const tab = strip.current?.querySelector(`[data-panel-id="${CSS.escape(id)}"]`);
    tab?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, []);

  useEffect(() => {
    const header = anchor.current?.closest(".dv-tabs-and-actions-container");
    const el = header?.querySelector<HTMLElement>(".dv-tabs-container") ?? null;
    strip.current = el;
    if (!el) return;
    let frame = 0;
    // The shown tab is brought into view when the strip appears and whenever
    // another tab is shown (the memory tree, a link). Tabs keep resizing for a
    // moment after (fonts, a thread's title arriving), so for a second after,
    // every measure brings it back if it's been pushed out; past that the
    // strip is the reader's to scroll.
    let revealUntil = performance.now() + 1000;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        let next = clippedTabs(el);
        const shown = group.activePanel?.id;
        if (shown && next.includes(shown) && performance.now() < revealUntil) {
          reveal(shown);
          next = clippedTabs(el);
        }
        setHidden(prev => (sameIds(prev, next) ? prev : next));
      });
    };
    measure();
    const resized = new ResizeObserver(measure);
    resized.observe(el);
    const changed = new MutationObserver(measure);
    changed.observe(el, { childList: true, subtree: true });
    el.addEventListener("scroll", measure, { passive: true });
    const sub = group.api.onDidActivePanelChange(e => {
      setActive(e.panel?.id);
      revealUntil = performance.now() + 1000;
      measure();
    });
    return () => {
      cancelAnimationFrame(frame);
      resized.disconnect();
      changed.disconnect();
      el.removeEventListener("scroll", measure);
      sub.dispose();
    };
  }, [group, reveal]);

  const show = (id: string) => {
    group.panels.find(p => p.id === id)?.api.setActive();
    requestAnimationFrame(() => reveal(id));
  };

  return (
    <div ref={anchor} className="flex h-full items-center">
      {hidden.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label={`${hidden.length} more ${hidden.length === 1 ? "tab" : "tabs"}`}
            title="Tabs out of view"
            className="flex h-full items-center gap-0.5 border-l border-border px-2 text-label tabular text-muted-foreground outline-none transition-colors hover:bg-hairline hover:text-text focus-visible:bg-hairline focus-visible:text-text data-[popup-open]:bg-hairline data-[popup-open]:text-text"
          >
            <ChevronDown className="size-3.5" />
            {hidden.length}
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-72">
            {hidden.map(id => {
              const panel = group.panels.find(p => p.id === id);
              const face = tabFace(id, panel?.title);
              const isActive = id === active;
              return (
                <DropdownMenuItem key={id} onClick={() => show(id)} title={face.title} aria-current={isActive || undefined}>
                  {face.icon ?? <span className="w-3.5 shrink-0" />}
                  <span className={`min-w-0 flex-1 truncate ${isActive ? "font-medium" : ""}`}>{face.label}</span>
                  {isActive && <span aria-label="Shown" className="size-1.5 shrink-0 rounded-full bg-accent" />}
                  {face.view && <KbdChord action={`pane.${face.view}`} size="xs" tone="muted" />}
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

// ── The strip's + ───────────────────────────────────────────────────────────

/** The room's own views that aren't open anywhere in the dock. */
function useClosedViews(api: DockviewApi): View[] {
  const closedNow = useCallback(() => VIEW_ORDER.filter(v => !api.getPanel(v)), [api]);
  const [closed, setClosed] = useState<View[]>(closedNow);
  useEffect(() => {
    const update = () => setClosed(closedNow());
    const subs = [api.onDidAddPanel(update), api.onDidRemovePanel(update)];
    return () => subs.forEach(s => s.dispose());
  }, [api, closedNow]);
  return closed;
}

/**
 * After a group's tabs: a + that brings back a room view that was closed,
 * into this group. Shown only while there is one to bring back.
 */
function GroupActions({ containerApi, group }: IDockviewHeaderActionsProps) {
  const closed = useClosedViews(containerApi);
  const [open, setOpen] = useState(false);
  if (closed.length === 0) return null;
  return (
    <div className="flex h-full items-center px-1">
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          aria-label="Open a view"
          title="Open a view"
          className={iconButtonClass("sm", "data-[popup-open]:bg-hairline data-[popup-open]:text-text")}
        >
          <Plus />
        </PopoverTrigger>
        <PopoverContent side="bottom" align="start" className="w-48 p-1">
          {closed.map(view => (
            <button
              key={view}
              type="button"
              onClick={() => {
                setOpen(false);
                addView(containerApi, view, { referenceGroup: group });
              }}
              className="flex w-full items-center justify-between gap-2 rounded-md px-2 py-1.5 text-left text-label text-text transition-colors hover:bg-hairline"
            >
              {VIEW_LABELS[view]}
              <KbdChord action={`pane.${view}`} size="sm" />
            </button>
          ))}
        </PopoverContent>
      </Popover>
    </div>
  );
}

// ── Opening and moving ──────────────────────────────────────────────────────

const VIEW_ORDER: View[] = ["channel", "stream", "board", "files", "schedules"];

function addView(api: DockviewApi, view: View, position?: Parameters<DockviewApi["addPanel"]>[0]["position"]) {
  return api.addPanel({
    id: view,
    component: view,
    title: VIEW_LABELS[view],
    // The Channel stays laid out while another tab is in front of it, so it
    // keeps its scroll position and never mistakes itself for an empty viewport.
    renderer: view === "channel" ? "always" : undefined,
    ...(position ? { position } : {}),
  });
}

/** The room's first layout: Channel, Stream, Board and Files as tabs, the Channel in front. */
function defaultLayout(api: DockviewApi): void {
  addView(api, "channel");
  addView(api, "stream", { referencePanel: "channel" });
  addView(api, "board", { referencePanel: "channel" });
  addView(api, "files", { referencePanel: "channel" });
  api.getPanel("channel")?.api.setActive();
}

/** Move a tab into a new group to the right of its own, when its group has others. */
export function splitRight(api: DockviewApi, id: string): void {
  const panel = api.getPanel(id);
  if (!panel || panel.api.group.panels.length < 2) return;
  const group = api.addGroup({ referenceGroup: panel.api.group, direction: "right" });
  panel.api.moveTo({ group });
  panel.api.setActive();
}

/** Every tab into the first group: one strip of tabs, for a window too narrow to split. */
function collapseGroups(api: DockviewApi): void {
  const [first, ...rest] = api.groups;
  if (!first) return;
  for (const group of rest) for (const panel of [...group.panels]) panel.api.moveTo({ group: first });
}

export interface RoomDockHandle {
  /** The room this dock is, so a handle left over from the last room is never used. */
  room: string;
  /** Show one of the room's views, reopening it if it was closed. */
  showView: (view: View) => void;
  openMemory: (key: string) => void;
  openThread: (episode: string) => void;
  /** Close the tab in front of the active group, if it closes; false when it doesn't. */
  closeActive: () => boolean;
  /** Reopen the tab closed most recently. */
  reopenClosed: () => void;
  splitActive: () => void;
  focusGroup: (step: 1 | -1) => void;
}

interface Props {
  roomName: string;
  onMemoryChanged: () => void;
  onConnectionChange: (connected: boolean) => void;
  focusMessageId: string | null;
  onFocusConsumed: () => void;
  openFind: number;
  /** Too narrow for splits: every tab stays in one group, and dragging is off. */
  narrow: boolean;
  /** The tab in front of the active group, whenever it changes. */
  onActiveChange: (id: string | null) => void;
  onReady: (handle: RoomDockHandle) => void;
  /** Wired by the page to the dock's own handle, so a `[[link]]` or a ping in
   *  any panel opens its tab through the same path the page does. */
  onOpenMemory: (key: string) => void;
  onOpenThread: (episode: string) => void;
  /** Reveal a message said in the channel, the way a search hit does. */
  onOpenMessage: (id: string) => void;
}

/**
 * The room's center: every view is a tab, and tabs drag into splits. The
 * layout is this browser's, remembered per room.
 */
export function RoomDock({
  roomName,
  onMemoryChanged,
  onConnectionChange,
  focusMessageId,
  onFocusConsumed,
  openFind,
  narrow,
  onActiveChange,
  onReady,
  onOpenMemory,
  onOpenThread,
  onOpenMessage,
}: Props) {
  const apiRef = useRef<DockviewApi | null>(null);
  const [channelCount, setChannelCount] = useState<number | null>(null);
  const memoryGuards = useRef(new Map<string, GuardHandle>());
  const closed = useRef<string[]>([]);
  const narrowRef = useRef(narrow);
  useEffect(() => {
    narrowRef.current = narrow;
  }, [narrow]);

  const onMemoryGuard = useCallback((key: string, guard: GuardHandle | null) => {
    if (guard) memoryGuards.current.set(key, guard);
    else memoryGuards.current.delete(key);
  }, []);

  // Closing a memory with edits in progress asks first.
  const requestClose = useCallback((id: string) => {
    const api = apiRef.current;
    const panel = api?.getPanel(id);
    if (!panel || !isClosable(id)) return;
    const parsed = parsePanelId(id);
    const guard = parsed?.kind === "memory" ? memoryGuards.current.get(parsed.key) : undefined;
    const close = () => {
      closed.current = [...closed.current.filter(c => c !== id), id].slice(-20);
      panel.api.close();
    };
    if (guard) guard(close);
    else close();
  }, []);

  const handle = useMemo<RoomDockHandle>(() => {
    const api = () => apiRef.current;
    const show = (id: string) => api()?.getPanel(id)?.api.setActive();
    /** Where a new tab goes: the active group, or beside the Channel when the
     *  active group is the Channel's and a split is wanted. */
    const open = (id: string, add: (api: DockviewApi) => void) => {
      const a = api();
      if (!a) return;
      if (a.getPanel(id)) return show(id);
      add(a);
    };
    return {
      room: roomName,
      showView: view => {
        open(view, a => {
          const anchor = VIEW_ORDER.map(v => a.getPanel(v)).find(Boolean);
          addView(a, view, anchor ? { referencePanel: anchor } : undefined);
        });
      },
      openMemory: key => {
        const id = memoryPanelId(key);
        open(id, a => {
          const group = a.activeGroup;
          a.addPanel({
            id,
            component: "memory",
            params: { key },
            title: memoryTabLabel(key),
            ...(group ? { position: { referenceGroup: group } } : {}),
          });
        });
      },
      openThread: episode => {
        const id = threadPanelId(episode);
        open(id, a => {
          // A thread opens beside the room rather than over it, as it always
          // has: into a group of threads to the right of the Channel's, made
          // the first time. Too narrow to split, it is one more tab.
          const channelGroup = a.getPanel("channel")?.api.group;
          const threadGroup = a.panels.find(p => parsePanelId(p.id)?.kind === "thread")?.api.group;
          const position = narrowRef.current
            ? a.activeGroup
              ? { referenceGroup: a.activeGroup }
              : undefined
            : threadGroup
              ? { referenceGroup: threadGroup }
              : channelGroup
                ? { referenceGroup: channelGroup, direction: "right" as const }
                : undefined;
          a.addPanel({ id, component: "thread", params: { episode }, ...(position ? { position } : {}) });
        });
      },
      closeActive: () => {
        const id = api()?.activePanel?.id;
        if (!id || !api()?.getPanel(id) || !isClosable(id)) return false;
        requestClose(id);
        return true;
      },
      reopenClosed: () => {
        const id = closed.current.pop();
        const parsed = id ? parsePanelId(id) : null;
        if (!parsed) return;
        if (parsed.kind === "memory") onOpenMemory(parsed.key);
        else if (parsed.kind === "thread") onOpenThread(parsed.episode);
        else handleRef.current?.showView(parsed.kind);
      },
      splitActive: () => {
        const a = api();
        const id = a?.activePanel?.id;
        if (a && id && !narrowRef.current) splitRight(a, id);
      },
      focusGroup: step => {
        const a = api();
        if (!a) return;
        if (step === 1) a.activateNext();
        else a.activatePrevious();
      },
    };
  }, [roomName, requestClose, onOpenMemory, onOpenThread]);
  const handleRef = useRef(handle);
  useEffect(() => {
    handleRef.current = handle;
  }, [handle]);

  const ready = useCallback(
    (event: DockviewReadyEvent) => {
      const api = event.api;
      apiRef.current = api;
      const saved = loadLayout(roomName);
      let restored = false;
      if (restorableLayout(saved)) {
        try {
          api.fromJSON(saved as Parameters<DockviewApi["fromJSON"]>[0]);
          restored = true;
        } catch {
          api.clear();
        }
      }
      if (!restored) defaultLayout(api);
      // Saved layouts predate nothing: the Channel's renderer isn't serialized.
      api.getPanel("channel")?.api.setRenderer("always");
      if (narrowRef.current) collapseGroups(api);

      api.onDidLayoutChange(() => saveLayout(roomName, api.toJSON()));
      api.onDidActivePanelChange(e => onActiveChange(e.panel?.id ?? null));
      onActiveChange(api.activePanel?.id ?? null);
      onReady(handleRef.current);
    },
    // The dock is keyed by room, so this runs once per room.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [],
  );

  // Handed over only once dockview is up: a handle before that opens nothing.
  useEffect(() => {
    if (apiRef.current) onReady(handle);
  }, [handle, onReady]);

  useEffect(() => {
    const api = apiRef.current;
    if (api && narrow) collapseGroups(api);
  }, [narrow]);

  const context = useMemo<DockContextValue>(
    () => ({
      roomName,
      onOpenMemory,
      onOpenThread,
      onOpenMessage,
      onMemoryChanged,
      onConnectionChange,
      focusMessageId,
      onFocusConsumed,
      openFind,
      onMemoryGuard,
      requestClose,
      channelCount,
      setChannelCount,
      showView: (view: View) => handleRef.current?.showView(view),
    }),
    [
      roomName,
      onOpenMemory,
      onOpenThread,
      onOpenMessage,
      onMemoryChanged,
      onConnectionChange,
      focusMessageId,
      onFocusConsumed,
      openFind,
      onMemoryGuard,
      requestClose,
      channelCount,
    ],
  );

  return (
    <DockContext.Provider value={context}>
      <DockviewReact
        className="h-full w-full"
        theme={THEME}
        components={COMPONENTS}
        defaultTabComponent={DockTab}
        leftHeaderActionsComponent={GroupActions}
        rightHeaderActionsComponent={GroupOverflow}
        disableTabsOverflowList
        onReady={ready}
        disableDnd={narrow}
        disableFloatingGroups
        singleTabMode="default"
      />
    </DockContext.Provider>
  );
}
