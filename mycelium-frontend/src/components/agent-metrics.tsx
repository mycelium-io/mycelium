// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * What the room's agents use on the machines they run on, and bringing them
 * down to save memory, opened from the agent count in the status rail.
 *
 * Each machine first, with how much of its memory the room's agents hold. Then
 * one row per agent, heaviest first: its state, machine, RAM, CPU and how long
 * since it last worked, as its runner last said (`useRoomAgentsUsage`).
 * Opening a row lists the processes in its pane, which is where the memory
 * goes, and its subagents.
 *
 * Your own agents can be picked with their boxes, or all the idle ones at
 * once, and the bar at the foot pauses or stops them. Pause holds an agent's
 * wakes and keeps it in memory. Stop ends its process to free the memory and
 * keeps its pane; Start brings it back there, in its own conversation when its
 * CLI can resume one (Claude Code). An agent
 * pinned to Keep running is never picked by the quick picks. Someone else's
 * agents are shown, never acted on: the hub refuses anyone but the owner.
 */

import { Fragment, useMemo, useState } from "react";
import { ChevronRight, Pause, Pin, Play, Square, SquareTerminal } from "lucide-react";
import { Monogram } from "@/components/ui/monogram";
import { Button, buttonVariants } from "@/components/ui/button";
import { Tooltip } from "@/components/ui/tooltip";
import { StatusDot, type Tone } from "@/components/status-items";
import { usePrincipal } from "@/components/current-user";
import { controlAgent, keepAgent, logFetchError, type AgentControlVerb, type AgentUsage } from "@/lib/api";
import { terminalLink, useThisMachine } from "@/lib/desktop";
import { useNow } from "@/lib/relative-time";
import { useRoomAgentsUsage, useRoomRevalidate } from "@/lib/room-data";
import { cn } from "@/lib/utils";

const STATE: Record<AgentUsage["state"], { word: string; tone: Tone }> = {
  working: { word: "Working", tone: "ok" },
  idle: { word: "Idle", tone: "off" },
  blocked: { word: "Waiting", tone: "warn" },
  paused: { word: "Paused", tone: "warn" },
  stopped: { word: "Stopped", tone: "off" },
  gone: { word: "Closed", tone: "off" },
  unknown: { word: "Unknown", tone: "off" },
};

/** How long the quick pick waits before an agent counts as idle. */
const IDLE_PICK_MS = 60 * 60 * 1000;

/** "1.2 GB" or "640 MB". */
export function ram(mb: number): string {
  return mb >= 1000 ? `${(mb / 1024).toFixed(1)} GB` : `${Math.round(mb)} MB`;
}

/** What every agent in the usage holds, in MB. */
export function totalMb(agents: AgentUsage[]): number {
  return agents.reduce((s, a) => s + (a.ram_mb ?? 0), 0);
}

/** "40m", "5h", "2d". */
function span(ms: number): string {
  const m = Math.max(0, Math.round(ms / 60_000));
  if (m < 60) return `${m}m`;
  const h = Math.round(m / 60);
  return h < 48 ? `${h}h` : `${Math.round(h / 24)}d`;
}

function idleMs(a: AgentUsage, now: number): number | null {
  if (a.state === "working" || !a.idle_since) return null;
  return now - Date.parse(a.idle_since);
}

function Bar({ value, className }: { value: number; className?: string }) {
  return (
    <span aria-hidden className={cn("block h-1 overflow-hidden rounded-full bg-hairline", className)}>
      <span className="block h-full rounded-full bg-accent/70" style={{ width: `${Math.min(100, value)}%` }} />
    </span>
  );
}

const isMine = (a: AgentUsage, me: string) => !!me && (a.owner ?? "").toLowerCase() === me;
const running = (a: AgentUsage) => a.state !== "stopped" && a.state !== "gone";

