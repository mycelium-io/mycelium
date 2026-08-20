// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { AppShell } from "@/components/app-shell";
import { MemoryGraphView } from "@/components/memory-graph-view";
import { GlobalStatusItems } from "@/components/status-items";
import { ActingAsPicker } from "@/components/acting-as-picker";

/** Full-page memory link graph at `/room/{room}/graph`. */
export default function MemoryGraphPage() {
  const params = useParams();
  const roomName = params.name as string;

  return (
    <AppShell
      activeRoom={roomName}
      statusLeft={<span className="text-micro text-muted-foreground">Memory graph</span>}
      statusRight={<GlobalStatusItems />}
    >
      {/* Room-page header: identity line, actor picker, and back link. */}
      <header className="flex h-[52px] flex-shrink-0 items-center gap-3 border-b border-border bg-surface/50 px-5">
        <Link
          href={`/room/${encodeURIComponent(roomName)}`}
          className="inline-flex items-center gap-1 rounded-md px-1.5 py-1 text-label text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          <ArrowLeft className="size-3.5" />
          Room
        </Link>
        <span className="truncate text-ui font-semibold text-text">{roomName}</span>
        <span className="truncate text-label text-faint">memory graph</span>
        <div className="ml-auto flex-shrink-0">
          <ActingAsPicker />
        </div>
      </header>

      <div className="min-h-0 flex-1">
        <MemoryGraphView roomName={roomName} />
      </div>
    </AppShell>
  );
}
