// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { forwardRef, useMemo, useState } from "react";
import { CornerDownLeft, Plus, UsersRound } from "lucide-react";
import { parseCapture, type ParsedCapture } from "@/lib/board/capture";
import { cn } from "@/lib/utils";
import { useSheetLayout } from "@/lib/use-viewport";

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
  // The capture grammar is a hint, and a hint clipped mid-token teaches
  // nothing: on a field this narrow it is the ask that has to survive.
  const sheet = useSheetLayout();
  const placeholder = sheet
    ? "Capture a concern…"
    : "Capture a concern…  @owner · !urgent · #tag · #502 · ? for a decision";

  return (
    <div className="mt-2 px-3 pb-2 sm:px-5">
      <div className="flex items-center gap-2">
        <div
          className={cn(
            "flex min-w-0 flex-1 items-center gap-2 rounded-lg border bg-surface/60 px-3 py-1.5 transition-colors",
            armed ? "border-accent/40" : "border-border",
          )}
        >
          <Plus className="size-3.5 shrink-0 text-faint" strokeWidth={2} />
          <input
            ref={ref}
            value={text}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => {
              if (e.key === "Enter" && armed) {
                onCapture(parsed);
                setText("");
              }
              if (e.key === "Escape") (e.target as HTMLInputElement).blur();
            }}
            placeholder={placeholder}
            className="min-w-0 flex-1 bg-transparent text-label text-text outline-none placeholder:text-faint"
          />
          {armed && (
            <span className="flex shrink-0 items-center gap-1 font-mono text-micro text-faint">
              <CornerDownLeft className="size-3" />
              file
            </span>
          )}
        </div>
        {onSwarm && (
          <button
            type="button"
            onClick={() => onSwarm(text.trim())}
            title="Put a team of agents on this task"
            className="flex h-[34px] shrink-0 items-center gap-1.5 rounded-lg border border-border px-3 text-label text-muted-foreground transition-colors hover:border-border2 hover:text-text"
          >
            <UsersRound className="size-3.5" />
            Swarm
          </button>
        )}
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
