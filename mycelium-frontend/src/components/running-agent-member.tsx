// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Laptop } from "lucide-react";
import { adoptRunnerAgent, type MachineUnenrolled, type Runner } from "@/lib/api";
import { runnerName, useRunnerJob, useRunners, useRunnersRevalidate } from "@/lib/runners";
import { useRoomRevalidate } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import { ConnectMachine } from "@/components/runner-fields";
import { IdentityRow, MemberFooter, handleValid, normHandle, tildePath } from "@/components/launch-agent-dialog";
import { cn } from "@/lib/utils";

/** One agent a person could bring in, and the machine it runs on. */
export interface RunningAgent {
  runner: Runner;
  agent: MachineUnenrolled;
}

/** Every pane a machine already knows as a member of some room. */
function enrolledPanes(runner: Runner): Set<string> {
  const panes = new Set<string>();
  for (const a of runner.agents) if (a.pane) panes.add(a.pane);
  for (const w of runner.machine?.workspaces ?? []) for (const a of w.agents) panes.add(a.pane);
  return panes;
}

/**
 * The agents running on your machines that no room has yet. A machine's
 * report can be a heartbeat behind, so a pane its runner already tracks
 * (one just brought in, say) is left out too.
 */
export function runningAgents(runners: Runner[]): RunningAgent[] {
  return runners.flatMap((runner) => {
    const taken = enrolledPanes(runner);
    return (runner.machine?.unenrolled ?? [])
      .filter((agent) => !taken.has(agent.pane))
      .map((agent) => ({ runner, agent }));
  });
}

function cliName(runner: Runner, kind: string | null): string {
  if (!kind) return "An agent";
  return runner.frameworks.find((f) => f.id === kind)?.name ?? kind;
}

const STATE_LABEL: Record<MachineUnenrolled["state"], string> = {
  working: "working",
  idle: "idle",
  blocked: "waiting for input",
  unknown: "running",
};

/**
 * A member that is an agent already running on your machine, in a herdr pane
 * no room has. Pick it, name it, and its runner maps the pane to the room
 * (after asking on the machine) and types its introduction once it's idle.
 */
