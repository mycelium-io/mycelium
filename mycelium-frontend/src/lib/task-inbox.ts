// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The bell's model: one entry per task you're involved in, not one per event.
//
// A frame off `/api/notifications/stream` becomes a `TaskEvent` (a board
// notice, a message in a thread, or a mention of you in the room's channel).
// Events fold into a `TaskEntry` per task, which remembers what happened to
// it, whether you're involved, and where its pull request stands. From that,
// `yourMove` says whether the task is waiting on you right now: someone asked
// you something, its pull request is approved with CI green, CI went red on
// your own work, or it's blocked and it's yours. Those are the bell's "Needs
// you" section and the only things that pop up a toast.
//
// Framework-agnostic on purpose, like `notifications.ts`: the provider owns
// fetching and timers, and this stays unit-testable without rendering.

import { parseMentions, parseSilentMentions } from "@/lib/mentions";
import { CHAT_TYPES, unwrapContent } from "@/lib/room-events";
import { isLiveEpisode, noticeOf, pingOf, threadShortId } from "@/lib/threads";

export type TaskEventKind =
  | "filed"
  | "claimed"
  | "released"
  | "resolved"
  | "blocked"
  | "unblocked"
  | "expired"
  | "upstream"
  | "message";

export interface TaskEvent {
  id: string;
  room: string;
  /** The task's thread, or null for something said in the room's channel. */
  episode: string | null;
  /** The board row, when the frame names it (a notice does, a message doesn't). */
  key: string | null;
  title: string | null;
  kind: TaskEventKind;
  /** On an `upstream` notice: what happened to the pull request. */
  change: string | null;
  /** On an `upstream` notice: `owner/repo#123` and its link. */
  ref: string | null;
  url: string | null;
  /** Who did it: the notice's `by`, or the message's sender. */
  actor: string;
  /** On a `filed` notice: who the task is for. */
  assignee: string | null;
  time: string;
  /** A message's text, cut short. */
  text: string | null;
  /** How a message names you: `ask` for `@you` (or sent to you), `silent` for `@~you`. */
  mention: "ask" | "silent" | null;
}

/** Why a task counts as yours to hear about. */
export type Involvement = "filed" | "assigned" | "holds" | "wrote" | "mentioned";

/** Why a task is waiting on you, in the order the bell ranks them. */
export type YourMove = "asks" | "blocked" | "ci_red" | "ready";

export interface PullRequestState {
  ref: string | null;
  url: string | null;
  approved: boolean;
  ci: "passed" | "failed" | null;
  merged: boolean;
}

export interface TaskEntry {
  id: string;
  room: string;
  episode: string | null;
  key: string | null;
  title: string | null;
  /** The newest events, oldest first, capped at {@link MAX_EVENTS}. */
  events: TaskEvent[];
  involvement: Involvement[];
  /** Filed by, assigned to, or held by you or an agent you own, which is what
   *  makes CI going red or a block your move. */
  yours: boolean;
  pr: PullRequestState;
  /** When someone last asked you something here that you haven't answered. */
  askedAt: string | null;
  blocked: boolean;
  settled: boolean;
  updatedAt: string;
  /** When you last opened it from the bell or a toast. */
  seenAt: string | null;
}

/** Who "you" are: your handle, and the handles of the agents you own. */
export interface Me {
  handle: string;
  agents: ReadonlySet<string>;
}

export const MAX_EVENTS = 30;

const bare = (h: string | null | undefined) => (h ?? "").trim().replace(/^@/, "").toLowerCase();

function isMe(handle: string | null | undefined, me: Me): boolean {
  const h = bare(handle);
  return !!h && h === me.handle;
}

function isMine(handle: string | null | undefined, me: Me): boolean {
  const h = bare(handle);
  return !!h && (h === me.handle || me.agents.has(h));
}

/** The entry id a task is kept under: its room and thread, or its row when a
 *  notice has no thread, or the room's channel. */
export function taskIdOf(room: string, episode: string | null, key: string | null): string {
  const short = threadShortId(episode);
  if (short) return `${room}#${short}`;
  if (key) return `${room}#key:${key}`;
  return `${room}#channel`;
}

/** Whether an entry is the room's channel rather than a task. */
export function isChannelEntry(entry: Pick<TaskEntry, "id">): boolean {
  return entry.id.endsWith("#channel");
}

