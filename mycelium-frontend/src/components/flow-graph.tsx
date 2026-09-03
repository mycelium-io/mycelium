// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * An episode's interaction flow, drawn: the steps the conductor walks, the
 * edges between them, where the run stands, and whose turn it is.
 *
 * Purpose-built for a flow of a handful of steps rather than a general graph
 * view: steps read in the order they run, a branch fans out with its stance
 * on the edge, and a loop back rides a rail beside the line. A short flow is
 * a row; a longer one is a column, the shape that fits the pane it is shown
 * in. The run's state is drawn on top of the shape — the current step lit,
 * taken edges solid, the member holding the floor marked — so the same
 * drawing serves an open run and a finished one.
 */

import type { EpisodeFlow, FlowTraceEntry, RoomFloor } from "@/lib/api";
import {
  layoutFlow,
  stepStates,
  takenEdges,
  LANE_GAP,
  LOOP_BASE,
  NODE_H,
  type FlowEdge,
  type FlowLayout,
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

interface Drawn {
  d: string;
  label: { x: number; y: number; rotate: boolean; anchor: "start" | "middle" | "end" };
}

/** A row's edge: straight between neighbours, arched over a skipped step, and
 *  a loop down under the row in its own lane. */
function rowEdge(from: FlowNode, to: FlowNode, edge: FlowEdge): Drawn {
  const y = from.y + NODE_H / 2;
  if (edge.rail === null) {
    const x1 = from.x + from.w;
    const x2 = to.x;
    const skip = x2 - x1 > from.w;
    if (!skip) return { d: `M ${x1} ${y} L ${x2} ${y}`, label: { x: (x1 + x2) / 2, y: y - 6, rotate: false, anchor: "middle" } };
    const top = from.y - 14;
    return {
      d: `M ${x1} ${y} C ${x1 + 40} ${top}, ${x2 - 40} ${top}, ${x2} ${y}`,
      label: { x: (x1 + x2) / 2, y: from.y - 6, rotate: false, anchor: "middle" },
    };
  }
  // Each loop has a lane of its own, lower than the last, so lines never
  // share a segment; a loop onto its own step is a narrow U under it.
  const lane = edge.rail;
  const x1 = from.x + from.w / 2 + (lane + 1) * 10;
  const x2 = to.x + to.w / 2 - (lane + 1) * 10;
  const bottom = from.y + NODE_H + LOOP_BASE + 6 + lane * LANE_GAP;
  return {
    d: `M ${x1} ${from.y + NODE_H} L ${x1} ${bottom} L ${x2} ${bottom} L ${x2} ${to.y + NODE_H}`,
    label: { x: (x1 + x2) / 2, y: bottom - 4, rotate: false, anchor: "middle" },
  };
}

/** Where a rail edge meets its node: the ports on one side of a node are
 *  spread down its height so two edges never share a point. */
type Ports = Map<string, { n: number; next: number }>;

function port(ports: Ports, key: string, node: FlowNode): number {
  const p = ports.get(key) ?? { n: 1, next: 0 };
  const y = node.y + (NODE_H * (p.next + 1)) / (p.n + 1);
  p.next += 1;
  ports.set(key, p);
  return y;
}

/** A column's edge: straight down between neighbours, out to a rail on the
 *  right to skip ahead, out to a rail on the left to loop back. */
function columnEdge(from: FlowNode, to: FlowNode, edge: FlowEdge, ports: Ports): Drawn {
  if (edge.rail === null) {
    const cx = from.x + from.w / 2;
    const y1 = from.y + NODE_H;
    const y2 = to.y;
    return { d: `M ${cx} ${y1} L ${cx} ${y2}`, label: { x: cx + 8, y: (y1 + y2) / 2 + 3, rotate: false, anchor: "start" } };
  }
  const lane = edge.rail;
  if (edge.back) {
    const railX = from.x - (lane + 1) * LANE_GAP;
    const self = from.id === to.id;
    const ySrc = self ? from.y + NODE_H / 2 + 8 : port(ports, `L:${from.id}`, from);
    const yDst = self ? to.y + NODE_H / 2 - 8 : port(ports, `L:${to.id}`, to);
    return {
      d: `M ${from.x} ${ySrc} L ${railX} ${ySrc} L ${railX} ${yDst} L ${to.x} ${yDst}`,
      label: { x: railX - 4, y: (ySrc + yDst) / 2, rotate: true, anchor: "middle" },
    };
  }
  const edgeX = from.x + from.w;
  const railX = edgeX + (lane + 1) * LANE_GAP;
  const ySrc = port(ports, `R:${from.id}`, from);
  const yDst = port(ports, `R:${to.id}`, to);
  return {
    d: `M ${edgeX} ${ySrc} L ${railX} ${ySrc} L ${railX} ${yDst} L ${edgeX} ${yDst}`,
    label: { x: railX + 10, y: (ySrc + yDst) / 2, rotate: true, anchor: "middle" },
  };
}

function drawEdges(layout: FlowLayout): Map<FlowEdge, Drawn> {
  const byId = new Map(layout.nodes.map((n) => [n.id, n]));
  const drawn = new Map<FlowEdge, Drawn>();
  // A node's ports are counted first so each edge can take its share.
  const ports: Ports = new Map();
  if (layout.direction === "column") {
    for (const e of layout.edges) {
      if (e.rail === null || e.from === e.to) continue;
      const side = e.back ? "L" : "R";
      for (const id of [e.from, e.to]) {
        const key = `${side}:${id}`;
        const p = ports.get(key) ?? { n: 0, next: 0 };
        p.n += 1;
        ports.set(key, p);
      }
    }
  }
  for (const edge of layout.edges) {
    const from = byId.get(edge.from);
    const to = byId.get(edge.to);
    if (!from || !to) continue;
    drawn.set(edge, layout.direction === "row" ? rowEdge(from, to, edge) : columnEdge(from, to, edge, ports));
  }
  return drawn;
}

export function FlowGraph({ flow, trace, currentStep, outcome, floor, className }: Props) {
  const layout = layoutFlow(flow);
  const states = stepStates(flow, trace, currentStep, outcome);
  const taken = takenEdges(trace);
  const speakers = new Set((floor?.speakers ?? []).map((h) => h.toLowerCase()));
  const drawn = drawEdges(layout);
  // A row shrinks a little to fit a narrow pane and scrolls past that; a
  // column is as wide as the pane gives it, which is what it was chosen for.
  const sizing =
    layout.direction === "row"
      ? { minWidth: layout.width * 0.7, maxWidth: layout.width }
      : { maxWidth: layout.width };

  return (
    <svg
      viewBox={`0 0 ${layout.width} ${layout.height}`}
      width="100%"
      style={{ ...sizing, display: "block", overflow: "visible" }}
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
        const shape = drawn.get(edge);
        if (!shape) return null;
        const solid = taken.has(`${edge.from}→${edge.to}`);
        const color = solid ? "var(--text)" : "var(--muted-foreground)";
        const { label } = shape;
        return (
          <g key={i} style={{ color }}>
            <path
              d={shape.d}
              fill="none"
              stroke="currentColor"
              strokeWidth={solid ? 1.8 : 1.2}
              strokeDasharray={solid ? undefined : "4 3"}
              markerEnd="url(#flow-arrow)"
            />
            {edge.label && (
              <text
                x={label.x}
                y={label.y}
                textAnchor={label.anchor}
                fontSize="10"
                fill="currentColor"
                fontFamily="var(--font-mono, ui-monospace, monospace)"
                transform={label.rotate ? `rotate(-90 ${label.x} ${label.y})` : undefined}
              >
                {edge.label}
              </text>
            )}
          </g>
        );
      })}
      {layout.nodes.map((node) => {
        const state = states.get(node.id) ?? "untouched";
        const t = tone(state, node.end);
        // The floor is a fact about now, so it marks the step the run stands
        // at, and only when the floor is with whom that step asks. A group
        // step names several members; the floor is theirs if any hold it.
        const hasFloor =
          state === "current" &&
          node.who !== null &&
          node.who.split(", ").some((h) => speakers.has(h.toLowerCase()));
        const line = node.who ? `${node.what} · ${node.who}` : node.what;
        return (
          <g key={node.id} transform={`translate(${node.x} ${node.y})`}>
            <title>{`${node.id}: ${line}`}</title>
            <rect width={node.w} height={NODE_H} rx={8} fill={t.fill} stroke={t.stroke} strokeWidth={state === "current" ? 2 : 1.2} />
            <clipPath id={`flow-clip-${node.id}`}>
              <rect x={0} y={0} width={node.w - 6} height={NODE_H} />
            </clipPath>
            <text x={10} y={18} fontSize="12" fontWeight={600} fill={t.text} fontFamily="var(--font-mono, ui-monospace, monospace)">
              {node.id}
            </text>
            {/* A group step's cast can outrun the box; it clips at the edge and
                the full line is the node's tooltip. */}
            <text x={10} y={34} fontSize="10" fill="var(--muted-foreground)" clipPath={`url(#flow-clip-${node.id})`}>
              {line}
            </text>
            {hasFloor && (
              <g transform={`translate(${node.w - 8} -6)`}>
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
