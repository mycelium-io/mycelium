// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The room's knowledge as a graph of its memories, read left to right by what
 * came from what (`lib/knowledge.ts`, from the hub's `/knowledge`).
 *
 * A memory sits one column right of the furthest memory it was derived from,
 * and as level with those as the column allows, so a line of reasoning reads
 * across. Open memories (still being worked) are drawn dashed; dead ends keep
 * their place, so nobody walks down them twice.
 *
 * The room's view shows everything, and picking a task lights that task's
 * memories. A task's view (`lens`) is the same graph cut to the memories the
 * task produced, plus the memories from other tasks they came from or fed,
 * drawn faded and named by their task.
 */

import { useMemo, useState } from "react";
import { Ban, Info, Lightbulb, type LucideIcon } from "lucide-react";
import type { Knowledge, KnowledgeKind, KnowledgeTask } from "@/lib/knowledge";
import { cn } from "@/lib/utils";

const NODE_W = 264;
const NODE_H = 26;
const COL_GAP = 48;
const ROW_GAP = 8;
const PAD = 16;

const KIND: Record<KnowledgeKind, { icon: LucideIcon; tone: string; label: string }> = {
  fact: { icon: Info, tone: "text-muted-foreground", label: "Fact" },
  finding: { icon: Lightbulb, tone: "text-accent", label: "Finding" },
  "dead-end": { icon: Ban, tone: "text-red", label: "Dead end" },
};

interface Props {
  tasks: KnowledgeTask[];
  memories: Knowledge[];
  /** A task's key: cut the graph to that task's memories and their neighbors. */
  lens?: string;
  onOpen?: (key: string) => void;
}

interface Placed {
  m: Knowledge;
  x: number;
  y: number;
}

/** Columns by the longest chain of `derived-from` behind each memory; rows by
 *  where its sources sit, so a memory lines up with what it came from. */
function place(memories: Knowledge[], taskOrder: string[]): Placed[] {
  const byKey = new Map(memories.map((m) => [m.key, m]));
  const depth = new Map<string, number>();
  const depthOf = (m: Knowledge): number => {
    const known = depth.get(m.key);
    if (known !== undefined) return known;
    const srcs = (m.derivedFrom ?? []).map((k) => byKey.get(k)).filter((s): s is Knowledge => !!s);
    const d = srcs.length ? Math.max(...srcs.map(depthOf)) + 1 : 0;
    depth.set(m.key, d);
    return d;
  };
  memories.forEach(depthOf);

  const cols: Knowledge[][] = [];
  for (const m of memories) (cols[depth.get(m.key)!] ??= []).push(m);

  const y = new Map<string, number>();
  const out: Placed[] = [];
  cols.forEach((col, c) => {
    const want = (m: Knowledge) => {
      const ys = [...(m.derivedFrom ?? []), ...(m.relatesTo ?? [])]
        .map((k) => y.get(k))
        .filter((v): v is number => v !== undefined);
      return ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : null;
    };
    const order = (m: Knowledge) => want(m) ?? taskOrder.indexOf(m.task) * 1000;
    let next = PAD;
    for (const m of [...col].sort((a, b) => order(a) - order(b))) {
      const top = Math.max(next, want(m) ?? next);
      y.set(m.key, top);
      out.push({ m, x: PAD + c * (NODE_W + COL_GAP), y: top });
      next = top + NODE_H + ROW_GAP;
    }
  });
  return out;
}

export function KnowledgeGraph({ tasks, memories, lens, onOpen }: Props) {
  const [picked, setPicked] = useState<string | null>(null);
  const [tag, setTag] = useState<string | null>(null);
  const taskTitle = new Map(tasks.map((t) => [t.key, t.title]));

  // A lens keeps its task's memories and their neighbors in other tasks.
  const shown = useMemo(() => {
    if (!lens) return memories;
    const own = new Set(memories.filter((m) => m.task === lens).map((m) => m.key));
    const near = new Set(own);
    for (const m of memories) {
      const links = [...(m.derivedFrom ?? []), ...(m.relatesTo ?? [])];
      if (own.has(m.key)) links.forEach((k) => near.add(k));
      else if (links.some((k) => own.has(k))) near.add(m.key);
    }
    return memories.filter((m) => near.has(m.key));
  }, [memories, lens]);

  const placed = useMemo(() => place(shown, tasks.map((t) => t.key)), [shown, tasks]);
  const at = new Map(placed.map((p) => [p.m.key, p]));
  // Room on the right for an arc between two memories of the last column.
  const width = Math.max(...placed.map((p) => p.x)) + NODE_W + PAD + 80;
  const height = Math.max(...placed.map((p) => p.y)) + NODE_H + PAD;

  const focus = lens ?? picked;
  const foreign = (m: Knowledge) => !!lens && m.task !== lens;
  const lit = (m: Knowledge) =>
    (!focus || m.task === focus) && (!tag || (m.tags ?? []).includes(tag));

  const own = shown.filter((m) => !foreign(m));
  const tags = [...new Set(shown.flatMap((m) => m.tags ?? []))];

  const edges = placed.flatMap((p) => [
    ...(p.m.derivedFrom ?? []).map((k) => ({ from: k, to: p.m.key, relates: false })),
    ...(p.m.relatesTo ?? []).map((k) => ({ from: k, to: p.m.key, relates: true })),
  ]);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex h-8 flex-shrink-0 items-center gap-1 overflow-x-auto whitespace-nowrap border-b border-border px-3 text-micro">
        {lens ? (
          <>
            <span className="px-1.5 text-text">
              {own.length} memories
            </span>
            <span className="px-1.5 text-accent">
              {own.filter((m) => m.open).length} open
            </span>
          </>
        ) : (
          <>
            <Chip on={!picked} onClick={() => setPicked(null)}>
              All tasks
            </Chip>
            {tasks.map((t) => (
              <Chip key={t.key} on={picked === t.key} onClick={() => setPicked(picked === t.key ? null : t.key)}>
                {t.title}
                <span className="text-faint">{memories.filter((m) => m.task === t.key).length}</span>
              </Chip>
            ))}
          </>
        )}
        {tags.length > 0 && <span className="mx-1 h-3.5 w-px bg-border" aria-hidden />}
        {tags.map((t) => (
          <Chip key={t} on={tag === t} onClick={() => setTag(tag === t ? null : t)}>
            #{t}
          </Chip>
        ))}
        <span className="ml-auto flex items-center gap-3 pl-3 text-faint">
          {(Object.keys(KIND) as KnowledgeKind[]).map((k) => {
            const { icon: Icon, tone, label } = KIND[k];
            return (
              <span key={k} className="flex items-center gap-1">
                <Icon className={cn("size-3", tone)} aria-hidden />
                {label}
              </span>
            );
          })}
          <span className="flex items-center gap-1">
            <span className="h-2.5 w-4 rounded-sm border border-dashed border-accent/70" aria-hidden />
            Open
          </span>
        </span>
      </div>
      <div className="min-h-0 flex-1 overflow-auto">
        <div className="relative" style={{ width, height }}>
          <svg className="pointer-events-none absolute inset-0" width={width} height={height} aria-hidden>
            <defs>
              <marker id="kg-arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto">
                <path d="M0,0 L6,3 L0,6 z" className="fill-border2" />
              </marker>
            </defs>
            {edges.map(({ from, to, relates }) => {
              const a = at.get(from);
              const b = at.get(to);
              if (!a || !b) return null;
              const dim = !(lit(a.m) || lit(b.m)) || foreign(a.m) || foreign(b.m);
              const ya = a.y + NODE_H / 2;
              const yb = b.y + NODE_H / 2;
              let d: string;
              if (a.x === b.x) {
                // Same column: arc round the right.
                const bend = a.x + NODE_W + 28;
                d = `M${a.x + NODE_W},${ya} C${bend},${ya} ${bend},${yb} ${a.x + NODE_W},${yb}`;
              } else {
                const x1 = a.x + NODE_W;
                const mid = (x1 + b.x) / 2;
                d = `M${x1},${ya} C${mid},${ya} ${mid},${yb} ${b.x},${yb}`;
              }
              return (
                <g key={`${from}>${to}`} className={cn("transition-opacity", dim && "opacity-40")}>
                  <path
                    d={d}
                    fill="none"
                    className={relates ? "stroke-accent/50" : "stroke-border2"}
                    strokeDasharray={relates ? "2 3" : undefined}
                    markerEnd={relates ? undefined : "url(#kg-arrow)"}
                  />
                  {relates && (
                    <text x={a.x + NODE_W + 32} y={(ya + yb) / 2 + 3} className="fill-accent/80 text-[10px]">
                      relates to
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          {placed.map((p) => (
            <MemoryNode
              key={p.m.key}
              placed={p}
              dim={!lit(p.m)}
              foreignTask={foreign(p.m) ? taskTitle.get(p.m.task) : undefined}
              onOpen={onOpen}
            />
          ))}
        </div>
      </div>
      <div className="flex h-7 flex-shrink-0 items-center gap-3 border-t border-border px-3 text-micro text-faint">
        <span className="flex items-center gap-1.5">
          <svg width="22" height="6" aria-hidden>
            <path d="M0,3 L16,3" className="stroke-border2" />
            <path d="M16,0 L22,3 L16,6 z" className="fill-border2" />
          </svg>
          derived from
        </span>
        <span className="flex items-center gap-1.5">
          <svg width="22" height="6" aria-hidden>
            <path d="M0,3 L22,3" className="stroke-accent/50" strokeDasharray="2 3" />
          </svg>
          relates to
        </span>
      </div>
    </div>
  );
}

function MemoryNode({
  placed: { m, x, y },
  dim,
  foreignTask,
  onOpen,
}: {
  placed: Placed;
  dim: boolean;
  foreignTask?: string;
  onOpen?: (key: string) => void;
}) {
  const { icon: Icon, tone } = KIND[m.kind];
  return (
    <button
      type="button"
      title={m.key}
      onClick={() => onOpen?.(m.key)}
      style={{ left: x, top: y, width: NODE_W, height: NODE_H }}
      className={cn(
        "absolute flex items-center gap-1.5 rounded-md border px-2 text-left text-micro transition-opacity hover:border-border2",
        m.open ? "border-dashed border-accent/60 bg-bg" : "border-border bg-surface",
        (dim || foreignTask) && "opacity-40",
      )}
    >
      <Icon className={cn("size-3.5 flex-shrink-0", tone)} aria-hidden />
      <span className={cn("min-w-0 flex-1 truncate", m.kind === "dead-end" ? "text-muted-foreground" : "text-text")}>
        {m.title}
      </span>
      <span className="flex-shrink-0 text-[10px] text-faint">{foreignTask ?? m.by}</span>
    </button>
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