/**
 * The task event a raw frame carries, or null when it isn't one the bell
 * follows: a ping (the thread message itself arrives too), a floor notice,
 * memory and join traffic, or chatter in the room's channel that doesn't name
 * you.
 */
export function taskEventOf(raw: Record<string, unknown>, principal: string): TaskEvent | null {
  const room = raw.room_name as string | undefined;
  if (!room) return null;
  const mtype = (raw.message_type as string) || "";
  // The persister's frames are `l9_exchange`; a message the hub couldn't hand
  // to SLIM is published as its plain chat type instead.
  if (mtype !== "l9_exchange" && !CHAT_TYPES.has(mtype)) return null;
  const content = unwrapContent(raw);
  if (pingOf(content)) return null;
  const time = (raw.created_at as string) || new Date().toISOString();
  const handle = bare(principal);

  const notice = noticeOf(content);
  if (notice) {
    if (notice.subkind === "floor") return null;
    return {
      id: (raw.id as string) || `${room}:${notice.key}:${notice.subkind}:${time}`,
      room,
      episode: notice.episode,
      key: notice.key,
      title: notice.title,
      kind: notice.subkind as TaskEventKind,
      change: notice.change,
      ref: notice.ref,
      url: notice.url,
      actor: bare(notice.by) || "system",
      assignee: notice.assignee ? bare(notice.assignee) : null,
      time,
      text: null,
      mention: null,
    };
  }

  const sender = bare(raw.sender_handle as string) || "system";
  const text =
    typeof content.content === "string" ? content.content : typeof content.text === "string" ? content.text : "";
  const recipient = bare(raw.recipient_handle as string | undefined);
  const asked = (!!handle && recipient === handle) || parseMentions(text).some((h) => bare(h) === handle);
  const named = parseSilentMentions(text).some((h) => bare(h) === handle);
  const mention = sender === handle ? null : asked ? "ask" : named ? "silent" : null;
  const episode = (raw.episode as string | null | undefined) ?? null;
  const inThread = !isLiveEpisode(room, episode);
  // The room's channel reaches the bell only when it names you; a thread's
  // messages all count, since whether you're in that task is decided later.
  if (!inThread && !mention) return null;
  return {
    id: (raw.id as string) || `${room}:${sender}:${time}`,
    room,
    episode: inThread ? episode : null,
    key: null,
    title: null,
    kind: "message",
    change: null,
    ref: null,
    url: null,
    actor: sender,
    assignee: null,
    time,
    text: text.slice(0, 200),
    mention,
  };
}

/** What a row's own fields say about you, read when the bell first meets its
 *  thread: who filed it, who it's for, and who holds it. */
export interface RowFacts {
  key: string;
  title: string;
  createdBy: string | null;
  assignee: string | null;
  holder: string | null;
  settled: boolean;
}

/** A board row's facts, from the memory the hub lists: its title is its first
 *  line (as the hub's notices take it), its holder is `owner`. */
