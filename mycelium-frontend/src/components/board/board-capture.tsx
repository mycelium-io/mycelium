// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { forwardRef, useMemo, useState } from "react";
import { CornerDownLeft, Plus, UsersRound } from "lucide-react";
import { parseCapture, type ParsedCapture } from "@/lib/board/capture";
import { cn } from "@/lib/utils";

interface Props {
  actor: string;
  now: string;
  onCapture: (parsed: ParsedCapture) => void;
  /** Hand what is typed to a team instead of filing it: opens the swarm dialog. */
  onSwarm?: (text: string) => void;
}

/**
 * One line in, a typed row out. The parse is shown live under the input, so the
 * sigils teach themselves and nothing is filed with fields the writer didn't see.
 */
export const BoardCapture = forwardRef<HTMLInputElement, Props>(function BoardCapture(
  { actor, now, onCapture, onSwarm },
  ref,
) {
  const [text, setText] = useState("");
  const parsed = useMemo(() => parseCapture(text, actor, now), [text, actor, now]);
  const armed = parsed.title.length > 0;
  // The capture grammar (@owner, !urgent, #tag, ? for a decision) is the
  // field's tooltip, not its placeholder: a cheat sheet in every empty box is
  // the loudest thing on the board.
  const placeholder = "Add a task…";

  const file = () => {
    if (!armed) return;
    onCapture(parsed);
    setText("");
  };

  return (
    <div className="border-b border-border px-3 py-1 sm:px-5">
      <div
        className={cn(
          "flex h-8 items-center gap-2 rounded px-1.5 transition-colors focus-within:bg-bg hover:bg-hairline",
          armed && "bg-bg",
        )}
      >
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
        {/* One control, two outcomes: a row someone claims later, or a team
            on it now. Filing is the everyday one; a swarm costs model turns,
            so it asks first. */}
        <div role="group" aria-label="Add the task" className="flex shrink-0 items-center gap-1 text-micro">
          <button
            type="button"
            onClick={file}
            disabled={!armed}
            title="Add it to the board for someone to pick up (Enter)"
            className={cn(
              "flex h-6 items-center gap-1 rounded px-1.5 transition-colors disabled:cursor-not-allowed disabled:opacity-40",
              armed ? "text-accent hover:bg-hairline" : "text-muted-foreground",
            )}
          >
            <CornerDownLeft className="size-3" />
            File
          </button>
          {onSwarm && (
            <button
              type="button"
              onClick={() => onSwarm(text.trim())}
              title="Have a team of agents work on it now (⌘Enter)"
              className="flex h-6 items-center gap-1 rounded px-1.5 text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
            >
              <UsersRound className="size-3" />
              Swarm
            </button>
          )}
        </div>
      </div>

      {armed && parsed.hints.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 px-1">
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
