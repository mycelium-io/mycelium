// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { autocompletion, type CompletionContext, type CompletionResult } from "@codemirror/autocomplete";
import type { Extension } from "@codemirror/state";

type KeysArg = string[] | (() => string[]);
const resolve = (arg: KeysArg): string[] => (typeof arg === "function" ? arg() : arg);

/**
 * CodeMirror 6 `CompletionSource` for `[[key]]` wikilinks.
 *
 * `keys` and `expandableKeys` may be plain arrays or getter functions.
 * Pass a getter (e.g. `() => keysRef.current`) so the completion source
 * always reads the latest list even after the EditorState was created —
 * this avoids the "empty completions on first open" problem that occurs
 * when the keys arrive asynchronously after editor mount.
 */
export function wikilinkSource(
  keys: KeysArg,
  expandableKeys?: KeysArg,
): (ctx: CompletionContext) => CompletionResult | null {
  return (ctx: CompletionContext): CompletionResult | null => {
    // Match `![[` (transclusion) or `[[` (link), then optional partial key.
    const before = ctx.matchBefore(/!?\[\[[^\]]*$/);
    if (!before || (before.from === before.to && !ctx.explicit)) return null;

    const sigil = before.text.startsWith("![[") ? "![[" : "[[";
    const sigilLen = sigil.length;
    const query = before.text.slice(sigilLen).toLowerCase();

    const candidates = sigil === "![[" ? resolve(expandableKeys ?? []) : resolve(keys);
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
 * `keys` / `expandableKeys` accept either a plain array or a getter function.
 * Use a getter (`() => ref.current`) when the list is fetched asynchronously
 * after editor mount so the extension is created once but always reads the
 * latest keys at completion time.
 */
export function wikilinkCompletions(
  keys: KeysArg,
  expandableKeys?: KeysArg,
): Extension {
  return autocompletion({ override: [wikilinkSource(keys, expandableKeys)] });
}
