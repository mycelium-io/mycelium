// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * MOCK: what a task has added to the room's memory, under the task itself.
 *
 * The memories the agents wrote while working the task, open ones first, each
 * with who wrote it. The graph button shows the same memories by what came
 * from what.
 */

import { Ban, Info, Lightbulb, Network, Vote, type LucideIcon } from "lucide-react";
import type { Knowledge, KnowledgeKind } from "@/mocks/knowledge";
import { cn } from "@/lib/utils";

const ICON: Record<KnowledgeKind, { icon: LucideIcon; tone: string }> = {
  fact: { icon: Info, tone: "text-muted-foreground" },
  finding: { icon: Lightbulb, tone: "text-accent" },
  "dead-end": { icon: Ban, tone: "text-red" },
  decision: { icon: Vote, tone: "text-green" },
};

export function TaskMemories({
  memories,
  onOpen,
  onGraph,
}: {
  memories: Knowledge[];
  onOpen?: (key: string) => void;
  onGraph: () => void;
}) {
  if (!memories.length) return null;
  const rows = [...memories].sort((a, b) => Number(!!b.open) - Number(!!a.open));
  const open = memories.filter((m) => m.open).length;
  return (
    <section className="border-b border-border px-4 py-3">
      <div className="mb-1.5 flex items-center gap-2">
        <h3 className="text-label font-medium text-text">Memories</h3>
        <span className="text-micro text-faint">{memories.length}</span>
        {open > 0 && <span className="text-micro text-accent">{open} open</span>}
        <button
          type="button"
          onClick={onGraph}
          className="ml-auto flex h-6 items-center gap-1 rounded px-1.5 text-micro text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          <Network className="size-3.5" aria-hidden />
          Graph
        </button>
      </div>
      <ul>
        {rows.map((m) => {
          const { icon: Icon, tone } = ICON[m.kind];
          return (
            <li key={m.key}>
              <button
                type="button"
                title={m.key}
                onClick={() => onOpen?.(m.key)}
                className="flex h-7 w-full items-center gap-2 rounded px-1.5 text-left text-label transition-colors hover:bg-hairline"
              >
                <Icon className={cn("size-3.5 flex-shrink-0", tone)} aria-hidden />
                <span className={cn("min-w-0 flex-1 truncate", m.kind === "dead-end" ? "text-muted-foreground" : "text-text")}>
                  {m.title}
                </span>
                {m.open && <span className="flex-shrink-0 text-micro text-accent">open</span>}
                <span className="w-24 flex-shrink-0 truncate text-right text-micro text-faint">{m.by}</span>
                <span className="w-12 flex-shrink-0 text-right text-micro text-faint">{m.at}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
