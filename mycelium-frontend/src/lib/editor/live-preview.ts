// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { syntaxTree } from "@codemirror/language";
import {
  type EditorState,
  type Extension,
  type Range,
  RangeSetBuilder,
  StateEffect,
  StateField,
} from "@codemirror/state";
import {
  Decoration,
  type DecorationSet,
  EditorView,
  ViewPlugin,
  type ViewUpdate,
  WidgetType,
} from "@codemirror/view";
import type { SyntaxNodeRef } from "@lezer/common";

/**
 * Live Preview: markdown drawn as it reads while it stays plain text, the way
 * Obsidian's editor does. Syntax shows on the lines the cursor is on and is
 * drawn everywhere else. Nothing here changes the document except a click on
 * a checkbox, so a memory is always exactly the markdown that was typed.
 *
 * Every drawn line keeps the height of its source: marks are hidden in place
 * rather than lines removed, so moving the cursor never makes the page jump.
 */

/** Lines the selection touches, while the editor has focus; none without it,
 *  so a page that isn't being edited reads fully drawn. */
function activeLines(view: EditorView): Set<number> {
  const lines = new Set<number>();
  if (!view.hasFocus) return lines;
  for (const r of view.state.selection.ranges) {
    const first = view.state.doc.lineAt(r.from).number;
    const last = view.state.doc.lineAt(r.to).number;
    for (let n = first; n <= last; n += 1) lines.add(n);
  }
  return lines;
}

/** Whether the selection touches `from..to` (inclusive at both ends). */
function cursorIn(view: EditorView, from: number, to: number): boolean {
  if (!view.hasFocus) return false;
  return view.state.selection.ranges.some((r) => r.from <= to && r.to >= from);
}

const hide = Decoration.replace({});
const mark = (cls: string) => Decoration.mark({ class: cls });
const HEADING = [1, 2, 3, 4, 5, 6].map((n) => mark(`cm-md-h${n}`));
const BOLD = mark("cm-md-bold");
const ITALIC = mark("cm-md-italic");
const STRIKE = mark("cm-md-strike");
const CODE = mark("cm-md-inline-code");
const LINK = mark("cm-md-link");
const LIST_NUMBER = mark("cm-md-list-number");
const CODE_LINE = Decoration.line({ class: "cm-md-code-block" });
const FENCE_LINE = Decoration.line({ class: "cm-md-code-block cm-md-fence" });
const QUOTE_LINE = Decoration.line({ class: "cm-md-quote" });
const DONE_LINE = Decoration.line({ class: "cm-md-task-done" });

class BulletWidget extends WidgetType {
  eq() {
    return true;
  }
  toDOM() {
    const span = document.createElement("span");
    span.className = "cm-md-bullet";
    span.textContent = "•";
    span.setAttribute("aria-hidden", "true");
    return span;
  }
}

/** A task's box. A click flips `[ ]` and `[x]` in the text, so the change is
 *  ordinary markdown and undoes like any other edit. */
class CheckboxWidget extends WidgetType {
  constructor(readonly checked: boolean) {
    super();
  }
  eq(other: CheckboxWidget) {
    return other.checked === this.checked;
  }
  toDOM(view: EditorView) {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.className = "cm-md-checkbox";
    box.checked = this.checked;
    box.setAttribute("aria-label", this.checked ? "Done" : "Not done");
    box.addEventListener("mousedown", (e) => {
      e.preventDefault();
      toggleTaskAt(view, view.posAtDOM(box));
    });
    return box;
  }
  ignoreEvent() {
    return true;
  }
}

/** Flip the `[ ]`/`[x]` of the task whose line holds `pos`. */
export function toggleTaskAt(view: EditorView, pos: number): boolean {
  const line = view.state.doc.lineAt(pos);
  const m = /^(\s*(?:[-*+]|\d+[.)]) \[)([ xX])\]/.exec(line.text);
  if (!m) return false;
  const at = line.from + m[1].length;
  view.dispatch({ changes: { from: at, to: at + 1, insert: m[2] === " " ? "x" : " " } });
  return true;
}

