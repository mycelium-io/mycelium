// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useMemo } from "react";
import { CircleCheck, CircleX } from "lucide-react";
import { useThreadMessages } from "@/lib/room-data";
import { conductorLineOf, isSuccess, type ConductorLine } from "@/lib/conductor-line";

type Close = Extract<ConductorLine, { event: "close" }>;

/** The close of the last run in a thread, or `null` while a run is going or
 *  when none ran here. */
export function closedRun(lines: ConductorLine[]): Close | null {
  let close: Close | null = null;
  for (const line of lines) {
    if (line.event === "open") close = null;
    else if (line.event === "close") close = line;
  }
  return close;
}

/**
 * How a conductor run ended, at the top of its thread once it closes, so the
 * thread opens on the outcome rather than on the prompts that led to it.
 */
export function RunResult({ roomName, episode }: { roomName: string; episode: string }) {
  const { messages } = useThreadMessages(roomName, episode);
  const close = useMemo(
    () =>
      closedRun(
        [...messages]
          .reverse()
          .map((m) => conductorLineOf(m))
          .filter((l): l is ConductorLine => l !== null),
      ),
    [messages],
  );
  if (!close) return null;
  const good = isSuccess(close.outcome);
  const Icon = good ? CircleCheck : CircleX;

  return (
    <section aria-label="Result" className="border-b border-border px-4 py-3">
      <div className="flex items-start gap-2">
        <Icon
          className="mt-0.5 size-4 flex-shrink-0"
          style={{ color: good ? "var(--green)" : "var(--yellow)" }}
          aria-label={good ? "succeeded" : "ended short"}
        />
        <h3 className="min-w-0 flex-1 text-label font-medium text-muted-foreground">
          {close.protocol} {good ? "done" : close.outcome}
        </h3>
      </div>
    </section>
  );
}
