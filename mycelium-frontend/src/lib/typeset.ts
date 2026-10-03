// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Typographic punctuation for prose as it is drawn, never as it is stored.
 *
 * Agents type on a keyboard's marks: straight quotes, three periods, two
 * hyphens. Drawn as-is in a proportional face they read as typed rather than
 * set. So the text a message shows gets curly quotes and apostrophes and an
 * ellipsis (two hyphens stay two hyphens), and the
 * markdown it came from is left alone: copying still gives what was written.
 *
 * Only prose comes through here. Code spans and blocks are skipped by the
 * renderer, so a quote inside `code` is never touched.
 */

/** A character after which a quote opens rather than closes. */
const OPENS_AFTER = /[\s([{—–/-]/;

/** Curly quotes and apostrophes, and an ellipsis for three periods. */
export function typeset(text: string): string {
  let out = "";
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c !== '"' && c !== "'") {
      out += c;
      continue;
    }
    const before = i === 0 ? "" : text[i - 1];
    const after = text[i + 1] ?? "";
    // At the start of a run the mark opens only when a word follows it; a run
    // can begin right after bold or a link, where a closing quote is common.
    const opens = (before === "" ? /\S/.test(after) : OPENS_AFTER.test(before)) && after !== "";
    if (c === '"') out += opens ? "“" : "”";
    else out += opens && /[A-Za-z]/.test(after) ? "‘" : "’";
  }
  return out.replace(/(?<!\.)\.\.\.(?!\.)/g, "…");
}
