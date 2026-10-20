// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import {
  fetchWireHistory,
  fetchMessages,
  logFetchError,
} from "@/lib/api";
import { useMessageSearch, useRoomSettings, type ThreadOwner } from "@/lib/room-data";
import { boardMovesInChat } from "@/lib/room-settings";
import {
  NOTICE_TYPE,
  PING_TYPE,
  isLiveEpisode,
  noticeLabel,
  threadShortId,
  upstreamInChat,
} from "@/lib/threads";
import { CHAT_TYPES, parseEvent, type Event } from "@/lib/room-events";
import {
  applyActivity,
  expireActivity,
  isActivityFrame,
  respondingLabel,
  settleActivity,
  splitActivity,
  type Responding,
} from "@/lib/activity";
import { useRoomConnected, useRoomStream } from "@/lib/stream-hub";
import { reportToApp } from "@/lib/report-to-app";
import { usePendingMessages, type Landed } from "@/lib/pending-messages";
import { PendingMessageRows } from "@/components/pending-message-rows";
import { ChatFindBar } from "@/components/chat-find-bar";
import { ChatSearchResults } from "@/components/chat-search-results";
import { freeText, hasScope, type MessageSearchHit } from "@/lib/message-search";
import { ChatMinimap, type MinimapTick } from "@/components/chat-minimap";
import { hasMatch, stepIndex } from "@/lib/chat-search";
import { ActivityRail, type ActivityItem } from "@/components/activity-rail";
import { NowProvider } from "@/lib/relative-time";
import { EmptyState } from "@/components/empty-state";
import { RoomStarters } from "@/components/room-starters";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { JumpToLatest } from "@/components/jump-to-latest";
import { useFollowLatest } from "@/components/messages/use-follow-latest";
import {
  FeedRow,
  RAISE_UP_TYPES,
  SYSTEM_TYPES,
  lastChatSender,
  nameActivity,
  useFeedContext,
} from "@/components/messages/feed-row";
import { Loader2, MessageSquare, MessagesSquare } from "lucide-react";
import { Shimmer, SporeMark } from "@/components/responding-mark";

/** Stable empties: find writes these back on every close, and a fresh array
 *  each time would re-run the effects that read them. */
const NO_MATCHES: string[] = [];
const NO_TICKS: MinimapTick[] = [];

/** The rendered row for a message, found by the id it carries in the DOM.
 *  A scan rather than a selector: an event id is synthesized, and escaping one
 *  into an attribute selector is a sharper edge than walking a handful of
 *  nodes. */
/** How long typing in the find bar pauses before the room-wide search runs. */
const SEARCH_SETTLE_MS = 200;
/** How long typing pauses before the loaded messages are marked and counted.
 *  Short enough to feel immediate, long enough that a word typed at speed is
 *  matched once rather than once per letter. */
const FIND_SETTLE_MS = 120;

function rowNode(root: HTMLElement | null, id: string): HTMLElement | null {
  if (!root) return null;
  for (const node of root.querySelectorAll<HTMLElement>("[data-event-id]")) {
    if (node.dataset.eventId === id) return node;
  }
  return null;
}

// The raise-up list lives with the rows that draw it; the contract test reads
// it from here.
export { RAISE_UP_TYPES };

// Event types that appear in the chat-channel view alongside real chat.
// Joins + consensus belong here so the room's chat surface narrates the
// negotiation lifecycle ("alice joined session X", "CONSENSUS in session X
// → 4 work rows", "TIMEOUT in session X, no agreement") instead of
// burying it all under the EVENTS tab.
const CHANNEL_VIEW_TYPES = new Set([...CHAT_TYPES, ...RAISE_UP_TYPES, PING_TYPE, NOTICE_TYPE]);

/** One line of "who is responding": the system-notice scale the channel already
 *  speaks in, with a spore growing for a turn in flight. `offset` staggers the
 *  spores of several rows. */
