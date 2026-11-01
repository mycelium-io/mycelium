// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// `:shortcode:` emoji, as Slack and GitHub read them: `:tada:` is 🎉 and
// `:+1:` is 👍. The names are GitHub's (the `gemoji` package), loaded the first
// time a `:` is typed rather than with the app, since the list is a few hundred
// kilobytes of source. A message keeps the character, never the shortcode, so
// whoever reads it (an agent through the CLI included) sees 🎉 with nothing to
// render.
//
// A `:` starts a shortcode only at the start of a line or after whitespace, and
// never inside code, so `12:30`, `https://`, `key: value` and a code span are
// left alone.

import type { Gemoji } from "gemoji";

export interface EmojiEntry {
  emoji: string;
  /** Its shortcodes, the first one the usual one (`+1`, then `thumbsup`). */
  names: string[];
  tags: string[];
  description: string;
}

export interface EmojiTable {
  entries: EmojiEntry[];
  /** Every shortcode, lowercase, to its emoji. */
  byName: Map<string, string>;
}

export function tableFrom(list: readonly Gemoji[]): EmojiTable {
  const entries = list.map((g) => ({ emoji: g.emoji, names: g.names, tags: g.tags, description: g.description }));
  const byName = new Map<string, string>();
  for (const e of entries) for (const n of e.names) byName.set(n.toLowerCase(), e.emoji);
  return { entries, byName };
}

let table: EmojiTable | null = null;
let loading: Promise<EmojiTable> | null = null;

/** The table, loading it the first time it's asked for. A load that fails
 *  (offline, or a deploy replaced the chunk) is forgotten, so the next ask
 *  tries again rather than failing forever. */
export function loadEmoji(): Promise<EmojiTable> {
  loading ??= import("gemoji").then(
    (m) => (table = tableFrom(m.gemoji)),
    (err: unknown) => {
      loading = null;
      throw err;
    },
  );
  return loading;
}

/** `text` with its shortcodes converted, or as typed when the list can't be
 *  had: an unconverted `:tada:` beats a message that won't send. */
export async function withEmoji(
  text: string,
  t: EmojiTable | null,
  load: () => Promise<EmojiTable> = loadEmoji,
): Promise<string> {
  if (!mayHaveShortcode(text)) return text;
  try {
    return replaceShortcodes(text, t ?? (await load()));
  } catch {
    return text;
  }
}

/** The table if it has loaded, for code that can't wait (typing). */
export function emojiNow(): EmojiTable | null {
  return table;
}

/** Whether the end of `prefix` is inside code: a fenced block left open, or
 *  an inline span left open on the current line. */
