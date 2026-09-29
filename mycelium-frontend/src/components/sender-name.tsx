// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { HighlightText } from "@/components/ui/highlight-text";
import { nameOf, useNames } from "@/lib/people";

/**
 * Who said it: the name they gave themselves, with their handle quieter beside
 * it, or the handle alone for anyone without a name (every agent, and people
 * who haven't said).
 */
export function SenderName({
  handle,
  highlight,
}: {
  handle: string;
  highlight?: { query: string; active: boolean };
}) {
  const name = nameOf(useNames(), handle);
  if (!name) {
    return (
      <span className="truncate text-label font-semibold text-text">
        <HighlightText text={handle} highlight={highlight} />
      </span>
    );
  }
  return (
    <span className="flex min-w-0 items-baseline gap-1.5">
      <span className="truncate text-label font-semibold text-text">
        <HighlightText text={name} highlight={highlight} />
      </span>
      <span className="flex-shrink-0 font-mono text-micro text-faint">@{handle.replace(/^@/, "")}</span>
    </span>
  );
}
