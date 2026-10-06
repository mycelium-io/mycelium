// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { EditorView } from "@codemirror/view";

/**
 * Formatting commands for the memory editors' toolbar and shortcuts. Each acts
 * on the editor's selection and toggles: running one on text that already has
 * the format takes it off, the way a word processor's Bold button does.
 */

/** Wrap the selection in `before`/`after`, unwrap it if it already is, or
 *  insert the pair around a selected placeholder when nothing is selected. */
export function toggleWrap(view: EditorView, before: string, after: string, placeholder: string) {
  const { state } = view;
  const { from, to } = state.selection.main;
  const outerFrom = from - before.length;
  const outerTo = to + after.length;
  if (
    outerFrom >= 0 &&
    outerTo <= state.doc.length &&
    state.sliceDoc(outerFrom, from) === before &&
    state.sliceDoc(to, outerTo) === after
  ) {
    view.dispatch({
      changes: [
        { from: outerFrom, to: from, insert: "" },
        { from: to, to: outerTo, insert: "" },
      ],
      selection: { anchor: outerFrom, head: to - before.length },
    });
    view.focus();
    return;
  }
  const selected = state.sliceDoc(from, to);
  if (selected.length > before.length + after.length && selected.startsWith(before) && selected.endsWith(after)) {
    const inner = selected.slice(before.length, selected.length - after.length);
    view.dispatch({ changes: { from, to, insert: inner }, selection: { anchor: from, head: from + inner.length } });
    view.focus();
    return;
  }
  const text = selected || placeholder;
  view.dispatch({
    changes: { from, to, insert: `${before}${text}${after}` },
    selection: { anchor: from + before.length, head: from + before.length + text.length },
  });
  view.focus();
}

/** The lines the selection touches. */
function selectedLines(view: EditorView) {
  const { state } = view;
  const { from, to } = state.selection.main;
  const first = state.doc.lineAt(from).number;
  const last = state.doc.lineAt(to).number;
  const lines = [];
  for (let n = first; n <= last; n += 1) lines.push(state.doc.line(n));
  return lines;
}

/** Any list or quote marker a line already starts with, so switching a line
 *  from one kind of list to another replaces the marker rather than stacking. */
const BLOCK_MARKER = /^(\s*)(?:[-*+] \[[ xX]\] |[-*+] |\d+[.)] |> )/;

/**
 * Start every selected line with the marker `kind` makes, or take it off when
 * they all have it already. A numbered list counts up from 1.
 */
export function toggleLinePrefix(view: EditorView, kind: "bullet" | "number" | "task" | "quote") {
  const lines = selectedLines(view);
  const has = (text: string) =>
    kind === "bullet"
      ? /^\s*[-*+] (?!\[[ xX]\] )/.test(text)
      : kind === "number"
        ? /^\s*\d+[.)] /.test(text)
        : kind === "task"
          ? /^\s*[-*+] \[[ xX]\] /.test(text)
          : /^\s*> /.test(text);
  const nonEmpty = lines.filter((l) => l.text.trim() !== "");
  const allHave = nonEmpty.length > 0 && nonEmpty.every((l) => has(l.text));
  let n = 0;
  const changes = lines.flatMap((line) => {
    if (line.text.trim() === "" && lines.length > 1) return [];
    const m = BLOCK_MARKER.exec(line.text);
    const indent = m?.[1] ?? /^\s*/.exec(line.text)?.[0] ?? "";
    const markerEnd = line.from + (m ? m[0].length : indent.length);
    if (allHave) return [{ from: line.from + indent.length, to: markerEnd, insert: "" }];
    n += 1;
    const marker = kind === "bullet" ? "- " : kind === "number" ? `${n}. ` : kind === "task" ? "- [ ] " : "> ";
    return [{ from: line.from + indent.length, to: markerEnd, insert: marker }];
  });
  view.dispatch({ changes });
  view.focus();
}

/** Step the cursor's line through heading levels: text → H2 → H3 → H1 → text. */
export function cycleHeading(view: EditorView) {
  const line = view.state.doc.lineAt(view.state.selection.main.from);
  const m = /^(#{1,6}) /.exec(line.text);
  const level = m ? m[1].length : 0;
  const next = level === 0 ? 2 : level === 2 ? 3 : level === 3 ? 1 : 0;
  const insert = next === 0 ? "" : `${"#".repeat(next)} `;
  view.dispatch({ changes: { from: line.from, to: line.from + (m ? m[0].length : 0), insert } });
  view.focus();
}

/** Put `text` on lines of its own at the cursor, replacing any selection. */
export function insertBlock(view: EditorView, text: string, selectFrom?: number, selectTo?: number) {
  const { state } = view;
  const { from, to } = state.selection.main;
  const before = state.sliceDoc(Math.max(0, from - 2), from);
  const after = state.sliceDoc(to, Math.min(state.doc.length, to + 2));
  const lead = from === 0 || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
  const trail = to === state.doc.length ? "\n" : after.startsWith("\n\n") ? "" : after.startsWith("\n") ? "\n" : "\n\n";
  const insert = `${lead}${text}${trail}`;
  const start = from + lead.length;
  view.dispatch({
    changes: { from, to, insert },
    selection:
      selectFrom === undefined
        ? { anchor: start + text.length }
        : { anchor: start + selectFrom, head: start + (selectTo ?? selectFrom) },
    scrollIntoView: true,
  });
  view.focus();
}

/** Fence the selection as a code block, or open an empty one at the cursor. */
export function codeBlock(view: EditorView) {
  const { from, to } = view.state.selection.main;
  const selected = view.state.sliceDoc(from, to);
  const fenced = `\`\`\`\n${selected}\n\`\`\``;
  insertBlock(view, fenced, 4, 4 + selected.length);
}

export const TABLE_TEMPLATE = "| Column | Column |\n| --- | --- |\n| Cell | Cell |";

/** Counts for the editor's status line. */
export function textStats(text: string): { words: number; chars: number; minutes: number } {
  const words = text.trim() === "" ? 0 : text.trim().split(/\s+/).length;
  return { words, chars: text.length, minutes: Math.max(1, Math.round(words / 230)) };
}

/** A `[[key]]` or `![[key]]` written in a body, and whether its key exists. */
export interface DraftLink {
  key: string;
  embed: boolean;
  exists: boolean;
}

/** The links a body makes, de-duplicated, in the order they first appear. */
export function draftLinks(text: string, keys: ReadonlySet<string>): DraftLink[] {
  const seen = new Set<string>();
  const out: DraftLink[] = [];
  for (const m of text.matchAll(/(!?)\[\[([^\]\n|#]+)(?:[#|][^\]\n]*)?\]\]/g)) {
    const key = m[2].trim();
    const embed = m[1] === "!";
    const id = `${embed ? "!" : ""}${key}`;
    if (!key || seen.has(id)) continue;
    seen.add(id);
    out.push({ key, embed, exists: keys.has(key) });
  }
  return out;
}
