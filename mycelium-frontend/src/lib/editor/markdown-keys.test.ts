// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it } from "vitest";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { javascript } from "@codemirror/lang-javascript";
import { ensureSyntaxTree, indentUnit, LanguageDescription } from "@codemirror/language";
import { EditorSelection, EditorState } from "@codemirror/state";
import { EditorView, keymap, runScopeHandlers } from "@codemirror/view";
import { insertLink, markdownKeys } from "@/lib/editor/markdown-keys";

let view: EditorView | null = null;
afterEach(() => {
  view?.destroy();
  view = null;
});

/** TypeScript for fenced code, loaded up front (the app loads it when a fence names it). */
const codeLanguages = [LanguageDescription.of({ name: "TypeScript", alias: ["ts"], support: javascript({ typescript: true }) })];

/** An editor set up as the memory editor is; `|` marks the cursor, `«`…`»` a selection. */
function editor(doc: string) {
  const cursor = doc.indexOf("|");
  const selFrom = doc.indexOf("«");
  const text = doc.replace("|", "").replace("«", "").replace("»", "");
  const selection =
    selFrom >= 0 ? EditorSelection.single(selFrom, doc.indexOf("»") - 1) : EditorSelection.cursor(cursor >= 0 ? cursor : text.length);
  const md = markdown({ base: markdownLanguage, codeLanguages, addKeymap: false });
  const state = EditorState.create({
    doc: text,
    selection,
    extensions: [markdownKeys(md.language), history(), keymap.of([...defaultKeymap, ...historyKeymap]), md, indentUnit.of("  ")],
  });
  ensureSyntaxTree(state, text.length, 5000);
  view = new EditorView({ state, parent: document.body });
  return view;
}

/** The document, with `|` where the cursor is. */
function text(v: EditorView) {
  const doc = v.state.doc.toString();
  const { head } = v.state.selection.main;
  return `${doc.slice(0, head)}|${doc.slice(head)}`;
}

/** Press a key. jsdom isn't a Mac, so CodeMirror's Mod is Ctrl here. */
function press(v: EditorView, key: string, mods: { shift?: boolean; mod?: boolean } = {}) {
  const event = new KeyboardEvent("keydown", { key, shiftKey: !!mods.shift, ctrlKey: !!mods.mod });
  return runScopeHandlers(v, event, "editor");
}

/** Type one character the way the browser hands it to CodeMirror. */
function type(v: EditorView, ch: string) {
  const { from, to } = v.state.selection.main;
  const handled = v.state
    .facet(EditorView.inputHandler)
    .some((h) => h(v, from, to, ch, () => v.state.update({ changes: { from, to, insert: ch } })));
  if (!handled) v.dispatch({ changes: { from, to, insert: ch }, selection: { anchor: from + 1 } });
}

describe("Tab and Shift-Tab", () => {
  it("nests a bullet under the one above, and Shift-Tab brings it back", () => {
    const v = editor("- a\n- b|");
    expect(press(v, "Tab")).toBe(true);
    expect(text(v)).toBe("- a\n  - b|");
    expect(press(v, "Tab", { shift: true })).toBe(true);
    expect(text(v)).toBe("- a\n- b|");
  });

  it("nests a numbered item under its text, past the number", () => {
    const v = editor("1. a\n2. b|");
    press(v, "Tab");
    expect(v.state.doc.toString()).toBe("1. a\n   2. b");
  });

  it("nests a checkbox under the item above it", () => {
    const v = editor("- [ ] a\n- [ ] b|");
    press(v, "Tab");
    expect(v.state.doc.toString()).toBe("- [ ] a\n  - [ ] b");
  });

  it("indents a plain line rather than leaving the editor", () => {
    const v = editor("words|");
    expect(press(v, "Tab")).toBe(true);
    expect(v.state.doc.toString()).toBe("  words");
  });
});

