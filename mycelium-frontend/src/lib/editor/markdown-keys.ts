// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { closeBrackets, closeBracketsKeymap } from "@codemirror/autocomplete";
import { indentLess, indentMore } from "@codemirror/commands";
import { deleteMarkupBackward, insertNewlineContinueMarkupCommand } from "@codemirror/lang-markdown";
import { type Language, syntaxTree } from "@codemirror/language";
import { EditorSelection, type EditorState, type Extension, Prec, type StateCommand } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";

/**
 * The editing keys an Obsidian user expects. CodeMirror does most of it:
 * lang-markdown continues and ends lists on Enter (with `nonTightLists` off,
 * so ending one doesn't make it loose), and `closeBrackets` pairs, wraps and
 * steps over brackets. The commands here cover only where those still differ
 * from Obsidian, each saying how, and every one leaves code alone, the way
 * CodeMirror's own markdown commands do. Esc then Tab still leaves the editor.
 */

/** Whether `pos` is inside a code block or inline code, where nothing is markup. */
function inCode(state: EditorState, pos: number): boolean {
  for (let node: ReturnType<typeof syntaxTree>["topNode"] | null = syntaxTree(state).resolveInner(pos, -1); node; node = node.parent) {
    if (node.name === "FencedCode" || node.name === "CodeBlock" || node.name === "InlineCode") return true;
  }
  return false;
}

/** A list item's leading space and marker (with any checkbox). */
const LIST_ITEM = /^(\s*)((?:[-*+]|\d+[.)])(?: \[[ xX]\])?)(?: +|$)/;

function listItem(state: EditorState, lineNumber: number) {
  const line = state.doc.line(lineNumber);
  const m = LIST_ITEM.exec(line.text);
  if (!m || inCode(state, line.from + m[1].length)) return null;
  return { indent: m[1].length, marker: m[2] };
}

/** Where a nested item's marker goes under `parent`: under its text. */
const childIndent = (parent: { indent: number; marker: string }) =>
  parent.indent + parent.marker.replace(/ \[[ xX]\]$/, "").length + 1;

function selectedLineNumbers(state: EditorState): number[] {
  const out = new Set<number>();
  for (const r of state.selection.ranges) {
    const first = state.doc.lineAt(r.from).number;
    const last = state.doc.lineAt(r.to).number;
    for (let n = first; n <= last; n += 1) out.add(n);
  }
  return [...out].sort((a, b) => a - b);
}

/** Change each line's leading space to `indent`, keeping the cursor on its text. */
function reindent(state: EditorState, lines: { number: number; indent: number }[]) {
  const changes = lines.map(({ number, indent }) => {
    const line = state.doc.line(number);
    const current = /^\s*/.exec(line.text)?.[0].length ?? 0;
    return { from: line.from, to: line.from + current, insert: " ".repeat(Math.max(0, indent)) };
  });
  return state.update({ changes, scrollIntoView: true, userEvent: "input.indent" });
}

/** Tab on list items: nest each under the item above it, under its text (so a
 *  numbered item's children clear the number). Elsewhere, including code, indent. */
export const indentListOrLine: StateCommand = ({ state, dispatch }) => {
  const items = selectedLineNumbers(state).map((n) => ({ n, item: listItem(state, n) }));
  if (!items.every((i) => i.item)) return indentMore({ state, dispatch });
  const targets = items.map(({ n, item }) => {
    // The nearest item above at this item's depth or shallower is what it nests under.
    for (let p = n - 1; p >= 1; p -= 1) {
      const above = listItem(state, p);
      if (above && above.indent <= item!.indent) {
        return { number: n, indent: above.indent === item!.indent ? childIndent(above) : item!.indent };
      }
      if (!above && state.doc.line(p).text.trim() !== "") break;
    }
    return { number: n, indent: item!.indent };
  });
  if (targets.every((t, i) => t.indent === items[i].item!.indent)) return true;
  dispatch(reindent(state, targets));
  return true;
};

/** Shift-Tab on list items: out to the item they're nested under. Elsewhere, outdent. */
export const outdentListOrLine: StateCommand = ({ state, dispatch }) => {
  const items = selectedLineNumbers(state).map((n) => ({ n, item: listItem(state, n) }));
  if (!items.every((i) => i.item)) return indentLess({ state, dispatch });
  const targets = items.map(({ n, item }) => {
    for (let p = n - 1; p >= 1; p -= 1) {
      const above = listItem(state, p);
      if (above && above.indent < item!.indent) return { number: n, indent: above.indent };
      if (!above && state.doc.line(p).text.trim() !== "") break;
    }
    return { number: n, indent: 0 };
  });
  if (targets.every((t, i) => t.indent === items[i].item!.indent)) return true;
  dispatch(reindent(state, targets));
  return true;
};

/** The lone cursor at the end of a line it's on, outside code. */
function cursorLine(state: EditorState) {
  const sel = state.selection.main;
  if (!sel.empty || state.selection.ranges.length > 1) return null;
  const line = state.doc.lineAt(sel.head);
  if (sel.head !== line.to || inCode(state, sel.head)) return null;
  return line;
}

/** The cursor at the end of a list item with nothing written in it. */
function emptyItemAtCursor(state: EditorState) {
  const line = cursorLine(state);
  if (!line) return null;
  const item = listItem(state, line.number);
  if (!item || line.text.trim() !== item.marker) return null;
  return { line, item };
}

/**
 * Clear the cursor's line and leave a blank line above it, so what's typed next
 * is a paragraph of its own: markdown carries a line typed straight after a
 * list item or a quote into it.
 */
