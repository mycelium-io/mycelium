// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { computeForceLayout } from "@/lib/memory-graph-layout";
import type { MemoryGraph, MemoryGraphEdge, MemoryGraphNode } from "@/lib/api";

function node(key: string, over: Partial<MemoryGraphNode> = {}): MemoryGraphNode {
  return { key, expandable: false, outbound: 0, inbound: 0, ...over };
}

function edge(
  source: string,
  target: string,
  over: Partial<MemoryGraphEdge> = {},
): MemoryGraphEdge {
  return { source, target, kind: "wikilink", resolved: true, ...over };
}

function isFinitePoint(p: { x: number; y: number }) {
  return Number.isFinite(p.x) && Number.isFinite(p.y);
}

describe("computeForceLayout", () => {
  it("gives every node finite coordinates", () => {
    const graph: MemoryGraph = {
      nodes: [node("a"), node("b"), node("c")],
      edges: [edge("a", "b")],
    };
    const layout = computeForceLayout(graph, { ticks: 50 });
    expect(layout.nodes).toHaveLength(3);
    for (const n of layout.nodes) expect(isFinitePoint(n)).toBe(true);
  });

  it("positions a resolved edge at its two endpoints", () => {
    const graph: MemoryGraph = {
      nodes: [node("a"), node("b")],
      edges: [edge("a", "b")],
    };
    const layout = computeForceLayout(graph, { ticks: 50 });
    const a = layout.nodes.find(n => n.key === "a")!;
    const b = layout.nodes.find(n => n.key === "b")!;
    expect(layout.edges).toHaveLength(1);
    const [drawn] = layout.edges;
    expect(drawn.x1).toBeCloseTo(a.x);
    expect(drawn.y1).toBeCloseTo(a.y);
    expect(drawn.x2).toBeCloseTo(b.x);
    expect(drawn.y2).toBeCloseTo(b.y);
  });

  it("places an isolated node without crashing and without a link", () => {
    const graph: MemoryGraph = { nodes: [node("lonely")], edges: [] };
    const layout = computeForceLayout(graph, { ticks: 20 });
    expect(layout.nodes).toHaveLength(1);
    expect(isFinitePoint(layout.nodes[0])).toBe(true);
    expect(layout.edges).toHaveLength(0);
  });

  it("drops a broken link with no such target — nothing to draw to", () => {
    const graph: MemoryGraph = {
      nodes: [node("a")],
      edges: [edge("a", "missing", { resolved: false, error: "not_found" })],
    };
    const layout = computeForceLayout(graph, { ticks: 20 });
    expect(layout.edges).toHaveLength(0);
  });

  it("keeps an unresolved edge whose two ends are both real memories", () => {
    // A `no_anchor` / `not_expandable` failure is about the *link*, not the
    // target: both memories exist, so the edge is positioned and left for the
    // canvas to draw in the broken style.
    const graph: MemoryGraph = {
      nodes: [node("a"), node("b")],
      edges: [edge("a", "b", { resolved: false, error: "no_anchor" })],
    };
    const layout = computeForceLayout(graph, { ticks: 20 });
    expect(layout.edges).toHaveLength(1);
    expect(layout.edges[0].resolved).toBe(false);
    expect(layout.edges[0].error).toBe("no_anchor");
    expect(isFinitePoint({ x: layout.edges[0].x1, y: layout.edges[0].y1 })).toBe(true);
  });

  it("drops an edge whose target isn't a node in this graph", () => {
    const graph: MemoryGraph = {
      nodes: [node("a"), node("b")],
      // resolved: true but pointing outside this node set shouldn't happen in
      // practice, but the layout must not crash forceLink's id lookup on it.
      edges: [edge("a", "not-in-graph")],
    };
    const layout = computeForceLayout(graph, { ticks: 20 });
    expect(layout.edges).toHaveLength(0);
  });

  it("drops a self-loop", () => {
    const graph: MemoryGraph = {
      nodes: [node("a")],
      edges: [edge("a", "a")],
    };
    const layout = computeForceLayout(graph, { ticks: 20 });
    expect(layout.edges).toHaveLength(0);
  });

  it("lays out disconnected components without crashing", () => {
    const graph: MemoryGraph = {
      nodes: [node("a"), node("b"), node("c"), node("d")],
      edges: [edge("a", "b"), edge("c", "d")],
    };
    const layout = computeForceLayout(graph, { ticks: 50 });
    expect(layout.nodes).toHaveLength(4);
    expect(layout.edges).toHaveLength(2);
    for (const n of layout.nodes) expect(isFinitePoint(n)).toBe(true);
  });

  it("handles an empty graph", () => {
    const layout = computeForceLayout({ nodes: [], edges: [] });
    expect(layout.nodes).toHaveLength(0);
    expect(layout.edges).toHaveLength(0);
  });
});
