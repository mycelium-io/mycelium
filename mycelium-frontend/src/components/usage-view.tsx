// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Usage: what this hub is used for, read from the usage events it records.
 *
 * The Metrics page's first tab. Everything here is per hub: how much work is
 * filed and finished, which ways of working get used and whether they end
 * well, who does the work, and whether the board keeps up. Comparing hubs
 * (activation, retention by cohort) needs many hubs' events, so it isn't here.
 */

import { useState, type ReactNode } from "react";
import type { UsageKpis } from "@/lib/api";
import { useUsage } from "@/lib/metrics-data";
import { fmtNum } from "@/lib/metrics-format";
import { Dot, Figure, Figures, Label, Note, Nothing, Panel } from "@/components/metrics-parts";

const RANGES = [30, 90] as const;

/** Hours as a person would say them: minutes under an hour, days past two. */
export function fmtHours(h: number | null | undefined): string {
  if (h === null || h === undefined) return "-";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`;
  if (h < 48) return `${h.toFixed(h < 10 ? 1 : 0)}h`;
  return `${Math.round(h / 24)}d`;
}

const sum = (counts: Record<string, number> | undefined) =>
  Object.values(counts ?? {}).reduce((a, b) => a + b, 0);

/** Days folded into weeks, newest last, once a window is long enough to want it. */
export function bucket(daily: UsageKpis["daily"]): { label: string; filed: number; resolved: number }[] {
  if (daily.length < 56) return daily.map(d => ({ label: d.day.slice(5), ...d }));
  const weeks: { label: string; filed: number; resolved: number }[] = [];
  for (let end = daily.length; end > 0; end -= 7) {
    const week = daily.slice(Math.max(0, end - 7), end);
    weeks.unshift({
      label: week[0].day.slice(5),
      filed: week.reduce((n, d) => n + d.filed, 0),
      resolved: week.reduce((n, d) => n + d.resolved, 0),
    });
  }
  return weeks;
}

/** One way of starting work, and how often it ends well. */
interface Way {
  name: string;
  from: string;
  runs: number;
  /** Share that ended well, or null where "well" has no meaning (a plain task resolves). */
  well: number | null;
  wellWord: string;
}

export function waysOf(usage: UsageKpis): Way[] {
  const ways: Way[] = [
    { name: "Tasks resolved", from: "task_resolved", runs: usage.tasks.resolved, well: null, wellWord: "" },
  ];
  const named: Record<string, string> = {
    review: "Review",
    swarm: "Split",
    gated: "Gated",
    "fan-out": "Fan-out",
    "round-robin": "Round robin",
    concord: "Help them agree",
    accord: "Get on the same page",
    custom: "Custom flows",
  };
  for (const [flow, outcomes] of Object.entries(usage.flows).sort((a, b) => sum(b[1]) - sum(a[1]))) {
    const runs = sum(outcomes);
    // An agreement a pick certified ends `converged`: a success, like `resolved`.
    const good = (outcomes.resolved ?? 0) + (outcomes.converged ?? 0);
    ways.push({
      name: named[flow] ?? flow,
      from: `flow ${flow}`,
      runs,
      well: runs ? good / runs : null,
      wellWord: flow === "review" ? "passed" : flow === "concord" ? "agreed" : "resolved",
    });
  }
  const negotiations = sum(usage.negotiations);
  if (negotiations) {
    ways.push({
      name: "Settle",
      from: "negotiation",
      runs: negotiations,
      well: (usage.negotiations.converged ?? 0) / negotiations,
      wellWord: "converged",
    });
  }
  return ways;
}

function tone(rate: number): string {
  if (rate >= 0.75) return "var(--green)";
  if (rate >= 0.6) return "var(--yellow)";
  return "var(--red)";
}

function Bar({ value, max, color = "var(--accent)" }: { value: number; max: number; color?: string }) {
  return (
    <span className="block h-1.5 w-full overflow-hidden rounded-full bg-hairline">
      <span className="block h-full rounded-full" style={{ width: `${max ? (value / max) * 100 : 0}%`, background: color }} />
    </span>
  );
}

function Pane({ title, question, children }: { title: string; question: string; children: ReactNode }) {
  return (
    <Panel title={title} meta={<span className="text-faint">{question}</span>}>
      {children}
    </Panel>
  );
}

function KeepingUp({ usage }: { usage: UsageKpis }) {
  const rows = bucket(usage.daily);
  const peak = Math.max(1, ...rows.flatMap(r => [r.filed, r.resolved]));
  const weekly = rows.length !== usage.daily.length;
  const last = rows.slice(weekly ? -4 : -7);
  const filed = last.reduce((n, r) => n + r.filed, 0);
  const resolved = last.reduce((n, r) => n + r.resolved, 0);
  return (
    <Pane title="Is the board keeping up?" question={`Tasks filed and resolved per ${weekly ? "week" : "day"}`}>
      <div className="px-4 pb-2">
        <div className="flex h-24 items-end gap-1" aria-label={`Tasks filed and resolved per ${weekly ? "week" : "day"}`} role="img">
          {rows.map(r => (
            <div key={r.label} className="flex h-full flex-1 items-end gap-px" title={`${r.label}: ${r.filed} filed, ${r.resolved} resolved`}>
              <span className="flex-1 rounded-t-[2px] bg-border2" style={{ height: `${(r.filed / peak) * 100}%` }} />
              <span className="flex-1 rounded-t-[2px] bg-accent" style={{ height: `${(r.resolved / peak) * 100}%` }} />
            </div>
          ))}
        </div>
        <div className="mt-1 flex items-center gap-3 text-micro text-faint">
          <span className="flex items-center gap-1"><span className="size-1.5 rounded-[1px] bg-border2" /> filed</span>
          <span className="flex items-center gap-1"><span className="size-1.5 rounded-[1px] bg-accent" /> resolved</span>
          <span className="ml-auto tabular">{rows[0]?.label} to {rows[rows.length - 1]?.label}</span>
        </div>
      </div>
      <Note>
        Over the last {last.length} {weekly ? "weeks" : "days"}, {fmtNum(resolved)} resolved for every {fmtNum(filed)} filed
        {filed ? ` (${Math.round((resolved / filed) * 100)}%)` : ""}. A gap that keeps growing means the board is filling up
        faster than work gets done.
      </Note>
    </Pane>
  );
}

function WaysOfWorking({ usage }: { usage: UsageKpis }) {
  const ways = waysOf(usage);
  const most = Math.max(1, ...ways.map(w => w.runs));
  return (
    <Pane title="Ways of working" question="What gets used, and whether it ends well">
      <div className="overflow-x-auto px-4 pb-2">
        <table className="w-full min-w-[34rem] text-label tabular">
          <thead>
            <tr className="text-left text-micro text-faint">
              <th className="py-1.5 font-medium">Started as</th>
              <th className="py-1.5 font-medium">Counted from</th>
              <th className="w-40 py-1.5 pr-6 font-medium">Runs</th>
              <th className="w-52 py-1.5 font-medium">Ended well</th>
            </tr>
          </thead>
          <tbody>
            {ways.map(w => (
              <tr key={w.name} className="border-t border-border">
                <td className="py-2 text-text">{w.name}</td>
                <td className="py-2 font-mono text-micro text-muted-foreground">{w.from}</td>
                <td className="py-2 pr-6">
                  <span className="grid grid-cols-[1fr_2.5rem] items-center gap-2">
                    <Bar value={w.runs} max={most} />
                    <span className="text-right font-mono text-micro text-text">{fmtNum(w.runs)}</span>
                  </span>
                </td>
                <td className="py-2">
                  {w.well === null ? (
                    <span className="text-micro text-faint">-</span>
                  ) : (
                    <span className="grid grid-cols-[1fr_7.5rem] items-center gap-2">
                      <Bar value={w.well} max={1} color={tone(w.well)} />
                      <span className="whitespace-nowrap font-mono text-micro text-muted-foreground">
                        {Math.round(w.well * 100)}% <span className="font-sans text-faint">{w.wellWord}</span>
                      </span>
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Note>
        Review, Split and Settle each run inside a task, so their tasks are also counted in Tasks resolved. Catch up
        isn&apos;t counted yet.
      </Note>
    </Pane>
  );
}

const FILERS: [string, string, string][] = [
  ["person", "People", "var(--accent)"],
  ["agent", "Agents", "var(--green)"],
  ["engine", "Engines", "var(--yellow)"],
];

function WhoDoesTheWork({ usage }: { usage: UsageKpis }) {
  const total = sum(usage.tasks.filed_by);
  const agents = Object.entries(usage.agents_joined).sort((a, b) => b[1] - a[1]);
  const most = Math.max(1, ...agents.map(([, n]) => n));
  return (
    <div className="grid items-start lg:grid-cols-2">
      <Pane title="Who files the work" question="Tasks filed, by who filed them">
        <div className="px-4 pb-3">
          {total ? (
            <>
              <div className="flex h-5 overflow-hidden rounded" aria-hidden>
                {FILERS.map(([key, , color]) => {
                  const n = usage.tasks.filed_by[key] ?? 0;
                  return n ? <span key={key} style={{ width: `${(n / total) * 100}%`, background: color }} /> : null;
                })}
              </div>
              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-micro text-muted-foreground">
                {FILERS.map(([key, name, color]) => {
                  const n = usage.tasks.filed_by[key] ?? 0;
                  return n ? (
                    <span key={key} className="flex items-center gap-1.5">
                      <Dot color={color} /> {name} {Math.round((n / total) * 100)}%
                    </span>
                  ) : null;
                })}
              </div>
            </>
          ) : (
            <span className="text-micro text-faint">No tasks filed in this window.</span>
          )}
          <div className="mt-3 border-t border-border pt-2">
            <Label>Median time open, by who resolved it</Label>
            <dl className="mt-1 grid grid-cols-[1fr_auto] gap-y-1 text-label">
              {FILERS.filter(([key]) => usage.tasks.median_hours_open_by?.[key] !== undefined).map(([key, name]) => (
                <div key={key} className="contents">
                  <dt className="text-muted-foreground">{name}</dt>
                  <dd className="font-mono text-micro text-text">{fmtHours(usage.tasks.median_hours_open_by[key])}</dd>
                </div>
              ))}
              <dt className="text-muted-foreground">All tasks</dt>
              <dd className="font-mono text-micro text-text">{fmtHours(usage.tasks.median_hours_open)}</dd>
            </dl>
          </div>
        </div>
      </Pane>
      <Pane title="Agents joined" question="By the tool they run in">
        <div className="flex flex-col gap-2 px-4 pb-3">
          {agents.length ? (
            agents.map(([adapter, n]) => (
              <div key={adapter} className="grid grid-cols-[7rem_1fr_2.5rem] items-center gap-2 text-label">
                <span className="truncate text-muted-foreground">{adapter.replace(/_/g, " ")}</span>
                <Bar value={n} max={most} />
                <span className="text-right font-mono text-micro text-text">{fmtNum(n)}</span>
              </div>
            ))
          ) : (
            <span className="text-micro text-faint">No agents joined in this window.</span>
          )}
        </div>
      </Pane>
    </div>
  );
}

export function UsageView({ refreshInterval }: { refreshInterval: number }) {
  const [days, setDays] = useState<(typeof RANGES)[number]>(30);
  const { usage, loading } = useUsage(days, refreshInterval);

  const range = (
    <div role="group" aria-label="Time range" className="flex items-center gap-2">
      {RANGES.map(r => (
        <button
          key={r}
          type="button"
          aria-pressed={days === r}
          onClick={() => setDays(r)}
          className={`tabular transition-colors hover:text-text ${days === r ? "text-text" : ""}`}
        >
          {r} days
        </button>
      ))}
    </div>
  );

  if (!usage) {
    return (
      <Panel title="Usage" meta={range}>
        <Nothing>
          {loading ? "Reading this hub's usage…" : "This hub hasn't reported usage yet. It starts counting when it starts."}
        </Nothing>
      </Panel>
    );
  }

  return (
    <>
      <Panel
        title="Usage"
        meta={
          <>
            {range}
            <span aria-hidden className="mx-1 h-3 w-px bg-border" />
            <Dot color={usage.sharing ? "var(--green)" : "var(--faint)"} />
            {usage.sharing ? "shared" : "kept on this hub"}
          </>
        }
      >
        <Figures cols={6}>
          <Figure label="Tasks filed" value={fmtNum(usage.tasks.filed)} />
          <Figure label="Resolved" value={fmtNum(usage.tasks.resolved)} />
          <Figure
            label="Median time open"
            value={fmtHours(usage.tasks.median_hours_open)}
            hint="From filed to resolved, for tasks resolved in this window"
          />
          <Figure label="Active days" value={`${usage.active_days} of ${usage.days}`} />
          <Figure label="Work finished" value={fmtNum(usage.work_total)} hint="Tasks, flows and negotiations, since the hub first started" />
          <Figure
            label="First finished"
            value={usage.first_value_hours === null ? "-" : fmtHours(usage.first_value_hours)}
            hint="From the hub's first start to its first finished work"
          />
        </Figures>
      </Panel>
      <KeepingUp usage={usage} />
      <WaysOfWorking usage={usage} />
      <WhoDoesTheWork usage={usage} />
      <Note>
        Counts and outcomes only: no names, rooms or what anyone wrote.{" "}
        {usage.sharing
          ? "This hub sends these events to its analytics destination."
          : "They stay on this hub. Sharing is asked at install and on the Mac app's first screen."}
      </Note>
    </>
  );
}
