// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import { ChevronDown, ChevronRight, MessageSquare } from "lucide-react";

import { Tooltip } from "@/components/ui/tooltip";
import { useIsClient } from "@/lib/client-hooks";
import { cn } from "@/lib/utils";

/** One thing the room raised about a task, as it reads once a row is opened. */
export interface ActivityUpdate {
  id: string;
  /** When it landed, on the room's clock. */
  time: string;
  /** When it landed, in ms, for saying how long ago. */
  at: number;
  /** What happened — "Claimed", "Knowledge", "Activity". */
  label: string;
  /** Who, and any version it carries. */
  detail: string;
  /** The board move it was, for a notice; null for anything else. */
  subkind: string | null;
}

/** One subject's whole run of activity, as the rail shows it. */
export interface ActivityItem {
  /** The row's key, or a thread URN where the room knows no row. */
  subject: string;
  title: string;
  /** The thread to open, when there is one. */
  episode: string | null;
  /** The row's own key, for opening its details. Null for a thread the room
   *  knows no row for — there the conversation is all there is to open. */
  memoryKey: string | null;
  /** Who moved it, in the order they first did. */
  actors: string[];
  /** Who moved it last: the answer to "who has this". */
  lastActor: string | null;
  /** The clock of the most recent update. */
  time: string;
  /** When it last moved, in ms. */
  at: number;
  /** The last board move it made — the state the row is standing in. */
  standing: string | null;
  /** What whoever moved it said about it ("waiting on the merchant ID"). */
  note: string | null;
  /** Everything the room raised about it, oldest first. */
  updates: ActivityUpdate[];
}

/** How many rows stand open before the rest go behind one line. */
const SHOWN = 4;

/** Whether the strip is folded to its header, remembered in this browser for
 *  every room: how much of the screen it gets is the reader's preference. */
const FOLDED_KEY = "mycelium.activity.folded";

function loadFolded(): boolean {
  if (typeof localStorage === "undefined") return false;
  try {
    return localStorage.getItem(FOLDED_KEY) === "1";
  } catch {
    return false;
  }
}

function saveFolded(folded: boolean): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(FOLDED_KEY, folded ? "1" : "0");
  } catch {
    // Storage refused: the strip still folds, it just won't be remembered.
  }
}

/** The state a row is standing in, said as a word, and the color it wears.
 *  Green when work arrives, accent while somebody holds it, red when it
 *  stalls, yellow when it comes back up for grabs, and grey once it's done:
 *  finished work steps back so the eye goes to what's still moving. */
const STANDING: Record<string, { word: string; tone: string }> = {
  filed: { word: "New", tone: "var(--green)" },
  claimed: { word: "Claimed", tone: "var(--accent)" },
  blocked: { word: "Blocked", tone: "var(--red)" },
  released: { word: "Released", tone: "var(--yellow)" },
  expired: { word: "Expired", tone: "var(--yellow)" },
  unblocked: { word: "Unblocked", tone: "var(--green)" },
  resolved: { word: "Done", tone: "var(--faint)" },
};

/** A row that has only been written to, not moved on the board. */
const ACTIVE = { word: "Active", tone: "var(--muted-foreground)" };

/** The states the header counts: what's live. Done work isn't news, and
 *  neither is a lease running out on work its holder is still doing. */
const TALLIED = ["blocked", "claimed", "filed", "released"] as const;

function standingOf(item: ActivityItem) {
  return (item.standing && STANDING[item.standing]) || ACTIVE;
}

/** "3 claimed · 2 blocked · 3 new", for the tasks given. */
function tally(items: ActivityItem[]): { key: string; n: number; word: string; tone: string }[] {
  const counts = new Map<string, number>();
  for (const item of items) {
    if (item.standing) counts.set(item.standing, (counts.get(item.standing) ?? 0) + 1);
  }
  return TALLIED.filter((s) => counts.get(s)).map((s) => ({
    key: s,
    n: counts.get(s) as number,
    word: STANDING[s].word.toLowerCase(),
    tone: STANDING[s].tone,
  }));
}

