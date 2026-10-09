// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Laptop, Server, SquareTerminal } from "lucide-react";
import type { ReactNode } from "react";
import type { Runner } from "@/lib/api";
import { terminalLink, useIsDesktop } from "@/lib/desktop";
import { useRunners } from "@/lib/runners";
import { useHubHealth, type HubHealth } from "@/lib/use-status";
import { useHubLabel } from "@/components/title-bar";
import { Tooltip } from "@/components/ui/tooltip";
import { KbdChord } from "@/components/ui/kbd";

const CELL = "flex items-center gap-1.5 rounded px-1.5 py-0.5 -my-0.5 transition-colors hover:bg-hairline hover:text-text";

interface CellProps {
  tooltip?: ReactNode;
  /** Extra classes on the cell — in practice, the width it drops out at. */
  className?: string;
  /** Keymap action this cell duplicates. Its chord is drawn as a keycap beside
   *  the tooltip label, so the cheap way in teaches the fast one — the rail is
   *  the one place every screen shows, and a cell that a key already reaches
   *  had no way of saying so. Silent when the keymap doesn't bind the action. */
  action?: string;
  children: ReactNode;
}

/** The tooltip body for a cell: its label, plus the key that does the same
 *  thing. A cell with no binding keeps the bare string. */
function cellTooltip(tooltip: ReactNode, action: string | undefined): ReactNode {
  if (!tooltip || !action) return tooltip;
  return (
    <span className="flex items-center gap-1.5">
      {tooltip}
      <KbdChord size="xs" action={action} />
    </span>
  );
}

/** A status-bar cell that navigates somewhere on click (editor footer style).
 *  The bar sits at the bottom of the viewport, so its tooltips open upward. */
export function StatusLink({ href, tooltip, action, className, children }: CellProps & { href: string }) {
  return (
    <Tooltip content={cellTooltip(tooltip, action)} side="top">
      <Link href={href} className={className ? `${CELL} ${className}` : CELL}>
        {children}
      </Link>
    </Tooltip>
  );
}

/** A status-bar cell that fires an action on click. */
export function StatusButton({ onClick, tooltip, action, className, children }: CellProps & { onClick: () => void }) {
  return (
    <Tooltip content={cellTooltip(tooltip, action)} side="top">
      <button type="button" onClick={onClick} className={className ? `${CELL} ${className}` : CELL}>
        {children}
      </button>
    </Tooltip>
  );
}

export type Tone = "ok" | "warn" | "bad" | "off";

export const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--green)",
  warn: "var(--yellow)",
  bad: "var(--red)",
  off: "var(--faint)",
};

export function StatusDot({ tone }: { tone: Tone }) {
  return (
    <span
      aria-hidden
      className="inline-block size-1.5 flex-shrink-0 rounded-full"
      style={{ background: TONE_COLOR[tone] }}
    />
  );
}

/** The quiet word ahead of a cell's value, so a value never stands unnamed. */
function CellLabel({ children }: { children: ReactNode }) {
  return <span className="text-faint">{children}</span>;
}

/** A tooltip laid out as a small card: a heading, then lines under it. */
function TooltipCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex max-w-72 flex-col gap-1 py-0.5 text-left">
      <span className="font-medium text-text">{title}</span>
      {children}
    </div>
  );
}

export interface MachinesSummary {
  /** What the cell says after its label. */
  text: string;
  tone: Tone;
  /** Open problems across connected machines (stopped agents, a stalled sync…). */
  problems: number;
}

/** One line for the machines cell: the machine's name when there is one, a
 *  count when there are several, and whether anything there needs a hand. */
export function machinesSummary(runners: Runner[]): MachinesSummary {
  if (runners.length === 0) return { text: "no machines", tone: "off", problems: 0 };
  const connected = runners.filter(r => r.connected);
  const problems = connected.reduce((n, r) => n + (r.machine?.problems.length ?? 0), 0);
  const text = runners.length === 1 ? runners[0].label || runners[0].id : `${runners.length}`;
  const tone: Tone =
    connected.length === 0 ? "bad" : connected.length < runners.length || problems > 0 ? "warn" : "ok";
  return { text, tone, problems };
}

function machineLine(r: Runner): string {
  if (!r.connected) return "offline";
  const agents = `${r.agents.length} agent${r.agents.length === 1 ? "" : "s"}`;
  const problems = r.machine?.problems.length ?? 0;
  return problems > 0 ? `${agents} · ${problems} to fix` : agents;
}

/** Where agents run: the machines this browser starts them on, by name, with
 *  a dot for whether they are up and a count of what needs fixing there. */
