// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { deleteMemory, stopRunnerAgent } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** What the dialog needs to know about the agent being unregistered. */
export interface UnregisterTarget {
  handle: string;
  /** The runner that started it, when that runner is one of your machines. */
  runner?: { id: string; name: string } | null;
}

interface Props {
  roomName: string;
  target: UnregisterTarget | null;
  onClose: () => void;
  onUnregistered: () => void;
}

/**
 * The app's `mycelium agent rm`: deletes the `agents/<handle>` manifest and
 * keeps its notes and logs, so the agent can be registered again. An agent one
 * of your machines started can be stopped there too, since a session left
 * running would go on acting as a handle the room no longer lists.
 */
export function UnregisterAgentDialog({ roomName, target, onClose, onUnregistered }: Props) {
  const [loading, setLoading] = useState(false);
  return (
    <Dialog
      open={target !== null}
      onOpenChange={(next) => {
        if (!next && !loading) onClose();
      }}
    >
      <DialogContent>
        {/* Mounted per opening, so each one starts from its defaults. */}
        {target && (
          <ConfirmUnregister
            key={target.handle}
            roomName={roomName}
            target={target}
            loading={loading}
            setLoading={setLoading}
            onClose={onClose}
            onUnregistered={onUnregistered}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ConfirmUnregister({
  roomName,
  target,
  loading,
  setLoading,
  onClose,
  onUnregistered,
}: {
  roomName: string;
  target: UnregisterTarget;
  loading: boolean;
  setLoading: (loading: boolean) => void;
  onClose: () => void;
  onUnregistered: () => void;
}) {
  const { handle, runner } = target;
  const [stop, setStop] = useState(Boolean(runner));
  const [error, setError] = useState<string | null>(null);

  const handleUnregister = async () => {
    if (loading) return;
    setLoading(true);
    setError(null);
    try {
      // Stop first: the stop job names the agent, and a failure here leaves
      // the registration in place to try again.
      if (stop && runner) await stopRunnerAgent(runner.id, roomName, handle);
      await deleteMemory(roomName, `agents/${handle}`);
      onUnregistered();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to unregister the agent");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Unregister @{handle}?</DialogTitle>
        <DialogDescription>
          This removes @{handle} from {roomName}. Its notes and logs stay, so it can be registered again.
        </DialogDescription>
      </DialogHeader>
      {runner && (
        <label className="flex items-center gap-2 text-label text-text">
          <Checkbox checked={stop} onCheckedChange={(v) => setStop(Boolean(v))} disabled={loading} />
          Also stop it on {runner.name}
        </label>
      )}
      {error && (
        <p role="alert" className="text-label text-red break-words">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant="destructive" onClick={() => void handleUnregister()} disabled={loading} autoFocus>
          {loading ? "Unregistering…" : "Unregister"}
        </Button>
      </DialogFooter>
    </>
  );
}
