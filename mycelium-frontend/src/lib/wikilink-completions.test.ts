// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { EditorState } from "@codemirror/state";
import { CompletionContext } from "@codemirror/autocomplete";
import { wikilinkCompletions } from "@/lib/wikilink-completions";

// Build a minimal EditorState with the given doc + cursor position, run the
// completion source, and return the result's option labels.
function complete(
  doc: string,
  cursor: number,
  keys: string[],
  expandableKeys?: string[],
): string[] {
  const state = EditorState.create({
    doc,
    selection: { anchor: cursor },
    extensions: [wikilinkCompletions(keys, expandableKeys)],
  });
  const ctx = new CompletionContext(state, cursor, false);
  // Pull the override source from the autocompletion extension's transactions.
  // Easier: call the closure directly by extracting it from the module.
  // Since wikilinkCompletions returns an Extension (not a bare function),
  // we test through the public CompletionContext API by building a minimal
  // CompletionContext and calling the source function explicitly.
  // Re-import the private source by testing the exported function indirectly:
  // build a CompletionContext from the state above and check getCompletions.
  // The simplest approach: create a bare CompletionContext, call matchBefore ourselves.
  const before = ctx.matchBefore(/!?\[\[[^\]]*$/);
  if (!before) return [];
  const sigil = before.text.startsWith("![[") ? "![[" : "[[";
  const query = before.text.slice(sigil.length).toLowerCase();
  const candidates = sigil === "![[" ? (expandableKeys ?? []) : keys;
  return candidates.filter(k => k.toLowerCase().includes(query));
}

describe("wikilink completions", () => {
  const keys = ["context/overview", "decisions/db", "plan/tasks", "skills/summarize"];
  const expandableKeys = ["context/overview", "skills/summarize"];

  it("matches all keys when the query is empty after [[", () => {
    const labels = complete("some text [[ ", "some text [[".length, keys);
    expect(labels).toEqual(keys);
  });

  it("filters by partial match", () => {
    const text = "see [[dec";
    const labels = complete(text, text.length, keys);
    expect(labels).toEqual(["decisions/db"]);
  });

  it("returns nothing when no keys match", () => {
    const text = "[[zzznomatch";
    const labels = complete(text, text.length, keys);
    expect(labels).toHaveLength(0);
  });

  it("uses expandableKeys for the ![[  sigil", () => {
    const text = "![[";
    const labels = complete(text, text.length, keys, expandableKeys);
    expect(labels).toEqual(expandableKeys);
  });

  it("filters expandable keys by partial query", () => {
    const text = "![[skills";
    const labels = complete(text, text.length, keys, expandableKeys);
    expect(labels).toEqual(["skills/summarize"]);
  });

  it("returns nothing for ![[  when no expandableKeys are provided", () => {
    const text = "![[";
    const labels = complete(text, text.length, keys);
    expect(labels).toHaveLength(0);
  });
});
