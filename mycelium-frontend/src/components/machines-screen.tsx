// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Machines: the computers connected to this hub through `mycelium runner`.
 *
 * People come here for two reasons. Something on a machine needs them, or they
 * want to see and manage the agents running on one. So the page leads with
 * what needs you, across every machine, each with the one thing that fixes it.
 * Then one machine at a time: its agents first, and its setup, paired devices
 * and recent activity each behind a tab of their own.
 *
 *   <MachinesScreen />
 *     ├─ <NeedsYou />          every machine's problems, each with its fix
 *     ├─ machine tabs          one per machine, with its status and agent count
 *     └─ <MachinePanel />      Agents · Setup · Paired devices · Activity
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Check,
  Copy,
  KeyRound,
  Laptop,
  Plus,
  RotateCcw,
  Server,
  SquareTerminal,
} from "lucide-react";
import type { MachineAgent, MachineProblem, Runner, RunnerPairing } from "@/lib/api";
import { fingerprint, pairingWith, useDeviceKeyId } from "@/lib/device-key";
import { useThisMachine } from "@/lib/desktop";
import { copyText } from "@/lib/clipboard";
import { describeJob, JOB_STATUS_LABEL, pairingNote, useRunnerJobs, useRunners } from "@/lib/runners";
import { fmtAgo } from "@/lib/metrics-format";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Monogram } from "@/components/ui/monogram";
import { EmptyNote } from "@/components/empty-state";
import { ConnectMachine } from "@/components/runner-fields";
import { RestartDialog } from "@/components/machine-agents";
import { AgentScreenWindow } from "@/components/agent-screen-window";
import { AddMachineDialog, PAIR_COMMAND } from "@/components/add-machine-dialog";
import { cn } from "@/lib/utils";

const RECENT_JOBS = 8;

type Tab = "agents" | "setup" | "paired" | "activity";
const TABS: { id: Tab; label: string }[] = [
  { id: "agents", label: "Agents" },
  { id: "setup", label: "Setup" },
  { id: "paired", label: "Paired devices" },
  { id: "activity", label: "Activity" },
];

function machineName(r: Runner): string {
  return r.label || r.id;
}

function tilde(path: string | null): string {
  if (!path) return "";
  return path.replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, "~");
}

function handles(list: string[]): string {
  const names = list.map((h) => `@${h}`);
  return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : (names[0] ?? "");
}

export function MachinesScreen() {
  const { runners, loading } = useRunners();
  const here = useThisMachine();
  const keyId = useDeviceKeyId();
  const [adding, setAdding] = useState(false);
  // This computer first, then the rest by name.
  const machines = useMemo(
    () =>
      [...runners].sort(
        (a, b) => Number(b.id === here) - Number(a.id === here) || machineName(a).localeCompare(machineName(b)),
      ),
    [runners, here],
  );
  const [picked, setPicked] = useState<string | null>(null);
  const current = machines.find((r) => r.id === picked) ?? machines[0];

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
        <AddMachineDialog open={adding} onClose={() => setAdding(false)} />

        {loading && runners.length === 0 && <Skeleton className="mt-6 h-40 w-full rounded-xl" />}
        {!loading && runners.length === 0 && (
          <div className="mt-6">
            <ConnectMachine />
          </div>
        )}

        {machines.length > 0 && <NeedsYou machines={machines} onShow={setPicked} />}

        {current && (
          <>
            <div role="tablist" aria-label="Machines" className="mt-8 flex flex-wrap gap-2 first:mt-0">
              {machines.map((r) => (
                <MachineTab
                  key={r.id}
                  runner={r}
                  here={r.id === here}
                  active={r.id === current.id}
                  onClick={() => setPicked(r.id)}
                />
              ))}
              {/* Another machine joins the row the machines are in. */}
              <button
                type="button"
                onClick={() => setAdding(true)}
                className="flex items-center gap-2 rounded-lg border border-dashed border-border px-3 py-2 text-label text-muted-foreground transition-colors hover:border-border2 hover:text-text"
              >
                <Plus className="size-4" aria-hidden />
                Add machine
              </button>
            </div>
            <MachinePanel key={current.id} runner={current} here={current.id === here} keyId={keyId} />
          </>
        )}
      </div>
    </div>
  );
}

