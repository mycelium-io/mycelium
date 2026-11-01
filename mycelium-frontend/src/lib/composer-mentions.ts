// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The mentions in a message being written, and whether each reaches someone:
// the composer colors the ones that do and dulls the ones that don't, so you
// can tell before sending. A mention counts where `lib/mentions.ts` says one
// does (at the start, or after whitespace, `(` or `<`, and never inside code),
// and reaches someone when its handle is a member of the room.

import { blankCode } from "./mentions";

export type ComposerMentionKind = "mention" | "silent" | "interrupt";

/** One `@word` in the text: where it is, which sigil it carries, and whether
 *  it's a mention of a member. */
export interface ComposerMention {
  start: number;
  end: number;
  kind: ComposerMentionKind;
  /** The word after the sigil, lowercased. */
  handle: string;
  resolved: boolean;
}

const TOKEN_RE = /@([~!]?)([A-Za-z0-9][\w-]*)/g;
const OPENS = /[\s(<]/;

/** Every `@word` in `text`, in order. `members` holds the room's handles,
 *  lowercased. One that isn't a mention where it stands (inside an email
 *  address, say) or names no member is unresolved. */
export function composerMentions(text: string, members: ReadonlySet<string>): ComposerMention[] {
  // Same length as `text`, with code masked, so an index means the same in both.
  const blanked = blankCode(text);
  return Array.from(blanked.matchAll(TOKEN_RE), (m) => {
    const start = m.index;
    const placed = start === 0 || OPENS.test(blanked[start - 1]);
    return {
      start,
      end: start + m[0].length,
      kind: m[1] === "~" ? "silent" : m[1] === "!" ? "interrupt" : "mention",
      handle: m[2].toLowerCase(),
      resolved: placed && members.has(m[2].toLowerCase()),
    };
  });
}
