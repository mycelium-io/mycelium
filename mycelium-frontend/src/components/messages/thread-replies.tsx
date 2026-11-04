// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The line under a message someone started a thread from: who replied, how
 * many replies, the newest one's opening words and when. One dense line, the
 * channel's own register, and a click opens the thread in the dock where a
 * task's thread opens. The replies themselves stay in the thread, so the
 * channel reads the same with a busy thread as with a quiet one.
 */

import { CornerDownRight } from "lucide-react";
import { useThreadMessages, type MessageThread } from "@/lib/room-data";
import { Ago } from "@/lib/relative-time";
import { Monogram } from "@/components/ui/monogram";

/** How many repliers the line shows faces for. */
const FACES = 3;

export function ThreadReplies({
  roomName,
  thread,
  onOpen,
}: {
  roomName: string;
  thread: MessageThread;
  onOpen?: (episode: string) => void;
}) {
  const { messages } = useThreadMessages(roomName, thread.episode, 50);
  const said = messages.filter((m) => m.message_type === "broadcast" || m.message_type === "l9_exchange");
  const latest = said.at(-1);
  // The newest repliers first, each once.
  const faces = [...new Set([...said].reverse().flatMap((m) => (m.sender_handle ? [m.sender_handle] : [])))].slice(0, FACES);
  const quote = latest ? firstLine(typeof latest.content === "string" ? latest.content : "") : "";
  return (
    <button
      type="button"
      onClick={() => onOpen?.(thread.episode)}
      aria-label={`Open the thread "${thread.title}", ${said.length} ${said.length === 1 ? "reply" : "replies"}`}
      className="-mx-1.5 mt-1 flex h-7 w-[calc(100%+0.75rem)] min-w-0 max-w-2xl items-center gap-2 rounded-md px-1.5 text-left text-label hover:bg-hairline"
    >
      <CornerDownRight className="size-3.5 flex-shrink-0 text-faint" aria-hidden />
      {faces.length > 0 && (
        <span className="flex flex-shrink-0 gap-0.5">
          {faces.map((h) => (
            <Monogram key={h} handle={h} className="size-[18px] text-[8px]" />
          ))}
        </span>
      )}
      <span className="flex-shrink-0 font-medium text-accent">
        {said.length === 0 ? "Thread" : `${said.length} ${said.length === 1 ? "reply" : "replies"}`}
      </span>
      {quote && <span className="min-w-0 flex-1 truncate text-muted-foreground">{quote}</span>}
      {latest?.created_at && (
        <span className="ml-auto flex-shrink-0 text-micro text-faint">
          <Ago at={latest.created_at} />
        </span>
      )}
    </button>
  );
}

const firstLine = (text: string) => text.split("\n").find((l) => l.trim())?.trim() ?? "";
