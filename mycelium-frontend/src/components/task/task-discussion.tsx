// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useRef } from "react";
import { MessagesSquare } from "lucide-react";
import { RoomChatBox } from "@/components/room-chat-box";
import { TaskConversation } from "@/components/task/task-conversation";
import { cn } from "@/lib/utils";

interface Props {
  roomName: string;
  /** The task's thread: the conversation reads it and the composer writes it. */
  episode: string;
  onOpenMemory?: (key: string) => void;
  /** The host's inset (`px-…`), so the heading, the replies and the composer
   *  line up with the task's body above them. */
  className?: string;
}

/** A task with no replies yet: where its conversation starts, and where it goes. */
function NoReplies() {
  return (
    <div className="flex items-start gap-3 px-5 py-3">
      <span className="flex size-8 flex-shrink-0 items-center justify-center rounded-full bg-hairline text-muted-foreground">
        <MessagesSquare className="size-4" />
      </span>
      <div className="min-w-0 space-y-0.5">
        <p className="text-label text-text">No replies yet</p>
        <p className="text-micro text-muted-foreground">
          Start the conversation below. @-mention an agent to bring it in; replies stay in this task, out of the
          room&apos;s channel.
        </p>
      </div>
    </div>
  );
}

/**
 * A task's Discussion, under its body: the heading, the conversation and a
 * composer into the thread. One component for every surface that shows a task
 * as a page (the memory page, a memory tab, the memory panel's drawer), so a
 * task reads the same wherever it is opened.
 *
 * It draws no card: it sits on the surface the body sits on, and the composer's
 * own box is the only box. The conversation's rows carry their own inset, which
 * the negative margin cancels so they line up with the host's.
 */
export function TaskDiscussion({ roomName, episode, onOpenMemory, className }: Props) {
  const refresh = useRef<(() => void) | null>(null);
  const onReady = useCallback((r: () => void) => {
    refresh.current = r;
  }, []);

  return (
    <section data-testid="task-discussion" className={cn("border-t border-border pt-4 pb-6", className)}>
      <h2 className="text-label font-medium text-text">Discussion</h2>
      <div className="-mx-5">
        <TaskConversation
          roomName={roomName}
          episode={episode}
          onOpenMemory={onOpenMemory}
          onReady={onReady}
          empty={<NoReplies />}
          surface="paper"
        />
      </div>
      <RoomChatBox roomName={roomName} episode={episode} inline onSent={() => refresh.current?.()} />
    </section>
  );
}
