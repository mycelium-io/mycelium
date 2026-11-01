// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { MessageSquare } from "lucide-react";
import {
  isSuccess,
  leastSatisfied,
  percent,
  type ConductorLine,
  type PickRecord,
  type RunProgress,
} from "@/lib/conductor-line";
import { AGREED_ICON, DONE_ICON, RUN_ICON, SHORT_ICON, TIMEOUT_ICON } from "@/lib/event-icons";
import { SystemNotice } from "@/components/messages/feed-row";

type Close = Extract<ConductorLine, { event: "close" }>;

/** "Concord", for a line's label. */
function protocolName(protocol: string): string {
  return protocol.charAt(0).toUpperCase() + protocol.slice(1);
}

/** The task a run is in, as the channel's other lines name one: by its title,
 *  opening its thread. */
function TaskButton({ title, onOpen }: { title: string; onOpen?: () => void }) {
  return (
    <button
      type="button"
      onClick={onOpen}
      disabled={!onOpen}
      title={title}
      className="inline-flex max-w-full items-center gap-1 truncate rounded px-1 text-accent transition-colors enabled:hover:bg-accent-soft enabled:hover:underline disabled:cursor-default disabled:text-text"
    >
      <MessageSquare className="size-3 shrink-0" strokeWidth={1.9} />
      <span className="truncate">{title}</span>
    </button>
  );
}

/**
 * A conductor run starting in a task's thread, as one line in the channel.
 * While it walks, the line says what the members are doing and how many have
 * answered ("scoring, 2 of 3 in"), so the channel shows the run moving without
 * the thread's prompts. Once it ends, it says who it started with.
 */
export function RunStartLine({
  time,
  at,
  open,
  progress,
  title,
  onOpen,
}: {
  time: string;
  at?: string;
  open: Extract<ConductorLine, { event: "open" }>;
  progress: RunProgress | null;
  title: string;
  onOpen?: () => void;
}) {
  const doing = progress?.open ? progress.doing : null;
  return (
    <SystemNotice
      time={time}
      at={at}
      icon={RUN_ICON}
      label={`${protocolName(open.protocol)} started`}
      labelColor="var(--accent)"
      task={<TaskButton title={title} onOpen={onOpen} />}
    >
      {doing ? (
        <span className="inline-flex min-w-0 items-center gap-1.5 truncate" role="status">
          <span aria-hidden className="size-1.5 flex-shrink-0 rounded-full bg-accent motion-safe:animate-pulse" />
          <span className="truncate">
            {doing.what}, {doing.answered} of {doing.asked} in
          </span>
        </span>
      ) : (
        <span className="truncate">{open.members.join(", ")}</span>
      )}
    </SystemNotice>
  );
}

/**
 * A conductor run ending, as one line in the channel: what it produced. A run
 * that picked (Concord) says what, and who is least satisfied, from the pick's
 * record; one that saved a shared summary (Accord), how many points it holds
 * and how many are open. `null` for a run that did neither.
 */
export function RunDoneLine({
  time,
  at,
  close,
  pick,
  progress,
  title,
  onOpen,
}: {
  time: string;
  at?: string;
  close: Close;
  pick: PickRecord | null;
  progress: RunProgress | null;
  title: string;
  onOpen?: () => void;
}) {
  const name = `${protocolName(close.protocol)} ended`;
  const task = <TaskButton title={title} onOpen={onOpen} />;
  const good = isSuccess(close.outcome);
  if (close.pick) {
    // An agreement everyone clears, or the best found when the fixes ran out.
    const agreed = close.outcome === "converged";
    const least = pick ? leastSatisfied(pick) : null;
    return (
      <SystemNotice
        time={time}
        at={at}
        icon={agreed ? AGREED_ICON : SHORT_ICON}
        label={name}
        labelColor={agreed ? "var(--green)" : "var(--yellow)"}
        strong
        task={task}
      >
        {/* The option's text is the tooltip; the thread has it in full. */}
        <span className="truncate" title={close.text}>
          {agreed ? "picked" : "best found"} {close.pick}
          {least && <span className="text-muted-foreground">, {least.member} least satisfied at {percent(least.placed)}</span>}
        </span>
      </SystemNotice>
    );
  }
  const lock = progress?.lock;
  if (lock && lock.outcome === "locked") {
    const counts = `${lock.points} ${lock.points === 1 ? "point" : "points"}${lock.flagged ? `, ${lock.flagged} open` : ""}`;
    return (
      <SystemNotice
        time={time}
        at={at}
        icon={good ? DONE_ICON : TIMEOUT_ICON}
        label={name}
        labelColor={good ? "var(--green)" : "var(--yellow)"}
        strong
        task={task}
      >
        <span className="truncate">
          summary locked<span className="text-muted-foreground">, {counts}</span>
        </span>
      </SystemNotice>
    );
  }
  return null;
}
