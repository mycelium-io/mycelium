// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import Link from "next/link";
import { Bell, BellOff, Check, Settings, VolumeX, X } from "lucide-react";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import { EmptyState } from "@/components/empty-state";
import { Tooltip } from "@/components/ui/tooltip";
import { iconButtonClass } from "@/components/ui/icon-button";
import { useNotifications } from "@/components/notifications-provider";
import { settingHref } from "@/lib/client-settings";
import {
  chainOf,
  entryHref,
  entryTitle,
  isUnseen,
  lastAsk,
  MOVE_LABEL,
  MOVE_TONE,
  sortEntries,
  yourMove,
  type TaskEntry,
} from "@/lib/task-inbox";

/** How many settled-or-quiet tasks the bell lists under Earlier. */
const EARLIER_LIMIT = 30;

export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return "";
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return "now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

/**
 * The bell: one entry per task you're in, not one per event. *Needs you* is
 * what waits on you (asked, blocked, CI red on yours, ready to merge) and is
 * what the badge counts; *Earlier* is the rest, newest first. Each entry shows
 * its recent history as a chain, and opens the task's thread in its room.
 */
export function NotificationBell() {
  const { tasks, needsYouCount, settings, markTaskSeen, markAllTasksSeen, dismissTask, muteTask } =
    useNotifications();
  const [open, setOpen] = useState(false);

  const muted = new Set(settings.mutedTasks ?? []);
  const { needsYou, earlier } = sortEntries(tasks.filter((t) => !muted.has(t.id)));
  const shownEarlier = earlier.slice(0, EARLIER_LIMIT);
  const anyUnseen = [...needsYou, ...shownEarlier].some(isUnseen);

  // One string names the trigger and fills its tooltip, so the do-not-disturb
  // dot — too small to anchor a bubble of its own — is still readable and
  // announced.
  const bellLabel = [
    needsYouCount > 0 ? `${needsYouCount} waiting on you` : "Notifications",
    settings.dnd ? "do not disturb is on" : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const entry = (t: TaskEntry) => (
    <BellEntry
      key={t.id}
      entry={t}
      onOpen={() => {
        markTaskSeen(t.id);
        setOpen(false);
      }}
      onMute={() => muteTask(t.id)}
      onDismiss={() => dismissTask(t.id)}
    />
  );

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <Tooltip content={bellLabel}>
          <PopoverTrigger
            className={iconButtonClass("md", "relative data-[popup-open]:bg-hairline data-[popup-open]:text-text")}
            aria-label={bellLabel}
          >
            <Bell />
            {needsYouCount > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-semibold tabular text-accent-fg">
                {needsYouCount > 99 ? "99+" : needsYouCount}
              </span>
            )}
            {settings.dnd && (
              <span
                aria-hidden
                className="absolute -bottom-0.5 -right-0.5 flex size-3 items-center justify-center rounded-full bg-surface text-muted-foreground"
              >
                <VolumeX className="size-2.5" />
              </span>
            )}
          </PopoverTrigger>
        </Tooltip>
        <PopoverContent className="flex max-h-[32rem] w-96 flex-col p-0">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
            <span className="text-label font-semibold text-text">Notifications</span>
            <div className="ml-auto flex items-center gap-1">
              {anyUnseen && (
                <Tooltip content="Mark all read">
                  <button
                    onClick={markAllTasksSeen}
                    aria-label="Mark all read"
                    className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
                  >
                    <Check className="size-3.5" />
                  </button>
                </Tooltip>
              )}
              <Tooltip content="Notification settings">
                <Link
                  href={settingHref("notifications")}
                  onClick={() => setOpen(false)}
                  aria-label="Notification settings"
                  className="flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
                >
                  <Settings className="size-3.5" />
                </Link>
              </Tooltip>
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto">
            {needsYou.length === 0 && shownEarlier.length === 0 ? (
              <EmptyState
                size="sm"
                icon={Bell}
                title="Nothing yet"
                description="Tasks you filed, are assigned, work on or were mentioned in show up here, one entry per task."
                className="py-8"
              />
            ) : (
              <>
                {needsYou.length > 0 && (
                  <section aria-label="Needs you">
                    <h3 className="px-3 pb-1 pt-2.5 text-micro font-semibold uppercase tracking-wide text-faint">
                      Needs you
                    </h3>
                    {needsYou.map(entry)}
                  </section>
                )}
                {shownEarlier.length > 0 && (
                  <section aria-label="Earlier">
                    <h3 className="px-3 pb-1 pt-2.5 text-micro font-semibold uppercase tracking-wide text-faint">
                      Earlier
                    </h3>
                    {shownEarlier.map(entry)}
                  </section>
                )}
              </>
            )}
          </div>
        </PopoverContent>
      </Popover>
    </>
  );
}

