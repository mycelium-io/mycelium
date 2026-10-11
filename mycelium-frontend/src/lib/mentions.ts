// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// `@handle` asks a member for something: the hub makes it a recipient, rings its
// doorbell and summons an engine by it. `@~handle` is a silent mention: it names
// the member (drawn as one, found by `mentions:`) and asks nothing of it.
// `@!handle` is a mention that interrupts: it asks, and stops a working agent's
// turn so it reads the message now. A token counts only at the start of the text
// or after whitespace, `(` or `<`, so an email address is none of them. The hub
// parses the same way; both assert contracts/mentions.json
// (mentions.contract.test.ts).

export const MENTION_SIGIL = "@";
export const SILENT_MENTION_SIGIL = "@~";
export const INTERRUPT_MENTION_SIGIL = "@!";

const MENTION_RE = /(?:^|(?<=[\s(<]))@!?([A-Za-z0-9][\w-]*)/g;
const SILENT_RE = /(?:^|(?<=[\s(<]))@~([A-Za-z0-9][\w-]*)/g;
const INTERRUPT_RE = /(?:^|(?<=[\s(<]))@!([A-Za-z0-9][\w-]*)/g;

function handles(text: string, re: RegExp): string[] {
  return [...new Set(Array.from(text.matchAll(re), (m) => m[1]))];
}

/** Handles a text asks for with `@handle` or `@!handle`, first-seen order, de-duplicated. */
export function parseMentions(text: string): string[] {
  return handles(text, MENTION_RE);
}

/** Handles a text names silently with `@~handle`. */
export function parseSilentMentions(text: string): string[] {
  return handles(text, SILENT_RE);
}

/** Handles a text interrupts with `@!handle`; each is in {@link parseMentions} too. */
export function parseInterruptMentions(text: string): string[] {
  return handles(text, INTERRUPT_RE);
}