class RuleWidget extends WidgetType {
  eq() {
    return true;
  }
  toDOM() {
    const span = document.createElement("span");
    span.className = "cm-md-hr";
    span.setAttribute("role", "separator");
    return span;
  }
}

class ImageWidget extends WidgetType {
  constructor(
    readonly alt: string,
    readonly src: string,
  ) {
    super();
  }
  eq(other: ImageWidget) {
    return other.alt === this.alt && other.src === this.src;
  }
  toDOM() {
    const img = document.createElement("img");
    img.src = this.src;
    img.alt = this.alt;
    img.className = "cm-md-image";
    return img;
  }
  ignoreEvent() {
    return false;
  }
}

/** The copy button in a code block's corner. */
class CopyWidget extends WidgetType {
  constructor(readonly code: string) {
    super();
  }
  eq(other: CopyWidget) {
    return other.code === this.code;
  }
  toDOM() {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "cm-md-copy";
    button.textContent = "Copy";
    button.setAttribute("aria-label", "Copy code block");
    button.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      void navigator.clipboard?.writeText(this.code).then(() => {
        button.textContent = "Copied";
        window.setTimeout(() => (button.textContent = "Copy"), 1200);
      });
    });
    return button;
  }
  ignoreEvent() {
    return true;
  }
}

interface Ctx {
  view: EditorView;
  state: EditorState;
  active: Set<number>;
  out: Range<Decoration>[];
}

const lineOf = (c: Ctx, pos: number) => c.state.doc.lineAt(pos);
const isActive = (c: Ctx, pos: number) => c.active.has(lineOf(c, pos).number);

/** Style `node` between its first and last marks; hide the marks off the cursor's lines. */
function wrapped(c: Ctx, node: SyntaxNodeRef, markName: string, deco: Decoration) {
  const first = node.node.firstChild;
  const last = node.node.lastChild;
  if (!first || !last || first.name !== markName || last.name !== markName || first === last) return;
  if (first.to < last.from) c.out.push(deco.range(first.to, last.from));
  if (isActive(c, node.from)) return;
  c.out.push(hide.range(first.from, first.to), hide.range(last.from, last.to));
}

function heading(c: Ctx, node: SyntaxNodeRef, level: number) {
  c.out.push(HEADING[level - 1].range(node.from, node.to));
  if (isActive(c, node.from)) return;
  const markNode = node.node.firstChild;
  if (!markNode || markNode.name !== "HeaderMark") return;
  const line = lineOf(c, node.from);
  const rest = c.state.sliceDoc(markNode.to, line.to);
  c.out.push(hide.range(markNode.from, markNode.to + (rest.length - rest.trimStart().length)));
}

function link(c: Ctx, node: SyntaxNodeRef) {
  const marks = node.node.getChildren("LinkMark");
  if (marks.length < 4) return;
  const [open, close] = marks;
  const end = marks[marks.length - 1];
  if (open.to < close.from) c.out.push(LINK.range(open.to, close.from));
  if (isActive(c, node.from)) return;
  c.out.push(hide.range(open.from, open.to), hide.range(close.from, end.to));
}

function image(c: Ctx, node: SyntaxNodeRef) {
  const marks = node.node.getChildren("LinkMark");
  if (marks.length < 4 || isActive(c, node.from)) return;
  const url = node.node.getChild("URL");
  const src = url ? c.state.sliceDoc(url.from, url.to) : "";
  if (!src) return;
  const alt = c.state.sliceDoc(marks[0].to, marks[1].from);
  c.out.push(Decoration.replace({ widget: new ImageWidget(alt, src) }).range(node.from, node.to));
}

