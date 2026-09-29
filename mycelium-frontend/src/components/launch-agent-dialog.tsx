// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { Check, Circle, Laptop, Loader2, X } from "lucide-react";
import { launchRunnerAgent, type Runner, type RunnerJob } from "@/lib/api";
import {
  jobSettled,
  launchable,
  runnerName,
  useRunnerJob,
  useRunners,
  useRunnersRevalidate,
} from "@/lib/runners";
import {
  BUILT_IN,
  deleteTemplate,
  loadSaved,
  saveTemplate,
  type InstructionTemplate,
} from "@/lib/instruction-templates";
import { useRoomRevalidate } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import { Monogram } from "@/components/ui/monogram";
import {
  ConnectMachine,
  HerdrMissing,
  RescanButton,
  shortVersion,
} from "@/components/runner-fields";
import { cn } from "@/lib/utils";

/** The hub's handle rule: a lowercase slug starting alphanumeric. */
const HANDLE_RE = /^[a-z0-9][a-z0-9_-]*$/;

/** ``/Users/julia/code`` as ``~/code``, for showing a path, never for sending one. */
export function tildePath(path: string): string {
  return path.replace(/^\/(?:Users|home)\/[^/]+(?=\/|$)/, "~");
}

/** A folder as typed (``~/code`` allowed) as the absolute path the machine checks. */
export function expandPath(typed: string, roots: string[]): string {
  const home = roots.map((r) => r.match(/^\/(?:Users|home)\/[^/]+/)?.[0]).find(Boolean);
  return home && /^~(?=\/|$)/.test(typed) ? typed.replace(/^~/, home) : typed;
}

function handleFromName(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
}

/**
 * A member that is a coding agent on your machine, started by its runner.
 *
 * Read top to bottom it is the agent itself: the role it starts from, its
 * handle, and its instructions (its notes, the character it reads when it
 * starts). Where it runs (machine, agent CLI, folder) is the strip at the
 * bottom beside the button. Once started, it follows the machine's job step
 * by step, so a failure there reads here rather than in a terminal you can't see.
 */
