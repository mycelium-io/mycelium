// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The code card: highlight.js tokens painted with the frontend's own palette.
 *
 * `lib/common` rather than the full build — it carries the ~40 languages this
 * repo actually contains and loads in a fraction of the time, which matters
 * because the load lands on somebody's first shot. An unknown language falls
 * back to plain text rather than pulling the full grammar set in.
 */

import { readFile } from "node:fs/promises";
import { basename, extname } from "node:path";
import { cardDocument, escapeHtml } from "./card.mjs";
import { palette } from "./theme.mjs";

let hljsPromise = null;
async function loadHljs() {
  if (!hljsPromise) {
    hljsPromise = import("highlight.js/lib/common")
      .then((m) => m.default ?? m)
      .catch(() => null);
  }
  return hljsPromise;
}

/** Extensions the repo uses that highlight.js does not map on its own. */
const EXT_LANG = {
  ".mjs": "javascript",
  ".cjs": "javascript",
  ".ts": "typescript",
  ".tsx": "typescript",
  ".jsx": "javascript",
  ".py": "python",
  ".toml": "ini",
  ".yml": "yaml",
  ".yaml": "yaml",
  ".json": "json",
  ".md": "markdown",
  ".sh": "bash",
  ".bash": "bash",
  ".rs": "rust",
  ".go": "go",
  ".css": "css",
  ".html": "xml",
  ".sql": "sql",
  ".dockerfile": "dockerfile",
};

/** @param {string} file */
export function guessLanguage(file) {
  const name = basename(file).toLowerCase();
  if (name === "dockerfile") return "dockerfile";
  if (name === "makefile") return "makefile";
  return EXT_LANG[extname(name)] ?? null;
}

/**
 * Split highlight.js output on newlines without breaking its markup: a comment
 * or string span legitimately runs across lines, so every open tag is closed at
 * the break and reopened on the next row.
 * @param {string} html
 * @returns {string[]}
 */
export function splitHighlightedLines(html) {
  /** @type {string[]} */
  const lines = [];
  /** @type {string[]} */
  const open = [];
  let current = "";
  const re = /<\/?span[^>]*>/g;
  let last = 0;

  const pushText = (text) => {
    const chunks = text.split("\n");
    chunks.forEach((chunk, i) => {
      if (i > 0) {
        current += open.map(() => "</span>").join("");
        lines.push(current);
        current = open.join("");
      }
      current += chunk;
    });
  };

  let m;
  while ((m = re.exec(html)) !== null) {
    pushText(html.slice(last, m.index));
    if (m[0].startsWith("</")) {
      open.pop();
      current += m[0];
    } else {
      open.push(m[0]);
      current += m[0];
    }
    last = m.index + m[0].length;
  }
  pushText(html.slice(last));
  lines.push(current);
  return lines;
}

/** @param {"dark"|"light"} theme */
function syntaxCss(theme) {
  const pal = palette(theme);
  const type = theme === "dark" ? "#65e2d7" : "#0f8c99";
  const keyword = theme === "dark" ? "#ea8cc2" : "#c02f86";
  const builtin = theme === "dark" ? "#8a92ea" : "#3c48c8";
  return `
.hljs-comment,.hljs-quote{color:${pal.faint};font-style:italic}
.hljs-doctag{color:${pal.faint}}
.hljs-keyword,.hljs-selector-tag,.hljs-operator,.hljs-literal-keyword{color:${keyword}}
.hljs-string,.hljs-char\\.escape_,.hljs-regexp,.hljs-addition{color:${pal.green}}
.hljs-number,.hljs-literal,.hljs-symbol,.hljs-bullet{color:${pal.yellow}}
.hljs-title,.hljs-title\\.function_,.hljs-section,.hljs-name{color:${pal.accent}}
.hljs-title\\.class_,.hljs-type,.hljs-class .hljs-title{color:${type}}
.hljs-built_in,.hljs-selector-id,.hljs-selector-class{color:${builtin}}
.hljs-attr,.hljs-attribute,.hljs-property,.hljs-variable,.hljs-template-variable{color:${pal.text}}
.hljs-params{color:${pal.muted}}
.hljs-meta{color:${pal.muted}}
.hljs-tag{color:${pal.muted}}
.hljs-deletion{color:${pal.red}}
.hljs-emphasis{font-style:italic}
.hljs-strong{font-weight:700}
.hljs-link{color:${pal.accent};text-decoration:underline}
.row{display:block}
.num{
  display:inline-block;width:${"3ch"};margin-right:1.6ch;text-align:right;
  color:${pal.faint};user-select:none;
}
.row.hl{background:${pal.accentSoft};box-shadow:inset 2px 0 0 ${pal.accent};margin:0 -18px;padding:0 18px 0 16px}
`;
}

/**
 * @typedef {import("./card.mjs").CardOptions & {
 *   code?: string,
 *   file?: string,
 *   lang?: string,
 *   lineNumbers?: boolean,
 *   startLine?: number,
 *   highlight?: number[],
 *   range?: [number, number],
 * }} CodeOptions
 */

/**
 * @param {CodeOptions} opts
 * @returns {Promise<{html:string, rows:number, cols:number, lang:string}>}
 */
export async function codeDocument(opts) {
  const theme = opts.theme ?? "dark";
  let source = opts.code;
  if (source === undefined && opts.file) source = await readFile(opts.file, "utf8");
  source = (source ?? "").replace(/\n+$/, "");

  let startLine = opts.startLine ?? 1;
  if (opts.range) {
    const all = source.split("\n");
    const [from, to] = opts.range;
    source = all.slice(Math.max(0, from - 1), to).join("\n");
    startLine = from;
  }

  const lang = opts.lang ?? (opts.file ? guessLanguage(opts.file) : null);
  const hljs = await loadHljs();
  let highlighted;
  let usedLang = "plaintext";
  if (hljs && lang && hljs.getLanguage(lang)) {
    highlighted = hljs.highlight(source, { language: lang, ignoreIllegals: true }).value;
    usedLang = lang;
  } else if (hljs && !lang) {
    const auto = hljs.highlightAuto(source);
    highlighted = auto.value;
    usedLang = auto.language ?? "plaintext";
  } else {
    highlighted = escapeHtml(source);
  }

  const lines = splitHighlightedLines(highlighted);
  const marked = new Set(opts.highlight ?? []);
  const gutter = opts.lineNumbers !== false;
  const width = String(startLine + lines.length - 1).length;

  const body = lines
    .map((line, i) => {
      const n = startLine + i;
      const num = gutter
        ? `<span class="num" style="width:${width}ch">${n}</span>`
        : "";
      const cls = marked.has(n) ? "row hl" : "row";
      return `<span class="${cls}">${num}${line || "&#8203;"}</span>`;
    })
    // No newline between rows: `.row` is already a block, and the container is
    // `white-space: pre`, so a separator would break the line a second time.
    .join("");

  const title = opts.title ?? (opts.file ? basename(opts.file) : usedLang);
  const cols = Math.max(...source.split("\n").map((l) => l.length), 1) + (gutter ? width + 2 : 0);

  return {
    html: cardDocument(body, { ...opts, theme, title }, syntaxCss(theme)),
    rows: lines.length,
    cols,
    lang: usedLang,
  };
}
