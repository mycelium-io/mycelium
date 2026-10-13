// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { indentLess, indentMore } from "@codemirror/commands";
import { EditorSelection, type EditorState, type Extension, Prec, type StateCommand } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";

/**
 * The editing keys an Obsidian user expects, on top of CodeMirror's markdown
 * keymap (which already continues lists on Enter and removes an empty bullet
 * on Backspace): Tab and Shift-Tab indent, pairs close and wrap a selection,
 * three backticks open a fenced block, Enter leaves an empty quote, and ⌘K
 * makes a link. Esc then Tab still leaves the editor (CodeMirror's own rule).
 */

/** A list item's leading space, marker (with any checkbox) and the space after it. */
const LIST_ITEM = /^(\s*)((?:[-*+]|\d+[.)])(?: \[[ xX]\])?)( +|$)/;

function listItem(text: string) {
  const m = LIST_ITEM.exec(text);
  if (!m) return null;
  return { indent: m[1].length, marker: m[2], contentAt: m[1].length + m[2].length + Math.max(1, m[3].length) };
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

/** Tab on list items: nest each under the item above it. Elsewhere, indent. */
export const indentListOrLine: StateCommand = ({ state, dispatch }) => {
  const numbers = selectedLineNumbers(state);
  const items = numbers.map((n) => ({ n, item: listItem(state.doc.line(n).text) }));
  if (!items.every((i) => i.item)) return indentMore({ state, dispatch });
  const targets = items.map(({ n, item }) => {
    // The nearest item above at this item's depth or shallower is what it nests under.
    for (let p = n - 1; p >= 1; p -= 1) {
      const above = listItem(state.doc.line(p).text);
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
  const numbers = selectedLineNumbers(state);
  const items = numbers.map((n) => ({ n, item: listItem(state.doc.line(n).text) }));
  if (!items.every((i) => i.item)) return indentLess({ state, dispatch });
  const targets = items.map(({ n, item }) => {
    for (let p = n - 1; p >= 1; p -= 1) {
      const above = listItem(state.doc.line(p).text);
      if (above && above.indent < item!.indent) return { number: n, indent: above.indent };
      if (!above && state.doc.line(p).text.trim() !== "") break;
    }
    return { number: n, indent: 0 };
  });
  if (targets.every((t, i) => t.indent === items[i].item!.indent)) return true;
  dispatch(reindent(state, targets));
  return true;
};

/** The cursor alone at the end of an item with nothing written in it. */
function emptyItemAtCursor(state: EditorState) {
  const sel = state.selection.main;
  if (!sel.empty || state.selection.ranges.length > 1) return null;
  const line = state.doc.lineAt(sel.head);
  if (sel.head !== line.to) return null;
  const item = listItem(line.text);
  if (!item || line.text.trim() !== item.marker) return null;
  return { line, item };
}

/** Enter or Backspace on an empty nested item moves it out a level, as Obsidian does. */
const outdentEmptyNestedItem: StateCommand = (target) => {
  const empty = emptyItemAtCursor(target.state);
  if (!empty || empty.item.indent === 0) return false;
  return outdentListOrLine(target);
};

/**
 * Clear the cursor's line and leave a blank line above it, so what's typed next
 * starts a new paragraph rather than running on into the list or quote above
 * (markdown carries a line straight after one into it).
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

/** Enter on a quote line with nothing after its `>` leaves the quote. */
const leaveEmptyQuote: StateCommand = ({ state, dispatch }) => {
  const sel = state.selection.main;
  if (!sel.empty || state.selection.ranges.length > 1) return false;
  const line = state.doc.lineAt(sel.head);
  if (!/^\s*>[>\s]*$/.test(line.text) || sel.head !== line.to) return false;
  return leaveBlock(state, dispatch);
};

/** Backspace on an empty top-level item takes its marker away in one press.
 *  (CodeMirror's own leaves the line indented inside the item.) */
const removeEmptyItem: StateCommand = ({ state, dispatch }) => {
  const empty = emptyItemAtCursor(state);
  if (!empty || empty.item.indent > 0) return false;
  dispatch(state.update({ changes: { from: empty.line.from, to: empty.line.to }, userEvent: "delete.backward" }));
  return true;
};

/** Enter on an empty item at the list's top level ends the list. (CodeMirror's
 *  own Enter would make the list loose and start another item.) */
const endListOnEmptyItem: StateCommand = ({ state, dispatch }) => {
  const empty = emptyItemAtCursor(state);
  if (!empty || empty.item.indent > 0) return false;
  return leaveBlock(state, dispatch);
};

/** What each opening character closes with, when it wraps or pairs. */
const PAIRS: Record<string, string> = { "`": "`", "*": "*", _: "_", "~": "~", "=": "=", "[": "]", "(": ")", '"': '"' };
/** The ones typed alone that close themselves too. Emphasis marks don't:
 *  `*` starts a bullet as often as it starts emphasis. */
const AUTO_CLOSE = new Set(["(", "[", "`", '"']);
const CLOSERS = new Set([")", "]", "`", '"']);

/** Typing a pair's opener over a selection wraps it; typed alone, a bracket or
 *  backtick closes itself; typing a closer that's already next steps over it. */
const pairInput = EditorView.inputHandler.of((view, from, to, text) => {
  if (text.length !== 1 || view.composing || view.state.selection.ranges.length > 1) return false;
  const { state } = view;
  const close = PAIRS[text];
  if (from !== to && close) {
    view.dispatch({
      changes: [
        { from, insert: text },
        { from: to, insert: close },
      ],
      selection: EditorSelection.range(from + 1, to + 1),
      userEvent: "input.type",
    });
    return true;
  }
  if (from !== to) return false;
  const line = state.doc.lineAt(from);
  const before = state.sliceDoc(line.from, from);
  const next = state.sliceDoc(from, from + 1);
  if (text === "`" && /^\s*``$/.test(before) && (next === "" || next === "`")) {
    // The third backtick at a line's start: a fenced block, closed, with the
    // cursor where its language goes.
    const indent = /^\s*/.exec(before)?.[0] ?? "";
    const rest = state.sliceDoc(from, line.to);
    view.dispatch({
      changes: { from, to: from + (/^`*$/.test(rest) ? rest.length : 0), insert: `\`\n${indent}\n${indent}\`\`\`` },
      selection: EditorSelection.cursor(from + 1),
      userEvent: "input.type",
    });
    return true;
  }
  if (CLOSERS.has(text) && next === text) {
    view.dispatch({ selection: EditorSelection.cursor(from + 1), userEvent: "select" });
    return true;
  }
  if (AUTO_CLOSE.has(text) && (next === "" || /[\s)\]}.,;:!?]/.test(next))) {
    const prev = state.sliceDoc(from - 1, from);
    // A quote or backtick right after a word is an apostrophe or the end of
    // something, not the start of a pair.
    if ((text === '"' || text === "`") && /\w/.test(prev)) return false;
    view.dispatch({
      changes: { from, insert: text + close },
      selection: EditorSelection.cursor(from + 1),
      userEvent: "input.type",
    });
    return true;
  }
  return false;
});

/** Backspace between a pair with nothing in it takes both. */
const deleteEmptyPair: StateCommand = ({ state, dispatch }) => {
  const sel = state.selection.main;
  if (!sel.empty || state.selection.ranges.length > 1) return false;
  const open = state.sliceDoc(sel.head - 1, sel.head);
  if (!AUTO_CLOSE.has(open) || state.sliceDoc(sel.head, sel.head + 1) !== PAIRS[open]) return false;
  dispatch(state.update({ changes: { from: sel.head - 1, to: sel.head + 1 }, userEvent: "delete.backward" }));
  return true;
};

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

/** Everything above, ahead of CodeMirror's markdown keymap. */
export function markdownKeys(): Extension {
  return [
    pairInput,
    Prec.highest(
      keymap.of([
        { key: "Tab", run: indentListOrLine, shift: outdentListOrLine },
        { key: "Enter", run: (t) => leaveEmptyQuote(t) || outdentEmptyNestedItem(t) || endListOnEmptyItem(t) },
        { key: "Backspace", run: (t) => deleteEmptyPair(t) || outdentEmptyNestedItem(t) || removeEmptyItem(t) },
        { key: "Mod-k", run: insertLink, preventDefault: true },
      ]),
    ),
  ];
}
