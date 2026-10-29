// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// `@handle` asks a member for something: the hub makes it a recipient, rings its
// doorbell and summons an engine by it. `@~handle` is a silent mention: it names
// the member (drawn as one, found by `mentions:`) and asks nothing of it.
// `@!handle` is a mention that interrupts: it asks, and stops a working agent's
// turn so it reads the message now. A token counts only at the start of the text
// or after whitespace, `(` or `<`, so an email address is none of them, and a
// handle inside code (a code span or a fenced block) is quoted, not mentioned.
// The hub parses the same way (persister.blank_code); both assert
// contracts/mentions.json (mentions.contract.test.ts).

export const MENTION_SIGIL = "@";
export const SILENT_MENTION_SIGIL = "@~";
export const INTERRUPT_MENTION_SIGIL = "@!";

const MENTION_RE = /(?:^|(?<=[\s(<]))@!?([A-Za-z0-9][\w-]*)/g;
const SILENT_RE = /(?:^|(?<=[\s(<]))@~([A-Za-z0-9][\w-]*)/g;
const INTERRUPT_RE = /(?:^|(?<=[\s(<]))@!([A-Za-z0-9][\w-]*)/g;

// What code is replaced with before matching: no word character, no
// whitespace, so it neither extends a handle nor starts one.
const CODE_MASK = "\u0000";
const FENCE_OPEN = /^[ \t]*(`{3,}|~{3,})(.*)$/;
const BLANK_LINE = /\n[ \t]*\n/;

const mask = (text: string) => text.replace(/[^\n]/g, CODE_MASK);

// A fence opens on a line of three or more backticks or tildes (any indent)
// and runs to a line of the same character at least as long, or to the end of
// the text, as Markdown draws it. A backtick fence's info string holds no backtick.
function blankFences(text: string): string {
  let fence: string | null = null;
  return text
    .split("\n")
    .map((line) => {
      if (fence !== null) {
        const close = new RegExp(`^[ \\t]*\\${fence[0]}{${fence.length},}[ \\t]*$`);
        if (close.test(line)) fence = null;
        return mask(line);
      }
      const opened = FENCE_OPEN.exec(line);
      if (opened && !(opened[1][0] === "`" && opened[2].includes("`"))) {
        fence = opened[1];
        return mask(line);
      }
      return line;
    })
    .join("\n");
}

function backtickRunEnd(text: string, start: number): number {
  let end = start;
  while (end < text.length && text[end] === "`") end++;
  return end;
}

/** `text` with its fenced blocks and code spans masked, same length. A code
 *  span closes on the next backtick run of its own length within its
 *  paragraph; a run with no such close is literal backticks, not code. */
export function blankCode(text: string): string {
  const source = blankFences(text);
  let out = "";
  let i = 0;
  while (i < source.length) {
    if (source[i] !== "`") {
      out += source[i];
      i++;
      continue;
    }
    const runEnd = backtickRunEnd(source, i);
    const run = runEnd - i;
    let close = -1;
    for (let k = runEnd; k < source.length; ) {
      if (source[k] !== "`") {
        k++;
        continue;
      }
      const kEnd = backtickRunEnd(source, k);
      if (kEnd - k === run) {
        close = k;
        break;
      }
      k = kEnd;
    }
    if (close === -1 || BLANK_LINE.test(source.slice(runEnd, close))) {
      out += source.slice(i, runEnd);
      i = runEnd;
      continue;
    }
    out += mask(source.slice(i, close + run));
    i = close + run;
  }
  return out;
}

/** `@here` and `@all` name a group of members, never a member called that. */
export const GROUP_NAMES = ["here", "all"] as const;
export type GroupName = (typeof GROUP_NAMES)[number];
export type GroupForm = "mention" | "interrupt" | "silent";

const GROUP_RE = /(?:^|(?<=[\s(<]))@([~!]?)(here|all)(?![\w-])/g;
const GROUP_FORMS: Record<string, GroupForm> = { "": "mention", "!": "interrupt", "~": "silent" };
const GROUP_STRENGTH: Record<GroupForm, number> = { silent: 0, mention: 1, interrupt: 2 };

function handles(text: string, re: RegExp): string[] {
  const named = Array.from(blankCode(text).matchAll(re), (m) => m[1]);
  return [...new Set(named.filter((h) => !(GROUP_NAMES as readonly string[]).includes(h.toLowerCase())))];
}

/** The groups a text names, each in the strongest form it's written in
 *  (interrupt, then mention, then silent). The hub decides who each reaches. */
export function parseGroupMentions(text: string): Partial<Record<GroupName, GroupForm>> {
  const found: Partial<Record<GroupName, GroupForm>> = {};
  for (const [, sigil, name] of blankCode(text).matchAll(GROUP_RE)) {
    const form = GROUP_FORMS[sigil];
    const group = name as GroupName;
    const had = found[group];
    if (had === undefined || GROUP_STRENGTH[form] > GROUP_STRENGTH[had]) found[group] = form;
  }
  return found;
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

/** The group mentions. The hub resolves each to members, the same way for
 *  what the composer shows and for delivery: `@here` is everyone taking part in
 *  the thread (in the channel, everyone), and `@all` is everyone in the room. */
export const MENTION_GROUPS = ["here", "all"] as const;
export type MentionGroupName = (typeof MENTION_GROUPS)[number];

export function isMentionGroup(handle: string): handle is MentionGroupName {
  return (MENTION_GROUPS as readonly string[]).includes(handle.toLowerCase());
}

/** What a mention typed with a sigil other than `@` does, as the @ popover says it. */
export interface MentionMode {
  label: string;
  about: string;
  tone: "warn" | "muted";
}

/** The mode a mention sigil turns on, or null for a plain `@`. */
export function mentionMode(sigil: string | undefined): MentionMode | null {
  if (sigil === INTERRUPT_MENTION_SIGIL) {
    return { label: "Interrupt", about: "stops a working agent", tone: "warn" };
  }
  if (sigil === SILENT_MENTION_SIGIL) {
    return { label: "Silent", about: "names them without notifying", tone: "muted" };
  }
  return null;
}

/** What an interrupt says about an engine: it only acts when it's mentioned,
 *  so `@!` reaches it as a plain mention. */
export const NOT_INTERRUPTIBLE = "mentioned as usual, not interrupted";
