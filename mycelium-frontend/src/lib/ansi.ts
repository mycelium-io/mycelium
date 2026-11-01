// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A terminal snapshot's colors, read into runs of text a page can draw. The
// snapshot is what herdr shows of an agent's screen (`pane read --format
// ansi`): lines of text with SGR codes (`ESC[...m`) for color and weight.
// Only those are read; any other escape is dropped, so nothing in a screen
// can move the cursor, set a title or reach the page as markup.

export interface AnsiStyle {
  /** A CSS color, or null for the terminal's own. */
  fg: string | null;
  bg: string | null;
  bold: boolean;
  dim: boolean;
  italic: boolean;
  underline: boolean;
  inverse: boolean;
}

export interface AnsiRun {
  text: string;
  style: AnsiStyle;
}

const PLAIN: AnsiStyle = {
  fg: null,
  bg: null,
  bold: false,
  dim: false,
  italic: false,
  underline: false,
  inverse: false,
};

/** The 16 base colors, as the app's own terminal (xterm.js) draws them by default. */
const BASE = [
  "#2e3436",
  "#cc0000",
  "#4e9a06",
  "#c4a000",
  "#3465a4",
  "#75507b",
  "#06989a",
  "#d3d7cf",
  "#555753",
  "#ef2929",
  "#8ae234",
  "#fce94f",
  "#729fcf",
  "#ad7fa8",
  "#34e2e2",
  "#eeeeec",
];

/** One of the 256 colors: the 16 base ones, a 6x6x6 cube, then 24 grays. */
export function color256(n: number): string {
  if (n < 16) return BASE[n];
  if (n < 232) {
    const c = n - 16;
    const level = (v: number) => (v === 0 ? 0 : 55 + v * 40);
    return rgb(level(Math.floor(c / 36)), level(Math.floor(c / 6) % 6), level(c % 6));
  }
  const g = 8 + (n - 232) * 10;
  return rgb(g, g, g);
}

function rgb(r: number, g: number, b: number): string {
  return `rgb(${r}, ${g}, ${b})`;
}

/**
 * A solid `#rgb`, `#rrggbb` or `rgb()`/`rgba()` color as its channels; null
 * for anything else. A translucent one is null too: what it looks like depends
 * on what's under it (a glass theme's background over a dark page), so it
 * can't be said to be light or dark.
 */
export function channels(color: string): [number, number, number] | null {
  const hex = color.trim().match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (hex) {
    const h = hex[1].length === 3 ? [...hex[1]].map((c) => c + c).join("") : hex[1];
    return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)) as [number, number, number];
  }
  const fn = color
    .trim()
    .match(/^rgba?\(\s*(\d+)[\s,]+(\d+)[\s,]+(\d+)\s*(?:[,/]\s*([\d.]+)(%?))?\s*\)$/i);
  if (!fn) return null;
  const alpha = fn[4] === undefined ? 1 : Number(fn[4]) / (fn[5] ? 100 : 1);
  return alpha < 1 ? null : [Number(fn[1]), Number(fn[2]), Number(fn[3])];
}

function luminance([r, g, b]: [number, number, number]): number {
  const lin = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: [number, number, number], b: [number, number, number]): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

/** The contrast a terminal color needs against what it's drawn on (WCAG's for body text). */
export const MIN_CONTRAST = 4.5;

/**
 * `fg` as it can be read on `bg`: unchanged when it already can, else moved
 * toward black on a light background or white on a dark one, only as far as
 * it takes. A terminal's colors are picked for its own background, usually a
 * dark one, so white or pale green text would vanish on a light page. Colors
 * it can't read are left as they are.
 */
export function readable(fg: string, bg: string): string {
  const f = channels(fg);
  const b = channels(bg);
  if (!f || !b || contrast(f, b) >= MIN_CONTRAST) return fg;
  const to = luminance(b) > 0.5 ? 0 : 255;
  for (let step = 1; step <= 20; step++) {
    const t = step / 20;
    const mixed = f.map((v) => Math.round(v + (to - v) * t)) as [number, number, number];
    if (contrast(mixed, b) >= MIN_CONTRAST) return rgb(...mixed);
  }
  return rgb(to, to, to);
}

/** Apply one SGR sequence's parameters to `style`. */
function apply(style: AnsiStyle, params: number[]): AnsiStyle {
  const next = { ...style };
  for (let i = 0; i < params.length; i++) {
    const p = params[i];
    if (p === 0) Object.assign(next, PLAIN);
    else if (p === 1) next.bold = true;
    else if (p === 2) next.dim = true;
    else if (p === 3) next.italic = true;
    else if (p === 4) next.underline = true;
    else if (p === 7) next.inverse = true;
    else if (p === 22) next.bold = next.dim = false;
    else if (p === 23) next.italic = false;
    else if (p === 24) next.underline = false;
    else if (p === 27) next.inverse = false;
    else if (p >= 30 && p <= 37) next.fg = BASE[p - 30];
    else if (p === 39) next.fg = null;
    else if (p >= 40 && p <= 47) next.bg = BASE[p - 40];
    else if (p === 49) next.bg = null;
    else if (p >= 90 && p <= 97) next.fg = BASE[p - 90 + 8];
    else if (p >= 100 && p <= 107) next.bg = BASE[p - 100 + 8];
    else if (p === 38 || p === 48) {
      // 38;5;n or 38;2;r;g;b (and 48 for the background).
      let value: string | null = null;
      if (params[i + 1] === 5 && params[i + 2] !== undefined) {
        value = color256(params[i + 2] & 255);
        i += 2;
      } else if (params[i + 1] === 2 && params[i + 4] !== undefined) {
        value = rgb(params[i + 2] & 255, params[i + 3] & 255, params[i + 4] & 255);
        i += 4;
      }
      if (value) next[p === 38 ? "fg" : "bg"] = value;
    }
  }
  return next;
}

// An SGR sequence, then any other CSI or OSC sequence, then a lone ESC.
const ESCAPES = /\x1b\[([0-9;]*)m|\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b./g;

/** A snapshot's lines, each as its runs of styled text. */
export function parseAnsi(snapshot: string): AnsiRun[][] {
  const lines: AnsiRun[][] = [];
  let style = PLAIN;
  // Carriage returns come with each newline in a snapshot; on their own they'd overwrite.
  for (const line of snapshot.replace(/\r\n?/g, "\n").split("\n")) {
    const runs: AnsiRun[] = [];
    let at = 0;
    const push = (text: string) => {
      // Other control characters are dropped, and a tab keeps its place.
      const clean = text.replace(/\t/g, "    ").replace(/[\x00-\x08\x0b-\x1f\x7f]/g, "");
      if (!clean) return;
      const last = runs[runs.length - 1];
      if (last && last.style === style) last.text += clean;
      else runs.push({ text: clean, style });
    };
    for (const m of line.matchAll(ESCAPES)) {
      push(line.slice(at, m.index));
      at = (m.index ?? 0) + m[0].length;
      if (m[1] !== undefined) {
        const params = m[1] === "" ? [0] : m[1].split(";").map((s) => (s === "" ? 0 : Number(s)));
        style = apply(style, params);
      }
    }
    push(line.slice(at));
    lines.push(runs);
  }
  // A snapshot ends with a newline; that's not a line of its own.
  while (lines.length > 0 && lines[lines.length - 1].length === 0) lines.pop();
  return lines;
}
