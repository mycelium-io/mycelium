// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import TextareaAutosize from "react-textarea-autosize";
import { ArrowUp } from "lucide-react";
import {
  fetchMemories,
  fetchRoomAgents,
  fetchSkills,
  logFetchError,
  sendRoomMessage,
  type AgentSummary,
  type Memory,
  type Skill,
} from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";
import { useKeyAction } from "@/components/keymap-provider";

interface Props {
  roomName: string;
  /** Fired after a successful POST so the parent can refresh the event stream. */
  onSent?: () => void;
  className?: string;
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

export function RoomChatBox({ roomName, onSent, className }: Props) {
  const [content, setContent] = useState("");
  // A human message is sent as the acting-as principal — the single source of
  // "who am I" (the ActingAsPicker), not a per-composer handle. Anonymous falls
  // back to "user" so the room still has a sender to attribute the message to.
  const { principal } = useCurrentUser();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [skills, setSkills] = useState<Skill[]>([]);
  const [trigger, setTrigger] = useState<Trigger | null>(null);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  const refreshSources = useCallback(() => {
    fetchRoomAgents(roomName).then(setAgents).catch((err) => {
      logFetchError("fetchRoomAgents")(err);
      setAgents([]);
    });
    // Memory keys drive `[[` autocomplete; skills drive `/`. Both degrade to [].
    fetchMemories(roomName).then(setMemories).catch(logFetchError("fetchMemories"));
    fetchSkills(roomName).then(setSkills).catch(logFetchError("fetchSkills"));
  }, [roomName]);

  useEffect(() => {
    refreshSources();
    const t = setInterval(refreshSources, 30_000);
    return () => clearInterval(t);
  }, [refreshSources]);

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

  const candidates = useMemo<Candidate[]>(() => {
    if (trigger === null) return [];
    if (trigger.kind === "agent") {
      const pool = trigger.query
        ? agents.filter((a) => a.handle.toLowerCase().startsWith(trigger.query))
        : agents;
      return pool.slice(0, 6).map((a) => ({
        id: a.handle,
        insert: `@${a.handle}`,
        primary: `@${a.handle}`,
        secondary: a.adapter === "engine" && a.kind ? `engine · ${a.kind}` : a.adapter,
        tertiary: a.description || undefined,
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
  }, [agents, memories, skills, trigger]);

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
      await sendRoomMessage(roomName, { sender_handle: handle, content: body });
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
  }, [content, onSent, roomName, principal, sending]);

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
    <div data-tour="composer" className={`border-t border-border bg-bg px-4 py-3 flex-shrink-0${className ? ` ${className}` : ""}`}>
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
            placeholder="Message the room…  @ agent · [[ memory · / skill"
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
              disabled={!content.trim() || sending}
              aria-label="Send message"
              className="ml-auto flex size-8 items-center justify-center rounded-full bg-accent text-accent-fg transition-opacity hover:opacity-90 disabled:opacity-30 disabled:cursor-not-allowed"
            >
              <ArrowUp className="size-4" strokeWidth={2.5} />
            </button>
          </div>
        </div>
        <div className="mt-1.5 px-1 text-micro text-muted-foreground">
          <kbd className="font-sans">Enter</kbd> to send · <kbd className="font-sans">Shift+Enter</kbd> for newline ·{" "}
          <kbd className="font-sans">Esc</kbd> for command mode
        </div>
      </div>
    </div>
  );
}
