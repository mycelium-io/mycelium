// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { EditorSelection, EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { afterEach, describe, expect, it } from "vitest";
import {
  codeBlock,
  cycleHeading,
  draftLinks,
  insertBlock,
  textStats,
  toggleLinePrefix,
  toggleWrap,
} from "@/lib/markdown-format";

const views: EditorView[] = [];
afterEach(() => views.splice(0).forEach((v) => v.destroy()));

/** An editor holding `doc`, with the selection from `from` to `to`. */
function editor(doc: string, from = 0, to = from) {
  const view = new EditorView({
    state: EditorState.create({ doc, selection: EditorSelection.single(from, to) }),
    parent: document.body,
  });
  views.push(view);
  return view;
}

const text = (v: EditorView) => v.state.doc.toString();
const selected = (v: EditorView) => v.state.sliceDoc(v.state.selection.main.from, v.state.selection.main.to);

describe("toggleWrap", () => {
  it("wraps the selection, and unwraps it on a second run", () => {
    const v = editor("make this bold", 5, 9);
    toggleWrap(v, "**", "**", "bold");
    expect(text(v)).toBe("make **this** bold");
    expect(selected(v)).toBe("this");
    toggleWrap(v, "**", "**", "bold");
    expect(text(v)).toBe("make this bold");
    expect(selected(v)).toBe("this");
  });

  it("unwraps a selection that includes its markers", () => {
    const v = editor("a `code` b", 2, 8);
    toggleWrap(v, "`", "`", "code");
    expect(text(v)).toBe("a code b");
  });

  it("selects a placeholder when nothing was selected", () => {
    const v = editor("", 0);
    toggleWrap(v, "_", "_", "italic");
    expect(text(v)).toBe("_italic_");
    expect(selected(v)).toBe("italic");
  });
});

describe("toggleLinePrefix", () => {
  it("lists every selected line, and takes the markers off again", () => {
    const v = editor("one\ntwo\nthree", 0, 13);
    toggleLinePrefix(v, "bullet");
    expect(text(v)).toBe("- one\n- two\n- three");
    v.dispatch({ selection: { anchor: 0, head: v.state.doc.length } });
    toggleLinePrefix(v, "bullet");
    expect(text(v)).toBe("one\ntwo\nthree");
  });

  it("numbers lines from 1 and swaps one kind of list for another", () => {
    const v = editor("- one\n- two", 0, 11);
    toggleLinePrefix(v, "number");
    expect(text(v)).toBe("1. one\n2. two");
    v.dispatch({ selection: { anchor: 0, head: v.state.doc.length } });
    toggleLinePrefix(v, "task");
    expect(text(v)).toBe("- [ ] one\n- [ ] two");
  });

  it("doesn't read a checklist as a bulleted list", () => {
    const v = editor("- [ ] todo", 0);
    toggleLinePrefix(v, "bullet");
    expect(text(v)).toBe("- todo");
  });
});

describe("cycleHeading", () => {
  it("steps through H2, H3, H1 and back to text", () => {
    const v = editor("Title", 2);
    const seen = [];
    for (let i = 0; i < 4; i += 1) {
      cycleHeading(v);
      seen.push(text(v));
    }
    expect(seen).toEqual(["## Title", "### Title", "# Title", "Title"]);
  });
});

describe("blocks", () => {
  it("puts a block on lines of its own", () => {
    const v = editor("above", 5);
    insertBlock(v, "---");
    expect(text(v)).toBe("above\n\n---\n");
  });

  it("fences the selection as code", () => {
    const v = editor("x = 1", 0, 5);
    codeBlock(v);
    expect(text(v)).toBe("```\nx = 1\n```\n");
    expect(selected(v)).toBe("x = 1");
  });
});

describe("draftLinks", () => {
  it("finds links and embeds once each, and which keys exist", () => {
    const links = draftLinks("[[a/b]] then ![[c]] and [[a/b]] and [[a/b#part]] [[missing]]", new Set(["a/b", "c"]));
    expect(links).toEqual([
      { key: "a/b", embed: false, exists: true },
      { key: "c", embed: true, exists: true },
      { key: "missing", embed: false, exists: false },
    ]);
  });
});

describe("textStats", () => {
  it("counts words and never reads less than a minute", () => {
    expect(textStats("")).toEqual({ words: 0, chars: 0, minutes: 1 });
    expect(textStats("two  words\n").words).toBe(2);
  });
});
