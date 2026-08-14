// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchRoom, logFetchError, type EpisodeSummary } from "@/lib/api";
import { AppShell } from "@/components/app-shell";
import { EventStream, type View, type NegotiationPhase } from "@/components/event-stream";
import { RoomChatBox } from "@/components/room-chat-box";
import { RoomInspector, type Tab } from "@/components/room-inspector";
import { RoomTour } from "@/components/room-tour";
import { GlobalStatusItems, StatusButton } from "@/components/status-items";
import { ActingAsPicker } from "@/components/acting-as-picker";
import { useRoomStatus } from "@/lib/use-status";

interface Room {
  name: string;
  mas_id?: string | null;
  is_persistent?: boolean;
  parent_namespace?: string | null;
}

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

export default function RoomPage() {
  const params = useParams();
  const roomName = params.name as string;
  const [room, setRoom] = useState<Room | null>(null);
  const [memoryRefresh, setMemoryRefresh] = useState(0);
  const [connected, setConnected] = useState(false);
  const [inspectorTab, setInspectorTab] = useState<Tab>("agents");
  const [inspectorOpen, setInspectorOpen] = useState(true);
  const [editorView, setEditorView] = useState<View>("channel");
  const [negPhase, setNegPhase] = useState<NegotiationPhase>("idle");
  const [tourActive, setTourActive] = useState(false);

  // Start the coached tour when arriving via "Run a sample coordination".
  useEffect(() => {
    if (typeof window !== "undefined" && new URLSearchParams(window.location.search).get("tour") === "1") {
      setTourActive(true);
    }
  }, []);

  const handleTourExit = useCallback(() => {
    setTourActive(false);
    if (typeof window !== "undefined") window.history.replaceState(null, "", window.location.pathname);
  }, []);

  const { agents, episodes, openTasks } = useRoomStatus(roomName, memoryRefresh);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchRoom(roomName).then((r: Room) => { if (!cancelled) setRoom(r); }).catch(logFetchError("fetchRoom"));
    load();
    const t = setInterval(load, 8000);
    return () => { cancelled = true; clearInterval(t); };
  }, [roomName]);

  const handleMemoryChanged = useCallback(() => {
    setMemoryRefresh(n => n + 1);
  }, []);

  const openTab = useCallback((tab: Tab) => {
    setInspectorTab(tab);
    setInspectorOpen(true);
  }, []);

  const episodeLabel = useMemo(() => episodeSummaryLabel(episodes), [episodes]);

  const statusLeft = (
    <>
      <span
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
        <StatusButton onClick={() => openTab("episodes")} title="View episodes">
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
        <StatusButton onClick={() => openTab("agents")} title="View agents">
          <span className="tabular">{agents} agent{agents === 1 ? "" : "s"}</span>
        </StatusButton>
      )}
      <GlobalStatusItems />
    </>
  );

  return (
    <AppShell activeRoom={roomName} statusLeft={statusLeft} statusRight={statusRight}>
      {/* Room header: identity + room-level context, spanning the workspace. */}
      <header className="flex h-[52px] flex-shrink-0 items-center gap-3 border-b border-border bg-surface/50 px-5">
        <span className="text-ui font-semibold text-text truncate">{roomName}</span>
        {room?.mas_id && (
          <span className="font-mono text-micro text-faint truncate" title="MAS id">{room.mas_id}</span>
        )}
        <div className="ml-auto flex-shrink-0">
          <ActingAsPicker />
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        <main className="flex min-w-0 flex-1 flex-col overflow-hidden">
          <div className="flex-1 overflow-hidden">
            <EventStream
              roomName={roomName}
              onMemoryChanged={handleMemoryChanged}
              onConnectionChange={setConnected}
              onNegotiationPhaseChange={setNegPhase}
              planRefreshTrigger={memoryRefresh}
              view={editorView}
              onViewChange={setEditorView}
              suppressInvites={tourActive}
            />
          </div>
          <RoomChatBox roomName={roomName} />
        </main>

        <RoomInspector
          roomName={roomName}
          masId={room?.mas_id ?? null}
          memoryRefresh={memoryRefresh}
          tab={inspectorTab}
          onTabChange={setInspectorTab}
          open={inspectorOpen}
          onOpenChange={setInspectorOpen}
        />
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
