// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { HighlightText } from "@/components/ui/highlight-text";
import type { Needles } from "@/lib/chat-search";
import { nameOf, useNames } from "@/lib/people";

/**
 * Who said it: the name they gave themselves, with their handle quieter beside
 * it, or the handle alone for anyone without a name (every agent, and people
 * who haven't said). An agent's `tag` (its CLI, or an engine's kind, from
 * `agentTag`) sits beside it as a small neutral label: neutral because the
 * accent is for links and mentions, and in the same face as the name so the
 * line reads as one line rather than as code.
 */
export function SenderName({
  handle,
  highlight,
  tag,
}: {
  handle: string;
  highlight?: { query: Needles; active: boolean };
  tag?: string;
}) {
  const name = nameOf(useNames(), handle);
  return (
    <span className="flex min-w-0 items-baseline gap-1.5">
      <span className="truncate text-label font-semibold text-text">
        <HighlightText text={name ?? handle} highlight={highlight} />
      </span>
      {name && <span className="flex-shrink-0 text-micro text-faint">@{handle.replace(/^@/, "")}</span>}
      {tag && (
        <span className="flex-shrink-0 self-center rounded bg-hairline px-1.5 py-0.5 text-[11px] leading-none text-muted-foreground">
          {tag}
        </span>
      )}
    </span>
  );
}
