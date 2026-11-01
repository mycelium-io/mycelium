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
import { ChevronDown, Copy, FileText, Link2, MessageSquare, X } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { EventStream } from "@/components/event-stream";
import { RoomBoard } from "@/components/board/room-board";
import { RoomSchedules } from "@/components/schedules/room-schedules";
import { RoomStream } from "@/components/stream/room-stream";
import { RoomFiles } from "@/components/files/room-files";
import { RoomChatBox } from "@/components/room-chat-box";
import { MemoryView, type GuardHandle } from "@/components/memory-view";
import { ThreadView } from "@/components/thread-view";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { copyText } from "@/lib/clipboard";
import { clearOnScreen, setOnScreen } from "@/lib/on-screen";
import { useRoomThreads } from "@/lib/room-data";
import { threadShortId } from "@/lib/threads";
import { Findable } from "@/components/findable";
import {
  VIEW_LABELS,
  findFor,
  isClosable,
  loadLayout,
  memoryPanelId,
  panesInFront,
  parsePanelId,
  restorableLayout,
  saveLayout,
  threadPanelId,
  type FindRequest,
  type View,
} from "@/lib/room-dock";
import { cn } from "@/lib/utils";

/** A memory's name on its tab: the last part of its key (`cutover` for `decisions/cutover`). */
export function memoryTabLabel(key: string): string {
  return key.split("/").pop() || key;
}

/** Colors come from the app's own tokens (globals.css), so it follows light and dark. */
const THEME: DockviewTheme = { name: "mycelium", className: "dockview-theme-mycelium" };

/** How much of the center the open tabs take beside the view, at first. */
const TABS_SHARE = 0.45;
const TABS_SHARE_MIN = 0.25;
const TABS_SHARE_MAX = 0.75;

interface DockContextValue {
  roomName: string;
  onOpenMemory: (key: string) => void;
  onOpenThread: (episode: string) => void;
  onOpenMessage: (id: string) => void;
  onMemoryChanged: () => void;
  onConnectionChange: (connected: boolean) => void;
  focusMessageId: string | null;
  onFocusConsumed: () => void;
  /** The latest ⌘F, for whichever panel was in front. */
  find: FindRequest;
  /** Put a panel in front, when it's clicked into. */
  bringToFront: (id: string) => void;
  onMemoryGuard: (key: string, guard: GuardHandle | null) => void;
  requestClose: (id: string) => void;
  setChannelCount: (n: number) => void;
  /** Show one of the room's views in the view pane. */
  showView: (view: View) => void;
}

const DockContext = createContext<DockContextValue | null>(null);

function useDock(): DockContextValue {
  const value = useContext(DockContext);
  if (!value) throw new Error("useDock outside RoomDock");
  return value;
}

// ── The room's views ────────────────────────────────────────────────────────

function ChannelView() {
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
          openFind={findFor(d.find, "channel")}
          onCountChange={d.setChannelCount}
        />
      </div>
      <RoomChatBox roomName={d.roomName} onOpenMemory={d.onOpenMemory} onOpenView={d.showView} receivesInserts />
    </div>
  );
}

/** What ⌘F says it finds in, per view. */
const FIND_LABELS: Record<Exclude<View, "channel">, string> = {
  stream: "Find in the stream",
  board: "Find on the board",
  files: "Find in the files",
  schedules: "Find in the schedules",
};

function OtherView({ view }: { view: Exclude<View, "channel"> }) {
  const d = useDock();
  return (
    <Findable
      request={findFor(d.find, view)}
      label={FIND_LABELS[view]}
      className="h-full"
      contentClassName="[&>*]:h-full"
    >
      {view === "stream" ? (
        <RoomStream roomName={d.roomName} onOpenThread={d.onOpenThread} onOpenMemory={d.onOpenMemory} />
      ) : view === "files" ? (
        <RoomFiles
          roomName={d.roomName}
          onOpenThread={d.onOpenThread}
          onOpenMessage={d.onOpenMessage}
          onOpenMemory={d.onOpenMemory}
        />
      ) : view === "board" ? (
        <div className="h-full min-h-0">
          <RoomBoard roomName={d.roomName} onOpenThread={d.onOpenThread} onOpenMessage={d.onOpenMessage} />
        </div>
      ) : (
        <div className="h-full min-h-0">
          <RoomSchedules roomName={d.roomName} />
        </div>
      )}
    </Findable>
  );
}

/**
 * The view pane: the view picked under the room in the Rooms rail. The Channel
 * stays mounted while another view is shown, so it keeps its scroll position
 * and its live feed; the others mount when shown.
 */
