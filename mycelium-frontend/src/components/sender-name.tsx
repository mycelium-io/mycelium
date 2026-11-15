// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useSyncExternalStore } from "react";
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
/** MOCK: how a subagent is named in the chat, from `?sub=`. */
type SubagentLook = "chevron" | "handle" | "tag" | "name";
const LOOKS: readonly SubagentLook[] = ["chevron", "handle", "tag", "name"];
const subscribeNever = () => () => {};
function useSubagentLook(): SubagentLook {
  return useSyncExternalStore(
    subscribeNever,
    // The name, then the handle: the one picked (2026-11-14).
    () => LOOKS.find((l) => l === new URLSearchParams(window.location.search).get("sub")) ?? "name",
    () => "name",
  );
}

export function SenderName({
  handle,
  highlight,
  tag,
  subagent,
}: {
  handle: string;
  highlight?: { query: Needles; active: boolean };
  tag?: string;
  /** MOCK: an agent's subagent: `review @builder:review [subagent]`. */
  subagent?: { parent: string; name: string } | null;
}) {
  const name = nameOf(useNames(), handle);
  const look = useSubagentLook();
  if (subagent && look !== "chevron") {
    // MOCK: the other ways to name a subagent, picked by `?sub=`.
    const shown = look === "handle" ? handle.replace(/^@/, "") : subagent.name;
    const chip = look === "tag" ? `${subagent.parent}'s subagent` : "subagent";
    return (
      <span className="flex min-w-0 items-baseline gap-1.5" title={`@${handle}`}>
        <span className="truncate text-label font-semibold text-text">
          <HighlightText text={shown} highlight={highlight} />
        </span>
        {look === "name" && <span className="flex-shrink-0 text-micro text-faint">@{handle.replace(/^@/, "")}</span>}
        <span className="flex-shrink-0 self-center rounded bg-hairline px-1.5 py-0.5 text-[11px] leading-none text-muted-foreground">
          {chip}
        </span>
      </span>
    );
  }
  return (
    <span className="flex min-w-0 items-baseline gap-1.5">
      {subagent ? (
        <span className="flex min-w-0 items-baseline gap-1 truncate text-label" title={`@${handle}`}>
          <span className="font-medium text-muted-foreground">{subagent.parent}</span>
          <span aria-hidden className="text-faint">›</span>
          <span className="truncate font-semibold text-text">
            <HighlightText text={subagent.name} highlight={highlight} />
          </span>
        </span>
      ) : (
      <span className="truncate text-label font-semibold text-text">
        <HighlightText text={name ?? handle} highlight={highlight} />
      </span>
      )}
      {name && <span className="flex-shrink-0 text-micro text-faint">@{handle.replace(/^@/, "")}</span>}
      {tag && (
        <span className="flex-shrink-0 self-center rounded bg-hairline px-1.5 py-0.5 text-[11px] leading-none text-muted-foreground">
          {tag}
        </span>
      )}
    </span>
  );
}
