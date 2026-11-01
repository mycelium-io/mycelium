// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it } from "vitest";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { ensureSyntaxTree } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { livePreview } from "@/lib/editor/live-preview";

let view: EditorView | null = null;
afterEach(() => {
  view?.destroy();
  view = null;
});

/** An unfocused editor, so every line is drawn rather than shown as source. */
function preview(doc: string) {
  const state = EditorState.create({ doc, extensions: [markdown({ base: markdownLanguage }), livePreview()] });
  ensureSyntaxTree(state, doc.length, 5000);
  view = new EditorView({ state, parent: document.body });
  return view;
}

const q = (v: EditorView, sel: string) => v.contentDOM.querySelector(sel);
const qa = (v: EditorView, sel: string) => [...v.contentDOM.querySelectorAll(sel)];

describe("Live Preview", () => {
  it("draws headings, bold, italic and inline code with their marks hidden", () => {
    const v = preview("## Title\n\nSome **bold**, _soft_ and `code`.");
    expect(q(v, ".cm-md-h2")?.textContent).toBe("Title");
    expect(q(v, ".cm-md-bold")?.textContent).toBe("bold");
    expect(q(v, ".cm-md-italic")?.textContent).toBe("soft");
    expect(q(v, ".cm-md-inline-code")?.textContent).toBe("code");
    expect(v.contentDOM.textContent).not.toContain("**");
  });

  it("draws strikethrough", () => {
    const v = preview("~~gone~~");
    expect(q(v, ".cm-md-strike")?.textContent).toBe("gone");
    expect(v.contentDOM.textContent).toBe("gone");
  });

  it("draws a checkbox, and clicking it ticks the task in the text", () => {
    const v = preview("- [ ] ship it");
    const box = q(v, "input.cm-md-checkbox") as HTMLInputElement;
    expect(box.checked).toBe(false);
    box.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    expect(v.state.doc.toString()).toBe("- [x] ship it");
    expect((q(v, "input.cm-md-checkbox") as HTMLInputElement).checked).toBe(true);
    expect(q(v, ".cm-md-task-done")).not.toBeNull();
  });

  it("draws a bullet in place of a dash, and leaves numbers as numbers", () => {
    const v = preview("- one\n\n1. first");
    expect(q(v, ".cm-md-bullet")?.textContent).toBe("•");
    expect(q(v, ".cm-md-list-number")?.textContent).toBe("1.");
  });

  it("draws a quote with a bar and without its >", () => {
    const v = preview("> said once\n> said twice");
    expect(qa(v, ".cm-md-quote")).toHaveLength(2);
    expect(v.contentDOM.textContent).not.toContain(">");
  });

  it("draws [[links]] and ![[embeds]] as links to their keys", () => {
    const v = preview("See [[context/goal]] and ![[decisions/ship|the decision]].");
    const links = qa(v, ".cm-md-wikilink");
    expect(links.map((l) => l.getAttribute("data-key"))).toEqual(["context/goal", "decisions/ship"]);
    expect(q(v, ".cm-md-embed")).not.toBeNull();
    expect(v.contentDOM.textContent).not.toContain("[[");
  });

  it("leaves a [[link]] inside code alone", () => {
    const v = preview("`[[not/a/link]]`");
    expect(q(v, ".cm-md-wikilink")).toBeNull();
  });

  it("draws a rule for ---", () => {
    const v = preview("above\n\n---\n\nbelow");
    expect(q(v, ".cm-md-hr")).not.toBeNull();
  });

  it("draws a table as a table", () => {
    const v = preview("| Name | Size |\n| :--- | ---: |\n| cart | 3 |");
    const table = q(v, "table.cm-md-table") ?? document.querySelector("table.cm-md-table");
    expect(table).not.toBeNull();
    expect([...table!.querySelectorAll("th")].map((th) => th.textContent)).toEqual(["Name", "Size"]);
    expect((table!.querySelector("td:last-child") as HTMLElement).style.textAlign).toBe("right");
  });

  it("shows a table's source while the cursor is in it", () => {
    const v = preview("intro\n\n| a | b |\n| - | - |\n| 1 | 2 |");
    v.focus();
    v.contentDOM.dispatchEvent(new FocusEvent("focus"));
    v.dispatch({ selection: { anchor: v.state.doc.length } });
    expect(v.dom.querySelector("table.cm-md-table")).toBeNull();
    expect(v.contentDOM.textContent).toContain("| 1 | 2 |");
  });

  it("keeps a code block's fence lines, so its height doesn't change with the cursor", () => {
    const doc = "```js\nconst a = 1;\n```";
    const v = preview(doc);
    expect(qa(v, ".cm-line")).toHaveLength(3);
    expect(qa(v, ".cm-md-fence")).toHaveLength(2);
    expect(q(v, ".cm-md-fence")?.textContent).toContain("js");
  });

  it("doesn't reveal a line while the mouse button is down, so a click doesn't move the text under it", () => {
    const v = preview("**bold** here\n\n**bold** there");
    v.focus();
    v.contentDOM.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    v.dispatch({ selection: { anchor: v.state.doc.length - 2 } });
    expect(qa(v, ".cm-line")[2].textContent).toBe("bold there");
    window.dispatchEvent(new MouseEvent("mouseup"));
    expect(qa(v, ".cm-line")[2].textContent).toBe("**bold** there");
  });

  it("shows the source on the line the cursor is on", () => {
    const v = preview("**bold** here\n\n**bold** there");
    v.focus();
    v.dispatch({ selection: { anchor: 2 } });
    const lines = qa(v, ".cm-line").map((l) => l.textContent);
    expect(lines[0]).toBe("**bold** here");
    expect(lines[2]).toBe("bold there");
  });
});
