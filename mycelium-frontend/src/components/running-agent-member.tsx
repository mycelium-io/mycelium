// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Laptop } from "lucide-react";
import { adoptRunnerAgent, resumeAgentSession, type Framework, type MachineUnenrolled, type Runner } from "@/lib/api";
import { EarlierSessions, sessionKey, type EarlierSession } from "@/components/earlier-sessions";
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

/** Every earlier session your machines' agent CLIs can list, newest first. */
export function earlierSessions(runners: Runner[]): EarlierSession[] {
  return runners
    .flatMap((runner) =>
      runner.frameworks.flatMap((framework) =>
        framework.installed ? (framework.sessions ?? []).map((session) => ({ runner, framework, session })) : [],
      ),
    )
    .sort((a, b) => b.session.last_used.localeCompare(a.session.last_used));
}

/** The installed agent CLIs whose sessions can't be listed yet. */
export function sessionsUnsupported(runners: Runner[]): Framework[] {
  const seen = new Map<string, Framework>();
  for (const r of runners) for (const f of r.frameworks) if (f.installed && !f.sessions) seen.set(f.id, f);
  return [...seen.values()];
}

/** Where to read how an agent CLI's integration lists and resumes sessions. */
export const ADD_SESSION_SUPPORT_URL =
  "https://github.com/mycelium-io/mycelium/tree/main/mycelium-cli/src/mycelium/integrations/agents";

/** A suggested handle for a session: its folder's name. */
function handleFor(folder: string): string {
  const name = folder.replace(/\/+$/, "").split("/").pop() ?? "";
  return name.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
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
  const earlier = useMemo(() => earlierSessions(connected), [connected]);
  const unsupported = useMemo(() => sessionsUnsupported(connected), [connected]);

  const [pick, setPick] = useState<string | null>(null);
  const [handle, setHandle] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [queued, setQueued] = useState<{ runner: Runner; job: string; handle: string; resumed: boolean } | null>(null);

  const key = (c: RunningAgent) => `run:${c.runner.id}:${c.agent.pane}`;
  const pastKey = sessionKey;
  // Running now comes first, so it's the one picked until another is.
  const chosenPast = earlier.find((s) => pastKey(s) === pick) ?? null;
  const chosen = chosenPast ? undefined : (candidates.find((c) => key(c) === pick) ?? candidates[0]);
  const chosenAny = chosen ?? chosenPast ?? earlier[0] ?? null;
  const past = chosenPast ?? (chosen ? null : (earlier[0] ?? null));
  const handleShown = handle ?? (past ? handleFor(past.session.folder) : (chosen?.agent.suggested_handle ?? ""));
  const trimmed = normHandle(handleShown);
  const canSubmit = !!chosenAny && handleValid(handleShown) && !submitting;
  const choose = (k: string) => {
    setPick(k);
    setHandle(null);
    setError(null);
  };

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
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      const by = principal.trim() || undefined;
      if (past) {
        const made = await resumeAgentSession(past.runner.id, {
          room: roomName,
          framework: past.framework.id,
          session: past.session.id,
          folder: past.session.folder,
          handle: trimmed,
          created_by: by,
        });
        revalidateRoom();
        setQueued({ runner: past.runner, job: made.id, handle: trimmed, resumed: true });
        return;
      }
      if (!chosen) return;
      const made = await adoptRunnerAgent(chosen.runner.id, {
        room: roomName,
        pane: chosen.agent.pane,
        handle: trimmed,
        created_by: by,
      });
      revalidateRoom();
      setQueued({ runner: chosen.runner, job: made.id, handle: trimmed, resumed: false });
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
        ? queued.resumed
          ? `@${queued.handle} is in ${roomName}, its session resumed in its own pane.`
          : introduced
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

  // Not seeing them? Each agent CLI whose sessions can't be listed says so,
  // and where to add it.
  const missing = unsupported.map((f) => (
    <p key={f.id} className="text-micro text-faint">
      Not seeing your {f.name} sessions? They can&apos;t be brought in yet.{" "}
      <a href={ADD_SESSION_SUPPORT_URL} target="_blank" rel="noreferrer" className="text-accent hover:underline">
        Add support
      </a>
    </p>
  ));

  if (!chosenAny) {
    const where = connected.length === 1 ? runnerName(connected[0]) : "your machines";
    return (
      <div className="space-y-1 px-5 py-4">
        <p className="text-label text-text">Every agent running on {where} is in a room already.</p>
        <p className="text-micro text-muted-foreground">
          An agent CLI you start in herdr shows up here until a room has it.
        </p>
        {missing}
      </div>
    );
  }

  const row = (active: boolean) =>
    cn(
      "flex w-full items-baseline gap-2 rounded-lg border px-3 py-2 text-left transition-colors",
      active ? "border-accent bg-accent/10" : "border-border hover:border-border2 hover:bg-hairline",
    );

  return (
    <>
      <div className="space-y-4 px-5 py-4">
        <div role="radiogroup" aria-label="Which agent" className="max-h-[26rem] space-y-3 overflow-y-auto">
          {candidates.length > 0 && (
            <div className="space-y-1.5">
              <p className="text-micro font-medium text-muted-foreground">Running now</p>
              {candidates.map((c) => {
                const active = !past && chosen !== undefined && key(c) === key(chosen);
                const where = [c.agent.tab_label, c.agent.folder && tildePath(c.agent.folder)].filter(Boolean).join(" · ");
                return (
                  <button key={key(c)} type="button" role="radio" aria-checked={active} onClick={() => choose(key(c))} className={row(active)}>
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
          )}
          {earlier.length > 0 && (
            <EarlierSessions
              sessions={earlier}
              picked={past ? pastKey(past) : null}
              onPick={choose}
            />
          )}
          {missing}
        </div>

        <IdentityRow
          value={handleShown}
          onChange={(v) => {
            setHandle(v);
            setError(null);
          }}
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
          {past
            ? `${runnerName(past.runner)} asks first, then resumes the session in its own pane.`
            : `${runnerName(chosenAny.runner)} asks first, then types its introduction once it's idle.`}
        </span>
      </MemberFooter>
    </>
  );
}
