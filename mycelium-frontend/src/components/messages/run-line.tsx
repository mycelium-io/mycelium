// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { MessageSquare } from "lucide-react";
import type { ConductorLine, RunProgress } from "@/lib/conductor-line";
import { RUN_ICON } from "@/lib/event-icons";
import { SystemNotice } from "@/components/messages/feed-row";

/** "Review", for a line's label. */
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
 * While it walks, the line names the step being asked and how many have
 * answered ("review, 2 of 3 in"), so the channel shows the run moving without
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