export function RunningAgentMember({
  roomName,
  onAdded,
  onClose,
}: {
  roomName: string;
  onAdded: (handle: string) => void;
  onClose: () => void;
}) {
  const { principal } = useCurrentUser();
  const { connected, loading } = useRunners();
  const revalidateRoom = useRoomRevalidate(roomName);
  const revalidateRunners = useRunnersRevalidate();
  const candidates = useMemo(() => runningAgents(connected), [connected]);

  const [pick, setPick] = useState<string | null>(null);
  const [handle, setHandle] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState<{ runner: Runner; job: string; handle: string } | null>(null);

  const key = (c: RunningAgent) => `${c.runner.id}:${c.agent.pane}`;
  const chosen = candidates.find((c) => key(c) === pick) ?? candidates[0];
  const handleShown = handle ?? chosen?.agent.suggested_handle ?? "";
  const trimmed = normHandle(handleShown);
  const canSubmit = !!chosen && handleValid(handleShown) && !submitting;

  const { job } = useRunnerJob(queued?.runner.id ?? null, queued?.job ?? null);
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (job?.status !== "done" || !queued || reported.current === queued.job) return;
    reported.current = queued.job;
    revalidateRoom();
    revalidateRunners();
    onAdded(queued.handle);
  }, [job?.status, queued, revalidateRoom, revalidateRunners, onAdded]);

  const submit = async () => {
    if (!canSubmit || !chosen) return;
    setSubmitting(true);
    setError(null);
    try {
      const made = await adoptRunnerAgent(chosen.runner.id, {
        room: roomName,
        pane: chosen.agent.pane,
        handle: trimmed,
        created_by: principal.trim() || undefined,
      });
      revalidateRoom();
      setQueued({ runner: chosen.runner, job: made.id, handle: trimmed });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not bring the agent in");
    } finally {
      setSubmitting(false);
    }
  };

  if (queued) {
    const machine = runnerName(queued.runner);
    const status = job?.status ?? "queued";
    const introduced = job?.result?.introduced === true;
    const line =
      status === "done"
        ? introduced
          ? `@${queued.handle} is in ${roomName}, and its introduction is typed into its pane.`
          : `@${queued.handle} is in ${roomName}. It gets its introduction as soon as it's idle.`
        : status === "failed"
          ? (job?.error ?? `${machine} couldn't bring it in.`)
          : status === "waiting"
            ? `Waiting for someone on ${machine} to approve it. ${machine} asks before it types into an agent's terminal.`
            : `Sent to ${machine}.`;
    return (
      <>
        <div className="px-5 py-4">
          <p role={status === "failed" ? "alert" : "status"} className={cn("text-label", status === "failed" ? "text-red" : "text-text")}>
            {line}
          </p>
        </div>
        <MemberFooter
          action={
            status === "failed" ? (
              <Button variant="outline" onClick={() => setQueued(null)}>
                Back
              </Button>
            ) : (
              <Button onClick={onClose}>Done</Button>
            )
          }
        >
          <Laptop className="size-4 flex-shrink-0" aria-hidden />
          <span className="truncate">Runs on {machine}.</span>
        </MemberFooter>
      </>
    );
  }

  if (connected.length === 0) {
    return (
      <div className="px-5 py-4">
        {loading ? (
          <p className="text-label text-muted-foreground">Looking for your machines…</p>
        ) : (
          <ConnectMachine />
        )}
      </div>
    );
  }

  if (!chosen) {
    const where = connected.length === 1 ? runnerName(connected[0]) : "your machines";
    return (
      <div className="space-y-1 px-5 py-4">
        <p className="text-label text-text">Every agent running on {where} is in a room already.</p>
        <p className="text-micro text-muted-foreground">
          An agent CLI you start in herdr shows up here until a room has it.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="space-y-4 px-5 py-4">
        <div>
          <p id="running-agent-label" className="mb-2 text-micro font-medium text-muted-foreground">
            Which agent
          </p>
          <div role="radiogroup" aria-labelledby="running-agent-label" className="max-h-56 space-y-1.5 overflow-y-auto">
            {candidates.map((c) => {
              const active = key(c) === key(chosen);
              const where = [c.agent.tab_label, c.agent.folder && tildePath(c.agent.folder)].filter(Boolean).join(" · ");
              return (
                <button
                  key={key(c)}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  onClick={() => {
                    setPick(key(c));
                    setHandle(null);
                    setError(null);
                  }}
                  className={cn(
                    "flex w-full items-baseline gap-2 rounded-lg border px-3 py-2 text-left transition-colors",
                    active ? "border-accent bg-accent/10" : "border-border hover:border-border2 hover:bg-hairline",
                  )}
                >
                  <span className={cn("text-label font-medium", active ? "text-text" : "text-muted-foreground")}>
                    {cliName(c.runner, c.agent.kind)}
                  </span>
                  <span className="min-w-0 flex-1 truncate font-mono text-micro text-faint">{where}</span>
                  <span className="flex-shrink-0 text-micro text-faint">
                    {connected.length > 1 ? `${runnerName(c.runner)}, ` : ""}
                    {STATE_LABEL[c.agent.state]}
                  </span>
                </button>
              );
            })}
          </div>
        </div>

        <IdentityRow
          value={handleShown}
          onChange={(v) => {
            setHandle(v);
            setError(null);
          }}
          hint="How the room addresses it. Its own session keeps going as it is."
        />
        {error && (
          <p role="alert" className="break-words text-label text-red">
            {error}
          </p>
        )}
      </div>
      <MemberFooter
        action={
          <Button onClick={() => void submit()} disabled={!canSubmit}>
            {submitting ? "Adding…" : "Add to room"}
          </Button>
        }
      >
        <Laptop className="size-4 flex-shrink-0" aria-hidden />
        <span className="truncate">
          {runnerName(chosen.runner)} asks first, then types its introduction once it&apos;s idle.
        </span>
      </MemberFooter>
    </>
  );
}
