// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { syntaxTree } from "@codemirror/language";
import type { Range } from "@codemirror/state";
import { Decoration, type DecorationSet, type EditorView, ViewPlugin, type ViewUpdate } from "@codemirror/view";

/**
 * Live Preview hides a heading's `#` marks once the cursor leaves its line,
 * which leaves the level unreadable. This marks every heading line with its
 * level (H1–H6), drawn in the margin by the `.cm-heading-line` rule in
 * globals.css, so the level stays in view without the marks.
 */
function headingLines(view: EditorView): DecorationSet {
  const marks: Range<Decoration>[] = [];
  for (const { from, to } of view.visibleRanges) {
    syntaxTree(view.state).iterate({
      from,
      to,
      enter: (node) => {
        const m = /^ATXHeading([1-6])$/.exec(node.name);
        if (!m) return;
        const line = view.state.doc.lineAt(node.from);
        marks.push(
          Decoration.line({ class: "cm-heading-line", attributes: { "data-heading": `H${m[1]}` } }).range(line.from),
        );
        return false;
      },
    });
  }
  return Decoration.set(marks, true);
}

export const headingGutter = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = headingLines(view);
    }
    update(u: ViewUpdate) {
      if (u.docChanged || u.viewportChanged || syntaxTree(u.startState) !== syntaxTree(u.state)) {
        this.decorations = headingLines(u.view);
      }
    }
  },
  { decorations: (v) => v.decorations },
);
