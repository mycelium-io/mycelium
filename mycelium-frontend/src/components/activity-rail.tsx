// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, MessageSquare } from "lucide-react";

/** One subject's whole run of activity, as the rail shows it. */
export interface ActivityItem {
  /** The row's key, or a thread URN where the room knows no row. */
  subject: string;
  title: string;
  /** The thread to open, when there is one. */
  episode: string | null;
  /** How many frames the room raised about it. */
  count: number;
  /** Who moved it, in the order they first did. */
  actors: string[];
  /** The clock of the most recent one. */
  time: string;
}

/** How many rows stand open before the rest go behind "more". */
const SHOWN = 3;

/**
 * What the room has been doing, held still above the conversation.
 *
 * A room under load raises far more state than speech — a task being worked
 * writes memory, pings its thread and moves on the board, and none of that is
 * something anybody said. Woven into the feed it is a changelog with the
 * conversation buried in it; here it is a fixed number of rows that update in
 * place, so a busy hour costs the same height as a quiet one and the channel
 * below stays what people wrote.
 *
 * Bounded on purpose: the rail is the room's current state, not its history.
 * Everything it names is one click from its thread, and the transitions worth
 * narrating — filed, resolved, blocked — still land in the feed in sequence.
 */
export function ActivityRail({
  items,
  onOpenThread,
}: {
  items: ActivityItem[];
  onOpenThread?: (episode: string) => void;
}) {
  const [open, setOpen] = useState(false);
  if (!items.length) return null;
  const shown = open ? items : items.slice(0, SHOWN);
  const hidden = items.length - shown.length;

  return (
    <div className="flex-shrink-0 border-b border-border bg-surface-2/40 px-5 py-2">
      <div className="flex items-center gap-2 text-micro text-muted-foreground">
        <span className="font-medium">Recently updated</span>
        <span className="text-faint">
          {items.length} {items.length === 1 ? "task" : "tasks"}
        </span>
        {items.length > SHOWN && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
            aria-label={open ? "Show fewer" : `Show all ${items.length}`}
            className="ml-auto inline-flex items-center gap-0.5 rounded px-1 text-faint transition-colors hover:bg-surface-2 hover:text-muted-foreground"
          >
            {open ? (
              <ChevronDown className="size-3" strokeWidth={1.9} />
            ) : (
              <ChevronRight className="size-3" strokeWidth={1.9} />
            )}
            {open ? "fewer" : `${hidden} more`}
          </button>
        )}
      </div>
      <ul className="mt-1 flex flex-col">
        {shown.map((item) => (
          <li key={item.subject}>
            <button
              type="button"
              onClick={() => item.episode && onOpenThread?.(item.episode)}
              disabled={!item.episode || !onOpenThread}
              title={item.subject}
              className="flex w-full items-center gap-2 rounded px-1 py-0.5 text-left text-micro text-muted-foreground transition-colors enabled:hover:bg-surface-2 disabled:cursor-default"
            >
              <MessageSquare className="size-3 flex-shrink-0 text-accent" strokeWidth={1.9} />
              <span className="min-w-0 flex-1 truncate text-text">{item.title}</span>
              <span className="flex-shrink-0 text-faint">
                {item.count} {item.count === 1 ? "update" : "updates"}
              </span>
              <span className="hidden max-w-[12rem] flex-shrink-0 truncate sm:inline">
                {item.actors.map((h) => `@${h}`).join(", ")}
              </span>
              <span className="tabular flex-shrink-0 text-faint">{item.time.slice(0, 5)}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
