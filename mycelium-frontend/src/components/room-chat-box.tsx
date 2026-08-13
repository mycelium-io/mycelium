// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import TextareaAutosize from "react-textarea-autosize";
import { ArrowUp } from "lucide-react";
import { fetchRoomAgents, logFetchError, sendRoomMessage, type AgentSummary } from "@/lib/api";

interface Props {
  roomName: string;
  /** Sender handle persisted to localStorage. Falls back to "user". */
  defaultSender?: string;
  /** Fired after a successful POST so the parent can refresh the event stream. */
  onSent?: () => void;
}

const SENDER_STORAGE_KEY = "mycelium.chat.sender";

export function RoomChatBox({ roomName, defaultSender, onSent }: Props) {
  const [content, setContent] = useState("");
  const [sender, setSender] = useState<string>(() => defaultSender || "user");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [mention, setMention] = useState<{ start: number; query: string } | null>(null);
  const [highlight, setHighlight] = useState(0);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);

  // Persist sender across reloads so agents see the same handle every time.
  useEffect(() => {
    if (typeof window === "undefined") return;
    const saved = window.localStorage.getItem(SENDER_STORAGE_KEY);
    if (saved) setSender(saved);
  }, []);
  useEffect(() => {
    if (typeof window === "undefined") return;
    window.localStorage.setItem(SENDER_STORAGE_KEY, sender);
  }, [sender]);

  const refreshAgents = useCallback(() => {
    fetchRoomAgents(roomName).then(setAgents).catch((err) => {
      logFetchError("fetchRoomAgents")(err);
      setAgents([]);
    });
  }, [roomName]);

  useEffect(() => {
    refreshAgents();
    const t = setInterval(refreshAgents, 30_000);
    return () => clearInterval(t);
  }, [refreshAgents]);

  // Detect an in-flight @-mention by looking at the cursor's prefix.
  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = e.target.value;
    setContent(next);
    const cursor = e.target.selectionStart ?? next.length;
    const prefix = next.slice(0, cursor);
    const match = prefix.match(/(?:^|\s)@([a-z0-9._-]*)$/i);
    if (match) {
      setMention({ start: cursor - match[1].length - 1, query: match[1].toLowerCase() });
      setHighlight(0);
    } else {
      setMention(null);
    }
  };

  const candidates = useMemo(() => {
    if (mention === null) return [];
    if (!mention.query) return agents.slice(0, 6);
    return agents
      .filter((a) => a.handle.toLowerCase().startsWith(mention.query))
      .slice(0, 6);
  }, [agents, mention]);

  const acceptMention = useCallback(
    (handle: string) => {
      if (mention === null) return;
      const before = content.slice(0, mention.start);
      const after = content.slice(mention.start + 1 + mention.query.length);
      const insertion = `@${handle} `;
      const next = `${before}${insertion}${after}`;
      setContent(next);
      setMention(null);
      // Restore the cursor after the inserted handle.
      requestAnimationFrame(() => {
        const node = inputRef.current;
        if (!node) return;
        const pos = before.length + insertion.length;
        node.focus();
        node.setSelectionRange(pos, pos);
      });
    },
    [content, mention],
  );

  const submit = useCallback(async () => {
    const body = content.trim();
    if (!body || sending) return;
    const handle = sender.trim() || "user";
    setSending(true);
    setError(null);
    try {
      await sendRoomMessage(roomName, { sender_handle: handle, content: body });
      setContent("");
      setMention(null);
      onSent?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
      // The textarea is disabled while sending; it re-enables on the next
      // render, so refocus after that commit lands to keep the user typing.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [content, onSent, roomName, sender, sending]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (mention !== null && candidates.length > 0) {
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
        acceptMention(candidates[highlight].handle);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMention(null);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  return (
    <div data-tour="composer" className="border-t border-border bg-bg px-4 py-3 flex-shrink-0">
      <div className="relative">
        {mention !== null && candidates.length > 0 && (
          <div className="absolute bottom-full left-0 mb-2 z-20 w-full max-w-md bg-elevated border border-border rounded-xl shadow-xl overflow-hidden p-1">
            {candidates.map((a, i) => (
              <button
                key={a.handle}
                type="button"
                onMouseDown={(e) => {
                  // mouseDown so we don't lose textarea focus before the click
                  e.preventDefault();
                  acceptMention(a.handle);
                }}
                onMouseEnter={() => setHighlight(i)}
                className={`w-full text-left px-2.5 py-1.5 rounded-lg flex items-baseline gap-2 transition-colors ${
                  i === highlight ? "bg-surface" : "hover:bg-surface/60"
                }`}
              >
                <span className="font-mono text-label text-accent flex-shrink-0">
                  @{a.handle}
                </span>
                <span className="text-micro text-muted-foreground flex-shrink-0">
                  {a.adapter}
                </span>
                {a.description && (
                  <span className="text-micro text-muted-foreground truncate min-w-0">
                    · {a.description}
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
            placeholder="Message the room…  @ to mention an agent"
            minRows={1}
            maxRows={10}
            className="w-full resize-none bg-transparent px-4 pt-3 pb-1.5 text-body text-text leading-relaxed focus:outline-none placeholder:text-muted-foreground"
            disabled={sending}
          />
          <div className="flex items-center gap-2 px-3 pb-2.5 pt-0.5">
            <label className="flex items-center gap-1.5 text-micro text-muted-foreground">
              <span>as</span>
              <input
                type="text"
                value={sender}
                onChange={(e) => setSender(e.target.value)}
                placeholder="user"
                aria-label="Send as handle"
                size={Math.max(sender.length || 4, 4)}
                className="font-mono text-micro bg-transparent text-muted-foreground rounded px-1 py-0.5 focus:outline-none focus:bg-surface hover:bg-surface transition-colors"
              />
            </label>
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
          <kbd className="font-sans">Enter</kbd> to send · <kbd className="font-sans">Shift+Enter</kbd> for newline
        </div>
      </div>
    </div>
  );
}
