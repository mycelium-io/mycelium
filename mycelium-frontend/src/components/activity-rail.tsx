// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight, MessageSquare } from "lucide-react";

/** One thing the room raised about a task, as it reads once a row is opened. */
export interface ActivityUpdate {
  id: string;
  /** When it landed, on the room's clock. */
  time: string;
  /** What happened — "Claimed", "Knowledge", "Activity". */
  label: string;
  /** Who, and any version it carries. */
  detail: string;
}

/** One subject's whole run of activity, as the rail shows it. */
export interface ActivityItem {
  /** The row's key, or a thread URN where the room knows no row. */
  subject: string;
  title: string;
  /** The thread to open, when there is one. */
  episode: string | null;
  /** Who moved it, in the order they first did. */
  actors: string[];
  /** The clock of the most recent update. */
  time: string;
  /** The last board move it made — the state the row is standing in. */
  standing: string | null;
  /** Everything the room raised about it, oldest first. */
  updates: ActivityUpdate[];
}

/** How many rows stand open before the rest go behind "more". */
const SHOWN = 3;

/** The colour a row wears for the state it is standing in. Green when work
 *  lands or closes, red when it stalls, yellow when it comes back up for
 *  grabs, accent while somebody holds it. */
const STANDING_TONE: Record<string, string> = {
  filed: "var(--green)",
  resolved: "var(--green)",
  unblocked: "var(--green)",
  blocked: "var(--red)",
  released: "var(--yellow)",
  claimed: "var(--accent)",
};

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
 * A row opens to the updates it stands for, each with its own clock, so the
 * count is a way in rather than a dead end — and because a task's filing and
 * its resolve land here too, an opened row reads as the whole life of that
 * task in order rather than as the part of it nobody filed anywhere else.
 *
 * Bounded on purpose: the rail is the room's current state, not its history.
 */
export function ActivityRail({
  items,
  onOpenThread,
}: {
  items: ActivityItem[];
  onOpenThread?: (episode: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [opened, setOpened] = useState<Set<string>>(() => new Set());
  if (!items.length) return null;
  const shown = showAll ? items : items.slice(0, SHOWN);
  const hidden = items.length - shown.length;

  const toggle = (subject: string) =>
    setOpened((prev) => {
      const next = new Set(prev);
      if (!next.delete(subject)) next.add(subject);
      return next;
    });

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
            onClick={() => setShowAll((v) => !v)}
            aria-expanded={showAll}
            aria-label={showAll ? "Show fewer" : `Show all ${items.length}`}
            className="ml-auto inline-flex items-center gap-0.5 rounded px-1 text-faint transition-colors hover:bg-surface-2 hover:text-muted-foreground"
          >
            {showAll ? (
              <ChevronDown className="size-3" strokeWidth={1.9} />
            ) : (
              <ChevronRight className="size-3" strokeWidth={1.9} />
            )}
            {showAll ? "fewer" : `${hidden} more`}
          </button>
        )}
      </div>
      <ul className="mt-1 flex flex-col">
        {shown.map((item) => {
          const open = opened.has(item.subject);
          return (
            <li key={item.subject}>
              <div className="flex items-center gap-2 rounded px-1 py-0.5 text-micro text-muted-foreground">
                <span
                  aria-hidden
                  className="inline-block size-1.5 flex-shrink-0 rounded-full"
                  style={{
                    background:
                      (item.standing && STANDING_TONE[item.standing]) ?? "var(--accent)",
                  }}
                />
                <button
                  type="button"
                  onClick={() => item.episode && onOpenThread?.(item.episode)}
                  disabled={!item.episode || !onOpenThread}
                  title={item.subject}
                  className="inline-flex min-w-0 flex-1 items-center gap-1 truncate rounded text-left text-text transition-colors enabled:hover:underline disabled:cursor-default"
                >
                  <MessageSquare className="size-3 flex-shrink-0 text-accent" strokeWidth={1.9} />
                  <span className="truncate">{item.title}</span>
                </button>
                <span className="hidden max-w-[12rem] flex-shrink-0 truncate lg:inline">
                  {item.actors.map((h) => `@${h}`).join(", ")}
                </span>
                <span className="tabular flex-shrink-0 text-faint">{item.time.slice(0, 5)}</span>
                <button
                  type="button"
                  onClick={() => toggle(item.subject)}
                  aria-expanded={open}
                  aria-label={`${open ? "Hide" : "Show"} ${item.updates.length} updates to ${item.title}`}
                  className="inline-flex flex-shrink-0 items-center gap-0.5 rounded px-1 text-faint transition-colors hover:bg-surface-2 hover:text-muted-foreground"
                >
                  {open ? (
                    <ChevronDown className="size-3" strokeWidth={1.9} />
                  ) : (
                    <ChevronRight className="size-3" strokeWidth={1.9} />
                  )}
                  {item.updates.length} {item.updates.length === 1 ? "update" : "updates"}
                </button>
              </div>
              {open && (
                <ul className="mb-1 ml-[0.6rem] flex flex-col gap-1 border-l border-border py-1 pl-3 text-micro text-muted-foreground">
                  {item.updates.map((update) => (
                    <li key={update.id} className="flex items-center gap-2">
                      <span className="tabular flex-shrink-0 text-faint">
                        {update.time.slice(0, 5)}
                      </span>
                      <span className="flex-shrink-0 font-medium">{update.label}</span>
                      {update.detail && <span className="truncate">{update.detail}</span>}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          );
        })}
      </ul>
    </div>
  );
}
