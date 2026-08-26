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

const TITLE_MAX = 120;

/** The mapping a structured value is, or null when the value is prose. */
function structuredValue(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

/** The first line with something on it, stripped of its heading marker. */
function firstLine(text: string): string {
  const line = text.split("\n").map(l => l.trim()).find(l => l && !l.startsWith("---"));
  return (line ?? "").replace(/^#+\s*/, "").slice(0, TITLE_MAX);
}

/**
 * What a memory is called.
 *
 * One derivation, because a task is a board row *and* a thread and the two must
 * not disagree about its name: a structured value's own `title`, else the first
 * readable line of the body, else the key.
 *
 * The body is whichever way the store hands it over. Prose lives in the
 * markdown body and the API value is rebuilt from it, so a prose memory arrives
 * as `{text: …}` rather than as a bare string — a reader that understands only
 * the string falls through to the key and prints a slug where the room expects
 * a name.
 */
export function memoryTitle(memory: Pick<Memory, "key" | "value" | "content_text">): string {
  const structured = structuredValue(memory.value);
  const explicit = structured?.title;
  if (typeof explicit === "string" && explicit.trim()) return explicit.trim().slice(0, TITLE_MAX);
  const body =
    typeof memory.value === "string"
      ? memory.value
      : typeof structured?.text === "string"
        ? structured.text
        : memory.content_text ?? "";
  return firstLine(body) || memory.key;
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

/** Markdown flattened to plain lines: fences dropped, blank runs collapsed. */
export function flattenMarkdown(body: string): string[] {
  const lines: string[] = [];
  let inFence = false;
  for (const raw of body.split("\n")) {
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
  /** Excerpt lines, already clipped to the line and character budgets. */
  lines: string[];
  /** True when the body ran past the budget, so the card can say so. */
  truncated: boolean;
  /** True when there is no body at all — the card shows a placeholder. */
  empty: boolean;
}

const MAX_LINES = 12;
const MAX_CHARS = 520;

/** A short excerpt of a memory's body for the rail hovercard. */
export function memoryPreview(
  memory: Pick<Memory, "value" | "content_text">,
  { maxLines = MAX_LINES, maxChars = MAX_CHARS } = {},
): MemoryPreview {
  const body = memoryValueText(memory.value) || memory.content_text || "";
  const all = flattenMarkdown(body);
  if (all.length === 0) return { lines: [], truncated: false, empty: true };

  const lines: string[] = [];
  let used = 0;
  let truncated = false;
  for (const line of all.slice(0, maxLines)) {
    const room = maxChars - used;
    if (room <= 0) {
      truncated = true;
      break;
    }
    if (line.length > room) {
      lines.push(`${clipAtWord(line, room)}…`);
      truncated = true;
      break;
    }
    lines.push(line);
    used += line.length + 1;
  }
  return { lines, truncated: truncated || lines.length < all.length, empty: false };
}

function clipAtWord(line: string, limit: number): string {
  const head = line.slice(0, limit);
  const space = head.lastIndexOf(" ");
  return (space > limit * 0.6 ? head.slice(0, space) : head).trimEnd();
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