export function inCode(prefix: string): boolean {
  if ((prefix.match(/```/g)?.length ?? 0) % 2 === 1) return true;
  const line = prefix.slice(prefix.lastIndexOf("\n") + 1).replace(/```/g, "");
  return (line.match(/`/g)?.length ?? 0) % 2 === 1;
}

/** The `:name` being typed at the end of `prefix`, once it's two characters
 *  long: `start` is where its `:` is. A letter must follow the `:`, or `+`/`-`
 *  for `:+1:` and `:-1:`. */
export function shortcodeAt(prefix: string): { start: number; query: string } | null {
  const m = prefix.match(/(?:^|\s):([a-z][a-z0-9_+-]*|[+-][a-z0-9_+-]*)$/i);
  if (!m || m[1].length < 2 || inCode(prefix)) return null;
  return { start: prefix.length - m[1].length - 1, query: m[1].toLowerCase() };
}

/** A whole `:name:` closing at the end of `prefix` that names an emoji. */
export function closedShortcode(prefix: string, t: EmojiTable): { start: number; emoji: string; name: string } | null {
  const m = prefix.match(/(?:^|\s):([a-z0-9_+-]+):$/i);
  if (!m) return null;
  const name = m[1].toLowerCase();
  const emoji = t.byName.get(name);
  if (!emoji) return null;
  const start = prefix.length - m[1].length - 2;
  if (inCode(prefix.slice(0, start))) return null;
  return { start, emoji, name };
}

const CLOSED = /(^|\s):([a-z0-9_+-]+):(?=$|[\s.,!?;)\]])/gim;

/** `text` with every `:name:` that names an emoji turned into it, outside code.
 *  A name it doesn't know is left as typed. */
export function replaceShortcodes(text: string, t: EmojiTable): string {
  // Split into code (fenced blocks, then inline spans) and prose; only prose changes.
  return text
    .split(/(```[\s\S]*?(?:```|$))/)
    .map((part, i) =>
      i % 2 === 1
        ? part
        : part
            .split(/(`[^`\n]*`)/)
            .map((piece, j) => (j % 2 === 1 ? piece : piece.replace(CLOSED, (all, lead: string, name: string) => {
              const emoji = t.byName.get(name.toLowerCase());
              return emoji ? `${lead}${emoji}` : all;
            })))
            .join(""),
    )
    .join("");
}

/** Whether `text` has anything `replaceShortcodes` could turn into an emoji. */
export function mayHaveShortcode(text: string): boolean {
  return /(?:^|\s):[a-z0-9_+-]+:/im.test(text);
}

export interface EmojiMatch {
  emoji: string;
  /** The shortcode the query matched (or the entry's usual one). */
  name: string;
  description: string;
}

/** Emoji people reach for most in a work chat, ahead of the rest of a match.
 *  The list itself is ordered by category, so `:ta` would offer 🍊 before 🎉. */
const COMMON = [
  "👍", "👎", "🎉", "❤️", "😂", "🚀", "👀", "🙏", "🔥", "✅", "🤔", "🙌", "👏", "💯", "😄",
  "😅", "👋", "👌", "😭", "⚠️", "❌", "✔️", "🐛", "✨", "😊", "🤦", "🫡", "💡", "📌", "⏳",
];

/**
 * Emoji for `query`, best first: the recently used among the matches, then a
 * shortcode that starts with the query (the common ones first), then one that
 * contains it, then a tag that starts with it. Within each, the list's order.
 */
export function searchEmoji(t: EmojiTable, query: string, recent: readonly string[] = [], limit = 8): EmojiMatch[] {
  const q = query.toLowerCase();
  const scored: { m: EmojiMatch; rank: number; at: number }[] = [];
  t.entries.forEach((e, at) => {
    const starts = e.names.find((n) => n.startsWith(q));
    const contains = starts ?? e.names.find((n) => n.includes(q));
    const tag = e.tags.some((g) => g.startsWith(q));
    if (!contains && !tag) return;
    const name = contains ?? e.names[0];
    const used = recent.indexOf(e.emoji);
    const common = COMMON.indexOf(e.emoji);
    const rank =
      used >= 0 ? used - recent.length : starts ? (common >= 0 ? common / COMMON.length : 1) : contains ? 2 : 3;
    scored.push({ m: { emoji: e.emoji, name, description: e.description }, rank, at });
  });
  return scored
    .sort((a, b) => a.rank - b.rank || a.at - b.at)
    .slice(0, limit)
    .map((s) => s.m);
}

// ── Recently used, in this browser ───────────────────────────────────────────

const RECENT_KEY = "mycelium.emoji.recent";
const RECENT_MAX = 24;

/** Emoji used last, newest first. */
export function readRecentEmoji(): string[] {
  try {
    const raw = window.localStorage.getItem(RECENT_KEY);
    const list: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(list) ? list.filter((e): e is string => typeof e === "string") : [];
  } catch {
    return [];
  }
}

export function recordEmoji(emoji: string): void {
  try {
    const next = [emoji, ...readRecentEmoji().filter((e) => e !== emoji)].slice(0, RECENT_MAX);
    window.localStorage.setItem(RECENT_KEY, JSON.stringify(next));
  } catch {
    // Storage full or blocked: the list just isn't remembered.
  }
}
