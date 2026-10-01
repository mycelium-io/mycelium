// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Every agent on one machine, and what to do about it: the Machines page's
 * half of `mycelium machine`.
 *
 *   <MachineAgents runner />
 *     ├─ problems     what's wrong, each with the action that fixes it
 *     ├─ workspaces   where agents run together, each with "Kept synced"
 *     │    └─ rows    state, agent CLI, folder, whether herdr brings it back,
 *     │               and Restart/Stop/Rename/Unbind
 *     └─ <RestartDialog />  what restarting does, asked here and then on the machine
 *
 * The report is the runner's (it sends it with every heartbeat), so it shows
 * agents the runner never started too: a pane someone bound to a room by hand.
 * Every action is a job for that runner; nothing here reaches the machine.
 *
 * An agent's own session is herdr's to keep: with herdr's integration for its
 * CLI, herdr brings it back in that session after herdr restarts. Restart here
 * starts a stopped agent again as itself, to catch up from the room.
 */

import { useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import {
  machineAction,
  type MachineAction,
  type MachineAgent,
  type MachineProblem,
  type MachineWorkspace,
  type Runner,
  type RunnerJob,
} from "@/lib/api";
import { JOB_STATUS_LABEL, jobSettled, useRunnerJob, useRunnersRevalidate } from "@/lib/runners";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

/** How each state reads, and the dot it wears. */
const STATE: Record<MachineAgent["state"], { word: string; tone: string }> = {
  working: { word: "Working", tone: "var(--accent)" },
  idle: { word: "Idle", tone: "var(--muted-foreground)" },
  blocked: { word: "Blocked", tone: "var(--yellow)" },
  stopped: { word: "Stopped, pane open", tone: "var(--red)" },
  gone: { word: "Pane gone", tone: "var(--faint)" },
  unknown: { word: "Unknown", tone: "var(--faint)" },
};

const RUNNING = new Set<MachineAgent["state"]>(["working", "idle", "blocked"]);

function tilde(path: string | null): string {
  if (!path) return "unknown";
  return path.replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, "~");
}

/** A job queued from this page, followed until the machine says how it went. */
function useAction(runner: Runner) {
  const revalidate = useRunnersRevalidate();
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { job } = useRunnerJob(runner.id, jobId);
  const run = async (action: MachineAction): Promise<RunnerJob | null> => {
    setBusy(true);
    setError(null);
    try {
      const queued = await machineAction(runner.id, action);
      setJobId(queued.id);
      revalidate();
      return queued;
    } catch (e) {
      setError(e instanceof Error ? e.message : "The machine couldn't be asked");
      return null;
    } finally {
      setBusy(false);
    }
  };
  return { run, job, error, busy };
}

/** How a queued action is going, said in a line (nothing once it's done). */
function JobLine({ job, error }: { job: RunnerJob | null; error: string | null }) {
  if (error) return <span className="text-micro text-red">{error}</span>;
  if (!job || job.status === "done") return null;
  if (job.status === "failed") return <span className="text-micro text-red">{job.error ?? "It failed."}</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-micro text-muted-foreground">
      <Loader2 className="size-3 animate-spin" />
      {JOB_STATUS_LABEL[job.status]}
    </span>
  );
}

export function MachineAgents({ runner }: { runner: Runner }) {
  const report = runner.machine;
  const [restarting, setRestarting] = useState<MachineAgent[] | null>(null);
  if (!report) return null;
  const restartable = report.workspaces.flatMap((w) => w.agents).filter((a) => a.restartable);

  return (
    <div className="space-y-4">
      {report.problems.length > 0 && (
        <Problems
          runner={runner}
          problems={report.problems}
          onRestart={(handles) => setRestarting(restartable.filter((a) => handles.includes(a.handle)))}
        />
      )}
      {report.workspaces.length === 0 ? (
        <p className="text-label text-muted-foreground">
          No agents on this machine yet. Start one from a room&apos;s Members panel, under Invite.
        </p>
      ) : (
        report.workspaces.map((w) => (
          <WorkspaceGroup key={w.id} runner={runner} workspace={w} onRestart={(a) => setRestarting([a])} />
        ))
      )}
      {restarting && (
        <RestartDialog runner={runner} agents={restarting} onClose={() => setRestarting(null)} />
      )}
    </div>
  );
}