// ── What needs you ───────────────────────────────────────────────────────────

/** A problem in a few words, for its card's title. The hub's own sentence
 *  says the rest, under it. */
function problemTitle(p: MachineProblem, r: Runner): string {
  const report = r.machine;
  switch (p.kind) {
    case "stopped":
      return `${handles(p.handles)} stopped`;
    case "lost":
      return p.handles.length === 1 ? `${handles(p.handles)}'s pane is gone` : `${handles(p.handles)} lost their panes`;
    case "no_restore":
      return `${handles(p.handles)} won't come back if herdr restarts`;
    case "herdr_update":
      return report?.herdr_minimum ? `herdr needs ${report.herdr_minimum} or newer` : "herdr needs an update";
    case "herdr_down":
      return "herdr isn't running";
    case "runner_down":
      return "The runner isn't running";
    case "wakes_stalled":
      return "Wakes aren't reaching agents";
    case "binding_failing":
      return "A workspace can't sync with its room";
  }
}

/** One plain sentence on what happens, in place of the hub's longer one. */
function problemDetail(p: MachineProblem, r: Runner): string {
  const report = r.machine;
  switch (p.kind) {
    case "stopped":
      return "Their panes are open with nothing running. Restarting picks up where the room left off.";
    case "lost":
      return "There's nothing left to restart. Unbinding forgets the pane and keeps the agent in the room.";
    case "no_restore":
      return `herdr's integration for ${report?.missing_integrations.join(" and ") ?? "their agent CLI"} isn't installed.`;
    case "herdr_update":
      return report?.herdr_server ? `This machine's herdr server is ${report.herdr_server}.` : p.text;
    default:
      return p.text;
  }
}

const SERIOUS = new Set<MachineProblem["kind"]>([
  "stopped",
  "runner_down",
  "herdr_down",
  "wakes_stalled",
  "binding_failing",
  "herdr_update",
]);

function NeedsYou({ machines, onShow }: { machines: Runner[]; onShow: (id: string) => void }) {
  const items = machines.flatMap((r) => (r.machine?.problems ?? []).map((p) => ({ runner: r, problem: p })));
  const [restarting, setRestarting] = useState<{ runner: Runner; agents: MachineAgent[] } | null>(null);
  // Nothing needs you: no section at all.
  if (items.length === 0) return null;
  // Stopped agents and broken setup first, then what only matters later.
  items.sort((a, b) => Number(SERIOUS.has(b.problem.kind)) - Number(SERIOUS.has(a.problem.kind)));
  const several = machines.length > 1;
  return (
    <section>
      <h2 className="mb-2 text-label font-medium text-text">Needs you</h2>
      <ul className="space-y-2">
        {items.map(({ runner, problem }) => {
          const agents = (runner.machine?.workspaces ?? []).flatMap((w) => w.agents);
          return (
            <li
              key={`${runner.id}/${problem.kind}`}
              className="flex items-start gap-3 rounded-lg border border-border bg-surface px-4 py-3"
            >
              {problem.handles.length > 0 ? (
                // A problem about agents shows who, by face, overlapping.
                <span className="flex w-14 flex-shrink-0 -space-x-1.5 pt-0.5" aria-hidden>
                  {problem.handles.slice(0, 3).map((h) => (
                    <Monogram key={h} handle={h} kind="agent" className="size-6 text-[10px] ring-2 ring-surface" />
                  ))}
                </span>
              ) : (
                <AlertTriangle
                  className={cn(
                    "mt-1 mr-10 ml-1 size-4 flex-shrink-0",
                    SERIOUS.has(problem.kind) ? "text-red" : "text-yellow",
                  )}
                  aria-hidden
                />
              )}
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <p className="text-label font-medium text-text">{problemTitle(problem, runner)}</p>
                  {several && (
                    <button
                      type="button"
                      onClick={() => onShow(runner.id)}
                      className="text-micro text-faint hover:text-text hover:underline"
                    >
                      {machineName(runner)}
                    </button>
                  )}
                </div>
                <p className="mt-0.5 text-label text-muted-foreground">{problemDetail(problem, runner)}</p>
                {/* Restart is a job the app can send. Any other fix is a
                    command to run on that machine. */}
                {problem.kind !== "stopped" && problem.fix && <Command text={problem.fix} />}
              </div>
              {problem.kind === "stopped" && (
                <Button
                  size="sm"
                  disabled={!runner.connected}
                  onClick={() =>
                    setRestarting({
                      runner,
                      agents: agents.filter((a) => a.restartable && problem.handles.includes(a.handle)),
                    })
                  }
                >
                  <RotateCcw className="size-3.5" />
                  Restart
                </Button>
              )}
            </li>
          );
        })}
      </ul>
      {restarting && (
        <RestartDialog runner={restarting.runner} agents={restarting.agents} onClose={() => setRestarting(null)} />
      )}
    </section>
  );
}

