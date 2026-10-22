// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDefaultLayout } from "react-resizable-panels";
import { type EpisodeSummary } from "@/lib/api";
import { StopNegotiation } from "@/components/stop-negotiation";
import { useRoom, useRoomRevalidate } from "@/lib/room-data";
import { useAppStream } from "@/lib/stream-hub";
import { parseFocus, type FocusTarget } from "@/lib/search";
import { parseRoomNameParam } from "@/lib/memory-routes";
import { AppShell } from "@/components/app-shell";
import { RoomDock, type RoomDockHandle } from "@/components/room-dock";
import { RoomInspector, type Tab } from "@/components/room-inspector";
import { RoomTour } from "@/components/room-tour";
import { AgentOpenerProvider } from "@/components/agent-opener";
import { CELL, StatusButton, StatusDot } from "@/components/status-items";
import { episodeUrn } from "@/lib/threads";
import { NO_FIND, loadView, parsePanelId, saveView, type FindRequest, type View } from "@/lib/room-dock";
import { useCommands, useKeyAction, useKeyScope } from "@/components/keymap-provider";
import type { PaletteCommand } from "@/lib/commands";
import { useRoomStatus } from "@/lib/use-status";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import {
  INSPECTOR_FOLD_WIDTH,
  INSPECTOR_PANEL,
  MAIN_PANEL,
  PANEL_INSPECTOR,
  PANEL_MAIN,
  ROOM_GROUP_ID,
  ROOM_PANEL_IDS,
  layoutStorage,
} from "@/lib/panel-layout";
import { useCollapsibleRail } from "@/lib/use-collapsible-rail";
import { useSheetLayout } from "@/lib/use-viewport";
import { RailSheet } from "@/components/rail-sheet";
import { RoomMenu } from "@/components/room-menu";
import { Tooltip } from "@/components/ui/tooltip";
import { Bot, Handshake, ListTodo, Lock } from "lucide-react";

function episodeSummaryLabel(episodes: EpisodeSummary[] | null): { text: string; color: string } | null {
  if (!episodes || episodes.length === 0) return null;
  const isLive = (ep: EpisodeSummary) => {
    const s = ep.subkind ?? ep.outcome;
    return s !== "converged" && s !== "resolved" && s !== "rejected";
  };
  const live = episodes.filter(isLive).length;
  if (live > 0) return { text: `${live} negotiating`, color: "var(--accent)" };
  const latest = episodes[0];
  const s = latest.subkind ?? latest.outcome;
  if (s === "rejected") return { text: "rejected", color: "var(--yellow)" };
  return { text: "converged", color: "var(--green)" };
}

/** `useSearchParams` suspends on the static prerender pass, so the room's body
 *  sits under a boundary rather than making the whole route dynamic. */
export default function RoomPage() {
  return (
    <Suspense fallback={null}>
      <RoomWithOpener />
    </Suspense>
  );
}

/** Every agent's @ tag in the room opens it, as a click in Members does. */
function RoomWithOpener() {
  const params = useParams();
  return (
    <AgentOpenerProvider roomName={parseRoomNameParam(params.name as string)}>
      <RoomWorkspace />
    </AgentOpenerProvider>
  );
}

