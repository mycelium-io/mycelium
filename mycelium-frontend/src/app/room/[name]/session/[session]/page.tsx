// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useParams } from "next/navigation";
import { Group as PanelGroup, Panel, Separator as PanelResizeHandle } from "react-resizable-panels";
import { ParticipantsPanel } from "@/components/participants-panel";
import { SessionsRail } from "@/components/sessions-rail";
import { SessionView } from "@/components/session-view";
import { MainTopBar } from "@/components/main-top-bar";
import { SubNav, type Crumb } from "@/components/sub-nav";

function shortSessionName(sessionRoom: string): string {
  const tail = sessionRoom.split(":").pop() ?? sessionRoom;
  return tail.length > 12 ? `${tail.slice(0, 8)}…${tail.slice(-3)}` : tail;
}

export default function SessionPage() {
  const params = useParams();
  const roomName = params.name as string;
  const sessionId = params.session as string;
  const sessionRoom = `${roomName}:session:${sessionId}`;

  const crumbs: Crumb[] = [
    { label: "rooms", href: "/" },
    { sigil: "rm:", label: roomName, href: `/room/${encodeURIComponent(roomName)}` },
    { sigil: "ss:", label: shortSessionName(sessionRoom) },
  ];

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
      <MainTopBar activeTab="rooms" />
      <SubNav crumbs={crumbs} />

      <div className="flex flex-1 overflow-hidden">
        {/* Left rail mirrors the room page: participants on top, sessions
            list below, resizable split. */}
        <aside className="w-[240px] flex-shrink-0 border-r border-border">
          <PanelGroup orientation="vertical" className="h-full" style={{ height: "100%" }}>
            <Panel id="participants" defaultSize={32} minSize={12} className="overflow-hidden">
              <ParticipantsPanel sessionRoom={sessionRoom} />
            </Panel>
            <PanelResizeHandle
              className="h-px bg-border hover:bg-accent transition-colors flex-shrink-0 relative"
              style={{ cursor: "row-resize" }}
            >
              <span aria-hidden className="absolute inset-x-0 -top-1.5 -bottom-1.5" />
            </PanelResizeHandle>
            <Panel id="sessions" defaultSize={68} minSize={20} className="overflow-hidden">
              <SessionsRail roomName={roomName} activeSessionName={sessionRoom} />
            </Panel>
          </PanelGroup>
        </aside>

        <main className="flex flex-1 flex-col overflow-hidden">
          <SessionView sessionRoom={sessionRoom} />
        </main>
      </div>
    </div>
  );
}
