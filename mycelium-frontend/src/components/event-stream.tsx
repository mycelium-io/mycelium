// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  fetchL9History,
  fetchMessages,
  logFetchError,
} from "@/lib/api";
import { useRoomAgents, useRoomRowNames, useRoomThreads, type RowNaming, type ThreadOwner } from "@/lib/room-data";
import { NOTICE_TYPE, PING_TYPE, isLiveEpisode, noticeLabel, noticeOf, pingOf, threadShortId } from "@/lib/threads";
import { useRoomConnected, useRoomStream } from "@/lib/stream-hub";
import { MessageBody } from "@/components/message-body";
import { ChatFindBar } from "@/components/chat-find-bar";
import { ChatMinimap, type MinimapTick } from "@/components/chat-minimap";
import { HighlightText } from "@/components/ui/highlight-text";
import { hasMatch, stepIndex } from "@/lib/chat-search";
import { RoomBoard } from "@/components/board/room-board";
import { ActivityRail, type ActivityItem } from "@/components/activity-rail";
import { EpisodeTag } from "@/components/episode-tag";
import { L9Inspector } from "@/components/l9-inspector";
import { RoomA2aView } from "@/components/room-a2a";
import { RoomSlimView } from "@/components/room-slim";
import { EmptyState } from "@/components/empty-state";
import { KeyBadge } from "@/components/key-badge";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Monogram } from "@/components/ui/monogram";
import { Tooltip } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { ArrowDown, Bot, Loader2, MessageSquare, MessagesSquare } from "lucide-react";

interface Event {
  /** Render key only — synthesized, so a message republished by a status
   *  transition can't collide with the row it updates. */
  id: string;
  /** The backend's id for this message, where it has one. Stable across reads
   *  (the transcript derives it from the envelope id), which is what a search
   *  result points at. */
  messageId: string | null;
  type: string;
  content: string;
  sender: string;
  recipient: string | null;
  time: string;
  /** The full stamp, for ordering two reads into one feed. */
  at: string;
  // The L9 episode URN this event belongs to, when it rode one. Negotiation
  // turns share their mediator's episode; casual chat carries the room default
  // or none. Lets the feed group/fold one negotiation's turns together.
  episode: string | null;
  /** The id of the message this one revises, when it is an amendment. The feed
   *  folds it into that message rather than showing it as a row of its own. */
  amends: string | null;
  /** True once an amendment has revised this message's text. */
  edited: boolean;
  /** The thread a **ping** is about — never the episode the ping itself rode,
   *  which is the room. Null on everything that is not a ping. */
  thread: string | null;
  /** Who wrote in the thread, on a ping. The row's own sender is the system
   *  that raised it, which is nobody, so the writer is read from the payload. */
  pingSenders: string[];
  raw: Record<string, unknown>;
}

const CHAT_TYPES = new Set(["broadcast", "direct", "announce", "delegate"]);

/** Stable empties: find writes these back on every close, and a fresh array
 *  each time would re-run the effects that read them. */
const NO_MATCHES: string[] = [];
const NO_TICKS: MinimapTick[] = [];

/** The rendered row for a message, found by the id it carries in the DOM.
 *  A scan rather than a selector: an event id is synthesized, and escaping one
 *  into an attribute selector is a sharper edge than walking a handful of
 *  nodes. */
function rowNode(root: HTMLElement | null, id: string): HTMLElement | null {
  if (!root) return null;
  for (const node of root.querySelectorAll<HTMLElement>("[data-event-id]")) {
    if (node.dataset.eventId === id) return node;
  }
  return null;
}

// The L9 "raise-up" whitelist: message types promoted from the L9 inspector
// into the primary channel/chat surface. This must mirror
// contracts/l9-surface.json's `raise_up_types` byte-for-byte — the CLI
// (mycelium-cli/src/mycelium/commands/room.py) carries an independent copy,
// and event-stream.contract.test.ts asserts both stay in sync with the
// contract so the two surfaces can't silently drift apart.
export const L9_RAISE_UP_TYPES = [
  "coordination_join",
  "coordination_consensus",
  "l9_knowledge",
];

// Event types that appear in the chat-channel view alongside real chat.
// Joins + consensus belong here so the room's chat surface narrates the
// negotiation lifecycle ("alice joined session X", "CONSENSUS in session X
// → 4 work rows", "TIMEOUT in session X, no agreement") instead of
// burying it all under the EVENTS tab.
const CHANNEL_VIEW_TYPES = new Set([...CHAT_TYPES, ...L9_RAISE_UP_TYPES, PING_TYPE, NOTICE_TYPE]);

// Lifecycle events that render as slim system notices (not chat rows). Used to
// decide message grouping: a chat message only groups under the sender above it
// when no system notice interrupts the run.
/**
 * A ping is a system notice too, but deliberately not on the shared raise-up
 * list: that list names message types both surfaces promote out of the L9
 * inspector, and a ping is an `l9_exchange` already on the chat path that is
 * *renamed* here — the same branch the CLI takes inside `chat_line`. Adding it
 * to the contract would claim a drift that isn't one.
 */
const SYSTEM_TYPES = new Set([...L9_RAISE_UP_TYPES, PING_TYPE, NOTICE_TYPE]);

/** Skeleton loader for chat rows. */
function ChannelSkeleton() {
  const widths = ["w-3/5", "w-2/5", "w-1/2"];
  return (
    <div className="flex flex-col gap-5 px-5 py-4">
      {widths.map((w, i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="size-8 flex-shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 pt-0.5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className={`mt-2 h-3 ${w}`} />
          </div>
        </div>
      ))}
    </div>
  );
}

/** A quiet, centered lifecycle line woven into the conversation. */
function SystemNotice({
  time,
  dot,
  label,
  labelColor,
  strong,
  children,
  trailing,
}: {
  time: string;
  dot: string;
  label?: string;
  labelColor?: string;
  strong?: boolean;
  children: React.ReactNode;
  /** Held out of the truncating run, so a control here survives a long title. */
  trailing?: React.ReactNode;
}) {
  return (
    <div className="group mt-3 flex items-center gap-2 px-5 py-1 text-micro text-muted-foreground first:mt-0">
      <span aria-hidden className="inline-block size-1.5 flex-shrink-0 rounded-full" style={{ background: dot }} />
      {label && (
        <span
          className={`flex-shrink-0 whitespace-nowrap ${strong ? "font-semibold" : "font-medium"}`}
          style={{ color: labelColor ?? "var(--muted-foreground)" }}
        >
          {label}
        </span>
      )}
      <span className="flex min-w-0 items-center gap-1.5 truncate">{children}</span>
      {trailing}
      <span className="ml-auto flex-shrink-0 tabular text-faint opacity-0 transition-opacity group-hover:opacity-100">
        {time.slice(0, 5)}
      </span>
    </div>
  );
}

