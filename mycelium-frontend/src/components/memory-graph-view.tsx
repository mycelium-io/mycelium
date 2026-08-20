// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Network } from "lucide-react";
import {
  fetchMemory,
  fetchMemoryExpanded,
  fetchMemoryGraph,
  type Memory,
  type MemoryGraph as MemoryGraphData,
} from "@/lib/api";
import { useRoomMemoryIntegrity } from "@/lib/room-data";
import { MemoryGraph } from "@/components/memory-graph";
import { DetailDrawer } from "@/components/detail-drawer";
import { MemoryDetail } from "@/components/memory-detail";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  roomName: string;
}

/** Full-page link graph; node click opens memory in `DetailDrawer` without leaving the view. */
export function MemoryGraphView({ roomName }: Props) {
  const [graph, setGraph] = useState<MemoryGraphData | null>(null);
  const [selected, setSelected] = useState<Memory | null>(null);
  const [renderedBody, setRenderedBody] = useState<string | null>(null);
  const { integrity } = useRoomMemoryIntegrity(roomName);

  useEffect(() => {
    let live = true;
    fetchMemoryGraph(roomName).then(g => {
      if (live) setGraph(g);
    });
    return () => {
      live = false;
    };
  }, [roomName]);

  // Graph nodes are keys only; fetch by key on open. Expanded body is fetched
  // in parallel so transclusions render inline. Each open takes a ticket; stale
  // responses from a superseded open are dropped.
  const openTicket = useRef(0);
  const openKey = useCallback(
    (key: string) => {
      const ticket = ++openTicket.current;
      const current = () => ticket === openTicket.current;
      setRenderedBody(null);
      fetchMemory(roomName, key).then(memory => {
        if (memory && current()) setSelected(memory);
      });
      fetchMemoryExpanded(roomName, key).then(exp => {
        if (exp.found && exp.rendered && current()) setRenderedBody(exp.rendered);
      });
    },
    [roomName],
  );

  if (!graph) {
    return (
      <div className="flex h-full flex-col gap-3 p-6">
        <Skeleton className="h-5 w-64" />
        <Skeleton className="h-full w-full" />
      </div>
    );
  }

  // Empty graph is ambiguous: hub unreachable or link index not built yet.
  // Message targets the link graph, not memory count.
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
      <MemoryGraph graph={graph} onNavigate={openKey} roomName={roomName} className="h-full" />

      <DetailDrawer
        open={selected !== null}
        onClose={() => setSelected(null)}
        title={selected?.key}
        subtitle={selected ? `v${selected.version} · ${selected.created_by}` : undefined}
      >
        {/* Following a link inside the drawer swaps it to the target, so a
            reader can walk the graph without closing and re-aiming at a node. */}
        {selected && (
          <MemoryDetail
            memory={selected}
            roomName={roomName}
            onNavigate={openKey}
            renderedBody={renderedBody}
            integrity={integrity}
          />
        )}
      </DetailDrawer>
    </>
  );
}