function RespondingRow({ children, offset = 0 }: { children: React.ReactNode; offset?: number }) {
  return (
    <div className="flex items-center gap-2 py-0.5 text-micro text-muted-foreground">
      <SporeMark offset={offset} />
      <span className="flex min-w-0 items-center gap-1.5 truncate">{children}</span>
    </div>
  );
}

/** "@aligner is responding…" pinned over the composer, gone the moment the
 *  reply lands. A turn going into a task's thread does not land here — the channel
 *  never shows a thread's prose — so that line says where instead, and opens
 *  it, the way the ping for the reply will: "@aligner is responding in <task>". */
function RespondingLine({
  entries,
  room,
  threads,
  onOpenThread,
}: {
  entries: Responding[];
  room: string;
  threads: Map<string, ThreadOwner>;
  onOpenThread?: (episode: string) => void;
}) {
  const { here, elsewhere } = splitActivity(entries, (episode) => !episode || isLiveEpisode(room, episode));
  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="responding-line"
      className="relative flex flex-shrink-0 flex-col bg-[var(--bg)] px-5 py-1 motion-safe:animate-in motion-safe:fade-in-0"
    >
      {/* The channel above fades into the line rather than stopping at an edge. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-x-0 bottom-full h-6"
        style={{ background: "linear-gradient(to top, var(--bg), transparent)" }}
      />
      {here.length > 0 && (
        <RespondingRow>
          <Shimmer className="truncate">{respondingLabel(here)}</Shimmer>
        </RespondingRow>
      )}
      {[...elsewhere.entries()].map(([thread, group], i) => {
        const shortId = threadShortId(thread) ?? "thread";
        const title = threads.get(thread)?.title ?? shortId;
        return (
          <RespondingRow key={thread} offset={(i + 1) * 4}>
            <Shimmer className="truncate">{respondingLabel(group, "elsewhere")}</Shimmer>
            <button
              type="button"
              onClick={() => onOpenThread?.(thread)}
              disabled={!onOpenThread}
              title={thread}
              aria-label={`Open thread ${shortId}`}
              className="inline-flex max-w-[18rem] items-center gap-1 truncate rounded px-1 text-accent transition-colors enabled:hover:bg-accent-soft enabled:hover:underline disabled:cursor-default"
            >
              <MessageSquare className="size-3 shrink-0" strokeWidth={1.9} />
              <span className="truncate">{title}</span>
            </button>
          </RespondingRow>
        );
      })}
    </div>
  );
}

/** Skeleton loader for chat rows. */
function ChannelSkeleton() {
  const widths = ["w-3/5", "w-2/5", "w-1/2"];
  return (
    <div className="flex flex-col gap-5 px-5 py-4">
      {widths.map((w, i) => (
        <div key={i} className="flex gap-3">
          <Skeleton className="size-6 flex-shrink-0 rounded-full" />
          <div className="min-w-0 flex-1 pt-0.5">
            <Skeleton className="h-3 w-24" />
            <Skeleton className={`mt-2 h-3 ${w}`} />
          </div>
        </div>
      ))}
    </div>
  );
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
 * Activity the chat shows as well: what a task's thread said (a ping, drawn as a
 * quoted line when there is one to quote), and the board moves the room picked
 * in its "Board moves shown in the chat" setting (by default a task's arrival
 * and its finish). Those are the room's news, so they get a line where people
 * are reading; each stays on the rail too, where the task's whole life
 * collects. Every other board event (the floor moving on each step of a flow,
 * and the moves the room left out) stays on the rail alone. A task's pull
 * request is the same: its merge and its CI going red are news, and the rest
 * of what GitHub says (a review asked for, CI green again) is the task's own.
 */
/** The verifier's notice about a message: drawn under that message, never as a row. */
function isVerifierCheck(event: Event): boolean {
  return event.type === NOTICE_TYPE && event.raw.subkind === "check";
}

function isAlsoInChat(event: Event, boardMoves: ReadonlySet<string>): boolean {
  if (event.type === PING_TYPE) return true;
  if (event.type !== NOTICE_TYPE) return false;
  const subkind = (event.raw.subkind as string) || "filed";
  if (subkind === "upstream") return upstreamInChat(event.raw.change as string | undefined);
  return boardMoves.has(subkind);
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

/** Who made one event: a notice's mover, a ping's last writer, a memory's
 *  last editor. Null when the event says nobody. */
function actorOf(ev: Event): string | null {
  const who =
    ev.type === PING_TYPE
      ? ev.pingSenders[ev.pingSenders.length - 1]
      : ev.type === NOTICE_TYPE
        ? (ev.raw.by as string | undefined)
        : ev.type === "l9_knowledge"
          ? (ev.raw.updated_by as string | undefined)
          : ev.sender;
  return who || null;
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
    const label = noticeLabel(
      (ev.raw.subkind as string) || "filed",
      ev.raw.kind as string | undefined,
      ev.raw.change as string | undefined,
    );
    if (ev.raw.subkind === "upstream") {
      // Which pull request, and who a review was asked of. Nobody moved it here.
      const who = ((ev.raw.who as string[] | undefined) ?? []).map((h) => `@${h}`).join(", ");
      return { label, detail: [ev.raw.ref as string | undefined, who].filter(Boolean).join(" · ") };
    }
    if (ev.raw.subkind === "floor") {
      // Whose turn it is in a thread: the task the thread belongs to (its id
      // only when no row carries it), then the handles it was given to, the
      // holder alone, or the floor opening back up.
      const speakers = (ev.raw.speakers as string[] | undefined) ?? [];
      const where = (ev.raw.title as string | undefined) || (ev.raw.key as string | undefined) || "";
      const turn = ev.raw.released
        ? "released"
        : speakers.length
          ? speakers.map((h) => `@${h}`).join(", ")
          : by
            ? `held by @${by}`
            : "";
      return { label, detail: [where, turn].filter(Boolean).join(" · ") };
    }
    return { label, detail: by ? `@${by}` : "" };
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

/** One page of the channel, on both of its reads.
 *
 *  The two used to disagree: the prose took the backend's default (50) while the
 *  control frames took 200, so the conversation was the shallower half of a feed
 *  assembled from both — and in a busy room the newest fifty are the churn, which
 *  is how a room with hundreds of messages in it read as having none. Same page
 *  size on both reads, and every older page is fetched the same way. */
const CHANNEL_PAGE = 200;

/** The two reads the channel is assembled from, as one page of it.
 *
 *  `/messages` is what the room *said*; the wire replay is where a ping and a
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

/** How long a message may be on the hub before its live copy counts as lost. */
const LIVE_GRACE_MS = 10_000;

/** A test for whether a message is already among `events`, by its id (a live
 *  frame carries the id the history read gives it), built once for a batch. */
function haveOf(events: Event[]): (e: Event) => boolean {
  const ids = new Set(events.map((x) => x.messageId).filter(Boolean));
  return (e) => e.messageId !== null && ids.has(e.messageId);
}

/** The newest stamp of anything said in the channel: where a catch-up reads from. */
function newestSaidAt(events: Event[]): string | null {
  let newest: string | null = null;
  let newestMs = -Infinity;
  for (const e of events) {
    if (!CHAT_TYPES.has(e.type)) continue;
    const ms = Date.parse(e.at);
    if (Number.isFinite(ms) && ms > newestMs) {
      newestMs = ms;
      newest = e.at;
    }
  }
  return newest;
}

/** Every message said since `since`, newest page first, walking back a page at
 *  a time so a long gap is read whole. */
async function readSince(room: string, since: string): Promise<Event[]> {
  const out: Event[] = [];
  let before: string | null = null;
  for (let pages = 0; pages < 10; pages++) {
    const data = await fetchMessages(room, CHANNEL_PAGE, { since, before });
    const page = (data.messages || []).map((m) => parseEvent(m));
    out.push(...page);
    if (page.length === 0 || (data.total ?? page.length) <= page.length) break;
    before = oldestAt(page);
    if (!before) break;
  }
  return out;
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
      (e.messageId === amendment.amends || (e.wireId !== null && e.wireId === amendment.amends)) &&
      e.sender === amendment.sender &&
      e.amends === null,
  );
  if (target === -1) return [...events, amendment];
  return events.map((e, i) =>
    i === target ? { ...e, content: amendment.content, edited: true } : e,
  );
}

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
  /** A message to reveal in the channel, arrived at from search. */
  focusMessageId?: string | null;
  onFocusConsumed?: () => void;
  /** Bumped by the room's ⌘F binding to open (or re-focus) the find bar. The
   *  page owns the key because it owns the pane switch that has to happen
   *  first; the channel owns the search itself. */
  openFind?: number;
  /** How many rows the channel draws, for its tab. */
  onCountChange?: (count: number) => void;
}

export function EventStream({ roomName, onMemoryChanged, onConnectionChange, onOpenMemory, onOpenThread, focusMessageId = null, onFocusConsumed, openFind = 0, onCountChange }: Props) {
  const [events, setEvents] = useState<Event[]>([]);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const connected = useRoomConnected(roomName);

  // Surface connection state to status bar; one home for the signal.
  useEffect(() => {
    onConnectionChange?.(connected);
  }, [connected, onConnectionChange]);
  // The scrolling viewport: a ref for find and its minimap, and state for the
  // scroll behavior, which attaches once the element exists.
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const attachScroller = useCallback((el: HTMLDivElement | null) => {
    scrollRef.current = el;
    setScroller(el);
  }, []);

  // What every row needs about the room: who is an agent (to badge their
  // replies) and whose, what each thread and row is called (so a ping or a
  // notice names the task rather than its URN), and the verifier's lines. All
  // off the room's shared reads, so none of it costs a request of its own.
  const feed = useFeedContext(roomName, { onOpenThread, onOpenMemory });
  const { threads, rowNames, refreshFlags } = feed;
  // Which board moves the room shows in its chat (a room setting).
  const { settings: roomSettings } = useRoomSettings(roomName);
  const boardMoves = useMemo(() => boardMovesInChat(roomSettings), [roomSettings]);
  const searchHandles = useMemo(() => [...feed.agentHandles], [feed.agentHandles]);

  // Where reading back has got to: the cursor the next older page is asked for,
  // whether both reads have run out, and whether one is in flight. Refs rather
  // than state because the scroll handler reads them on every wheel tick and
  // must not be re-bound to see the current values.
  const older = useRef({ cursor: null as string | null, exhausted: false, loading: false });
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [reachedStart, setReachedStart] = useState(false);

  // Two reads, one feed.
  //
  // The room's messages are what was *said*; a ping is a control frame and the
  // conversational read leaves it out by construction — which would mean the
  // channel's account of a busy thread survived only as long as the tab that
  // watched it land. The transcript's wire replay is where a ping does survive, so
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
        fetchWireHistory(roomName, CHANNEL_PAGE, before),
      ]);
      const said = (data.messages || []).map((m) => parseEvent(m));
      const notices = frames
        .map((frame) => parseEvent(frame))
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
  // while you read back. A page lands prepended, and the scroll behavior keeps
  // the reader on what was already there, so reaching the top reveals history
  // instead of moving it.
  const loadOlder = useCallback(() => {
    const state = older.current;
    if (state.loading || state.exhausted || !state.cursor) return;
    state.loading = true;
    setLoadingOlder(true);
    readPage(state.cursor)
      .then(({ page, more }) => {
        const cursor = oldestAt(page);
        // No cursor means the page carried nothing datable to ask before, so
        // there is no next request to make even if the room has more.
        state.exhausted = !more || cursor === null;
        if (cursor) state.cursor = cursor;
        if (state.exhausted) setReachedStart(true);
        setEvents((prev) => mergePage(prev, page));
      })
      .catch(logFetchError("fetchMessages"))
      .finally(() => {
        state.loading = false;
        setLoadingOlder(false);
      });
  }, [readPage]);

  // Who is mid-turn right now: a presence-style signal off the same stream,
  // never a message (#513). A frame starts or ends a handle's entry; the
  // handle's next message ends it too, whether or not the ending frame arrived;
  // and an entry nobody has heard from within its TTL expires on the tick below.
  const [responding, setResponding] = useState<Responding[]>([]);
  useEffect(() => {
    if (responding.length === 0) return;
    const tick = setInterval(() => setResponding((prev) => expireActivity(prev, Date.now())), 1_000);
    return () => clearInterval(tick);
  }, [responding.length]);

  // Catching up: what the room said that this view didn't get live, read from
  // the hub on events rather than on a timer:
  // - the room's feed comes back after a drop ("back");
  // - the window comes to the front ("check");
  // - something sent from here wasn't echoed live within LIVE_GRACE_MS ("check",
  //   below, once the pending rows are known);
  // - the live handler failed on several frames in a row ("broken").
  // A check that finds a message the live feed lost, or a broken handler, also
  // subscribes again (`epoch`).
  const eventsRef = useRef<Event[]>([]);
  useEffect(() => {
    eventsRef.current = events;
  }, [events]);
  const [epoch, setEpoch] = useState(0);
  const catchUp = useCallback(
    async (why: "back" | "check" | "broken") => {
      if (why === "broken") setEpoch((n) => n + 1);
      const since = newestSaidAt(eventsRef.current);
      if (!since) return;
      let page: Event[];
      try {
        page = await readSince(roomName, since);
      } catch (err) {
        logFetchError("fetchMessages")(err);
        return;
      }
      const have = haveOf(eventsRef.current);
      const missed = page.filter((e) => !have(e));
      if (missed.length === 0) return;
      setEvents((prev) => {
        const had = haveOf(prev);
        return mergePage(prev, missed.filter((e) => !had(e)));
      });
      // A message can be on the hub a moment before its live frame lands, so
      // only one older than that says the live feed lost it.
      const lost = missed.some((e) => Date.now() - (Date.parse(e.at) || 0) > LIVE_GRACE_MS);
      if (why === "check" && lost) {
        reportToApp(`the channel in ${roomName} missed ${missed.length} live message(s); subscribing again`);
        setEpoch((n) => n + 1);
      }
    },
    [roomName],
  );
  const wasConnected = useRef(connected);
  useEffect(() => {
    const back = connected && !wasConnected.current;
    wasConnected.current = connected;
    if (back && historyLoaded) void catchUp("back");
  }, [connected, historyLoaded, catchUp]);
  useEffect(() => {
    if (!historyLoaded) return;
    const check = () => {
      if (document.visibilityState === "visible") void catchUp("check");
    };
    document.addEventListener("visibilitychange", check);
    window.addEventListener("focus", check);
    return () => {
      document.removeEventListener("visibilitychange", check);
      window.removeEventListener("focus", check);
    };
  }, [historyLoaded, catchUp]);

  // Live room messages, off the app's one multiplexed connection.
  useRoomStream(roomName, (data) => {
    const msg = data as Record<string, unknown>;
    if (isActivityFrame(msg)) {
      setResponding((prev) => applyActivity(prev, msg, Date.now()));
      return;
    }
    // A schedule ran or changed: the Schedules tab's business, never a line here.
    if (msg.type === "schedule_changed") return;
    const event = parseEvent(msg);
    // The verifier raised a line or someone dismissed one: re-read the flags.
    if (isVerifierCheck(event)) {
      refreshFlags();
      return;
    }
    setResponding((prev) => settleActivity(prev, event.sender));
    setEvents((prev) => {
      if (event.amends) return foldAmendment(prev, event);
      // A catch-up may have read it from the hub before its live frame landed.
      if (event.messageId !== null && prev.some((x) => x.messageId === event.messageId)) return prev;
      return [...prev, event];
    });
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
  }, { epoch, onBroken: () => void catchUp("broken") });

  // The room's own timeline, split by what it is: a thread's prose is dropped
  // (it is not lost, it is placed, and the pane the ping opens is where it
  // reads), everything the room raised about a task goes up to that task's rail
  // row, and what is left in the feed is what people actually said. The
  // verifier's `check` notice is drawn under the message it is about, so it
  // is neither a row nor rail activity of its own.
  const inChannel = useMemo(
    () =>
      events.filter(
        (e) => CHANNEL_VIEW_TYPES.has(e.type) && !inAThread(e, roomName) && !isVerifierCheck(e),
      ),
    [events, roomName],
  );

  const candidates = useMemo(
    () => inChannel.filter(e => !isActivity(e) || isAlsoInChat(e, boardMoves)),
    [inChannel, boardMoves],
  );

  // What you sent to the room that the feed doesn't have yet, drawn under it.
  const saidHere = useMemo<Landed[]>(
    () =>
      inChannel
        .filter((e) => CHAT_TYPES.has(e.type))
        .map((e) => ({ id: e.messageId, sender: e.sender, content: e.content, at: e.at })),
    [inChannel],
  );
  const pending = usePendingMessages(roomName, null, saidHere);

  // Something sent from here that the hub took but the live feed hasn't
  // echoed within LIVE_GRACE_MS: the feed has gone quiet for this view, so
  // catch up (and subscribe again if it really lost it). Once per message.
  const unechoed = pending.find((p) => p.state === "sent")?.id ?? null;
  const unechoedAt = pending.find((p) => p.state === "sent")?.at ?? 0;
  useEffect(() => {
    if (!unechoed) return;
    // A little past the grace, so the message counts as lost when it's read.
    const wait = Math.max(0, unechoedAt + LIVE_GRACE_MS + 2_000 - Date.now());
    const timer = setTimeout(() => void catchUp("check"), wait);
    return () => clearTimeout(timer);
  }, [unechoed, unechoedAt, catchUp]);

  const saidById = useMemo(() => {
    const said = new Map<string, Event>();
    for (const ev of events) {
      if (!CHAT_TYPES.has(ev.type)) continue;
      if (ev.messageId) said.set(ev.messageId, ev);
      // A ping names a thread message by its envelope id, which only a copy
      // that arrived live carries.
      if (ev.wireId) said.set(ev.wireId, ev);
    }
    return said;
  }, [events]);

  // A thread's activity reads in the channel as one line per run: a ping
  // followed by another from the same thread folds into the later one, which
  // says how many it stands for and quotes the newest of their messages that
  // is loaded. A run with nothing loaded to quote is left to the rail.
  const pingLines = useMemo(() => {
    const lines = new Map<string, { said: Event; quote: string; count: number }>();
    let run: string[] = [];
    candidates.forEach((ev, i) => {
      if (ev.type !== PING_TYPE) return;
      run.push((ev.raw.pingMessage as string | undefined) ?? "");
      const next = candidates[i + 1];
      if (next?.type === PING_TYPE && next.thread === ev.thread) return;
      const said = [...run].reverse().map((id) => saidById.get(id)).find(Boolean);
      const quote = said?.content.split("\n").find((line) => line.trim())?.trim();
      if (said && quote) lines.set(ev.id, { said, quote, count: run.length });
      run = [];
    });
    return lines;
  }, [candidates, saidById]);

  // What the channel draws, row for row: a ping that draws nothing is not
  // here, so it neither splits a sender's messages nor breaks a run of notices.
  const visible = useMemo(
    () => candidates.filter(e => e.type !== PING_TYPE || pingLines.has(e.id)),
    [candidates, pingLines],
  );

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
          lastActor: actorOf(latest),
          time: latest.time,
          standing: standing ?? null,
          note: subject.startsWith("urn:") ? null : (rowNames.get(subject)?.note ?? null),
          updates: members.map((member) => {
            const { label, detail } = activityLine(member);
            return {
              id: member.id,
              time: member.time,
              at: Date.parse(member.at) || 0,
              label,
              detail,
              subkind: member.type === NOTICE_TYPE ? ((member.raw.subkind as string) || "filed") : null,
            };
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

  // Arriving from the find bar's History: a hit said in the channel is
  // revealed where it was said, reading back a page at a time until it is
  // loaded; a hit said inside a task opens that task's thread.
  const [seeking, setSeeking] = useState<string | null>(null);
  useEffect(() => {
    if (!seeking) return;
    if (events.some((e) => e.messageId === seeking)) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setHighlight(seeking);
      setSeeking(null);
      return;
    }
    if (older.current.exhausted) {
      setSeeking(null);
      return;
    }
    if (!loadingOlder) loadOlder();
  }, [seeking, events, loadingOlder, loadOlder]);

  const openHit = useCallback(
    (hit: MessageSearchHit) => {
      if (hit.thread && onOpenThread) {
        onOpenThread(hit.thread);
        return;
      }
      setSeeking(hit.message.id);
    },
    [onOpenThread],
  );

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

  // The query is the hub's grammar (`from:avery task:checkout apple`). What
  // marks a loaded message is its words and phrases; the fields narrow the
  // room-wide search behind the bar, and a query that is all fields steps
  // through the loaded messages that search returned.
  //
  // The input shows every keystroke at once; what it marks and counts follows
  // once typing pauses (`applied`), so a word typed at speed re-marks the
  // channel once rather than per letter. Clearing it applies at once.
  const [applied, setApplied] = useState("");
  useEffect(() => {
    const next = findOpen ? query : "";
    const timer = setTimeout(() => setApplied(next), next.trim() ? FIND_SETTLE_MS : 0);
    return () => clearTimeout(timer);
  }, [findOpen, query]);
  const needles = useMemo(() => freeText(applied), [applied]);
  const needle = needles.length > 0 ? needles : null;
  // The hub is asked once typing pauses, not per keystroke: a half-typed
  // `fr` on its way to `from:` is not a query worth a round trip.
  const [settled, setSettled] = useState("");
  useEffect(() => {
    const next = findOpen ? query : "";
    const timer = setTimeout(() => setSettled(next), next ? SEARCH_SETTLE_MS : 0);
    return () => clearTimeout(timer);
  }, [findOpen, query]);
  const search = useMessageSearch(roomName, settled);
  const [historyOpen, setHistoryOpen] = useState(true);
  const serverHits = useMemo(
    () => new Set((search.result?.hits ?? []).map((h) => h.message.id)),
    [search.result],
  );
  const matches = useMemo(() => {
    if (!findOpen || !applied.trim()) return NO_MATCHES;
    // System notices are the feed's own narration, not what anyone said, and
    // several carry an envelope rather than prose. Find searches messages.
    const said = visible.filter(e => !SYSTEM_TYPES.has(e.type));
    // Words alone are matched here, at once. Once a field narrows the query,
    // only the hub can say which messages pass it, so stepping walks the
    // loaded messages its answer named.
    if (!needle || hasScope(applied)) {
      return said.filter(e => e.messageId !== null && serverHits.has(e.messageId)).map(e => e.id);
    }
    return said.filter(e => hasMatch(e.content, needle) || hasMatch(e.sender, needle)).map(e => e.id);
  }, [findOpen, applied, needle, serverHits, visible]);

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
    // A step taken before typing has paused applies what was typed and lands
    // on its newest hit, rather than stepping through the previous query's.
    if (applied !== query) {
      setApplied(query);
      setStanding(null);
      return;
    }
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
      // One walk over the rows for all the hits, not one per hit: a common
      // word hits hundreds of messages, and a scan for each was quadratic.
      const rows = new Map<string, HTMLElement>();
      for (const node of el.querySelectorAll<HTMLElement>("[data-event-id]")) {
        if (node.dataset.eventId) rows.set(node.dataset.eventId, node);
      }
      const next: MinimapTick[] = [];
      for (const id of matches) {
        const row = rows.get(id);
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

  // The scroll behavior every message list shares: open at the newest message,
  // follow it while the reader is there, hold still when they've scrolled up
  // and say how much landed meanwhile, read back a page near the top (and
  // until the view is full: a page of the room can leave a handful of rows
  // here once its thread prose and churn are placed elsewhere). A live message
  // must not pull the view off a hit the reader stepped to, or off a message
  // they arrived at from search; what they just sent takes them back down.
  const newestPending = pending[pending.length - 1]?.id ?? null;
  const rowIds = useMemo(() => (historyLoaded ? visible.map((e) => e.id) : null), [historyLoaded, visible]);
  const follow = useFollowLatest(scroller, {
    rows: rowIds,
    holding: Boolean(highlight || activeId),
    onNearTop: loadOlder,
    sent: newestPending,
    resetKey: roomName,
  });

  useEffect(() => {
    onCountChange?.(visible.length);
  }, [visible.length, onCountChange]);

  useEffect(() => {
    if (!highlight) return;
    highlightRow.current?.scrollIntoView({ block: "center" });
  }, [highlight, historyLoaded, visible]);

  return (
    <div className="flex flex-col h-full">
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
          settling={applied !== query}
          onStep={stepMatch}
          onClose={closeFind}
          inputRef={findInput}
          partial={!reachedStart}
          history={{
            total: search.result?.total ?? null,
            loading: search.loading,
            failed: Boolean(search.error),
            open: historyOpen,
            onToggle: () => setHistoryOpen((o) => !o),
            problems: search.result?.scope.problems ?? [],
          }}
          seen={search.result?.facets}
          handles={searchHandles}
        />
      )}
      {findOpen && historyOpen && query.trim() && (
        <ChatSearchResults
          query={query}
          onQueryChange={value => {
            setQuery(value);
            setStanding(null);
          }}
          result={search.result}
          failed={Boolean(search.error)}
          needles={needles}
          onOpenHit={openHit}
        />
      )}
      {historyLoaded && !(findOpen && historyOpen && query.trim()) && (
        <ActivityRail items={activity} onOpenThread={onOpenThread} onOpenMemory={onOpenMemory} />
      )}
      <div className="relative flex-1 min-h-0">
      <ScrollArea className="h-full" viewportRef={attachScroller}>
        {!historyLoaded ? (
          <ChannelSkeleton />
        ) : visible.length === 0 && pending.length === 0 ? (
          // A room whose every message is task-scoped has a full rail and an
          // empty feed, and "no messages yet" is then a false statement about a
          // room with hundreds of them. Say where the talking went instead.
          activity.length ? (
            <EmptyState
              className="h-full"
              icon={MessagesSquare}
              title="The talking is inside the tasks"
              description="Every message here belongs to a task. Open one from the rail above to read it."
            />
          ) : (
            // A new room says what it is for by what it can start, not by
            // an empty card: each starter is one sentence and one click.
            <RoomStarters roomName={roomName} onStarted={onOpenThread} />
          )
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
        <NowProvider>
        {visible.map((ev, idx) => {
              const marked = highlight !== null && ev.messageId === highlight;
              return (
                <FeedRow
                  key={ev.id}
                  ev={ev}
                  prev={visible[idx - 1]}
                  ctx={feed}
                  pingLine={pingLines.get(ev.id)}
                  marked={marked}
                  rowRef={marked ? highlightRow : undefined}
                  // The row's own share of the open find: whether to mark its
                  // prose at all, and whether it is the hit being stood on.
                  hit={matchSet.has(ev.id) ? { query: needles, active: ev.id === activeId } : undefined}
                />
              );
            })}
        </NowProvider>
          <PendingMessageRows
            roomName={roomName}
            pending={pending}
            previousSender={lastChatSender(visible)}
            onOpenMemory={onOpenMemory}
          />
        </div>
        )}
      </ScrollArea>
      {findOpen && ticks.length > 0 && (
        <ChatMinimap viewportRef={scrollRef} ticks={ticks} activeId={activeId} onJump={setStanding} />
      )}
      </div>
      {!follow.atBottom && visible.length > 0 && <JumpToLatest unread={follow.unread} onClick={follow.jump} />}
      </div>
      {/* Outside the scroll, so it stays over the composer wherever the
          channel is scrolled to, and sending a message can't push it away. */}
      {responding.length > 0 && (
        <RespondingLine entries={responding} room={roomName} threads={threads} onOpenThread={onOpenThread} />
      )}
    </div>
  );
}
