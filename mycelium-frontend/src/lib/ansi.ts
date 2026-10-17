// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A terminal screen with its colors (ANSI SGR escapes, as `herdr pane read
 * --format ansi` gives it) split into lines of styled runs, to draw as text.
 *
 * Only color and weight are kept: a screen snapshot is already laid out, so
 * cursor moves and other control sequences are dropped rather than run.
 */

export interface AnsiStyle {
  fg?: string;
  bg?: string;
  bold?: boolean;
  dim?: boolean;
  italic?: boolean;
  underline?: boolean;
  inverse?: boolean;
}

export interface AnsiRun {
  text: string;
  style: AnsiStyle;
}

/** The 16 base colors, as the agents terminal in the desktop app draws them. */
const BASE16 = [
  "#1d1f21", "#cc6666", "#b5bd68", "#f0c674", "#81a2be", "#b294bb", "#8abeb7", "#c5c8c6",
  "#666666", "#d54e53", "#b9ca4a", "#e7c547", "#7aa6da", "#c397d8", "#70c0b1", "#eaeaea",
];

/** A 256-color index as CSS. */
export function color256(n: number): string {
  if (n < 16) return BASE16[n];
  if (n < 232) {
    const i = n - 16;
    const level = (v: number) => (v === 0 ? 0 : 55 + v * 40);
    return `rgb(${level(Math.floor(i / 36))}, ${level(Math.floor(i / 6) % 6)}, ${level(i % 6)})`;
  }
  const grey = 8 + (n - 232) * 10;
  return `rgb(${grey}, ${grey}, ${grey})`;
}

/** Apply one SGR sequence's parameters to `style`, returning the new style. */
function applySgr(style: AnsiStyle, params: number[]): AnsiStyle {
  let next = { ...style };
  for (let i = 0; i < params.length; i += 1) {
    const p = params[i];
    if (p === 0) next = {};
    else if (p === 1) next.bold = true;
    else if (p === 2) next.dim = true;
    else if (p === 3) next.italic = true;
    else if (p === 4) next.underline = true;
    else if (p === 7) next.inverse = true;
    else if (p === 22) next.bold = next.dim = undefined;
    else if (p === 23) next.italic = undefined;
    else if (p === 24) next.underline = undefined;
    else if (p === 27) next.inverse = undefined;
    else if (p >= 30 && p <= 37) next.fg = BASE16[p - 30];
    else if (p >= 90 && p <= 97) next.fg = BASE16[p - 90 + 8];
    else if (p === 39) next.fg = undefined;
    else if (p >= 40 && p <= 47) next.bg = BASE16[p - 40];
    else if (p >= 100 && p <= 107) next.bg = BASE16[p - 100 + 8];
    else if (p === 49) next.bg = undefined;
    else if (p === 38 || p === 48) {
      const key = p === 38 ? "fg" : "bg";
      if (params[i + 1] === 5 && params[i + 2] !== undefined) {
        next[key] = color256(params[i + 2]);
        i += 2;
      } else if (params[i + 1] === 2 && params[i + 4] !== undefined) {
        next[key] = `rgb(${params[i + 2]}, ${params[i + 3]}, ${params[i + 4]})`;
        i += 4;
      }
    }
  }
  return next;
}

// An escape sequence: CSI (ESC [ … final), OSC (ESC ] … BEL or ST), or a lone ESC + one char.
const ESCAPE = /\x1b\[([0-9;?]*)([@-~])|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]/g;

/** Split `screen` into lines of styled runs. */
export function parseAnsi(screen: string): AnsiRun[][] {
  const lines: AnsiRun[][] = [[]];
  let style: AnsiStyle = {};
  const push = (text: string) => {
    const parts = text.replace(/\r\n?/g, "\n").split("\n");
    parts.forEach((part, i) => {
      if (i > 0) lines.push([]);
      const visible = part.replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
      if (visible) lines[lines.length - 1].push({ text: visible, style });
    });
  };
  let last = 0;
  for (const match of screen.matchAll(ESCAPE)) {
    push(screen.slice(last, match.index));
    last = match.index + match[0].length;
    if (match[2] === "m") {
      const params = (match[1] || "0").split(";").map((n) => Number.parseInt(n || "0", 10));
      style = applySgr(style, params);
    }
  }
  push(screen.slice(last));
  // A screen that ends in a newline has no last line of its own.
  if (lines.length > 1 && lines[lines.length - 1].length === 0) lines.pop();
  return lines;
}
