// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * MOCK: a task's graph, one picture of what was tried and what came of it.
 *
 * Read left to right: the task's parts, what each part produced (a pull
 * request, an ask, a conductor run, an agent's subagents) and what came of
 * those (an answer, a decision, a subagent's posts). Every edge says what it
 * is. Links that aren't parent and child (`depends on`) arc around the left of
 * the column they join. Notes (step 2) are steps agents labeled themselves,
 * drawn dashed, and a subagent's notes sit on its own branch.
 */

import { useMemo, useState } from "react";
import {
  Bot,
  CircleCheck,
  CircleHelp,
  CircleSlash,
  FileText,
  FlaskConical,
  GitPullRequest,
  Lightbulb,
  MessageSquareText,
  OctagonAlert,
  SquareCheckBig,
  Vote,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import type { GraphKind, GraphNode, GraphState, TaskGraph as Graph } from "@/mocks/task-graph";
import { cn } from "@/lib/utils";

const NODE_W = 188;
const NODE_H = 24;
const COL_GAP = 64;
const ROW_GAP = 5;
const BAND_GAP = 12;
const PAD = 16;
/** Room on the left of the parts' column for the arcs of `depends on`. */
const ARC_ROOM = 64;

const ICON: Record<GraphKind, LucideIcon> = {
  task: SquareCheckBig,
  part: SquareCheckBig,
  pr: GitPullRequest,
  ask: CircleHelp,
  answer: CircleCheck,
  run: Workflow,
  decision: Vote,
  summary: FileText,
  subagent: Bot,
  post: MessageSquareText,
  tried: FlaskConical,
  found: Lightbulb,
  "ruled-out": CircleSlash,
  blocked: OctagonAlert,
};

const TONE: Record<GraphState, string> = {
  done: "text-green",
  working: "text-accent",
  open: "text-muted-foreground",
  blocked: "text-red",
  waiting: "text-yellow",
  dropped: "text-faint",
};

interface Placed {
  node: GraphNode;
  x: number;
  y: number;
  parent: Placed | null;
}

/** Each node's place: its depth is its column, a leaf takes the next row, and
 *  a parent sits level with the middle of its children. The task itself isn't
 *  drawn, since the pane already names it: its branches start the picture. */
function place(root: GraphNode, notes: boolean, arcRoom: number): Placed[] {
  const out: Placed[] = [];
  let cursor = PAD;
  const walk = (node: GraphNode, depth: number, parent: Placed | null): Placed => {
    const x = PAD + arcRoom + depth * (NODE_W + COL_GAP);
    const me: Placed = { node, x, y: 0, parent };
    out.push(me);
    const kids = (node.children ?? []).filter((c) => notes || !c.note);
    if (!kids.length) {
      me.y = cursor;
      cursor += NODE_H + ROW_GAP;
    } else {
      const placed = kids.map((c) => walk(c, depth + 1, me));
      me.y = (placed[0].y + placed[placed.length - 1].y) / 2;
    }
    // Each of the task's own branches gets a little more air below it.
    if (depth === 0) cursor += BAND_GAP;
    return me;
  };
  for (const branch of root.children ?? []) walk(branch, 0, null);
  return out;
}

export function TaskGraph({ graph }: { graph: Graph }) {
  const [notes, setNotes] = useState(true);
  const placed = useMemo(() => place(graph.root, notes, graph.links.length ? ARC_ROOM : 0), [graph, notes]);
  const byId = new Map(placed.map((p) => [p.node.id, p]));
  const width = Math.max(...placed.map((p) => p.x)) + NODE_W + PAD;
  const height = Math.max(...placed.map((p) => p.y)) + NODE_H + PAD;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-8 flex-shrink-0 items-center gap-3 border-b border-border px-3 text-micro text-muted-foreground">
        <button
          type="button"
          aria-pressed={notes}
          onClick={() => setNotes((v) => !v)}
          className={cn(
            "flex h-5 items-center gap-1 rounded px-1.5 transition-colors hover:bg-hairline",
            notes ? "text-text" : "text-faint",
          )}
        >
          <FlaskConical className="size-3" aria-hidden />
          Notes
        </button>
        <span className="ml-auto flex items-center gap-3 text-faint">
          <Legend tone="text-green" label="Done" />
          <Legend tone="text-accent" label="Working" />
          <Legend tone="text-yellow" label="Waiting" />
          <Legend tone="text-red" label="Blocked" />
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="relative" style={{ width, height }}>
          <svg className="pointer-events-none absolute inset-0" width={width} height={height} aria-hidden>
            {placed
              .filter((p) => p.parent)
              .map((p) => {
                const from = p.parent!;
                const x1 = from.x + NODE_W;
                const y1 = from.y + NODE_H / 2;
                const x2 = p.x;
                const y2 = p.y + NODE_H / 2;
                const mid = (x1 + x2) / 2;
                return (
                  <g key={p.node.id}>
                    <path
                      d={`M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`}
                      fill="none"
                      className="stroke-border2"
                      strokeWidth={1}
                      strokeDasharray={p.node.note ? "3 3" : undefined}
                    />
                    {p.node.edge && (
                      <text x={x2 - 6} y={y2 - 4} textAnchor="end" className="fill-faint text-[10px]">
                        {p.node.edge}
                      </text>
                    )}
                  </g>
                );
              })}
            {graph.links.map((link) => {
              const a = byId.get(link.from);
              const b = byId.get(link.to);
              if (!a || !b) return null;
              const ya = a.y + NODE_H / 2;
              const yb = b.y + NODE_H / 2;
              const left = Math.min(a.x, b.x);
              const bend = left - ARC_ROOM + 6;
              const d =
                a.x === b.x
                  ? `M${a.x},${ya} C${bend},${ya} ${bend},${yb} ${b.x},${yb}`
                  : `M${a.x + NODE_W},${ya} C${a.x + NODE_W + 40},${ya} ${b.x - 40},${yb} ${b.x},${yb}`;
              return (
                <g key={`${link.from}-${link.to}`}>
                  <path d={d} fill="none" className="stroke-accent/50" strokeWidth={1} strokeDasharray="2 3" markerEnd="url(#arrow)" />
                  <text
                    x={a.x === b.x ? bend + 2 : (a.x + NODE_W + b.x) / 2}
                    y={(ya + yb) / 2 + 3}
                    className="fill-accent/80 text-[10px]"
                  >
                    {link.label}
                  </text>
                </g>
              );
            })}
            <defs>
              <marker id="arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0,0 L6,3 L0,6 z" className="fill-accent/60" />
              </marker>
            </defs>
          </svg>
          {placed.map((p) => (
            <Node key={p.node.id} placed={p} />
          ))}
        </div>
      </div>
    </div>
  );
}

function Node({ placed: { node, x, y } }: { placed: Placed }) {
  const Icon = ICON[node.kind];
  return (
    <div
      title={node.handle ? `@${node.handle}` : node.label}
      style={{ left: x, top: y, width: NODE_W, height: NODE_H }}
      className={cn(
        "absolute flex items-center gap-1.5 rounded-md border px-2 text-micro",
        node.note ? "border-dashed border-border2 bg-bg" : "border-border bg-surface",
      )}
    >
      <Icon className={cn("size-3.5 flex-shrink-0", node.state ? TONE[node.state] : "text-muted-foreground")} aria-hidden />
      <span
        className={cn(
          "min-w-0 flex-1 truncate",
          node.kind === "pr" || node.kind === "summary" ? "font-mono" : "",
          node.state === "dropped" ? "text-faint line-through" : node.note ? "text-muted-foreground" : "text-text",
        )}
      >
        {node.label}
      </span>
      {node.meta && <span className="flex-shrink-0 text-[10px] text-faint">{node.meta}</span>}
    </div>
  );
}

function Legend({ tone, label }: { tone: string; label: string }) {
  return (
    <span className="flex items-center gap-1">
      <span className={cn("size-1.5 rounded-full bg-current", tone)} aria-hidden />
      {label}
    </span>
  );
}