function parseEvent(msg: Record<string, unknown>, room: string): Event {
  let mtype = (msg.message_type as string) || (msg.type as string) || "unknown";
  const sender = (msg.sender_handle as string) || (msg.updated_by as string) || "?";
  const recipient = (msg.recipient_handle as string) || null;
  const created = (msg.created_at as string) || new Date().toISOString();
  const time = created.slice(11, 19);

  let content = "";
  let raw: Record<string, unknown> = {};
  let thread: string | null = null;
  let pingSender: string | null = null;

  try {
    if (typeof msg.content === "string") {
      // Chat messages carry a plain string in content; coordination events
      // carry a JSON blob. Try to parse, fall back to the raw string.
      if (CHAT_TYPES.has(mtype)) {
        raw = { text: msg.content };
      } else {
        raw = JSON.parse(msg.content);
      }
    } else if (msg.content) {
      raw = msg.content as Record<string, unknown>;
    } else {
      raw = msg;
    }
  } catch {
    raw = CHAT_TYPES.has(mtype) ? { text: msg.content } : msg;
  }

  switch (mtype) {
    case "broadcast":
    case "direct":
    case "announce":
    case "delegate":
      content = (raw.text as string) || (msg.content as string) || "";
      break;
    case "coordination_join": {
      const handle = (raw.handle as string) || sender;
      const intent = raw.intent as string;
      content = `${handle} joined${intent ? `: ${intent}` : ""}`;
      break;
    }
    case "coordination_start":
      content = `Episode started with ${raw.agent_count || "?"} agents`;
      break;
    case "coordination_tick": {
      // Ticks wrap their fields under .payload
      const tick = (raw.payload as Record<string, unknown>) || raw;
      const round = tick.round ?? "?";
      const action = tick.action ?? "tick";
      const participant = tick.participant_id ?? "?";
      content = `Round ${round}: ${participant} → ${action}`;
      if (tick.current_offer) content += ` ${JSON.stringify(tick.current_offer)}`;
      break;
    }
    case "coordination_consensus": {
      const broken = raw.broken === true;
      const assignments = raw.assignments as Record<string, string>;
      const tasks = Array.isArray(raw.tasks) ? (raw.tasks as string[]) : [];
      content = "";
      if (assignments) content += Object.entries(assignments).map(([k, v]) => `${k}=${v}`).join(", ");
      // Consensus isn't the end; it compiles into work the room can pick up.
      if (!broken && tasks.length) {
        content += ` · compiled → ${tasks.length} ${tasks.length === 1 ? "row" : "rows"}`;
      }
      {
        const metrics = raw.metrics as Record<string, unknown> | undefined;
        const gar = metrics && typeof metrics === "object" ? metrics.gar : undefined;
        if (typeof gar === "number" && Number.isFinite(gar)) content += ` · GAR ${gar.toFixed(2)}`;
      }
      break;
    }
    case "memory_changed": {
      const key = (raw.key || msg.key) as string;
      const version = (raw.version || msg.version) as number;
      const by = (raw.updated_by || msg.updated_by) as string;
      content = `${key} v${version} by ${by}`;
      break;
    }
    case "l9_exchange": {
      // A ping rides the exchange kind like everything else, so it has to be
      // recognised before the prose unwrap below — which would otherwise turn
      // it into an empty chat row from `system`, the one shape a thread exists
      // to keep out of the room.
      const ping = pingOf(raw);
      if (ping) {
        thread = ping.episode;
        pingSender = ping.sender;
        mtype = PING_TYPE;
        break;
      }
      // A board event — a task filed, claimed, handed back, resolved — rides the
      // same exchange kind, named before the prose unwrap for the same reason a
      // ping is: it is a notice about the board, not a chat row. `thread` holds
      // the task's own thread to open.
      const notice = noticeOf(raw);
      if (notice) {
        thread = notice.episode;
        content = notice.title ?? notice.key;
        mtype = NOTICE_TYPE;
        raw = { ...raw, taskKey: notice.key, by: notice.by, kind: notice.kind, subkind: notice.subkind, for: notice.assignee };
        break;
      }
      // The live SSE stream wraps human/agent messages as an L9 exchange
      // envelope, while the REST snapshot (loaded on mount/refresh) delivers the
      // same message as a plain "broadcast". Unwrap the prose and normalise to
      // the chat shape so the live feed matches a refresh instead of silently
      // dropping the message.
      content = (raw.content as string) || "";
      mtype = recipient ? "direct" : "broadcast";
      break;
    }
    case "l9_commit": {
      // Unwrap the L9 commit envelope into the coordination_consensus shape
      // the channel notice row and the L9 inspector both read.
      const l9env = (raw.l9 as Record<string, unknown> | undefined) ?? {};
      const header = (l9env.header as Record<string, unknown> | undefined) ?? {};
      const payload = (l9env.payload as Record<string, unknown> | undefined) ?? {};
      const data = (payload.data as Record<string, unknown> | undefined) ?? {};
      const message = header.message as Record<string, unknown> | undefined;
      content = (raw.content as string) || "";
      raw = {
        ...raw,
        broken: header.subkind !== "converged",
        assignments: data.assignments,
        metrics: data.metrics,
        episode: message?.episode,
      };
      mtype = "coordination_consensus";
      break;
    }
    case "l9_knowledge": {
      // A memory push (e.g. a compiled task landing in the room) rides as
      // an L9 "knowledge" envelope. Recognized as its own system notice rather
      // than falling to the unhandled-type fallback.
      const l9env = (raw.l9 as Record<string, unknown> | undefined) ?? {};
      const payload = (l9env.payload as Record<string, unknown> | undefined) ?? {};
      const data = (payload.data as Record<string, unknown> | undefined) ?? {};
      content = (raw.content as string) || `${(data.key as string) ?? "memory"} updated`;
      raw = { ...raw, key: data.key, updated_by: data.updated_by, version: data.version };
      break;
    }
    default:
      // A message type nothing above handles would otherwise vanish from the
      // channel view without a trace (exactly how l9_exchange hid). Surface it
      // loudly so an unsupported/renamed type can't fail silently again.
      console.warn(
        `[mycelium] EventStream: unhandled message_type "${mtype}" — ` +
          "rendered as a raw fallback and likely hidden from the channel view",
        msg,
      );
      content = (msg.content as string) || JSON.stringify(msg).slice(0, 100);
  }

  const episode =
    (msg.episode as string) ||
    ((raw.header as Record<string, unknown> | undefined)?.message as
      | Record<string, unknown>
      | undefined)?.episode as string ||
    null;

  // An amendment names the message it revises: over SSE that's the L9 envelope's
  // subkind + parents, on the REST snapshot the backend has already folded it and
  // only the `edited_at` stamp survives.
  const l9header = ((raw.l9 as Record<string, unknown> | undefined)?.header ??
    {}) as Record<string, unknown>;
  const parents = (l9header.message as Record<string, unknown> | undefined)?.parents;
  const amends =
    l9header.subkind === "amend" && Array.isArray(parents) && typeof parents[0] === "string"
      ? (parents[0] as string)
      : typeof msg.amends === "string"
        ? msg.amends
        : null;

  return {
    id: `${Date.now()}-${Math.random()}`,
    messageId: typeof msg.id === "string" ? msg.id : null,
    type: mtype,
    content,
    sender,
    recipient,
    time,
    at: created,
    episode,
    amends,
    edited: typeof msg.edited_at === "string",
    thread,
    pingSenders: pingSender ? [pingSender] : [],
    raw,
  };
}

