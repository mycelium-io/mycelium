// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * MOCK: what the room's agents use on the machines they run on, and bringing
 * them down to save memory, opened from the agent count in the status rail.
 *
 * Each machine first, with how much of its RAM the room's agents hold. Then
 * one row per agent, heaviest first: its state, machine, RAM, CPU and how
 * long since its last turn. Opening a row lists the processes in its pane,
 * which is where the memory goes, and the subagents running inside it.
 *
 * Agents are selected the way any list selects: a box per row, and a box in
 * the header for every row shown. The Idle filter shows the agents not
 * working, leaving out ones marked Keep running, so selecting all of them is
 * one click. The bar at the foot pauses or stops the selection. Pause holds an
 * agent's wakes and keeps it in memory. Stop ends its process to free the
 * memory, and Start brings it back in the same conversation.
 */

import { Fragment, useState } from "react";
import { ChevronRight, Pause, Pin, Play, Square, SquareTerminal } from "lucide-react";
import { Monogram } from "@/components/ui/monogram";
import { Button } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { StatusDot, type Tone } from "@/components/status-items";
import { AGENT_METRICS, HERE, MACHINE, NO_METRICS, ram, totalMb, type AgentMetrics } from "@/mocks/agent-metrics";
import { cn } from "@/lib/utils";

const STATE: Record<AgentMetrics["state"], { word: string; tone: Tone }> = {
  working: { word: "Working", tone: "ok" },
  idle: { word: "Idle", tone: "off" },
  blocked: { word: "Blocked", tone: "warn" },
  paused: { word: "Paused", tone: "warn" },
  stopped: { word: "Stopped", tone: "off" },
};

function Bar({ value, className }: { value: number; className?: string }) {
  return (
    <span aria-hidden className={cn("block h-1 overflow-hidden rounded-full bg-hairline", className)}>
      <span className="block h-full rounded-full bg-accent/70" style={{ width: `${Math.min(100, value)}%` }} />
    </span>
  );
}

