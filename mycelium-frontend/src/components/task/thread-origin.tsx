// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The message a thread was started from, at the top of the thread, where a
 * task's thread shows the task. It's what the thread is about, so it reads as
 * the message did in the channel: who said it, when, and what they said.
 */

import { useRoomMessage } from "@/lib/room-data";
import { Ago } from "@/lib/relative-time";
import { MessageBody } from "@/components/message-body";
import { Monogram } from "@/components/ui/monogram";

export function ThreadOrigin({
  roomName,
  from,
  onOpenMemory,
}: {
  roomName: string;
  /** The id of the message the thread was started from. */
  from: string;
  onOpenMemory?: (key: string) => void;
}) {
  const { message, loading } = useRoomMessage(roomName, from);
  if (!message) {
    return (
      <p className="px-3 py-2 text-label text-faint">
        {loading ? "Loading the message…" : "The message this thread was started from isn't in the room's history."}
      </p>
    );
  }
  const sender = message.sender_handle ?? "someone";
  return (
    <div className="flex gap-2 px-3 py-2" data-testid="thread-origin">
      <Monogram handle={sender} className="mt-0.5 size-5 flex-shrink-0 text-[9px]" />
      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2 text-label">
          <span className="font-medium text-text">{sender}</span>
          {message.created_at && (
            <span className="text-micro text-faint">
              <Ago at={message.created_at} />
            </span>
          )}
        </div>
        <MessageBody
          content={typeof message.content === "string" ? message.content : ""}
          roomName={roomName}
          onOpenMemory={onOpenMemory}
        />
      </div>
    </div>
  );
}
