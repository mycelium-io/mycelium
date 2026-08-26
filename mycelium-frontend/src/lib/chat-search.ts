// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** Find-in-channel: what counts as a hit, decided once.
 *
 *  Two surfaces read this — the marks drawn inside a message, and the ticks
 *  drawn in the scroll gutter beside it — so the gutter can never claim a hit
 *  the text doesn't show, and a tick always lands on something a reader can
 *  see when they jump to it.
 *
 *  The query is matched as literal text, folded for case. A reader who types
 *  `(` into a find bar means a parenthesis, not a group, so nothing here
 *  compiles a regex out of what they typed. */

/** A run of text, marked or not. Concatenating `text` reproduces the input. */
export interface Segment {
  text: string;
  match: boolean;
}

/** Split `text` into alternating plain/matched runs.
 *
 *  An empty or whitespace-only query matches nothing: a find bar is open long
 *  before it has a query in it, and lighting up every character in the room the
 *  moment it opens is not a search result. */
export function splitOnMatches(text: string, query: string): Segment[] {
  const needle = query.toLowerCase();
  if (!needle.trim() || !text) return text ? [{ text, match: false }] : [];

  const hay = text.toLowerCase();
  const segments: Segment[] = [];
  let cursor = 0;
  for (;;) {
    const at = hay.indexOf(needle, cursor);
    if (at === -1) break;
    if (at > cursor) segments.push({ text: text.slice(cursor, at), match: false });
    segments.push({ text: text.slice(at, at + needle.length), match: true });
    cursor = at + needle.length;
  }
  if (segments.length === 0) return [{ text, match: false }];
  if (cursor < text.length) segments.push({ text: text.slice(cursor), match: false });
  return segments;
}

/** How many times the query occurs in the text. */
export function countMatches(text: string, query: string): number {
  return splitOnMatches(text, query).reduce((n, s) => n + (s.match ? 1 : 0), 0);
}

/** Whether the text carries the query at all — the cheap half of the split. */
export function hasMatch(text: string, query: string): boolean {
  const needle = query.toLowerCase();
  if (!needle.trim() || !text) return false;
  return text.toLowerCase().includes(needle);
}

/** Step through matches with wrap-around, the way a find bar does: past the
 *  last one is the first, and before the first one is the last. */
export function stepIndex(current: number, total: number, delta: number): number {
  if (total <= 0) return 0;
  return (((current + delta) % total) + total) % total;
}