export function AgentMetricsView({ initiallyOpen, initiallyPicked }: { initiallyOpen?: string; initiallyPicked?: string[] }) {
  const [open, setOpen] = useState<string | null>(initiallyOpen ?? null);
  const [picked, setPicked] = useState<Set<string>>(new Set(initiallyPicked ?? []));
  // This computer's agents first, heaviest first; then the ones elsewhere.
  const rows = [...AGENT_METRICS].sort(
    (a, b) => Number(a.machine !== HERE) - Number(b.machine !== HERE) || b.ramMb - a.ramMb,
  );
  const heaviest = rows[0]?.ramMb ?? 1;
  const [filter, setFilter] = useState<"all" | "idle">("all");
  const isIdle = (a: AgentMetrics) => !a.keep && (a.state === "idle" || a.state === "paused");
  const shown = filter === "idle" ? rows.filter(isIdle) : rows;
  const selectable = shown.filter((a) => a.state !== "stopped");
  const allPicked = selectable.length > 0 && selectable.every((a) => picked.has(a.handle));
  const somePicked = selectable.some((a) => picked.has(a.handle));
  const chosen = rows.filter((a) => picked.has(a.handle));
  const frees = chosen.reduce((s, a) => s + a.ramMb, 0);

  const toggle = (h: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(h)) next.delete(h);
      else next.add(h);
      return next;
    });

  return (
    <div className="flex min-h-full flex-col">
      <div className="flex flex-1 flex-col gap-6 px-5 py-4">
        <section>
          <div className="rounded-md border border-border bg-bg px-3 py-2.5">
            <div className="text-micro text-muted-foreground">{MACHINE.name}</div>
            <div className="mt-0.5 text-body font-medium text-text tabular">
              {ram(totalMb)} <span className="text-label font-normal text-faint">of {MACHINE.ramGb} GB</span>
            </div>
            <Bar value={(totalMb / (MACHINE.ramGb * 1024)) * 100} className="mt-2" />
          </div>
          <p className="mt-2 text-micro text-muted-foreground">
            Numbers are for this computer only. They never leave it.
          </p>
        </section>

        <section>
          <div role="tablist" className="mb-2 inline-flex rounded-md border border-border p-0.5 text-micro">
            {(
              [
                ["all", "All", rows.length],
                ["idle", "Idle", rows.filter(isIdle).length],
              ] as const
            ).map(([value, label, count]) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={filter === value}
                onClick={() => setFilter(value)}
                className={cn(
                  "flex h-6 items-center gap-1.5 rounded px-2.5 transition-colors",
                  filter === value ? "bg-hairline text-text" : "text-muted-foreground hover:text-text",
                )}
              >
                {label}
                <span className="text-faint">{count}</span>
              </button>
            ))}
          </div>

          {/* Boxed, with room at both ends, so the rows sit on the page rather than run to its edges. */}
          <div className="overflow-hidden rounded-md border border-border bg-bg">
          <table className="w-full text-label [&_td:first-child]:pl-3 [&_td:last-child]:pr-3 [&_th:first-child]:pl-3 [&_th:last-child]:pr-3">
            <thead>
              <tr className="bg-surface text-left text-micro text-faint [&>th]:py-2">
                <th className="w-10">
                  <input
                    type="checkbox"
                    aria-label="Select all"
                    checked={allPicked}
                    ref={(el) => {
                      if (el) el.indeterminate = somePicked && !allPicked;
                    }}
                    onChange={() =>
                      setPicked((prev) => {
                        const next = new Set(prev);
                        for (const a of selectable) {
                          if (allPicked) next.delete(a.handle);
                          else next.add(a.handle);
                        }
                        return next;
                      })
                    }
                    className="size-3.5 accent-[var(--accent)]"
                  />
                </th>
                <th className="font-normal">Agent</th>
                <th className="font-normal">Machine</th>
                <th className="w-28 font-normal">RAM</th>
                <th className="w-12 text-right font-normal">CPU</th>
                <th className="w-14 text-right font-normal">Idle</th>
                <th className="w-16" />
              </tr>
            </thead>
            <tbody>
              {shown.map((a) => {
                const isOpen = open === a.handle;
                const stopped = a.state === "stopped";
                const remote = a.machine !== HERE;
                return (
                  <Fragment key={a.handle}>
                    <tr className={cn("group border-t border-border hover:bg-hairline", isOpen && "bg-hairline")}>
                      <td className="py-2">
                        {!stopped && (
                          <input
                            type="checkbox"
                            aria-label={`Select ${a.handle}`}
                            checked={picked.has(a.handle)}
                            onChange={() => toggle(a.handle)}
                            className="size-3.5 accent-[var(--accent)]"
                          />
                        )}
                      </td>
                      <td
                        className={cn("py-2 pr-2", !stopped && !remote && "cursor-pointer")}
                        onClick={() => !stopped && !remote && setOpen(isOpen ? null : a.handle)}
                      >
                        <span className="flex items-center gap-2">
                          <ChevronRight
                            className={cn(
                              "size-3.5 flex-shrink-0 text-faint transition-transform",
                              isOpen && "rotate-90",
                              (stopped || remote) && "invisible",
                            )}
                            aria-hidden
                          />
                          <Monogram handle={a.handle} kind="agent" className={cn("size-5 text-[9px]", stopped && "opacity-50")} />
                          <span className={stopped ? "text-muted-foreground" : "text-text"}>{a.handle}</span>
                          <StatusDot tone={STATE[a.state].tone} />
                          <span className="text-micro text-muted-foreground">{STATE[a.state].word}</span>
                          <Tooltip content={a.keep ? "Always kept running. It won't show under Idle." : "Keep running"}>
                            <button
                              type="button"
                              aria-label={a.keep ? `Stop keeping ${a.handle} running` : `Keep ${a.handle} running`}
                              aria-pressed={!!a.keep}
                              onClick={(e) => e.stopPropagation()}
                              className={cn(
                                "grid size-5 place-items-center rounded hover:bg-hairline",
                                a.keep ? "text-accent" : "text-faint opacity-0 group-hover:opacity-100",
                              )}
                            >
                              <Pin className="size-3" fill={a.keep ? "currentColor" : "none"} />
                            </button>
                          </Tooltip>
                        </span>
                      </td>
                      <td className="py-2 pr-2 text-muted-foreground">{a.machine}</td>
                      <td className="py-2 pr-2">
                        {!stopped && !remote && (
                          <span className="flex flex-col gap-1">
                            <span className="tabular text-text">{ram(a.ramMb)}</span>
                            <Bar value={(a.ramMb / heaviest) * 100} />
                          </span>
                        )}
                      </td>
                      <td className="py-2 text-right tabular text-muted-foreground">
                        {stopped || remote ? "" : `${a.cpu}%`}
                      </td>
                      <td className="py-2 text-right tabular text-muted-foreground">
                        {a.state === "working" ? "" : a.idleFor}
                      </td>
                      <td className="py-2 text-right">
                        {stopped && (
                          <Tooltip content="Picks up where it left off">
                            <Button variant="outline" size="xs">
                              <Play className="size-3" /> Start
                            </Button>
                          </Tooltip>
                        )}
                        {a.state === "paused" && (
                          <Button variant="ghost" size="xs">
                            Resume
                          </Button>
                        )}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-hairline/50">
                        <td />
                        <td colSpan={6} className="px-6 pt-1 pb-3">
                          <ul className="flex flex-col">
                            {a.processes.map((p) => (
                              <li key={p.name} className="flex items-baseline gap-3 py-1">
                                <span className="w-28 flex-shrink-0 font-mono text-[12px] text-text">{p.name}</span>
                                <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-faint">{p.command}</span>
                                <span className="tabular text-muted-foreground">{ram(p.ramMb)}</span>
                              </li>
                            ))}
                          </ul>
                          {a.subagents && (
                            <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-muted-foreground">
                              <span className="text-faint">Subagents inside it</span>
                              {a.subagents.map((s) => (
                                <span key={s.handle} className="flex items-center gap-1.5">
                                  <StatusDot tone={s.state === "working" ? "ok" : "off"} />
                                  {s.handle}
                                </span>
                              ))}
                            </div>
                          )}
                          {a.machine === "This computer" && (
                            <Button variant="outline" size="xs" className="mt-3">
                              <SquareTerminal className="size-3" /> Open its terminal
                            </Button>
                          )}
                        </td>
                      </tr>
                    )}
                  </Fragment>
                );
              })}
              {NO_METRICS.map((m) => (
                <tr key={m.handle} className="border-t border-border">
                  <td />
                  <td className="py-2 pr-2">
                    <span className="flex items-center gap-2 pl-5.5">
                      <Monogram handle={m.handle} kind="agent" className="size-5 text-[9px]" />
                      <span className="text-muted-foreground">{m.handle}</span>
                    </span>
                  </td>
                  <td colSpan={5} className="py-2 text-micro text-faint">
                    {m.why}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        </section>
      </div>

      {chosen.length > 0 && (
        <div className="sticky bottom-0 flex items-center gap-2 border-t border-border bg-surface px-5 py-3">
          <span className="text-label text-text">{chosen.length} selected</span>
          <button type="button" onClick={() => setPicked(new Set())} className="text-micro text-muted-foreground hover:text-text">
            Clear
          </button>
          <span className="ml-auto text-micro text-muted-foreground">Stopping frees {ram(frees)}</span>
          <Tooltip content="They stop taking new work but stay in memory.">
            <Button variant="outline" size="sm">
              <Pause className="size-3.5" /> Pause
            </Button>
          </Tooltip>
          <Tooltip content="Closes them to free up memory. Start picks up where they left off.">
            <Button size="sm">
              <Square className="size-3.5" /> Stop {chosen.length}
            </Button>
          </Tooltip>
        </div>
      )}
    </div>
  );
}
