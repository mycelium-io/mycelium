// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Every agent on one machine, and what's wrong: the Machines page's half of
 * `mycelium machine`.
 *
 *   <MachineAgents runner />
 *     ├─ problems     what's wrong, each with the command that fixes it
 *     ├─ workspaces   where agents run, the room each is bound to, and each
 *     │               agent's state and what a herdr restart does to it
 *     └─ <RestartDialog />  restart stopped agents; the machine asks once more
 *
 * The report is the runner's, sent with every heartbeat, so it shows agents
 * the runner never started too. Restart is the one thing this page does: a
 * job for the runner. Every other fix is shown as the command to run there.
 */

import { useState } from "react";
import Link from "next/link";
import { Loader2 } from "lucide-react";
import { restartMachineAgents, type MachineAgent, type MachineProblem, type Runner } from "@/lib/api";
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

const PROBLEM_TONE: Record<MachineProblem["kind"], string> = {
  stopped: "var(--red)",
  runner_down: "var(--red)",
  wakes_stalled: "var(--red)",
  herdr_down: "var(--red)",
  herdr_update: "var(--red)",
  no_restore: "var(--yellow)",
  lost: "var(--faint)",
};

function tilde(path: string | null): string {
  if (!path) return "unknown";
  return path.replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, "~");
}

