// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { usePendingMessages, type Landed } from "@/lib/pending-messages";
import { PendingMessageRows } from "@/components/pending-message-rows";
import { Shimmer, SporeMark } from "@/components/responding-mark";
import {
  applyActivity,
  expireActivity,
  isActivityFrame,
  respondingLabel,
  settleActivity,
  type Responding,
} from "@/lib/activity";
import { useThreadMessages } from "@/lib/room-data";
import { useRoomStream } from "@/lib/stream-hub";
import { pingOf } from "@/lib/threads";
import { CHAT_TYPES, parseEvent, type Event } from "@/lib/room-events";
import { FeedRow, lastChatSender, useFeedContext } from "@/components/messages/feed-row";
import type { ConversationRows } from "@/components/messages/use-follow-latest";
import { Skeleton } from "@/components/ui/skeleton";
import { NowProvider } from "@/lib/relative-time";
import { cn } from "@/lib/utils";

interface Props {
  roomName: string;
  /** The episode URN this conversation reads and writes. */
  episode: string;
  /** A `[[wikilink]]` in a thread message opens the memory, same as in chat. */
  onOpenMemory?: (key: string) => void;
  /**
   * Hands the parent this conversation's `refresh`, so a send through the
   * parent's composer can re-read the episode. The read lives here (one SWR
   * entry per thread), so the parent reaches it through this seam rather than
   * duplicating the hook.
   */
  onReady?: (refresh: () => void) => void;
  /** The surface it sits on, so the pinned "responding" line covers what
   *  scrolls under it. */
  surface?: "bg" | "paper";
  /** What an empty thread shows, for a host that frames it its own way. */
  empty?: ReactNode;
  /** Told what the conversation draws whenever that changes, so the page it
   *  sits in can scroll it the way every message list scrolls. */
  onRows?: (rows: ConversationRows) => void;
}

/**
 * What a thread draws: what was said, and a conductor's lines. A thread also
 * carries its lifecycle (joins, mediator ticks, the commit it converged on),
 * and those are frames, not things anybody said: the row's own state, which
 * the board draws, is where they read.
 */
function drawn(ev: Event): boolean {
  return ev.conductor !== null || (CHAT_TYPES.has(ev.type) && ev.content.trim().length > 0);
}

/**
 * One task's conversation: the messages, and nothing else.
 *
 * It owns no scroll. The task's body, its metadata and this conversation are
 * one column in the surface's single scroll region, so a reply flows on below
 * the task the way a comment follows an issue. The page scrolls it the way
 * every message list scrolls, told what it draws through `onRows`.
 *
 * Each message is the same row the channel draws (`FeedRow`): the sender, the
 * prose, the verifier's lines, the hover actions and the right-click menu.
 *
 * The composer stays with the parent (a task is rendered in more than one place
 * and the composer's chrome differs), so this is just the read and its
 * rendering. The read is its own SWR entry (`useThreadMessages`), so showing a
 * conversation never replaces the room's feed with a filtered slice of itself.
 */
