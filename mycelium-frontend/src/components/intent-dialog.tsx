// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useState } from "react";
import { CheckCheck, History, Loader2, Scale, Split, SquarePlus, type LucideIcon } from "lucide-react";
import TextareaAutosize from "react-textarea-autosize";
import { createTask, sendRoomMessage } from "@/lib/api";
import { INTENTS, intentById, ready, type IntentId } from "@/lib/intents";
import { useRoomRevalidate, useRoomRoster } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { Kbd } from "@/components/ui/kbd";
import { Monogram } from "@/components/ui/monogram";

const ICONS: Record<IntentId, LucideIcon> = {
  task: SquarePlus,
  review: CheckCheck,
  split: Split,
  settle: Scale,
  "catch-up": History,
};

/**
 * Ask the room for something by what you want, not by which engine does it.
 *
 * Opened on a task (its thread is where it runs) or from an empty room (then
 * it files the task first). Picking agents and saying what you want is all it
 * asks; the summon it sends is shown, so the grammar is learnable but never
 * required.
 */
export function IntentDialog({
  roomName,
  episode = null,
  initial = "review",
  onClose,
  onStarted,
}: {
  roomName: string;
  /** The task's thread; null files a new task from the title asked for. */
  episode?: string | null;
  initial?: IntentId;
  onClose: () => void;
  onStarted?: (episode: string) => void;
}) {
  const [intentId, setIntentId] = useState<IntentId>(initial);
  const [roles, setRoles] = useState<Record<string, string>>({});
  const [group, setGroup] = useState<string[]>([]);
  const [note, setNote] = useState("");
  const [title, setTitle] = useState("");
  const [assignee, setAssignee] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { principal } = useCurrentUser();
  const revalidate = useRoomRevalidate(roomName);
  const { agents } = useRoomRoster(roomName);
  // Engines do the coordinating; the picks are the agents doing the work.
  const workers = useMemo(() => agents.filter(a => a.adapter !== "engine").map(a => a.handle), [agents]);

  const intent = intentById(intentId);
  const picks = { roles, group };
  const needsTitle = episode === null;
  // A plain task only makes sense where there isn't one yet.
  const offered = INTENTS.filter(i => i.id !== "task" || needsTitle);
  const plainTask = intent.id === "task";
  const canStart = ready(intent, picks) && (!needsTitle || title.trim().length > 0) && !busy;
  const preview = intent.summon(
    {
      roles: Object.fromEntries(intent.roles.map(r => [r.id, roles[r.id] ?? r.id])),
      group: group.length ? group : ["…"],
    },
    note || (needsTitle ? title : ""),
  );

  const start = async () => {
    if (!canStart) return;
    setBusy(true);
    setError(null);
    const me = principal.trim() || "user";
    try {
      let thread = episode;
      if (!thread) {
        const task = await createTask(roomName, {
          title: title.trim(),
          handle: me,
          ...(plainTask && assignee ? { assignee } : {}),
        });
        thread = task.episode ?? null;
        if (!thread) throw new Error("The task was filed but has no thread to start it in.");
      }
      // A plain task starts nothing; a note is its thread's first message.
      const content = plainTask ? note.trim() : intent.summon(picks, note || (needsTitle ? title : ""));
      if (content) {
        await sendRoomMessage(roomName, { sender_handle: me, content, episode: thread });
      }
      revalidate();
      onStarted?.(thread);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't start it");
      setBusy(false);
    }
  };

  const toggleGroup = (h: string) =>
    setGroup(g => (g.includes(h) ? g.filter(x => x !== h) : [...g, h]));

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-6 pt-[12vh]">
      <div className="absolute inset-0 bg-black/30" onClick={onClose} aria-hidden />
      <div
        role="dialog"
        aria-modal="true"
        aria-label={intent.label}
        onKeyDown={e => {
          if (e.key === "Escape") onClose();
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) void start();
        }}
        className="relative w-full max-w-lg overflow-hidden rounded-lg border border-border bg-elevated shadow-2xl motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95"
      >
        {/* What you want, as four plain choices. */}
        <div className="flex items-stretch border-b border-border">
          {offered.map(i => {
            const Icon = ICONS[i.id];
            const on = i.id === intentId;
            return (
              <button
                key={i.id}
                type="button"
                aria-pressed={on}
                title={i.when}
                onClick={() => setIntentId(i.id)}
                className={`flex min-w-0 flex-1 items-center justify-center gap-1.5 whitespace-nowrap border-r border-border px-2 py-2 text-micro last:border-r-0 transition-colors ${
                  on ? "bg-bg text-text" : "text-muted-foreground hover:bg-hairline hover:text-text"
                }`}
              >
                <Icon className="size-3.5" />
                {i.label}
              </button>
            );
          })}
        </div>

        {/* What it is: a title and details, written like a new issue. */}
        <div className="px-4 pt-3">
          {needsTitle && (
            <input
              autoFocus
              value={title}
              onChange={e => setTitle(e.target.value)}
              aria-label="Task title"
              placeholder="Task title"
              className="w-full bg-transparent text-[15px] font-medium text-text placeholder:text-faint focus:outline-none"
            />
          )}
          <TextareaAutosize
            autoFocus={!needsTitle}
            value={note}
            onChange={e => setNote(e.target.value)}
            minRows={2}
            maxRows={6}
            aria-label="Details"
            placeholder={
              intent.id === "settle"
                ? "What do they disagree about?"
                : plainTask
                  ? "Add details (optional)"
                  : "Anything they should know (optional)"
            }
            className="mt-1.5 w-full resize-none bg-transparent text-label leading-relaxed text-text placeholder:text-faint focus:outline-none"
          />
        </div>

        {/* Who: one row per pick, labeled on the left. */}
        <div className="space-y-1 border-t border-border px-4 py-2.5">
          {plainTask && (
            <Row label="For">
              <AgentChips
                agents={workers}
                selected={assignee ? [assignee] : []}
                onPick={h => setAssignee(a => (a === h ? "" : h))}
              />
            </Row>
          )}
          {intent.roles.map(role => (
            <Row key={role.id} label={role.label}>
              <AgentChips
                agents={workers}
                selected={roles[role.id] ? [roles[role.id]] : []}
                disabled={Object.entries(roles).filter(([k]) => k !== role.id).map(([, v]) => v)}
                onPick={h => setRoles(r => ({ ...r, [role.id]: r[role.id] === h ? "" : h }))}
              />
            </Row>
          ))}
          {intent.minGroup > 0 && (
            <Row label="Agents" hint={`${intent.minGroup} or more`}>
              <AgentChips agents={workers} selected={group} onPick={toggleGroup} />
            </Row>
          )}
          {intent.id === "catch-up" && <Row label="Who">The synthesizer</Row>}
          <p className="pt-1 text-micro text-faint">{intent.then}</p>
          {error && <p role="alert" className="text-micro text-red">{error}</p>}
        </div>

        <div className="flex items-center gap-3 border-t border-border px-4 py-2">
          {/* The summon it sends: learnable, never required. */}
          <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-faint" title={preview || undefined}>
            {preview}
          </code>
          <span className="flex items-center gap-1 text-micro text-faint">
            <Kbd size="xs" tone="muted">⌘↵</Kbd>
          </span>
          <button
            type="button"
            disabled={!canStart}
            onClick={() => void start()}
            className="flex h-7 items-center gap-1.5 rounded-md bg-accent px-3 text-label font-medium text-bg transition-opacity hover:opacity-90 disabled:cursor-not-allowed disabled:bg-hairline disabled:text-faint disabled:hover:opacity-100"
          >
            {busy && <Loader2 className="size-3.5 animate-spin" />}
            {plainTask ? "File it" : "Start"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3">
      <div className="w-20 flex-shrink-0 pt-1.5 text-micro text-muted-foreground">
        {label}
        {hint && <span className="block text-faint">{hint}</span>}
      </div>
      <div className="min-w-0 flex-1 pt-0.5 text-label text-muted-foreground">{children}</div>
    </div>
  );
}

function AgentChips({
  agents,
  selected,
  disabled = [],
  onPick,
}: {
  agents: string[];
  selected: string[];
  disabled?: string[];
  onPick: (handle: string) => void;
}) {
  if (agents.length === 0) {
    return <p className="text-micro text-muted-foreground">No agents in this room yet. Add one from Members.</p>;
  }
  return (
    <div className="flex flex-wrap gap-1">
      {agents.map(h => {
        const on = selected.includes(h);
        const off = disabled.includes(h);
        return (
          <button
            key={h}
            type="button"
            aria-pressed={on}
            disabled={off}
            onClick={() => onPick(h)}
            className={`flex h-7 items-center gap-1.5 rounded px-1.5 text-label transition-colors disabled:opacity-40 ${
              on ? "bg-accent-soft text-text ring-1 ring-accent/40" : "text-muted-foreground hover:bg-hairline hover:text-text"
            }`}
          >
            <Monogram handle={h} className="size-4 text-[7px]" />
            <span className="font-mono">{h}</span>
          </button>
        );
      })}
    </div>
  );
}
