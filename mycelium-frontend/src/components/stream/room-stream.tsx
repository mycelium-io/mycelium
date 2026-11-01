// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Fragment, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { X } from "lucide-react";
import { EmptyState } from "@/components/empty-state";
import { VIEW_ICONS } from "@/components/room-views-nav";
import { fetchWireHistory, logFetchError } from "@/lib/api";
import { useRoomStream } from "@/lib/stream-hub";
import { useRoomThreads } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { MessageBody } from "@/components/message-body";
import { Chip } from "@/components/ui/chip";
import { EventIconMark } from "@/components/event-icon";
import { JumpToLatest } from "@/components/jump-to-latest";
import { useFollowLatest } from "@/components/messages/use-follow-latest";
import { MessageRow, useFeedContext } from "@/components/messages/feed-row";
import { parseEvent } from "@/lib/room-events";
import { MEMORY_ICON, noticeIcon, type EventIcon } from "@/lib/event-icons";

/** The icon for a board, pull request or saved-memory line: the chat's table. */
function eventIconOf(ev: StreamEvent): EventIcon {
  if (ev.kind === "saved") return MEMORY_ICON;
  if (ev.kind === "github") return noticeIcon("upstream", ev.change);
  return noticeIcon(ev.subkind ?? "", null, ev.rowKind);
}
import {
  ALL_KINDS,
  dayLabel,
  dayOf,
  describe,
  firstLine,
  foldEvents,
  lanesOf,
  matches,
  streamEventOf,
  type StreamEvent,
  type StreamKind,
} from "@/lib/room-stream";
import { cn } from "@/lib/utils";

/** How much of the room's history the Stream reads when it opens. */
const HISTORY = 400;
/** The most lines kept while the tab stays open; the oldest go first, so a
 *  room left open all day stays quick to draw. */
const KEEP = 2000;
/** The gutter: the channel's own rule, then one column per lane. */
const LANE_X0 = 14;
const LANE_STEP = 9;
/** An event line in the room's own channel has no lane, so its icon is a
 *  neutral grey rather than any thread's color. */
const CHANNEL_TONE = "var(--muted-foreground)";

const KIND_LABELS: { kind: StreamKind; label: string }[] = [
  { kind: "message", label: "Messages" },
  { kind: "board", label: "Board" },
  { kind: "github", label: "GitHub" },
  { kind: "saved", label: "Saved" },
];

const seenKey = (room: string) => `mycelium.stream.seen.${room}`;

function loadSeen(room: string): string | null {
  try {
    return window.localStorage.getItem(seenKey(room));
  } catch {
    return null;
  }
}

function saveSeen(room: string, at: string): void {
  try {
    window.localStorage.setItem(seenKey(room), at);
  } catch {
    // Not remembered: the next visit just has no "new since" line.
  }
}

const clock = (iso: string) => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "" : d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
};

