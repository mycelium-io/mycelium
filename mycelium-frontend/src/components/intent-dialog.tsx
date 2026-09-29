// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo, useState } from "react";
import {
  Check,
  CheckCheck,
  ChevronDown,
  History,
  Loader2,
  Scale,
  Split,
  SquarePlus,
  X,
  type LucideIcon,
} from "lucide-react";
import TextareaAutosize from "react-textarea-autosize";
import { createTask, sendRoomMessage } from "@/lib/api";
import { INTENTS, intentById, ready, type IntentId } from "@/lib/intents";
import { useRoomRevalidate, useRoomRoster } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { Kbd } from "@/components/ui/kbd";
import { Monogram } from "@/components/ui/monogram";

const FIELD =
  "w-full rounded-md border border-border bg-bg px-2.5 py-1.5 text-label text-text placeholder:text-faint focus:border-accent/60 focus:outline-none focus:ring-1 focus:ring-accent/30";

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
  const { agents, presence } = useRoomRoster(roomName);
  // Engines do the coordinating; the picks are the agents doing the work.
  const workers = useMemo(() => agents.filter(a => a.adapter !== "engine").map(a => a.handle), [agents]);
  const active = useMemo(() => new Set(presence.keys()), [presence]);

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

  // What you wrote carries across tabs; who you picked doesn't, since each
  // tab's picks mean something different.
  const switchTo = (id: IntentId) => {
    if (id === intentId) return;
    setIntentId(id);
    setRoles({});
    setGroup([]);
    setAssignee("");
    setError(null);
  };

  const toggleGroup = (h: string) =>
    setGroup(g => (g.includes(h) ? g.filter(x => x !== h) : [...g, h]));

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center p-6 pt-[12vh]">
      <div className="absolute inset-0 bg-black/30 backdrop-blur-[2px] motion-safe:animate-in motion-safe:fade-in-0" onClick={onClose} aria-hidden />
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
                onClick={() => switchTo(i.id)}
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

        {/* What it is: plain labeled fields. */}
        <div className="space-y-3 px-4 py-3">
          {needsTitle && (
            <label className="block">
              <span className="mb-1 block text-micro text-muted-foreground">Title</span>
              <input
                autoFocus
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="e.g. Fix the flaky login test"
                className={FIELD}
              />
            </label>
          )}
          <label className="block">
            <span className="mb-1 block text-micro text-muted-foreground">
              {intent.id === "settle" ? "What they disagree about" : "Details"}{" "}
              <span className="text-faint">(optional)</span>
            </span>
            <TextareaAutosize
              autoFocus={!needsTitle}
              value={note}
              onChange={e => setNote(e.target.value)}
              minRows={2}
              maxRows={6}
              className={`${FIELD} resize-none leading-relaxed`}
            />
          </label>
        </div>

        {/* Who: one picker per role, labeled like the fields above. */}
        <div className="space-y-3 px-4 pb-3">
          {plainTask && (
            <Row label="For" hint="optional">
              <AgentPicker
                key={`${intent.id}-for`}
                agents={workers}
                active={active}
                placeholder="Choose one agent, or leave it for anyone"
                selected={assignee ? [assignee] : []}
                onPick={h => setAssignee(a => (a === h ? "" : h))}
              />
            </Row>
          )}
          {intent.roles.map(role => (
            <Row key={role.id} label={role.label}>
              <AgentPicker
                key={`${intent.id}-${role.id}`}
                agents={workers}
                active={active}
                placeholder="Choose one agent"
                selected={roles[role.id] ? [roles[role.id]] : []}
                disabled={Object.entries(roles).filter(([k]) => k !== role.id).map(([, v]) => v)}
                onPick={h => setRoles(r => ({ ...r, [role.id]: r[role.id] === h ? "" : h }))}
              />
            </Row>
          ))}
          {intent.minGroup > 0 && (
            <Row label="Agents" hint={`pick ${intent.minGroup} or more`}>
              <AgentPicker
                key={`${intent.id}-group`}
                multiple
                agents={workers}
                active={active}
                placeholder={`Choose ${intent.minGroup} or more agents`}
                selected={group}
                onPick={toggleGroup}
              />
            </Row>
          )}
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
    <div>
      <div className="mb-1 text-micro text-muted-foreground">
        {label} {hint && <span className="text-faint">({hint})</span>}
      </div>
      <div className="text-label text-muted-foreground">{children}</div>
    </div>
  );
}

/**
 * Who, picked from a list that stays one line tall until it's opened. A room
 * can hold dozens of agents, so the list searches and scrolls, and the ones
 * present right now come first.
 */
