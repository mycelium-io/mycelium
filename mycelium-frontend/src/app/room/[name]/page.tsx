// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { fetchRoom } from "@/lib/api";
import { AgentsPanel } from "@/components/agents-panel";
import { EventStream } from "@/components/event-stream";
import { MemoryPanel } from "@/components/memory-panel";
import { RoomChatBox } from "@/components/room-chat-box";
import { RoomPlanHeader } from "@/components/room-plan-header";
import { SessionsRail } from "@/components/sessions-rail";
import { MainTopBar } from "@/components/main-top-bar";
import { SubNav, type Crumb } from "@/components/sub-nav";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";

interface Room {
  name: string;
  coordination_state: string;
  mas_id?: string | null;
  is_persistent?: boolean;
  parent_namespace?: string | null;
}

export default function RoomPage() {
  const params = useParams();
  const roomName = params.name as string;
  const [room, setRoom] = useState<Room | null>(null);
  const [memoryRefresh, setMemoryRefresh] = useState(0);
  const [memoryOpen, setMemoryOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchRoom(roomName).then((r: Room) => { if (!cancelled) setRoom(r); }).catch(() => {});
    load();
    const t = setInterval(load, 8000);
    return () => { cancelled = true; clearInterval(t); };
  }, [roomName]);

  const handleMemoryChanged = useCallback(() => {
    setMemoryRefresh(n => n + 1);
  }, []);

  const crumbs: Crumb[] = [
    { label: "rooms", href: "/" },
    { sigil: "rm:", label: roomName },
  ];

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
      <MainTopBar activeTab="rooms" />
      <SubNav crumbs={crumbs} />

      <div className="flex flex-1 overflow-hidden">
        <aside className="w-[240px] flex-shrink-0 border-r border-border">
          <PanelGroup orientation="vertical" className="h-full" style={{ height: "100%" }}>
            <Panel id="agents" defaultSize={32} minSize={12} className="overflow-hidden">
              <AgentsPanel roomName={roomName} />
            </Panel>
            <PanelResizeHandle
              className="h-px bg-border hover:bg-accent transition-colors flex-shrink-0 relative"
              style={{ cursor: "row-resize" }}
            >
              <span aria-hidden className="absolute inset-x-0 -top-1.5 -bottom-1.5" />
            </PanelResizeHandle>
            <Panel id="sessions" defaultSize={68} minSize={20} className="overflow-hidden">
              <SessionsRail roomName={roomName} activeSessionName={null} />
            </Panel>
          </PanelGroup>
        </aside>

        <main className="flex flex-1 flex-col overflow-hidden">
          <RoomPlanHeader roomName={roomName} refreshTrigger={memoryRefresh} />
          <div className="flex-1 overflow-hidden">
            <EventStream roomName={roomName} onMemoryChanged={handleMemoryChanged} />
          </div>
          <RoomChatBox roomName={roomName} />
        </main>

        {/* Memory: collapsible right rail. Thin always-visible toggle on the edge. */}
        <aside
          className="flex flex-shrink-0 border-l border-border bg-surface/40 overflow-hidden transition-[width] duration-200"
          style={{ width: memoryOpen ? 420 : 36 }}
        >
          <button
            onClick={() => setMemoryOpen(o => !o)}
            className="w-9 flex-shrink-0 border-r border-border bg-paper hover:bg-paper/70 transition-colors flex items-start justify-center pt-4"
            aria-label={memoryOpen ? "collapse memory" : "expand memory"}
          >
            <span
              className="caps-mono-sm text-muted hover:text-accent"
              style={{ writingMode: "vertical-rl", letterSpacing: "0.2em" }}
            >
              {memoryOpen ? "× MEMORY" : "MEMORY"}
            </span>
          </button>
          {memoryOpen && (
            <div className="flex-1 min-w-0 overflow-hidden">
              <MemoryPanel
                roomName={roomName}
                masId={room?.mas_id ?? null}
                refreshTrigger={memoryRefresh}
              />
            </div>
          )}
        </aside>
      </div>
    </div>
  );
}
