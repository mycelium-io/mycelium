// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { markdown } from "@codemirror/lang-markdown";
import { ensureSyntaxTree } from "@codemirror/language";
import { EditorState } from "@codemirror/state";
import { EditorView } from "@codemirror/view";
import { describe, expect, it } from "vitest";
import { headingGutter } from "@/lib/heading-gutter";

describe("headingGutter", () => {
  it("labels each heading line with its level, and nothing else", () => {
    const state = EditorState.create({
      doc: "# One\ntext\n## Two\n```\n# not a heading\n```\n### Three",
      extensions: [markdown(), headingGutter],
    });
    ensureSyntaxTree(state, state.doc.length, 5000);
    const view = new EditorView({ state, parent: document.body });
    try {
      const labels = [...view.contentDOM.querySelectorAll(".cm-heading-line")].map((el) =>
        el.getAttribute("data-heading"),
      );
      expect(labels).toEqual(["H1", "H2", "H3"]);
    } finally {
      view.destroy();
    }
  });
});
