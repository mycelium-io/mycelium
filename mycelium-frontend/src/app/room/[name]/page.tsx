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
          <SessionsRail roomName={roomName} activeSessionName={null} />
        </aside>

        <PanelGroup orientation="horizontal" className="flex-1" style={{ width: "100%", height: "100%" }}>
          <Panel id="activity" defaultSize={62} minSize={30} className="overflow-hidden" style={{ minWidth: 0 }}>
            <main className="flex flex-col h-full overflow-hidden" style={{ minWidth: 0 }}>
              <PaneHeader>
                <span className="caps-mono-sm text-muted">ROOM ACTIVITY</span>
              </PaneHeader>
              <div className="flex-1 overflow-hidden">
                <EventStream roomName={roomName} onMemoryChanged={handleMemoryChanged} />
              </div>
              <RoomChatBox roomName={roomName} />
            </main>
          </Panel>
          <PanelResizeHandle
            className="w-px bg-border hover:bg-accent transition-colors flex-shrink-0 relative"
            style={{ cursor: "col-resize" }}
          >
            <span aria-hidden className="absolute inset-y-0 -left-1.5 -right-1.5" />
          </PanelResizeHandle>
          <Panel id="side" defaultSize={38} minSize={22} className="overflow-hidden" style={{ minWidth: 0 }}>
            <aside className="flex flex-col h-full bg-surface/40 overflow-hidden" style={{ minWidth: 0 }}>
              <PanelGroup orientation="vertical" className="flex-1" style={{ height: "100%" }}>
                <Panel id="agents" defaultSize={40} minSize={15} className="overflow-hidden">
                  <AgentsPanel roomName={roomName} />
                </Panel>
                <PanelResizeHandle
                  className="h-px bg-border hover:bg-accent transition-colors flex-shrink-0 relative"
                  style={{ cursor: "row-resize" }}
                >
                  <span aria-hidden className="absolute inset-x-0 -top-1.5 -bottom-1.5" />
                </PanelResizeHandle>
                <Panel id="memory" defaultSize={60} minSize={20} className="overflow-hidden">
                  <div className="flex flex-col h-full">
                    <PaneHeader>
                      <span className="caps-mono-sm text-muted">MEMORY</span>
                    </PaneHeader>
                    <div className="flex-1 overflow-hidden">
                      <MemoryPanel
                        roomName={roomName}
                        masId={room?.mas_id ?? null}
                        refreshTrigger={memoryRefresh}
                      />
                    </div>
                  </div>
                </Panel>
              </PanelGroup>
            </aside>
          </Panel>
        </PanelGroup>
      </div>
    </div>
  );
}

function PaneHeader({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-shrink-0 items-center gap-2 border-b border-border bg-paper px-4 py-2.5 min-w-0">
      {children}
    </div>
  );
}
