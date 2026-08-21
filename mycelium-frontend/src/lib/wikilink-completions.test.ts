// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { EditorState } from "@codemirror/state";
import { CompletionContext } from "@codemirror/autocomplete";
import { wikilinkSource, wikilinkCompletions } from "@/lib/wikilink-completions";

function makeCtx(doc: string, cursor: number, keys: string[], expandableKeys?: string[]) {
  const state = EditorState.create({
    doc,
    selection: { anchor: cursor },
    extensions: [wikilinkCompletions(() => keys, expandableKeys ? () => expandableKeys : undefined)],
  });
  return {
    ctx: new CompletionContext(state, cursor, false),
    source: wikilinkSource(() => keys, expandableKeys ? () => expandableKeys : undefined),
  };
}

function complete(doc: string, cursor: number, keys: string[], expandableKeys?: string[]): string[] {
  const { ctx, source } = makeCtx(doc, cursor, keys, expandableKeys);
  const result = source(ctx);
  return result?.options.map(o => o.label) ?? [];
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

  it("sets from to the start of the [[ sigil so the apply string replaces it, not appends to it", () => {
    // Regression: `from` was previously set to `before.from + sigilLen`,
    // causing the [[key]] apply text to be inserted *after* the already-typed
    // [[ rather than replacing it, producing [[[[key]].
    const text = "text [[dec";
    const cursor = text.length;
    const { ctx, source } = makeCtx(text, cursor, keys);
    const result = source(ctx);
    expect(result).not.toBeNull();
    // `from` should be at the position of the first `[`, not after `[[`.
    expect(result!.from).toBe(text.indexOf("[["));
    // The apply string already contains the sigil.
    expect(result!.options[0].apply).toBe("[[decisions/db]]");
  });

  it("reads keys from getter so late-arriving keys are seen", () => {
    // Simulates the SWR async-load scenario: the getter returns an updated
    // array after the source closure was already created.
    const liveKeys = ["context/overview"];
    const getKeys = () => liveKeys;
    const source = wikilinkSource(getKeys);
    const state = EditorState.create({ doc: "[[con", selection: { anchor: 5 } });
    const ctx = new CompletionContext(state, 5, false);

    const before = source(ctx);
    expect(before?.options.map(o => o.label)).toEqual(["context/overview"]);

    // Simulate SWR updating the keys array.
    liveKeys.push("context/deep-dive");
    const after = source(ctx);
    expect(after?.options.map(o => o.label)).toEqual(["context/overview", "context/deep-dive"]);
  });
});
