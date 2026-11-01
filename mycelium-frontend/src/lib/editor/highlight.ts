// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { HighlightStyle, syntaxHighlighting } from "@codemirror/language";
import type { Extension } from "@codemirror/state";
import { tags as t } from "@lezer/highlight";

/**
 * Colors for code, in the app's own palette so they follow light and dark.
 * Only code's tags are styled here: Live Preview draws the markdown itself,
 * and a style for markdown's tags would fight it.
 */
const code = HighlightStyle.define([
  { tag: [t.keyword, t.controlKeyword, t.moduleKeyword, t.operatorKeyword], color: "var(--accent)" },
  { tag: [t.string, t.special(t.string), t.regexp], color: "var(--green)" },
  { tag: [t.number, t.bool, t.null, t.atom], color: "var(--yellow)" },
  { tag: [t.comment, t.lineComment, t.blockComment], color: "var(--faint)", fontStyle: "italic" },
  { tag: [t.function(t.variableName), t.function(t.propertyName)], color: "var(--text)", fontWeight: "600" },
  { tag: [t.typeName, t.className, t.tagName], color: "var(--yellow)" },
  { tag: [t.propertyName, t.attributeName], color: "var(--muted-foreground)" },
  { tag: t.invalid, color: "var(--red)" },
]);

/**
 * The plain source, readable: the syntax that Live Preview would hide is
 * dimmed, and what it would draw keeps a hint of its weight.
 */
const source = HighlightStyle.define([
  { tag: [t.processingInstruction, t.meta, t.contentSeparator], color: "var(--faint)" },
  { tag: t.heading, fontWeight: "600" },
  { tag: t.strong, fontWeight: "600" },
  { tag: t.emphasis, fontStyle: "italic" },
  { tag: t.strikethrough, textDecoration: "line-through" },
  { tag: [t.link, t.url], color: "var(--accent)" },
  { tag: t.monospace, color: "var(--muted-foreground)" },
  { tag: t.quote, color: "var(--muted-foreground)" },
]);

export function codeHighlighting(): Extension {
  return syntaxHighlighting(code);
}

export function sourceHighlighting(): Extension {
  return syntaxHighlighting(source);
}
