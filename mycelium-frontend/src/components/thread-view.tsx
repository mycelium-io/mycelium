// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef } from "react";
import { MessageSquare, X } from "lucide-react";
import type { RoomMessage } from "@/lib/api";
import { useRoomAgents, useThreadMessages } from "@/lib/room-data";
import { useRoomStream } from "@/lib/stream-hub";
import { pingOf, threadShortId } from "@/lib/threads";
import { MarkdownContent } from "@/components/markdown-content";
import { RoomChatBox } from "@/components/room-chat-box";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Monogram } from "@/components/ui/monogram";
import { Kbd } from "@/components/ui/kbd";
import { Tooltip } from "@/components/ui/tooltip";

/** What a thread is a thread *of*, as far as anything can tell. */
export interface ThreadTarget {
  /** The episode URN the conversation is tagged with. */
  episode: string;
  /**
   * The task this thread belongs to, when the room knows. A coordination phase
   * opens its own episode and records no back-link to the task that summoned
   * it, so this is absent for one — the pane says which thread rather than
   * inventing which task.
   */
  title?: string | null;
}

interface Props {
  roomName: string;
  target: ThreadTarget;
  onClose: () => void;
  /** A `[[wikilink]]` in a thread message opens the memory, same as in chat. */
  onOpenMemory?: (key: string) => void;
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

/**
 * One task's conversation, on its own.
 *
 * A **transient pane**, not a rail: it is here because you opened a row and
 * gone when you close it, and the room keeps no chrome for it in between —
 * the same restraint that keeps skills out of a rail of their own. There is
 * deliberately no "all threads" view either: a thread is reached through the
 * task it belongs to, which is the only place it means anything.
 *
 * The read is its own SWR entry (`useThreadMessages`), so opening this never
 * replaces the room's feed with a filtered slice of itself, and the composer at
 * the foot is the room's composer pointed at this episode — one way to write,
 * aimed differently.
 */
export function ThreadView({ roomName, target, onClose, onOpenMemory }: Props) {
  const { messages, loading, refresh } = useThreadMessages(roomName, target.episode);
  const { agents } = useRoomAgents(roomName);
  const agentHandles = new Set(agents.map(a => a.handle));
  const shortId = threadShortId(target.episode) ?? "thread";
  const scrollRef = useRef<HTMLDivElement>(null);

  // A write into this thread reaches the room's one multiplexed stream twice —
  // as the message itself (tagged with this episode) and as the ping that
  // announces it (tagged `live`, naming this episode in its payload). Either is
  // reason to re-read; nothing else here is, so a busy room does not refetch a
  // quiet thread. The refresh is a revalidation, not an append: the pane stays
  // a read of one episode rather than a second feed assembled by hand.
  useRoomStream(roomName, frame => {
    const message = frame as Record<string, unknown>;
    if (message.episode === target.episode) {
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
    if (pingOf(content as Record<string, unknown>)?.episode === target.episode) refresh();
  });

  // Esc closes: the pane is transient, so leaving it must be as cheap as
  // opening it was.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const el = e.target as HTMLElement | null;
      if (el && /^(INPUT|TEXTAREA|SELECT)$/.test(el.tagName)) return;
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // The backend answers newest-first; a conversation reads the other way.
  //
  // A thread carries its lifecycle as well as its argument — joins, mediator
  // ticks, the commit it converged on — and those are frames, not things
  // anybody said. Selecting on whether a message has prose keeps the pane a
  // conversation without it having to know which types aren't one; what the
  // lifecycle amounts to is the row's own state, which the board already draws.
  const ordered = [...messages]
    .reverse()
    .map(message => ({ message, text: textOf(message) }))
    .filter(({ text }) => text.trim().length > 0);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [ordered.length]);

  return (
    <section
      aria-label={`Thread ${shortId}`}
      data-thread={target.episode}
      className="flex min-h-0 flex-1 flex-col bg-bg"
    >
      <header className="flex h-[48px] shrink-0 items-center gap-2 border-b border-border bg-paper px-4">
        <MessageSquare className="size-3.5 shrink-0 text-accent" strokeWidth={1.9} />
        <span className="min-w-0 truncate text-label font-semibold text-text">
          {target.title || `Thread ${shortId}`}
        </span>
        {/* The short id only where a task's name is what the header says —
            otherwise the header is already the id, and this would repeat it. */}
        {target.title && (
          <Tooltip content={target.episode}>
            <span className="shrink-0 rounded bg-hairline px-1.5 py-px font-mono text-micro text-muted-foreground">
              {shortId}
            </span>
          </Tooltip>
        )}
        <span className="ml-auto flex items-center gap-2">
          <Kbd size="xs" tone="muted">Esc</Kbd>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close thread"
            className="grid size-6 place-items-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
          >
            <X className="size-3.5" strokeWidth={1.9} />
          </button>
        </span>
      </header>

      <ScrollArea className="min-h-0 flex-1" viewportRef={scrollRef}>
        {loading && ordered.length === 0 ? (
          <div className="flex flex-col gap-4 px-5 py-4">
            <Skeleton className="h-3 w-2/5" />
            <Skeleton className="h-3 w-3/5" />
          </div>
        ) : ordered.length === 0 ? (
          <EmptyState
            className="h-full"
            icon={MessageSquare}
            title="Nothing said here yet"
            description="Reply below, or @-mention an agent — it lands in this task, not in the room."
          />
        ) : (
          <div className="py-3">
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
                    <MarkdownContent
                      className="contrast text-body leading-relaxed"
                      onLinkClick={onOpenMemory}
                    >
                      {text}
                    </MarkdownContent>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </ScrollArea>

      <RoomChatBox
        roomName={roomName}
        episode={target.episode}
        threadLabel={target.title || shortId}
        onSent={refresh}
      />
    </section>
  );
}
