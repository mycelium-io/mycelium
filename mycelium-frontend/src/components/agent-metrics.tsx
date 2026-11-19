// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The room's agents, what the ones on this computer use, and bringing them
 * down to save memory, opened from the status rail.
 *
 * The rows are the hub's list of the room's agents on connected machines:
 * where each runs, its state, whether it's kept running (`useRoomAgentsRunning`).
 * The numbers are this computer's alone: the runner here reads each local
 * agent's memory, CPU and processes and the desktop app reads them
 * (`useLocalUsage`). None of it goes to the hub, so an agent on another
 * machine shows its state and machine with no numbers, and doesn't open.
 *
 * Agents are selected the way any list selects: a box per row, and a box in
 * the header for every row shown. The Idle filter shows the agents idle or
 * paused, leaving out ones kept running, so selecting all of them is one
 * click. The bar at the foot pauses or stops the selection. Only your own
 * agents can be selected; the hub refuses anyone but the owner.
 */

import { Fragment, useMemo, useState } from "react";
import { ChevronRight, Pause, Pin, Play, Square, SquareTerminal } from "lucide-react";
import { Monogram } from "@/components/ui/monogram";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { StatusDot, type Tone } from "@/components/status-items";
import { usePrincipal } from "@/components/current-user";
import { controlAgent, keepAgent, logFetchError, type AgentControlVerb, type AgentRunning } from "@/lib/api";
import { terminalLink, useLocalUsage, type LocalAgentUsage, type LocalUsage } from "@/lib/desktop";
import { useNow } from "@/lib/relative-time";
import { useRoomAgentsRunning, useRoomRevalidate } from "@/lib/room-data";
import { cn } from "@/lib/utils";

const STATE: Record<AgentRunning["state"], { word: string; tone: Tone }> = {
  working: { word: "Working", tone: "ok" },
  idle: { word: "Idle", tone: "off" },
  blocked: { word: "Waiting", tone: "warn" },
  paused: { word: "Paused", tone: "warn" },
  stopped: { word: "Stopped", tone: "off" },
  gone: { word: "Closed", tone: "off" },
  unknown: { word: "Unknown", tone: "off" },
};

