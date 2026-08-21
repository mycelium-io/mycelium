// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { EditorView } from "@codemirror/view";
import type { Extension } from "@codemirror/state";

// Matches `![[` (transclusion) or `[[` followed by an optional partial key
// consisting only of valid key characters (word chars, slashes, dots, dashes).
// The character-class constraint prevents matching a stale `[[` from earlier
// in the same line that is followed by arbitrary prose.
const WIKILINK_RE = /(!?\[\[[\w/.-]*)$/;

/** An in-flight `[[…` token, located within the text preceding the cursor. */
export interface WikilinkToken {
  /** Offset within the searched text where the sigil starts. */
  offset: number;
  /** Text typed after the sigil — used to filter candidates. */
  query: string;
  /** Which kind of link is being typed. */
  sigil: "[[" | "![[";
}

/**
 * Find an unterminated wikilink at the end of `textBeforeCursor`.
 *
 * Returns `null` when the cursor is not inside one, which includes the case
 * where an earlier `[[` on the line has already been closed.
 */
export function matchWikilinkAt(textBeforeCursor: string): WikilinkToken | null {
  const match = WIKILINK_RE.exec(textBeforeCursor);
  if (!match) return null;

  const raw = match[1];
  const sigil: "[[" | "![[" = raw.startsWith("![[") ? "![[" : "[[";
  return { offset: match.index, query: raw.slice(sigil.length), sigil };
}

/** Narrow a pool of memory keys to those matching a partial wikilink query. */
export function filterWikilinkCandidates(pool: string[], query: string): string[] {
  const needle = query.toLowerCase();
  return pool.filter(k => k.toLowerCase().includes(needle));
}

/** A located wikilink token, positioned for rendering a completion popup. */
export interface WikilinkMatch extends WikilinkToken {
  /** Document position where the sigil starts. */
  from: number;
  /** Current cursor position (end of the token so far). */
  to: number;
  /** Viewport x coordinate (left edge of cursor). */
  x: number;
  /** Viewport y coordinate (bottom of cursor line). */
  y: number;
}

/**
 * CM6 extension that fires `onMatch` whenever the cursor is inside an
 * in-flight `[[…` token and `null` when it leaves one.
 *
 * Pair with a React portal dropdown rather than CodeMirror's own completion
 * tooltip, which does not render reliably inside the editor's ancestors.
 */
export function wikilinkDetector(
  onMatch: (match: WikilinkMatch | null) => void,
): Extension {
  return EditorView.updateListener.of((update) => {
    if (!update.selectionSet && !update.docChanged) return;

    const { state, view } = update;
    const cursor = state.selection.main.head;
    const line = state.doc.lineAt(cursor);

    const token = matchWikilinkAt(line.text.slice(0, cursor - line.from));
    if (!token) { onMatch(null); return; }

    const coords = view.coordsAtPos(cursor);
    if (!coords) { onMatch(null); return; }

    onMatch({
      ...token,
      from: line.from + token.offset,
      to: cursor,
      x: coords.left,
      y: coords.bottom,
    });
  });
}
