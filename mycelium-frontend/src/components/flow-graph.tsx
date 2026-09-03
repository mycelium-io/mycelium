// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * An episode's interaction flow, drawn: the steps the conductor walks, the
 * edges between them, where the run stands, and whose turn it is.
 *
 * Purpose-built for a flow of a handful of steps rather than a general graph
 * view: steps read left to right in the order they run, a branch fans out with
 * its stance on the edge, and a loop back is an arc under the row. The run's
 * state is drawn on top of the shape — the current step lit, taken edges
 * solid, the member holding the floor named — so the same drawing serves an
 * open run and a finished one.
 */

import type { EpisodeFlow, FlowTraceEntry, RoomFloor } from "@/lib/api";
import {
  layoutFlow,
  stepStates,
  takenEdges,
  NODE_H,
  NODE_W,
  type FlowEdge,
  type FlowNode,
  type StepState,
} from "@/lib/flow-graph";

interface Props {
  flow: EpisodeFlow;
  trace: FlowTraceEntry[];
  currentStep: string | null | undefined;
  outcome: string;
  /** The floor held on this episode right now, if any. */
  floor?: RoomFloor | null;
  className?: string;
}

function tone(state: StepState, end: FlowNode["end"]): { stroke: string; fill: string; text: string } {
  if (state === "current") return { stroke: "var(--accent)", fill: "color-mix(in srgb, var(--accent) 16%, transparent)", text: "var(--text)" };
  if (state === "reached") {
    const c = end === "rejected" ? "var(--yellow)" : "var(--green)";
    return { stroke: c, fill: `color-mix(in srgb, ${c} 16%, transparent)`, text: "var(--text)" };
  }
  if (state === "visited") return { stroke: "var(--muted-foreground)", fill: "color-mix(in srgb, var(--muted-foreground) 10%, transparent)", text: "var(--text)" };
  return { stroke: "var(--border)", fill: "transparent", text: "var(--muted-foreground)" };
}

/** Vertical room between two loops from one source: a label's height plus air,
 *  so a second loop's label never prints over the first's. */
const LANE_GAP = 14;

function edgePath(from: FlowNode, to: FlowNode, edge: FlowEdge, lane: number): string {
  const y = from.y + NODE_H / 2;
  if (!edge.back) {
    const x1 = from.x + NODE_W;
    const x2 = to.x;
    // A forward edge that skips a step arches over the row so it does not
    // run through the step between.
    const skip = to.x - x1 > NODE_W;
    if (!skip) return `M ${x1} ${y} L ${x2} ${y}`;
    const top = from.y - 14;
    return `M ${x1} ${y} C ${x1 + 40} ${top}, ${x2 - 40} ${top}, ${x2} ${y}`;
  }
  // A loop: down from the source, under the row, up into the target.
  const x1 = from.x + NODE_W / 2 + lane * 10;
  const x2 = to.x + NODE_W / 2 - lane * 10;
  const bottom = from.y + NODE_H + 22 + lane * LANE_GAP;
  return `M ${x1} ${from.y + NODE_H} L ${x1} ${bottom} L ${x2} ${bottom} L ${x2} ${to.y + NODE_H}`;
}

function edgeLabelPos(from: FlowNode, to: FlowNode, edge: FlowEdge, lane: number): { x: number; y: number } {
  if (!edge.back) {
    const skip = to.x - (from.x + NODE_W) > NODE_W;
    return { x: (from.x + NODE_W + to.x) / 2, y: skip ? from.y - 6 : from.y + NODE_H / 2 - 6 };
  }
  return { x: (from.x + to.x + NODE_W) / 2, y: from.y + NODE_H + 22 + lane * LANE_GAP - 4 };
}

export function FlowGraph({ flow, trace, currentStep, outcome, floor, className }: Props) {
  const layout = layoutFlow(flow);
  const states = stepStates(flow, trace, currentStep, outcome);
  const taken = takenEdges(trace);
  const byId = new Map(layout.nodes.map((n) => [n.id, n]));
  const speakers = new Set((floor?.speakers ?? []).map((h) => h.toLowerCase()));
  // Loops from the same source stack outward so two never overlap.
  const lanes = new Map<string, number>();
  const laneOf = (e: FlowEdge) => {
    if (!e.back) return 0;
    const n = lanes.get(e.from) ?? 0;
    lanes.set(e.from, n + 1);
    return n;
  };

  return (
    <svg
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      width="100%"
      style={{ maxWidth: layout.width, display: "block", overflow: "visible" }}
      role="img"
      aria-label={`${flow.name} flow: ${layout.nodes.map((n) => n.id).join(", ")}`}
      className={className}
    >
      <defs>
        <marker id="flow-arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 8 4 L 0 8 z" fill="currentColor" />
        </marker>
      </defs>
      {layout.edges.map((edge, i) => {
        const from = byId.get(edge.from);
        const to = byId.get(edge.to);
        if (!from || !to) return null;
        const lane = laneOf(edge);
        const solid = taken.has(`${edge.from}→${edge.to}`);
        const color = solid ? "var(--text)" : "var(--muted-foreground)";
        const label = edgeLabelPos(from, to, edge, lane);
        return (
          <g key={i} style={{ color }}>
            <path
              d={edgePath(from, to, edge, lane)}
              fill="none"
              stroke="currentColor"
              strokeWidth={solid ? 1.8 : 1.2}
              strokeDasharray={solid ? undefined : "4 3"}
              markerEnd="url(#flow-arrow)"
            />
            {edge.label && (
              <text x={label.x} y={label.y} textAnchor="middle" fontSize="10" fill="currentColor" fontFamily="var(--font-mono, ui-monospace, monospace)">
                {edge.label}
              </text>
            )}
          </g>
        );
      })}
      {layout.nodes.map((node) => {
        const state = states.get(node.id) ?? "untouched";
        const t = tone(state, node.end);
        const hasFloor = node.who !== null && speakers.has(node.who.toLowerCase());
        return (
          <g key={node.id} transform={`translate(${node.x} ${node.y})`}>
            <rect width={NODE_W} height={NODE_H} rx={8} fill={t.fill} stroke={t.stroke} strokeWidth={state === "current" ? 2 : 1.2} />
            <text x={10} y={18} fontSize="12" fontWeight={600} fill={t.text} fontFamily="var(--font-mono, ui-monospace, monospace)">
              {node.id}
            </text>
            <text x={10} y={34} fontSize="10" fill="var(--muted-foreground)">
              {node.who ? `${node.what} · ${node.who}` : node.what}
            </text>
            {hasFloor && (
              <g transform={`translate(${NODE_W - 8} -6)`}>
                <circle r={5} fill="var(--accent)" />
                <title>{`${node.who} has the floor`}</title>
              </g>
            )}
          </g>
        );
      })}
    </svg>
  );
}