function listItem(c: Ctx, node: SyntaxNodeRef) {
  const listMark = node.node.firstChild;
  if (!listMark || listMark.name !== "ListMark") return;
  const task = node.node.getChild("Task");
  const taskMarker = task?.getChild("TaskMarker");
  if (taskMarker) {
    const checked = /x/i.test(c.state.sliceDoc(taskMarker.from, taskMarker.to));
    if (checked) c.out.push(DONE_LINE.range(lineOf(c, node.from).from));
    // The box stands in for `- [ ]` unless the cursor is inside that marker.
    if (!cursorIn(c.view, listMark.from, taskMarker.to)) {
      c.out.push(Decoration.replace({ widget: new CheckboxWidget(checked) }).range(listMark.from, taskMarker.to));
    }
    return;
  }
  if (node.node.parent?.name === "OrderedList") {
    c.out.push(LIST_NUMBER.range(listMark.from, listMark.to));
    return;
  }
  if (!cursorIn(c.view, listMark.from, listMark.to)) {
    c.out.push(Decoration.replace({ widget: new BulletWidget() }).range(listMark.from, listMark.to));
  }
}

function blockquote(c: Ctx, node: SyntaxNodeRef) {
  const first = lineOf(c, node.from).number;
  const last = lineOf(c, node.to).number;
  for (let n = first; n <= last; n += 1) c.out.push(QUOTE_LINE.range(c.state.doc.line(n).from));
  // A quote's later lines carry their `>` inside the paragraphs it holds.
  syntaxTree(c.state).iterate({
    from: node.from,
    to: node.to,
    enter(inner) {
      if (inner.name !== "QuoteMark" || isActive(c, inner.from)) return;
      // A nested quote's marks are its own to hide.
      let owner = inner.node.parent;
      while (owner && owner.name !== "Blockquote") owner = owner.parent;
      if (owner?.from !== node.from || owner.to !== node.to) return;
      const after = c.state.sliceDoc(inner.to, inner.to + 1) === " " ? 1 : 0;
      c.out.push(hide.range(inner.from, inner.to + after));
    },
  });
}

function fencedCode(c: Ctx, node: SyntaxNodeRef) {
  const firstLine = lineOf(c, node.from);
  const lastLine = lineOf(c, node.to);
  const open = node.node.firstChild;
  const close = node.node.lastChild;
  const closed = close?.name === "CodeMark" && open !== null && close.from !== open.from;
  let inside = false;
  for (let n = firstLine.number; n <= lastLine.number; n += 1) {
    const line = c.state.doc.line(n);
    const fence = n === firstLine.number || (closed && n === lastLine.number);
    c.out.push((fence ? FENCE_LINE : CODE_LINE).range(line.from));
    if (c.active.has(n)) inside = true;
  }
  // The fence lines stay, so the block is the same height either way; off the
  // cursor only their backticks go, leaving the language as a label.
  if (!inside) {
    if (open?.name === "CodeMark") c.out.push(hide.range(open.from, open.to));
    if (closed && close) c.out.push(hide.range(close.from, close.to));
  }
  const body = node.node.getChild("CodeText");
  const code = body ? c.state.sliceDoc(body.from, body.to) : "";
  if (code) c.out.push(Decoration.widget({ widget: new CopyWidget(code), side: 1 }).range(firstLine.to));
}

function rule(c: Ctx, node: SyntaxNodeRef) {
  if (isActive(c, node.from)) return;
  c.out.push(Decoration.replace({ widget: new RuleWidget() }).range(node.from, node.to));
}

/** `[[key]]` and `![[key]]` aren't markdown, so they're found in the text,
 *  outside code. The key is styled as a link; the brackets go off the cursor's line. */
const WIKILINK = /(!?)\[\[([^\]\n]+)\]\]/g;

