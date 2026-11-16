// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * MOCK: a task's graph, one picture of what was tried and what came of it.
 *
 * Read left to right: the task's parts, what each part produced (a pull
 * request, an ask, a conductor run, an agent's subagents) and what came of
 * those (an answer, a decision, a subagent's posts). Every edge says what it
 * is. `depends on` arcs around the left of the parts' column.
 *
 * Notes are tagged messages, drawn dashed, with their tag as their edge; a
 * subagent's notes sit on its own branch. A tagged reply is drawn as a link
 * between the two messages, arcing around the right of their column when they
 * share one. Picking a tag above the graph dims everything that doesn't carry
 * it.
 */

import { useMemo, useState } from "react";
import {
  Bot,
  CircleCheck,
  CircleHelp,
  FileText,
  GitPullRequest,
  Hash,
  MessageSquareText,
  SquareCheckBig,
  Vote,
  Workflow,
  type LucideIcon,
} from "lucide-react";
import type { GraphKind, GraphNode, GraphState, RoomTag, TagTone, TaskGraph as Graph } from "@/mocks/task-graph";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

const NODE_W = 188;
const NODE_H = 24;
const COL_GAP = 64;
const ROW_GAP = 5;
const BAND_GAP = 12;
const PAD = 16;
/** Room beside a column for the arcs of links between nodes in it. */
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
  note: Hash,
};

const TONE: Record<GraphState, string> = {
  done: "text-green",
  working: "text-accent",
  open: "text-muted-foreground",
  blocked: "text-red",
  waiting: "text-yellow",
  dropped: "text-faint",
};

const TAG_TEXT: Record<TagTone, string> = {
  accent: "text-accent",
  green: "text-green",
  red: "text-red",
  yellow: "text-yellow",
  plain: "text-muted-foreground",
};

const TAG_FILL: Record<TagTone, string> = {
  accent: "fill-accent",
  green: "fill-green",
  red: "fill-red",
  yellow: "fill-yellow",
  plain: "fill-muted-foreground",
};