export function MachineAgents({ runner }: { runner: Runner }) {
  const report = runner.machine;
  const [restarting, setRestarting] = useState<MachineAgent[] | null>(null);
  if (!report) return null;
  const agents = report.workspaces.flatMap((w) => w.agents);
  const restart = (handles: string[]) =>
    setRestarting(agents.filter((a) => a.restartable && handles.includes(a.handle)));

  return (
    <div className="space-y-4">
      {report.problems.length > 0 && (
        <div className="rounded-md border border-border">
          <div className="border-b border-border px-3 py-1.5 text-micro font-medium text-muted-foreground">
            {report.problems.length} to fix
          </div>
          <ul>
            {report.problems.map((p) => (
              <li
                key={p.kind}
                className="grid grid-cols-[12px_1fr_auto] items-start gap-3 border-b border-hairline px-3 py-2 last:border-b-0"
              >
                <span aria-hidden className="mt-1.5 size-1.5 rounded-full" style={{ background: PROBLEM_TONE[p.kind] }} />
                <div className="min-w-0 text-label">
                  <p className="text-text">{p.text}</p>
                  {/* The fix, to run on the machine. */}
                  {p.fix && <p className="mt-0.5 font-mono text-micro text-faint">{p.fix}</p>}
                </div>
                <div className="pt-0.5">
                  {p.kind === "stopped" && (
                    <Button size="xs" onClick={() => restart(p.handles)} disabled={!runner.connected}>
                      Restart {p.handles.length}…
                    </Button>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
      {report.workspaces.length === 0 ? (
        <p className="text-label text-muted-foreground">
          No agents on this machine yet. Start one from a room&apos;s Members panel, under Invite.
        </p>
      ) : (
        report.workspaces.map((w) => (
          <section key={w.id}>
            <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1 py-1">
              <span className="text-label font-medium text-text">{w.label}</span>
              {w.room && (
                <span className="font-mono text-micro text-faint">
                  {w.id} →{" "}
                  <Link href={`/room/${encodeURIComponent(w.room)}`} className="hover:text-text hover:underline">
                    {w.room}
                  </Link>
                </span>
              )}
            </div>
            {w.agents.length === 0 ? (
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
                    {w.agents.map((a) => (
                      <tr
                        key={`${a.room}/${a.handle}`}
                        className={cn(
                          "border-b border-hairline align-top last:border-b-0",
                          a.state === "stopped" && "bg-red/[0.04]",
                        )}
                      >
                        <td className="px-2.5 py-1.5">
                          <span className="font-mono text-text">@{a.handle}</span>
                          <span className="block text-micro text-faint">
                            {a.room}
                            {a.kind ? ` · ${a.kind}` : ""}
                          </span>
                        </td>
                        <td className="px-2.5 py-1.5">
                          <span className="inline-flex items-center gap-1.5 text-micro text-text">
                            <span aria-hidden className="size-1.5 rounded-full" style={{ background: STATE[a.state].tone }} />
                            {STATE[a.state].word}
                          </span>
                        </td>
                        <td className="hidden px-2.5 py-1.5 font-mono text-micro text-muted-foreground md:table-cell">
                          {tilde(a.folder)}
                        </td>
                        <td className="px-2.5 py-1.5 text-micro">
                          {a.restores === null ? (
                            <span className="text-faint">–</span>
                          ) : a.restores ? (
                            <span className="text-muted-foreground">Comes back</span>
                          ) : (
                            <span className="text-yellow" title="herdr's integration for its agent CLI isn't installed">
                              Stops
                            </span>
                          )}
                        </td>
                        <td className="px-2.5 py-1.5 text-right">
                          {a.restartable && (
                            <Button size="xs" disabled={!runner.connected} onClick={() => setRestarting([a])}>
                              Restart
                            </Button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ))
      )}
      {restarting && <RestartDialog runner={runner} agents={restarting} onClose={() => setRestarting(null)} />}
    </div>
  );
}

/** What restarting does, said before anything starts. The machine asks once more. */
function RestartDialog({ runner, agents, onClose }: { runner: Runner; agents: MachineAgent[]; onClose: () => void }) {
  const revalidate = useRunnersRevalidate();
  const [picked, setPicked] = useState(() => new Set(agents.map((a) => `${a.room}/${a.handle}`)));
  const [jobId, setJobId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const { job } = useRunnerJob(runner.id, jobId);
  const chosen = agents.filter((a) => picked.has(`${a.room}/${a.handle}`));
  const name = runner.label || runner.id;

  const run = async () => {
    setBusy(true);
    setError(null);
    try {
      const queued = await restartMachineAgents(
        runner.id,
        chosen.map((a) => ({ handle: a.handle, room: a.room })),
      );
      setJobId(queued.id);
      revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "The machine couldn't be asked");
    } finally {
      setBusy(false);
    }
  };

  const said =
    job?.status === "done"
      ? "Started."
      : job?.status === "failed"
        ? (job.error ?? "It failed.")
        : job?.status === "waiting"
          ? `Waiting for a yes on ${name}.`
          : job
            ? JOB_STATUS_LABEL[job.status]
            : "The machine will ask once more before anything starts.";

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogTitle>
          Restart {agents.length} {agents.length === 1 ? "agent" : "agents"} on {name}?
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
                <div className="min-w-0 text-label">
                  <span className="font-mono text-text">@{a.handle}</span>{" "}
                  <span className="text-muted-foreground">
                    in {a.room} · {a.kind} in {tilde(a.folder)}
                  </span>
                  <p className="mt-0.5 text-micro text-faint">
                    {a.state === "stopped" ? `In its pane, ${a.pane}` : "In a new pane beside its room's"}
                  </p>
                </div>
              </li>
            );
          })}
        </ul>
        <div className="flex items-center gap-2">
          <span className={cn("text-micro", job?.status === "failed" || error ? "text-red" : "text-faint")}>
            {error ?? said}
          </span>
          {job && !jobSettled(job) && job.status !== "waiting" && (
            <Loader2 className="size-3 animate-spin text-muted-foreground" />
          )}
          <span className="ml-auto flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              {job?.status === "done" ? "Close" : "Cancel"}
            </Button>
            {job?.status !== "done" && (
              <Button disabled={chosen.length === 0 || busy || Boolean(job && !jobSettled(job))} onClick={run}>
                Restart {chosen.length}
              </Button>
            )}
          </span>
        </div>
      </DialogContent>
    </Dialog>
  );
}
