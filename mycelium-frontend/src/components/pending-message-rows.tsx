// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { MessageBody } from "@/components/message-body";
import { SenderName } from "@/components/sender-name";
import { Monogram } from "@/components/ui/monogram";
import { forget, retryPending, type PendingMessage } from "@/lib/pending-messages";
import { cn } from "@/lib/utils";

interface Props {
  roomName: string;
  pending: readonly PendingMessage[];
  /** Who wrote the last message drawn above, so a run of yours stays one group. */
  previousSender?: string | null;
  onOpenMemory?: (key: string) => void;
}

/**
 * Your messages the room has not shown back yet, drawn the way a message is,
 * under everything read so far: faded while sending, and, when the hub refused
 * one, why, with its text kept and a way to send it again.
 */
export function PendingMessageRows({ roomName, pending, previousSender = null, onOpenMemory }: Props) {
  return (
    <>
      {pending.map((entry, i) => {
        const above = i > 0 ? pending[i - 1].sender : previousSender;
        const grouped = above === entry.sender;
        const failed = entry.state === "failed";
        return (
          <div
            key={entry.id}
            data-testid="pending-message"
            data-state={entry.state}
            className={cn("flex gap-3 px-5", grouped ? "py-0.5" : "mt-3 pt-1 first:mt-0")}
          >
            <div className="w-6 flex-shrink-0">
              {!grouped && <Monogram handle={entry.sender} color="var(--avatar-neutral)" className="size-6 text-[10px]" />}
            </div>
            <div className="min-w-0 flex-1">
              {!grouped && (
                <div className="flex items-center gap-1.5">
                  <SenderName handle={entry.sender} />
                </div>
              )}
              <div className={cn(entry.state === "sending" && "opacity-60", failed && "opacity-70")}>
                <MessageBody content={entry.content} onOpenMemory={onOpenMemory} roomName={roomName} />
              </div>
              {entry.state === "sending" && <p className="text-micro text-faint">Sending…</p>}
              {failed && (
                <p role="alert" className="flex flex-wrap items-center gap-x-2 text-micro text-red">
                  <span className="min-w-0">Couldn&apos;t send{entry.error ? `: ${entry.error}` : "."}</span>
                  <button
                    type="button"
                    onClick={() => void retryPending(entry.id)}
                    className="font-medium underline-offset-2 hover:underline"
                  >
                    Retry
                  </button>
                  <button
                    type="button"
                    onClick={() => forget(entry.id)}
                    className="text-muted-foreground underline-offset-2 hover:underline"
                  >
                    Discard
                  </button>
                </p>
              )}
            </div>
          </div>
        );
      })}
    </>
  );
}
