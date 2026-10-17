// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
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
      onRenamed(renamed.handle);
      setDone(renamed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Couldn't rename the agent");
    } finally {
      setLoading(false);
    }
  };

  if (done) return <Renamed done={done} roomName={roomName} onClose={onClose} />;

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

/** After the rename: where it is being restarted under its new name, followed like a launch. */
function Renamed({ done, roomName, onClose }: { done: AgentRenamed; roomName: string; onClose: () => void }) {
  const { runners } = useRunners();
  const { job } = useRunnerJob(done.restart_runner, done.restart_job);
  const machine = runnerName(
    runners.find((r) => r.id === done.restart_runner),
    done.restart_runner,
  );
  const status = job?.status ?? "queued";
  const line = !done.restart_runner
    ? "It isn't running on any of your machines. Restart it with the new name to use it."
    : status === "done"
      ? `Restarted on ${machine}.`
      : status === "failed"
        ? `Couldn't restart on ${machine}: ${job?.error ?? "no reason given"}`
        : status === "waiting"
          ? `Waiting for approval on ${machine}.`
          : `Restarting on ${machine}…`;
  const tasks = done.rows.length === 1 ? "1 task moved with it." : `${done.rows.length} tasks moved with it.`;
  return (
    <>
      <DialogHeader>
        <DialogTitle>Renamed to @{done.handle}</DialogTitle>
        <DialogDescription>
          We let {roomName} know.{done.rows.length > 0 && ` ${tasks}`}
        </DialogDescription>
      </DialogHeader>
      <p role={status === "failed" ? "alert" : "status"} className={status === "failed" ? "text-label text-red" : "text-label text-text"}>
        {line}
      </p>
      <DialogFooter>
        <Button onClick={onClose}>Done</Button>
      </DialogFooter>
    </>
  );
}