/**
 * Whether this event's prose belongs to a thread rather than to the room.
 *
 * Only prose: a thread absorbs the argument, not the outcome. A consensus or a
 * join is the room's business however deep inside a task it happened, which is
 * why the raise-up notices are not asked this question — the same split the CLI
 * makes by consulting its own `in_a_thread` from the chat branch alone.
 */
function inAThread(event: Event, room: string): boolean {
  return CHAT_TYPES.has(event.type) && !isLiveEpisode(room, event.episode);
}

/**
 * Whether this row is the room *doing* something rather than saying it.
 *
 * A room under load raises far more state than speech: a task being worked
 * writes memory, pings its thread and moves on the board, and none of it is
 * something anybody wrote. Woven into the feed, that is a changelog with the
 * conversation buried in it — so it is lifted out into {@link ActivityRail},
 * which holds a fixed number of rows however busy the room gets.
 *
 * A board notice included, its arrival and its outcome with the rest. Keeping
 * those two in the feed scattered a task across three places: its filing folded
 * into a cross-task "New tasks" line, its resolve into a "Resolved" one, and
 * everything in between onto its rail row — so the row nobody could read as
 * *created → worked → resolved* was the row the work actually happened on. One
 * subject, one place, in order.
 */
function isActivity(event: Event): boolean {
  return event.type === PING_TYPE || event.type === "l9_knowledge" || event.type === NOTICE_TYPE;
}

/**
 * What a row is *about*, so activity can be grouped by it.
 *
 * The room's task key, wherever the room knows one — that is what makes a
 * thread's ping, the board's notice about that task and the memory write behind
 * it fold into one entry instead of three ways of saying the same task moved. A
 * thread no single row is bound to is its own subject; naming it after one of
 * several rows would be picking at random.
 */
function subjectOf(event: Event, threads: Map<string, ThreadOwner>): string | null {
  if (event.type === PING_TYPE && event.thread) {
    const owner = threads.get(event.thread);
    return owner && owner.keys.length === 1 ? owner.keys[0] : event.thread;
  }
  if (event.type === NOTICE_TYPE) return (event.raw.taskKey as string) || null;
  if (event.type === "l9_knowledge") {
    const key = (event.raw.key as string) || null;
    // An agent writing its own manifest is the roster's news, and the Members
    // rail already carries it. In a room of seven agents it is otherwise seven
    // lines saying somebody arrived.
    return key && !key.startsWith("agents/") ? key : null;
  }
  return null;
}

/**
 * What to call a subject, and the thread that opens it.
 *
 * Read off the room's own rows, so a task reads in the feed as the name it
 * carries on the board rather than as its `work/…` slug. A notice carries its
 * own copy of both, which is what answers for a subject the room's memories do
 * not have — one filed a moment ago, or one since removed.
 */
function nameActivity(
  subject: string,
  members: Event[],
  threads: Map<string, ThreadOwner>,
  rows: Map<string, RowNaming>,
): { title: string; episode: string | null } {
  const noticed = members.find((m) => m.type === NOTICE_TYPE)?.content;
  if (subject.startsWith("urn:")) {
    const owner = threads.get(subject);
    return {
      title: owner?.title ?? noticed ?? threadShortId(subject) ?? "thread",
      episode: subject,
    };
  }
  const row = rows.get(subject);
  return {
    title: row?.title ?? noticed ?? subject,
    episode: row?.episode ?? members.find((m) => m.thread)?.thread ?? null,
  };
}

/** Who moved a subject, in the order they first did. A ping's own sender is the
 *  system that raised it, which is nobody, so its writers come off the payload. */
function actorsOf(members: Event[]): string[] {
  const who: string[] = [];
  for (const ev of members) {
    const from =
      ev.type === PING_TYPE
        ? ev.pingSenders
        : ev.type === NOTICE_TYPE
          ? [ev.raw.by as string | undefined]
          : ev.type === "l9_knowledge"
            ? [ev.raw.updated_by as string | undefined]
            : [ev.sender];
    for (const handle of from) if (handle && !who.includes(handle)) who.push(handle);
  }
  return who;
}

/** One folded event, as it reads once a block is opened up. */
function activityLine(ev: Event): { label: string; detail: string } {
  if (ev.type === PING_TYPE) {
    const who = ev.pingSenders.filter(Boolean);
    return { label: "Activity", detail: who.map((h) => `@${h}`).join(", ") || "a message landed" };
  }
  if (ev.type === NOTICE_TYPE) {
    const by = ev.raw.by as string | undefined;
    return {
      label: noticeLabel((ev.raw.subkind as string) || "filed", ev.raw.kind as string | undefined),
      detail: by ? `@${by}` : "",
    };
  }
  if (ev.type === "l9_knowledge") {
    const version = ev.raw.version;
    const by = ev.raw.updated_by as string | undefined;
    return {
      label: "Knowledge",
      detail: [typeof version === "number" ? `v${version}` : "", by ? `@${by}` : ""]
        .filter(Boolean)
        .join(" · "),
    };
  }
  return { label: ev.type, detail: ev.sender };
}

/** A reader a couple of lines off the bottom still counts as reading the tail,
 *  so a stray wheel tick doesn't detach them. */
const PIN_TOLERANCE_PX = 64;

/** One page of the channel, on both of its reads.
 *
 *  The two used to disagree: the prose took the backend's default (50) while the
 *  control frames took 200, so the conversation was the shallower half of a feed
 *  assembled from both — and in a busy room the newest fifty are the churn, which
 *  is how a room with hundreds of messages in it read as having none. Same page
 *  size on both reads, and every older page is fetched the same way. */
const CHANNEL_PAGE = 200;

/** How close to the top of the viewport counts as asking for the page before. */
const LOAD_OLDER_MARGIN_PX = 240;

/** The two reads the channel is assembled from, as one page of it.
 *
 *  `/messages` is what the room *said*; the L9 replay is where a ping and a
 *  board notice survive, and neither reaches the conversational read. So a page
 *  is both, merged by time — the initial window and every older one land here.
 *
 *  Dedup is by the backend's id, because the live stream never stops while you
 *  are reading back: a page can overlap rows that arrived over SSE, and an
 *  amendment already folded into a message on screen would otherwise unfold
 *  itself into a second copy. An event with no id is kept — there is nothing to
 *  compare it by, and dropping it would lose a row to save a duplicate. */
