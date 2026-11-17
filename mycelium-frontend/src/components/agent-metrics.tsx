// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * MOCK: what the room's agents use on the machines they run on, opened from
 * the agent count in the status rail.
 *
 * Each machine first, with how much of its RAM the room's agents hold. Then
 * one row per agent, heaviest first: its state, machine, RAM, CPU and how long
 * it has run. Opening a row lists the processes in its pane, which is where
 * the memory goes (an agent's MCP servers count toward it), and the subagents
 * running inside it. Members that report nothing say why, last.
 */

import { Fragment, useState } from "react";
import { ChevronRight, SquareTerminal } from "lucide-react";
import { Monogram } from "@/components/ui/monogram";
import { StatusDot, type Tone } from "@/components/status-items";
import { AGENT_METRICS, MACHINES, NO_METRICS, ram, type AgentMetrics } from "@/mocks/agent-metrics";
import { cn } from "@/lib/utils";

const STATE: Record<AgentMetrics["state"], { word: string; tone: Tone }> = {
  working: { word: "Working", tone: "ok" },
  idle: { word: "Idle", tone: "off" },
  blocked: { word: "Blocked", tone: "warn" },
};

function Bar({ value, className }: { value: number; className?: string }) {
  return (
    <span aria-hidden className={cn("block h-1 overflow-hidden rounded-full bg-hairline", className)}>
      <span className="block h-full rounded-full bg-accent/70" style={{ width: `${Math.min(100, value)}%` }} />
    </span>
  );
}

export function AgentMetricsView({ initiallyOpen }: { initiallyOpen?: string }) {
  const [open, setOpen] = useState<string | null>(initiallyOpen ?? null);
  const rows = [...AGENT_METRICS].sort((a, b) => b.ramMb - a.ramMb);
  const heaviest = rows[0]?.ramMb ?? 1;

  return (
    <div className="flex flex-col gap-6 overflow-y-auto px-5 py-4">
      <section className="grid grid-cols-2 gap-2">
        {MACHINES.map((m) => {
          const used = AGENT_METRICS.filter((a) => a.machine === m.name).reduce((s, a) => s + a.ramMb, 0);
          return (
            <div key={m.name} className="rounded-md border border-border bg-bg px-3 py-2.5">
              <div className="text-micro text-muted-foreground">{m.name}</div>
              <div className="mt-0.5 text-body font-medium text-text tabular">
                {ram(used)} <span className="text-label font-normal text-faint">of {m.ramGb} GB</span>
              </div>
              <Bar value={(used / (m.ramGb * 1024)) * 100} className="mt-2" />
            </div>
          );
        })}
      </section>

      <table className="w-full text-label">
        <thead>
          <tr className="text-left text-micro text-faint">
            <th className="pb-1.5 font-normal">Agent</th>
            <th className="pb-1.5 font-normal">Machine</th>
            <th className="w-32 pb-1.5 font-normal">RAM</th>
            <th className="w-12 pb-1.5 text-right font-normal">CPU</th>
            <th className="w-10 pb-1.5 text-right font-normal">Up</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((a) => {
            const isOpen = open === a.handle;
            return (
              <Fragment key={a.handle}>
                <tr
                  onClick={() => setOpen(isOpen ? null : a.handle)}
                  className={cn("cursor-pointer border-t border-border hover:bg-hairline", isOpen && "bg-hairline")}
                >
                  <td className="py-2 pr-2">
                    <span className="flex items-center gap-2">
                      <ChevronRight
                        className={cn("size-3.5 flex-shrink-0 text-faint transition-transform", isOpen && "rotate-90")}
                        aria-hidden
                      />
                      <Monogram handle={a.handle} kind="agent" className="size-5 text-[9px]" />
                      <span className="text-text">{a.handle}</span>
                      <StatusDot tone={STATE[a.state].tone} />
                      <span className="text-micro text-muted-foreground">{STATE[a.state].word}</span>
                    </span>
                  </td>
                  <td className="py-2 pr-2 text-muted-foreground">{a.machine}</td>
                  <td className="py-2 pr-2">
                    <span className="flex flex-col gap-1">
                      <span className="tabular text-text">{ram(a.ramMb)}</span>
                      <Bar value={(a.ramMb / heaviest) * 100} />
                    </span>
                  </td>
                  <td className="py-2 text-right tabular text-muted-foreground">{a.cpu}%</td>
                  <td className="py-2 text-right tabular text-muted-foreground">{a.up}</td>
                </tr>
                {isOpen && (
                  <tr className="bg-hairline/50">
                    <td colSpan={5} className="px-8 pt-1 pb-3">
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
                        <button
                          type="button"
                          className="mt-3 flex items-center gap-1.5 rounded border border-border px-2 py-1 text-micro text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
                        >
                          <SquareTerminal className="size-3.5" aria-hidden />
                          Open its terminal
                        </button>
                      )}
                    </td>
                  </tr>
                )}
              </Fragment>
            );
          })}
          {NO_METRICS.map((m) => (
            <tr key={m.handle} className="border-t border-border">
              <td className="py-2 pr-2">
                <span className="flex items-center gap-2 pl-5.5">
                  <Monogram handle={m.handle} kind="agent" className="size-5 text-[9px]" />
                  <span className="text-muted-foreground">{m.handle}</span>
                </span>
              </td>
              <td colSpan={4} className="py-2 text-micro text-faint">
                {m.why}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