export function rowFactsOf(row: {
  key: string;
  created_by?: string | null;
  content_text?: string;
  value?: unknown;
  meta?: Record<string, unknown> | null;
}): RowFacts {
  // The body is `value`; `content_text` is the text the search index embeds,
  // which can lead with something else.
  const text = typeof row.value === "string" ? row.value : (row.content_text ?? "");
  const first = text.split("\n").find((l) => l.trim()) ?? row.key;
  const meta = row.meta ?? {};
  const str = (v: unknown) => (typeof v === "string" && v ? v : null);
  const status = str(meta.status);
  return {
    key: row.key,
    title: first.replace(/^#+\s*/, "").trim(),
    createdBy: str(row.created_by),
    assignee: str(meta.assignee),
    holder: meta.assignment === "held" ? str(meta.owner) : null,
    settled: status === "resolved" || status === "dismissed",
  };
}

function emptyEntry(id: string, ev: Pick<TaskEvent, "room" | "episode" | "key" | "title" | "time">): TaskEntry {
  return {
    id,
    room: ev.room,
    episode: ev.episode,
    key: ev.key,
    title: ev.title,
    events: [],
    involvement: [],
    yours: false,
    pr: { ref: null, url: null, approved: false, ci: null, merged: false },
    askedAt: null,
    blocked: false,
    settled: false,
    updatedAt: ev.time,
    seenAt: null,
  };
}

function involve(entry: TaskEntry, why: Involvement) {
  if (!entry.involvement.includes(why)) entry.involvement = [...entry.involvement, why];
}

/** Fold a row's own fields into its entry: they can make it yours before any
 *  event has said so. */
export function applyRow(entry: TaskEntry, row: RowFacts, me: Me): TaskEntry {
  const next: TaskEntry = { ...entry, key: entry.key ?? row.key, title: entry.title ?? row.title };
  if (isMine(row.createdBy, me)) involve(next, "filed");
  if (isMine(row.assignee, me)) involve(next, "assigned");
  if (isMine(row.holder, me)) involve(next, "holds");
  next.yours = next.yours || isMine(row.createdBy, me) || isMine(row.assignee, me) || isMine(row.holder, me);
  if (row.settled) next.settled = true;
  return next;
}

/** Fold one event into its task's entry (a new entry when there is none). */
export function applyEvent(entry: TaskEntry | undefined, ev: TaskEvent, me: Me): TaskEntry {
  const id = taskIdOf(ev.room, ev.episode, ev.key);
  const base = entry ?? emptyEntry(id, ev);
  if (base.events.some((e) => e.id === ev.id)) return base;
  const next: TaskEntry = {
    ...base,
    episode: base.episode ?? ev.episode,
    key: base.key ?? ev.key,
    title: ev.title || base.title,
    events: [...base.events, ev].slice(-MAX_EVENTS),
    pr: { ...base.pr },
    updatedAt: ev.time > base.updatedAt ? ev.time : base.updatedAt,
  };

  switch (ev.kind) {
    case "filed":
      if (isMine(ev.actor, me)) {
        involve(next, "filed");
        next.yours = true;
      }
      if (isMine(ev.assignee, me)) {
        involve(next, "assigned");
        next.yours = true;
      }
      break;
    case "claimed":
      if (isMine(ev.actor, me)) {
        involve(next, "holds");
        next.yours = true;
      }
      break;
    case "resolved":
      next.settled = true;
      next.askedAt = null;
      break;
    case "blocked":
      next.blocked = true;
      break;
    case "unblocked":
      next.blocked = false;
      break;
    case "upstream":
      next.pr.ref = ev.ref ?? next.pr.ref;
      next.pr.url = ev.url ?? next.pr.url;
      switch (ev.change) {
        case "approved":
          next.pr.approved = true;
          break;
        case "changes_requested":
          next.pr.approved = false;
          break;
        case "ci_passed":
          next.pr.ci = "passed";
          break;
        case "ci_failed":
          next.pr.ci = "failed";
          break;
        case "merged":
        case "closed":
          next.pr.merged = true;
          break;
        case "opened":
          next.pr = { ...next.pr, approved: false, ci: null, merged: false };
          break;
      }
      break;
    case "message":
      if (isMe(ev.actor, me)) {
        // You answered: whatever was asked of you here has been.
        involve(next, "wrote");
        next.askedAt = null;
      } else if (me.agents.has(bare(ev.actor))) {
        involve(next, "holds");
      }
      if (ev.mention) involve(next, "mentioned");
      if (ev.mention === "ask") next.askedAt = ev.time;
      break;
  }
  return next;
}

/** Whether you hear about this task at all. */
export function isInvolved(entry: TaskEntry): boolean {
  return entry.involvement.length > 0;
}

/** Why the task is waiting on you right now, or null when it isn't. */
export function yourMove(entry: TaskEntry): YourMove | null {
  if (entry.settled) return null;
  if (entry.askedAt) return "asks";
  if (entry.blocked && entry.yours) return "blocked";
  if (entry.pr.merged) return null;
  if (entry.pr.ci === "failed" && entry.yours) return "ci_red";
  if (entry.pr.approved && entry.pr.ci === "passed") return "ready";
  return null;
}

/** Whether something happened since you last opened it. */
export function isUnseen(entry: TaskEntry): boolean {
  return !entry.seenAt || entry.updatedAt > entry.seenAt;
}

/** The words a "your move" wears, in the bell and on a toast. */
export const MOVE_LABEL: Record<YourMove, string> = {
  asks: "Asks you",
  blocked: "Blocked",
  ci_red: "CI red",
  ready: "Ready to merge",
};

/** The color a "your move" wears: accent for a question, red for something
 *  broken, yellow for stuck, green for ready. */
export const MOVE_TONE: Record<YourMove, string> = {
  asks: "var(--accent)",
  blocked: "var(--yellow)",
  ci_red: "var(--red)",
  ready: "var(--green)",
};

const UPSTREAM_STEP: Record<string, string> = {
  opened: "PR opened",
  review_requested: "review asked",
  approved: "approved",
  changes_requested: "changes requested",
  ci_failed: "CI red",
  ci_passed: "CI green",
  merged: "merged",
  closed: "PR closed",
};

/** One event as a step in the entry's chain ("PR opened → approved → …"). */
export function stepOf(ev: TaskEvent): string {
  switch (ev.kind) {
    case "upstream":
      return (ev.change && UPSTREAM_STEP[ev.change]) || "PR updated";
    case "filed":
      return "filed";
    case "claimed":
      return `${ev.actor} claimed`;
    case "message":
      if (ev.mention === "ask") return `${ev.actor} asked you`;
      if (ev.mention === "silent") return `${ev.actor} named you`;
      return `${ev.actor} wrote`;
    default:
      return ev.kind;
  }
}

/**
 * The entry's recent history as a chain of steps, newest last: repeats folded
 * ("3 messages" rather than three "wrote"s), at most `max` steps, and the
 * task's move appended when it has one ("→ ready to merge").
 */
export function chainOf(entry: TaskEntry, max = 4): string[] {
  const steps: string[] = [];
  let run = 0;
  for (const ev of entry.events) {
    const step = stepOf(ev);
    const prev = steps[steps.length - 1];
    if (ev.kind === "message" && !ev.mention && prev !== undefined && /( wrote|\d+ messages)$/.test(prev)) {
      run += 1;
      steps[steps.length - 1] = `${run + 1} messages`;
      continue;
    }
    run = 0;
    if (step !== prev) steps.push(step);
  }
  const move = yourMove(entry);
  if (move && move !== "asks") steps.push(MOVE_LABEL[move].toLowerCase());
  return steps.length > max ? ["…", ...steps.slice(-max)] : steps;
}

/** The newest question put to you here, for a toast or the bell to quote. */
export function lastAsk(entry: TaskEntry): TaskEvent | null {
  for (let i = entry.events.length - 1; i >= 0; i--) {
    if (entry.events[i].mention === "ask") return entry.events[i];
  }
  return null;
}

/** The entry's display name: its task's title, else what's known about it. */
export function entryTitle(entry: TaskEntry): string {
  if (entry.title) return entry.title;
  if (isChannelEntry(entry)) return `${entry.room} channel`;
  return entry.key ?? "A thread";
}

/** Where opening an entry goes: its thread in its room, or the room. */
export function entryHref(entry: TaskEntry): string {
  const room = `/room/${encodeURIComponent(entry.room)}`;
  const short = threadShortId(entry.episode);
  return short ? `${room}?focus=${encodeURIComponent(`episode:${short}`)}` : room;
}

/** The bell's two sections: what waits on you, ranked by kind then newest,
 *  and everything else you're in, newest first. */
export function sortEntries(entries: TaskEntry[]): { needsYou: TaskEntry[]; earlier: TaskEntry[] } {
  const rank: Record<YourMove, number> = { asks: 0, blocked: 1, ci_red: 2, ready: 3 };
  const involved = entries.filter(isInvolved);
  const newest = (a: TaskEntry, b: TaskEntry) => (a.updatedAt < b.updatedAt ? 1 : a.updatedAt > b.updatedAt ? -1 : 0);
  const needsYou = involved
    .filter((e) => yourMove(e) !== null)
    .sort((a, b) => rank[yourMove(a)!] - rank[yourMove(b)!] || newest(a, b));
  const earlier = involved.filter((e) => yourMove(e) === null).sort(newest);
  return { needsYou, earlier };
}

/** Keep the store bounded: every involved entry first, newest first, then the
 *  uninvolved ones (kept so a pull request's state is known if you join later). */
export function pruneEntries(entries: TaskEntry[], max = 150): TaskEntry[] {
  if (entries.length <= max) return entries;
  const newest = (a: TaskEntry, b: TaskEntry) => (a.updatedAt < b.updatedAt ? 1 : -1);
  const involved = entries.filter(isInvolved).sort(newest);
  const rest = entries.filter((e) => !isInvolved(e)).sort(newest);
  return [...involved, ...rest].slice(0, max);
}

const ENTRIES_KEY = "mycelium.task-inbox";

export function loadEntries(): TaskEntry[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(ENTRIES_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveEntries(entries: TaskEntry[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ENTRIES_KEY, JSON.stringify(pruneEntries(entries)));
  } catch {
    // Best-effort, like the rest of the notification store.
  }
}