function wikilinks(c: Ctx, from: number, to: number) {
  const text = c.state.sliceDoc(from, to);
  for (const m of text.matchAll(WIKILINK)) {
    const start = from + (m.index ?? 0);
    const inner = syntaxTree(c.state).resolveInner(start, 1);
    if (/Code|CodeText|CodeMark/.test(inner.name) || /Code/.test(inner.parent?.name ?? "")) continue;
    const open = m[1].length + 2;
    const end = start + m[0].length;
    const target = m[2].split(/[|#]/)[0].trim();
    c.out.push(
      Decoration.mark({
        class: m[1] ? "cm-md-wikilink cm-md-embed" : "cm-md-wikilink",
        attributes: { "data-key": target },
      }).range(start + open, end - 2),
    );
    if (isActive(c, start)) continue;
    c.out.push(hide.range(start, start + open), hide.range(end - 2, end));
  }
}

function build(view: EditorView, active: Set<number> = activeLines(view)): DecorationSet {
  const c: Ctx = { view, state: view.state, active, out: [] };
  for (const { from, to } of view.visibleRanges) {
    syntaxTree(view.state).iterate({
      from,
      to,
      enter(node) {
        const level = /^ATXHeading(\d)$/.exec(node.name);
        if (level) {
          heading(c, node, Number(level[1]));
          return;
        }
        switch (node.name) {
          case "StrongEmphasis":
            wrapped(c, node, "EmphasisMark", BOLD);
            return;
          case "Emphasis":
            wrapped(c, node, "EmphasisMark", ITALIC);
            return;
          case "Strikethrough":
            wrapped(c, node, "StrikethroughMark", STRIKE);
            return;
          case "InlineCode":
            wrapped(c, node, "CodeMark", CODE);
            return false;
          case "FencedCode":
            fencedCode(c, node);
            return false;
          case "Link":
            link(c, node);
            return;
          case "Image":
            image(c, node);
            return false;
          case "ListItem":
            listItem(c, node);
            return;
          case "Blockquote":
            blockquote(c, node);
            return;
          case "HorizontalRule":
            rule(c, node);
            return;
          case "Table":
            // Drawn as a block by `tableField`.
            return false;
        }
      },
    });
    wikilinks(c, from, to);
  }
  return Decoration.set(c.out, true);
}

/**
 * Whether a mouse button is down in the editor. While it is, nothing new is
 * revealed: showing a line's syntax under the pointer mid-click moves the
 * text, so the click or drag lands somewhere other than where it was aimed.
 * What the cursor reached is revealed on release.
 */
const setPressed = StateEffect.define<boolean>();
const pressedField = StateField.define<boolean>({
  create: () => false,
  update: (value, tr) => tr.effects.find((e) => e.is(setPressed))?.value ?? value,
});

const trackPointer = ViewPlugin.fromClass(
  class {
    constructor(readonly view: EditorView) {
      this.release = this.release.bind(this);
      window.addEventListener("mouseup", this.release);
    }
    release() {
      if (this.view.state.field(pressedField)) this.view.dispatch({ effects: setPressed.of(false) });
    }
    destroy() {
      window.removeEventListener("mouseup", this.release);
    }
  },
  {
    eventHandlers: {
      mousedown(event, view) {
        if (event.button === 0) view.dispatch({ effects: setPressed.of(true) });
      },
    },
  },
);

const released = (u: ViewUpdate) =>
  u.startState.field(pressedField) && !u.state.field(pressedField);

const inlinePreview = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    /** The lines shown as source when the button went down, kept until it's up. */
    held: Set<number> | null = null;
    constructor(view: EditorView) {
      this.decorations = build(view);
    }
    update(u: ViewUpdate) {
      const pressed = u.state.field(pressedField);
      // The press arrives before the click moves the selection, so this is
      // what was showing before it.
      if (pressed && !this.held) this.held = activeLines(u.view);
      if (!pressed) this.held = null;
      const moved = u.docChanged || u.viewportChanged || u.selectionSet || u.focusChanged || released(u);
      if (!moved) return;
      // Pressed, only an edit or a scroll redraws, and with the lines it started with.
      if (pressed && !u.docChanged && !u.viewportChanged) return;
      this.decorations = build(u.view, pressed ? (this.held ?? undefined) : undefined);
    }
  },
  { decorations: (p) => p.decorations },
);