function leaveBlock(state: EditorState, dispatch: (tr: ReturnType<EditorState["update"]>) => void) {
  const line = state.doc.lineAt(state.selection.main.head);
  const above = line.number > 1 ? state.doc.line(line.number - 1).text : "";
  const insert = line.number > 1 && above.trim() !== "" ? "\n" : "";
  dispatch(
    state.update({
      changes: { from: line.from, to: line.to, insert },
      selection: EditorSelection.cursor(line.from + insert.length),
      userEvent: "delete",
    }),
  );
  return true;
}

/** Enter on a top-level empty item ends the list. lang-markdown's Enter does
 *  too, but leaves no blank line, so the next line would still be the item's. */
const endListOnEmptyItem: StateCommand = ({ state, dispatch }) => {
  const empty = emptyItemAtCursor(state);
  if (!empty || empty.item.indent > 0) return false;
  return leaveBlock(state, dispatch);
};

/** Enter on a quote line with nothing after its `>` leaves the quote.
 *  lang-markdown's Enter keeps adding `>`, so a quote can't be left with it. */
const leaveEmptyQuote: StateCommand = ({ state, dispatch }) => {
  const line = cursorLine(state);
  if (!line || !/^\s*>[>\s]*$/.test(line.text)) return false;
  return leaveBlock(state, dispatch);
};

/** Backspace on an empty item: a nested one moves out a level, a top-level one
 *  loses its marker. lang-markdown's Backspace leaves the line indented inside
 *  the item instead, which takes a second press to leave. */
const backspaceEmptyItem: StateCommand = (target) => {
  const empty = emptyItemAtCursor(target.state);
  if (!empty) return false;
  if (empty.item.indent > 0) return outdentListOrLine(target);
  target.dispatch(
    target.state.update({ changes: { from: empty.line.from, to: empty.line.to }, userEvent: "delete.backward" }),
  );
  return true;
};

/** What `closeBrackets` pairs in markdown: brackets, backticks and quotes.
 *  Emphasis marks don't pair as they're typed: `*` starts a bullet as often
 *  as it starts emphasis. */
const BRACKETS = ["(", "[", "`", '"'];
/** Marks that wrap a selection, which `closeBrackets` doesn't do for them. */
const WRAPS = new Set(["*", "_", "~", "="]);

/**
 * The two things `closeBrackets` can't: an emphasis mark typed over a
 * selection wraps it, and a third backtick at a line's start opens a closed
 * fenced block (where `closeBrackets` would add a fourth).
 */
const markdownInput = EditorView.inputHandler.of((view, from, to, text) => {
  if (text.length !== 1 || view.composing || view.state.selection.ranges.length > 1) return false;
  const { state } = view;
  if (from !== to && WRAPS.has(text)) {
    view.dispatch({
      changes: [
        { from, insert: text },
        { from: to, insert: text },
      ],
      selection: EditorSelection.range(from + 1, to + 1),
      userEvent: "input.type",
    });
    return true;
  }
  if (text !== "`" || from !== to) return false;
  const line = state.doc.lineAt(from);
  const before = state.sliceDoc(line.from, from);
  const rest = state.sliceDoc(from, line.to);
  if (!/^\s*``$/.test(before) || !/^`*$/.test(rest)) return false;
  const indent = /^\s*/.exec(before)?.[0] ?? "";
  view.dispatch({
    changes: { from, to: line.to, insert: `\`\n${indent}\n${indent}\`\`\`` },
    selection: EditorSelection.cursor(from + 1),
    userEvent: "input.type",
  });
  return true;
});

const URL_RE = /^(?:https?:\/\/|mailto:)\S+$/;

/** ⌘K: a markdown link. Selected text becomes its words, a selected URL its
 *  target; the cursor waits in whichever part is still empty. */
export const insertLink: StateCommand = ({ state, dispatch }) => {
  const { from, to } = state.selection.main;
  const selected = state.sliceDoc(from, to);
  if (URL_RE.test(selected.trim())) {
    dispatch(
      state.update({
        changes: { from, to, insert: `[](${selected.trim()})` },
        selection: EditorSelection.cursor(from + 1),
        userEvent: "input",
      }),
    );
    return true;
  }
  const insert = `[${selected}]()`;
  dispatch(
    state.update({
      changes: { from, to, insert },
      selection: EditorSelection.cursor(from + (selected ? insert.length - 1 : 1)),
      userEvent: "input",
    }),
  );
  return true;
};

/**
 * The editing keys, for `language` (the markdown the editor parses). Pass
 * `markdown({ addKeymap: false })`: this supplies lang-markdown's Enter and
 * Backspace itself, with the settings and exceptions above.
 */
export function markdownKeys(language: Language): Extension {
  return [
    language.data.of({ closeBrackets: { brackets: BRACKETS } }),
    Prec.high(markdownInput),
    closeBrackets(),
    Prec.highest(
      keymap.of([
        { key: "Tab", run: indentListOrLine, shift: outdentListOrLine },
        {
          key: "Enter",
          run: (t) =>
            endListOnEmptyItem(t) || leaveEmptyQuote(t) || insertNewlineContinueMarkupCommand({ nonTightLists: false })(t),
        },
        { key: "Backspace", run: (t) => backspaceEmptyItem(t) || deleteMarkupBackward(t) },
        { key: "Mod-k", run: insertLink, preventDefault: true },
      ]),
    ),
    keymap.of(closeBracketsKeymap),
  ];
}