describe("Enter", () => {
  it("continues a list, a numbered list and a checklist", () => {
    let v = editor("- a|");
    press(v, "Enter");
    expect(text(v)).toBe("- a\n- |");
    v.destroy();
    v = editor("1. a|");
    press(v, "Enter");
    expect(text(v)).toBe("1. a\n2. |");
    v.destroy();
    v = editor("- [x] a|");
    press(v, "Enter");
    expect(text(v)).toBe("- [x] a\n- [ ] |");
  });

  it("ends a list on an empty item, with a blank line so what follows is its own paragraph", () => {
    for (const [doc, ended] of [
      ["- a\n- |", "- a\n\n|"],
      ["1. a\n2. |", "1. a\n\n|"],
      ["- [ ] a\n- [ ] |", "- [ ] a\n\n|"],
    ]) {
      const v = editor(doc);
      press(v, "Enter");
      expect(text(v)).toBe(ended);
      v.destroy();
    }
  });

  it("moves an empty nested item out a level before ending the list", () => {
    const v = editor("- a\n  - |");
    press(v, "Enter");
    expect(text(v)).toBe("- a\n- |");
  });

  it("starts a plain, unindented line after a code block's closing fence", () => {
    const code = "```ts\nconst total = items.reduce((a, b) => a + b.price, 0); // cents\n```";
    const v = editor(`${code}|`);
    ensureSyntaxTree(v.state, v.state.doc.length, 5000);
    press(v, "Enter");
    expect(text(v)).toBe(`${code}\n|`);
  });

  it("leaves a quote on an empty quote line, with a blank line after it", () => {
    const v = editor("> said\n> |");
    press(v, "Enter");
    expect(text(v)).toBe("> said\n\n|");
  });
});

describe("Backspace", () => {
  it("removes an empty bullet", () => {
    let v = editor("- |");
    press(v, "Backspace");
    expect(v.state.doc.toString()).toBe("");
    v.destroy();
    v = editor("- a\n- |");
    press(v, "Backspace");
    expect(text(v)).toBe("- a\n|");
  });

  it("moves an empty nested bullet out a level first", () => {
    const v = editor("- a\n  - |");
    press(v, "Backspace");
    expect(text(v)).toBe("- a\n- |");
  });

  it("takes both halves of an empty pair", () => {
    const v = editor("see (|)");
    press(v, "Backspace");
    expect(text(v)).toBe("see |");
  });
});

describe("inside code, nothing is markup", () => {
  it("Tab indents a list-looking line in a code block as text, not as a nested item", () => {
    // As a list, `2.` would nest three spaces in, past `1.`; as code it's one indent.
    const v = editor("```\n1. a\n2. b|\n```");
    press(v, "Tab");
    expect(v.state.doc.toString()).toBe("```\n1. a\n  2. b\n```");
  });

  it("Enter on an empty `-` or `>` line in a code block keeps it and starts a new line", () => {
    let v = editor("```\n- |\n```");
    press(v, "Enter");
    expect(v.state.doc.toString()).toBe("```\n- \n\n```");
    v.destroy();
    v = editor("```\n> |\n```");
    press(v, "Enter");
    expect(v.state.doc.toString()).toBe("```\n> \n\n```");
  });

  it("Backspace on an empty `-` line in a code block deletes one character", () => {
    const v = editor("```\n- |\n```");
    press(v, "Backspace");
    expect(v.state.doc.toString()).toBe("```\n-\n```");
  });
});

describe("pairs", () => {
  it("wraps a selection in backticks, bold, brackets and parentheses", () => {
    let v = editor("a «word» b");
    type(v, "`");
    expect(v.state.doc.toString()).toBe("a `word` b");
    v.destroy();
    v = editor("a «word» b");
    type(v, "*");
    type(v, "*");
    expect(v.state.doc.toString()).toBe("a **word** b");
    v.destroy();
    v = editor("«word»");
    type(v, "[");
    expect(v.state.doc.toString()).toBe("[word]");
  });

  it("closes brackets and backticks typed alone, and steps over the closer", () => {
    const v = editor("|");
    type(v, "(");
    expect(text(v)).toBe("(|)");
    type(v, "x");
    type(v, ")");
    expect(text(v)).toBe("(x)|");
  });

  it("doesn't pair a backtick or quote right after a word", () => {
    const v = editor("it|");
    type(v, '"');
    expect(text(v)).toBe('it"|');
  });

  it("opens a closed fenced block on the third backtick at a line's start", () => {
    const v = editor("|");
    type(v, "`");
    type(v, "`");
    type(v, "`");
    expect(text(v)).toBe("```|\n\n```");
  });
});

describe("⌘K", () => {
  it("makes selected words a link with the cursor in the target", () => {
    const v = editor("«docs»");
    insertLink(v);
    expect(text(v)).toBe("[docs](|)");
  });

  it("makes a selected URL the target with the cursor in the words", () => {
    const v = editor("«https://example.com»");
    insertLink(v);
    expect(text(v)).toBe("[|](https://example.com)");
  });

  it("is bound to Mod-k", () => {
    const v = editor("|");
    expect(press(v, "k", { mod: true })).toBe(true);
    expect(text(v)).toBe("[|]()");
  });
});
