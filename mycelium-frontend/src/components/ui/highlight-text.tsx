// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import React from "react";
import { splitOnMatches, type Needles } from "@/lib/chat-search";

/** The one mark the app draws for a find hit.
 *
 *  Yellow, matching how a marked hit reads everywhere else in the app; the
 *  accent color is reserved for links and mentions. The active occurrence
 *  uses the same hue, filled, so a jump between matches reads as one mark
 *  moving rather than two different marks. */
const MARK = "rounded-[2px] px-px text-text";
const REST = `${MARK} bg-yellow/25`;
const ACTIVE = `${MARK} bg-yellow/60 ring-1 ring-yellow/70`;
/** The words the verifier couldn't confirm: underlined, not filled, so they
 *  read as "look here" rather than as a search hit. */
const CLAIM =
  "bg-transparent text-inherit underline decoration-dotted decoration-yellow decoration-[1.5px] underline-offset-[3px]";

export interface Highlight {
  /** The text to mark: one string, or every word and phrase of a query. */
  query: Needles;
  /** True on the occurrence run the find bar has stepped to. */
  active?: boolean;
  /** `claim` underlines words the verifier flagged; the default fills a find hit. */
  variant?: "find" | "claim";
}

/** Mark every occurrence of `highlight.query` in `text`.
 *
 *  Returns the string untouched when there is nothing to mark, so a message
 *  with no hit renders exactly the nodes it rendered before find was opened. */
export function highlightText(text: string, highlight?: Highlight): React.ReactNode {
  if (!highlight?.query || highlight.query.length === 0 || !text) return text;
  const segments = splitOnMatches(text, highlight.query);
  if (!segments.some(s => s.match)) return text;
  const claim = highlight.variant === "claim";
  return segments.map((segment, i) =>
    segment.match ? (
      claim ? (
        <mark key={i} data-claim="" className={CLAIM}>
          {segment.text}
        </mark>
      ) : (
        <mark key={i} data-find-match={highlight.active ? "active" : "hit"} className={highlight.active ? ACTIVE : REST}>
          {segment.text}
        </mark>
      )
    ) : (
      <React.Fragment key={i}>{segment.text}</React.Fragment>
    ),
  );
}

/** `highlightText` bound to one query, stable while that query is. */
export function useHighlighter(highlight?: Highlight): (text: string) => React.ReactNode {
  // Keyed by the needles' text, so a fresh array holding the same words is
  // the same highlighter.
  const raw = highlight?.query ?? "";
  const key = typeof raw === "string" ? raw : raw.join("\n");
  const active = highlight?.active ?? false;
  const variant = highlight?.variant;
  return React.useCallback(
    (text: string) => {
      if (!key) return text;
      const query = key.includes("\n") ? key.split("\n") : key;
      return highlightText(text, { query, active, variant });
    },
    [key, active, variant],
  );
}

/** The component form, for a plain string in the middle of a layout. */
export function HighlightText({ text, highlight }: { text: string; highlight?: Highlight }) {
  return <>{highlightText(text, highlight)}</>;
}
