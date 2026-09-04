// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import React from "react";
import { splitOnMatches } from "@/lib/chat-search";

/** The one mark the app draws for a find hit.
 *
 *  Yellow, matching how a marked hit reads everywhere else in the app; the
 *  accent color is reserved for links and mentions. The active occurrence
 *  uses the same hue, filled, so a jump between matches reads as one mark
 *  moving rather than two different marks. */
const MARK = "rounded-[2px] px-px text-text";
const REST = `${MARK} bg-yellow/25`;
const ACTIVE = `${MARK} bg-yellow/60 ring-1 ring-yellow/70`;

export interface Highlight {
  query: string;
  /** True on the occurrence run the find bar has stepped to. */
  active?: boolean;
}

/** Mark every occurrence of `highlight.query` in `text`.
 *
 *  Returns the string untouched when there is nothing to mark, so a message
 *  with no hit renders exactly the nodes it rendered before find was opened. */
export function highlightText(text: string, highlight?: Highlight): React.ReactNode {
  if (!highlight?.query || !text) return text;
  const segments = splitOnMatches(text, highlight.query);
  if (!segments.some(s => s.match)) return text;
  return segments.map((segment, i) =>
    segment.match ? (
      <mark key={i} data-find-match={highlight.active ? "active" : "hit"} className={highlight.active ? ACTIVE : REST}>
        {segment.text}
      </mark>
    ) : (
      <React.Fragment key={i}>{segment.text}</React.Fragment>
    ),
  );
}

/** `highlightText` bound to one query, stable while that query is. */
export function useHighlighter(highlight?: Highlight): (text: string) => React.ReactNode {
  const query = highlight?.query ?? "";
  const active = highlight?.active ?? false;
  return React.useCallback(
    (text: string) => (query ? highlightText(text, { query, active }) : text),
    [query, active],
  );
}

/** The component form, for a plain string in the middle of a layout. */
export function HighlightText({ text, highlight }: { text: string; highlight?: Highlight }) {
  return <>{highlightText(text, highlight)}</>;
}
