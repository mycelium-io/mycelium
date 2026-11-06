// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Under a message the reader just sent: where each member it mentioned stands.
 *
 * A plain `@` reaches a working member only when its turn ends, so a message
 * that changes what it's doing can arrive after it has done it. While that
 * mention is still held, the sender can turn it into an interrupt, once, and
 * the member stops, reads it, and carries on. The message's text never changes.
 * Once the member has read it, or the sender has interrupted, the row says so
 * quietly and offers nothing.
 *
 * Only the reader's own recent messages ask, and only while something is held.
 */

import { useState } from "react";
import { CheckCheck, Loader2, Zap } from "lucide-react";
import { interruptMention, type MentionWake } from "@/lib/api";
import { useMentionWakes } from "@/lib/room-data";
import { Ago } from "@/lib/relative-time";

/** How long after sending a message its mentions are shown under it. */
export const MENTION_WAKES_FOR_MS = 30 * 60_000;

export function MentionWakes({ roomName, messageId, me }: { roomName: string; messageId: string; me: string }) {
  const { wakes, refresh } = useMentionWakes(roomName, messageId);
  if (wakes.length === 0) return null;
  return (
    <div className="mt-1 space-y-0.5">
      {wakes.map((w) => (
        <WakeRow key={w.handle} wake={w} roomName={roomName} messageId={messageId} me={me} onDone={() => void refresh()} />
      ))}
    </div>
  );
}

function WakeRow({
  wake,
  roomName,
  messageId,
  me,
  onDone,
}: {
  wake: MentionWake;
  roomName: string;
  messageId: string;
  me: string;
  onDone: () => void;
}) {
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const interrupt = async () => {
    setSending(true);
    setError(null);
    try {
      await interruptMention(roomName, messageId, wake.handle, me);
      onDone();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't interrupt");
    } finally {
      setSending(false);
    }
  };

  if (wake.wake === "held" && wake.status === "working") {
    return (
      <div className="flex h-6 items-center gap-2 text-micro">
        <span className="relative flex size-3.5 flex-shrink-0 items-center justify-center" aria-hidden>
          <span className="absolute size-2 rounded-full bg-yellow/40 motion-safe:animate-ping" />
          <span className="size-1.5 rounded-full bg-yellow" />
        </span>
        <span className="min-w-0 truncate text-muted-foreground">
          <span className="font-medium text-text">{wake.handle}</span> reads this when its turn ends
        </span>
        <button
          type="button"
          onClick={() => void interrupt()}
          disabled={sending}
          aria-label={`Interrupt ${wake.handle} so it reads this now`}
          title={`${wake.handle} stops, reads this, then carries on. Once, and the message stays as it is.`}
          className="flex flex-shrink-0 items-center gap-1 rounded px-1.5 py-0.5 font-medium text-accent hover:bg-hairline"
        >
          {sending ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Zap className="size-3" aria-hidden />}
          Interrupt
        </button>
        {error && <span className="truncate text-red">{error}</span>}
      </div>
    );
  }
  if (wake.wake === "interrupted") {
    return (
      <div className="flex h-6 items-center gap-2 text-micro text-faint">
        <Zap className="size-3.5 flex-shrink-0 text-accent" aria-hidden />
        <span className="min-w-0 truncate">
          Interrupted <span className="text-muted-foreground">{wake.handle}</span>
        </span>
        {wake.at && <Ago at={wake.at} />}
      </div>
    );
  }
  // Read, or held for a member that isn't working (it reads it next): nothing to do.
  return (
    <div className="flex h-6 items-center gap-2 text-micro text-faint">
      <CheckCheck className="size-3.5 flex-shrink-0" aria-hidden />
      <span className="min-w-0 truncate">
        <span className="text-muted-foreground">{wake.handle}</span> {wake.wake === "read" ? "read it" : "reads it next"}
      </span>
      {wake.wake === "read" && wake.at && <Ago at={wake.at} />}
    </div>
  );
}