function BellEntry({
  entry,
  onOpen,
  onMute,
  onDismiss,
}: {
  entry: TaskEntry;
  onOpen: () => void;
  onMute: () => void;
  onDismiss: () => void;
}) {
  const move = yourMove(entry);
  const unseen = isUnseen(entry);
  const ask = move === "asks" ? lastAsk(entry) : null;
  // A question alone needs no chain: the line above already quotes it.
  const steps = chainOf(entry);
  const chain = ask && steps.length === 1 ? [] : steps;
  const people = [...new Set(entry.events.map((e) => e.actor).filter((a) => a && a !== "system"))].slice(-2);
  return (
    <div className="group flex items-start gap-2.5 border-b border-border px-3 py-2.5 last:border-b-0 hover:bg-hairline">
      <span
        className="mt-1.5 size-1.5 flex-shrink-0 rounded-full"
        style={{ background: move ? MOVE_TONE[move] : entry.settled ? "var(--faint)" : "var(--muted-foreground)" }}
        aria-hidden
      />
      <Link href={entryHref(entry)} onClick={onOpen} className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className={`truncate text-label ${unseen ? "font-semibold text-text" : "text-muted-foreground"}`}>
            {entryTitle(entry)}
          </span>
          <span className="ml-auto flex-shrink-0 text-micro tabular text-faint">{timeAgo(entry.updatedAt)}</span>
        </div>
        {move && (
          <p className="mt-0.5 truncate text-micro" style={{ color: MOVE_TONE[move] }}>
            <span className="font-semibold">{MOVE_LABEL[move]}</span>
            {ask?.text ? <span className="text-muted-foreground"> · {ask.actor}: {ask.text}</span> : null}
            {!ask && entry.pr.ref ? <span className="text-muted-foreground"> · {entry.pr.ref.split("/").pop()}</span> : null}
          </p>
        )}
        {chain.length > 0 && (
          <p className="mt-0.5 truncate text-micro text-muted-foreground">
            {chain.map((step, i) => (
              <span key={i}>
                {i > 0 && <span className="px-1 text-faint">→</span>}
                {step}
              </span>
            ))}
          </p>
        )}
        <p className="mt-0.5 truncate text-micro text-faint">
          {[entry.room, ...people].join(" · ")}
        </p>
      </Link>
      <div className="flex flex-shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-focus-within:opacity-100 group-hover:opacity-100">
        <Tooltip content="Mute this task">
          <button
            onClick={onMute}
            aria-label={`Mute ${entryTitle(entry)}`}
            className="mt-0.5 flex size-5 items-center justify-center rounded text-faint hover:bg-hairline hover:text-text"
          >
            <BellOff className="size-3" />
          </button>
        </Tooltip>
        <Tooltip content="Dismiss">
          <button
            onClick={onDismiss}
            aria-label={`Dismiss ${entryTitle(entry)}`}
            className="mt-0.5 flex size-5 items-center justify-center rounded text-faint hover:bg-hairline hover:text-text"
          >
            <X className="size-3" />
          </button>
        </Tooltip>
      </div>
    </div>
  );
}
