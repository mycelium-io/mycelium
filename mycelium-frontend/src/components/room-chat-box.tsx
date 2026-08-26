// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import TextareaAutosize from "react-textarea-autosize";
import { sendRoomMessage, type Memory } from "@/lib/api";
import { SendPlaneIcon } from "@/components/send-plane-icon";
import { useRoomMemories, useRoomRoster, useRoomSkills } from "@/lib/room-data";
import { useKeyAction } from "@/components/keymap-provider";
import { useCurrentUser } from "@/components/current-user";
import { Kbd } from "@/components/ui/kbd";

interface Props {
  roomName: string;
  /** Fired after a successful POST so the parent can refresh the event stream. */
  onSent?: () => void;
  className?: string;
  /**
   * The thread this composer writes into. Without one it writes to the room —
   * the same composer either way, since a thread is a tag over the room's own
   * channel and not a second place to type.
   */
  episode?: string | null;
  /** What to call that thread in the placeholder, e.g. a task's title. */
  threadLabel?: string | null;
}

// Three sigils, three vocabularies, one composer (#618, #619):
//   @   → agents        → inserts `@handle`
//   [[  → memories      → inserts `[[key]]` (resolves to myc://, clickable in chat)
//   /   → skills        → inserts `/name`
// Each detects an in-flight token by the cursor's prefix, offers a candidate
// popover, and inserts on select — the same machinery the `@` mention always had.
type TriggerKind = "agent" | "memory" | "skill";

interface Trigger {
  kind: TriggerKind;
  /** Index where the sigil begins (`@`, `[[`, or `/`) — the start of the replaced span. */
  start: number;
  /** Cursor position (the end of the replaced span). */
  end: number;
  query: string;
}

/** A normalized popover row, so rendering is uniform across the three sigils. */
interface Candidate {
  /** Stable React key. */
  id: string;
  /** The full token written into the message on select, e.g. `@bob`, `[[decisions/db]]`, `/summarize`. */
  insert: string;
  /** Monospace accent label (the token itself). */
  primary: string;
  /** Dim qualifier (adapter, "memory", "skill"). */
  secondary: string;
  /** Optional trailing description. */
  tertiary?: string;
}

/** Detect an in-flight trigger from the cursor's prefix. Order matters: `[[`
 *  is checked before `/` and `@` since a memory key can itself contain slashes. */
