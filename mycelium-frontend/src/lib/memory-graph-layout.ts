// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from "d3-force";
import type { MemoryGraph, MemoryGraphEdge, MemoryGraphNode } from "@/lib/api";

export interface GraphLayoutNode extends MemoryGraphNode {
  x: number;
  y: number;
}

/** An edge that survived layout — endpoints deliberately *not* included.
 *
 *  Baking coordinates in here would freeze them at the moment the simulation
 *  stopped, and nodes move afterwards (a reader can drag them). Consumers look
 *  their endpoints up by key instead, so an edge can't drift away from the nodes
 *  it connects. */
export type GraphLayoutEdge = MemoryGraphEdge;

export interface GraphLayout {
  nodes: GraphLayoutNode[];
  edges: GraphLayoutEdge[];
}

export interface LayoutOptions {
  width?: number;
  height?: number;
  /** Simulation steps run synchronously before reading positions back out. */
  ticks?: number;
}

const DEFAULT_WIDTH = 960;
const DEFAULT_HEIGHT = 640;
const DEFAULT_TICKS = 300;

// d3-force mutates its node/link objects in place (adds x/y/vx/vy, and turns
// a link's string source/target into a node reference) — these two types
// describe that private working shape so the public `GraphLayout*` types can
// stay a clean, d3-free snapshot.
interface SimNode extends MemoryGraphNode {
  x: number;
  y: number;
}

interface SimLink {
  source: string | SimNode;
  target: string | SimNode;
  edge: MemoryGraphEdge;
}

/**
 * Lays out a room's memory graph with a force simulation, run to convergence
 * synchronously (a fixed tick count, no live animation loop). Rooms here are
 * tens to low hundreds of memories, so a one-shot layout on mount is simpler
 * and cheaper than keeping a simulation alive across renders.
 *
 * An edge earns a physics link and a drawn line when both of its ends are real
 * nodes in this graph. That deliberately includes an edge that failed to
 * resolve for a reason *other* than a missing target — a `no_anchor` or
 * `not_expandable` link still joins two memories that both exist, and the
 * canvas draws it in the broken style rather than pretending it isn't there.
 * What gets dropped is an edge with nothing at the other end to pull toward:
 * a self-link, or one naming a target this room has no memory for.
 */
export function computeForceLayout(graph: MemoryGraph, options: LayoutOptions = {}): GraphLayout {
  const width = options.width ?? DEFAULT_WIDTH;
  const height = options.height ?? DEFAULT_HEIGHT;
  const ticks = options.ticks ?? DEFAULT_TICKS;

  const known = new Set(graph.nodes.map(n => n.key));

  // Seed on a circle rather than d3's default (0,0) pile: a stable, spread
  // starting point avoids a first-tick explosion when the charge force pushes
  // coincident nodes apart in an arbitrary direction.
  const simNodes: SimNode[] = graph.nodes.map((n, i) => {
    const angle = (i / Math.max(graph.nodes.length, 1)) * 2 * Math.PI;
    const radius = Math.min(width, height) / 3;
    return { ...n, x: width / 2 + radius * Math.cos(angle), y: height / 2 + radius * Math.sin(angle) };
  });

  const positionable = graph.edges.filter(
    e => e.source !== e.target && known.has(e.source) && known.has(e.target),
  );
  const simLinks: SimLink[] = positionable.map(edge => ({ source: edge.source, target: edge.target, edge }));

  const simulation = forceSimulation(simNodes)
    .force(
      "link",
      forceLink<SimNode, SimLink>(simLinks)
        .id(d => d.key)
        .distance(90)
        .strength(0.5),
    )
    .force("charge", forceManyBody().strength(-220))
    .force("center", forceCenter(width / 2, height / 2))
    .force("collide", forceCollide(28))
    .stop();

  for (let i = 0; i < ticks; i++) simulation.tick();

  // Rebuilt field by field rather than spread: the simulation has by now
  // decorated each node in place with its own `vx`/`vy`/`index`, which have no
  // meaning once the ticking has stopped.
  const nodes: GraphLayoutNode[] = simNodes.map(n => ({
    key: n.key,
    expandable: n.expandable,
    outbound: n.outbound,
    inbound: n.inbound,
    x: n.x,
    y: n.y,
  }));
  const edges: GraphLayoutEdge[] = simLinks.map(link => ({ ...link.edge }));

  return { nodes, edges };
}