export function TaskConversation({
  roomName,
  episode,
  onOpenMemory,
  onReady,
  empty,
  surface = "bg",
  onRows,
}: Props) {
  const { messages, loading, refresh, hasOlder, loadOlder, loadingOlder } =
    useThreadMessages(roomName, episode);
  const feed = useFeedContext(roomName, { onOpenMemory });

  // Hand the parent our refresh once it is stable, so its composer's onSent can
  // re-read this episode after a send.
  useEffect(() => {
    onReady?.(refresh);
  }, [onReady, refresh]);

  // Who is mid-turn in this thread. The same signal the channel folds, scoped
  // to this episode: a turn going elsewhere is not this conversation's news.
  const [responding, setResponding] = useState<Responding[]>([]);
  useEffect(() => {
    if (responding.length === 0) return;
    const tick = setInterval(() => setResponding(prev => expireActivity(prev, Date.now())), 1_000);
    return () => clearInterval(tick);
  }, [responding.length]);

  // A write into this thread reaches the room's one multiplexed stream twice —
  // as the message itself (tagged with this episode) and as the ping that
  // announces it (tagged `live`, naming this episode in its payload). Either is
  // reason to re-read; nothing else here is, so a busy room does not refetch a
  // quiet thread. The refresh is a revalidation, not an append: the region stays
  // a read of one episode rather than a second feed assembled by hand.
  useRoomStream(roomName, frame => {
    const message = frame as Record<string, unknown>;
    if (isActivityFrame(message)) {
      if (message.episode === episode) setResponding(prev => applyActivity(prev, message, Date.now()));
      return;
    }
    if (message.episode === episode) {
      setResponding(prev => settleActivity(prev, message.sender_handle as string | undefined));
      refresh();
      return;
    }
    let content = message.content;
    if (typeof content === "string") {
      try {
        content = JSON.parse(content);
      } catch {
        return;
      }
    }
    if (pingOf(content as Record<string, unknown>)?.episode === episode) refresh();
  });

  // The backend answers newest-first; a conversation reads the other way. Read
  // the way the channel reads a message, so a row here is the row there.
  // Every refresh re-reads the whole thread, and `parseEvent` gives each event
  // a fresh id, so a row keeps its message's own id instead (each is unique
  // in one read). Otherwise every poll remounts every row: an expanded Show
  // more closes, the page's height jumps, and following the latest sees every
  // row as new.
  const events = useMemo(
    () =>
      [...messages]
        .reverse()
        .map((m) => {
          const ev = parseEvent(m);
          return ev.messageId ? { ...ev, id: ev.messageId } : ev;
        })
        .filter(drawn),
    [messages],
  );

  // What you sent here that the read doesn't have yet, drawn under it.
  const landed = useMemo<Landed[]>(
    () =>
      events
        .filter((ev) => CHAT_TYPES.has(ev.type))
        .map((ev) => ({ id: ev.messageId, sender: ev.sender, content: ev.content, at: ev.at })),
    [events],
  );
  const pending = usePendingMessages(roomName, episode, landed);
  const newestPending = pending[pending.length - 1]?.id ?? null;

  // Reading back asks for one more page at a time: the page is wider once the
  // answer is, not once per scroll event at the top.
  const askedAt = useRef<number | null>(null);
  const readBack = useCallback(() => {
    if (askedAt.current === messages.length) return;
    askedAt.current = messages.length;
    loadOlder();
  }, [loadOlder, messages.length]);

  const rowIds = useMemo(() => (loading && events.length === 0 ? null : events.map((ev) => ev.id)), [loading, events]);
  useEffect(() => {
    onRows?.({ rows: rowIds, sent: newestPending, onNearTop: hasOlder ? readBack : undefined });
  }, [onRows, rowIds, newestPending, hasOlder, readBack]);

  return (
    <div data-testid="thread-conversation">
      {loading && events.length === 0 && pending.length === 0 ? (
        <div className="flex flex-col gap-4 px-5 py-4">
          <Skeleton className="h-3 w-2/5" />
          <Skeleton className="h-3 w-3/5" />
        </div>
      ) : events.length === 0 && pending.length === 0 ? (
        // A quiet line, not a card: an empty thread is where every task starts.
        empty ?? <p className="px-5 py-3 text-micro text-faint">
          No replies yet. Reply below, or @-mention an agent: it lands in this task, not in the room.
        </p>
      ) : (
        <NowProvider>
          <div className="py-3">
            {/* Reading near the top of the page asks for these too; this is the
                same thing as a control, for a page whose top is the task. */}
            {hasOlder && (
              <div className="px-5 pb-2 text-center">
                <button
                  type="button"
                  onClick={loadOlder}
                  disabled={loadingOlder}
                  className="text-micro text-muted-foreground underline-offset-2 hover:underline disabled:no-underline disabled:opacity-60"
                >
                  {loadingOlder ? "Loading earlier replies…" : "Load earlier replies"}
                </button>
              </div>
            )}
            {events.map((ev, i) => (
              <FeedRow key={ev.id} ev={ev} prev={events[i - 1]} ctx={feed} />
            ))}
            <PendingMessageRows
              roomName={roomName}
              pending={pending}
              previousSender={lastChatSender(events)}
              onOpenMemory={onOpenMemory}
            />
          </div>
        </NowProvider>
      )}
      {responding.length > 0 && (
        <div
          role="status"
          aria-live="polite"
          data-testid="responding-line"
          // Sticks to the bottom of whatever scrolls this conversation, so it
          // stays by the composer however far up the thread is scrolled.
          className={cn(
            "sticky bottom-0 mt-2 flex items-center gap-2 px-5 py-1 text-micro text-muted-foreground",
            surface === "paper" ? "bg-paper" : "bg-bg",
          )}
        >
          <SporeMark />
          <Shimmer className="truncate">{respondingLabel(responding)}</Shimmer>
        </div>
      )}
    </div>
  );
}
