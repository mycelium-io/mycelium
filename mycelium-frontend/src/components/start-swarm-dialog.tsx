// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { startSwarm } from "@/lib/api";
import { launchable, useRunners } from "@/lib/runners";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { CopyField } from "@/components/ui/copy-field";
import { FolderField, FrameworkPicker, HerdrMissing } from "@/components/runner-fields";

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
/** The "Where" choice that keeps the members on the hub. */
const HUB = "hub";

/** The same swarm with the user's own agent CLI, run from the folder they work in. */
export function localCommand(task: string, room: string, size: number): string {
  const what = task.trim().replace(/["\\$`]/g, m => `\\${m}`) || "<task>";
  const n = size === DEFAULT_SIZE ? "" : ` -n ${size}`;
  return `mycelium swarm "${what}" --room ${room}${n}`;
}

/**
 * Start a swarm: a team of agents put on one task in this room.
 *
 * The members are workers the hub plays (`mycelium swarm --server`), or, when
 * a machine is connected with herdr, that machine's own agent CLIs in a herdr
 * workspace (`mycelium swarm`). Either way the task is filed on this room's
 * board, and on start the dialog opens its thread so the kickoff is the first
 * thing you see. A repository is for hub members only; the hub clones it
 * before anything else, so one it cannot reach is said here.
 */
export function StartSwarmDialog({ open, onClose, roomName, initialTask = "" }: Props) {
  const router = useRouter();
  const { principal } = useCurrentUser();
  const { connected } = useRunners();
  const [task, setTask] = useState(initialTask);
  const [size, setSize] = useState(DEFAULT_SIZE);
  const [repo, setRepo] = useState("");
  const [where, setWhere] = useState<string>(HUB);
  const [frameworkPick, setFrameworkPick] = useState<string | null>(null);
  const [folderPick, setFolderPick] = useState<string | null>(null);
  const [worktree, setWorktree] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  // A local team starts in herdr panes, so a machine without herdr is listed
  // but can't be started on.
  const machines = connected;
  const machine = machines.find(r => r.id === where) ?? null;
  const startable = machine ? launchable(machine) : [];
  const framework = startable.find(f => f.id === frameworkPick) ?? startable[0] ?? null;
  const folder = folderPick ?? machine?.roots[0] ?? "";

  const close = () => {
    setError(null);
    onClose();
  };

  const start = async () => {
    const what = task.trim();
    if (!what || starting) return;
    if (machine && !framework) return;
    setStarting(true);
    setError(null);
    try {
      const swarm = await startSwarm(roomName, {
        task: what,
        size,
        created_by: principal.trim() || undefined,
        ...(machine && framework
          ? {
              runner: machine.id,
              framework: framework.id,
              cwd: folder.trim() || undefined,
              worktree,
            }
          : { repo: repo.trim() || undefined }),
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

  const places = [
    { id: HUB, label: "On the hub" },
    ...machines.map(r => ({ id: r.id, label: `On ${r.label || r.id}` })),
  ];

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
      onClick={close}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="start-swarm-title"
        className="max-h-[calc(100vh-2rem)] w-[480px] max-w-[calc(100vw-2rem)] overflow-y-auto rounded-xl border border-border bg-elevated p-6 shadow-2xl"
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

        {machines.length > 0 && (
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <span id="swarm-where-label" className="text-micro font-medium text-muted-foreground">
              Where
            </span>
            <div role="radiogroup" aria-labelledby="swarm-where-label" className="flex flex-wrap gap-1">
              {places.map(p => (
                <button
                  key={p.id}
                  type="button"
                  role="radio"
                  aria-checked={where === p.id}
                  onClick={() => {
                    setWhere(p.id);
                    setFrameworkPick(null);
                    setFolderPick(null);
                    if (error) setError(null);
                  }}
                  className={`rounded-md border px-2.5 py-1 text-label transition-colors ${
                    where === p.id
                      ? "border-accent bg-accent-soft text-text"
                      : "border-border text-muted-foreground hover:border-border2 hover:text-text"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {machine ? (
          <div className="mt-4 space-y-4">
            {!machine.herdr && <HerdrMissing runner={machine} />}
            <FrameworkPicker runner={machine} value={framework?.id ?? null} onChange={setFrameworkPick} />
            <FolderField runner={machine} value={folder} onChange={setFolderPick} id="swarm-folder" />
            <label className="flex items-center gap-2 text-label text-text">
              <Checkbox checked={worktree} onCheckedChange={v => setWorktree(v === true)} />
              Give each agent its own git worktree
            </label>
            <p className="text-micro text-muted-foreground">
              The agents open side by side in a new herdr workspace on {machine.label || machine.id},
              where you can watch and type to them, each already set up as its own handle in this
              room.
            </p>
          </div>
        ) : (
          <>
            <label
              htmlFor="swarm-repo"
              className="mb-1.5 mt-4 block text-micro font-medium text-muted-foreground"
            >
              Repository <span className="font-normal">(optional)</span>
            </label>
            <input
              id="swarm-repo"
              value={repo}
              onChange={e => {
                setRepo(e.target.value);
                if (error) setError(null);
              }}
              onKeyDown={e => {
                if (e.key === "Enter") start();
              }}
              spellCheck={false}
              placeholder="https://github.com/your-org/your-repo"
              className="w-full rounded-lg border border-border bg-bg px-3 py-2 font-mono text-label text-text outline-none transition-colors placeholder:font-sans placeholder:text-muted-foreground hover:border-border2 focus:border-accent"
            />
            <p className="mt-1.5 text-micro text-muted-foreground">
              The hub clones it, and each agent works on its own branch of the clone. Leave it
              empty and they start with an empty one.
            </p>
          </>
        )}

        {machines.length === 0 && (
          <div className="mt-5 border-t border-border pt-4">
            <p className="text-label font-medium text-text">Or use the agents on your machine</p>
            <p className="mt-1 text-label text-muted-foreground">
              These agents run on your hub. To have your own coding agent do it instead, in
              the folder you&apos;re working in and with your uncommitted changes, run this
              there:
            </p>
            <CopyField value={localCommand(task, roomName, size)} className="mt-2 font-mono" />
            <p className="mt-2 text-micro text-muted-foreground">
              Or run <code className="font-mono text-accent">mycelium runner</code> on that
              machine (with herdr open) and start the team from here.
            </p>
          </div>
        )}

        {error && (
          <p role="alert" className="mt-3 break-words text-label text-red">
            {error}
          </p>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button onClick={start} disabled={!task.trim() || starting || (!!machine && !framework)}>
            {starting
              ? machine
                ? "Starting…"
                : repo.trim()
                  ? "Cloning…"
                  : "Starting…"
              : "Start swarm"}
          </Button>
        </div>
      </div>
    </div>
  );
}