/** How long ago, as short as it can be said: "now", "4m", "2h", "3d". */
export function shortAge(at: number, now: number): string {
  if (!at) return "";
  const min = Math.floor(Math.max(0, now - at) / 60_000);
  if (min < 1) return "now";
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60);
  return h < 24 ? `${h}h` : `${Math.floor(h / 24)}d`;
}

/** The time, kept current, so an age doesn't freeze at what it said on arrival. */
function useNow(everyMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), everyMs);
    return () => clearInterval(id);
  }, [everyMs]);
  return now;
}

/** The last thing that happened to a task, as a short sentence:
 *  "@ana posted in the thread", "@sam edited its notes", "claimed by @ana". */
export function lastChange(update: ActivityUpdate): string {
  const who = update.detail.match(/@[\w.@-]+/g)?.join(", ") ?? "";
  if (update.label === "Activity") return who ? `${who} posted in the thread` : "a message in the thread";
  if (update.label === "Knowledge") return who ? `${who} edited its notes` : "its notes changed";
  // The handle on an expired lease is whoever stopped renewing it, not who did it.
  if (update.label === "Expired") return who ? `${who}'s lease ran out` : "its lease ran out";
  // Whose turn it is in the thread: the holder alone, the handles it gave the
  // floor to, or the floor opening back up.
  if (update.label === "Floor") {
    // The detail is "<task> · <turn>"; only the part after the title says it.
    if (update.detail.split(" · ").pop() === "released") return "floor open";
    const holder = update.detail.match(/held by (@[\w.@-]+)/)?.[1];
    const turn = holder ?? who;
    if (!turn) return "the floor moved";
    return turn.includes(",") ? `turn for ${turn}` : `${turn}'s turn`;
  }
  return `${update.label.toLowerCase()}${who ? ` by ${who}` : ""}`;
}

function Dot({ tone }: { tone: string }) {
  return <span aria-hidden className="inline-block size-1.5 flex-shrink-0 rounded-full" style={{ background: tone }} />;
}

/**
 * What the room has been doing, held still above the conversation.
 *
 * A room under load raises far more state than speech — a task being worked
 * writes memory, pings its thread and moves on the board, and none of that is
 * something anybody said. Woven into the feed it is a changelog with the
 * conversation buried in it; here it is a bounded strip that updates in place,
 * so a busy hour never pushes the channel below off the screen.
 *
 * Each row says the state its task is standing in as a word (Claimed, Blocked,
 * Done), who moved it last and how long ago, and what they said about it when
 * they said anything. The header counts what's live. A row opens to its whole
 * life in order. One task is a single line with no header; past four, the rest
 * wait behind one line that says what they are, and showing them all scrolls
 * inside the strip rather than growing it.
 *
 * The header folds the strip to itself: one line with the counts and the task
 * that moved last, for a reader who wants the conversation to have the room.
 * Three densities, then: folded, four rows, all of them.
 */
