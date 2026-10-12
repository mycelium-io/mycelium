// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The Stream tab's model: everything that happens in a room, one line each.
 *
 * A room's wire frames (the transcript replayed by `/messages/wire`, then the
 * live room feed) become `StreamEvent`s: a message in the channel or in any
 * task's thread, a board change (filed, claimed, resolved…), a change to a
 * linked pull request, or a saved memory. Nothing is ranked or hidden. The only
 * condensing is folding the same kind of thing, by the same actor on the same
 * task, in the same minute into one line. `lanesOf` gives each thread on screen
 * a lane, so parallel conversations can be drawn side by side.
 *
 * Framework-agnostic, so the folding and lanes are unit-tested without rendering.
 */

import { parseMentions } from "@/lib/mentions";
import { CHAT_TYPES, unwrapContent } from "@/lib/room-events";
import { isLiveEpisode, noticeOf, pingOf } from "@/lib/threads";

export type StreamKind = "message" | "board" | "github" | "saved";

export interface StreamEvent {
  id: string;
  /** ISO time it was recorded. */
  at: string;
  /** Who did it: the sender, the notice's `by`, or "github" for a pull request change. */
  who: string;
  kind: StreamKind;
  /** The task's thread it happened in, or null for the room's channel. */
  episode: string | null;
  /** The task's title when the frame names it (a notice does). */
  title: string | null;
  /** A message's full text; for a saved memory, its key. */
  text: string;
  /** For a board change, what happened (`filed`, `claimed`…). */
  subkind: string | null;
  /** For a pull request change, what changed and which one (`owner/repo#12`). */
  change: string | null;
  ref: string | null;
  /** For a `filed` notice, who the task is for. */
  assignee: string | null;
  /** For a review request, who was asked. */
  asked: string[];
  /** Handles the message asks for with `@handle` (not silent `@~` ones). */
  mentions: string[];
}

/** Board namespaces: saving one of their rows is the board change itself, which
 *  its notice already says, so the save isn't a line of its own. */
const BOARD_KEY = /^(work|decisions|status|failed)\//;

const str = (v: unknown): string | null => (typeof v === "string" && v ? v : null);

function threadOf(room: string, episode: unknown): string | null {
  const ep = str(episode);
  // Memory pushes ride an episode of their own (`…:knowledge`), not a thread.
  if (!ep || isLiveEpisode(room, ep) || ep.endsWith(":knowledge")) return null;
  return ep;
}

/** The stream event a wire frame carries, or null when it isn't one: a ping
 *  (the message itself arrives too), a floor change, presence, or the save of
 *  a board row. */
export function streamEventOf(raw: Record<string, unknown>, room: string): StreamEvent | null {
  const mtype = str(raw.message_type) ?? "";
  const id = str(raw.id);
  const at = str(raw.created_at);
  if (!id || !at) return null;
  const content = unwrapContent(raw);
  const l9 = (content.l9 ?? {}) as Record<string, unknown>;
  const header = ((l9.header as Record<string, unknown> | undefined)?.message ?? {}) as Record<string, unknown>;
  const base = {
    id,
    at,
    who: str(raw.sender_handle) ?? "hub",
    episode: threadOf(room, header.episode ?? raw.episode),
    title: null,
    subkind: null,
    change: null,
    ref: null,
    assignee: null,
    asked: [] as string[],
    mentions: [] as string[],
  };

  if (mtype === "l9_knowledge" || mtype === "knowledge") {
    const data = ((l9.payload as Record<string, unknown> | undefined)?.data ?? {}) as Record<string, unknown>;
    const fallback = str(content.content)?.replace(/^memory updated\s*→\s*/, "") ?? null;
    const key = str(data.key) ?? fallback;
    if (!key || BOARD_KEY.test(key)) return null;
    return { ...base, kind: "saved", episode: null, text: key, who: base.who === "system" ? "hub" : base.who };
  }

  if (mtype !== "l9_exchange" && !CHAT_TYPES.has(mtype)) return null;
  if (pingOf(content)) return null;

  const notice = noticeOf(content);
  if (notice) {
    if (notice.subkind === "floor") return null;
    const github = notice.subkind === "upstream";
    return {
      ...base,
      kind: github ? "github" : "board",
      who: github ? "github" : notice.by ?? base.who,
      episode: threadOf(room, notice.episode),
      title: notice.title,
      text: "",
      subkind: notice.subkind,
      change: notice.change,
      ref: notice.ref,
      assignee: notice.assignee,
      asked: notice.who,
    };
  }

  const text = str(content.content) ?? str(content.text) ?? "";
  if (!text) return null;
  return { ...base, kind: "message", text, mentions: parseMentions(text).map((h) => h.toLowerCase()) };
}

/** A stream line: one event, or several the same that were folded into it. */
export interface StreamLine {
  event: StreamEvent;
  /** Events folded into this line after the first, oldest first. */
  more: StreamEvent[];
}

const minute = (iso: string) => iso.slice(0, 16);

/**
 * Fold repeats into one line: a board change, pull request change or save that
 * follows one of the same kind, by the same actor, on the same task, in the
 * same minute. Messages never fold; each one is something someone said.
 */
export function foldEvents(events: StreamEvent[]): StreamLine[] {
  const lines: StreamLine[] = [];
  for (const event of events) {
    const prev = lines[lines.length - 1];
    if (
      prev &&
      event.kind !== "message" &&
      prev.event.kind === event.kind &&
      prev.event.who === event.who &&
      prev.event.episode === event.episode &&
      minute(prev.event.at) === minute(event.at)
    ) {
      prev.more.push(event);
      continue;
    }
    lines.push({ event, more: [] });
  }
  return lines;
}

