// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The line under a message someone started a thread from: who replied, how
 * many replies, the newest one's opening words and when, and the task made
 * from it, if one was. One dense line, the channel's own register, and a click
 * opens the thread in the dock where a task's thread opens. The replies stay
 * in the thread, so the channel reads the same with a busy thread as with a
 * quiet one. What it says comes with the room's memory list (the hub works it
 * out from the room's history), so drawing it reads nothing of its own.
 */

import { CornerDownRight, ListTodo } from "lucide-react";
import type { MessageThread } from "@/lib/room-data";
import { Ago } from "@/lib/relative-time";
import { Monogram } from "@/components/ui/monogram";

export function ThreadReplies({
  thread,
  onOpen,
}: {
  thread: MessageThread;
  onOpen?: (episode: string) => void;
}) {
  const { replies, repliers, last_reply: quote, last_reply_at: at } = thread.replies;
  const count = replies === 0 ? "Thread" : `${replies} ${replies === 1 ? "reply" : "replies"}`;
  const task = thread.task;
  return (
    <div className="-mx-1.5 mt-1 flex h-7 w-[calc(100%+0.75rem)] min-w-0 max-w-2xl items-center gap-1 text-label">
      <button
        type="button"
        onClick={() => onOpen?.(thread.episode)}
        aria-label={`Open the thread "${thread.title}", ${replies === 0 ? "no replies yet" : count}`}
        className="flex h-full min-w-0 flex-1 items-center gap-2 rounded-md px-1.5 text-left hover:bg-hairline"
      >
        <CornerDownRight className="size-3.5 flex-shrink-0 text-faint" aria-hidden />
        {repliers.length > 0 && (
          <span className="flex flex-shrink-0 gap-0.5">
            {repliers.map((h) => (
              <Monogram key={h} handle={h} className="size-[18px] text-[8px]" />
            ))}
          </span>
        )}
        <span className="flex-shrink-0 font-medium text-accent">{count}</span>
        {quote && <span className="min-w-0 flex-1 truncate text-muted-foreground">{quote}</span>}
        {at && (
          <span className="ml-auto flex-shrink-0 text-micro text-faint">
            <Ago at={at} />
          </span>
        )}
      </button>
      {task?.episode && (
        <button
          type="button"
          onClick={() => onOpen?.(task.episode as string)}
          aria-label={`Open the task "${task.title}"`}
          title={task.title}
          className="flex h-full max-w-[40%] flex-shrink-0 items-center gap-1 rounded-md px-1.5 text-muted-foreground hover:bg-hairline hover:text-text"
        >
          <ListTodo className="size-3.5 flex-shrink-0" aria-hidden />
          <span className="truncate">{task.title}</span>
        </button>
      )}
    </div>
  );
}
