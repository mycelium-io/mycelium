// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A message's markdown as something to say out loud: the same words, without
// the syntax. Asterisks, backticks and `[[…]]` aren't read; a link is read by
// its text and a bare address by its site; a code block or a table is named
// rather than read; `@julia` is read as "julia". The words are split into
// sentences, because the speech server is asked for a sentence at a time and
// the popover lights the one being said. Each sentence keeps the text it
// shows (the words as written, markup aside) beside the text it says, so what
// is lit is exactly what is heard.

export interface Sentence {
  /** The words as the popover shows them. */
  show: string;
  /** The words as they're said. */
  say: string;
}

export type BlockKind = "paragraph" | "heading" | "item" | "code" | "table";

export interface Block {
  kind: BlockKind;
  sentences: Sentence[];
  /** A code block or a table, shown as it was written but not read. */
  raw?: string;
}

/** About twenty seconds of speech, in words. */
export const EXCERPT_WORDS = 50;

/** The longest one sentence may be when it's sent to be said; a run-on line
 *  is cut at a comma or a space under it. The hub takes up to 1000. */
export const MAX_SENTENCE = 300;

const FENCE = /^\s*(```|~~~)/;
const ITEM = /^\s*(?:[-*+]|\d+[.)])\s+/;
const HEADING = /^\s*#{1,6}\s+/;
const RULE = /^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/;
const TABLE = /^\s*\|/;
const QUOTE = /^\s*>\s?/;

/** The last part of a memory key, as words: `work/speed-up-the-board` → "speed up the board". */
function keyWords(key: string): string {
  const last = key.split("|")[0].split("/").filter(Boolean).pop() ?? key;
  return last.replace(/\.[a-z0-9]{2,4}$/i, "").replace(/[-_]+/g, " ").trim();
}

/** Inline markdown taken out, keeping the words and addresses as written. */
export function plainInline(text: string): string {
  return (
    text
      // A machine marker for the conductor isn't prose.
      .replace(/\[\[mycelium:[^\]]*\]\]/gi, "")
      // ![[key]], [[key]] and [[key|label]].
      .replace(/!?\[\[([^\]|]+)\|([^\]]+)\]\]/g, "$2")
      .replace(/!?\[\[([^\]]+)\]\]/g, (_, key: string) => keyWords(key))
      .replace(/myc:\/\/([^\s)]+)/g, (_, key: string) => keyWords(key))
      // Images by their alt text, links by their text.
      .replace(/!\[([^\]]*)\]\([^)]*\)/g, (_, alt: string) => alt || "an image")
      .replace(/\[([^\]]+)\]\([^)]*\)/g, "$1")
      .replace(/`([^`]+)`/g, "$1")
      .replace(/(\*\*|__)(.+?)\1/g, "$2")
      .replace(/~~(.+?)~~/g, "$1")
      .replace(/(^|[\s(])[*_]([^*_\s][^*_]*?)[*_](?=[\s).,!?:;]|$)/g, "$1$2")
      .replace(/<\/?[a-z][^>]*>/gi, "")
      .replace(/\s+/g, " ")
      .trim()
  );
}

/** Shown words as said words: a bare address by its site, a handle without its `@`. */
export function sayable(text: string): string {
  return text
    .replace(/https?:\/\/[^\s)]+/g, (url) => {
      try {
        return `a link to ${new URL(url.replace(/[.,;:!?]+$/, "")).hostname.replace(/^www\./, "")}`;
      } catch {
        return "a link";
      }
    })
    .replace(/(^|[\s(])@~?([A-Za-z0-9][\w.-]*\w|[A-Za-z0-9])/g, "$1$2")
    .replace(/\s+/g, " ")
    .trim();
}

/** A line cut into sentences, each short enough to send. */
export function splitSentences(text: string): string[] {
  const out: string[] = [];
  for (const part of text.split(/(?<=[.!?])\s+(?=\S)/)) {
    let rest = part.trim();
    while (rest.length > MAX_SENTENCE) {
      const window = rest.slice(0, MAX_SENTENCE);
      const cut = Math.max(window.lastIndexOf(", "), window.lastIndexOf("; "));
      const at = cut > MAX_SENTENCE / 3 ? cut + 1 : window.lastIndexOf(" ") > 0 ? window.lastIndexOf(" ") : MAX_SENTENCE;
      out.push(rest.slice(0, at).trim());
      rest = rest.slice(at).trim();
    }
    if (rest) out.push(rest);
  }
  return out;
}

/** A sentence that doesn't end in punctuation gets a full stop when it's
 *  said, so a heading or a list item is followed by a pause. */
function closed(say: string): string {
  return /[.!?:;]$/.test(say) ? say : `${say}.`;
}

function textBlock(kind: BlockKind, line: string): Block | null {
  const shown = plainInline(line);
  if (!shown) return null;
  const sentences = splitSentences(shown)
    .map((show) => ({ show, say: closed(sayable(show)) }))
    .filter((s) => s.say !== ".");
  return sentences.length ? { kind, sentences } : null;
}

/** A message's markdown as blocks of sentences, in order. */
export function speakable(markdown: string): Block[] {
  const blocks: Block[] = [];
  const lines = markdown.replace(/\r\n?/g, "\n").split("\n");
  let paragraph: string[] = [];
  const flush = () => {
    if (paragraph.length) {
      const block = textBlock("paragraph", paragraph.join(" "));
      if (block) blocks.push(block);
    }
    paragraph = [];
  };

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].replace(QUOTE, "");
    const fence = FENCE.exec(line);
    if (fence) {
      flush();
      const code: string[] = [];
      for (i++; i < lines.length && !lines[i].trimStart().startsWith(fence[1]); i++) code.push(lines[i]);
      blocks.push({ kind: "code", sentences: [{ show: "", say: "A code block." }], raw: code.join("\n") });
      continue;
    }
    if (TABLE.test(line)) {
      flush();
      const rows: string[] = [];
      for (; i < lines.length && TABLE.test(lines[i]); i++) rows.push(lines[i].trim());
      i--;
      blocks.push({ kind: "table", sentences: [{ show: "", say: "A table." }], raw: rows.join("\n") });
      continue;
    }
    if (!line.trim() || RULE.test(line)) {
      flush();
      continue;
    }
    if (HEADING.test(line) || ITEM.test(line)) {
      flush();
      const kind = HEADING.test(line) ? "heading" : "item";
      const block = textBlock(kind, line.replace(HEADING, "").replace(ITEM, ""));
      if (block) blocks.push(block);
      continue;
    }
    paragraph.push(line.trim());
  }
  flush();
  return blocks;
}

/** Every sentence of the message, in order. */
export function sentencesOf(blocks: Block[]): Sentence[] {
  return blocks.flatMap((b) => b.sentences);
}

/** How many of the message's sentences are read before "Read all": its first
 *  paragraph (with any heading over it), or about twenty seconds of it,
 *  whichever ends first, always at the end of a sentence. */
export function excerptLength(blocks: Block[], words = EXCERPT_WORDS): number {
  let count = 0;
  let said = 0;
  for (const block of blocks) {
    for (const sentence of block.sentences) {
      count++;
      said += sentence.say.split(/\s+/).filter(Boolean).length;
      if (said >= words) return count;
    }
    if (block.kind !== "heading") return count;
  }
  return count;
}
