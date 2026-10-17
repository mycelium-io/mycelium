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
          Its notes, its tasks and its place in {roomName} move to the new name. The machine running it restarts
          it under that name, asking there first, and it catches up from the room.
        </DialogDescription>
      </DialogHeader>
      <IdentityRow value={value} onChange={setValue} hint="Its new handle: how the room addresses it from now on." />
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
    ? `No connected machine is running it, so restart it yourself with its new name before it answers to @${done.handle}.`
    : status === "done"
      ? `@${done.handle} started again on ${machine} and is catching up from the room.`
      : status === "failed"
        ? `${machine} couldn't restart it: ${job?.error ?? "it didn't say why"}. It's still @${done.handle} in ${roomName}; restart it there with its new name.`
        : status === "waiting"
          ? `Waiting for someone on ${machine} to approve restarting it as @${done.handle}.`
          : `Asking ${machine} to restart it as @${done.handle}.`;
  return (
    <>
      <DialogHeader>
        <DialogTitle>
          @{done.was} is @{done.handle}
        </DialogTitle>
        <DialogDescription>
          {roomName} was told.
          {done.rows.length > 0 &&
            ` ${done.rows.length === 1 ? "1 task now names it" : `${done.rows.length} tasks now name it`}.`}
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
