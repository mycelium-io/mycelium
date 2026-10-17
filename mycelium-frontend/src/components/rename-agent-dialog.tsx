// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState } from "react";
import { renameAgent, type AgentRenamed } from "@/lib/api";
import { runnerName, useRunnerJob, useRunners } from "@/lib/runners";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { IdentityRow, handleValid, normHandle } from "@/components/launch-agent-dialog";

interface Props {
  roomName: string;
  /** The agent being renamed, or null when the dialog is closed. */
  handle: string | null;
  onClose: () => void;
  onRenamed: (handle: string) => void;
}

/**
 * The app's `mycelium agent rename`: a new handle for an agent. Its notes, the
 * tasks it holds and its place in the room move with it, its pane is renamed on
 * its machine's next sync, and you tell the room, which wakes the agent with
 * its new name.
 */
export function RenameAgentDialog({ roomName, handle, onClose, onRenamed }: Props) {
  const [loading, setLoading] = useState(false);
  return (
    <Dialog
      open={handle !== null}
      onOpenChange={(next) => {
        if (!next && !loading) onClose();
      }}
    >
      <DialogContent>
        {/* Mounted per opening, so each one starts from the agent's name. */}
        {handle && (
          <RenameForm
            key={handle}
            roomName={roomName}
            handle={handle}
            loading={loading}
            setLoading={setLoading}
            onClose={onClose}
            onRenamed={onRenamed}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function RenameForm({
  roomName,
  handle,
  loading,
  setLoading,
  onClose,
  onRenamed,
}: {
  roomName: string;
  handle: string;
  loading: boolean;
  setLoading: (loading: boolean) => void;
  onClose: () => void;
  onRenamed: (handle: string) => void;
}) {
  const { principal } = useCurrentUser();
  const [value, setValue] = useState(handle);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<AgentRenamed | null>(null);
  const next = normHandle(value);
  const canRename = handleValid(value) && next !== handle && !loading;

  const rename = async () => {
    if (!canRename) return;
    setLoading(true);
    setError(null);
    try {
      const renamed = await renameAgent(roomName, handle, next, principal.trim() || null);
      if (!renamed.pending) onRenamed(renamed.handle);
      setDone(renamed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't rename the agent");
    } finally {
      setLoading(false);
    }
  };

  if (done) return <Renamed done={done} roomName={roomName} onClose={onClose} onRenamed={onRenamed} />;

  return (
    <form
      className="contents"
      onSubmit={(e) => {
        e.preventDefault();
        void rename();
      }}
    >
      <DialogHeader>
        <DialogTitle>Rename @{handle}</DialogTitle>
        <DialogDescription>
          Its notes and tasks move to the new name. The agent restarts to use it.
        </DialogDescription>
      </DialogHeader>
      <IdentityRow value={value} onChange={setValue} hint="The name people use to mention it." />
      {error && (
        <p role="alert" className="break-words text-label text-red">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <Button type="submit" disabled={!canRename}>
          {loading ? "Renaming…" : "Rename"}
        </Button>
      </DialogFooter>
    </form>
  );
}

/**
 * After asking: renamed at once when no machine runs it, or, when one does,
 * followed on that machine. Nothing changes until it's approved there, so the
 * title says renamed only once it is.
 */
function Renamed({
  done,
  roomName,
  onClose,
  onRenamed,
}: {
  done: AgentRenamed;
  roomName: string;
  onClose: () => void;
  onRenamed: (handle: string) => void;
}) {
  const { runners } = useRunners();
  const { job } = useRunnerJob(done.restart_runner, done.restart_job);
  const machine = runnerName(
    runners.find((r) => r.id === done.restart_runner),
    done.restart_runner,
  );
  const status = job?.status ?? "queued";
  // The hub renames it when the machine goes ahead; a restart can still fail after that.
  const applied = !done.pending || Boolean(job?.spec?.applied);
  const told = useRef(!done.pending);
  useEffect(() => {
    if (applied && !told.current) {
      told.current = true;
      onRenamed(done.handle);
    }
  }, [applied, done.handle, onRenamed]);

  const failed = status === "failed";
  const title = applied ? `Renamed to @${done.handle}` : failed ? "Not renamed" : `Rename @${done.was}`;
  const line = !done.pending
    ? "It isn't running on any of your machines. Restart it with the new name to use it."
    : failed && applied
      ? `Couldn't restart on ${machine}: ${job?.error ?? "no reason given"}. Restart it with the new name.`
      : failed
        ? `${job?.error ?? "No reason given."} @${done.was} is unchanged.`
        : status === "done"
          ? `Restarted on ${machine}.`
          : status === "running"
            ? `Restarting on ${machine}…`
            : `Waiting for approval on ${machine}. Nothing changes until then.`;
  const tasks = done.rows.length === 1 ? "1 task moved with it." : `${done.rows.length} tasks moved with it.`;
  return (
    <>
      <DialogHeader>
        <DialogTitle>{title}</DialogTitle>
        {applied && (
          <DialogDescription>
            We let {roomName} know.{done.rows.length > 0 && ` ${tasks}`}
          </DialogDescription>
        )}
      </DialogHeader>
      <p role={failed ? "alert" : "status"} className={failed ? "text-label text-red" : "text-label text-text"}>
        {line}
      </p>
      <DialogFooter>
        <Button onClick={onClose}>Done</Button>
      </DialogFooter>
    </>
  );
}