export function LaunchAgentForm({
  roomName,
  onLaunched,
  onClose = () => {},
}: {
  roomName: string;
  onLaunched: (handle: string) => void;
  onClose?: () => void;
}) {
  const { principal } = useCurrentUser();
  const { connected, loading } = useRunners();
  const revalidateRoom = useRoomRevalidate(roomName);
  const revalidateRunners = useRunnersRevalidate();

  const [runnerPick, setRunnerPick] = useState<string | null>(null);
  const [frameworkPick, setFrameworkPick] = useState<string | null>(null);
  const [folderTyped, setFolderTyped] = useState<string | null>(null);
  const [role, setRole] = useState<string | null>(null);
  const [handle, setHandle] = useState("");
  const [handleTouched, setHandleTouched] = useState(false);
  const [instructions, setInstructions] = useState("");
  const [saved, setSaved] = useState<InstructionTemplate[]>(() => loadSaved());
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const runner = connected.find((r) => r.id === runnerPick) ?? connected[0];
  const startable = useMemo(() => (runner ? launchable(runner) : []), [runner]);
  const framework = startable.find((f) => f.id === frameworkPick) ?? startable[0];
  const folderShown = folderTyped ?? tildePath(runner?.roots[0] ?? "");

  const { job } = useRunnerJob(runner?.id ?? null, jobId);
  const trimmed = handle.trim().replace(/^@/, "").toLowerCase();
  const handleOk = HANDLE_RE.test(trimmed);
  const canSubmit = !!runner?.herdr && !!framework && handleOk && !submitting;

  const done = job?.status === "done";
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (!done || reported.current === jobId) return;
    reported.current = jobId;
    revalidateRoom();
    revalidateRunners();
    onLaunched(trimmed);
  }, [done, jobId, revalidateRoom, revalidateRunners, onLaunched, trimmed]);

  const pickRole = (t: InstructionTemplate | null) => {
    setRole(t?.name ?? null);
    setInstructions(t?.text ?? "");
    if (!handleTouched) setHandle(t ? handleFromName(t.name) : "");
  };

  const submit = async () => {
    if (!canSubmit || !runner || !framework) return;
    setSubmitting(true);
    setError(null);
    setJobId(null);
    try {
      const folder = expandPath(folderShown.trim(), runner.roots);
      const queued = await launchRunnerAgent(runner.id, {
        room: roomName,
        handle: trimmed,
        framework: framework.id,
        instructions: instructions.trim() || undefined,
        cwd: folder || undefined,
        created_by: principal.trim() || undefined,
      });
      setJobId(queued.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the agent");
    } finally {
      setSubmitting(false);
    }
  };

  const startOver = () => {
    setJobId(null);
    setError(null);
    setRole(null);
    setHandle("");
    setHandleTouched(false);
    setInstructions("");
  };

  if (!runner) {
    return (
      <div className="px-6 py-5">
        {loading ? (
          <p className="text-label text-muted-foreground">Looking for your machines…</p>
        ) : (
          <ConnectMachine />
        )}
      </div>
    );
  }

  if (jobId) {
    return (
      <LaunchProgress
        job={job}
        runner={runner}
        room={roomName}
        handle={trimmed}
        frameworkName={framework?.name ?? "the agent"}
        onRetry={() => setJobId(null)}
        onAnother={startOver}
        onClose={onClose}
      />
    );
  }

  return (
    <>
      <div className="space-y-5 px-6 py-5">
        <RoleRow
          saved={saved}
          role={role}
          onPick={pickRole}
          onDelete={(name) => {
            setSaved(deleteTemplate(name));
            if (role === name) setRole(null);
          }}
        />

        <IdentityRow
          value={handle}
          onChange={(v) => {
            setHandle(v);
            setHandleTouched(true);
            setError(null);
          }}
        />

        <InstructionsEditor
          handle={trimmed}
          value={instructions}
          onChange={(v) => {
            setInstructions(v);
            if (role && v !== [...saved, ...BUILT_IN].find((t) => t.name === role)?.text) setRole(null);
          }}
          onSaveTemplate={(name) => {
            setSaved(saveTemplate(name, instructions));
            setRole(name.trim());
          }}
        />

        {error && (
          <p role="alert" className="break-words text-label text-red">
            {error}
          </p>
        )}
      </div>

      <RunsOn
        runners={connected}
        runner={runner}
        frameworkId={framework?.id ?? null}
        folder={folderShown}
        onRunner={(id) => {
          setRunnerPick(id);
          setFolderTyped(null);
        }}
        onFramework={setFrameworkPick}
        onFolder={setFolderTyped}
      >
        <Button onClick={submit} disabled={!canSubmit}>
          {submitting ? "Adding…" : `Add ${trimmed && handleOk ? `@${trimmed}` : "agent"}`}
        </Button>
      </RunsOn>
    </>
  );
}

/** A handle as typed, as the hub will store it: no leading `@`, lowercase. */
export function normHandle(value: string): string {
  return value.trim().replace(/^@/, "").toLowerCase();
}

export function handleValid(value: string): boolean {
  return HANDLE_RE.test(normHandle(value));
}

/** Who the member is: its avatar as the room will draw it, and its `@handle`. */
export function IdentityRow({
  value,
  onChange,
  hint = "How the room addresses it, and how it signs what it posts.",
}: {
  value: string;
  onChange: (value: string) => void;
  hint?: string;
}) {
  const trimmed = normHandle(value);
  const bad = trimmed.length > 0 && !HANDLE_RE.test(trimmed);
  return (
    <div className="flex items-center gap-3">
      <Monogram handle={trimmed || "?"} className="size-10 text-label" />
      <div className="min-w-0 flex-1">
        <label htmlFor="member-handle" className="sr-only">
          Handle
        </label>
        <div
          className={cn(
            "flex items-center rounded-lg border bg-bg px-3 transition-colors focus-within:border-accent",
            bad ? "border-red" : "border-border hover:border-border2",
          )}
        >
          <span className="font-mono text-ui text-faint">@</span>
          <input
            id="member-handle"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            placeholder="handle"
            autoCapitalize="none"
            autoComplete="off"
            spellCheck={false}
            aria-invalid={bad}
            className="w-full bg-transparent py-2 pl-0.5 font-mono text-ui text-text outline-none placeholder:text-faint"
          />
        </div>
      </div>
      <p
        className={cn(
          "hidden w-44 text-micro leading-snug sm:block",
          bad ? "text-red" : "text-muted-foreground",
        )}
      >
        {bad ? "Lowercase letters, digits, - and _." : hint}
      </p>
    </div>
  );
}

