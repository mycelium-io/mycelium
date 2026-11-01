// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { forwardRef, type ReactNode } from "react";
import type { ComposerMention } from "@/lib/composer-mentions";
import { cn } from "@/lib/utils";

/** How a mention reads while it's typed, as one does once it's sent: a member
 *  asked (`@`, `@!`) in the accent, a member named silently (`@~`) a quieter
 *  accent, and an `@word` that reaches nobody dull. Color only: a heavier
 *  weight would widen the text and pull it off the caret. */
function tone(m: ComposerMention): string {
  if (!m.resolved) return "text-muted-foreground";
  return m.kind === "silent" ? "text-accent/70" : "text-accent";
}

/**
 * The composer's text drawn again behind its textarea, with its mentions
 * colored: a textarea can't color part of its own text, so it draws its text
 * transparent over this one. `className` has to set the textarea's font,
 * padding and wrapping exactly, and the caller keeps `scrollTop` in step.
 * `scrolls` says the textarea shows a scrollbar, which narrows its text: the
 * layer takes one too (hidden under the textarea's) so the lines wrap alike.
 */
export const MentionLayer = forwardRef<
  HTMLDivElement,
  { text: string; mentions: ComposerMention[]; className: string; scrolls: boolean }
>(
  function MentionLayer({ text, mentions, className, scrolls }, ref) {
    const parts: ReactNode[] = [];
    let at = 0;
    for (const m of mentions) {
      if (m.start > at) parts.push(text.slice(at, m.start));
      parts.push(
        <span key={m.start} className={tone(m)}>
          {text.slice(m.start, m.end)}
        </span>,
      );
      at = m.end;
    }
    parts.push(text.slice(at));
    return (
      <div
        ref={ref}
        aria-hidden
        style={{ overflowY: scrolls ? "scroll" : "hidden" }}
        className={cn(
          "pointer-events-none absolute inset-0 overflow-x-hidden whitespace-pre-wrap [overflow-wrap:break-word]",
          className,
        )}
      >
        {parts}
        {/* A trailing newline only takes up its line when something follows it. */}
        {"​"}
      </div>
    );
  },
);
