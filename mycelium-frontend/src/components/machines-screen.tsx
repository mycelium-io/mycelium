// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Machines: the computers that checked in with this hub through
 * `mycelium runner`, what each found installed, what it is running, and what
 * it was last asked to do.
 *
 *   <MachinesScreen />
 *     └─ <MachineCard /> per runner
 *          ├─ frameworks   the scan, with Rescan
 *          ├─ agents       started from the app, each with Stop
 *          └─ jobs         the recent queue, newest first
 */

import { useState } from "react";
import Link from "next/link";
import { Laptop, Loader2, Square, SquareTerminal } from "lucide-react";
import { stopRunnerAgent, type Runner, type RunnerAgent } from "@/lib/api";
import { terminalLink, useIsDesktop } from "@/lib/desktop";
import {
  describeJob,
  JOB_STATUS_LABEL,
  sortFrameworks,
  useRunnerJobs,
  useRunners,
  useRunnersRevalidate,
} from "@/lib/runners";
import { fmtAgo } from "@/lib/metrics-format";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { AddMachineCode, ConnectMachine, HerdrMissing, RescanButton } from "@/components/runner-fields";

/** How many of a machine's jobs are listed. */
const RECENT_JOBS = 8;

export function MachinesScreen() {
  const { runners, loading } = useRunners();
  // Inside the Mac app this Mac is always one of them: the app runs its
  // runner, so there is nothing to set up, only a moment to wait for it.
  const desktop = useIsDesktop();

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
        <h1 className="text-display font-semibold text-text">Machines</h1>
        <p className="mt-1 max-w-2xl text-label leading-relaxed text-muted-foreground">
          {desktop ? (
            <>This Mac, and any other computer of yours connected with </>
          ) : (
            <>Your computers connected to this hub with </>
          )}
          <code className="font-mono text-accent">mycelium runner</code>. Each one reports the agent
          CLIs it has installed, and starts the agents you ask for in a herdr terminal there, where
          you can watch and type to them. Only yours are listed here.
        </p>

        <div className="mt-6 space-y-4">
          {loading && runners.length === 0 && <Skeleton className="h-40 w-full rounded-xl" />}
          {!loading && runners.length === 0 && (desktop ? <ThisMacConnecting /> : <ConnectMachine />)}
          {runners.map((r) => (
            <MachineCard key={r.id} runner={r} />
          ))}
          {runners.length > 0 && (
            <div className="text-micro text-muted-foreground">
              To add another machine, run <code className="font-mono text-accent">mycelium runner</code> on it.
              <AddMachineCode />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

/** In the Mac app before its runner has checked in: it is on its way, not missing. */
function ThisMacConnecting() {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-surface/40 p-4">
      <Loader2 className="size-4 animate-spin text-muted-foreground" />
      <div>
        <p className="text-label font-medium text-text">This Mac is connecting</p>
        <p className="text-micro text-muted-foreground">
          Mycelium starts this Mac&apos;s runner for you. It appears here in a few seconds. If it
          doesn&apos;t, open Health check in the menu bar.
        </p>
      </div>
    </div>
  );
}

function Section({ title, action, children }: { title: string; action?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="mt-4">
      <div className="mb-1.5 flex items-center gap-2">
        <h3 className="text-micro font-semibold uppercase tracking-wide text-muted-foreground">{title}</h3>
        {action && <div className="ml-auto">{action}</div>}
      </div>
      {children}
    </section>
  );
}

function MachineCard({ runner }: { runner: Runner }) {
  const frameworks = sortFrameworks(runner.frameworks);
  const { jobs } = useRunnerJobs(runner.id);

  return (
    <article className="rounded-xl border border-border bg-surface/40 p-4">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <Laptop className="size-4 text-muted-foreground" />
        <h2 className="text-ui font-semibold text-text">{runner.label || runner.id}</h2>
        <span
          className={`inline-flex items-center gap-1.5 text-micro ${runner.connected ? "text-green" : "text-muted-foreground"}`}
        >
          <span
            aria-hidden
            className={`size-1.5 rounded-full ${runner.connected ? "bg-green" : "bg-faint"}`}
          />
          {runner.connected ? "Connected" : `Last seen ${fmtAgo(runner.last_seen)}`}
        </span>
        <span className="ml-auto font-mono text-micro text-faint">
          {runner.platform} · mycelium {runner.version}
          {runner.owner ? ` · @${runner.owner}` : ""}
        </span>
      </header>

      {!runner.herdr && (
        <div className="mt-3">
          <HerdrMissing runner={runner} />
        </div>
      )}

      <Section title="Folders agents may start in">
        {runner.roots.length === 0 ? (
          <p className="text-label text-muted-foreground">None. Start the runner with --root &lt;folder&gt;.</p>
        ) : (
          <ul className="flex flex-wrap gap-1.5">
            {runner.roots.map((root) => (
              <li key={root} className="rounded border border-border bg-bg px-1.5 py-0.5 font-mono text-micro text-text">
                {root}
              </li>
            ))}
          </ul>
        )}
      </Section>

      <Section title="Agent CLIs" action={<RescanButton runner={runner} />}>
        {frameworks.length === 0 ? (
          <p className="text-label text-muted-foreground">The machine has not reported a scan yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-label">
              <tbody>
                {frameworks.map((f) => (
                  <tr key={f.id} className={`border-t border-border first:border-t-0 ${f.installed ? "" : "opacity-50"}`}>
                    <td className="py-1.5 pr-3 font-medium text-text">{f.name}</td>
                    <td className="py-1.5 pr-3 font-mono text-micro text-muted-foreground">
                      {f.installed ? (f.version ?? "installed") : "not installed"}
                    </td>
                    <td className="hidden py-1.5 pr-3 font-mono text-micro text-faint sm:table-cell">
                      {f.path ?? f.command}
                    </td>
                    <td className="py-1.5 text-right text-micro text-muted-foreground">
                      {f.installed && f.launchable ? (runner.herdr ? "Can start" : "Needs herdr") : (f.note ?? "")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      <Section title="Agents running here">
        {runner.agents.length === 0 ? (
          <p className="text-label text-muted-foreground">
            None yet. Start one from a room&apos;s Members panel, under Invite.
          </p>
        ) : (
          <ul className="divide-y divide-border">
            {runner.agents.map((a) => (
              <AgentLine key={`${a.room}/${a.handle}`} runner={runner} agent={a} />
            ))}
          </ul>
        )}
      </Section>

      <Section title="Recent jobs">
        {jobs.length === 0 ? (
          <p className="text-label text-muted-foreground">Nothing asked of this machine yet.</p>
        ) : (
          <ul className="space-y-1">
            {jobs.slice(0, RECENT_JOBS).map((j) => (
              <li key={j.id} className="flex flex-wrap items-baseline gap-x-2 text-label">
                <span className="text-text">{describeJob(j)}</span>
                <span
                  className={`text-micro ${
                    j.status === "failed" ? "text-red" : j.status === "done" ? "text-green" : "text-muted-foreground"
                  }`}
                >
                  {JOB_STATUS_LABEL[j.status]}
                </span>
                <span className="text-micro text-faint">{fmtAgo(j.created_at)}</span>
                {j.error && <span className="basis-full text-micro text-red">{j.error}</span>}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </article>
  );
}

const STATUS_TONE: Record<RunnerAgent["status"], string> = {
  starting: "text-muted-foreground",
  running: "text-green",
  idle: "text-green",
  working: "text-accent",
  blocked: "text-yellow",
  stopped: "text-faint",
  failed: "text-red",
};

function AgentLine({ runner, agent }: { runner: Runner; agent: RunnerAgent }) {
  const [stopping, setStopping] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const revalidate = useRunnersRevalidate();
  const gone = agent.status === "stopped" || agent.status === "failed";
  const desktop = useIsDesktop();

  const stop = async () => {
    setStopping(true);
    setError(null);
    try {
      await stopRunnerAgent(runner.id, agent.room, agent.handle);
      revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not stop it");
    } finally {
      setStopping(false);
    }
  };

  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
      <span className="font-mono text-label text-text">@{agent.handle}</span>
      <Link
        href={`/room/${encodeURIComponent(agent.room)}`}
        className="text-micro text-muted-foreground underline-offset-2 hover:text-text hover:underline"
      >
        {agent.room}
      </Link>
      <span className="text-micro text-faint">{agent.framework}</span>
      <span className={`text-micro ${STATUS_TONE[agent.status]}`}>{agent.status}</span>
      {agent.pane && <span className="font-mono text-micro text-faint">pane {agent.pane}</span>}
      {agent.cwd && <span className="hidden truncate font-mono text-micro text-faint md:inline">{agent.cwd}</span>}
      <span className="ml-auto flex items-center gap-2">
        {error && <span className="text-micro text-red">{error}</span>}
        {desktop && !gone && agent.pane && (
          <a
            href={terminalLink(agent.pane)}
            className="inline-flex h-7 items-center gap-1.5 rounded-md px-2.5 text-label text-muted-foreground hover:bg-hairline hover:text-text"
          >
            <SquareTerminal className="size-3" />
            Open terminal
          </a>
        )}
        {!gone && (
          <Button
            variant="ghost"
            size="sm"
            onClick={stop}
            disabled={stopping || !runner.connected}
            aria-label={`Stop @${agent.handle}`}
          >
            <Square className="size-3" />
            {stopping ? "Stopping…" : "Stop"}
          </Button>
        )}
      </span>
      {agent.detail && <span className="basis-full text-micro text-muted-foreground">{agent.detail}</span>}
    </li>
  );
}
