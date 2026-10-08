// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import { Network } from "lucide-react";
import { fetchMemoryGraph, type MemoryGraph as MemoryGraphData } from "@/lib/api";
import { MemoryGraph } from "@/components/memory-graph";
import { DetailDrawer } from "@/components/detail-drawer";
import { MemoryView } from "@/components/memory-view";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  roomName: string;
}

/** Fetches a room's link graph and renders it full-page (#599). Clicking a node
 *  opens that memory in a drawer over the graph, drawn by the same `MemoryView`
 *  as everywhere else, rather than navigating away: the graph is the thing
 *  you're exploring, so losing your pan/zoom and hand-arranged layout to read
 *  one memory would defeat the view. */
export function MemoryGraphView({ roomName }: Props) {
  const [graph, setGraph] = useState<MemoryGraphData | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);

  useEffect(() => {
    let live = true;
    fetchMemoryGraph(roomName).then(g => {
      if (live) setGraph(g);
    });
    return () => {
      live = false;
    };
  }, [roomName]);

  if (!graph) {
    return (
      <div className="flex h-full flex-col gap-3 p-6">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-full w-full" />
      </div>
    );
  }

  // An empty payload is genuinely ambiguous: `fetchMemoryGraph` degrades to
  // `{nodes: [], edges: []}` for an unreachable hub, and the backend returns
  // the same for a room whose link index hasn't been built yet (memories
  // written straight to disk stay unindexed until `mycelium memory reindex`).
  // Claiming "no memories" would contradict the Memory rail beside it, so the
  // empty state speaks only to what this payload actually proves.
  if (graph.nodes.length === 0) {
    return (
      <EmptyState
        icon={Network}
        title="No link graph for this room"
        description="Either nothing has been written here yet, or the room's link index hasn't been built — run `mycelium memory reindex` if the Memory rail lists memories."
      />
    );
  }

  return (
    <>
      <MemoryGraph graph={graph} onNavigate={setOpenKey} roomName={roomName} className="h-full" />

      <DetailDrawer open={openKey !== null} onClose={() => setOpenKey(null)} title={openKey}>
        {/* Following a link inside the drawer swaps it to the target, so a
            reader can walk the graph without closing and re-aiming at a node.
            Keyed on the memory, so a slow answer for the last one can't land
            under the next one's title. */}
        {openKey && (
          <MemoryView key={openKey} roomName={roomName} memoryKey={openKey} onOpenMemory={setOpenKey} />
        )}
      </DetailDrawer>
    </>
  );
}
