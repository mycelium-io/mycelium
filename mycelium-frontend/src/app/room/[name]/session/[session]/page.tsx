// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useParams } from "next/navigation";
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
        <aside className="w-[240px] flex-shrink-0 border-r border-border">
          <SessionsRail roomName={roomName} activeSessionName={sessionRoom} />
        </aside>

        <main className="flex flex-1 flex-col overflow-hidden">
          <SessionView sessionRoom={sessionRoom} />
        </main>
      </div>
    </div>
  );
}
