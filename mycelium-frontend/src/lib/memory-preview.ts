// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { Memory } from "@/lib/api";

/** Plain text for a memory's value: prose as written, anything else as JSON. */
export function memoryValueText(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "object" && value !== null) {
    const obj = value as Record<string, unknown>;
    if (typeof obj.text === "string") return obj.text;
    return JSON.stringify(value, null, 0);
  }
  return String(value);
}

// The hovercard shows an excerpt, not a rendered document: markdown syntax is
// flattened to the text it decorates so a cut-off construct can't leave a
// dangling marker on screen.
function flattenLine(line: string): string {
  return line
    .replace(/^\s{0,3}#{1,6}\s+/, "")
    .replace(/^\s{0,3}>\s?/, "")
    .replace(/^\s{0,3}([-*+]|\d+\.)\s+/, "• ")
    .replace(/!?\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g, (_m, key, alias) => alias || key)
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, (_m, text) => text)
    .replace(/`([^`]*)`/g, "$1")
    .replace(/(\*\*|__)(.+?)\1/g, "$2")
    .replace(/(\*|_)(.+?)\1/g, "$2")
    .trim();
}

/** Markdown flattened to plain lines: fences dropped, blank runs collapsed.
 *  Stops once `limit` lines are in hand, so a huge body isn't walked in full. */
export function flattenMarkdown(body: string, limit = Infinity): string[] {
  const lines: string[] = [];
  let inFence = false;
  for (const raw of body.split("\n")) {
    if (lines.length > limit) break;
    if (/^\s*(```|~~~)/.test(raw)) {
      inFence = !inFence;
      continue;
    }
    if (inFence) {
      lines.push(raw.trim());
      continue;
    }
    // A setext underline or a horizontal rule is decoration with no text.
    if (/^\s*([-*_=])\1{2,}\s*$/.test(raw)) continue;
    const line = flattenLine(raw);
    if (!line && (lines.length === 0 || lines[lines.length - 1] === "")) continue;
    lines.push(line);
  }
  while (lines.length > 0 && lines[lines.length - 1] === "") lines.pop();
  return lines;
}

export interface MemoryPreview {
  /** The body's leading lines, as many as `maxLines`. How many of them are
   *  actually *visible* is the card's CSS to decide, not this function's. */
  lines: string[];
  /** True when the body has more lines than the excerpt carries. */
  truncated: boolean;
  /** True when there is no body at all — the card shows a placeholder. */
  empty: boolean;
}

/** Lines of the source document, not of the rendered card: a content-shaped
 *  budget, generous enough that CSS is what runs out of room first. */
const MAX_LINES = 14;

/** Never hand the DOM an unbounded string. Far past anything the card's own
 *  clamp leaves visible, so this only ever trims a pathological body. */
const LINE_PAYLOAD_CAP = 2000;

/** A short excerpt of a memory's body for the rail hovercard. */
export function memoryPreview(
  memory: Pick<Memory, "value" | "content_text">,
  { maxLines = MAX_LINES } = {},
): MemoryPreview {
  const body = memoryValueText(memory.value) || memory.content_text || "";
  const all = flattenMarkdown(body, maxLines);
  if (all.length === 0) return { lines: [], truncated: false, empty: true };

  return {
    lines: all.slice(0, maxLines).map(line => line.slice(0, LINE_PAYLOAD_CAP)),
    truncated: all.length > maxLines,
    empty: false,
  };
}

/** Vertical placement for a card anchored to a row, clamped to the viewport. */
export function previewCardTop(
  anchorTop: number,
  anchorHeight: number,
  cardHeight: number,
  viewportHeight: number,
  margin = 12,
): number {
  const centered = anchorTop + anchorHeight / 2 - cardHeight / 2;
  const lowest = viewportHeight - cardHeight - margin;
  if (lowest < margin) return margin;
  return Math.min(Math.max(centered, margin), lowest);
}