function RoomWorkspace() {
  const params = useParams();
  const roomName = parseRoomNameParam(params.name as string);
  const [connected, setConnected] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<Tab>("agents");
  // Bumped on every ask to show a rail section, so a folded one opens even
  // when it is already the section named.
  const [inspectorReveal, setInspectorReveal] = useState(0);
  const [inspectorOpen, setInspectorOpen] = useState(true);
  // Hoisted above the state below so the tour flag can be seeded from the URL.
  const searchParamsEarly = useSearchParams();
  // `?tour=1` seeds the tour once on mount; exiting is client-only state after that.
  const [tourActive, setTourActive] = useState(() => searchParamsEarly.get("tour") === "1");
  const [inviteEngine, setInviteEngine] = useState(false);
  const [focusMemory, setFocusMemory] = useState<{ key: string; nonce: number } | null>(null);

  const handleTourExit = useCallback(() => {
    setTourActive(false);
    if (typeof window !== "undefined") window.history.replaceState(null, "", window.location.pathname);
  }, []);

  const { agents, episodes, openTasks } = useRoomStatus(roomName);
  const { room, refresh: refreshRoom } = useRoom(roomName);

  // A pushed memory/presence event refreshes every reader of this room's data
  // at once — the panels no longer take a refresh counter to find out.
  const handleMemoryChanged = useRoomRevalidate(roomName);

  const openTab = useCallback((tab: Tab) => {
    setInspectorTab(tab);
    setInspectorReveal(n => n + 1);
    setInspectorOpen(true);
  }, []);

  // The room's center is its view and a dock of tabs (`RoomDock`). What arrives before it
  // is ready (a `?focus=` on first load) waits for it rather than being lost.
  const dock = useRef<RoomDockHandle | null>(null);
  const pending = useRef<((d: RoomDockHandle) => void)[]>([]);
  const withDock = useCallback(
    (run: (d: RoomDockHandle) => void) => {
      if (dock.current?.room === roomName) run(dock.current);
      else pending.current.push(run);
    },
    [roomName],
  );
  const onDockReady = useCallback((handle: RoomDockHandle) => {
    dock.current = handle;
    const queued = pending.current;
    pending.current = [];
    queued.forEach(run => run(handle));
  }, []);
  // The view in the room's view pane, picked under the room in the Rooms rail
  // and remembered per room. Read once mounted, so the server's render and the
  // first client one agree.
  const [view, setView] = useState<View>("channel");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the saved view is client-only
    setView(loadView(roomName));
  }, [roomName]);
  const changeView = useCallback(
    (next: View) => {
      setView(next);
      saveView(roomName, next);
    },
    [roomName],
  );
  const [channelCount, setChannelCount] = useState<number | null>(null);
  const [activePanel, setActivePanel] = useState<string | null>("channel");
  const activeParsed = activePanel ? parsePanelId(activePanel) : null;
  const activeMemory = activeParsed?.kind === "memory" ? activeParsed.key : null;

  // Memories open as tabs, from the Memory rail's tree or a `[[wikilink]]`
  // anywhere in the room. The tree reveals the one opened.
  const openMemory = useCallback(
    (key: string) => {
      withDock(d => d.openMemory(key));
      setFocusMemory(prev => ({ key, nonce: (prev?.nonce ?? 0) + 1 }));
    },
    [withDock],
  );
  const showView = useCallback((next: View) => withDock(d => d.showView(next)), [withDock]);
  const roomViews = useMemo(() => ({ view, onView: showView, channelCount }), [view, showView, channelCount]);

  const handleEngineInviteShown = useCallback(() => setInviteEngine(false), []);

  // A board row's thread chip, or a ping in the channel. Both name the same
  // thing — the episode — because a row and its thread are one object.
  const openThread = useCallback((episode: string) => withDock(d => d.openThread(episode)), [withDock]);

  // Arriving from search: `?focus=<type>:<id>` names one item in this room.
  // Reveal the surface it lives on, then hand the id to the panel that owns the
  // row — a result opens the item, not just the room it is in. The parameter is
  // consumed on arrival so returning to a rail later doesn't re-select, and so
  // jumping to the same item twice is a change the panel sees both times.
  const searchParams = searchParamsEarly;
  const router = useRouter();
  const focusParam = searchParams.get("focus");
  const [focus, setFocus] = useState<FocusTarget | null>(null);
  const clearFocus = useCallback(() => setFocus(null), []);
  // A message said in the channel, opened from elsewhere in the room (a file
  // in the Files tab names the message it was posted with): the same reveal a
  // search hit gets, without a trip through the URL.
  const openMessage = useCallback(
    (id: string) => {
      setFocus({ type: "message", id });
      showView("channel");
    },
    [showView],
  );
  // Acted on once per value: the request is a one-shot, and a re-run over the
  // same parameter would drag you back to the item you had just dismissed.
  const applied = useRef<string | null>(null);

  useAppStream((data) => {
    const msg = data as { type?: string; room_name?: string };
    if (msg.type === "room_deleted" && msg.room_name === roomName) router.push("/");
  });

  useEffect(() => {
    if (applied.current === focusParam) return;
    applied.current = focusParam;
    const target = parseFocus(focusParam);
    if (!target) return;
    if (target.type === "memory") {
      // A memory opens as a tab in its room, like any other way into one. The
      // request is a one-shot, so acting on it here is the point.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      openMemory(target.id);
      router.replace(`/room/${encodeURIComponent(roomName)}`, { scroll: false });
      return;
    }
    // The focus target is consumed here rather than derived: it has to outlive
    // the parameter, which is cleared as soon as it has been acted on.
    setFocus(target);
    if (target.type === "episode") openThread(episodeUrn(roomName, target.id));
    else if (target.type === "agent") openTab("agents");
    else if (target.type === "message") showView("channel");
    router.replace(`/room/${encodeURIComponent(roomName)}`, { scroll: false });
  }, [focusParam, openMemory, openTab, openThread, showView, roomName, router]);

  // Room-scoped keybinds: the panes, the tabs, the inspector rails, and the
  // composer are all reachable without a pointer. The chat box focuses the
  // textarea itself; this only makes sure the pane holding it is the one on
  // screen.
  useKeyScope("room");
  // ⌘F belongs to the page rather than to any one view: it finds in whatever is
  // in front (the channel, a thread, a memory, the board). The counter is the
  // message: that view opens (or re-focuses) its find bar on every press,
  // including the ones where the bar is already open.
  const [findRequest, setFindRequest] = useState<FindRequest>(NO_FIND);
  useKeyAction("chat.find", () => setFindRequest(r => ({ id: activePanel, n: r.n + 1 })), {
    enabled: activePanel !== null,
  });
  useKeyAction("pane.channel", () => showView("channel"));
  useKeyAction("pane.stream", () => showView("stream"));
  useKeyAction("pane.board", () => showView("board"));
  useKeyAction("pane.files", () => showView("files"));
  useKeyAction("pane.schedules", () => showView("schedules"));
  // False with no tab to close (only the Channel is left), so in the desktop
  // app ⌘W goes on to close the window.
  useKeyAction("tab.close", () => (dock.current?.room === roomName ? dock.current.closeActive() : false));
  useKeyAction("tab.reopen", () => withDock(d => d.reopenClosed()));
  useKeyAction("tab.split", () => withDock(d => d.splitActive()));
  useKeyAction("group.next", () => withDock(d => d.focusGroup(1)));
  useKeyAction("group.prev", () => withDock(d => d.focusGroup(-1)));
  useKeyAction("rail.agents", () => openTab("agents"));
  useKeyAction("rail.memory", () => openTab("memory"));
  useKeyAction("rail.toggle", () => setInspectorOpen(open => !open));
  useKeyAction("focus.chat", () => showView("channel"));

  // The palette reaches the invite form wherever you are in the room: open the
  // rail it lives behind, and ask it to show itself. A one-shot request the
  // panel clears once consumed, so returning to the rail later doesn't reopen it.
  const commands = useMemo<PaletteCommand[]>(
    () => [
      {
        id: "engine.invite",
        title: "Invite an engine",
        group: "Inspector",
        keywords: ["aligner", "synthesizer", "member", "add"],
        run: () => {
          openTab("agents");
          setInviteEngine(true);
        },
      },
    ],
    [openTab],
  );
  useCommands(commands);

  const episodeLabel = useMemo(() => episodeSummaryLabel(episodes), [episodes]);

  // Chat vs. inspector is a reading preference, so the split is remembered per
  // browser rather than reset on every visit.
  // Both callbacks: `onLayoutChanged` fires when a drag is committed, but these
  // are nested groups — widening the rooms rail resizes this group's container
  // without anyone touching its own seam, and only `onLayoutChange` sees that.
  // Saving on the commit alone leaves the stored percentages describing a
  // container width that no longer exists, and the rail comes back a few dozen
  // pixels off after a reload.
  const { defaultLayout, onLayoutChange, onLayoutChanged } = useDefaultLayout({
    id: ROOM_GROUP_ID,
    storage: layoutStorage,
    panelIds: ROOM_PANEL_IDS,
  });

  // Folded, the inspector is a plain strip beside the group rather than a panel
  // inside it: a panel that isn't there can't be squeezed, and it comes back at
  // the width it left at.
  // Too narrow for a split: the rail leaves the group and becomes a sheet over
  // the room, with its icon strip left in place to open and close it.
  const sheetLayout = useSheetLayout();
  const inspectorInPanel = inspectorOpen && !sheetLayout;

  const {
    panelRef: inspectorPanelRef,
    size: inspectorSize,
    onResize: onInspectorResize,
  } = useCollapsibleRail({
    foldWidth: INSPECTOR_FOLD_WIDTH,
    defaultWidth: INSPECTOR_PANEL.default,
    open: inspectorOpen,
    onOpenChange: setInspectorOpen,
  });

  const closeInspector = useCallback(() => setInspectorOpen(false), []);

  // The rail, wherever it is standing: a panel in the split, the icon strip
  // beside it, or a sheet over the room. One call site rather than three
  // copies of eleven props — they have to stay identical for the rail to keep
  // its tab and its selection as the window crosses the breakpoint.
  const inspector = (open: boolean, onOpenChange = setInspectorOpen as (open: boolean) => void) => (
    <RoomInspector
      roomName={roomName}
      masId={room?.mas_id ?? null}
      tab={inspectorTab}
      reveal={inspectorReveal}
      onTabChange={setInspectorTab}
      open={open}
      onOpenChange={onOpenChange}
      engineInvite={inviteEngine}
      onEngineInviteShown={handleEngineInviteShown}
      focus={focus}
      onFocusConsumed={clearFocus}
      focusMemory={focusMemory}
      onOpenMemory={openMemory}
      activeMemoryKey={activeMemory}
    />
  );

  const statusLeft = (
    <>
      <span
        // A stable hook for anything that has to wait until the room is
        // actually connected — the screenshot pipeline gates on this rather
        // than on the label text, which is a translation away from breaking.
        data-connection={connected ? "live" : "reconnecting"}
        // The bar's one standing color: whether this room is connected.
        className={`${CELL} flex-shrink-0 hover:bg-transparent`}
      >
        <StatusDot tone={connected ? "ok" : "warn"} />
        {connected ? "Live" : "Reconnecting…"}
      </span>
      {episodeLabel && (
        // A plain, ambient signal that a negotiation is live in the room —
        // shown without interaction.
        <span className={`${CELL} flex-shrink-0 hover:bg-transparent`}>
          <Handshake />
          {episodeLabel.text}
        </span>
      )}
      <StopNegotiation roomName={roomName} episodes={episodes} onStopped={handleMemoryChanged} />
      {openTasks !== null && openTasks > 0 && (
        <StatusButton
          onClick={() => showView("board")}
          tooltip="Open the board"
          action="pane.board"
          className="flex-shrink-0"
        >
          <ListTodo />
          <span className="tabular">
            {openTasks} open task{openTasks === 1 ? "" : "s"}
          </span>
        </StatusButton>
      )}
      {agents !== null && (
        <StatusButton
          onClick={() => openTab("agents")}
          tooltip="View agents"
          action="rail.agents"
          className="flex-shrink-0"
        >
          <Bot />
          <span className="tabular">
            {agents} agent{agents === 1 ? "" : "s"}
          </span>
        </StatusButton>
      )}
    </>
  );

  // The name, then the room's own menu beside it (its id, deleting it): what
  // you do to the room sits with the room, not among the app-wide buttons.
  const header = (
    <>
      <span className="flex min-w-0 items-center gap-1.5 px-1.5 font-medium text-text">
        <span className="truncate">{roomName}</span>
        {room?.is_public === false && (
          <Tooltip content="Private: listed only for its owner and members">
            <Lock aria-label="private" className="size-3.5 flex-shrink-0 text-faint" />
          </Tooltip>
        )}
        {/* DESIGN MOCKUP (local branch): a shared room says so before you post.
            A room only for you already has its lock. */}
        {room?.is_public !== false && <span className="ml-1 text-micro font-normal text-faint">Shared</span>}
      </span>
      <RoomMenu
        roomName={roomName}
        masId={room?.mas_id ?? null}
        isPrivate={room?.is_public === false}
        onChanged={refreshRoom}
      />
    </>
  );

  return (
    <AppShell
      activeRoom={roomName}
      header={header}
      statusLeft={statusLeft}
      roomViews={roomViews}
    >
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <ResizablePanelGroup
          className="min-h-0 flex-1"
          defaultLayout={defaultLayout}
          // Only while both panels are here: a one-panel layout saved over the
          // split would be the rail's remembered width, gone.
          onLayoutChange={inspectorInPanel ? onLayoutChange : undefined}
          onLayoutChanged={inspectorInPanel ? onLayoutChanged : undefined}
        >
          <ResizablePanel
            id={PANEL_MAIN}
            // Under the sheet layout it holds one surface at whatever width the
            // window has, and a floor wider than the window is a constraint
            // nothing satisfies.
            minSize={sheetLayout ? "0px" : MAIN_PANEL.min}
            className="flex min-w-0"
          >
            <main className="flex min-w-0 flex-1 overflow-hidden">
              <RoomDock
                // One dock per room: its layout, its tabs and their state are
                // the room's, and switching rooms starts from that room's own.
                key={roomName}
                roomName={roomName}
                view={view}
                onViewChange={changeView}
                onChannelCount={setChannelCount}
                onMemoryChanged={handleMemoryChanged}
                onConnectionChange={setConnected}
                focusMessageId={focus?.type === "message" ? focus.id : null}
                onFocusConsumed={clearFocus}
                find={findRequest}
                narrow={sheetLayout}
                onActiveChange={setActivePanel}
                onReady={onDockReady}
                onOpenMemory={openMemory}
                onOpenThread={openThread}
                onOpenMessage={openMessage}
              />
            </main>
          </ResizablePanel>
          {inspectorInPanel && (
            <>
              <ResizableHandle withHandle />
              <ResizablePanel
                id={PANEL_INSPECTOR}
                panelRef={inspectorPanelRef}
                collapsible
                collapsedSize={INSPECTOR_PANEL.collapsed}
                defaultSize={inspectorSize}
                minSize={INSPECTOR_PANEL.min}
                maxSize={INSPECTOR_PANEL.max}
                groupResizeBehavior="preserve-pixel-size"
                className="flex"
                onResize={onInspectorResize}
              >
                {inspector(true)}
              </ResizablePanel>
            </>
          )}
        </ResizablePanelGroup>

        {!inspectorInPanel && (
          <div className="flex w-12 flex-none border-l border-border">
            {/* A toggle rather than "expand": while the sheet is open the strip
                is still on screen behind it, and the control that opened it is
                the one a reader reaches for to put it away. */}
            {inspector(false, () => setInspectorOpen(open => !open))}
          </div>
        )}
        <RailSheet
          open={sheetLayout && inspectorOpen}
          onClose={closeInspector}
          side="right"
          label="Room inspector"
        >
          {inspector(true, closeInspector)}
        </RailSheet>
      </div>

      <RoomTour
        active={tourActive}
        setEditorView={showView}
        setInspectorTab={setInspectorTab}
        onExit={handleTourExit}
      />
    </AppShell>
  );
}