function detectTrigger(prefix: string, cursor: number): Trigger | null {
  const mem = prefix.match(/\[\[([^\]\n]*)$/);
  if (mem) {
    return { kind: "memory", start: cursor - mem[1].length - 2, end: cursor, query: mem[1] };
  }
  const agent = prefix.match(/(?:^|\s)@([a-z0-9._-]*)$/i);
  if (agent) {
    return { kind: "agent", start: cursor - agent[1].length - 1, end: cursor, query: agent[1].toLowerCase() };
  }
  const skill = prefix.match(/(?:^|\s)\/([a-z0-9._-]*)$/i);
  if (skill) {
    return { kind: "skill", start: cursor - skill[1].length - 1, end: cursor, query: skill[1].toLowerCase() };
  }
  return null;
}

function memoryKey(m: Memory): string {
  return m.key;
}

export function RoomChatBox({ roomName, onSent, className, episode = null, threadLabel = null }: Props) {
  const [content, setContent] = useState("");
  // A human message is sent as the acting-as principal — the single source of
  // "who am I" (the ActingAsPicker), not a per-composer handle. Anonymous falls
  // back to "user" so the room still has a sender to attribute the message to.
  const { principal } = useCurrentUser();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trigger, setTrigger] = useState<Trigger | null>(null);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // `@` reaches everyone in the room, off the same roster the Members rail
  // renders; `[[` reads the room's memory keys and `/` its skills. All three
  // are shared reads — opening a room fetches each of them once, however many
  // panels are looking.
  const { agents, people } = useRoomRoster(roomName);
  const { memories } = useRoomMemories(roomName);
  const { skills } = useRoomSkills(roomName);

  // The composer is a keybind target. Focus lands on the next frame because the
  // same keypress may be switching the channel pane back into view, and a
  // hidden textarea can't take focus.
  useKeyAction("focus.chat", () => {
    requestAnimationFrame(() => inputRef.current?.focus());
  });

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = e.target.value;
    setContent(next);
    const cursor = e.target.selectionStart ?? next.length;
    const found = detectTrigger(next.slice(0, cursor), cursor);
    setTrigger(found);
    if (found) setHighlight(0);
  };

  // Agents first, then people — the roster's order, labelled for the popover.
  const mentionRoster = useMemo(
    () => [
      ...agents.map((a) => ({
        handle: a.handle,
        secondary: a.adapter === "engine" && a.kind ? `engine · ${a.kind}` : a.adapter,
        tertiary: a.description as string | undefined,
      })),
      ...people.map((p) => ({
        handle: p.handle,
        secondary: p.you ? "you" : p.presence?.kind === "slim" ? "person · here" : "person",
        tertiary: undefined as string | undefined,
      })),
    ],
    [agents, people],
  );

  const candidates = useMemo<Candidate[]>(() => {
    if (trigger === null) return [];
    if (trigger.kind === "agent") {
      const pool = trigger.query
        ? mentionRoster.filter((r) => r.handle.toLowerCase().startsWith(trigger.query))
        : mentionRoster;
      return pool.slice(0, 8).map((r) => ({
        id: r.handle,
        insert: `@${r.handle}`,
        primary: `@${r.handle}`,
        secondary: r.secondary,
        tertiary: r.tertiary,
      }));
    }
    if (trigger.kind === "memory") {
      const q = trigger.query.toLowerCase();
      const pool = q
        ? memories.filter((m) => memoryKey(m).toLowerCase().includes(q))
        : memories;
      return pool.slice(0, 6).map((m) => ({
        id: memoryKey(m),
        insert: `[[${memoryKey(m)}]]`,
        primary: `[[${memoryKey(m)}]]`,
        secondary: "memory",
        tertiary: `v${m.version} · ${m.created_by}`,
      }));
    }
    // skill
    const q = trigger.query;
    const pool = q ? skills.filter((s) => s.name.toLowerCase().startsWith(q)) : skills;
    return pool.slice(0, 6).map((s) => ({
      id: s.name,
      insert: `/${s.name}`,
      primary: `/${s.name}`,
      secondary: "skill",
      tertiary: s.description || undefined,
    }));
  }, [mentionRoster, memories, skills, trigger]);

  const accept = useCallback(
    (candidate: Candidate) => {
      if (trigger === null) return;
      const before = content.slice(0, trigger.start);
      const after = content.slice(trigger.end);
      const insertion = `${candidate.insert} `;
      const next = `${before}${insertion}${after}`;
      setContent(next);
      setTrigger(null);
      // Restore the cursor after the inserted token.
      requestAnimationFrame(() => {
        const node = inputRef.current;
        if (!node) return;
        const pos = before.length + insertion.length;
        node.focus();
        node.setSelectionRange(pos, pos);
      });
    },
    [content, trigger],
  );

  const submit = useCallback(async () => {
    const body = content.trim();
    if (!body || sending) return;
    const handle = principal.trim() || "user";
    setSending(true);
    setError(null);
    try {
      await sendRoomMessage(roomName, { sender_handle: handle, content: body, episode });
      setContent("");
      setTrigger(null);
      onSent?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
      // The textarea is disabled while sending; it re-enables on the next
      // render, so refocus after that commit lands to keep the user typing.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [content, episode, onSent, roomName, principal, sending]);

  // Where this lands is the one thing the composer must never be coy about: the
  // same box writes to the room and into a thread, and the difference is whether
  // an argument stays inside a task or becomes everyone's.
  // The sigils live in the hint row below rather than in here: a placeholder is
  // gone the moment anybody types, and on a narrow box it wrapped the field to
  // two lines to say something the reader had already stopped reading.
  const placeholder = episode ? `Reply in ${threadLabel || "this thread"}…` : "Message the room…";

  // The button carries no chrome at rest — the composer's own border is the
  // affordance and Enter is the primary path. It only colors up, and only
  // grows a hover surface, once there is something to send.
  const armed = content.trim().length > 0 && !sending;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (trigger !== null && candidates.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => (h + 1) % candidates.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => (h - 1 + candidates.length) % candidates.length);
        return;
      }
      if (e.key === "Enter" || e.key === "Tab") {
        e.preventDefault();
        accept(candidates[highlight]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setTrigger(null);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div data-tour="composer" className={`@container border-t border-border bg-bg px-4 py-3 flex-shrink-0${className ? ` ${className}` : ""}`}>
      <div className="relative">
        {trigger !== null && candidates.length > 0 && (
          <div className="absolute bottom-full left-0 mb-2 z-20 w-full max-w-md bg-elevated border border-border rounded-xl shadow-xl overflow-hidden p-1">
            {candidates.map((c, i) => (
              <button
                key={c.id}
                type="button"
                onMouseDown={(e) => {
                  // mouseDown so we don't lose textarea focus before the click
                  e.preventDefault();
                  accept(c);
                }}
                onMouseEnter={() => setHighlight(i)}
                className={`w-full text-left px-2.5 py-1.5 rounded-lg flex items-baseline gap-2 transition-colors ${
                  i === highlight ? "bg-surface" : "hover:bg-surface/60"
                }`}
              >
                <span className="font-mono text-label text-accent flex-shrink-0 truncate max-w-[60%]">
                  {c.primary}
                </span>
                <span className="text-micro text-muted-foreground flex-shrink-0">
                  {c.secondary}
                </span>
                {c.tertiary && (
                  <span className="text-micro text-muted-foreground truncate min-w-0">
                    · {c.tertiary}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        <div className="flex flex-col rounded-2xl border border-border bg-surface transition-colors focus-within:border-accent focus-within:bg-bg">
          <TextareaAutosize
            ref={inputRef}
            value={content}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder={placeholder}
            minRows={1}
            maxRows={10}
            className="w-full resize-none bg-transparent px-4 pt-3 pb-1.5 text-body text-text leading-relaxed focus:outline-none placeholder:text-muted-foreground"
            disabled={sending}
          />
          <div className="flex items-center gap-2 px-3 pb-2.5 pt-0.5">
            {error && <span className="text-micro text-red truncate">{error}</span>}
            <button
              type="button"
              onClick={submit}
              disabled={!armed}
              aria-label="Send message"
              className={`group ml-auto grid size-8 place-items-center rounded-xl transition-colors ${
                armed ? "text-accent hover:bg-accent-soft" : "cursor-not-allowed text-faint"
              }`}
            >
              <SendPlaneIcon
                className={`size-[17px] transition-[transform,opacity] duration-200 ease-out ${
                  sending ? "translate-x-1.5 -translate-y-1.5 opacity-0" : ""
                } ${armed ? "group-hover:-translate-y-px group-hover:translate-x-px group-active:scale-90" : ""}`}
              />
            </button>
          </div>
        </div>
        {/* What the composer answers to, in two halves. The sigils are typed,
            so they hold at every width; the keycaps name keys a phone does not
            have, and three of them wrapped the row onto three lines to say so.
            Measured against the composer rather than the window: the box is
            this narrow on a phone and again in a room with both rails open,
            and the row has to fit the box either way. */}
        <div className="mt-1.5 flex flex-wrap items-center gap-x-1.5 gap-y-1 px-1 text-micro text-muted-foreground">
          <span className="text-faint">@ mention · [[ memory · / skill</span>
          <span className="hidden flex-wrap items-center gap-x-1.5 gap-y-1 @[34rem]:flex">
            <Kbd size="xs" tone="muted">Enter</Kbd> to send ·
            <Kbd size="xs" tone="muted">Shift+Enter</Kbd> for newline ·
            <Kbd size="xs" tone="muted">Esc</Kbd> for command mode
          </span>
        </div>
      </div>
    </div>
  );
}
