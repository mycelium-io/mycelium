// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { startSwarm } from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import { CopyField } from "@/components/ui/copy-field";

interface Props {
  open: boolean;
  onClose: () => void;
  /** The room the team works in. */
  roomName: string;
  /** What was already typed where the dialog was opened from. */
  initialTask?: string;
}

/** Team sizes offered. The hub allows up to 8; past five the kickoff alone is long. */
const SIZES = [2, 3, 4, 5];
const DEFAULT_SIZE = 3;

/** The same swarm, run from a repo with agents that can work in it. */
export function localCommand(task: string, room: string, size: number): string {
  const what = task.trim().replace(/["\\$`]/g, m => `\\${m}`) || "<task>";
  const n = size === DEFAULT_SIZE ? "" : ` -n ${size}`;
  return `mycelium swarm "${what}" --room ${room}${n}`;
}

/**
 * Start a swarm: a team of workers the hub plays, put on one task in this room.
 *
 * One field and one choice, like `mycelium swarm "<task>" --server --room <room>`:
 * the task is filed on this room's board, and on start the dialog opens its
 * thread so the kickoff is the first thing you see.
 */
export function StartSwarmDialog({ open, onClose, roomName, initialTask = "" }: Props) {
  const router = useRouter();
  const { principal } = useCurrentUser();
  const [task, setTask] = useState(initialTask);
  const [size, setSize] = useState(DEFAULT_SIZE);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const close = () => {
    setError(null);
    onClose();
  };

  const start = async () => {
    const what = task.trim();
    if (!what || starting) return;
    setStarting(true);
    setError(null);
    try {
      const swarm = await startSwarm({
        task: what,
        size,
        room: roomName,
        created_by: principal.trim() || undefined,
      });
      const thread = swarm.episode.split(":").pop();
      setTask("");
      onClose();
      router.push(
        `/room/${encodeURIComponent(swarm.room)}${thread ? `?focus=episode:${thread}` : ""}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the swarm");
    } finally {
      setStarting(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={close}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="start-swarm-title"
        className="w-[480px] max-w-[calc(100vw-2rem)] rounded-xl border border-border bg-elevated p-6 shadow-2xl"
        onClick={e => e.stopPropagation()}
      >
        <h2 id="start-swarm-title" className="mb-1 text-ui font-semibold text-text">
          Start a swarm
        </h2>
        <p className="mb-4 text-label text-muted-foreground">
          {size} agents split this task between them, each do a part, and check each
          other&apos;s work. You watch it happen in the task&apos;s thread.
        </p>

        <label htmlFor="swarm-task" className="mb-1.5 block text-micro font-medium text-muted-foreground">
          What should the team work on?
        </label>
        <textarea
          id="swarm-task"
          value={task}
          onChange={e => {
            setTask(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={e => {
            if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) start();
          }}
          rows={3}
          maxLength={500}
          placeholder="Write release notes for the 2.0 launch"
          autoFocus
          className="w-full resize-none rounded-lg border border-border bg-bg px-3 py-2 text-label text-text outline-none transition-colors placeholder:text-muted-foreground hover:border-border2 focus:border-accent"
        />

        <div className="mt-4 flex items-center gap-3">
          <span id="swarm-size-label" className="text-micro font-medium text-muted-foreground">
            Agents
          </span>
          <div role="radiogroup" aria-labelledby="swarm-size-label" className="flex gap-1">
            {SIZES.map(n => (
              <button
                key={n}
                type="button"
                role="radio"
                aria-checked={size === n}
                onClick={() => setSize(n)}
                className={`size-8 rounded-md border text-label tabular transition-colors ${
                  size === n
                    ? "border-accent bg-accent-soft text-text"
                    : "border-border text-muted-foreground hover:border-border2 hover:text-text"
                }`}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        <div className="mt-5 border-t border-border pt-4">
          <p className="text-label font-medium text-text">These agents can&apos;t see your code</p>
          <p className="mt-1 text-label text-muted-foreground">
            They&apos;re good for work that ends in writing: a plan, a comparison, a draft. To
            have agents work in a repo, run this from the repo instead. It opens Claude Code
            (or Codex, or Pi) in herdr, one per agent, working in this room:
          </p>
          <CopyField value={localCommand(task, roomName, size)} className="mt-2 font-mono" />
        </div>

        {error && (
          <p role="alert" className="mt-3 break-words text-label text-red">
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button onClick={start} disabled={!task.trim() || starting}>
            {starting ? "Starting…" : "Start swarm"}
          </Button>
        </div>
      </div>
    </div>
  );
}
