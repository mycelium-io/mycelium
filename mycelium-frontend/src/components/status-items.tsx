// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3, Laptop, Server } from "lucide-react";
import type { ReactNode } from "react";
import type { Runner } from "@/lib/api";
import { useRunners } from "@/lib/runners";
import { useHubHealth, type HubHealth } from "@/lib/use-status";
import { useHubLabel } from "@/components/title-bar";
import { DOCS_URL } from "@/lib/install";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
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

type Tone = "ok" | "warn" | "bad" | "off";

const TONE_COLOR: Record<Tone, string> = {
  ok: "var(--green)",
  warn: "var(--yellow)",
  bad: "var(--red)",
  off: "var(--faint)",
};

function Dot({ tone }: { tone: Tone }) {
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
            <Dot tone={!r.connected ? "bad" : r.machine?.problems.length ? "warn" : "ok"} />
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
        {!loading && runners.length > 0 && <Dot tone={summary.tone} />}
        {summary.problems > 0 && (
          <span className="tabular" style={{ color: TONE_COLOR.warn }}>
            {summary.problems} to fix
          </span>
        )}
      </Link>
    </Tooltip>
  );
}

/** `/health` part statuses that mean the part works. */
const USABLE = new Set(["ok", "unchecked"]);

export interface HubSummary {
  tone: Tone;
  /** One word for the cell when the hub needs attention; null when healthy. */
  problem: string | null;
}

/** How the hub reads at a glance: unreachable, degraded (naming what), its
 *  model unusable, or fine. `undefined` health is a probe still in flight. */
export function hubSummary(health: HubHealth | null | undefined): HubSummary {
  if (health === undefined) return { tone: "off", problem: null };
  if (health === null) return { tone: "bad", problem: "unreachable" };
  if (health.llm?.status && !USABLE.has(health.llm.status)) return { tone: "warn", problem: "LLM not ready" };
  if (health.status === "degraded") return { tone: "warn", problem: "degraded" };
  return { tone: "ok", problem: null };
}

function HubRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-faint">{label}</dt>
      <dd className="min-w-0 text-text">{children}</dd>
    </>
  );
}

/** The hub, as one cell: whether it is up, and the model its engines think
 *  with, which is the hub's configuration rather than anything of this page.
 *  Opens a card with the rest of how the hub is set up. */
export function HubStatus() {
  const { data: health } = useHubHealth();
  const hub = useHubLabel();
  const summary = hubSummary(health);
  const model = health?.llm?.model || null;
  const shortModel = model ? model.slice(model.indexOf("/") + 1) : null;
  const llmUsable = !health?.llm?.status || USABLE.has(health.llm.status);
  const store = health?.storage?.host_path || health?.storage?.path || null;

  return (
    <Popover>
      <Tooltip content="How this hub is set up" side="top">
        <PopoverTrigger
          aria-label="Hub"
          className={`${CELL} flex-shrink-0 ${summary.tone === "bad" ? "text-red" : ""}`}
        >
          <Server className="size-3.5" />
          <span>hub</span>
          <Dot tone={summary.tone} />
          {summary.problem ? (
            <span style={{ color: TONE_COLOR[summary.tone] }}>{summary.problem}</span>
          ) : (
            shortModel && (
              <span className="hidden max-w-48 truncate font-mono text-faint lg:inline">{shortModel}</span>
            )
          )}
        </PopoverTrigger>
      </Tooltip>
      <PopoverContent side="top" align="end" className="w-96 p-0 text-label">
        <div className="flex items-center gap-2 border-b border-border px-3 py-2">
          <Server className="size-3.5 text-muted-foreground" />
          <span className="font-medium">Hub</span>
          {hub && <span className="truncate text-muted-foreground">{hub}</span>}
          <span className="ml-auto flex items-center gap-1.5 text-micro" style={{ color: TONE_COLOR[summary.tone] }}>
            <Dot tone={summary.tone} />
            {health === null
              ? "unreachable"
              : health?.status === "degraded"
                ? `degraded${health.issues?.length ? `: ${health.issues.join(", ")}` : ""}`
                : health
                  ? "healthy"
                  : "checking…"}
          </span>
        </div>
        {health ? (
          <dl className="grid grid-cols-[6.5rem_1fr] gap-x-3 gap-y-1.5 px-3 py-2.5 text-micro">
            <HubRow label="LLM">
              <span className="flex items-center gap-1.5">
                <span className="truncate font-mono">{model ?? "not set"}</span>
                <Link href="/metrics#cognition" className="ml-auto flex-shrink-0 text-accent hover:underline">
                  usage
                </Link>
              </span>
              <span className="block text-muted-foreground">
                What the aligner, personas, workers and the task compiler think with.
              </span>
              {!llmUsable && health.llm?.message && (
                <span className="block" style={{ color: TONE_COLOR.warn }}>
                  {health.llm.message}
                </span>
              )}
            </HubRow>
            {health.embedding?.model && (
              <HubRow label="Search">
                <span className="font-mono">{health.embedding.model}</span>
              </HubRow>
            )}
            {health.coordination?.channels_live != null && (
              <HubRow label="Channels">{health.coordination.channels_live} live</HubRow>
            )}
            {health.identity?.mode && <HubRow label="Identity">{health.identity.mode}</HubRow>}
            {health.auth && <HubRow label="API auth">{health.auth.enabled ? "on" : "off"}</HubRow>}
            {health.version && <HubRow label="Version">{health.version}</HubRow>}
            {store && (
              <HubRow label="Store">
                <span className="block truncate font-mono" title={store}>
                  {store}
                </span>
              </HubRow>
            )}
          </dl>
        ) : (
          <p className="px-3 py-2.5 text-micro text-muted-foreground">
            {health === null ? "The hub is not answering. Start it with `mycelium up`." : "Checking the hub…"}
          </p>
        )}
        <div className="border-t border-border px-3 py-2 text-micro text-muted-foreground">
          Set on the hub&apos;s machine:{" "}
          <span className="font-mono text-text">mycelium config set llm.model provider/model</span>, then{" "}
          <span className="font-mono text-text">mycelium config apply</span>.{" "}
          <a
            href={`${DOCS_URL}/reference.html#config-llm`}
            target="_blank"
            rel="noreferrer"
            className="text-accent hover:underline"
          >
            Every setting
          </a>
        </div>
      </PopoverContent>
    </Popover>
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