/** A command to run on the machine, with a button that copies it. */
function Command({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="mt-2 inline-flex max-w-full items-center gap-1 rounded-md border border-border bg-bg py-0.5 pr-0.5 pl-2.5">
      <code className="truncate font-mono text-micro text-text">{text}</code>
      <button
        type="button"
        aria-label={copied ? "Copied" : "Copy the command"}
        onClick={() =>
          void copyText(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 1500);
          })
        }
        className="flex size-6 flex-shrink-0 items-center justify-center rounded text-faint hover:bg-hairline hover:text-text"
      >
        {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
      </button>
    </div>
  );
}

// ── One machine ──────────────────────────────────────────────────────────────

function MachineTab({
  runner,
  here,
  active,
  onClick,
}: {
  runner: Runner;
  here: boolean;
  active: boolean;
  onClick: () => void;
}) {
  const Icon = runner.platform.startsWith("darwin") ? Laptop : Server;
  const live = (runner.machine?.workspaces ?? []).flatMap((w) => w.agents).filter((a) => a.state !== "gone");
  const count = runner.machine ? live.length : runner.agents.length;
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={cn(
        "flex min-w-44 items-center gap-2.5 rounded-lg border px-3 py-2 text-left transition-colors",
        active ? "border-accent/60 bg-accent/10" : "border-border hover:border-border2 hover:bg-hairline",
      )}
    >
      <Icon className="size-4 flex-shrink-0 text-muted-foreground" aria-hidden />
      <span className="min-w-0 flex-1 leading-tight">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-label font-medium text-text">{machineName(runner)}</span>
          <span
            aria-label={runner.connected ? "Connected" : "Offline"}
            className={cn("size-1.5 flex-shrink-0 rounded-full", runner.connected ? "bg-green" : "bg-faint")}
          />
        </span>
        <span className="block text-micro text-faint">
          {here ? "This computer" : runner.connected ? `${count} ${count === 1 ? "agent" : "agents"}` : `Seen ${fmtAgo(runner.last_seen)}`}
        </span>
      </span>
    </button>
  );
}

function MachinePanel({ runner, here, keyId }: { runner: Runner; here: boolean; keyId: string | null }) {
  const [tab, setTab] = useState<Tab>("agents");
  const pairings = runner.pairings?.length ?? 0;
  return (
    <section className="mt-4 rounded-lg border border-border">
      <div role="tablist" aria-label={machineName(runner)} className="flex gap-1 border-b border-border px-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "-mb-px border-b-2 px-2.5 py-2 text-label transition-colors",
              tab === t.id ? "border-accent text-text" : "border-transparent text-muted-foreground hover:text-text",
            )}
          >
            {t.label}
            {t.id === "paired" && pairings > 0 && <span className="ml-1.5 text-faint">{pairings}</span>}
          </button>
        ))}
      </div>
      <div className="p-4">
        {tab === "agents" && <Agents runner={runner} here={here} />}
        {tab === "setup" && <Setup runner={runner} />}
        {tab === "paired" && <Paired runner={runner} keyId={keyId} />}
        {tab === "activity" && <Activity runner={runner} />}
      </div>
    </section>
  );
}