/**
 * The strip along the bottom of every kind of member: where it will run, on
 * the left, and the one button that adds it, on the right.
 */
export function MemberFooter({
  children,
  action,
  above,
}: {
  children: React.ReactNode;
  action: React.ReactNode;
  /** A notice that belongs to where it runs, shown above the strip's row. */
  above?: React.ReactNode;
}) {
  return (
    <div className="space-y-2 border-t border-border bg-surface/60 px-6 py-3">
      {above}
      <div className="flex items-center gap-3">
        <div className="flex min-w-0 flex-1 items-center gap-2 text-label text-muted-foreground">
          {children}
        </div>
        <div className="flex-shrink-0">{action}</div>
      </div>
    </div>
  );
}

/** The roles to start from: yours first, then the built-in ones, then a blank page. */
function RoleRow({
  saved,
  role,
  onPick,
  onDelete,
}: {
  saved: InstructionTemplate[];
  role: string | null;
  onPick: (t: InstructionTemplate | null) => void;
  onDelete: (name: string) => void;
}) {
  const chip = (active: boolean) =>
    cn(
      "flex items-center gap-1 rounded-full border px-3 py-1 text-label transition-colors",
      active
        ? "border-accent bg-accent/10 text-text"
        : "border-border text-muted-foreground hover:border-border2 hover:text-text",
    );
  return (
    <div>
      <p id="launch-role-label" className="mb-2 text-micro font-medium text-muted-foreground">
        Start from a role
      </p>
      <div role="radiogroup" aria-labelledby="launch-role-label" className="flex flex-wrap gap-1.5">
        {[...saved, ...BUILT_IN].map((t) => (
          <span key={`${t.saved ? "saved" : "built"}-${t.name}`} className="group relative">
            <button
              type="button"
              role="radio"
              aria-checked={role === t.name}
              title={t.text}
              onClick={() => onPick(t)}
              className={cn(chip(role === t.name), t.saved && "pr-6")}
            >
              {t.name}
            </button>
            {t.saved && (
              <button
                type="button"
                aria-label={`Delete ${t.name}`}
                onClick={() => onDelete(t.name)}
                className="absolute top-1/2 right-1.5 -translate-y-1/2 rounded-full p-0.5 text-faint hover:text-red"
              >
                <X className="size-3" />
              </button>
            )}
          </span>
        ))}
        <button
          type="button"
          role="radio"
          aria-checked={role === null}
          onClick={() => onPick(null)}
          className={cn(chip(role === null), "border-dashed")}
        >
          blank
        </button>
      </div>
    </div>
  );
}

const INSTRUCTIONS_PLACEHOLDER =
  "What is this agent for, and how should it work?\n\n" +
  "It reads this first, every time it starts. Say what it owns, how it " +
  "should talk to the room, and when to ask a teammate.";