function mergePage(existing: Event[], page: Event[]): Event[] {
  const seen = new Set(existing.map((e) => e.messageId).filter(Boolean));
  const fresh = page.filter((e) => !e.messageId || !seen.has(e.messageId));
  if (fresh.length === 0) return existing;
  return [...existing, ...fresh].sort((a, b) => (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0));
}

/** The earliest stamp in a page — the cursor the page before it is fetched by. */
function oldestAt(page: Event[]): string | null {
  let oldest: string | null = null;
  for (const event of page) {
    if (!Date.parse(event.at)) continue;
    if (oldest === null || Date.parse(event.at) < Date.parse(oldest)) oldest = event.at;
  }
  return oldest;
}

/** Fold an amendment into the message it revises, or keep it as its own row.
 *
 *  The backend folds a cold read; the live stream carries the amendment as the
 *  message it is, so the open tab has to fold it too or it reads as the sender
 *  repeating themselves. An amendment that matches nothing here (its target
 *  scrolled out of this window, or came from someone else) stays visible rather
 *  than being dropped — the same rule the read path follows. */
function foldAmendment(events: Event[], amendment: Event): Event[] {
  const target = events.findIndex(
    (e) =>
      e.messageId === amendment.amends &&
      e.sender === amendment.sender &&
      e.amends === null,
  );
  if (target === -1) return [...events, amendment];
  return events.map((e, i) =>
    i === target ? { ...e, content: amendment.content, edited: true } : e,
  );
}

export type View = "channel" | "board" | "network";

interface Props {
  roomName: string;
  onMemoryChanged?: () => void;
  onConnectionChange?: (connected: boolean) => void;
  /** Open a memory by key — wired to `[[wikilinks]]` in chat so a message can
   *  link a room's memory and a reader (or agent author) can jump straight to it. */
  onOpenMemory?: (key: string) => void;
  /** Open a thread by its episode URN — from a ping in the channel, from the
   *  board row the thread belongs to, or from an episode tag on a coordination
   *  notice. */
  onOpenThread?: (episode: string) => void;
  /** Optional controlled tab (e.g. driven by the onboarding tour). */
  view?: View;
  onViewChange?: (view: View) => void;
  /** A message to reveal in the channel, arrived at from search. */
  focusMessageId?: string | null;
  onFocusConsumed?: () => void;
  /** Bumped by the room's ⌘F binding to open (or re-focus) the find bar. The
   *  page owns the key because it owns the pane switch that has to happen
   *  first; the channel owns the search itself. */
  openFind?: number;
}

