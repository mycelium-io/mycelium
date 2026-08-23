// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useParams, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useDefaultLayout } from "react-resizable-panels";
import { type EpisodeSummary } from "@/lib/api";
import { useRoom, useRoomRevalidate } from "@/lib/room-data";
import { parseFocus, type FocusTarget } from "@/lib/search";
import { memoryHref } from "@/lib/memory-routes";
import { AppShell } from "@/components/app-shell";
import { EventStream, type View, type NegotiationPhase } from "@/components/event-stream";
import { RoomChatBox } from "@/components/room-chat-box";
import { RoomInspector, type Tab } from "@/components/room-inspector";
import { RoomTour } from "@/components/room-tour";
import { GlobalStatusItems, StatusButton } from "@/components/status-items";
import { Tooltip } from "@/components/ui/tooltip";
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
      <RoomWorkspace />
    </Suspense>
  );
}

function RoomWorkspace() {
  const params = useParams();
  const roomName = params.name as string;
  const [connected, setConnected] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<Tab>("agents");
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [editorView, setEditorView] = useState<View>("channel");
  const [negPhase, setNegPhase] = useState<NegotiationPhase>("idle");
  // Hoisted above the state below so the tour flag can be seeded from the URL.
  const searchParamsEarly = useSearchParams();
  // `?tour=1` seeds the tour once on mount; exiting is client-only state after that.
  const [tourActive, setTourActive] = useState(() => searchParamsEarly.get("tour") === "1");
  const [inviteEngine, setInviteEngine] = useState(false);
  const [focusMemory, setFocusMemory] = useState<{ key: string; nonce: number } | null>(null);
  const [focusEpisode, setFocusEpisode] = useState<{ shortId: string; nonce: number } | null>(null);

  const handleTourExit = useCallback(() => {
    setTourActive(false);
    if (typeof window !== "undefined") window.history.replaceState(null, "", window.location.pathname);
  }, []);

  const { agents, episodes, openTasks } = useRoomStatus(roomName);
  const { room } = useRoom(roomName);

  // A pushed memory/presence event refreshes every reader of this room's data
  // at once — the panels no longer take a refresh counter to find out.
  const handleMemoryChanged = useRoomRevalidate(roomName);

  const openTab = useCallback((tab: Tab) => {
    setInspectorTab(tab);
    setInspectorOpen(true);
  }, []);

  // A `[[wikilink]]` clicked in chat opens the Memory rail on that key.
  const openMemory = useCallback((key: string) => {
    setInspectorTab("memory");
    setInspectorOpen(true);
    setFocusMemory(prev => ({ key, nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);

  // An episode tag clicked in chat opens the Episodes rail on that episode.
  const openEpisode = useCallback((shortId: string) => {
    setInspectorTab("episodes");
    setInspectorOpen(true);
    setFocusEpisode(prev => ({ shortId, nonce: (prev?.nonce ?? 0) + 1 }));
  }, []);

  const handleEngineInviteShown = useCallback(() => setInviteEngine(false), []);

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
  // Acted on once per value: the request is a one-shot, and a re-run over the
  // same parameter would drag you back to the item you had just dismissed.
  const applied = useRef<string | null>(null);

  useEffect(() => {
    if (applied.current === focusParam) return;
    applied.current = focusParam;
    const target = parseFocus(focusParam);
    if (!target) return;
    if (target.type === "memory") {
      router.replace(memoryHref(roomName, target.id));
      return;
    }
    // The focus target is consumed here rather than derived: it has to outlive
    // the parameter, which is cleared as soon as it has been acted on.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFocus(target);
    if (target.type === "episode") openTab("episodes");
    else if (target.type === "agent") openTab("agents");
    else if (target.type === "message") setEditorView("channel");
    router.replace(`/room/${encodeURIComponent(roomName)}`, { scroll: false });
  }, [focusParam, openTab, roomName, router]);

  // Room-scoped keybinds: the panes, the inspector rails, and the composer are
  // all reachable without a pointer. The chat box focuses the textarea itself;
  // this only makes sure the pane holding it is the one on screen.
  useKeyScope("room");
  useKeyAction("pane.channel", () => setEditorView("channel"));
  useKeyAction("pane.negotiate", () => setEditorView("negotiate"));
  useKeyAction("pane.plan", () => setEditorView("plan"));
  useKeyAction("pane.network", () => setEditorView("network"));
  useKeyAction("rail.agents", () => openTab("agents"));
  useKeyAction("rail.episodes", () => openTab("episodes"));
  useKeyAction("rail.memory", () => openTab("memory"));
  useKeyAction("rail.toggle", () => setInspectorOpen(open => !open));
  useKeyAction("focus.chat", () => setEditorView("channel"));

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

  const statusLeft = (
    <>
      <span
        // A stable hook for anything that has to wait until the room is
        // actually connected — the screenshot pipeline gates on this rather
        // than on the label text, which is a translation away from breaking.
        data-connection={connected ? "live" : "reconnecting"}
        className="rounded px-1.5 py-0.5 text-micro font-medium"
        style={{
          color: connected ? "var(--green)" : "var(--yellow)",
          background: connected
            ? "color-mix(in srgb, var(--green) 14%, transparent)"
            : "color-mix(in srgb, var(--yellow) 14%, transparent)",
        }}
      >
        {connected ? "Live" : "Reconnecting…"}
      </span>
      {episodeLabel && (
        <StatusButton onClick={() => openTab("episodes")} tooltip="View episodes" action="rail.episodes">
          <span style={{ color: episodeLabel.color }}>{episodeLabel.text}</span>
        </StatusButton>
      )}
      {openTasks !== null && openTasks > 0 && (
        <span className="px-1.5 tabular">{openTasks} open task{openTasks === 1 ? "" : "s"}</span>
      )}
    </>
  );

  const statusRight = (
    <>
      {agents !== null && (
        <StatusButton onClick={() => openTab("agents")} tooltip="View agents" action="rail.agents">
          <span className="tabular">{agents} agent{agents === 1 ? "" : "s"}</span>
        </StatusButton>
      )}
      <GlobalStatusItems />
    </>
  );

  const header = (
    <>
      <span className="text-ui font-semibold text-text truncate">{roomName}</span>
      {room?.mas_id && (
        <Tooltip content="MAS id" side="bottom">
          <span className="font-mono text-micro text-faint truncate">{room.mas_id}</span>
        </Tooltip>
      )}
    </>
  );

  return (
    <AppShell
      activeRoom={roomName}
      header={header}
      statusLeft={statusLeft}
      statusRight={statusRight}
    >
      <div className="flex min-h-0 flex-1 overflow-hidden">
        <ResizablePanelGroup
          className="min-h-0 flex-1"
          defaultLayout={defaultLayout}
          // Only while both panels are here: a one-panel layout saved over the
          // split would be the rail's remembered width, gone.
          onLayoutChange={inspectorOpen ? onLayoutChange : undefined}
          onLayoutChanged={inspectorOpen ? onLayoutChanged : undefined}
        >
          <ResizablePanel id={PANEL_MAIN} minSize={MAIN_PANEL.min} className="flex min-w-0">
            <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
              <div className="flex-1 overflow-hidden">
                <EventStream
                  roomName={roomName}
                  onMemoryChanged={handleMemoryChanged}
                  onConnectionChange={setConnected}
                  onNegotiationPhaseChange={setNegPhase}
                  onOpenMemory={openMemory}
                  onOpenEpisode={openEpisode}
                  view={editorView}
                  onViewChange={setEditorView}
                  suppressInvites={tourActive}
                  focusMessageId={focus?.type === "message" ? focus.id : null}
                  onFocusConsumed={clearFocus}
                />
              </div>
              <RoomChatBox roomName={roomName} className={editorView !== "channel" ? "hidden" : undefined} />
            </main>
          </ResizablePanel>
          {inspectorOpen && (
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
                <RoomInspector
                  roomName={roomName}
                  masId={room?.mas_id ?? null}
                  tab={inspectorTab}
                  onTabChange={setInspectorTab}
                  open={inspectorOpen}
                  onOpenChange={setInspectorOpen}
                  engineInvite={inviteEngine}
                  onEngineInviteShown={handleEngineInviteShown}
                  focus={focus}
                  onFocusConsumed={clearFocus}
                  focusMemory={focusMemory}
                  focusEpisode={focusEpisode}
                />
              </ResizablePanel>
            </>
          )}
        </ResizablePanelGroup>

        {!inspectorOpen && (
          <div className="flex w-12 flex-none border-l border-border">
            <RoomInspector
            roomName={roomName}
            masId={room?.mas_id ?? null}
            tab={inspectorTab}
            onTabChange={setInspectorTab}
            open={inspectorOpen}
            onOpenChange={setInspectorOpen}
            engineInvite={inviteEngine}
            onEngineInviteShown={handleEngineInviteShown}
            focus={focus}
            onFocusConsumed={clearFocus}
            focusMemory={focusMemory}
            focusEpisode={focusEpisode}
            />
          </div>
        )}
      </div>

      <RoomTour
        active={tourActive}
        phase={negPhase}
        setEditorView={setEditorView}
        setInspectorTab={setInspectorTab}
        onExit={handleTourExit}
      />
    </AppShell>
  );
}