function ViewPane({ view }: { view: View }) {
  return (
    <>
      <div className={cn("h-full min-h-0", view !== "channel" && "hidden")}>
        <ChannelView />
      </div>
      {view !== "channel" && <OtherView view={view} />}
    </>
  );
}

// ── What you opened ─────────────────────────────────────────────────────────

/** A tab's content, which puts the tab in front when it's clicked into. The
 *  dock says so when a tab is picked, but not when the reader clicks back into
 *  the tab already showing in its group after using the view beside it. */
function InFront({ id, children }: { id: string; children: React.ReactNode }) {
  const d = useDock();
  return (
    <div
      className="flex h-full min-h-0 min-w-0 flex-col"
      onFocusCapture={() => d.bringToFront(id)}
      onPointerDownCapture={() => d.bringToFront(id)}
    >
      {children}
    </div>
  );
}

function MemoryPanel({ params }: IDockviewPanelProps<{ key: string }>) {
  const d = useDock();
  const id = memoryPanelId(params.key);
  return (
    <InFront id={id}>
      <Findable
        request={findFor(d.find, id)}
        label="Find in this memory"
        history={{ kind: "memories", room: d.roomName, onOpen: d.onOpenMemory }}
        className="h-full"
        contentClassName="[&>*]:h-full"
      >
        <MemoryView
          key={params.key}
          roomName={d.roomName}
          memoryKey={params.key}
          onOpenMemory={d.onOpenMemory}
          onGuard={d.onMemoryGuard}
        />
      </Findable>
    </InFront>
  );
}

function ThreadPanel({ params, api }: IDockviewPanelProps<{ episode: string }>) {
  const d = useDock();
  const threads = useRoomThreads(d.roomName);
  const target = useMemo(
    () => ({ episode: params.episode, title: threads.get(params.episode)?.title ?? null }),
    [params.episode, threads],
  );
  const id = threadPanelId(params.episode);
  return (
    <InFront id={id}>
      <div className="flex h-full min-w-0">
        <ThreadView
          roomName={d.roomName}
          target={target}
          onClose={() => api.close()}
          showClose={false}
          onOpenMemory={d.onOpenMemory}
          findRequest={findFor(d.find, id)}
        />
      </div>
    </InFront>
  );
}

const COMPONENTS = {
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

/** How a tab names itself, the same in the strip, its overflow menu and the
 *  narrow pane's list of open tabs. */
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
  }
  return { parsed, icon, label, title };
}

/**
 * One tab: a memory or a thread you opened. It closes with its ×, a middle
 * click, its menu or ⌘W. Dragging it is dockview's: onto another tab bar to
 * move it, onto an edge to split.
 */
function DockTab({ api, containerApi }: IDockviewPanelHeaderProps) {
  const d = useDock();
  const shown = useShown(api);
  const { parsed, icon, label, title } = tabFace(api.id, api.title);
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
          onMouseDown={e => {
            if (e.button === 1) {
              e.preventDefault();
              close();
            }
          }}
          className={`group/tab flex h-full items-center gap-1.5 border-r border-border pl-3 pr-1.5 text-label transition-colors ${
            shown ? "bg-paper text-text" : "text-muted-foreground hover:bg-hairline hover:text-text"
          }`}
        >
          {icon}
          <span className="max-w-40 truncate">{label}</span>
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
        </div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        <ContextMenuItem icon={X} onClick={close}>
          Close
        </ContextMenuItem>
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
                </DropdownMenuItem>
              );
            })}
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

/**
 * On a narrow pane, over the view while tabs are open: one line naming them,
 * each a way back to it. The view and the tabs don't fit side by side there,
 * so the pane shows one or the other.
 */