/** "1.2 GB" or "640 MB". */
export function ram(mb: number): string {
  return mb >= 1000 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

/** What this computer's agents hold, in MB. */
export function localMb(usage: LocalUsage | null): number {
  return (usage?.agents ?? []).reduce((s, a) => s + (a.ram_mb ?? 0), 0);
}

/** "40m", "5h", "2d". */
function span(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60_000));
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}h` : `${Math.round(h / 24)}d`;
}

function Bar({ value, className }: { value: number; className?: string }) {
  return (
    <span aria-hidden className={cn("block h-1 overflow-hidden rounded-full bg-hairline", className)}>
      <span className="block h-full rounded-full bg-accent/70" style={{ width: `${Math.min(100, value)}%` }} />
    </span>
  );
}

const running = (a: AgentRunning) => a.state !== "stopped" && a.state !== "gone";
/** What Idle shows: an agent not working and not waiting on a person, unless kept. */
const isIdle = (a: AgentRunning) => !a.keep && (a.state === "idle" || a.state === "paused");

export function AgentMetricsView({ roomName }: { roomName: string }) {
  const { running: rows, refresh } = useRoomAgentsRunning(roomName);
  const local = useLocalUsage();
  const revalidate = useRoomRevalidate(roomName);
  const me = usePrincipal();
  const now = useNow();
  const [open, setOpen] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [filter, setFilter] = useState<"all" | "idle">("all");
  const [busy, setBusy] = useState(false);

  const key = (a: AgentRunning) => `${a.runner}/${a.room}/${a.handle}`;
  const here = (a: AgentRunning) => local !== null && a.runner === local.runner;
  const usageOf = useMemo(() => {
    const by = new Map<string, LocalAgentUsage>();
    for (const u of local?.agents ?? []) by.set(`${u.room}/${u.handle}`, u);
    return (a: AgentRunning) => (here(a) ? by.get(`${a.room}/${a.handle}`) : undefined);
    // `here` reads `local`, which is the dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [local]);
  const mb = (a: AgentRunning) => usageOf(a)?.ram_mb ?? 0;

  // This computer's agents first, heaviest first; then the ones elsewhere.
  const sorted = [...rows].sort((a, b) => Number(!here(a)) - Number(!here(b)) || mb(b) - mb(a));
  const heaviest = Math.max(1, ...sorted.map(mb));
  const shown = filter === "idle" ? sorted.filter(isIdle) : sorted;
  const own = (a: AgentRunning) => !!me && (a.owner ?? "").toLowerCase() === me;
  const selectable = shown.filter((a) => own(a) && running(a));
  const allPicked = selectable.length > 0 && selectable.every((a) => picked.has(key(a)));
  const somePicked = selectable.some((a) => picked.has(key(a)));
  const chosen = sorted.filter((a) => picked.has(key(a)));
  const frees = chosen.reduce((s, a) => s + mb(a), 0);
  const total = localMb(local);

  const toggle = (k: string) =>
    setPicked((prev) => {
      const next = new Set(prev);
      if (next.has(k)) next.delete(k);
      else next.add(k);
      return next;
    });

  const settle = () => {
    refresh();
    revalidate();
  };
  const act = async (agents: AgentRunning[], verb: AgentControlVerb) => {
    setBusy(true);
    try {
      await Promise.all(
        agents.map((a) =>
          controlAgent(a.room, a.handle, verb, me).catch(logFetchError(`controlAgent(${a.room}, ${a.handle}, ${verb})`)),
        ),
      );
    } finally {
      setBusy(false);
      setPicked(new Set());
      settle();
    }
  };
  const keep = (a: AgentRunning) =>
    keepAgent(a.room, a.handle, !a.keep, me)
      .catch(logFetchError(`keepAgent(${a.room}, ${a.handle})`))
      .finally(settle);

  return (
    <div className="flex min-h-full flex-col">
      <div className="flex flex-1 flex-col gap-6 px-5 py-4">
        {local && (
          <section>
            <div className="rounded-md border border-border bg-bg px-3 py-2.5">
              <div className="text-micro text-muted-foreground">This computer</div>
              <div className="mt-0.5 text-body font-medium text-text tabular">
                {ram(total)}
                {local.ram_total_mb ? (
                  <span className="text-label font-normal text-faint"> of {ram(local.ram_total_mb)}</span>
                ) : null}
              </div>
              {local.ram_total_mb ? <Bar value={(total / local.ram_total_mb) * 100} className="mt-2" /> : null}
            </div>
            <p className="mt-2 text-micro text-muted-foreground">Numbers are for this computer only. They never leave it.</p>
          </section>
        )}

        <section>
          <div role="tablist" className="mb-2 inline-flex rounded-md border border-border p-0.5 text-micro">
            {(
              [
                ["all", "All", sorted.length],
                ["idle", "Idle", sorted.filter(isIdle).length],
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
                      disabled={selectable.length === 0}
                      ref={(el) => {
                        if (el) el.indeterminate = somePicked && !allPicked;
                      }}
                      onChange={() =>
                        setPicked((prev) => {
                          const next = new Set(prev);
                          for (const a of selectable) {
                            if (allPicked) next.delete(key(a));
                            else next.add(key(a));
                          }
                          return next;
                        })
                      }
                      className="size-3.5 accent-[var(--accent)]"
                    />
                  </th>
                  <th className="font-normal">Agent</th>
                  <th className="font-normal">Machine</th>
                  <th className="w-40 font-normal">RAM</th>
                  <th className="w-12 text-right font-normal">CPU</th>
                  <th className="w-14 text-right font-normal">Idle</th>
                  <th className="w-20" />
                </tr>
              </thead>
              <tbody>
                {shown.length === 0 && (
                  <tr className="h-11 border-t border-border">
                    <td colSpan={7} className="py-2 text-center text-micro text-muted-foreground">
                      {filter === "idle" ? "No idle agents." : "No machine is running this room's agents."}
                    </td>
                  </tr>
                )}
                {shown.map((a) => {
                  const k = key(a);
                  const isOpen = open === k;
                  const stopped = !running(a);
                  const used = usageOf(a);
                  const opens = !stopped && !!used;
                  const mine = own(a);
                  const idleFor = used?.idle_since && a.state !== "working" ? now - Date.parse(used.idle_since) : null;
                  return (
                    <Fragment key={k}>
                      <tr className={cn("group h-11 border-t border-border hover:bg-hairline", isOpen && "bg-hairline")}>
                        <td className="py-2">
                          {mine && !stopped && (
                            <input
                              type="checkbox"
                              aria-label={`Select ${a.handle}`}
                              checked={picked.has(k)}
                              onChange={() => toggle(k)}
                              className="size-3.5 accent-[var(--accent)]"
                            />
                          )}
                        </td>
                        <td
                          className={cn("py-2 pr-2", opens && "cursor-pointer")}
                          onClick={() => opens && setOpen(isOpen ? null : k)}
                        >
                          <span className="flex items-center gap-2">
                            <ChevronRight
                              className={cn(
                                "size-3.5 flex-shrink-0 text-faint transition-transform",
                                isOpen && "rotate-90",
                                !opens && "invisible",
                              )}
                              aria-hidden
                            />
                            <Monogram handle={a.handle} kind="agent" className={cn("size-5 text-[9px]", stopped && "opacity-50")} />
                            <span className={stopped ? "text-muted-foreground" : "text-text"}>{a.handle}</span>
                            <StatusDot tone={STATE[a.state].tone} />
                            <span className="text-micro text-muted-foreground">{STATE[a.state].word}</span>
                            {mine ? (
                              <Tooltip content={a.keep ? "Always kept running. It won't show under Idle." : "Keep running"}>
                                <button
                                  type="button"
                                  aria-label={a.keep ? `Stop keeping ${a.handle} running` : `Keep ${a.handle} running`}
                                  aria-pressed={a.keep}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    void keep(a);
                                  }}
                                  className={cn(
                                    "grid size-5 place-items-center rounded hover:bg-hairline",
                                    a.keep ? "text-accent" : "text-faint opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
                                  )}
                                >
                                  <Pin className="size-3" fill={a.keep ? "currentColor" : "none"} />
                                </button>
                              </Tooltip>
                            ) : (
                              a.keep && (
                                <Tooltip content="Kept running by its owner">
                                  <Pin className="size-3 text-faint" fill="currentColor" aria-label="Kept running" />
                                </Tooltip>
                              )
                            )}
                          </span>
                        </td>
                        <td className="py-2 pr-2 text-muted-foreground">{here(a) ? "This computer" : a.machine}</td>
                        <td className="py-2 pr-2">
                          {!stopped && used?.ram_mb != null && (
                            <span className="flex items-center gap-2">
                              <span className="w-14 flex-shrink-0 tabular text-text">{ram(used.ram_mb)}</span>
                              <Bar value={(used.ram_mb / heaviest) * 100} className="flex-1" />
                            </span>
                          )}
                        </td>
                        <td className="py-2 text-right tabular text-muted-foreground">
                          {stopped || used?.cpu == null ? "" : `${Math.round(used.cpu)}%`}
                        </td>
                        <td className="py-2 text-right tabular text-muted-foreground">
                          {idleFor === null ? "" : span(idleFor)}
                        </td>
                        <td className="py-2 text-right">
                          {mine && a.state === "stopped" && (
                            <Tooltip content="Starts it again in its pane, in its own conversation if its CLI can resume one. Its machine asks first unless it trusts this hub.">
                              <Button variant="outline" size="xs" disabled={busy} onClick={() => void act([a], "start")}>
                                <Play className="size-3" /> Start
                              </Button>
                            </Tooltip>
                          )}
                          {mine && a.state === "paused" && (
                            <Button variant="ghost" size="xs" disabled={busy} onClick={() => void act([a], "resume")}>
                              Resume
                            </Button>
                          )}
                        </td>
                      </tr>
                      {isOpen && used && (
                        <tr className="bg-hairline/50">
                          <td />
                          <td colSpan={6} className="px-6 pt-1 pb-3">
                            {used.processes.length === 0 ? (
                              <p className="py-1 text-micro text-faint">Nothing has been read from its pane yet.</p>
                            ) : (
                              <ul className="flex flex-col">
                                {used.processes.map((p, i) => (
                                  <li key={`${p.name}-${i}`} className="flex items-baseline gap-3 py-1">
                                    <span className="w-28 flex-shrink-0 truncate font-mono text-[12px] text-text">{p.name}</span>
                                    <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-faint">{p.command}</span>
                                    <span className="tabular text-muted-foreground">{ram(p.ram_mb)}</span>
                                  </li>
                                ))}
                              </ul>
                            )}
                            {a.pane && (
                              <a
                                href={terminalLink(a.pane)}
                                className={buttonVariants({ variant: "outline", size: "xs", className: "mt-3" })}
                              >
                                <SquareTerminal className="size-3" /> Open its terminal
                              </a>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  );
                })}
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
          {frees > 0 && <span className="ml-auto text-micro text-muted-foreground">Stopping frees {ram(frees)}</span>}
          <Tooltip content="They stop taking new work but stay in memory.">
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void act(chosen, "pause")} className={cn(frees === 0 && "ml-auto")}>
              <Pause className="size-3.5" /> Pause
            </Button>
          </Tooltip>
          <Tooltip content="Ends them to free up memory. Their panes stay, so Start brings each back.">
            <Button size="sm" disabled={busy} onClick={() => void act(chosen, "stop")}>
              <Square className="size-3.5" /> Stop {chosen.length}
            </Button>
          </Tooltip>
        </div>
      )}
    </div>
  );
}
