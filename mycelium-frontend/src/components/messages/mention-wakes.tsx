// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Turning a sent `@` into an interrupt.
 *
 * A plain `@` reaches a working member only when its turn ends, so a message
 * that changes what it's doing can arrive after it has done it. The composer's
 * `@` list already marks a working member and offers `@!`, so most of the time
 * that's decided before sending. When a plain `@` went to one anyway, the
 * composer says so once, for a few seconds, with an Interrupt button. Nothing
 * stays under the message, and the room gets no line: an interrupt shows as a
 * ⚡ beside the message's time.
 */

import { useState } from "react";
import { Loader2, Zap } from "lucide-react";
import { interruptMention } from "@/lib/api";
import { WorkingDot } from "@/components/composer-hints";

/** How long the line after sending stays, unless the pointer is on it. */
export const SENT_TO_WORKING_MS = 8_000;

/** Who a message's sender interrupted with it, and when. */
export interface Interrupted {
  by: string;
  handle: string;
  at: string;
}

/** The live frame the hub sends when a sender interrupts someone with a
 *  message already sent (`interrupts._announce`); it draws no row. */
export const INTERRUPTED_FRAME = "message_interrupted";

/** The line over the composer after a plain `@` went to a working member. */
export function SentToWorking({
  roomName,
  messageId,
  handles,
  me,
  onDone,
}: {
  roomName: string;
  messageId: string;
  handles: string[];
  me: string;
  onDone: () => void;
}) {
  const [sending, setSending] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const names = handles.map((h) => `@${h}`).join(", ");
  const interrupt = async () => {
    setSending(true);
    setError(null);
    try {
      for (const h of handles) await interruptMention(roomName, messageId, h, me);
      setDone(true);
      setTimeout(onDone, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't interrupt");
    } finally {
      setSending(false);
    }
  };
  if (done) {
    return (
      <span className="inline-flex items-center gap-1.5">
        <Zap className="size-3 text-accent" aria-hidden />
        Interrupted {names}.
      </span>
    );
  }
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <WorkingDot />
      <span className="truncate">
        <span className="text-text">{names}</span> {handles.length > 1 ? "are" : "is"} working, so it sees this when its turn ends.
      </span>
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => void interrupt()}
        disabled={sending}
        title="It stops, reads this, then carries on. The message stays as it is."
        className="inline-flex flex-shrink-0 items-center gap-1 font-medium text-accent hover:underline"
      >
        {sending ? <Loader2 className="size-3 animate-spin" aria-hidden /> : <Zap className="size-3" aria-hidden />}
        Interrupt
      </button>
      {error && <span className="truncate text-red">{error}</span>}
    </span>
  );
}

/** A ⚡ beside a message's time when its sender interrupted someone with it. */
export function InterruptMark({ marks }: { marks: readonly Interrupted[] | undefined }) {
  if (!marks?.length) return null;
  const who = marks.map((m) => `@${m.handle}`).join(", ");
  return (
    <span
      role="img"
      aria-label={`@${marks[0].by} interrupted ${who} with this`}
      title={`@${marks[0].by} interrupted ${who} with this`}
      className="inline-flex flex-shrink-0 items-center text-accent"
    >
      <Zap className="size-3" aria-hidden />
    </span>
  );
}