function AgentPicker({
  agents,
  active,
  selected,
  multiple = false,
  disabled = [],
  placeholder,
  onPick,
}: {
  agents: string[];
  active: Set<string>;
  selected: string[];
  multiple?: boolean;
  disabled?: string[];
  placeholder: string;
  onPick: (handle: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return agents
      .filter(h => !q || h.toLowerCase().includes(q))
      .sort((a, b) => Number(active.has(b.toLowerCase())) - Number(active.has(a.toLowerCase())) || a.localeCompare(b));
  }, [agents, active, query]);

  if (agents.length === 0) {
    return <p className="text-micro text-muted-foreground">No agents in this room yet. Add one from Members.</p>;
  }

  const pick = (h: string) => {
    onPick(h);
    if (!multiple) {
      setOpen(false);
      setQuery("");
    }
  };

  return (
    <div>
      <div
        onClick={() => setOpen(o => !o)}
        className={`flex min-h-8 cursor-pointer flex-wrap items-center gap-1 rounded-md border bg-bg px-1.5 py-1 transition-colors ${
          open ? "border-accent/60 ring-1 ring-accent/30" : "border-border hover:border-muted-foreground/40"
        }`}
      >
        {!multiple &&
          selected.map(h => (
            <span key={h} className="flex h-6 items-center gap-1.5 px-1 text-label text-text">
              <Monogram handle={h} className="size-4 text-[7px]" />
              <span className="font-mono">{h}</span>
            </span>
          ))}
        {multiple && selected.map(h => (
          <span key={h} className="flex h-6 items-center gap-1.5 rounded bg-hairline pl-1 pr-1.5 text-label text-text">
            <Monogram handle={h} className="size-4 text-[7px]" />
            <span className="font-mono">{h}</span>
            <button
              type="button"
              aria-label={`Remove ${h}`}
              onClick={e => {
                e.stopPropagation();
                onPick(h);
              }}
              className="text-faint hover:text-text"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <button
          type="button"
          aria-expanded={open}
          className="flex h-6 flex-1 items-center justify-between gap-2 px-1 text-left text-label text-faint"
        >
          <span>{selected.length === 0 ? placeholder : multiple ? "Add more" : ""}</span>
          <ChevronDown className={`size-3.5 transition-transform ${open ? "rotate-180" : ""}`} />
        </button>
      </div>

      {open && (
        <div className="mt-1 overflow-hidden rounded-md border border-border bg-bg">
          <input
            autoFocus
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Escape") {
                e.stopPropagation();
                setOpen(false);
              }
              if (e.key === "Enter" && !e.metaKey && !e.ctrlKey && shown[0]) {
                e.preventDefault();
                pick(shown[0]);
              }
            }}
            placeholder={`Search ${agents.length} agents`}
            className="h-8 w-full border-b border-border bg-transparent px-2.5 text-label text-text placeholder:text-faint focus:outline-none"
          />
          <ul className="max-h-44 overflow-y-auto py-1">
            {shown.map(h => {
              const on = selected.includes(h);
              const off = disabled.includes(h);
              const live = active.has(h.toLowerCase());
              return (
                <li key={h}>
                  <button
                    type="button"
                    disabled={off}
                    onClick={() => pick(h)}
                    className="flex h-7 w-full items-center gap-2 px-2.5 text-left text-label text-muted-foreground transition-colors hover:bg-hairline hover:text-text disabled:opacity-40 disabled:hover:bg-transparent"
                  >
                    {/* A box for pick-several, a circle for pick-one. */}
                    <span
                      aria-hidden
                      className={`flex size-3.5 flex-shrink-0 items-center justify-center border transition-colors ${
                        multiple ? "rounded-[3px]" : "rounded-full"
                      } ${on ? "border-accent bg-accent" : "border-muted-foreground/50"}`}
                    >
                      {on &&
                        (multiple ? (
                          <Check className="size-2.5 text-bg" strokeWidth={3} />
                        ) : (
                          <span className="size-1.5 rounded-full bg-bg" />
                        ))}
                    </span>
                    <Monogram handle={h} className="size-4 text-[7px]" />
                    <span className="min-w-0 flex-1 truncate font-mono">{h}</span>
                    {live && <span className="text-micro text-green">here</span>}
                  </button>
                </li>
              );
            })}
            {shown.length === 0 && <li className="px-2.5 py-1.5 text-micro text-faint">No agent matches.</li>}
          </ul>
        </div>
      )}
    </div>
  );
}