const STATE: Record<MachineAgent["state"], { word: string; tone: string }> = {
  working: { word: "Working", tone: "bg-accent" },
  idle: { word: "Idle", tone: "bg-muted-foreground" },
  blocked: { word: "Waiting for input", tone: "bg-yellow" },
  stopped: { word: "Stopped", tone: "bg-red" },
  gone: { word: "Pane gone", tone: "bg-faint" },
  unknown: { word: "Unknown", tone: "bg-faint" },
};

/** Stopped first, since it's what you'd act on, then waiting, working and idle. */
const ORDER: MachineAgent["state"][] = ["stopped", "blocked", "working", "idle", "unknown", "gone"];

function Agents({ runner, here }: { runner: Runner; here: boolean }) {
  const [viewing, setViewing] = useState<MachineAgent | null>(null);
  const [restarting, setRestarting] = useState<MachineAgent[] | null>(null);
  const report = runner.machine;
  const all = (report?.workspaces ?? []).flatMap((w) => w.agents);
  const live = all
    .filter((a) => a.state !== "gone")
    .sort((a, b) => ORDER.indexOf(a.state) - ORDER.indexOf(b.state) || a.handle.localeCompare(b.handle));
  const loose = report?.unenrolled ?? [];
  if (live.length === 0 && loose.length === 0) {
    return <EmptyNote>No agents here yet. Add one from a room&apos;s Members panel.</EmptyNote>;
  }
  return (
    <>
      {live.length > 0 && (
        <table className="w-full text-left text-label">
          <thead>
            <tr className="text-micro text-faint">
              <th className="pb-2 font-normal">Agent</th>
              <th className="pb-2 font-normal">Room</th>
              <th className="pb-2 font-normal">State</th>
              <th className="hidden pb-2 font-normal md:table-cell">Folder</th>
              <th className="pb-2" />
            </tr>
          </thead>
          <tbody>
            {live.map((a) => (
              <tr key={`${a.room}/${a.handle}`} className="h-10 border-t border-hairline">
                <td className="pr-3">
                  <span className="flex items-center gap-2.5">
                    {/* Each agent wears the face it wears in its room. */}
                    <Monogram handle={a.handle} kind="agent" className="size-6 text-[10px]" />
                    <span className="font-mono text-text">@{a.handle}</span>
                    {a.kind && <span className="text-micro text-faint">{a.kind}</span>}
                  </span>
                </td>
                <td className="pr-3">
                  <Link
                    href={`/room/${encodeURIComponent(a.room)}`}
                    className="text-muted-foreground hover:text-text hover:underline"
                  >
                    {a.room}
                  </Link>
                </td>
                <td className="pr-3">
                  <span className="inline-flex items-center gap-1.5 text-text">
                    <span aria-hidden className={cn("size-1.5 rounded-full", STATE[a.state].tone)} />
                    {STATE[a.state].word}
                  </span>
                </td>
                <td className="hidden pr-3 font-mono text-micro text-muted-foreground md:table-cell">{tilde(a.folder)}</td>
                <td className="text-right whitespace-nowrap">
                  {here && a.state !== "stopped" && (
                    <Button size="xs" variant="ghost" onClick={() => setViewing(a)}>
                      <SquareTerminal className="size-3" />
                      Terminal
                    </Button>
                  )}
                  {a.restartable && (
                    <Button size="xs" variant="secondary" disabled={!runner.connected} onClick={() => setRestarting([a])}>
                      Restart
                    </Button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {loose.length > 0 && (
        <div className="mt-5">
          <h3 className="mb-1 text-micro text-faint">Not in a room yet</h3>
          <ul>
            {loose.map((u) => (
              <li key={u.pane} className="flex h-9 items-center gap-3 border-t border-hairline text-label">
                <span className="text-text">{u.tab_label ?? u.pane}</span>
                {u.kind && <span className="text-micro text-faint">{u.kind}</span>}
                <span className="font-mono text-micro text-muted-foreground">{tilde(u.folder)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {restarting && <RestartDialog runner={runner} agents={restarting} onClose={() => setRestarting(null)} />}
      {viewing && (
        <AgentScreenWindow
          key={`${viewing.room}/${viewing.handle}`}
          onClose={() => setViewing(null)}
          room={viewing.room}
          handle={viewing.handle}
        />
      )}
    </>
  );
}

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[10rem_1fr] items-baseline gap-3 border-t border-hairline py-2 first:border-t-0">
      <dt className="text-label text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-label text-text">{children}</dd>
    </div>
  );
}

function Setup({ runner }: { runner: Runner }) {
  const report = runner.machine;
  return (
    <dl>
      <Fact label="Folders">
        {runner.roots.length === 0 ? (
          <span className="text-muted-foreground">None</span>
        ) : (
          <ul className="space-y-0.5">
            {runner.roots.map((root) => (
              <li key={root} className="font-mono text-micro">
                {tilde(root)}
              </li>
            ))}
          </ul>
        )}
      </Fact>
      <Fact label="herdr">
        <span className="font-mono text-micro">{report?.herdr_server ?? (runner.herdr ? "running" : "not running")}</span>
      </Fact>
      <Fact label="Mycelium">
        <span className="font-mono text-micro">{runner.version}</span>
      </Fact>
      <Fact label="System">
        <span className="font-mono text-micro">{runner.platform}</span>
      </Fact>
      <Fact label="Connected since">{fmtAgo(runner.started_at)}</Fact>
    </dl>
  );
}

function Paired({ runner, keyId }: { runner: Runner; keyId: string | null }) {
  const pairings = runner.pairings ?? [];
  const mine = pairingWith(runner, keyId);
  if (pairings.length === 0) {
    return (
      <div>
        <p className="text-label text-muted-foreground">Every request needs a yes on this machine.</p>
        <p className="mt-2 text-label text-muted-foreground">To pair another computer, run this there.</p>
        <Command text={PAIR_COMMAND} />
      </div>
    );
  }
  return (
    <ul>
      {pairings.map((p) => (
        <PairingRow key={p.key} pairing={p} mine={mine?.key === p.key} />
      ))}
    </ul>
  );
}

function PairingRow({ pairing: p, mine }: { pairing: RunnerPairing; mine: boolean }) {
  return (
    <li className="flex items-start gap-3 border-t border-hairline py-2.5 first:border-t-0">
      <KeyRound className="mt-0.5 size-4 text-faint" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-label text-text">
          {p.name}
          {mine && <span className="ml-2 text-micro text-accent">This computer</span>}
        </p>
        <p className="mt-0.5 text-micro text-muted-foreground">
          {p.folders.length ? p.folders.map(tilde).join(" and ") : "Any folder"}
        </p>
        <p className="text-micro text-muted-foreground">{p.clis.length ? p.clis.join(" and ") : "Any agent CLI"}</p>
      </div>
      <div className="text-right">
        <p className="font-mono text-micro text-faint">{fingerprint(p.key)}</p>
        <p className="text-micro text-faint">
          {p.expires_at === null ? "No expiry" : `Until ${new Date(p.expires_at).toLocaleDateString()}`}
        </p>
      </div>
    </li>
  );
}

function Activity({ runner }: { runner: Runner }) {
  const { jobs } = useRunnerJobs(runner.id);
  if (jobs.length === 0) return <EmptyNote>Nothing asked of this machine yet.</EmptyNote>;
  return (
    <ul>
      {jobs.slice(0, RECENT_JOBS).map((j) => (
        <li key={j.id} className="border-t border-hairline py-2 first:border-t-0">
          <div className="flex items-baseline gap-3 text-label">
            <span className="text-text">{describeJob(j)}</span>
            <span
              className={cn(
                "text-micro",
                j.status === "failed" ? "text-red" : j.status === "done" ? "text-green" : "text-muted-foreground",
              )}
            >
              {JOB_STATUS_LABEL[j.status]}
            </span>
            <span className="ml-auto text-micro text-faint">{fmtAgo(j.created_at)}</span>
          </div>
          {j.error && <p className="mt-0.5 text-micro text-red">{j.error}</p>}
          {!j.error && pairingNote(j) && <p className="mt-0.5 text-micro text-muted-foreground">{pairingNote(j)}</p>}
        </li>
      ))}
    </ul>
  );
}
