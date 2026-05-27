// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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

  // Persist sender across reloads — agents see the same handle every time.
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
    <div className="border-t border-border bg-paper px-3 pt-2 pb-3 flex-shrink-0">
      <div className="flex items-center gap-2 pb-2">
        <span className="caps-mono-sm text-muted">SEND AS</span>
        <input
          type="text"
          value={sender}
          onChange={(e) => setSender(e.target.value)}
          placeholder="handle"
          className="font-mono text-micro bg-bg border border-border rounded px-2 py-0.5 w-32 focus:outline-none focus:border-accent"
        />
        <span className="caps-mono-sm text-muted ml-auto">
          {agents.length} agent{agents.length === 1 ? "" : "s"}
        </span>
      </div>

      <div className="relative">
        {mention !== null && candidates.length > 0 && (
          <div className="absolute bottom-full left-0 mb-1 z-20 w-full max-w-md bg-paper border border-border rounded shadow-lg overflow-hidden">
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
                className={`w-full text-left px-3 py-1.5 flex items-baseline gap-2 ${
                  i === highlight ? "bg-bg" : "hover:bg-bg/60"
                }`}
              >
                <span className="font-mono text-label text-accent flex-shrink-0">
                  @{a.handle}
                </span>
                <span
                  className="caps-mono-sm tabular flex-shrink-0"
                  style={{
                    color:
                      a.adapter === "openclaw" ? "var(--green)" : "var(--muted)",
                  }}
                >
                  {a.adapter}
                </span>
                {a.description && (
                  <span className="text-micro text-muted truncate min-w-0">
                    — {a.description}
                  </span>
                )}
              </button>
            ))}
          </div>
        )}

        <textarea
          ref={inputRef}
          value={content}
          onChange={handleChange}
          onKeyDown={handleKeyDown}
          placeholder="message the room — @ to mention an agent · ⇧⏎ for newline"
          rows={2}
          className="w-full resize-none bg-bg border border-border rounded px-3 py-2 font-mono text-label focus:outline-none focus:border-accent placeholder:text-muted"
          disabled={sending}
        />
      </div>

      <div className="flex items-center justify-between mt-1">
        <span className="text-micro text-muted">
          {error ? <span style={{ color: "var(--red)" }}>{error}</span> : ""}
        </span>
        <button
          type="button"
          onClick={submit}
          disabled={!content.trim() || sending}
          className="caps-mono-sm px-3 py-1 border border-accent text-accent rounded disabled:opacity-40 disabled:cursor-not-allowed hover:bg-accent hover:text-bg transition-colors"
        >
          {sending ? "SENDING…" : "SEND"}
        </button>
      </div>
    </div>
  );
}
