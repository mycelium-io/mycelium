// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { syntaxTree } from "@codemirror/language";
import { EditorView } from "@codemirror/view";

/**
 * Rich text pasted from a web page or a document arrives as HTML; a memory is
 * markdown, so it goes in as markdown: headings, emphasis, links, lists, quotes,
 * code and tables keep their shape instead of flattening to plain text.
 */

const BLOCK = new Set([
  "P", "DIV", "SECTION", "ARTICLE", "HEADER", "FOOTER", "MAIN", "ASIDE", "NAV",
  "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI", "BLOCKQUOTE", "PRE", "TABLE", "HR",
]);

/** Markdown for a fragment of HTML. Unknown tags keep their text. */
export function htmlToMarkdown(html: string): string {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const out = blocks(doc.body, 0);
  return out.replace(/\n{3,}/g, "\n\n").trim();
}

/** Text that would otherwise read as markdown. An underscore inside a word
 *  (`snake_case`) can't start emphasis, so it's left alone. */
const escapeInline = (text: string) => text.replace(/([\\`*[\]])/g, "\\$1").replace(/(?<!\w)_|_(?!\w)/g, "\\_");

function inline(node: Node): string {
  if (node.nodeType === Node.TEXT_NODE) return escapeInline((node.textContent ?? "").replace(/\s+/g, " "));
  if (!(node instanceof HTMLElement)) return "";
  const inner = () => [...node.childNodes].map(inline).join("");
  const style = node.getAttribute("style") ?? "";
  switch (node.tagName) {
    case "STRONG":
    case "B":
      return around(inner(), "**");
    case "EM":
    case "I":
      return around(inner(), "_");
    case "S":
    case "DEL":
    case "STRIKE":
      return around(inner(), "~~");
    case "CODE":
      return codeSpan(node.textContent ?? "");
    case "A": {
      const href = node.getAttribute("href") ?? "";
      const text = inner().trim();
      if (!href || href.startsWith("javascript:")) return text;
      return text && text !== href ? `[${text}](${href})` : `<${href}>`;
    }
    case "IMG":
      return `![${node.getAttribute("alt") ?? ""}](${node.getAttribute("src") ?? ""})`;
    case "BR":
      return "\n";
    case "SPAN":
      // Google Docs marks bold and italic with styles rather than tags.
      if (/font-weight:\s*(bold|[6-9]00)/.test(style)) return around(inner(), "**");
      if (/font-style:\s*italic/.test(style)) return around(inner(), "_");
      return inner();
    default:
      return BLOCK.has(node.tagName) ? blocks(node, 0) : inner();
  }
}

/** `text` inside `mark`, with the mark outside any space at its ends (markdown
 *  doesn't close `** bold **`). */
function around(text: string, mark: string): string {
  const m = /^(\s*)([\s\S]*?)(\s*)$/.exec(text);
  if (!m || !m[2]) return text;
  return `${m[1]}${mark}${m[2]}${mark}${m[3]}`;
}

function codeSpan(text: string): string {
  const ticks = "`".repeat(Math.max(1, ...[...text.matchAll(/`+/g)].map((t) => t[0].length + 1)));
  return ticks.length > 1 || text.startsWith("`") ? `${ticks} ${text} ${ticks}` : `${ticks}${text}${ticks}`;
}

function blocks(el: Element, depth: number): string {
  let out = "";
  let line = "";
  const flush = () => {
    if (line.trim()) out += `${line.trim()}\n\n`;
    line = "";
  };
  for (const child of el.childNodes) {
    if (!(child instanceof HTMLElement) || !BLOCK.has(child.tagName)) {
      line += inline(child);
      continue;
    }
    flush();
    out += block(child, depth);
  }
  flush();
  return out;
}

function block(el: HTMLElement, depth: number): string {
  const tag = el.tagName;
  const heading = /^H([1-6])$/.exec(tag);
  if (heading) return `${"#".repeat(Number(heading[1]))} ${inlineOf(el)}\n\n`;
  switch (tag) {
    case "UL":
    case "OL":
      return `${list(el, depth, tag === "OL")}\n`;
    case "BLOCKQUOTE":
      return `${blocks(el, depth)
        .trim()
        .split("\n")
        .map((l) => (l ? `> ${l}` : ">"))
        .join("\n")}\n\n`;
    case "PRE": {
      const code = el.textContent ?? "";
      const lang = /language-(\w+)/.exec(el.querySelector("code")?.className ?? "")?.[1] ?? "";
      const fence = code.includes("```") ? "~~~" : "```";
      return `${fence}${lang}\n${code.replace(/\n$/, "")}\n${fence}\n\n`;
    }
    case "HR":
      return "---\n\n";
    case "TABLE":
      return table(el);
    default:
      return blocks(el, depth);
  }
}

const inlineOf = (el: Element) => [...el.childNodes].map(inline).join("").replace(/\s+/g, " ").trim();

function list(el: HTMLElement, depth: number, ordered: boolean): string {
  let n = Number(el.getAttribute("start") ?? "1");
  const pad = "  ".repeat(depth);
  return [...el.children]
    .filter((li) => li.tagName === "LI")
    .map((li) => {
      const nested = [...li.children].filter((c) => c.tagName === "UL" || c.tagName === "OL");
      const own = [...li.childNodes].filter((c) => !nested.includes(c as Element));
      const box = li.querySelector(":scope > input[type=checkbox]") as HTMLInputElement | null;
      const text = own
        .filter((c) => c !== box)
        .map(inline)
        .join("")
        .replace(/\s+/g, " ")
        .trim();
      const marker = ordered ? `${n++}.` : "-";
      const task = box ? (box.checked ? "[x] " : "[ ] ") : "";
      const sub = nested.map((c) => list(c as HTMLElement, depth + 1, c.tagName === "OL")).join("");
      return `${pad}${marker} ${task}${text}\n${sub}`;
    })
    .join("");
}

function table(el: HTMLElement): string {
  const rows = [...el.querySelectorAll("tr")].map((tr) =>
    [...tr.children].map((cell) => inlineOf(cell).replace(/\|/g, "\\|")),
  );
  if (rows.length === 0) return "";
  const width = Math.max(...rows.map((r) => r.length));
  const pad = (r: string[]) => [...r, ...Array(width - r.length).fill("")];
  const line = (r: string[]) => `| ${pad(r).join(" | ")} |`;
  return `${[line(rows[0]), line(Array(width).fill("---")), ...rows.slice(1).map(line)].join("\n")}\n\n`;
}

/** Whether HTML carries any formatting worth keeping over its plain text. */
function hasStructure(html: string): boolean {
  return /<(h[1-6]|strong|b|em|i|a|ul|ol|li|blockquote|pre|code|table|hr|img|s|del)\b/i.test(html) ||
    /font-weight:\s*(bold|[6-9]00)|font-style:\s*italic/i.test(html);
}

/** Paste HTML as markdown, except into code, where text is text. */
export const pasteAsMarkdown = EditorView.domEventHandlers({
  paste(event, view) {
    const html = event.clipboardData?.getData("text/html");
    if (!html || !hasStructure(html)) return false;
    const { from, to } = view.state.selection.main;
    const at = syntaxTree(view.state).resolveInner(from, -1);
    for (let n: typeof at | null = at; n; n = n.parent) if (/Code/.test(n.name)) return false;
    const markdown = htmlToMarkdown(html);
    if (!markdown) return false;
    event.preventDefault();
    view.dispatch({
      changes: { from, to, insert: markdown },
      selection: { anchor: from + markdown.length },
      scrollIntoView: true,
      userEvent: "input.paste",
    });
    return true;
  },
});