export function MachinesStatusLink() {
  const active = usePathname() === "/machines";
  const { runners, loading } = useRunners();
  const summary = machinesSummary(runners);
  const tooltip = (
    <TooltipCard title="Machines">
      {runners.length === 0 ? (
        <span className="text-muted-foreground">
          {loading ? "Looking…" : "None connected. Add one to start agents on it from here."}
        </span>
      ) : (
        runners.map(r => (
          <span key={r.id} className="flex items-center gap-1.5 text-muted-foreground">
            <StatusDot tone={!r.connected ? "bad" : r.machine?.problems.length ? "warn" : "ok"} />
            <span className="text-text">{r.label || r.id}</span>
            <span>{machineLine(r)}</span>
          </span>
        ))
      )}
      <span className="text-faint">Click to open Machines.</span>
    </TooltipCard>
  );
  return (
    <Tooltip content={tooltip} side="top" align="start">
      <Link
        href="/machines"
        aria-label="Machines"
        aria-current={active ? "page" : undefined}
        className={`${CELL} flex-shrink-0 ${active ? "text-text" : ""}`}
      >
        <Laptop className="size-3.5" />
        {runners.length > 0 && (
          <CellLabel>
            <span className="hidden md:inline">machine{runners.length === 1 ? "" : "s"}</span>
          </CellLabel>
        )}
        {!loading && <span className="max-w-32 truncate">{summary.text}</span>}
        {!loading && runners.length > 0 && <StatusDot tone={summary.tone} />}
        {summary.problems > 0 && (
          <span className="tabular" style={{ color: TONE_COLOR.warn }}>
            {summary.problems} to fix
          </span>
        )}
      </Link>
    </Tooltip>
  );
}

export interface HubSummary {
  tone: Tone;
  /** What the dot means, in a word or two. */
  text: string;
}

/** How the hub reads at a glance. `undefined` health is a probe in flight. */
export function hubSummary(health: HubHealth | null | undefined): HubSummary {
  if (health === undefined) return { tone: "off", text: "checking…" };
  if (health === null) return { tone: "bad", text: "unreachable" };
  if (health.status === "degraded") {
    const issues = health.issues?.length ? `: ${health.issues.join(", ")}` : "";
    return { tone: "warn", text: `degraded${issues}` };
  }
  return { tone: "ok", text: "healthy" };
}

/** The hub this page talks to, beside the machines that run agents for it:
 *  its name and whether it is up. Opens Settings, which says how it is set up. */
export function HubStatus() {
  const { data: health } = useHubHealth();
  const hub = useHubLabel();
  const active = usePathname() === "/settings";
  const summary = hubSummary(health);
  return (
    <Tooltip content={`Hub: ${summary.text}`} side="top" align="start">
      <Link
        href="/settings"
        aria-label="Hub settings"
        aria-current={active ? "page" : undefined}
        className={`${CELL} flex-shrink-0 ${active ? "text-text" : ""}`}
      >
        <Server className="size-3.5" />
        <CellLabel>
          <span className="hidden md:inline">hub</span>
        </CellLabel>
        <span className="max-w-40 truncate">{hub || "hub"}</span>
        <StatusDot tone={summary.tone} />
        {(summary.tone === "bad" || summary.tone === "warn") && (
          <span style={{ color: TONE_COLOR[summary.tone] }}>{health === null ? "unreachable" : "degraded"}</span>
        )}
      </Link>
    </Tooltip>
  );
}

/** The app's agents terminal, where every agent this machine started is a
 *  pane. Only inside the desktop app, which is what answers the link. */
export function TerminalStatusLink() {
  const desktop = useIsDesktop();
  if (!desktop) return null;
  return (
    <Tooltip content="Agents terminal" side="top">
      <a href={terminalLink()} aria-label="Open the agents terminal" className={`${CELL} flex-shrink-0`}>
        <SquareTerminal className="size-3.5" />
        <span className="hidden md:inline">terminal</span>
      </a>
    </Tooltip>
  );
}

/** Metrics lives in the status bar, beside the model cell that already
 *  deep-links into it — telemetry reads as a footer concern (editor-style), not
 *  a peer of the rooms in the navigation rail. */
export function MetricsStatusLink() {
  const pathname = usePathname();
  const active = pathname === "/metrics";
  return (
    <Tooltip content="Metrics" side="top">
      <Link
        href="/metrics"
        aria-current={active ? "page" : undefined}
        className={`${CELL} ${active ? "text-text" : ""}`}
      >
        <BarChart3 className="size-3.5" />
        <span className="hidden xl:inline">metrics</span>
      </Link>
    </Tooltip>
  );
}
