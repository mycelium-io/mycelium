// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { launchRunnerAgent } from "@/lib/api";
import { launchable, runnerName, useRunnerJob, useRunners, useRunnersRevalidate } from "@/lib/runners";
import { useRoomRevalidate } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  ConnectMachine,
  FolderField,
  FrameworkPicker,
  HerdrMissing,
  MachinePicker,
} from "@/components/runner-fields";

/** The hub's handle rule: a lowercase slug starting alphanumeric. */
const HANDLE_RE = /^[a-z0-9][a-z0-9_-]*$/;

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roomName: string;
  /** Called once the machine reports the agent started. */
  onLaunched?: (handle: string) => void;
}

/**
 * Define an agent and start it on your machine, from the app.
 *
 * The agent is registered in this room by the hub (its manifest, and its
 * instructions as `agents/<handle>/notes`), then the machine's runner starts
 * the chosen agent CLI as that handle in a herdr pane. herdr is the only way a
 * runner starts an agent, so a machine without it can start nothing here. The
 * dialog follows the runner's job, so
 * a failure on the machine reads here rather than in a terminal you can't see.
 */
export function LaunchAgentDialog({ open, onOpenChange, roomName, onLaunched }: Props) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[calc(100vh-2rem)] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="text-ui font-semibold text-text">Start an agent on your machine</DialogTitle>
          <DialogDescription className="text-label leading-relaxed text-muted-foreground">
            Pick an agent CLI you have installed and say how it should work. It opens in a herdr
            terminal on that machine, where you can watch and type to it, already a member of
            this room.
          </DialogDescription>
        </DialogHeader>
        {open && (
          <LaunchAgentForm
            roomName={roomName}
            onLaunched={(handle) => {
              onLaunched?.(handle);
              onOpenChange(false);
            }}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

export function LaunchAgentForm({
  roomName,
  onLaunched,
}: {
  roomName: string;
  onLaunched: (handle: string) => void;
}) {
  const { principal } = useCurrentUser();
  const { connected, loading } = useRunners();
  const revalidateRoom = useRoomRevalidate(roomName);
  const revalidateRunners = useRunnersRevalidate();

  // Each choice is the user's once made; until then it follows the machine.
  const [runnerPick, setRunnerPick] = useState<string | null>(null);
  const [frameworkPick, setFrameworkPick] = useState<string | null>(null);
  const [folderPick, setFolderPick] = useState<string | null>(null);
  const [handle, setHandle] = useState("");
  const [instructions, setInstructions] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  const runner = connected.find((r) => r.id === runnerPick) ?? connected[0];
  const startable = runner ? launchable(runner) : [];
  const framework =
    startable.find((f) => f.id === frameworkPick) ?? startable[0];
  const folder = folderPick ?? runner?.roots[0] ?? "";

  const { job } = useRunnerJob(runner?.id ?? null, jobId);
  const trimmed = handle.trim().replace(/^@/, "").toLowerCase();
  const handleOk = HANDLE_RE.test(trimmed);
  const busy = submitting || (jobId !== null && job?.status !== "failed");
  const canSubmit = !!runner?.herdr && !!framework && handleOk && !busy;

  // The machine said it started: the agent is in the room's roster now.
  const done = job?.status === "done";
  const reported = useRef<string | null>(null);
  useEffect(() => {
    if (!done || reported.current === jobId) return;
    reported.current = jobId;
    revalidateRoom();
    revalidateRunners();
    onLaunched(trimmed);
  }, [done, jobId, revalidateRoom, revalidateRunners, onLaunched, trimmed]);

  if (!runner) {
    return loading ? (
      <p className="mt-2 text-label text-muted-foreground">Looking for your machines…</p>
    ) : (
      <div className="mt-2">
        <ConnectMachine />
      </div>
    );
  }

  const submit = async () => {
    if (!canSubmit || !framework) return;
    setSubmitting(true);
    setError(null);
    setJobId(null);
    try {
      const queued = await launchRunnerAgent(runner.id, {
        room: roomName,
        handle: trimmed,
        framework: framework.id,
        instructions: instructions.trim() || undefined,
        description: description.trim() || undefined,
        cwd: folder.trim() || undefined,
        created_by: principal.trim() || undefined,
      });
      setJobId(queued.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not start the agent");
    } finally {
      setSubmitting(false);
    }
  };

  const failure = error ?? (job?.status === "failed" ? (job.error ?? "The machine could not start it") : null);

  return (
    <div className="mt-2 space-y-4">
      <MachinePicker runners={connected} value={runner.id} onChange={setRunnerPick} />
      {!runner.herdr && <HerdrMissing runner={runner} />}
      <FrameworkPicker runner={runner} value={framework?.id ?? null} onChange={setFrameworkPick} />

      <div className="space-y-1.5">
        <label htmlFor="launch-handle" className="block text-micro font-medium text-muted-foreground">
          Handle
        </label>
        <Input
          id="launch-handle"
          value={handle}
          onChange={(e) => {
            setHandle(e.target.value);
            setError(null);
          }}
          placeholder="reviewer"
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={trimmed.length > 0 && !handleOk}
        />
        <p className="text-micro leading-snug text-muted-foreground">
          Address it in the room with <code className="font-mono text-accent">@{trimmed || "handle"}</code>.
          Lowercase letters, digits, - and _.
        </p>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="launch-instructions" className="block text-micro font-medium text-muted-foreground">
          Instructions <span className="font-normal">(optional)</span>
        </label>
        <textarea
          id="launch-instructions"
          value={instructions}
          onChange={(e) => setInstructions(e.target.value)}
          rows={4}
          placeholder="You review pull requests for correctness. Be specific and brief."
          className="w-full resize-y rounded-lg border border-border bg-bg px-3 py-2 text-label text-text outline-none transition-colors placeholder:text-muted-foreground hover:border-border2 focus:border-accent"
        />
        <p className="text-micro leading-snug text-muted-foreground">
          How this agent should work. Saved as its notes, which it reads when it starts.
        </p>
      </div>

      <div className="space-y-1.5">
        <label htmlFor="launch-description" className="block text-micro font-medium text-muted-foreground">
          Description <span className="font-normal">(optional)</span>
        </label>
        <Input
          id="launch-description"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What this agent does in the room"
        />
      </div>

      <FolderField runner={runner} value={folder} onChange={setFolderPick} />

      {jobId && !failure && (
        <p role="status" className="flex items-center gap-2 text-label text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          {job?.status === "running"
            ? `Starting @${trimmed} on ${runnerName(runner)}…`
            : job?.status === "done"
              ? `@${trimmed} is running.`
              : `Waiting for ${runnerName(runner)} to pick it up…`}
        </p>
      )}
      {failure && (
        <p role="alert" className="break-words text-label text-red">
          {failure}
        </p>
      )}

      <div className="flex items-center gap-2">
        <Button size="sm" onClick={submit} disabled={!canSubmit}>
          {busy ? "Starting…" : framework ? `Start ${framework.name}` : "Start"}
        </Button>
        {runner.herdr && !framework && (
          <span className="text-micro text-muted-foreground">
            No agent CLI this machine can start. Install one, then rescan.
          </span>
        )}
      </div>
    </div>
  );
}
