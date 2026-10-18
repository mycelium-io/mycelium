// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { forwardRef, useMemo, useState } from "react";
import { Plus } from "lucide-react";
import { Kbd } from "@/components/ui/kbd";
import { parseCapture, type ParsedCapture } from "@/lib/board/capture";

interface Props {
  actor: string;
  now: string;
  onCapture: (parsed: ParsedCapture) => void;
  /** Hand what is typed to a team instead of filing it: opens the swarm dialog. */
  onSwarm?: (text: string) => void;
  /** What the empty box says. The capture grammar (@owner, !urgent, #tag, ?
   *  for a decision) is the field's tooltip, not its placeholder: a cheat
   *  sheet in every empty box is the loudest thing on the board. */
  placeholder?: string;
}

/**
 * One line in, a typed row out. The parse is shown live under the input, so the
 * sigils teach themselves and nothing is filed with fields the writer didn't see.
 */
export const BoardCapture = forwardRef<HTMLInputElement, Props>(function BoardCapture(
  { actor, now, onCapture, onSwarm, placeholder = "Add a task…" },
  ref,
) {
  const [text, setText] = useState("");
  const parsed = useMemo(() => parseCapture(text, actor, now), [text, actor, now]);
  const armed = parsed.title.length > 0;

  const file = () => {
    if (!armed) return;
    onCapture(parsed);
    setText("");
  };

  return (
    <div className="flex-shrink-0 border-b border-border px-3 sm:px-4">
      <div className="flex h-8 items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Plus className="size-3.5 shrink-0 text-faint" strokeWidth={2} />
          <input
            ref={ref}
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && onSwarm) onSwarm(text.trim());
              else if (e.key === "Enter") file();
              if (e.key === "Escape") (e.target as HTMLInputElement).blur();
            }}
            placeholder={placeholder}
            title="@who · !urgent · #tag · #502 for an issue · end with ? for a decision"
            aria-label="New task"
            className="min-w-0 flex-1 bg-transparent text-label text-text outline-none placeholder:text-faint"
          />
        </div>
        {/* One line, two outcomes: a row someone picks up later, or a team on
            it now. The keys show once there is something to send, and each
            is also a click. A swarm costs model turns, so it asks first. */}
        {armed && (
          <div role="group" aria-label="Send it" className="flex shrink-0 items-center gap-2 text-micro text-faint">
            <button
              type="button"
              onClick={file}
              title="Add it to the board for someone to pick up"
              className="flex items-center gap-1 rounded px-1 transition-colors hover:bg-hairline hover:text-text"
            >
              <Kbd size="xs" tone="muted">↵</Kbd> to file
            </button>
            {onSwarm && (
              <button
                type="button"
                onClick={() => onSwarm(text.trim())}
                title="Have a team of agents work on it now"
                className="flex items-center gap-1 rounded px-1 transition-colors hover:bg-hairline hover:text-text"
              >
                <Kbd size="xs" tone="muted">⌘↵</Kbd> for a team
              </button>
            )}
          </div>
        )}
      </div>

      {armed && parsed.hints.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 pb-1.5">
          <span className="font-mono text-micro text-faint">parsed →</span>
          {parsed.hints.map(hint => (
            <span
              key={`${hint.label}:${hint.value}`}
              className="rounded bg-accent-soft px-1.5 font-mono text-micro text-accent"
            >
              {hint.label}: {hint.value}
            </span>
          ))}
        </div>
      )}
    </div>
  );
});
