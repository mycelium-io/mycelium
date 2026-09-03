// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef, useState } from "react";
import { MessageSquare } from "lucide-react";
import type { RoomMessage } from "@/lib/api";
import {
  applyActivity,
  expireActivity,
  isActivityFrame,
  respondingLabel,
  settleActivity,
  type Responding,
} from "@/lib/activity";
import { useRoomAgents, useThreadMessages } from "@/lib/room-data";
import { useRoomStream } from "@/lib/stream-hub";
import { pingOf } from "@/lib/threads";
import { MessageBody } from "@/components/message-body";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Monogram } from "@/components/ui/monogram";

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
}

/** The prose a thread message carries, or "" when it carries none. */
function textOf(message: RoomMessage): string {
  const content = message.content;
  if (typeof content !== "string") return "";
  if (!content.startsWith("{")) return content;
  try {
    const parsed = JSON.parse(content) as Record<string, unknown>;
    return typeof parsed.content === "string"
      ? parsed.content
      : typeof parsed.text === "string"
        ? parsed.text
        : "";
  } catch {
    return content;
  }
}

/** How close to the bottom you have to be for a new reply to pull you down. */
const STICK_PX = 120;

/** The scrollable ancestor an element sits in, if it has one. */
function scrollParentOf(el: HTMLElement | null): HTMLElement | null {
  for (let node = el?.parentElement ?? null; node; node = node.parentElement) {
    const overflow = getComputedStyle(node).overflowY;
    if (overflow === "auto" || overflow === "scroll") return node;
  }
  return null;
}

/**
 * One task's conversation: the messages, and nothing else.
 *
 * It owns no scroll. The task's body, its metadata and this conversation are
 * one column in the surface's single scroll region, so a reply flows on below
 * the task the way a comment follows an issue — rather than sitting in a
 * fixed-height box with a scrollbar of its own a few pixels inside the pane's.
 *
 * The composer stays with the parent (a task is rendered in more than one place
 * and the composer's chrome differs), so this is just the read and its
 * rendering. The read is its own SWR entry (`useThreadMessages`), so showing a
 * conversation never replaces the room's feed with a filtered slice of itself.
 */
export function TaskConversation({ roomName, episode, onOpenMemory, onReady }: Props) {
  const { messages, loading, refresh, hasOlder, loadOlder, loadingOlder } =
    useThreadMessages(roomName, episode);
  const { agents } = useRoomAgents(roomName);
  const agentHandles = new Set(agents.map(a => a.handle));
  const endRef = useRef<HTMLDivElement>(null);

  // Hand the parent our refresh once it is stable, so its composer's onSent can
  // re-read this episode after a send.
  useEffect(() => {
    onReady?.(refresh);
  }, [onReady, refresh]);

  // A write into this thread reaches the room's one multiplexed stream twice —
  // as the message itself (tagged with this episode) and as the ping that
  // announces it (tagged `live`, naming this episode in its payload). Either is
  // reason to re-read; nothing else here is, so a busy room does not refetch a
  // quiet thread. The refresh is a revalidation, not an append: the region stays
  // a read of one episode rather than a second feed assembled by hand.
  // Who is mid-turn in this thread. The same signal the channel folds, scoped
  // to this episode: a turn going elsewhere is not this conversation's news.
  const [responding, setResponding] = useState<Responding[]>([]);
  useEffect(() => {
    if (responding.length === 0) return;
    const tick = setInterval(() => setResponding(prev => expireActivity(prev, Date.now())), 1_000);
    return () => clearInterval(tick);
  }, [responding.length]);

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

  // The backend answers newest-first; a conversation reads the other way.
  //
  // A thread carries its lifecycle as well as its argument — joins, mediator
  // ticks, the commit it converged on — and those are frames, not things
  // anybody said. Selecting on whether a message has prose keeps this a
  // conversation without it having to know which types aren't one; what the
  // lifecycle amounts to is the row's own state, which the board already draws.
  const ordered = [...messages]
    .reverse()
    .map(message => ({ message, text: textOf(message) }))
    .filter(({ text }) => text.trim().length > 0);

  // A reply that lands while you are reading the bottom pulls you down with it;
  // one that lands while you are further up does not, and opening the task lands
  // on the task rather than on its last comment. With one scroll for the whole
  // column, sticking unconditionally would scroll the body out of view the
  // moment anything arrived.
  const count = ordered.length;
  const seen = useRef<number | null>(null);
  useEffect(() => {
    const first = seen.current === null;
    seen.current = count;
    if (first || count === 0) return;
    const anchor = endRef.current;
    const viewport = scrollParentOf(anchor);
    if (!anchor || !viewport) return;
    const fromBottom = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight;
    if (fromBottom > STICK_PX) return;
    anchor.scrollIntoView({ block: "end" });
  }, [count]);

  return (
    <div>
      {loading && ordered.length === 0 ? (
        <div className="flex flex-col gap-4 px-5 py-4">
          <Skeleton className="h-3 w-2/5" />
          <Skeleton className="h-3 w-3/5" />
        </div>
      ) : ordered.length === 0 ? (
        <EmptyState
          className="py-14"
          icon={MessageSquare}
          title="No replies yet"
          description="Reply below, or @-mention an agent — it lands in this task, not in the room."
        />
      ) : (
        <div className="py-3">
          {/* A control, not a scroll trigger. This conversation owns no scroll —
              it is the lower half of the task's own column — so "near the top"
              is a position in the task above it, not in the thread. Asking is
              the honest gesture here. */}
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
          {ordered.map(({ message, text }, i) => {
            const sender = message.sender_handle ?? message.updated_by ?? "?";
            const previous = ordered[i - 1]?.message;
            const grouped = previous && (previous.sender_handle ?? previous.updated_by) === sender;
            const isAgent = agentHandles.has(sender);
            return (
              <div
                key={message.id ?? `${sender}-${i}`}
                className={`flex gap-3 px-5 ${grouped ? "py-0.5" : "mt-3 pt-1 first:mt-0"}`}
              >
                <div className="w-7 flex-shrink-0">
                  {!grouped && (
                    <Monogram
                      handle={sender}
                      color={isAgent ? undefined : "var(--avatar-neutral)"}
                      className="size-7 text-micro"
                    />
                  )}
                </div>
                <div className="min-w-0 flex-1">
                  {!grouped && (
                    <span className="text-label font-semibold text-text">{sender}</span>
                  )}
                  <MessageBody content={text} onOpenMemory={onOpenMemory} />
                </div>
              </div>
            );
          })}
        </div>
      )}
      {responding.length > 0 && (
        <div
          role="status"
          aria-live="polite"
          data-testid="responding-line"
          className="mt-2 flex items-center gap-2 px-5 py-1 text-micro text-muted-foreground"
        >
          <span
            aria-hidden
            className="inline-block size-1.5 flex-shrink-0 rounded-full motion-safe:animate-pulse"
            style={{ background: "var(--accent)" }}
          />
          <span className="truncate">{respondingLabel(responding)}</span>
        </div>
      )}
      <div ref={endRef} />
    </div>
  );
}