/** A GFM table as the reader sees it, until the cursor goes into its source. */
class TableWidget extends WidgetType {
  constructor(
    readonly source: string,
    readonly from: number,
  ) {
    super();
  }
  eq(other: TableWidget) {
    return other.source === this.source;
  }
  /** A row's height per line, until it's drawn and measured. */
  get estimatedHeight() {
    return (this.source.split("\n").length - 1) * 28 + 12;
  }
  toDOM(view: EditorView) {
    const rows = this.source.split("\n").map(splitRow);
    const align = (rows[1] ?? []).map((cell) =>
      cell.startsWith(":") && cell.endsWith(":") ? "center" : cell.endsWith(":") ? "right" : "left",
    );
    const table = document.createElement("table");
    table.className = "cm-md-table";
    rows.forEach((cells, i) => {
      if (i === 1) return;
      const tr = table.insertRow();
      cells.forEach((text, j) => {
        const cell = document.createElement(i === 0 ? "th" : "td");
        cell.textContent = text;
        cell.style.textAlign = align[j] ?? "left";
        tr.appendChild(cell);
      });
    });
    // Its spacing is padding on a wrapper, never margin: CodeMirror measures a
    // block by its box, and a margin it can't see puts every line below off
    // by that much, so the arrow keys would land on the wrong line.
    const wrap = document.createElement("div");
    wrap.className = "cm-md-table-wrap";
    wrap.appendChild(table);
    // A click puts the cursor in the source, which shows it for editing.
    wrap.addEventListener("mousedown", (e) => {
      e.preventDefault();
      view.dispatch({ selection: { anchor: view.posAtDOM(wrap) } });
      view.focus();
    });
    return wrap;
  }
  ignoreEvent() {
    return true;
  }
}

function splitRow(line: string): string[] {
  return line
    .trim()
    .replace(/^\||\|$/g, "")
    .split(/(?<!\\)\|/)
    .map((cell) => cell.trim());
}

function tables(state: EditorState, focused: boolean): DecorationSet {
  const builder = new RangeSetBuilder<Decoration>();
  const sel = state.selection.ranges;
  syntaxTree(state).iterate({
    enter(node) {
      if (node.name !== "Table") return;
      const from = state.doc.lineAt(node.from).from;
      const to = state.doc.lineAt(node.to).to;
      if (focused && sel.some((r) => r.from <= to && r.to >= from)) return false;
      const widget = new TableWidget(state.sliceDoc(from, to), from);
      builder.add(from, to, Decoration.replace({ widget, block: true }));
      return false;
    },
  });
  return builder.finish();
}

/** Whether the editor has focus, told to the table field, which (being state)
 *  can't ask the view: like every other line, a table shows its source only
 *  while it's being edited. */
const setFocused = StateEffect.define<boolean>();

/** Tables are whole blocks, which only a state field may replace. */
const tableField = StateField.define<{ focused: boolean; decorations: DecorationSet }>({
  create: (state) => ({ focused: false, decorations: tables(state, false) }),
  update(value, tr) {
    const told = tr.effects.find((e) => e.is(setFocused));
    const focused = told ? (told.value as boolean) : value.focused;
    const pressed = tr.state.field(pressedField);
    const releasedNow = tr.startState.field(pressedField) && !pressed;
    // A table doesn't swap between drawn and source under a held button (see `pressedField`).
    const moved = tr.docChanged || releasedNow || (!pressed && (told || tr.selection));
    if (!moved) return told ? { ...value, focused } : value;
    if (!tr.docChanged && pressed) return { ...value, focused };
    return { focused, decorations: tables(tr.state, focused) };
  },
  provide: (f) => EditorView.decorations.from(f, (v) => v.decorations),
});

const tellFocus = EditorView.domEventHandlers({
  focus: (_e, view) => {
    view.dispatch({ effects: setFocused.of(true) });
  },
  blur: (_e, view) => {
    view.dispatch({ effects: setFocused.of(false) });
  },
});

/** Live Preview, for an editor that isn't showing plain source. */
export function livePreview(): Extension {
  return [pressedField, trackPointer, inlinePreview, tableField, tellFocus];
}
