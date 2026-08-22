// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** The terminal card: a replayed ANSI stream under an optional prompt line. */

import { ansiToHtml } from "./ansi.mjs";
import { cardDocument, escapeHtml } from "./card.mjs";
import { palette } from "./theme.mjs";

/**
 * @typedef {import("./card.mjs").CardOptions & {
 *   output: string,
 *   command?: string,
 *   prompt?: string,
 *   exitCode?: number,
 *   showExit?: boolean,
 * }} TerminalOptions
 */

/**
 * @param {TerminalOptions} opts
 * @returns {{html:string, rows:number, cols:number}}
 */
export function terminalDocument(opts) {
  const theme = opts.theme ?? "dark";
  const pal = palette(theme);
  const rendered = ansiToHtml(opts.output ?? "", pal);

  const parts = [];
  if (opts.command) {
    const sigil = opts.prompt ?? "❯";
    parts.push(
      `<span class="sigil">${escapeHtml(sigil)}</span> <span class="cmd">${escapeHtml(opts.command)}</span>`,
    );
  }
  parts.push(rendered.html);
  if (opts.showExit && opts.exitCode) {
    parts.push(`<span class="exit">exit ${opts.exitCode}</span>`);
  }

  const extraCss = `
.sigil{color:${pal.accent};font-weight:600}
.cmd{color:${pal.text};font-weight:600}
.exit{color:${pal.red};opacity:.85}
`;

  // The prompt line adds a row; the command adds to the widest line.
  const promptCols = opts.command ? opts.command.length + 2 : 0;
  return {
    html: cardDocument(parts.join("\n"), { ...opts, theme }, extraCss),
    rows: rendered.rows + (opts.command ? 1 : 0) + (opts.showExit && opts.exitCode ? 1 : 0),
    cols: Math.max(rendered.cols, promptCols),
  };
}