function Problems({
  runner,
  problems,
  onRestart,
}: {
  runner: Runner;
  problems: MachineProblem[];
  onRestart: (handles: string[]) => void;
}) {
  return (
    <div className="rounded-md border border-border">
      <div className="border-b border-border px-3 py-1.5 text-micro font-medium text-muted-foreground">
        {problems.length} {problems.length === 1 ? "problem" : "problems"}
      </div>
      <ul>
        {problems.map((p, i) => (
          <ProblemRow key={`${p.kind}-${i}`} runner={runner} problem={p} onRestart={onRestart} />
        ))}
      </ul>
    </div>
  );
}

const PROBLEM_TONE: Record<MachineProblem["kind"], string> = {
  stopped: "var(--red)",
  herdr_down: "var(--red)",
  herdr_update: "var(--red)",
  no_restore: "var(--yellow)",
  unsynced: "var(--yellow)",
  lost: "var(--faint)",
};

function ProblemRow({
  runner,
  problem,
  onRestart,
}: {
  runner: Runner;
  problem: MachineProblem;
  onRestart: (handles: string[]) => void;
}) {
  const action = useAction(runner);
  const off = !runner.connected || action.busy;
  let button: React.ReactNode = null;
  if (problem.kind === "stopped") {
    button = (
      <Button size="xs" onClick={() => onRestart(problem.handles)} disabled={!runner.connected}>
        Restart {problem.handles.length}…
      </Button>
    );
  } else if (problem.kind === "no_restore") {
    // It changes each agent CLI's own settings, so the machine asks first.
    button = (
      <Button size="xs" variant="outline" disabled={off} onClick={() => action.run({ kind: "integrations" })}>
        Install integrations
      </Button>
    );
  } else if (problem.kind === "unsynced" && problem.workspace) {
    const workspace = problem.workspace;
    button = (
      <Button size="xs" variant="outline" disabled={off} onClick={() => action.run({ kind: "sync", workspace, on: true })}>
        Keep it synced
      </Button>
    );
  } else if (problem.kind === "lost") {
    button = (
      <Button size="xs" variant="outline" disabled={off} onClick={() => action.run({ kind: "unbind", gone: true })}>
        Unbind
      </Button>
    );
  }
  return (
    <li className="grid grid-cols-[12px_1fr_auto] items-start gap-3 border-b border-hairline px-3 py-2 last:border-b-0">
      <span aria-hidden className="mt-1.5 size-1.5 rounded-full" style={{ background: PROBLEM_TONE[problem.kind] }} />
      <div className="min-w-0 text-label">
        <p className="text-text">{problem.text}</p>
        {/* The same fix from a terminal, for a machine you're sitting at. */}
        {problem.fix && <p className="mt-0.5 font-mono text-micro text-faint">{problem.fix}</p>}
        <JobLine job={action.job} error={action.error} />
      </div>
      <div className="pt-0.5">{button}</div>
    </li>
  );
}

function SyncSwitch({ runner, workspace }: { runner: Runner; workspace: MachineWorkspace }) {
  const action = useAction(runner);
  const pending = action.job && !jobSettled(action.job) ? action.job : null;
  const on = pending ? Boolean(pending.spec.on) : workspace.runner_keeps;
  const label =
    workspace.synced_by === "terminal"
      ? "Synced by a herdr sync loop"
      : on
        ? workspace.synced_by === "runner" || !runner.connected
          ? "Kept synced by this machine"
          : "Kept synced (runner starting)"
        : "Not synced";
  return (
    <span className="ml-auto flex items-center gap-2 text-micro text-muted-foreground">
      <JobLine job={null} error={action.error} />
      {label}
      <button
        type="button"
        role="switch"
        aria-checked={on}
        aria-label={`Keep ${workspace.label} synced`}
        disabled={!runner.connected || action.busy}
        onClick={() => action.run({ kind: "sync", workspace: workspace.id, on: !on })}
        className={cn(
          "relative h-4 w-7 rounded-full transition-colors disabled:opacity-40",
          on ? "bg-accent" : "bg-border2",
        )}
      >
        <span
          aria-hidden
          className={cn(
            "absolute top-0.5 size-3 rounded-full transition-[left]",
            on ? "left-3.5 bg-bg" : "left-0.5 bg-muted-foreground",
          )}
        />
      </button>
    </span>
  );
}

