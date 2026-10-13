// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What the buttons on a hovered channel message write: a reply or a quote
// added to the composer's draft, and the title and body of a task made from
// the message. The bar itself is `components/message-actions.tsx`.

/** Fired on `window` to add text to the channel's composer, which listens for
 *  it while it is the room's own (`RoomChatBox`'s `receivesInserts`). */
export const COMPOSER_INSERT_EVENT = "mycelium:composer-insert";

export interface ComposerInsert {
  room: string;
  text: string;
}

export function insertIntoComposer(detail: ComposerInsert): void {
  window.dispatchEvent(new CustomEvent<ComposerInsert>(COMPOSER_INSERT_EVENT, { detail }));
}

/** The path that opens the room scrolled to a message, as search results link it. */
export function messagePath(room: string, messageId: string): string {
  return `/room/${encodeURIComponent(room)}?focus=${encodeURIComponent(`message:${messageId}`)}`;
}

/** A reply names the sender, which notifies them. */
export function replyText(sender: string): string {
  return `@${sender} `;
}

/** A quote names the sender silently (`@~`), so quoting someone doesn't
 *  notify them; the reply button is the one that does. Blank lines stay
 *  inside the quote. */
export function quoteText(content: string, sender: string): string {
  const lines = content.trim().split("\n");
  const quoted = lines.map((line, i) => {
    const text = i === 0 ? `@~${sender}: ${line}` : line;
    return text.trim() ? `> ${text}` : ">";
  });
  return `${quoted.join("\n")}\n\n`;
}

/** The draft with `text` added after what is already typed. A reply to
 *  someone the draft already mentions adds nothing. */
export function appendToDraft(draft: string, text: string): string {
  const mention = text.match(/^@([\w.-]+) $/);
  if (mention && new RegExp(`(^|\\s)@${mention[1].replace(/\./g, "\\.")}(?![\\w.-])`).test(draft)) return draft;
  if (!draft.trim()) return text;
  if (draft.endsWith("\n\n")) return draft + text;
  // A quote is a block of its own; a mention carries on the line.
  if (text.startsWith(">")) return `${draft.replace(/\n*$/, "")}\n\n${text}`;
  return /\s$/.test(draft) ? draft + text : `${draft} ${text}`;
}

const TITLE_MAX = 80;

/** A task's title from a message: its first line of words, without markdown
 *  or mention sigils, cut at a word near `TITLE_MAX`. */
export function taskTitle(content: string): string {
  const line =
    content
      .split("\n")
      .map((l) =>
        l
          .replace(/^\s*(?:>\s*)+/, "")
          .replace(/^\s*(?:#{1,6}\s+|[-*+]\s+|\d+\.\s+)/, "")
          .replace(/!?\[\[([^\]\n]+)\]\]/g, "$1")
          .replace(/\[([^\]\n]+)\]\([^)\s]+\)/g, "$1")
          .replace(/[*_`~]+/g, "")
          .replace(/(^|\s)@[~!]?(?=[\w])/g, "$1")
          .replace(/\s+/g, " ")
          .trim(),
      )
      .find(Boolean) ?? "";
  if (!line) return "Follow up on a message";
  if (line.length <= TITLE_MAX) return line;
  const cut = line.slice(0, TITLE_MAX);
  const space = cut.lastIndexOf(" ");
  return `${(space > TITLE_MAX / 2 ? cut.slice(0, space) : cut).replace(/[\s,.;:]+$/, "")}…`;
}

/** A task's body from a message: the message quoted, and where it was said. */
export function taskBody(content: string, sender: string, link: string | null): string {
  const quoted = content
    .trim()
    .split("\n")
    .map((line) => (line.trim() ? `> ${line}` : ">"))
    .join("\n");
  const from = link ? `From [a message](${link}) by @~${sender} in the channel.` : `From a message by @~${sender} in the channel.`;
  return `${quoted}\n\n${from}\n`;
}
