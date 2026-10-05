// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Machines: the computers that checked in with this hub through
 * `mycelium runner`, what each found installed, what it is running, and what
 * it was last asked to do.
 *
 *   <MachinesScreen />            Add machine: pair one nobody sits at, or add one by id
 *     └─ <MachineCard /> per runner
 *          ├─ frameworks   the scan, with Rescan
 *          ├─ agents       started from the app, each with Stop
 *          ├─ pairings     devices that start agents here without asking
 *          └─ jobs         the recent queue, newest first
 */

import { useState } from "react";
import Link from "next/link";
import { KeyRound, Laptop, Loader2, Plus, Square, SquareTerminal } from "lucide-react";
import { stopRunnerAgent, type Runner, type RunnerAgent, type RunnerPairing } from "@/lib/api";
import { fingerprint, pairingWith, useDeviceKeyId } from "@/lib/device-key";
import { terminalLink, useIsDesktop } from "@/lib/desktop";
import {
  describeJob,
  hostOf,
  JOB_STATUS_LABEL,
  pairingNote,
  sortFrameworks,
  startsInHerdr,
  useRunnerJobs,
  useRunners,
  useRunnersRevalidate,
} from "@/lib/runners";
import { fmtAgo } from "@/lib/metrics-format";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { ConnectMachine, HostMissing, RescanButton } from "@/components/runner-fields";
import { MachineAgents } from "@/components/machine-agents";
import { AddMachineDialog, PAIR_COMMAND } from "@/components/add-machine-dialog";

/** How many of a machine's jobs are listed. */
const RECENT_JOBS = 8;

export function MachinesScreen() {
  const { runners, loading } = useRunners();
  // Inside the Mac app this Mac is always one of them: the app runs its
  // runner, so there is nothing to set up, only a moment to wait for it.
  const desktop = useIsDesktop();
  const keyId = useDeviceKeyId();
  const [adding, setAdding] = useState(false);

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-4xl px-4 py-6 sm:px-6">
        <div className="flex flex-wrap items-start gap-3 px-1">
          <p className="min-w-0 max-w-2xl flex-1 text-micro leading-relaxed text-muted-foreground">
            {desktop ? (
              <>This Mac, and any other computer of yours connected with </>
            ) : (
              <>Your computers connected to this hub with </>
            )}
            <code className="font-mono text-text">mycelium runner</code>. Each starts the agents you ask
            for on that computer, where you can watch and type to them. Only yours are listed.
          </p>
          <Button size="sm" variant="secondary" onClick={() => setAdding(true)}>
            <Plus className="size-3.5" />
            Add machine
          </Button>
        </div>
        <AddMachineDialog open={adding} onClose={() => setAdding(false)} />

        <div className="mt-4 space-y-6">
          {loading && runners.length === 0 && <Skeleton className="h-40 w-full rounded-xl" />}
          {!loading && runners.length === 0 && (desktop ? <ThisMacConnecting /> : <ConnectMachine />)}
          {runners.map((r) => (
            <MachineCard key={r.id} runner={r} keyId={keyId} />
          ))}
        </div>
      </div>
    </div>
  );
}

/** In the Mac app before its runner has checked in: it is on its way, not missing. */
function ThisMacConnecting() {
  return (
    <div className="flex items-center gap-3 px-1 py-2">
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
    <section className="mt-3">
      <div className="mb-0.5 flex h-6 items-center gap-2 px-1">
        <h3 className="text-micro font-medium text-faint">{title}</h3>
        {action && <div className="ml-auto">{action}</div>}
      </div>
      <div className="px-1">{children}</div>
    </section>
  );
}