const TAG_STROKE: Record<TagTone, string> = {
  accent: "stroke-accent/70",
  green: "stroke-green/60",
  red: "stroke-red/60",
  yellow: "stroke-yellow/60",
  plain: "stroke-border2",
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
function place(root: GraphNode, arcRoom: number): Placed[] {
  const out: Placed[] = [];
  let cursor = PAD;
  const walk = (node: GraphNode, depth: number, parent: Placed | null): Placed => {
    const x = PAD + arcRoom + depth * (NODE_W + COL_GAP);
    const me: Placed = { node, x, y: 0, parent };
    out.push(me);
    const kids = node.children ?? [];
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
  const [picked, setPicked] = useState<string | null>(null);
  const tagged = graph.links.some((l) => l.tag);
  const placed = useMemo(
    () => place(graph.root, graph.links.some((l) => !l.tag) ? ARC_ROOM : 0),
    [graph],
  );
  const byId = new Map(placed.map((p) => [p.node.id, p]));
  const width = Math.max(...placed.map((p) => p.x)) + NODE_W + PAD + (tagged ? ARC_ROOM : 0);
  const height = Math.max(...placed.map((p) => p.y)) + NODE_H + PAD;

  // Every tag in the picture, with its count; a tag with no memory is plain.
  const known = new Map(graph.tags.map((t) => [t.name, t]));
  const counts = new Map<string, number>();
  for (const p of placed) for (const t of p.node.tags ?? []) counts.set(t, (counts.get(t) ?? 0) + 1);
  for (const l of graph.links) if (l.tag) counts.set(l.tag, (counts.get(l.tag) ?? 0) + 1);
  const tags: RoomTag[] = [...counts.keys()].map((name) => known.get(name) ?? { name, tone: "plain" });
  const tone = (name: string): TagTone => known.get(name)?.tone ?? "plain";
  const lit = (node: GraphNode) => !picked || (node.tags ?? []).includes(picked);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-8 flex-shrink-0 items-center gap-1 border-b border-border px-3 text-micro">
        <Chip on={!picked} onClick={() => setPicked(null)}>
          All
        </Chip>
        {tags.map((t) => (
          <Tooltip key={t.name} content={t.about ?? `No memory for #${t.name} yet`}>
            <Chip on={picked === t.name} onClick={() => setPicked(picked === t.name ? null : t.name)}>
              <span className={TAG_TEXT[t.tone]}>#{t.name}</span>
              <span className="text-faint">{counts.get(t.name)}</span>
            </Chip>
          </Tooltip>
        ))}
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
                const isNote = p.node.kind === "note";
                const t = isNote ? tone(p.node.tags![0]) : "plain";
                return (
                  <g key={p.node.id} className={cn("transition-opacity", !lit(p.node) && "opacity-25")}>
                    <path
                      d={`M${x1},${y1} C${mid},${y1} ${mid},${y2} ${x2},${y2}`}
                      fill="none"
                      className={isNote ? TAG_STROKE[t] : "stroke-border2"}
                      strokeWidth={1}
                      strokeDasharray={isNote ? "3 3" : undefined}
                    />
                    {p.node.edge && (
                      <text
                        x={x2 - 6}
                        y={y2 - 4}
                        textAnchor="end"
                        className={cn("text-[10px]", isNote ? TAG_FILL[t] : "fill-faint")}
                      >
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
              const t = link.tag ? tone(link.tag) : "accent";
              const dim = picked && link.tag !== picked;
              let d: string;
              let lx: number;
              let ly = (ya + yb) / 2 + 3;
              if (a.x === b.x && link.tag) {
                // A tagged reply between two nodes of one column arcs round its
                // right, labeled where it leaves the reply.
                const bend = a.x + NODE_W + ARC_ROOM - 6;
                d = `M${a.x + NODE_W},${ya} C${bend},${ya} ${bend},${yb} ${b.x + NODE_W},${yb}`;
                lx = a.x + NODE_W + 4;
                ly = ya - 4;
              } else if (a.x === b.x) {
                const bend = a.x - ARC_ROOM + 6;
                d = `M${a.x},${ya} C${bend},${ya} ${bend},${yb} ${b.x},${yb}`;
                lx = bend + 2;
              } else {
                d = `M${a.x + NODE_W},${ya} C${a.x + NODE_W + 40},${ya} ${b.x - 40},${yb} ${b.x},${yb}`;
                lx = (a.x + NODE_W + b.x) / 2;
              }
              return (
                <g key={`${link.from}-${link.to}`} className={cn("transition-opacity", dim && "opacity-25")}>
                  <path
                    d={d}
                    fill="none"
                    className={link.tag ? TAG_STROKE[t] : "stroke-accent/50"}
                    strokeWidth={link.tag ? 1.25 : 1}
                    strokeDasharray={link.tag ? undefined : "2 3"}
                    markerEnd={`url(#arrow-${t})`}
                  />
                  <text x={lx} y={ly} className={cn("text-[10px]", TAG_FILL[t])}>
                    {link.label}
                  </text>
                </g>
              );
            })}
            <defs>
              {(Object.keys(TAG_FILL) as TagTone[]).map((t) => (
                <marker key={t} id={`arrow-${t}`} viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto">
                  <path d="M0,0 L6,3 L0,6 z" className={TAG_FILL[t]} />
                </marker>
              ))}
            </defs>
          </svg>
          {placed.map((p) => (
            <Node key={p.node.id} placed={p} dim={!lit(p.node)} tone={tone} />
          ))}
        </div>
      </div>
    </div>
  );
}

function Node({ placed: { node, x, y }, dim, tone }: { placed: Placed; dim: boolean; tone: (t: string) => TagTone }) {
  const Icon = ICON[node.kind];
  const note = node.kind === "note";
  const iconTone = note ? TAG_TEXT[tone(node.tags![0])] : node.state ? TONE[node.state] : "text-muted-foreground";
  // A note's tag is its edge; any other node shows its own tags in place of meta.
  const ownTags = note ? [] : (node.tags ?? []);
  return (
    <div
      title={node.handle ? `@${node.handle}` : node.label}
      style={{ left: x, top: y, width: NODE_W, height: NODE_H }}
      className={cn(
        "absolute flex items-center gap-1.5 rounded-md border px-2 text-micro transition-opacity",
        note ? "border-dashed border-border2 bg-bg" : "border-border bg-surface",
        dim && "opacity-25",
      )}
    >
      <Icon className={cn("size-3.5 flex-shrink-0", iconTone)} aria-hidden />
      <span
        className={cn(
          "min-w-0 flex-1 truncate",
          node.kind === "pr" || node.kind === "summary" ? "font-mono" : "",
          node.state === "dropped" ? "text-faint line-through" : note ? "text-muted-foreground" : "text-text",
        )}
      >
        {node.label}
      </span>
      {ownTags.map((t) => (
        <span key={t} className={cn("flex-shrink-0 text-[10px]", TAG_TEXT[tone(t)])}>
          #{t}
        </span>
      ))}
      {!ownTags.length && node.meta && <span className="flex-shrink-0 text-[10px] text-faint">{node.meta}</span>}
    </div>
  );
}

function Chip({ on, className, ...rest }: React.ComponentProps<"button"> & { on: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      {...rest}
      className={cn(
        "flex h-5 items-center gap-1 rounded px-1.5 transition-colors hover:bg-hairline",
        on ? "bg-hairline text-text" : "text-muted-foreground",
        className,
      )}
    />
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