function OpenTabsLine({ ids, titles, onShow }: { ids: string[]; titles: Record<string, string | undefined>; onShow: (id: string) => void }) {
  return (
    <div className="flex h-8 flex-shrink-0 items-center gap-1 overflow-x-auto border-b border-border bg-surface px-2 text-micro text-muted-foreground">
      <span className="flex-shrink-0 px-1 text-faint">Open</span>
      {ids.map(id => {
        const face = tabFace(id, titles[id]);
        return (
          <button
            key={id}
            type="button"
            onClick={() => onShow(id)}
            title={face.title}
            className="flex h-6 max-w-48 flex-shrink-0 items-center gap-1 rounded px-1.5 text-label transition-colors hover:bg-hairline hover:text-text"
          >
            {face.icon}
            <span className="truncate">{face.label}</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Opening and moving ──────────────────────────────────────────────────────

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
  /** Show one of the room's views in the view pane. */
  showView: (view: View) => void;
  openMemory: (key: string) => void;
  openThread: (episode: string) => void;
  /** Close the tab in front of the active group; false when there's none to
   *  close. A view is never closed. */
  closeActive: () => boolean;
  /** Reopen the tab closed most recently. */
  reopenClosed: () => void;
  splitActive: () => void;
  focusGroup: (step: 1 | -1) => void;
}

interface Props {
  roomName: string;
  /** The view in the view pane, picked under the room in the Rooms rail. */
  view: View;
  onViewChange: (view: View) => void;
  /** How many messages the Channel has, for its row in the Rooms rail. */
  onChannelCount: (n: number) => void;
  onMemoryChanged: () => void;
  onConnectionChange: (connected: boolean) => void;
  focusMessageId: string | null;
  onFocusConsumed: () => void;
  find: FindRequest;
  /** Too narrow for the view and the tabs side by side: the pane shows one at
   *  a time, every tab stays in one group, and dragging is off. */
  narrow: boolean;
  /** What's in front: the view, or the tab in front of the active group. */
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
 * The room's center: the view picked in the Rooms rail, and beside it the
 * tabs you opened, which drag into splits. The view isn't a tab, so it can't
 * be closed or lost among them. The tabs' layout is this browser's,
 * remembered per room.
 */
export function RoomDock({
  roomName,
  view,
  onViewChange,
  onChannelCount,
  onMemoryChanged,
  onConnectionChange,
  focusMessageId,
  onFocusConsumed,
  find,
  narrow,
  onActiveChange,
  onReady,
  onOpenMemory,
  onOpenThread,
  onOpenMessage,
}: Props) {
  const apiRef = useRef<DockviewApi | null>(null);
  const memoryGuards = useRef(new Map<string, GuardHandle>());
  const closed = useRef<string[]>([]);
  // The open tabs, in the order they were opened, and their titles.
  const [tabs, setTabs] = useState<string[]>([]);
  const [titles, setTitles] = useState<Record<string, string | undefined>>({});
  // On a narrow pane, which of the two is shown.
  const [showing, setShowing] = useState<"view" | "tabs">("view");
  const [share, setShare] = useState(TABS_SHARE);
  const centerRef = useRef<HTMLDivElement>(null);

  // A view picked (or restored for this room after the dock was ready) is
  // what's in front, so ⌘F never goes to the Channel hidden behind it.
  useEffect(() => {
    onActiveChange(view);
  }, [view, onActiveChange]);

  const narrowRef = useRef(narrow);
  const viewRef = useRef(view);
  const showingRef = useRef(showing);
  useEffect(() => {
    narrowRef.current = narrow;
    viewRef.current = view;
    showingRef.current = showing;
  }, [narrow, view, showing]);

  const hasTabs = tabs.length > 0;
  const viewShown = !narrow || !hasTabs || showing === "view";
  const tabsShown = hasTabs && (!narrow || showing === "tabs");

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

  // What's in front of you, for the bell and reading aloud: the view when it's
  // on screen, and every group's front tab when the tabs are.
  const publish = useCallback(() => {
    const api = apiRef.current;
    const n = api?.panels.length ?? 0;
    const front: (string | undefined)[] = [];
    if (!narrowRef.current || n === 0 || showingRef.current === "view") front.push(viewRef.current);
    if (api && n > 0 && (!narrowRef.current || showingRef.current === "tabs")) {
      front.push(...api.groups.map(g => g.activePanel?.id));
    }
    setOnScreen({ room: roomName, panes: panesInFront(front) });
  }, [roomName]);

  const handle = useMemo<RoomDockHandle>(() => {
    const api = () => apiRef.current;
    const reveal = (id: string) => {
      api()?.getPanel(id)?.api.setActive();
      setShowing("tabs");
    };
    const open = (id: string, add: (api: DockviewApi) => void) => {
      const a = api();
      if (!a) return;
      if (!a.getPanel(id)) add(a);
      reveal(id);
    };
    const into = (a: DockviewApi) => (a.activeGroup ? { position: { referenceGroup: a.activeGroup } } : {});
    return {
      room: roomName,
      showView: next => {
        onViewChange(next);
        setShowing("view");
        onActiveChange(next);
      },
      openMemory: key => {
        const id = memoryPanelId(key);
        open(id, a => a.addPanel({ id, component: "memory", params: { key }, title: memoryTabLabel(key), ...into(a) }));
      },
      openThread: episode => {
        const id = threadPanelId(episode);
        open(id, a => a.addPanel({ id, component: "thread", params: { episode }, ...into(a) }));
      },
      closeActive: () => {
        // A tab hidden behind the view on a narrow pane isn't the one in front.
        if (narrowRef.current && showingRef.current === "view") return false;
        const id = api()?.activePanel?.id;
        if (!id || !isClosable(id)) return false;
        requestClose(id);
        return true;
      },
      reopenClosed: () => {
        const id = closed.current.pop();
        const parsed = id ? parsePanelId(id) : null;
        if (parsed?.kind === "memory") onOpenMemory(parsed.key);
        else if (parsed?.kind === "thread") onOpenThread(parsed.episode);
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
  }, [roomName, requestClose, onOpenMemory, onOpenThread, onViewChange, onActiveChange]);
  const handleRef = useRef(handle);
  useEffect(() => {
    handleRef.current = handle;
  }, [handle]);

  const ready = useCallback(
    (event: DockviewReadyEvent) => {
      const api = event.api;
      apiRef.current = api;
      const saved = loadLayout(roomName);
      if (restorableLayout(saved)) {
        try {
          api.fromJSON(saved as Parameters<DockviewApi["fromJSON"]>[0]);
        } catch {
          api.clear();
        }
      }
      if (narrowRef.current) collapseGroups(api);

      const recount = () => {
        setTabs(api.panels.map(p => p.id));
        setTitles(Object.fromEntries(api.panels.map(p => [p.id, p.title])));
        if (api.panels.length === 0) {
          // The last tab closed: the view is what's in front again.
          setShowing("view");
          onActiveChange(viewRef.current);
        }
      };
      api.onDidAddPanel(recount);
      api.onDidRemovePanel(recount);
      api.onDidLayoutChange(() => {
        saveLayout(roomName, api.toJSON());
        publish();
      });
      api.onDidActivePanelChange(e => {
        if (e.panel) onActiveChange(e.panel.id);
        publish();
      });
      recount();
      onActiveChange(viewRef.current);
      publish();
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

  // Whatever the pane shows changed: say what's in front now.
  useEffect(() => {
    if (apiRef.current) publish();
  }, [view, showing, narrow, hasTabs, publish]);

  // Leaving the room: none of it is in front any more.
  useEffect(() => () => clearOnScreen(roomName), [roomName]);

  // The handle between the view and the tabs: drag to share the width.
  const startResize = useCallback((e: React.PointerEvent) => {
    const box = centerRef.current?.getBoundingClientRect();
    if (!box) return;
    e.preventDefault();
    const move = (ev: PointerEvent) => {
      const next = (box.right - ev.clientX) / box.width;
      setShare(Math.min(TABS_SHARE_MAX, Math.max(TABS_SHARE_MIN, next)));
    };
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }, []);

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
      find,
      bringToFront: onActiveChange,
      onMemoryGuard,
      requestClose,
      setChannelCount: onChannelCount,
      showView: (next: View) => handleRef.current?.showView(next),
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
      find,
      onActiveChange,
      onMemoryGuard,
      requestClose,
      onChannelCount,
    ],
  );

  return (
    <DockContext.Provider value={context}>
      <div ref={centerRef} className="flex h-full min-h-0 w-full min-w-0">
        <section
          aria-label={VIEW_LABELS[view]}
          data-room-view={view}
          // Clicking into the view puts it in front again, for the keys that
          // act on what's in front (⌘F finds in it), whether or not what was
          // clicked takes focus.
          onFocusCapture={() => onActiveChange(view)}
          onPointerDownCapture={() => onActiveChange(view)}
          className={cn("flex min-h-0 min-w-0 flex-1 flex-col", !viewShown && "hidden")}
        >
          {narrow && hasTabs && (
            <OpenTabsLine
              ids={tabs}
              titles={titles}
              onShow={id => {
                apiRef.current?.getPanel(id)?.api.setActive();
                setShowing("tabs");
              }}
            />
          )}
          <div className="min-h-0 flex-1">
            <ViewPane view={view} />
          </div>
        </section>
        {tabsShown && !narrow && (
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize the open tabs"
            onPointerDown={startResize}
            className="w-px flex-shrink-0 cursor-col-resize bg-border transition-colors hover:bg-accent"
          />
        )}
        {/* Always mounted, so the tabs' layout survives having none open. */}
        <section
          aria-label="Open tabs"
          className={cn("min-h-0 min-w-0", !tabsShown && "hidden", narrow ? "flex-1" : "flex-shrink-0")}
          style={!narrow ? { width: `${share * 100}%` } : undefined}
        >
          <DockviewReact
            className="h-full w-full"
            theme={THEME}
            components={COMPONENTS}
            defaultTabComponent={DockTab}
            rightHeaderActionsComponent={GroupOverflow}
            disableTabsOverflowList
            onReady={ready}
            disableDnd={narrow}
            disableFloatingGroups
            singleTabMode="default"
          />
        </section>
      </div>
    </DockContext.Provider>
  );
}
