// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A small screen buffer that replays an ANSI byte stream and hands back HTML.
 *
 * A one-shot capture of a Rich CLI is not a flat string of styled text: Rich
 * draws spinners with `\r`, repaints Live regions by moving the cursor up, and
 * clears rows with `ESC[K`. Concatenating the runs would stack every
 * intermediate frame into the image. So the stream is replayed into a cell grid
 * and only the final state is rendered — the screenshot shows the terminal as a
 * person would have found it, not its whole redraw history.
 *
 * Scope is exactly that job: SGR, the cursor moves and erases a CLI actually
 * emits. Scrollback, alt-screen and wrapping-at-width are left to the process's
 * own `COLUMNS`.
 */

/** @typedef {{fg:any,bg:any,bold:boolean,dim:boolean,italic:boolean,underline:boolean,strike:boolean,inverse:boolean}} Style */

/** @returns {Style} */
const blank = () => ({
  fg: null,
  bg: null,
  bold: false,
  dim: false,
  italic: false,
  underline: false,
  strike: false,
  inverse: false,
});

const sameStyle = (a, b) =>
  a.bold === b.bold &&
  a.dim === b.dim &&
  a.italic === b.italic &&
  a.underline === b.underline &&
  a.strike === b.strike &&
  a.inverse === b.inverse &&
  colorKey(a.fg) === colorKey(b.fg) &&
  colorKey(a.bg) === colorKey(b.bg);

const colorKey = (c) => (c === null ? "" : typeof c === "number" ? `i${c}` : `r${c.r},${c.g},${c.b}`);

/** xterm-256 index -> rgb, for everything above the 16 themeable slots. */
function cube256(n) {
  if (n < 16) return n;
  if (n < 232) {
    const i = n - 16;
    const step = (v) => (v === 0 ? 0 : 55 + v * 40);
    return { r: step(Math.floor(i / 36) % 6), g: step(Math.floor(i / 6) % 6), b: step(i % 6) };
  }
  const v = 8 + (n - 232) * 10;
  return { r: v, g: v, b: v };
}

/**
 * Apply one SGR parameter list to `st`, in place.
 * @param {Style} st
 * @param {number[]} ps
 */
function applySgr(st, ps) {
  for (let i = 0; i < ps.length; i++) {
    const p = ps[i];
    if (p === 0) Object.assign(st, blank());
    else if (p === 1) st.bold = true;
    else if (p === 2) st.dim = true;
    else if (p === 3) st.italic = true;
    else if (p === 4) st.underline = true;
    else if (p === 7) st.inverse = true;
    else if (p === 9) st.strike = true;
    else if (p === 22) (st.bold = false), (st.dim = false);
    else if (p === 23) st.italic = false;
    else if (p === 24) st.underline = false;
    else if (p === 27) st.inverse = false;
    else if (p === 29) st.strike = false;
    else if (p >= 30 && p <= 37) st.fg = p - 30;
    else if (p === 39) st.fg = null;
    else if (p >= 40 && p <= 47) st.bg = p - 40;
    else if (p === 49) st.bg = null;
    else if (p >= 90 && p <= 97) st.fg = p - 90 + 8;
    else if (p >= 100 && p <= 107) st.bg = p - 100 + 8;
    else if (p === 38 || p === 48) {
      const target = p === 38 ? "fg" : "bg";
      if (ps[i + 1] === 5) {
        st[target] = cube256(ps[i + 2] ?? 0);
        i += 2;
      } else if (ps[i + 1] === 2) {
        st[target] = { r: ps[i + 2] ?? 0, g: ps[i + 3] ?? 0, b: ps[i + 4] ?? 0 };
        i += 4;
      }
    }
  }
}

/**
 * Replay `input` and return the final grid as rows of styled runs.
 * @param {string} input
 * @returns {{runs: {text:string, style:Style}[]}[]}
 */