function MachineCard({ runner, keyId }: { runner: Runner; keyId: string | null }) {
  const frameworks = sortFrameworks(runner.frameworks);
  const { jobs } = useRunnerJobs(runner.id);
  const mine = pairingWith(runner, keyId);

  return (
    <article className="border-t border-border pt-3">
      <header className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1">
        <Laptop className="size-4 text-muted-foreground" />
        <h2 className="text-label font-medium text-text">{runner.label || runner.id}</h2>
        <span
          className={`inline-flex items-center gap-1.5 text-micro ${runner.connected ? "text-green" : "text-muted-foreground"}`}
        >
          <span
            aria-hidden
            className={`size-1.5 rounded-full ${runner.connected ? "bg-green" : "bg-faint"}`}
          />
          {runner.connected ? "Connected" : `Last seen ${fmtAgo(runner.last_seen)}`}
        </span>
        {mine && (
          <span
            className="inline-flex items-center gap-1 rounded bg-hairline px-1.5 text-micro text-text"
            title="What this device asks for starts there without a yes, inside what the pairing allows."
          >
            <KeyRound className="size-3" />
            Paired as &ldquo;{mine.name}&rdquo;
          </span>
        )}
        <span className="ml-auto font-mono text-micro text-faint">
          {runner.platform} · mycelium {runner.version}
          {runner.owner ? ` · @${runner.owner}` : ""}
        </span>
      </header>

      {!runner.herdr && (
        <div className="mt-3">
          <HostMissing runner={runner} />
        </div>
      )}

      <Section title="Folders agents may start in">
        {runner.roots.length === 0 ? (
          <p className="text-label text-muted-foreground">None. Start the runner with --root &lt;folder&gt;.</p>
        ) : (
          <ul className="flex flex-wrap gap-x-4 gap-y-0.5">
            {runner.roots.map((root) => (
              <li key={root} className="font-mono text-micro text-text">
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
                  <tr key={f.id} className={`h-7 ${f.installed ? "" : "opacity-50"}`}>
                    <td className="pr-3 text-text">{f.name}</td>
                    <td className="pr-3 font-mono text-micro text-muted-foreground">
                      {f.installed ? (f.version ?? "installed") : "not installed"}
                    </td>
                    <td className="hidden pr-3 font-mono text-micro text-faint sm:table-cell">
                      {f.path ?? f.command}
                    </td>
                    <td className="text-right text-micro text-muted-foreground">
                      {f.installed && f.launchable ? (runner.herdr ? "Can start" : `Needs ${hostOf(runner).name}`) : (f.note ?? "")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>

      {/* Every agent on the machine when its runner reports them; a runner
          from before that, the ones it started. */}
      {runner.machine ? (
        <Section title="Agents on this machine">
          <MachineAgents runner={runner} />
        </Section>
      ) : (
        <Section title="Agents running here">
          {runner.agents.length === 0 ? (
            <p className="text-label text-muted-foreground">
              None yet. Start one from a room&apos;s Members panel, under Invite.
            </p>
          ) : (
            <ul>
              {runner.agents.map((a) => (
                <AgentLine key={`${a.room}/${a.handle}`} runner={runner} agent={a} />
              ))}
            </ul>
          )}
        </Section>
      )}

      <Section title="Paired devices">
        <Pairings runner={runner} keyId={keyId} />
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
                {!j.error && pairingNote(j) && (
                  <span className="basis-full text-micro text-muted-foreground">{pairingNote(j)}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
    </article>
  );
}

/** The devices that start agents on a machine without asking there, and what each may start. */
function Pairings({ runner, keyId }: { runner: Runner; keyId: string | null }) {
  const pairings = runner.pairings ?? [];
  if (pairings.length === 0) {
    return (
      <p className="text-label text-muted-foreground">
        None. Everything asks for a yes on this machine. For one nobody sits at, run{" "}
        <code className="font-mono text-micro text-text">{PAIR_COMMAND}</code> there, then Add machine → Pair.
      </p>
    );
  }
  return (
    <ul className="space-y-1">
      {pairings.map((p) => (
        <PairingLine key={p.key} pairing={p} mine={p.key === keyId} />
      ))}
      <li className="pt-1 text-micro text-faint">
        Unpair one on the machine: <code className="font-mono">mycelium runner unpair &quot;&lt;name&gt;&quot;</code>
      </li>
    </ul>
  );
}

function PairingLine({ pairing: p, mine }: { pairing: RunnerPairing; mine: boolean }) {
  const covers = [
    p.folders.length ? p.folders.join(", ") : "every folder",
    p.clis.length ? p.clis.join(", ") : "any agent CLI",
    p.swarms ? "teams too" : "no teams",
  ].join(" · ");
  return (
    <li className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-label">
      <span className="text-text">{p.name}</span>
      {mine && <span className="text-micro text-accent">this device</span>}
      <span className="font-mono text-micro text-faint">{fingerprint(p.key)}</span>
      <span className="text-micro text-muted-foreground">{covers}</span>
      {/* A machine lists only the pairings that haven't ended. */}
      <span className="ml-auto text-micro text-faint">
        {p.expires_at === null ? "doesn't end" : `ends ${new Date(p.expires_at).toLocaleDateString()}`}
      </span>
    </li>
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
    <li className="flex min-h-7 flex-wrap items-center gap-x-3 gap-y-1 py-0.5">
      <span className="font-mono text-label text-text">@{agent.handle}</span>
      <Link
        href={`/room/${encodeURIComponent(agent.room)}`}
        className="text-micro text-muted-foreground underline-offset-2 hover:text-text hover:underline"
      >
        {agent.room}
      </Link>
      <span className="text-micro text-faint">{agent.framework}</span>
      <span className={`text-micro ${STATUS_TONE[agent.status]}`}>{agent.status}</span>
      {agent.pane && (
        <span className="font-mono text-micro text-faint">
          {startsInHerdr(runner) ? "pane" : "session"} {agent.pane}
        </span>
      )}
      {agent.cwd && <span className="hidden truncate font-mono text-micro text-faint md:inline">{agent.cwd}</span>}
      <span className="ml-auto flex items-center gap-2">
        {error && <span className="text-micro text-red">{error}</span>}
        {/* The app's agents terminal opens herdr panes; an agent elsewhere is watched there. */}
        {desktop && !gone && agent.pane && startsInHerdr(runner) && (
          <a
            href={terminalLink(agent.pane)}
            className="inline-flex h-6 items-center gap-1.5 rounded px-1.5 text-micro text-muted-foreground hover:bg-hairline hover:text-text"
          >
            <SquareTerminal className="size-3" />
            Open terminal
          </a>
        )}
        {!gone && (
          <Button
            variant="ghost"
            size="xs"
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