export function AgentMetricsView({ roomName }: { roomName: string }) {
  const { usage, refresh } = useRoomAgentsUsage(roomName);
  const revalidate = useRoomRevalidate(roomName);
  const me = usePrincipal();
  const now = useNow();
  const here = useThisMachine();
  const [open, setOpen] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);

  const key = (a: AgentUsage) => `${a.runner}/${a.handle}`;
  const rows = usage.agents;
  const heaviest = Math.max(1, ...rows.map((a) => a.ram_mb ?? 0));
  const mine = rows.filter((a) => isMine(a, me) && running(a));
  const idle = useMemo(
    () => mine.filter((a) => !a.keep && (idleMs(a, now) ?? 0) >= IDLE_PICK_MS),
    [mine, now],
  );
  const chosen = rows.filter((a) => picked.has(key(a)));
  const frees = totalMb(chosen);

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
  const act = async (agents: AgentUsage[], verb: AgentControlVerb) => {
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
  const keep = (a: AgentUsage) =>
    keepAgent(a.room, a.handle, !a.keep, me)
      .catch(logFetchError(`keepAgent(${a.room}, ${a.handle})`))
      .finally(settle);

  if (rows.length === 0) {
    return (
      <div className="px-5 py-4 text-label text-muted-foreground">
        No machine reports what this room&apos;s agents use. A machine says once its runner is running there.
      </div>
    );
  }

  return (
    <div className="flex min-h-full flex-col">
      <div className="flex flex-1 flex-col gap-6 px-5 py-4">
        <section className="grid grid-cols-2 gap-2">
          {usage.machines.map((m) => {
            const used = totalMb(rows.filter((a) => a.runner === m.runner));
            return (
              <div key={m.runner} className="rounded-md border border-border bg-bg px-3 py-2.5">
                <div className="text-micro text-muted-foreground">{m.runner === here ? "This computer" : m.machine}</div>
                <div className="mt-0.5 text-body font-medium text-text tabular">
                  {ram(used)}
                  {m.ram_total_mb ? (
                    <span className="text-label font-normal text-faint"> of {ram(m.ram_total_mb)}</span>
                  ) : null}
                </div>
                {m.ram_total_mb ? <Bar value={(used / m.ram_total_mb) * 100} className="mt-2" /> : null}
              </div>
            );
          })}
        </section>

        <section>
          {mine.length > 0 && (
            <div className="mb-2 flex items-center gap-2">
              <Button variant="outline" size="xs" onClick={() => setPicked(new Set(idle.map(key)))}>
                Pick idle for an hour
                <span className="text-faint">{idle.length}</span>
              </Button>
              <Button
                variant="ghost"
                size="xs"
                onClick={() => setPicked(new Set(mine.filter((a) => !a.keep).map(key)))}
              >
                Pick all but kept
              </Button>
            </div>
          )}

          <table className="w-full text-label">
            <thead>
              <tr className="text-left text-micro text-faint">
                <th className="w-7 pb-1.5" />
                <th className="pb-1.5 font-normal">Agent</th>
                <th className="pb-1.5 font-normal">Machine</th>
                <th className="w-28 pb-1.5 font-normal">RAM</th>
                <th className="w-12 pb-1.5 text-right font-normal">CPU</th>
                <th className="w-14 pb-1.5 text-right font-normal">Idle</th>
                <th className="w-20 pb-1.5" />
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => {
                const k = key(a);
                const isOpen = open === k;
                const stopped = !running(a);
                const own = isMine(a, me);
                const idleFor = idleMs(a, now);
                return (
                  <Fragment key={k}>
                    <tr className={cn("group border-t border-border hover:bg-hairline", isOpen && "bg-hairline")}>
                      <td className="py-2">
                        {own && !stopped && (
                          <input
                            type="checkbox"
                            aria-label={`Pick ${a.handle}`}
                            checked={picked.has(k)}
                            onChange={() => toggle(k)}
                            className="size-3.5 accent-[var(--accent)]"
                          />
                        )}
                      </td>
                      <td className="cursor-pointer py-2 pr-2" onClick={() => !stopped && setOpen(isOpen ? null : k)}>
                        <span className="flex items-center gap-2">
                          <ChevronRight
                            className={cn(
                              "size-3.5 flex-shrink-0 text-faint transition-transform",
                              isOpen && "rotate-90",
                              stopped && "invisible",
                            )}
                            aria-hidden
                          />
                          <Monogram handle={a.handle} kind="agent" className={cn("size-5 text-[9px]", stopped && "opacity-50")} />
                          <span className={stopped ? "text-muted-foreground" : "text-text"}>{a.handle}</span>
                          <StatusDot tone={STATE[a.state].tone} />
                          <span className="text-micro text-muted-foreground">{STATE[a.state].word}</span>
                          {own ? (
                            <Tooltip content={a.keep ? "Kept running. The quick picks leave it out." : "Keep running"}>
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
                      <td className="py-2 pr-2 text-muted-foreground">{a.runner === here ? "This computer" : a.machine}</td>
                      <td className="py-2 pr-2">
                        {!stopped && a.ram_mb !== null && (
                          <span className="flex flex-col gap-1">
                            <span className="tabular text-text">{ram(a.ram_mb)}</span>
                            <Bar value={(a.ram_mb / heaviest) * 100} />
                          </span>
                        )}
                      </td>
                      <td className="py-2 text-right tabular text-muted-foreground">
                        {stopped || a.cpu === null ? "" : `${Math.round(a.cpu)}%`}
                      </td>
                      <td className="py-2 text-right tabular text-muted-foreground">
                        {idleFor === null ? "" : span(idleFor)}
                      </td>
                      <td className="py-2 text-right">
                        {own && a.state === "stopped" && (
                          <Tooltip content="Starts it in its pane again, in its own conversation when its CLI can resume one. Its machine asks first unless it trusts this hub.">
                            <Button variant="outline" size="xs" disabled={busy} onClick={() => void act([a], "start")}>
                              <Play className="size-3" /> Start
                            </Button>
                          </Tooltip>
                        )}
                        {own && a.state === "paused" && (
                          <Button variant="ghost" size="xs" disabled={busy} onClick={() => void act([a], "resume")}>
                            Resume
                          </Button>
                        )}
                      </td>
                    </tr>
                    {isOpen && (
                      <tr className="bg-hairline/50">
                        <td />
                        <td colSpan={6} className="px-6 pt-1 pb-3">
                          {a.processes.length === 0 ? (
                            <p className="py-1 text-micro text-faint">Its machine hasn&apos;t said what runs in its pane yet.</p>
                          ) : (
                            <ul className="flex flex-col">
                              {a.processes.map((p, i) => (
                                <li key={`${p.name}-${i}`} className="flex items-baseline gap-3 py-1">
                                  <span className="w-28 flex-shrink-0 truncate font-mono text-[12px] text-text">{p.name}</span>
                                  <span className="min-w-0 flex-1 truncate font-mono text-[11px] text-faint">{p.command}</span>
                                  <span className="tabular text-muted-foreground">{ram(p.ram_mb)}</span>
                                </li>
                              ))}
                            </ul>
                          )}
                          {(a.subagents_open ?? 0) > 0 && (
                            <p className="mt-2 text-micro text-muted-foreground">
                              {a.subagents_open} subagent{a.subagents_open === 1 ? "" : "s"} working inside it, in its memory.
                            </p>
                          )}
                          {a.runner === here && a.pane && (
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
        </section>
      </div>

      {chosen.length > 0 && (
        <div className="sticky bottom-0 flex items-center gap-2 border-t border-border bg-surface px-5 py-3">
          <span className="text-label text-text">{chosen.length} picked</span>
          <button type="button" onClick={() => setPicked(new Set())} className="text-micro text-muted-foreground hover:text-text">
            Clear
          </button>
          <span className="ml-auto text-micro text-muted-foreground">Stopping frees {ram(frees)}</span>
          <Tooltip content="Holds their wakes. They stay in memory and resume at once.">
            <Button variant="outline" size="sm" disabled={busy} onClick={() => void act(chosen, "pause")}>
              <Pause className="size-3.5" /> Pause
            </Button>
          </Tooltip>
          <Tooltip content="Ends their processes to free the memory. Their panes stay, and Start brings each back there.">
            <Button size="sm" disabled={busy} onClick={() => void act(chosen, "stop")}>
              <Square className="size-3.5" /> Stop {chosen.length}
            </Button>
          </Tooltip>
        </div>
      )}
    </div>
  );
}