export function ActivityRail({
  items,
  onOpenThread,
  onOpenMemory,
}: {
  items: ActivityItem[];
  onOpenThread?: (episode: string) => void;
  onOpenMemory?: (key: string) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const [opened, setOpened] = useState<Set<string>>(() => new Set());
  // The stored fold is read once mounted, so the server's render and the first
  // client one agree; a click here wins over it from then on.
  const mounted = useIsClient();
  const [chosen, setChosen] = useState<boolean | null>(null);
  const folded = chosen ?? (mounted && loadFolded());
  const now = useNow();
  if (!items.length) return null;
  const fold = (next: boolean) => {
    setChosen(next);
    saveFolded(next);
  };

  const toggle = (subject: string) =>
    setOpened((prev) => {
      const next = new Set(prev);
      if (!next.delete(subject)) next.add(subject);
      return next;
    });
  const row = (item: ActivityItem) => (
    <ActivityRow
      key={item.subject}
      item={item}
      now={now}
      open={opened.has(item.subject)}
      onToggle={() => toggle(item.subject)}
      onOpenThread={onOpenThread}
      onOpenMemory={onOpenMemory}
    />
  );

  // One task is one line: a header over a single row is the heaviest version
  // of the strip for the least news.
  if (items.length === 1) {
    return (
      <div className="@container flex flex-shrink-0 items-start gap-3 border-b border-border bg-surface px-3 py-0.5 sm:px-4">
        <span className="hidden h-[26px] flex-shrink-0 items-center text-micro font-medium text-muted-foreground @[30rem]:flex">
          Recently updated
        </span>
        <ul className="flex min-w-0 flex-1 flex-col">{row(items[0])}</ul>
      </div>
    );
  }

  // Finished work steps back behind one line: the four rows on show are the
  // ones still moving, so a merged task never takes a slot from a live one.
  const live = items.filter((item) => item.standing !== "resolved");
  const done = items.filter((item) => item.standing === "resolved");
  const ordered = [...live, ...done];
  const shown = showAll ? ordered : live.slice(0, SHOWN);
  const rest = ordered.slice(shown.length);
  const restLive = live.slice(SHOWN);
  // Folded, the line still says what moved last, so it is news rather than a label.
  const latest = live.reduce<ActivityItem | null>((a, b) => (!a || b.at > a.at ? b : a), null);

  return (
    <div className={cn("@container flex-shrink-0 border-b border-border bg-surface px-3 sm:px-4", !folded && "pb-1")}>
      <button
        type="button"
        onClick={() => fold(!folded)}
        aria-expanded={!folded}
        aria-label={folded ? "Show recently updated tasks" : "Fold recently updated tasks"}
        className="group flex h-7 w-full items-center gap-3 text-left text-micro text-muted-foreground"
      >
        <span className="flex flex-shrink-0 items-center gap-1 font-medium group-hover:text-text">
          {folded ? <ChevronRight className="size-3" /> : <ChevronDown className="size-3" />}
          Recently updated
        </span>
        <span className="flex flex-shrink-0 items-center gap-2.5 whitespace-nowrap text-muted-foreground">
          {tally(items).map((t) => (
            <span key={t.key} className="inline-flex items-center gap-1.5">
              <Dot tone={t.tone} />
              {t.n} {t.word}
            </span>
          ))}
        </span>
        {folded && latest && (
          <span className="hidden min-w-0 flex-1 items-center gap-1.5 text-faint @[36rem]:flex">
            <span aria-hidden>·</span>
            <span className="truncate text-muted-foreground">{latest.title}</span>
            <span className="flex-shrink-0 tabular">{shortAge(latest.at, now)}</span>
          </span>
        )}
        <span className="ml-auto hidden flex-shrink-0 text-faint @[30rem]:inline">
          {items.length} tasks
        </span>
      </button>
      {!folded && (
        <ul className={cn("flex flex-col", showAll && "max-h-[12.5rem] overflow-y-auto")}>{shown.map(row)}</ul>
      )}
      {!folded && (rest.length > 0 || showAll) && (
        <div className="flex h-7 items-center gap-3 text-micro">
          <button
            type="button"
            onClick={() => setShowAll((v) => !v)}
            aria-expanded={showAll}
            aria-label={showAll ? "Show fewer" : `Show all ${items.length}`}
            className="rounded px-1 text-accent transition-colors hover:bg-accent-soft"
          >
            {showAll ? "Show fewer" : `Show ${rest.length} more`}
          </button>
          {!showAll && (
            <span className="min-w-0 truncate text-faint">
              {[
                ...tally(restLive).map((t) => `${t.n} ${t.word}`),
                ...(done.length ? [`${done.length} done`] : []),
              ].join(" · ")}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

function ActivityRow({
  item,
  now,
  open,
  onToggle,
  onOpenThread,
  onOpenMemory,
}: {
  item: ActivityItem;
  now: number;
  open: boolean;
  onToggle: () => void;
  onOpenThread?: (episode: string) => void;
  onOpenMemory?: (key: string) => void;
}) {
  const standing = standingOf(item);
  const done = item.standing === "resolved";
  const count = item.updates.length;
  // What changed, not only when: what its holder said, else the last thing
  // that happened to it, so two rows from the same hour don't read the same.
  const last = item.updates[item.updates.length - 1];
  const changed = item.note ?? (last ? `${lastChange(last)}${count > 1 ? ` · ${count} updates` : ""}` : null);
  const canOpen = Boolean((item.memoryKey && onOpenMemory) || (item.episode && onOpenThread));
  return (
    <li>
      <div className="flex h-[26px] items-center gap-2 text-micro">
        {/* The row's history: a way in from the state, not a bare count. */}
        <button
          type="button"
          onClick={onToggle}
          aria-expanded={open}
          aria-label={`${open ? "Hide" : "Show"} ${count} ${count === 1 ? "update" : "updates"} to ${item.title}`}
          className="flex w-4 flex-shrink-0 items-center justify-center rounded text-faint transition-colors hover:bg-hairline hover:text-muted-foreground"
        >
          {open ? <ChevronDown className="size-3" strokeWidth={1.9} /> : <ChevronRight className="size-3" strokeWidth={1.9} />}
        </button>
        {/* The state as a word in a column of its own, so titles line up and a
            blocked row says it's blocked without anyone learning the colors.
            A narrow strip keeps the color alone. */}
        <span className="flex flex-shrink-0 items-center gap-1.5 @[30rem]:w-[4.75rem]" style={{ color: standing.tone }}>
          <Dot tone={standing.tone} />
          <span className="hidden @[30rem]:inline">{standing.word}</span>
        </span>
        {/* The task itself, as text rather than a link-colored wall: it still
            opens the task, and says so on hover. */}
        <span className="flex min-w-0 flex-1 items-center gap-2">
          <button
            type="button"
            onClick={() =>
              item.memoryKey && onOpenMemory ? onOpenMemory(item.memoryKey) : item.episode && onOpenThread?.(item.episode)
            }
            disabled={!canOpen}
            title={item.subject}
            aria-label={`Open task ${item.title}`}
            className={cn(
              "min-w-0 truncate rounded text-left text-label transition-colors enabled:hover:text-accent enabled:hover:underline disabled:cursor-default",
              done ? "text-muted-foreground" : "text-text",
            )}
          >
            {item.title}
          </button>
          {changed && (
            <span className="hidden min-w-0 truncate text-faint @[36rem]:inline" title={changed}>
              {changed}
            </span>
          )}
        </span>
        {item.lastActor && (
          <span className="hidden max-w-[9rem] flex-shrink-0 truncate text-muted-foreground @[30rem]:inline">
            @{item.lastActor}
          </span>
        )}
        <span className="tabular w-8 flex-shrink-0 text-right text-faint" title={item.time.slice(0, 5)}>
          {shortAge(item.at, now)}
        </span>
        {/* Its conversation, kept as its own target: the details and the
            argument about them are two places. */}
        {item.episode && onOpenThread ? (
          <Tooltip content="Open the thread">
            <button
              type="button"
              onClick={() => onOpenThread(item.episode as string)}
              aria-label={`Open thread for ${item.title}`}
              className="inline-flex w-5 flex-shrink-0 items-center justify-center rounded p-0.5 text-faint transition-colors hover:bg-hairline hover:text-accent"
            >
              <MessageSquare className="size-3" strokeWidth={1.9} />
            </button>
          </Tooltip>
        ) : (
          <span className="w-5 flex-shrink-0" />
        )}
      </div>
      {open && (
        <ul className="mb-1.5 ml-[1.9rem] flex flex-col gap-0.5 border-l border-border pl-3 text-micro text-muted-foreground">
          {item.updates.map((update) => (
            <li key={update.id} className="flex items-center gap-2">
              <span className="tabular w-8 flex-shrink-0 text-right text-faint" title={update.time.slice(0, 5)}>
                {shortAge(update.at, now)}
              </span>
              <Dot tone={(update.subkind && STANDING[update.subkind]?.tone) || "var(--border2)"} />
              <span className="flex-shrink-0 font-medium">{update.label}</span>
              {update.detail && <span className="truncate">{update.detail}</span>}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}