/** A member's instructions: the notes it reads, which can be kept as a role. */
export function InstructionsEditor({
  handle,
  value,
  onChange,
  onSaveTemplate,
  placeholder = INSTRUCTIONS_PLACEHOLDER,
  rows = 9,
}: {
  handle: string;
  value: string;
  onChange: (value: string) => void;
  /** Offered as "Save as a role" when given. */
  onSaveTemplate?: (name: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  return (
    <div className="rounded-lg border border-border bg-bg transition-colors focus-within:border-accent hover:border-border2">
      <label htmlFor="launch-instructions" className="sr-only">
        Instructions
      </label>
      <textarea
        id="launch-instructions"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={rows}
        placeholder={placeholder}
        className="block min-h-32 w-full resize-y bg-transparent px-4 py-3 text-label leading-relaxed text-text outline-none placeholder:text-faint"
      />
      <div className="flex items-center gap-2 border-t border-border px-4 py-2 text-micro text-muted-foreground">
        <span className="min-w-0 truncate">
          Saved as <code className="font-mono">agents/{handle || "handle"}/notes</code>. Edit it
          any time in Memory.
        </span>
        {!onSaveTemplate ? null : naming ? (
          <form
            className="ml-auto flex items-center gap-1.5"
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim()) return;
              onSaveTemplate(name);
              setName("");
              setNaming(false);
            }}
          >
            <input
              autoFocus
              aria-label="Role name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.stopPropagation();
                  setNaming(false);
                }
              }}
              placeholder="Role name"
              className="w-32 rounded border border-border bg-surface px-2 py-0.5 text-micro text-text outline-none focus:border-accent"
            />
            <button type="submit" disabled={!name.trim()} className="text-accent disabled:text-faint">
              Save
            </button>
          </form>
        ) : (
          <button
            type="button"
            disabled={!value.trim()}
            onClick={() => setNaming(true)}
            className="ml-auto flex-shrink-0 text-accent hover:underline disabled:text-faint disabled:no-underline"
          >
            Save as a role
          </button>
        )}
      </div>
    </div>
  );
}

const selectClass =
  "rounded-md border border-border bg-bg px-2 py-1 text-label text-text outline-none hover:border-border2 focus:border-accent";