export function parseAnsi(input) {
  /** @type {{ch:string, style:Style}[][]} */
  const rows = [[]];
  let row = 0;
  let col = 0;
  let st = blank();

  const rowAt = (r) => {
    while (rows.length <= r) rows.push([]);
    return rows[r];
  };
  const put = (ch) => {
    const line = rowAt(row);
    while (line.length < col) line.push({ ch: " ", style: blank() });
    line[col] = { ch, style: { ...st } };
    col++;
  };

  for (let i = 0; i < input.length; i++) {
    const ch = input[i];

    if (ch === "\x1b") {
      const next = input[i + 1];
      if (next === "[") {
        // CSI: parameters, then a final byte in @-~.
        let j = i + 2;
        let raw = "";
        while (j < input.length && !/[@-~]/.test(input[j])) raw += input[j++];
        const final = input[j];
        const ps = raw
          .replace(/^[?<>=]/, "")
          .split(";")
          .map((s) => (s === "" ? 0 : Number.parseInt(s, 10)))
          .map((n) => (Number.isNaN(n) ? 0 : n));
        const n = ps[0] || 1;

        if (final === "m" && !/^[?<>=]/.test(raw)) applySgr(st, raw === "" ? [0] : ps);
        else if (final === "A") row = Math.max(0, row - n);
        else if (final === "B") row += n;
        else if (final === "C") col += n;
        else if (final === "D") col = Math.max(0, col - n);
        else if (final === "E") (row += n), (col = 0);
        else if (final === "F") (row = Math.max(0, row - n)), (col = 0);
        else if (final === "G") col = Math.max(0, n - 1);
        else if (final === "H" || final === "f") {
          row = Math.max(0, (ps[0] || 1) - 1);
          col = Math.max(0, (ps[1] || 1) - 1);
        } else if (final === "K") {
          const line = rowAt(row);
          if (ps[0] === 1) for (let k = 0; k <= col && k < line.length; k++) line[k] = { ch: " ", style: blank() };
          else if (ps[0] === 2) line.length = 0;
          else line.length = Math.min(line.length, col);
        } else if (final === "J") {
          if (ps[0] === 2 || ps[0] === 3) {
            rows.length = 1;
            rows[0] = [];
            row = 0;
            col = 0;
          } else rows.length = row + 1;
        }
        i = j;
        continue;
      }
      if (next === "]") {
        // OSC — window titles, hyperlinks. Dropped; the link text survives
        // because it sits between the two OSC 8 wrappers, not inside them.
        let j = i + 2;
        while (j < input.length && !(input[j] === "\x07" || (input[j] === "\x1b" && input[j + 1] === "\\"))) j++;
        i = input[j] === "\x1b" ? j + 1 : j;
        continue;
      }
      i++; // lone two-byte escape
      continue;
    }

    if (ch === "\n") (row += 1), (col = 0);
    else if (ch === "\r") col = 0;
    else if (ch === "\b") col = Math.max(0, col - 1);
    else if (ch === "\t") {
      const stop = col + (8 - (col % 8));
      while (col < stop) put(" ");
    } else if (ch === "\x07" || ch === "\x00") continue;
    else put(ch);
  }

  // Trailing blank rows are an artifact of the final newline, not content.
  while (rows.length > 1 && rows[rows.length - 1].length === 0) rows.pop();

  return rows.map((line) => {
    /** @type {{text:string, style:Style}[]} */
    const runs = [];
    for (const cell of line) {
      const last = runs[runs.length - 1];
      if (last && sameStyle(last.style, cell.style)) last.text += cell.ch;
      else runs.push({ text: cell.ch, style: cell.style });
    }
    return { runs };
  });
}

const escapeHtml = (s) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/**
 * Render parsed rows to HTML using a theme's 16 ANSI slots.
 * @param {string} input raw stream, escapes included
 * @param {ReturnType<import("./theme.mjs").palette>} pal
 * @returns {{html:string, rows:number, cols:number}}
 */
export function ansiToHtml(input, pal) {
  const rows = parseAnsi(input);
  const resolve = (c, bright) => {
    if (c === null) return null;
    if (typeof c === "number") return pal.ansi[bright && c < 8 ? c + 8 : c];
    return `rgb(${c.r},${c.g},${c.b})`;
  };

  let cols = 0;
  const lines = rows.map(({ runs }) => {
    let width = 0;
    const spans = runs.map(({ text, style }) => {
      width += text.length;
      let fg = resolve(style.fg, style.bold);
      let bg = resolve(style.bg, false);
      if (style.inverse) {
        const f = fg ?? pal.text;
        const b = bg ?? pal.paper;
        fg = b;
        bg = f;
      }
      const css = [];
      if (fg) css.push(`color:${fg}`);
      if (bg) css.push(`background:${bg}`);
      if (style.bold) css.push("font-weight:600");
      if (style.dim) css.push("opacity:.62");
      if (style.italic) css.push("font-style:italic");
      const deco = [style.underline && "underline", style.strike && "line-through"].filter(Boolean);
      if (deco.length) css.push(`text-decoration:${deco.join(" ")}`);
      const body = escapeHtml(text);
      return css.length ? `<span style="${css.join(";")}">${body}</span>` : body;
    });
    cols = Math.max(cols, width);
    // A zero-width joiner keeps an empty row at full line-height.
    return spans.join("") || "&#8203;";
  });

  return { html: lines.join("\n"), rows: rows.length, cols };
}

/** Drop every escape sequence — used for width math and `--json` echoes. */
export function stripAnsi(s) {
  return s.replace(/\x1b\[[0-9;?<>=]*[@-~]/g, "").replace(/\x1b\][^\x07\x1b]*(\x07|\x1b\\)/g, "");
}
