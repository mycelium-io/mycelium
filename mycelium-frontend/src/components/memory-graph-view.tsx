// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Network } from "lucide-react";
import {
  fetchMemory,
  fetchMemoryExpanded,
  fetchMemoryGraph,
  fetchMemoryIntegrity,
  type Memory,
  type MemoryGraph as MemoryGraphData,
  type MemoryLinksIntegrity,
} from "@/lib/api";
import { MemoryGraph } from "@/components/memory-graph";
import { DetailDrawer } from "@/components/detail-drawer";
import { MemoryDetail } from "@/components/memory-detail";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";

interface Props {
  roomName: string;
}

/** Fetches a room's link graph and renders it full-page (#599). Clicking a node
 *  opens that memory in the same right-hand `DetailDrawer` the Memory rail uses,
 *  over the graph rather than navigating away — the graph is the thing you're
 *  exploring, so losing your pan/zoom and hand-arranged layout to read one
 *  memory would defeat the view. */
export function MemoryGraphView({ roomName }: Props) {
  const [graph, setGraph] = useState<MemoryGraphData | null>(null);
  const [selected, setSelected] = useState<Memory | null>(null);
  const [renderedBody, setRenderedBody] = useState<string | null>(null);
  const [integrity, setIntegrity] = useState<MemoryLinksIntegrity | null>(null);

  useEffect(() => {
    let live = true;
    fetchMemoryGraph(roomName).then(g => {
      if (live) setGraph(g);
    });
    // Room-wide, so it's fetched once here rather than per opened memory;
    // `MemoryDetail` slices out the entry for whichever key is showing.
    fetchMemoryIntegrity(roomName).then(report => {
      if (live) setIntegrity(report);
    });
    return () => {
      live = false;
    };
  }, [roomName]);

  // Always fetched by key rather than looked up in a loaded list: the graph
  // holds only keys, and unlike the rail (whose tree may hold just the first
  // page) every node here is therefore openable.
  //
  // The expanded body is fetched alongside it for the same reason the rail and
  // the full page do: without it the drawer renders `![[key]]` as an unexpanded
  // chip, so the same memory would read differently depending on which surface
  // you opened it from.
  // Two requests per open, and clicks can overlap, so each open takes a ticket
  // and late responses from a superseded one are dropped. Without it a slow
  // first request can land after a fast second and the drawer titles itself one
  // memory while rendering another's body.
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
