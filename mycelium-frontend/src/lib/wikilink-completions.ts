// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { autocompletion, type CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import type { Extension } from "@codemirror/state";

/**
 * CodeMirror 6 `CompletionSource` for `[[key]]` wikilinks.
 *
 * Feed it the room's memory keys and it will offer completions any time the
 * cursor is inside an in-flight `[[…` token, inserting `[[key]]` when chosen.
 * Pass `expandableKeys` to also complete `![[key]]` — limited to memories
 * whose `expandable: true` frontmatter flag allows transclusion.
 */
export function wikilinkSource(
  keys: string[],
  expandableKeys?: string[],
): (ctx: CompletionContext) => CompletionResult | null {
  return (ctx: CompletionContext): CompletionResult | null => {
    // Match `![[` (transclusion) or `[[` (link), then optional partial key.
    const before = ctx.matchBefore(/!?\[\[[^\]]*$/);
    if (!before || (before.from === before.to && !ctx.explicit)) return null;

    const sigil = before.text.startsWith("![[") ? "![[" : "[[";
    const sigilLen = sigil.length;
    const query = before.text.slice(sigilLen).toLowerCase();

    const candidates = sigil === "![[" ? (expandableKeys ?? []) : keys;
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
 * CodeMirror 6 `Extension` that autocompletes `[[key]]` wikilinks (and
 * optionally `![[key]]` transclusions) in a markdown editor.
 *
 * Pass all room memory keys as `keys` and the subset whose `expandable`
 * frontmatter flag is true as `expandableKeys`.
 */
export function wikilinkCompletions(
  keys: string[],
  expandableKeys?: string[],
): Extension {
  return autocompletion({ override: [wikilinkSource(keys, expandableKeys)] });
}
