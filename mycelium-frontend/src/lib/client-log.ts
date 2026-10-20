// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What `/api/client-log` writes to this server's output, and how much.
 * SERVER-SIDE only.
 *
 * People and agents read the app's log when something breaks, so a line from
 * a page is held to one line of plain text (no control character, line break
 * or direction mark can draw a line of its own), and to LINES_PER_SECOND a
 * second and LINES_PER_MINUTE a minute, with what's dropped counted on the next
 * line written.
 */

export const MAX_CHARS = 4_000;
export const LINES_PER_SECOND = 5;
export const LINES_PER_MINUTE = 60;

/** Unicode's line and paragraph separators, which break a line like a newline. */
const BREAKS = /\r\n|\r|\n|\u{2028}|\u{2029}/gu;
/** C0 and C1 controls, and Unicode's direction marks and overrides. */
const CONTROL = /[\u{0}-\u{1f}\u{7f}-\u{9f}\u{200e}\u{200f}\u{202a}-\u{202e}\u{2066}-\u{2069}]/gu;

/** `line` as one line of plain text: its line breaks read as " | ". */
export function plainLine(line: string): string {
  return line.replace(BREAKS, " | ").replace(CONTROL, "").slice(0, MAX_CHARS).trim();
}

/** When lines were written, oldest first, for the limits above. */
const written: number[] = [];
let dropped = 0;

/**
 * The line to write for `line` at `now`, with any dropped before it counted,
 * or `null` when a limit is reached (it's counted as dropped).
 */
export function admit(line: string, now: number = Date.now()): string | null {
  while (written.length > 0 && now - written[0] >= 60_000) written.shift();
  const lastSecond = written.filter((t) => now - t < 1_000).length;
  if (lastSecond >= LINES_PER_SECOND || written.length >= LINES_PER_MINUTE) {
    dropped += 1;
    return null;
  }
  written.push(now);
  const note = dropped > 0 ? ` (${dropped} earlier line${dropped === 1 ? "" : "s"} dropped)` : "";
  dropped = 0;
  return `[page] ${line}${note}`;
}

/** Forget what was written. For tests. */
export function resetClientLog(): void {
  written.length = 0;
  dropped = 0;
}
