// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { autocompletion, type CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import { EditorView } from "@codemirror/view";
import type { Extension } from "@codemirror/state";

// ---------------------------------------------------------------------------
// Wikilink pattern
// ---------------------------------------------------------------------------

// Matches `![[` (transclusion) or `[[` followed by an optional partial key
// consisting only of valid key characters (word chars, slashes, dots, dashes).
// The character-class constraint prevents matching a stale `[[` from earlier
// in the same line that is followed by arbitrary prose.
const WIKILINK_RE = /(!?\[\[[\w/.-]*)$/;

// ---------------------------------------------------------------------------
// Pure CM6 completion source — used by unit tests and wikilinkCompletions().
// ---------------------------------------------------------------------------

/**
 * CodeMirror 6 `CompletionSource` for `[[key]]` wikilinks.
 *
 * Accepts getter functions so the source always reads the current key list
 * even when the extension was mounted before the keys were available (e.g.
 * inside an editor whose host loads keys asynchronously via SWR).
 */
export function wikilinkSource(
  getKeys: () => string[],
  getExpandableKeys?: () => string[],
): (ctx: CompletionContext) => CompletionResult | null {
  return (ctx: CompletionContext): CompletionResult | null => {
    const before = ctx.matchBefore(WIKILINK_RE);
    if (!before || (before.from === before.to && !ctx.explicit)) return null;

    const sigil = before.text.startsWith("![[") ? "![[" : "[[";
    const query = before.text.slice(sigil.length).toLowerCase();

    const keys = getKeys();
    const expandableKeys = getExpandableKeys?.() ?? [];
    const candidates = sigil === "![[" ? expandableKeys : keys;
    const options = candidates
      .filter(k => k.toLowerCase().includes(query))
      .map(k => ({
        label: k,
        apply: `${sigil}${k}]]`,
        detail: sigil === "![[" ? "transclusion" : "wikilink",
        type: "variable" as const,
      }));

    if (options.length === 0) return null;
    // `from` must point at the start of the sigil so the full `[[query`
    // token is replaced by the `[[key]]` apply string, not appended to it.
    return { from: before.from, options };
  };
}

/**
 * CM6 `Extension` that autocompletes `[[key]]` wikilinks (and optionally
 * `![[key]]` transclusions) in a markdown editor.
 *
 * Pass getter functions rather than plain arrays so the extension can be
 * created once at editor mount time and still see the latest key list on
 * every completion invocation (useful when keys load asynchronously via SWR).
 */
export function wikilinkCompletions(
  getKeys: () => string[],
  getExpandableKeys?: () => string[],
): Extension {
  return autocompletion({ override: [wikilinkSource(getKeys, getExpandableKeys)] });
}

// ---------------------------------------------------------------------------
// React-portal approach — used by MemoryEditor in production.
// ---------------------------------------------------------------------------

/** Describes a wikilink token that is currently being typed. */
export interface WikilinkMatch {
  /** Document position where the `[[` sigil starts. */
  from: number;
  /** Current cursor position (end of the token so far). */
  to: number;
  /** Text typed after the sigil — used to filter candidates. */
  query: string;
  /** Which kind of link is being typed. */
  sigil: "[[" | "![[";
  /** Viewport x coordinate (left edge of cursor). */
  x: number;
  /** Viewport y coordinate (bottom of cursor line). */
  y: number;
}

/**
 * CM6 extension that fires `onMatch` whenever the cursor is inside an
 * in-flight `[[…` token and `null` when it leaves one.
 *
 * Pair with a React portal dropdown for a tooltip-free autocomplete that
 * works regardless of overflow/transform/stacking-context ancestors.
 */
export function wikilinkDetector(
  onMatch: (match: WikilinkMatch | null) => void,
): Extension {
  return EditorView.updateListener.of((update) => {
    if (!update.selectionSet && !update.docChanged) return;

    const { state, view } = update;
    const cursor = state.selection.main.head;
    const line = state.doc.lineAt(cursor);
    const beforeCursor = line.text.slice(0, cursor - line.from);

    const match = WIKILINK_RE.exec(beforeCursor);
    if (!match) { onMatch(null); return; }

    const raw = match[1];
    const sigil: "[[" | "![[" = raw.startsWith("![[") ? "![[" : "[[";
    const query = raw.slice(sigil.length);
    const coords = view.coordsAtPos(cursor);
    if (!coords) { onMatch(null); return; }

    onMatch({
      from: line.from + match.index,
      to: cursor,
      query,
      sigil,
      x: coords.left,
      y: coords.bottom,
    });
  });
}
