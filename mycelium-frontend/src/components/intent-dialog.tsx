// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useState } from "react";
import { CheckCheck, History, Loader2, Scale, Split, type LucideIcon } from "lucide-react";
import { createTask, sendRoomMessage } from "@/lib/api";
import { INTENTS, intentById, ready, type IntentId } from "@/lib/intents";
import { useRoomRevalidate, useRoomRoster } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { Kbd } from "@/components/ui/kbd";
import { Monogram } from "@/components/ui/monogram";

const ICONS: Record<IntentId, LucideIcon> = {
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
        const task = await createTask(roomName, { title: title.trim(), handle: me });
        thread = task.episode ?? null;
        if (!thread) throw new Error("The task was filed but has no thread to start it in.");
      }
      await sendRoomMessage(roomName, {
        sender_handle: me,
        content: intent.summon(picks, note || (needsTitle ? title : "")),
        episode: thread,
      });
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
          {INTENTS.map(i => {
            const Icon = ICONS[i.id];
            const on = i.id === intentId;
            return (
              <button
                key={i.id}
                type="button"
                aria-pressed={on}
                onClick={() => setIntentId(i.id)}
                className={`flex flex-1 items-center justify-center gap-1.5 border-r border-border px-2 py-2 text-micro last:border-r-0 transition-colors ${
                  on ? "bg-bg text-text" : "text-muted-foreground hover:bg-hairline hover:text-text"
                }`}
              >
                <Icon className="size-3.5" />
                {i.label}
              </button>
            );
          })}
        </div>

        <div className="space-y-3 px-4 py-3">
          <p className="text-label text-muted-foreground">{intent.when}</p>

          {needsTitle && (
            <Field label="The task">
              <input
                autoFocus
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="Fix the flaky login test"
                className="h-8 w-full rounded bg-hairline px-2 text-label text-text placeholder:text-faint focus:bg-bg focus:outline-none focus:ring-1 focus:ring-border"
              />
            </Field>
          )}

          {intent.roles.map(role => (
            <Field key={role.id} label={role.label}>
              <AgentChips
                agents={workers}
                selected={roles[role.id] ? [roles[role.id]] : []}
                disabled={Object.entries(roles).filter(([k]) => k !== role.id).map(([, v]) => v)}
                onPick={h => setRoles(r => ({ ...r, [role.id]: r[role.id] === h ? "" : h }))}
              />
            </Field>
          ))}

          {intent.minGroup > 0 && (
            <Field label={`Which agents (${intent.minGroup} or more)`}>
              <AgentChips agents={workers} selected={group} onPick={toggleGroup} />
            </Field>
          )}

          <Field label="Anything to add">
            <input
              value={note}
              onChange={e => setNote(e.target.value)}
              placeholder={intent.id === "settle" ? "What they disagree about" : "Optional"}
              className="h-8 w-full rounded bg-hairline px-2 text-label text-text placeholder:text-faint focus:bg-bg focus:outline-none focus:ring-1 focus:ring-border"
            />
          </Field>

          <p className="text-micro text-faint">{intent.then}</p>
          {error && <p role="alert" className="text-micro text-red">{error}</p>}
        </div>

        <div className="flex items-center gap-3 border-t border-border px-4 py-2">
          {/* The summon it sends: learnable, never required. */}
          <code className="min-w-0 flex-1 truncate font-mono text-[11px] text-faint" title={preview}>
            {preview}
          </code>
          <span className="flex items-center gap-1 text-micro text-faint">
            <Kbd size="xs" tone="muted">⌘↵</Kbd>
          </span>
          <button
            type="button"
            disabled={!canStart}
            onClick={() => void start()}
            className="flex h-7 items-center gap-1.5 rounded px-2.5 text-label text-accent transition-colors hover:bg-accent-soft disabled:cursor-not-allowed disabled:text-faint disabled:hover:bg-transparent"
          >
            {busy && <Loader2 className="size-3.5 animate-spin" />}
            Start
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-micro font-medium text-faint">{label}</div>
      {children}
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