export function EventStream({ roomName, onMemoryChanged, onConnectionChange, onOpenMemory, onOpenThread, view: viewProp, onViewChange, focusMessageId = null, onFocusConsumed, openFind = 0 }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const connected = useRoomConnected(roomName);

  // Surface connection state to status bar; one home for the signal.
  useEffect(() => {
    onConnectionChange?.(connected);
  }, [connected, onConnectionChange]);
  const [viewInternal, setViewInternal] = useState<View>("channel");
  const view = viewProp ?? viewInternal;
  const setView = (v: View) => { if (viewProp === undefined) setViewInternal(v); onViewChange?.(v); };
  const scrollRef = useRef<HTMLDivElement>(null);

  // Know which senders are registered agents (to badge their replies) and whom
  // each belongs to (to attribute them inline). Off the room's shared agent
  // read, so this costs no request of its own; owner is resolved at render time
  // so it always reflects the current manifest, never a stale stamp.
  const { agents } = useRoomAgents(roomName);
  // Which task each thread belongs to, so a ping can name the row rather than
  // six characters of URN. Off the room's shared memory read, so it costs
  // nothing; a thread no row is bound to simply has no name to give.
  const threads = useRoomThreads(roomName);
  // And what each row is called, so a notice, a ping and a memory push about one
  // task all print its name rather than three shapes of its key.
  const rowNames = useRoomRowNames(roomName);
  const agentHandles = useMemo(() => new Set(agents.map((a) => a.handle)), [agents]);
  const agentOwners = useMemo(
    () => new Map(agents.filter((a) => a.owner).map((a) => [a.handle, a.owner as string])),
    [agents],
  );

  // Where reading back has got to: the cursor the next older page is asked for,
  // whether both reads have run out, and whether one is in flight. Refs rather
  // than state because the scroll handler reads them on every wheel tick and
  // must not be re-bound to see the current values.
  const older = useRef({ cursor: null as string | null, exhausted: false, loading: false });
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [reachedStart, setReachedStart] = useState(false);
  // Distance from the bottom, captured before a prepend and restored after it.
  // The distance from the *top* is what the new page changes, which is why the
  // view would otherwise jump the moment older messages landed above it.
  const anchor = useRef<number | null>(null);

  // Two reads, one feed.
  //
  // The room's messages are what was *said*; a ping is a control frame and the
  // conversational read leaves it out by construction — which would mean the
  // channel's account of a busy thread survived only as long as the tab that
  // watched it land. The transcript's L9 replay is where a ping does survive, so
  // the pings are lifted out of it and merged back in by time. Everything else
  // in that replay already reaches the feed as a message, so only pings are
  // taken; reading both is what makes a reload say what the room said.
  //
  // Both are paged, and this is what a page is: the window a room opens on, and
  // every older one behind it.
  const readPage = useCallback(
    async (before: string | null) => {
      const [data, frames] = await Promise.all([
        fetchMessages(roomName, CHANNEL_PAGE, { before }),
        fetchL9History(roomName, CHANNEL_PAGE, before),
      ]);
      const said = (data.messages || []).map((m) => parseEvent(m, roomName));
      const notices = frames
        .map((frame) => parseEvent(frame, roomName))
        .filter((e) => e.type === PING_TYPE || e.type === NOTICE_TYPE);
      // `total` counts everything older than the cursor, so a page shorter than
      // it is the honest end of the prose. The replay carries no such count, so
      // a short page is the only thing it can say — one wasted request at the
      // start of the room, against paging a room forever.
      const more = (data.total ?? said.length) > said.length || frames.length >= CHANNEL_PAGE;
      return { page: [...said, ...notices], more };
    },
    [roomName],
  );

  useEffect(() => {
    let live = true;
    older.current = { cursor: null, exhausted: false, loading: false };
    readPage(null)
      .then(({ page, more }) => {
        if (!live) return;
        older.current.cursor = oldestAt(page);
        older.current.exhausted = !more || older.current.cursor === null;
        setReachedStart(older.current.exhausted);
        setEvents([...page].sort((a, b) => (Date.parse(a.at) || 0) - (Date.parse(b.at) || 0)));
        setHistoryLoaded(true);
      })
      .catch((err) => {
        logFetchError("fetchMessages")(err);
        if (live) setHistoryLoaded(true);
      });
    return () => {
      live = false;
    };
  }, [roomName, readPage]);

  // The page before the one on screen, fetched when the reader nears the top.
  //
  // Keyed off the oldest message loaded rather than an offset: the live stream
  // never stops, and every offset in the room shifts under a message arriving
  // while you read back. A page lands prepended, with the scroll position
  // anchored to what was already there, so reaching the top reveals history
  // instead of moving it.
  const loadOlder = useCallback(() => {
    const state = older.current;
    if (state.loading || state.exhausted || !state.cursor) return;
    const el = scrollRef.current;
    if (!el) return;
    state.loading = true;
    setLoadingOlder(true);
    const from = el.scrollHeight - el.scrollTop;
    readPage(state.cursor)
      .then(({ page, more }) => {
        const cursor = oldestAt(page);
        // No cursor means the page carried nothing datable to ask before, so
        // there is no next request to make even if the room has more.
        state.exhausted = !more || cursor === null;
        if (cursor) state.cursor = cursor;
        if (state.exhausted) setReachedStart(true);
        anchor.current = from;
        setEvents((prev) => mergePage(prev, page));
      })
      .catch(logFetchError("fetchMessages"))
      .finally(() => {
        state.loading = false;
        setLoadingOlder(false);
      });
  }, [readPage]);

  // Live room messages, off the app's one multiplexed connection.
  useRoomStream(roomName, (data) => {
    const msg = data as Record<string, unknown>;
    const event = parseEvent(msg, roomName);
    setEvents(prev => (event.amends ? foldAmendment(prev, event) : [...prev, event]));
    if (event.type === "memory_changed") onMemoryChanged?.();
    // A consensus compiles the negotiation into work rows, so nudge the
    // room's caches to refetch and surface them immediately.
    if (event.type === "coordination_consensus" && event.raw.broken !== true) {
      onMemoryChanged?.();
    }
    // Presence changes: refresh the room's derived state (agent roster/count).
    if (event.type === "coordination_join" || event.type === "coordination_leave") {
      onMemoryChanged?.();
    }
  });

  // The room's own timeline, split by what it is: a thread's prose is dropped
  // (it is not lost, it is placed, and the pane the ping opens is where it
  // reads), everything the room raised about a task goes up to that task's rail
  // row, and what is left in the feed is what people actually said.
  const inChannel = useMemo(
    () => events.filter(e => CHANNEL_VIEW_TYPES.has(e.type) && !inAThread(e, roomName)),
    [events, roomName],
  );

  const visible = useMemo(() => inChannel.filter(e => !isActivity(e)), [inChannel]);

  // What the room has been doing, one entry per task rather than one per frame.
  // No window here: the rail is the room's current state, so a task that has
  // been written to all morning is one row that keeps moving up, never a row
  // per burst. Sorted by what moved last, which is the order a reader wants.
  const activity = useMemo<ActivityItem[]>(() => {
    const bySubject = new Map<string, Event[]>();
    for (const event of inChannel) {
      if (!isActivity(event)) continue;
      const subject = subjectOf(event, threads);
      if (!subject) continue;
      const group = bySubject.get(subject);
      if (group) group.push(event);
      else bySubject.set(subject, [event]);
    }
    return [...bySubject.entries()]
      .map(([subject, members]) => {
        const latest = members[members.length - 1];
        const { title, episode } = nameActivity(subject, members, threads, rowNames);
        // The last board move the task made is the state it is standing in —
        // the one thing about a row worth seeing without opening it.
        const standing = [...members]
          .reverse()
          .find((m) => m.type === NOTICE_TYPE)?.raw.subkind as string | undefined;
        return {
          subject,
          title,
          episode,
          // A thread nobody's row is bound to has no details to open — the
          // conversation is the whole of what the room knows about it.
          memoryKey: subject.startsWith("urn:") ? null : subject,
          actors: actorsOf(members),
          time: latest.time,
          standing: standing ?? null,
          updates: members.map((member) => {
            const { label, detail } = activityLine(member);
            return { id: member.id, time: member.time, label, detail };
          }),
          at: Date.parse(latest.at) || 0,
        };
      })
      .sort((a, b) => {
        // A blocked row is the one thing here that is asking for somebody. The
        // rail shows three at a time, so leaving it in date order would let a
        // blocker sit behind "N more" precisely when it is waiting on a human.
        const stalled = (x: { standing: string | null }) => (x.standing === "blocked" ? 0 : 1);
        return stalled(a) - stalled(b) || b.at - a.at;
      });
  }, [inChannel, threads, rowNames]);

  // Arriving from search: mark the named message and scroll it into sight once
  // history has landed. The mark outlives the request that carried it — a
  // highlight cleared with the URL parameter would be gone before it was read.
  const [highlight, setHighlight] = useState<string | null>(null);
  const highlightRow = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focusMessageId) return;
    // The highlight outlives focusMessageId, which is cleared once consumed.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHighlight(focusMessageId);
    onFocusConsumed?.();
  }, [focusMessageId, onFocusConsumed]);

  // ── Find in the channel ────────────────────────────────────────────────
  //
  // ⌘F is taken off the browser here rather than left alone, because the
  // browser's own find reads the DOM and the channel is a window onto a paged
  // feed: it would search whatever happened to be mounted, silently, with no
  // way to say so. This one searches the messages the channel has actually
  // loaded, says which ones, and can walk between them.
  const [findOpen, setFindOpen] = useState(false);
  const [query, setQuery] = useState("");
  // The hit the reader is standing on, held as the message rather than as an
  // ordinal: a page of older messages lands at the *front* of the list, and an
  // ordinal would then be pointing at somebody else's sentence. Null means they
  // have not stepped yet and get the newest hit — the channel reads
  // oldest-first, so the first match in the room is the furthest thing from
  // where they were looking when they pressed the key.
  const [standing, setStanding] = useState<string | null>(null);
  const findInput = useRef<HTMLInputElement>(null);
  const [ticks, setTicks] = useState<MinimapTick[]>(NO_TICKS);

  const needle = query.trim();
  const matches = useMemo(() => {
    if (!findOpen || !needle) return NO_MATCHES;
    // System notices are the feed's own narration, not what anyone said, and
    // several carry an envelope rather than prose. Find searches messages.
    return visible
      .filter(e => !SYSTEM_TYPES.has(e.type) && (hasMatch(e.content, needle) || hasMatch(e.sender, needle)))
      .map(e => e.id);
  }, [findOpen, needle, visible]);

  const matchSet = useMemo(() => new Set(matches), [matches]);
  // Resolved at read time rather than corrected in an effect, so a message
  // arriving or an amendment folding away cannot leave a stale count on screen
  // for a frame. A standing hit that is no longer in the list falls back to the
  // newest one rather than to nothing.
  const standingAt = standing === null ? -1 : matches.indexOf(standing);
  const position = matches.length === 0 ? null : standingAt === -1 ? matches.length - 1 : standingAt;
  const activeId = position === null ? null : matches[position];

  useEffect(() => {
    if (!openFind) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setFindOpen(true);
  }, [openFind]);

  // Focus follows the bar opening, and a second ⌘F selects what is in it, so
  // the key that opens a search is also the key that starts a new one.
  useEffect(() => {
    if (!findOpen) return;
    const input = findInput.current;
    input?.focus();
    input?.select();
  }, [findOpen, openFind]);

  const closeFind = useCallback(() => setFindOpen(false), []);

  const stepMatch = (delta: 1 | -1) => {
    if (matches.length === 0) return;
    setStanding(matches[stepIndex(position ?? 0, matches.length, delta)]);
  };

  useEffect(() => {
    if (!activeId) return;
    rowNode(scrollRef.current, activeId)?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [activeId]);

  // Where each hit sits in the whole scrollable feed, as a fraction of it —
  // measured off the live boxes rather than estimated from row counts, since a
  // one-line reply and a forty-line write-up are both one message. Remeasured
  // whenever the feed changes shape under it.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    if (!el || !findOpen || matches.length === 0) {
      setTicks(NO_TICKS);
      return;
    }
    const measure = () => {
      const base = el.getBoundingClientRect().top;
      const height = el.scrollHeight || 1;
      const next: MinimapTick[] = [];
      for (const id of matches) {
        const row = rowNode(el, id);
        if (!row) continue;
        const top = row.getBoundingClientRect().top - base + el.scrollTop;
        next.push({ id, top: Math.min(1, Math.max(0, top / height)) });
      }
      setTicks(next);
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    // The content, too: a message rendering taller moves every hit below it
    // without changing the viewport at all.
    if (el.firstElementChild) observer.observe(el.firstElementChild);
    return () => observer.disconnect();
  }, [findOpen, matches, visible]);

  // The feed follows new messages only while the reader is on the tail; scroll
  // up and it holds still. A jump-back button carries the count of what landed
  // meanwhile, so leaving the tail doesn't read as a quiet room.
  const [atBottom, setAtBottom] = useState(true);
  const atBottomRef = useRef(true);
  // The last row the reader had reached when they left the tail — the row
  // itself, not how many there were. A count is wrong the moment a page of
  // older messages is prepended: every one of them lands *above* the mark, and
  // none of it is news.
  const [detachedAt, setDetachedAt] = useState<string | null>(null);
  const lastVisible = useRef<string | null>(null);

  useEffect(() => {
    // Only the channel renders this viewport; the other views replace it, so
    // the ref is null for them and the pin is left as they found it.
    const el = scrollRef.current;
    if (!el) return;
    // A view switch unmounts the viewport, and a remount starts at the top;
    // put a pinned reader back on the tail rather than in the archive.
    if (atBottomRef.current) el.scrollTop = el.scrollHeight;
    const measure = () => {
      if (el.scrollTop <= LOAD_OLDER_MARGIN_PX) loadOlder();
      const pinned = el.scrollHeight - el.scrollTop - el.clientHeight <= PIN_TOLERANCE_PX;
      if (pinned === atBottomRef.current) return;
      atBottomRef.current = pinned;
      if (!pinned) setDetachedAt(lastVisible.current);
      setAtBottom(pinned);
    };
    el.addEventListener("scroll", measure, { passive: true });
    return () => el.removeEventListener("scroll", measure);
  }, [view, loadOlder]);

  // Put the reader back where they were reading. Before paint, and before the
  // follow-the-tail effect below runs — which it won't, since anyone reading
  // back is by definition off the tail.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const from = anchor.current;
    if (!el || from === null) return;
    anchor.current = null;
    el.scrollTop = el.scrollHeight - from;
  }, [visible]);

  // A page of the room is not a page of the channel: the thread prose in it is
  // placed rather than shown, and the churn goes up to the rail, so two hundred
  // messages can leave a handful of rows and nothing to scroll. Keep pulling
  // until the viewport actually overflows — otherwise the one gesture that
  // reaches the older pages is a gesture the reader has no way to make.
  useEffect(() => {
    if (!historyLoaded) return;
    const el = scrollRef.current;
    if (!el) return;
    if (el.scrollHeight <= el.clientHeight + LOAD_OLDER_MARGIN_PX) loadOlder();
  }, [historyLoaded, visible, loadOlder]);

  const jumpToLatest = () => {
    const el = scrollRef.current;
    if (!el) return;
    atBottomRef.current = true;
    setAtBottom(true);
    el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
  };

  const unread = useMemo(() => {
    if (atBottom || detachedAt === null) return 0;
    const mark = visible.findIndex((e) => e.id === detachedAt);
    return mark === -1 ? 0 : visible.length - 1 - mark;
  }, [atBottom, detachedAt, visible]);

  // Auto-scroll when new events arrive — but not over a message the user was
  // just sent to, which is the one place in the feed they're looking, and not
  // over history they scrolled up to read.
  useEffect(() => {
    lastVisible.current = visible[visible.length - 1]?.id ?? null;
    // A live message must not pull the view off the hit the reader stepped to,
    // any more than it may off a message they arrived at from search.
    if (highlight || activeId || !atBottomRef.current) return;
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [visible, highlight, activeId]);

  useEffect(() => {
    if (!highlight) return;
    highlightRow.current?.scrollIntoView({ block: "center" });
  }, [highlight, historyLoaded, visible]);

  const channelCount = visible.length;

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-3 border-b border-border shrink-0 h-[48px] bg-paper px-4">
        {/* Connection state lives in the shell status bar. */}
        <div className="ml-auto flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
          {([
            { id: "channel" as const, label: "Channel", count: channelCount as number | null },
            { id: "board" as const,   label: "Board",   count: null },
            { id: "network" as const, label: "Network", count: null },
          ]).map(t => {
            // Hold the reveal modifier and each tab wears the key that selects it.
            const active = view === t.id;
            return (
              <button
                key={t.id}
                data-tour={`tab-${t.id}`}
                onClick={() => setView(t.id)}
                className={`relative flex items-center gap-1.5 rounded-md px-3 py-1 text-label font-medium transition-colors ${
                  active
                    ? "bg-elevated text-text shadow-sm ring-1 ring-border"
                    : "text-muted-foreground hover:bg-hairline hover:text-text"
                }`}
              >
                {t.label}
                <KeyBadge action={`pane.${t.id}`} />
                {t.count !== null && (
                  <span className={`text-micro tabular ${active ? "text-accent" : "text-muted-foreground"}`}>
                    {t.count}
                  </span>
                )}
              </button>
            );
          })}
        </div>
      </div>
      {view === "board" ? (
        <div className="flex-1 min-h-0">
          <RoomBoard roomName={roomName} onOpenThread={onOpenThread} />
        </div>
      ) : view === "network" ? (
        // Unified Network pane: SLIM channel diagnostics as a rail on top, the
        // A2A bridge (the room's off-channel traffic) beneath it when there is
        // one, and the live L9 protocol feed filling the rest.
        <div className="flex flex-1 min-h-0 flex-col">
          <div className="shrink-0 border-b border-border bg-surface/40">
            <RoomSlimView roomName={roomName} layout="rail" />
          </div>
          <div className="shrink-0">
            <RoomA2aView roomName={roomName} />
          </div>
          <div className="flex-1 min-h-0">
            <L9Inspector roomName={roomName} />
          </div>
        </div>
      ) : (
      <div className="relative flex flex-1 min-h-0 flex-col">
      {findOpen && (
        <ChatFindBar
          query={query}
          onQueryChange={value => {
            setQuery(value);
            // A new query is a new search: back to the newest hit rather than
            // to wherever the last one had got to.
            setStanding(null);
          }}
          count={matches.length}
          position={position}
          onStep={stepMatch}
          onClose={closeFind}
          inputRef={findInput}
          partial={!reachedStart}
        />
      )}
      {historyLoaded && (
        <ActivityRail items={activity} onOpenThread={onOpenThread} onOpenMemory={onOpenMemory} />
      )}
      <div className="relative flex-1 min-h-0">
      <ScrollArea className="h-full" viewportRef={scrollRef}>
        {!historyLoaded ? (
          <ChannelSkeleton />
        ) : visible.length === 0 ? (
          // A room whose every message is task-scoped has a full rail and an
          // empty feed, and "no messages yet" is then a false statement about a
          // room with hundreds of them. Say where the talking went instead.
          <EmptyState
            className="h-full"
            icon={MessagesSquare}
            title={activity.length ? "The talking is inside the tasks" : "No messages yet"}
            description={
              activity.length
                ? "Every message here belongs to a task. Open one from the rail above to read it."
                : "Post a position or @-mention an agent to get the room talking."
            }
          />
        ) : (
        <div className="py-3">
        {/* The head of the walk back. Says which of the two it is — still
            fetching, or there is genuinely nothing before this. */}
        {loadingOlder ? (
          <div className="flex items-center justify-center gap-2 py-3 text-micro text-muted-foreground">
            <Loader2 className="size-3 animate-spin" />
            Loading earlier messages…
          </div>
        ) : reachedStart ? (
          <div className="py-3 text-center text-micro text-muted-foreground">Beginning of the room</div>
        ) : null}
        {visible.map((ev, idx) => {
              // Coordination + plan lifecycle events render as slim, centered
              // system notices — quiet dividers woven into the conversation,
              // not loud rows. Chat messages group under one sender header.
              if (ev.type === PING_TYPE && ev.thread) {
                const thread = ev.thread;
                const shortId = threadShortId(thread) ?? "thread";
                const owner = threads.get(thread);
                const who = ev.pingSenders;
                return (
                  <SystemNotice key={ev.id} time={ev.time} dot="var(--accent)" label="Activity">
                    <span>in</span>
                    <button
                      type="button"
                      onClick={() => onOpenThread?.(thread)}
                      disabled={!onOpenThread}
                      title={thread}
                      aria-label={`Open thread ${shortId}`}
                      className="inline-flex max-w-[18rem] items-center gap-1 truncate rounded px-1 text-accent transition-colors enabled:hover:bg-accent-soft enabled:hover:underline disabled:cursor-default"
                    >
                      <MessageSquare className="size-3 shrink-0" strokeWidth={1.9} />
                      <span className="truncate">{owner?.title ?? shortId}</span>
                    </button>
                    {who.length > 0 && (
                      <span className="truncate">· {who.map(h => `@${h}`).join(", ")}</span>
                    )}
                    {onOpenThread && <span className="text-faint">· click to open</span>}
                  </SystemNotice>
                );
              }
              if (ev.type === NOTICE_TYPE) {
                const episode = ev.thread;
                const by = ev.raw.by as string | undefined;
                const subkind = (ev.raw.subkind as string) || "filed";
                // Green when work lands, closes or clears; red when it stalls on a
                // blocker; yellow when it comes back up for grabs, handed back or
                // drained; accent in hand.
                const dot =
                  subkind === "resolved" || subkind === "filed" || subkind === "unblocked"
                    ? "var(--green)"
                    : subkind === "blocked"
                      ? "var(--red)"
                      : subkind === "released" || subkind === "expired"
                        ? "var(--yellow)"
                        : "var(--accent)";
                return (
                  <SystemNotice
                    key={ev.id}
                    time={ev.time}
                    dot={dot}
                    label={noticeLabel(subkind, ev.raw.kind as string | undefined)}
                  >
                    <button
                      type="button"
                      onClick={() => episode && onOpenThread?.(episode)}
                      disabled={!episode || !onOpenThread}
                      className="inline-flex max-w-[20rem] items-center gap-1 truncate rounded px-1 text-accent transition-colors enabled:hover:bg-accent-soft enabled:hover:underline disabled:cursor-default disabled:text-text"
                    >
                      <MessageSquare className="size-3 shrink-0" strokeWidth={1.9} />
                      <span className="truncate">{ev.content}</span>
                    </button>
                    {/* A filed task reads by who it is for; a lease event by who
                        moved it; an expired one by who let it drain. Fall back to
                        the filer when a task is for no one. */}
                    {subkind === "filed" && ev.raw.for ? (
                      <span>· for @{String(ev.raw.for).replace(/^@/, "")}</span>
                    ) : by ? (
                      <span>
                        · {subkind === "filed" ? "by " : subkind === "expired" ? "held by " : ""}@{by}
                      </span>
                    ) : null}
                  </SystemNotice>
                );
              }
              if (ev.type === "l9_knowledge") {
                const key = ev.raw.key as string | undefined;
                const updatedBy = ev.raw.updated_by as string | undefined;
                const version = ev.raw.version;
                // The key printed once, as the name the room calls it — the
                // content line already said it, in slug form, and said it again
                // in the mono span beside it.
                const named = key ? nameActivity(key, [ev], threads, rowNames) : null;
                return (
                  <SystemNotice key={ev.id} time={ev.time} dot="var(--yellow)" label="Knowledge">
                    <span>updated</span>
                    {named ? (
                      <button
                        type="button"
                        onClick={() => named.episode && onOpenThread?.(named.episode)}
                        disabled={!named.episode || !onOpenThread}
                        title={key}
                        className="inline-flex max-w-[18rem] items-center gap-1 truncate rounded px-1 text-accent transition-colors enabled:hover:bg-accent-soft enabled:hover:underline disabled:cursor-default disabled:text-text"
                      >
                        <span className="truncate">{named.title}</span>
                      </button>
                    ) : (
                      <span className="truncate">{ev.content}</span>
                    )}
                    {typeof version === "number" && <span>· v{version}</span>}
                    {updatedBy ? <span>· by @{updatedBy}</span> : null}
                  </SystemNotice>
                );
              }
              if (ev.type === "coordination_consensus") {
                const broken = ev.raw.broken === true;
                const episodeUrn = (ev.raw.episode as string | undefined) ?? (ev.raw.session as string | undefined);
                const shortId = episodeUrn ? episodeUrn.split(":").pop() : undefined;
                const planFile = ev.raw.plan_file as string | undefined;
                const assignments = ev.raw.assignments as Record<string, string> | undefined;
                const issueCount = assignments ? Object.keys(assignments).length : 0;
                const metrics = ev.raw.metrics && typeof ev.raw.metrics === "object"
                  ? (ev.raw.metrics as Record<string, unknown>)
                  : undefined;
                const garRaw = metrics ? metrics.gar : undefined;
                const gar = typeof garRaw === "number" && Number.isFinite(garRaw) ? garRaw : undefined;
                const tone = broken ? "var(--yellow)" : "var(--green)";
                return (
                  <SystemNotice
                    key={ev.id}
                    time={ev.time}
                    dot={tone}
                    label={broken ? "Timeout" : "Consensus"}
                    labelColor={tone}
                    strong
                  >
                    <span>in</span>
                    {shortId ? (
                      <EpisodeTag urn={episodeUrn} shortId={shortId} onOpen={onOpenThread && episodeUrn ? () => onOpenThread(episodeUrn) : undefined} />
                    ) : (
                      <span className="font-mono">episode</span>
                    )}
                    {broken ? (
                      <span>· no agreement</span>
                    ) : (
                      <>
                        <span>· {issueCount} issue{issueCount === 1 ? "" : "s"} agreed</span>
                        {gar !== undefined ? (
                          <Tooltip content="Genuine agreement ratio: how many agents actually moved toward the outcome">
                            <span
                              className="font-mono"
                              aria-description="Genuine agreement ratio: how many agents actually moved toward the outcome"
                            >
                              · GAR {gar.toFixed(2)}
                            </span>
                          </Tooltip>
                        ) : null}
                        {planFile ? (
                          <span>→ <span className="font-mono text-accent">{planFile}</span></span>
                        ) : null}
                      </>
                    )}
                  </SystemNotice>
                );
              }
              if (ev.type === "coordination_join") {
                const handle = (ev.raw.handle as string | undefined) ?? ev.sender;
                const intent = (ev.raw.intent as string | undefined) ?? "";
                const episodeUrn = (ev.raw.episode as string | undefined) ?? (ev.raw.session as string | undefined);
                const shortId = episodeUrn ? episodeUrn.split(":").pop() : undefined;
                return (
                  <SystemNotice key={ev.id} time={ev.time} dot="var(--muted-foreground)">
                    <span className="font-medium text-muted-foreground">@{handle}</span>
                    <span>joined</span>
                    {shortId ? (
                      <EpisodeTag urn={episodeUrn} shortId={shortId} onOpen={onOpenThread && episodeUrn ? () => onOpenThread(episodeUrn) : undefined} />
                    ) : null}
                    {intent ? <span>· &ldquo;{intent}&rdquo;</span> : null}
                  </SystemNotice>
                );
              }
              // A chat message groups with the one above it when the same
              // sender speaks consecutively (no intervening system notice).
              const prev = visible[idx - 1];
              const grouped =
                prev &&
                !SYSTEM_TYPES.has(prev.type) &&
                prev.sender === ev.sender;
              const isAgent = agentHandles.has(ev.sender);
              // Match the members panel so one sender isn't two colours in two
              // places: an agent wears its own stable tint (Monogram's default),
              // a human the neutral seat.
              const color = isAgent ? undefined : "var(--avatar-neutral)";
              const marked = highlight !== null && ev.messageId === highlight;
              const owner = isAgent ? agentOwners.get(ev.sender) : undefined;
              // The row's own share of the open find: whether to mark its prose
              // at all, and whether it is the hit being stood on.
              const hit = needle && matchSet.has(ev.id) ? { query: needle, active: ev.id === activeId } : undefined;
              return (
                <div
                  key={ev.id}
                  data-event-id={ev.id}
                  ref={marked ? highlightRow : undefined}
                  className={`group relative flex gap-3 px-5 hover:bg-hairline ${grouped ? "py-0.5" : "mt-3 pt-1 first:mt-0"} ${
                    marked ? "bg-accent/15" : ""
                  } ${hit?.active ? "bg-yellow/10 ring-1 ring-inset ring-yellow/40" : ""}`}
                >
                  {/* Timestamp low-signal: right gutter, hover-revealed. */}
                  <span className="pointer-events-none absolute right-5 top-1.5 text-micro tabular text-faint opacity-0 transition-opacity group-hover:opacity-100">
                    {ev.time.slice(0, 5)}
                  </span>

                  <div className="w-7 flex-shrink-0">
                    {!grouped && (
                      <Tooltip content={owner ? `@${ev.sender} · owned by @${owner}` : ev.sender}>
                        <span role="img" aria-label={owner ? `@${ev.sender} · owned by @${owner}` : ev.sender}>
                          <Monogram handle={ev.sender} color={color} className="size-7 text-micro" />
                        </span>
                      </Tooltip>
                    )}
                  </div>
                  <div className="min-w-0 flex-1">
                    {!grouped && (
                      <div className="flex items-center gap-1.5 pr-12">
                        <span className="text-label font-semibold text-text truncate">
                          <HighlightText text={ev.sender} highlight={hit} />
                        </span>
                        {isAgent && (
                          <Bot aria-label="agent" className="size-3 flex-shrink-0 text-accent" />
                        )}
                        {ev.recipient && (
                          <span className="rounded bg-hairline px-1.5 py-px font-mono text-micro text-muted-foreground">
                            → {ev.recipient}
                          </span>
                        )}
                      </div>
                    )}
                    <MessageBody content={ev.content} hit={hit} onOpenMemory={onOpenMemory} />
                    {ev.edited && (
                      <span className="text-micro text-faint" title="revised by a later message">
                        (edited)
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
        </div>
        )}
      </ScrollArea>
      {findOpen && ticks.length > 0 && (
        <ChatMinimap viewportRef={scrollRef} ticks={ticks} activeId={activeId} onJump={setStanding} />
      )}
      </div>
      {!atBottom && visible.length > 0 && (
        <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center">
          <Button
            size="sm"
            variant="secondary"
            onClick={jumpToLatest}
            aria-label={unread > 0 ? `Jump to latest, ${unread} new` : "Jump to latest"}
            className="pointer-events-auto rounded-full border-border bg-elevated shadow-lg motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1"
          >
            <ArrowDown className="size-3.5" />
            {unread > 0 ? `${unread} new ${unread === 1 ? "message" : "messages"}` : "Jump to latest"}
          </Button>
        </div>
      )}
      </div>
      )}
    </div>
  );
}
