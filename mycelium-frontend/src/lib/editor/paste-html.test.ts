// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it } from "vitest";
import { markdown, markdownLanguage } from "@codemirror/lang-markdown";
import { ensureSyntaxTree } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { htmlToMarkdown, pasteAsMarkdown } from "@/lib/editor/paste-html";

describe("htmlToMarkdown", () => {
  it("keeps headings, emphasis, strikethrough, code and links", () => {
    expect(
      htmlToMarkdown(
        '<h2>Plan</h2><p>Ship <strong>today</strong>, <em>maybe</em> <del>never</del>. Run <code>make</code>; see <a href="https://example.com">the docs</a>.</p>',
      ),
    ).toBe("## Plan\n\nShip **today**, _maybe_ ~~never~~. Run `make`; see [the docs](https://example.com).");
  });

  it("keeps nested lists, numbering and checkboxes", () => {
    expect(
      htmlToMarkdown(
        '<ol start="3"><li>three<ul><li>sub</li></ul></li><li>four</li></ol><ul><li><input type="checkbox" checked> done</li></ul>',
      ),
    ).toBe("3. three\n  - sub\n4. four\n\n- [x] done");
  });

  it("keeps quotes, code blocks with their language, rules and tables", () => {
    expect(
      htmlToMarkdown(
        '<blockquote><p>said</p></blockquote><pre><code class="language-js">const a = 1;\n</code></pre><hr><table><tr><th>a</th><th>b</th></tr><tr><td>1</td><td>2</td></tr></table>',
      ),
    ).toBe("> said\n\n```js\nconst a = 1;\n```\n\n---\n\n| a | b |\n| --- | --- |\n| 1 | 2 |");
  });

  it("reads Google Docs' styled spans as bold and italic", () => {
    expect(
      htmlToMarkdown('<span style="font-weight:700">loud</span> and <span style="font-style:italic">soft</span>'),
    ).toBe("**loud** and _soft_");
  });

  it("escapes what would read as markdown, but not snake_case", () => {
    expect(htmlToMarkdown("<p>a *star* and my_var and _x_</p>")).toBe("a \\*star\\* and my_var and \\_x\\_");
  });
});

describe("pasting", () => {
  let view: EditorView | null = null;
  afterEach(() => {
    view?.destroy();
    view = null;
  });

  function paste(doc: string, at: number, html: string) {
    const state = EditorState.create({
      doc,
      selection: { anchor: at },
      extensions: [markdown({ base: markdownLanguage }), pasteAsMarkdown],
    });
    ensureSyntaxTree(state, doc.length, 5000);
    view = new EditorView({ state, parent: document.body });
    const event = new Event("paste", { bubbles: true, cancelable: true }) as ClipboardEvent;
    Object.defineProperty(event, "clipboardData", {
      value: { getData: (type: string) => (type === "text/html" ? html : "") },
    });
    view.contentDOM.dispatchEvent(event);
    // When this handler declines, CodeMirror's own pastes the plain text,
    // which this fake clipboard leaves empty.
    return view.state.doc.toString();
  }

  it("pastes rich text as markdown", () => {
    expect(paste("", 0, "<p><b>hi</b></p>")).toBe("**hi**");
  });

  it("leaves pasting into code to the plain text", () => {
    expect(paste("```\n\n```", 4, "<p><b>hi</b></p>")).toBe("```\n\n```");
  });

  it("leaves HTML with no formatting to the plain text", () => {
    expect(paste("", 0, "<div>just words</div>")).toBe("");
  });
});