/** A message's first line, with `@handles` drawn as mentions and yours marked. */
function MessageLine({ text, me }: { text: string; me: string }) {
  const parts: ReactNode[] = [];
  const line = firstLine(text);
  const re = /(^|[\s(<])@(~|!)?([A-Za-z0-9][\w-]*)/g;
  let last = 0;
  for (const m of line.matchAll(re)) {
    const start = (m.index ?? 0) + m[1].length;
    parts.push(line.slice(last, start));
    const mine = m[3].toLowerCase() === me && m[2] !== "~";
    parts.push(
      <span key={start} className={mine ? "rounded-sm bg-accent px-0.5 font-semibold text-accent-fg" : "text-accent"}>
        @{m[2] ?? ""}
        {m[3]}
      </span>,
    );
    last = start + m[0].length - m[1].length;
  }
  parts.push(line.slice(last));
  return <>{parts}</>;
}

interface Props {
  roomName: string;
  onOpenThread: (episode: string) => void;
  onOpenMemory?: (key: string) => void;
}

/**
 * The Stream tab: everything that happens in the room, one line each, in time
 * order. Messages in the channel and in every task's thread, board changes,
 * pull request changes and saved memories, with nothing ranked or hidden.
 * Each thread on screen gets a colored lane in the gutter, so conversations
 * running in parallel can be told apart. Clicking a message opens it in place;
 * a task's tag opens its thread as a tab.
 *
 * It's read-only: a stream to watch, not a place to talk. Replying happens in
 * the channel or in a task's thread, where the conversation is.
 */
export function RoomStream({ roomName, onOpenThread, onOpenMemory }: Props) {
  const [events, setEvents] = useState<StreamEvent[]>([]);
  const seenIds = useRef<Set<string>>(new Set());
  const threads = useRoomThreads(roomName);
  const feed = useFeedContext(roomName, { onOpenThread, onOpenMemory });
  const { principal } = useCurrentUser();
  const me = principal.trim().replace(/^@/, "").toLowerCase();

  const [kinds, setKinds] = useState<Set<StreamKind>>(() => new Set(ALL_KINDS));
  const [mineOnly, setMineOnly] = useState(false);
  const [who, setWho] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [seenAt, setSeenAt] = useState<string | null>(null);

  // History first, then whatever the live feed adds; ids keep the two from
  // doubling up when a frame arrives both ways.
  useEffect(() => {
    let canceled = false;
    seenIds.current = new Set();
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the previous room's lines go before the new ones load
    setEvents([]);
    setSeenAt(loadSeen(roomName));
    fetchWireHistory(roomName, HISTORY)
      .then((rows) => {
        if (canceled) return;
        const seeded: StreamEvent[] = [];
        for (const row of rows) {
          const ev = streamEventOf(row, roomName);
          if (ev && !seenIds.current.has(ev.id)) {
            seenIds.current.add(ev.id);
            seeded.push(ev);
          }
        }
        setEvents((prev) => [...seeded, ...prev]);
      })
      .catch(logFetchError("fetchWireHistory"));
    return () => {
      canceled = true;
    };
  }, [roomName]);

  useRoomStream(roomName, (data) => {
    const ev = streamEventOf(data as Record<string, unknown>, roomName);
    if (!ev || seenIds.current.has(ev.id)) return;
    seenIds.current.add(ev.id);
    setEvents((prev) => (prev.length >= KEEP ? [...prev.slice(prev.length - KEEP + 1), ev] : [...prev, ev]));
  });

  // What you've seen is remembered when you leave the tab or the window, so
  // the next visit draws "new since you last looked" where you left off.
  const latest = events.length ? events[events.length - 1].at : null;
  const latestRef = useRef(latest);
  useLayoutEffect(() => {
    latestRef.current = latest;
  }, [latest]);
  useEffect(() => {
    const remember = () => {
      if (latestRef.current) saveSeen(roomName, latestRef.current);
    };
    window.addEventListener("blur", remember);
    return () => {
      window.removeEventListener("blur", remember);
      remember();
    };
  }, [roomName]);

  const lines = useMemo(() => {
    const filter = { kinds, mentioning: mineOnly ? me : null, who, where: null };
    // Time order, whatever order the history and the live feed arrived in.
    const ordered = events.filter((e) => matches(e, filter)).sort((a, b) => a.at.localeCompare(b.at));
    return foldEvents(ordered);
  }, [events, kinds, mineOnly, me, who]);
  const lanes = useMemo(() => lanesOf(lines), [lines]);
  const columns = lanes.reduce((n, l) => Math.max(n, l.column + 1), 0);
  const gutter = LANE_X0 + columns * LANE_STEP + 6;
  const newAt = seenAt ? lines.findIndex((l) => l.event.at > seenAt) : -1;

  // The scroll behavior every message list shares: open at the newest line,
  // stay there as lines arrive unless you've scrolled up to read, and then the
  // same "Jump to latest", counting the messages that arrived meanwhile (by
  // which ones, so it holds once the oldest lines start dropping off). A
  // change of filter starts over, since the lines are different ones.
  const [scroller, setScroller] = useState<HTMLDivElement | null>(null);
  const lineIds = useMemo(() => lines.map((l) => l.event.id), [lines]);
  const messageIds = useMemo(
    () => lines.filter((l) => l.event.kind === "message").map((l) => l.event.id),
    [lines],
  );
  const filterKey = `${roomName}|${[...kinds].sort().join(",")}|${mineOnly}|${who ?? ""}`;
  const jumpTo = useFollowLatest(scroller, { rows: lineIds, counted: messageIds, resetKey: filterKey });

  const titleOf = useCallback((episode: string) => threads.get(episode)?.title ?? null, [threads]);
  const toggleKind = (kind: StreamKind) =>
    setKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind);
      else next.add(kind);
      return next;
    });

  return (
    <div className="flex h-full min-w-0 flex-col overflow-hidden bg-bg">
      <div className="flex flex-shrink-0 flex-wrap items-center gap-1.5 border-b border-border px-3 py-1.5">
        {KIND_LABELS.map(({ kind, label }) => (
          <Chip key={kind} active={kinds.has(kind)} onClick={() => toggleKind(kind)}>
            {label}
          </Chip>
        ))}
        <span className="mx-1 h-4 w-px bg-border" aria-hidden />
        {me && (
          <Chip variant="accent" active={mineOnly} onClick={() => setMineOnly((v) => !v)}>
            @{me}
          </Chip>
        )}
        {who && (
          <Chip active onClick={() => setWho(null)}>
            <span className="inline-flex items-center gap-1">
              {who}
              <X className="size-3" aria-label={`Show everyone, not just ${who}`} />
            </span>
          </Chip>
        )}
        <span className="ml-auto text-micro tabular text-faint">{lines.length} lines</span>
      </div>

      <div
        ref={setScroller}
        className="min-h-0 flex-1 overflow-y-auto py-1.5"
        role="log"
        aria-label="Everything in the room, newest last"
      >
        {lines.length === 0 ? (
          <EmptyState
            icon={VIEW_ICONS.stream}
            title="Nothing has happened in this room yet"
            description="Messages, board moves, pull requests and saved memories show here as they happen."
          />
        ) : (
          lines.map((line, i) => {
            const ev = line.event;
            const lane = ev.episode ? lanes.find((l) => l.episode === ev.episode) : undefined;
            const color = lane?.color ?? "var(--faint)";
            const title = ev.title ?? (ev.episode ? titleOf(ev.episode) : null);
            const isMessage = ev.kind === "message";
            const mentionsMe = isMessage && !!me && ev.mentions.includes(me);
            const open = expanded.has(ev.id);
            return (
              <Fragment key={ev.id}>
                {/* A quiet line wherever the day changes, so 18:10 then 15:10
                    reads as the next day rather than out of order. */}
                {(i === 0 || dayOf(lines[i - 1].event.at) !== dayOf(ev.at)) && (
                  <div
                    role="separator"
                    aria-label={dayLabel(ev.at)}
                    className="mx-3 mb-0.5 mt-2 flex items-center gap-2 text-micro font-medium text-faint first:mt-0"
                  >
                    <span className="h-px flex-1 bg-border" aria-hidden />
                    {dayLabel(ev.at)}
                    <span className="h-px flex-1 bg-border" aria-hidden />
                  </div>
                )}
                {i === newAt && (
                  <div className="mx-3 my-1 flex items-center gap-2 text-micro font-semibold text-red">
                    New since you last looked
                    <span className="h-px flex-1 bg-red/50" aria-hidden />
                  </div>
                )}
                <div
                  data-line={ev.id}
                  className={cn(
                    "relative grid min-h-[22px] cursor-default items-baseline gap-x-2.5 px-3 hover:bg-hairline",
                    mentionsMe && "bg-accent-soft/40 before:absolute before:inset-y-0 before:left-0 before:w-0.5 before:bg-accent",
                  )}
                  style={{ gridTemplateColumns: `2.5rem ${gutter}px 8rem minmax(0,1fr)` }}
                  onClick={() => {
                    if (!isMessage) return;
                    setExpanded((prev) => {
                      const next = new Set(prev);
                      if (next.has(ev.id)) next.delete(ev.id);
                      else next.add(ev.id);
                      return next;
                    });
                  }}
                >
                  <span className="font-mono text-[11px] tabular text-faint">{clock(ev.at)}</span>
                  <span className="relative self-stretch" aria-hidden>
                    <span className="absolute inset-y-0 w-px bg-border" style={{ left: 4 }} />
                    {lanes
                      .filter((l) => i >= l.from && i <= l.to)
                      .map((l) => (
                        <span
                          key={l.episode}
                          className="absolute inset-y-0 w-0.5 rounded-full opacity-40"
                          style={{ left: LANE_X0 + l.column * LANE_STEP, background: l.color }}
                        />
                      ))}
                    {/* A message is a dot in its thread's color; any other line is
                        the chat's icon for what happened, in the same place, so
                        every line's columns stay where they are. */}
                    {isMessage ? (
                      <span
                        className="absolute top-1/2 size-2 -translate-x-[3px] -translate-y-1/2 rounded-full ring-2 ring-bg"
                        style={{ left: lane ? LANE_X0 + lane.column * LANE_STEP : 4, background: color }}
                      />
                    ) : (
                      <span
                        className="absolute top-1/2 flex -translate-x-[5px] -translate-y-1/2 rounded-sm bg-bg"
                        style={{ left: lane ? LANE_X0 + lane.column * LANE_STEP : 4 }}
                      >
                        {/* Colored like the lane it sits on: the shape says what
                            happened, the color which thread. */}
                        <EventIconMark icon={eventIconOf(ev)} tone={lane?.color ?? CHANNEL_TONE} />
                      </span>
                    )}
                  </span>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      setWho(ev.who === who ? null : ev.who);
                    }}
                    className={cn(
                      "truncate text-left text-label",
                      isMessage ? "font-medium text-text" : "text-faint",
                    )}
                  >
                    {ev.who}
                  </button>
                  <span className={cn("min-w-0 truncate text-label", isMessage ? "text-text" : "text-faint")}>
                    {/* The gutter is hidden from screen readers, so its icon's
                        words are said here instead. */}
                    {!isMessage && <span className="sr-only">{eventIconOf(ev).label}: </span>}
                    {ev.episode && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          onOpenThread(ev.episode!);
                        }}
                        className="mr-2 rounded px-1.5 text-micro"
                        style={{ background: `color-mix(in srgb, ${color} 18%, transparent)`, color }}
                        title={title ?? undefined}
                      >
                        {title ? (title.length > 26 ? `${title.slice(0, 25)}…` : title) : "thread"}
                      </button>
                    )}
                    {isMessage ? <MessageLine text={ev.text} me={me} /> : describe(ev, { withTitle: !ev.episode })}
                    {line.more.map((m) => (
                      <span key={m.id} className="ml-1.5 text-faint">
                        · {describe(m, { withTitle: !m.episode })}
                      </span>
                    ))}
                  </span>
                </div>
                {/* Opened, a message is the same row every list draws: its
                    actions, its menu and the verifier's lines with it. */}
                {open && (
                  <div className="mx-3 mb-1 mt-0.5 rounded-r-md border-l-2 border-border2 bg-surface py-2">
                    {ev.frame ? (
                      <MessageRow ev={parseEvent(ev.frame)} grouped={false} ctx={feed} />
                    ) : (
                      <div className="px-3 text-label">
                        <MessageBody content={ev.text} roomName={roomName} onOpenMemory={onOpenMemory} />
                      </div>
                    )}
                  </div>
                )}
              </Fragment>
            );
          })
        )}
      </div>
      {/* No height of its own: the pill floats up from here over the log's bottom edge. */}
      <div className="relative h-0 flex-shrink-0">
        {!jumpTo.atBottom && lines.length > 0 && <JumpToLatest unread={jumpTo.unread} onClick={jumpTo.jump} />}
      </div>
    </div>
  );
}