/** One thread's lane: its column, its color, and the first and last line it spans. */
export interface Lane {
  episode: string;
  column: number;
  from: number;
  to: number;
  color: string;
}

/**
 * Give each thread a lane. A lane runs from the thread's first line to its
 * last, so drawn as a vertical rule it shows when that conversation started
 * and stopped. A column is reused once the thread in it has ended, so the
 * gutter is only as wide as the most threads running at the same time.
 */
export function lanesOf(lines: StreamLine[]): Lane[] {
  const spans = new Map<string, { from: number; to: number }>();
  lines.forEach((line, i) => {
    const ep = line.event.episode;
    if (!ep) return;
    const span = spans.get(ep);
    if (span) span.to = i;
    else spans.set(ep, { from: i, to: i });
  });
  const columnEnds: number[] = [];
  const lanes: Lane[] = [];
  for (const [episode, { from, to }] of spans) {
    let column = columnEnds.findIndex((end) => end < from);
    if (column === -1) column = columnEnds.length;
    columnEnds[column] = to;
    // A thread keeps its own color when it can; two threads on screen at the
    // same time never share one while the palette has a free color.
    const taken = new Set(lanes.filter((l) => l.to >= from).map((l) => l.color));
    const own = laneColor(episode);
    const color = !taken.has(own) ? own : (LANE_COLORS.find((c) => !taken.has(c)) ?? own);
    lanes.push({ episode, column, from, to, color });
  }
  return lanes;
}

const LANE_COLORS = ["#5cc7d2", "#d9a94e", "#b48ae0", "#4fc296", "#e6746f", "#7aa2f7", "#e08ab4", "#a3c46a"];

/** A thread's own color, from its id, so it's the same across reloads. */
export function laneColor(episode: string): string {
  let h = 0;
  for (let i = 0; i < episode.length; i++) h = (h * 31 + episode.charCodeAt(i)) >>> 0;
  return LANE_COLORS[h % LANE_COLORS.length];
}

/** The filters, each a plain fact about an event. */
export interface StreamFilter {
  kinds: ReadonlySet<StreamKind>;
  /** Only messages that mention this handle. */
  mentioning: string | null;
  /** Only this person. */
  who: string | null;
  /** Only this thread, or "channel" for the room's own channel. */
  where: string | null;
}

export const ALL_KINDS: ReadonlySet<StreamKind> = new Set<StreamKind>(["message", "board", "github", "saved"]);

export function matches(event: StreamEvent, filter: StreamFilter): boolean {
  if (!filter.kinds.has(event.kind)) return false;
  if (filter.mentioning && !event.mentions.includes(filter.mentioning.toLowerCase())) return false;
  if (filter.who && event.who !== filter.who) return false;
  if (filter.where === "channel" && event.episode) return false;
  if (filter.where && filter.where !== "channel" && event.episode !== filter.where) return false;
  return true;
}

/** A pull request change, led by the pull request: GitHub reports it, but a
 *  person approved or merged it, so the line doesn't credit "github" with it.
 *  `%s` is the pull request ("PR #12"). */
const PR_WORDS: Record<string, string> = {
  opened: "%s opened",
  review_requested: "review asked on %s",
  approved: "%s approved",
  changes_requested: "changes asked for on %s",
  ci_passed: "CI passed on %s",
  ci_failed: "CI failed on %s",
  merged: "%s merged",
  closed: "%s closed",
};

const BOARD_WORDS: Record<string, string> = {
  filed: "filed",
  claimed: "claimed",
  released: "let go of",
  resolved: "resolved",
  blocked: "marked blocked",
  unblocked: "unblocked",
  expired: "stopped holding (claim expired)",
};

/** What a line says happened, in words, for everything but a message (whose
 *  first line is shown as is). `withTitle: false` leaves the task's title out,
 *  for a line that already shows it in its tag. */
export function describe(event: StreamEvent, { withTitle = true }: { withTitle?: boolean } = {}): string {
  switch (event.kind) {
    case "saved":
      return `saved ${event.text}`;
    case "github": {
      const number = event.ref?.split("#").pop();
      const pr = number ? `PR #${number}` : "the pull request";
      const said = ((event.change && PR_WORDS[event.change]) || "%s changed").replace("%s", pr);
      // A review request names who was asked.
      return event.change === "review_requested" && event.asked.length ? `${said} of ${event.asked.join(", ")}` : said;
    }
    case "board": {
      const what = (event.subkind && BOARD_WORDS[event.subkind]) || event.subkind || "changed";
      const target = withTitle && event.title ? ` ${event.title}` : "";
      const forWhom = event.subkind === "filed" && event.assignee ? ` for ${event.assignee}` : "";
      return `${what}${target}${forWhom}`;
    }
    default:
      return firstLine(event.text);
  }
}

/** The calendar day an ISO time falls on, in this browser's time zone, as
 *  `YYYY-MM-DD`: lines on the same day share it. */
export function dayOf(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/**
 * The words on a date line: "Today", "Yesterday", or the weekday and date
 * ("Thursday, Aug 27"), with the year added when it isn't this year's.
 */
export function dayLabel(iso: string, now: Date = new Date()): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const day = dayOf(iso);
  if (day === dayOf(now.toISOString())) return "Today";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (day === dayOf(yesterday.toISOString())) return "Yesterday";
  return d.toLocaleDateString(undefined, {
    weekday: "long",
    month: "short",
    day: "numeric",
    ...(d.getFullYear() !== now.getFullYear() ? { year: "numeric" } : {}),
  });
}

/** The first non-blank line of a message, without markdown emphasis. */
export function firstLine(text: string): string {
  const line = text.split("\n").find((l) => l.trim() && !/^[-*]\s*$/.test(l.trim())) ?? "";
  return line.trim().replace(/\*\*/g, "");
}