/** Where the agent runs: machine, agent CLI and folder, in one strip beside the button. */
function RunsOn({
  runners,
  runner,
  frameworkId,
  folder,
  onRunner,
  onFramework,
  onFolder,
  children,
}: {
  runners: Runner[];
  runner: Runner;
  frameworkId: string | null;
  folder: string;
  onRunner: (id: string) => void;
  onFramework: (id: string) => void;
  onFolder: (folder: string) => void;
  children: React.ReactNode;
}) {
  const startable = launchable(runner);
  const roots = runner.roots.map(tildePath);
  return (
    <MemberFooter
      action={children}
      above={
        <>
          {!runner.herdr ? (
            <HerdrMissing runner={runner} />
          ) : startable.length === 0 ? (
            <p className="text-micro text-muted-foreground">
              No agent CLI on this machine that herdr can start. Install one, then rescan.
            </p>
          ) : null}
          {/* First line: which machine, and which agent CLI on it. */}
          <div className="flex min-w-0 items-center gap-2 text-label text-muted-foreground">
            <Laptop className="size-4 flex-shrink-0" aria-hidden />
            {runners.length > 1 ? (
              <select
                aria-label="Machine"
                value={runner.id}
                onChange={(e) => onRunner(e.target.value)}
                className={cn(selectClass, "max-w-48")}
              >
                {runners.map((r) => (
                  <option key={r.id} value={r.id}>
                    {runnerName(r)}
                  </option>
                ))}
              </select>
            ) : (
              <span className="max-w-48 truncate text-text" title={runnerName(runner)}>
                {runnerName(runner)}
              </span>
            )}
            {startable.length > 0 && (
              <>
                <span className="flex-shrink-0 text-micro text-faint">with</span>
                <select
                  aria-label="Agent CLI"
                  value={frameworkId ?? ""}
                  onChange={(e) => onFramework(e.target.value)}
                  className={cn(selectClass, "flex-shrink-0")}
                >
                  {startable.map((f) => (
                    <option key={f.id} value={f.id}>
                      {f.name}
                      {shortVersion(f.version) ? ` ${shortVersion(f.version)}` : ""}
                    </option>
                  ))}
                </select>
              </>
            )}
            <RescanButton runner={runner} iconOnly />
          </div>
        </>
      }
    >
      {/* Second line: the folder it works in, with the room to read the path. */}
      <label htmlFor="launch-folder" className="flex-shrink-0 text-micro text-faint">
        Folder
      </label>
      <input
        id="launch-folder"
        list="launch-folder-roots"
        value={folder}
        onChange={(e) => onFolder(e.target.value)}
        spellCheck={false}
        placeholder={roots[0] ?? "~/code/project"}
        title={roots.length ? `Inside ${roots.join(" or ")}` : undefined}
        className={cn(selectClass, "min-w-0 flex-1 py-1.5 font-mono")}
      />
      <datalist id="launch-folder-roots">
        {roots.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>
    </MemberFooter>
  );
}

type StepState = "done" | "active" | "waiting" | "failed";

/** The start, step by step, from the hub's write to the agent running in herdr. */
function LaunchProgress({
  job,
  runner,
  room,
  handle,
  frameworkName,
  onRetry,
  onAnother,
  onClose,
}: {
  job: RunnerJob | null | undefined;
  runner: Runner;
  room: string;
  handle: string;
  frameworkName: string;
  onRetry: () => void;
  onAnother: () => void;
  onClose: () => void;
}) {
  const status = job?.status ?? "queued";
  const failed = status === "failed";
  const machine = runnerName(runner);
  // A machine asks the person there before starting what a hub sent it,
  // except the app's own hub; the step shows only once it has asked.
  const [asked, setAsked] = useState(false);
  if (status === "waiting" && !asked) setAsked(true);
  const steps: { label: string; state: StepState }[] = [
    { label: `@${handle} added to ${room}, with its notes`, state: "done" },
    { label: `${machine} picked it up`, state: status === "queued" ? "active" : "done" },
    ...(asked
      ? [
          {
            label: `Yes given on ${machine}`,
            state: (status === "waiting" ? "active" : failed ? "failed" : "done") as StepState,
          },
        ]
      : []),
    {
      label: `${frameworkName} running in herdr, reading its notes`,
      state: status === "done" ? "done" : failed ? "failed" : status === "running" ? "active" : "waiting",
    },
  ];
  return (
    <div className="px-6 py-5">
      <div className="flex items-center gap-3">
        <Monogram handle={handle} className="size-10 text-label" />
        <div>
          <p className="font-mono text-ui text-text">@{handle}</p>
          <p className="text-micro text-muted-foreground">
            {status === "done"
              ? `Running on ${machine}, in herdr workspace ${room}.`
              : failed
                ? `Added to ${room}, but ${machine} could not start it.`
                : status === "waiting"
                  ? `Waiting for a yes on ${machine}: it asks there before starting anything.`
                  : `Starting on ${machine}…`}
          </p>
        </div>
      </div>
      <ol className="mt-5 space-y-2.5">
        {steps.map((s) => (
          <li key={s.label} className="flex items-center gap-2.5 text-label">
            <StepIcon state={s.state} />
            <span className={s.state === "waiting" ? "text-faint" : "text-text"}>{s.label}</span>
          </li>
        ))}
      </ol>
      {failed && (
        <p role="alert" className="mt-4 break-words rounded-lg border border-red/30 bg-red/5 px-3 py-2 text-label text-red">
          {job?.error ?? "The machine could not start it."}
        </p>
      )}
      <div className="mt-6 flex justify-end gap-2">
        {failed ? (
          <Button variant="secondary" onClick={onRetry}>
            Back
          </Button>
        ) : (
          jobSettled(job) && (
            <Button variant="secondary" onClick={onAnother}>
              Add another
            </Button>
          )
        )}
        <Button onClick={onClose}>{jobSettled(job) ? "Done" : "Close"}</Button>
      </div>
    </div>
  );
}

function StepIcon({ state }: { state: StepState }) {
  if (state === "done") return <Check className="size-4 text-green" aria-label="done" />;
  if (state === "failed") return <X className="size-4 text-red" aria-label="failed" />;
  if (state === "active") return <Loader2 className="size-4 animate-spin text-accent" aria-label="in progress" />;
  return <Circle className="size-4 text-faint" aria-label="waiting" />;
}