function WorkspaceGroup({
  runner,
  workspace,
  onRestart,
}: {
  runner: Runner;
  workspace: MachineWorkspace;
  onRestart: (agent: MachineAgent) => void;
}) {
  // A herdr workspace bound to a room can be synced; the gone panes and
  // Omnigent's sessions are kept by the runner or not at all.
  const syncable = workspace.host === "herdr" && Boolean(workspace.room);
  return (
    <section>
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 py-1">
        <span className="text-label font-medium text-text">
          {workspace.host === "herdr" && workspace.room ? `herdr · ${workspace.label}` : workspace.label}
        </span>
        {workspace.room && (
          <span className="font-mono text-micro text-faint">
            {workspace.id} →{" "}
            <Link href={`/room/${encodeURIComponent(workspace.room)}`} className="hover:text-text hover:underline">
              {workspace.room}
            </Link>
          </span>
        )}
        {syncable && <SyncSwitch runner={runner} workspace={workspace} />}
      </div>
      {workspace.agents.length === 0 ? (
        <p className="px-1 text-micro text-muted-foreground">No agents bound here yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-md border border-border">
          <table className="w-full text-left text-label">
            <thead>
              <tr className="border-b border-border bg-surface text-micro text-faint">
                <th className="px-2.5 py-1.5 font-medium">Agent</th>
                <th className="px-2.5 py-1.5 font-medium">State</th>
                <th className="hidden px-2.5 py-1.5 font-medium md:table-cell">Folder</th>
                <th className="px-2.5 py-1.5 font-medium">If herdr restarts</th>
                <th className="px-2.5 py-1.5" />
              </tr>
            </thead>
            <tbody>
              {workspace.agents.map((a) => (
                <AgentRow key={`${a.room}/${a.handle}`} runner={runner} agent={a} onRestart={onRestart} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** What happens to an agent if herdr's server restarts. */
function Restores({ agent }: { agent: MachineAgent }) {
  if (agent.host !== "herdr" || agent.restores === null) return <span className="text-faint">–</span>;
  return agent.restores ? (
    <span className="text-muted-foreground" title="herdr's integration for its agent CLI is installed">
      Comes back
    </span>
  ) : (
    <span className="text-yellow" title="herdr's integration for its agent CLI isn't installed">
      Stops
    </span>
  );
}

function AgentRow({
  runner,
  agent,
  onRestart,
}: {
  runner: Runner;
  agent: MachineAgent;
  onRestart: (agent: MachineAgent) => void;
}) {
  const action = useAction(runner);
  const [renaming, setRenaming] = useState(false);
  const [name, setName] = useState(agent.handle);
  const state = STATE[agent.state];
  const herdr = agent.host === "herdr";
  const running = RUNNING.has(agent.state);
  const off = !runner.connected || action.busy;
  const ref = { handle: agent.handle, room: agent.room };

  return (
    <tr className={cn("border-b border-hairline last:border-b-0 align-top", agent.state === "stopped" && "bg-red/[0.04]")}>
      <td className="px-2.5 py-1.5">
        <span className="font-mono text-text">@{agent.handle}</span>
        <span className="block text-micro text-faint">
          {agent.room}
          {agent.kind ? ` · ${agent.kind}` : ""}
        </span>
      </td>
      <td className="px-2.5 py-1.5">
        <span className="inline-flex items-center gap-1.5 text-micro text-text">
          <span aria-hidden className="size-1.5 rounded-full" style={{ background: state.tone }} />
          {state.word}
        </span>
      </td>
      <td className="hidden px-2.5 py-1.5 font-mono text-micro text-muted-foreground md:table-cell">
        {tilde(agent.folder)}
      </td>
      <td className="px-2.5 py-1.5 text-micro">
        <Restores agent={agent} />
      </td>
      <td className="px-2.5 py-1.5">
        <div className="flex flex-wrap items-center justify-end gap-1.5">
          <JobLine job={action.job} error={action.error} />
          {renaming ? (
            <form
              className="flex items-center gap-1.5"
              onSubmit={(e) => {
                e.preventDefault();
                if (name.trim()) void action.run({ kind: "rename", ...ref, name: name.trim() });
                setRenaming(false);
              }}
            >
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                aria-label={`New name for @${agent.handle} in herdr`}
                className="h-6 w-32 rounded border border-border bg-bg px-1.5 font-mono text-micro text-text outline-none focus:border-accent"
              />
              <Button size="xs" type="submit">
                Save
              </Button>
              <Button size="xs" variant="ghost" type="button" onClick={() => setRenaming(false)}>
                Cancel
              </Button>
            </form>
          ) : (
            <>
              {agent.restartable && (
                <Button size="xs" disabled={off} onClick={() => onRestart(agent)}>
                  Restart
                </Button>
              )}
              {running && herdr && (
                <Button size="xs" variant="outline" disabled={off} onClick={() => action.run({ kind: "stop", ...ref })}>
                  Stop
                </Button>
              )}
              {running && herdr && (
                <Button size="xs" variant="ghost" disabled={off} onClick={() => setRenaming(true)}>
                  Rename
                </Button>
              )}
              {herdr && (
                <Button size="xs" variant="ghost" disabled={off} onClick={() => action.run({ kind: "unbind", ...ref })}>
                  Unbind
                </Button>
              )}
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

/** What restarting does, shown before anything starts. The machine asks once more. */
function RestartDialog({
  runner,
  agents,
  onClose,
}: {
  runner: Runner;
  agents: MachineAgent[];
  onClose: () => void;
}) {
  const action = useAction(runner);
  const [picked, setPicked] = useState(() => new Set(agents.map((a) => `${a.room}/${a.handle}`)));
  const chosen = agents.filter((a) => picked.has(`${a.room}/${a.handle}`));
  const n = chosen.length;
  const done = action.job?.status === "done";

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogTitle>
          Restart {agents.length} {agents.length === 1 ? "agent" : "agents"} on {runner.label || runner.id}?
        </DialogTitle>
        <DialogDescription>
          Each starts again in its own folder, as itself. It won&apos;t remember what it was doing, so it reads its
          notes and catches up from the room.
        </DialogDescription>
        <ul className="space-y-2">
          {agents.map((a) => {
            const key = `${a.room}/${a.handle}`;
            return (
              <li key={key} className="flex gap-2.5 rounded-md border border-border px-3 py-2">
                <input
                  type="checkbox"
                  checked={picked.has(key)}
                  onChange={(e) =>
                    setPicked((prev) => {
                      const next = new Set(prev);
                      if (e.target.checked) next.add(key);
                      else next.delete(key);
                      return next;
                    })
                  }
                  aria-label={`Restart @${a.handle}`}
                  className="mt-1"
                />
                <div className="min-w-0">
                  <p className="text-label">
                    <span className="font-mono text-text">@{a.handle}</span>{" "}
                    <span className="text-muted-foreground">
                      in {a.room} · {a.kind ?? "agent"} in {tilde(a.folder)}
                    </span>
                  </p>
                  <p className="mt-0.5 text-micro text-faint">
                    {a.state === "stopped" ? `In its pane, ${a.ref}` : "In a new pane beside its room's"}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
        <div className="flex items-center gap-2">
          <span className="text-micro text-faint">
            {done
              ? "Started."
              : action.job?.status === "waiting"
                ? `Waiting for a yes on ${runner.label || runner.id}.`
                : "The machine will ask once more before anything starts."}
          </span>
          <JobLine job={action.job?.status === "waiting" ? null : action.job} error={action.error} />
          <span className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              {done ? "Close" : "Cancel"}
            </Button>
            {!done && (
              <Button
                disabled={n === 0 || action.busy || Boolean(action.job && !jobSettled(action.job))}
                onClick={() =>
                  action.run({ kind: "restart", agents: chosen.map((a) => ({ handle: a.handle, room: a.room })) })
                }
              >
                Restart {n}
              </Button>
            )}
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
