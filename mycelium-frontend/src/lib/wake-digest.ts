// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * A wake, read into its parts.
 *
 * The hub writes each wake as plain text for the agent's terminal
 * (`fastapi-backend/app/services/wake_digest.py`). The agent window draws it
 * from these parts instead of as a block of monospace. The text is made of
 * three kinds of block:
 *
 *   mycelium wake for @builder in checkout      the header: who and which room
 *   Why:     @hay mentioned you in the room     a field: a label, its line, and
 *            and its indented lines               any indented lines under it
 *   ┌ @hay · 2m ago · in the room · 7d0a9599    a message: who, when, where and
 *   │ what they said                              its id, then what they said
 *   └ also for @builder (working)
 *   Members (3 other agents)                    the members pane: one row a state
 *     ● working   @desktop  answering @hay
 *
 * `contracts/wake-digests.json` holds wakes the hub builds, and the test beside
 * this file parses each one. A line this parser doesn't place goes into
 * `unread`, and that test fails on any, so a change to the wake can't leave
 * the app reading it wrong without a red test.
 */

export interface WakeField {
  /** As written, without its colon: "Why", "Since", "Next", "Also asking you (1)". */
  label: string;
  /** Its first line, then each indented line under it, trimmed. */
  lines: string[];
}

export interface WakeMessage {
  sender: string;
  /** How long ago it was said, as the wake says it: "2m ago", "now". */
  age: string;
  /** Where it was said: "in the room", `in "Fix the receipt tax"`. */
  place: string;
  /** The short id `mycelium room messages --id` takes. */
  id: string | null;
  /** Anything after the id, such as "interrupted you just now". */
  flags: string[];
  body: string;
  /** What the box closes on: who else it's for, or where it was cut. */
  note: string | null;
  /** Shown under "Also asking you", not the message that woke it. */
  also: boolean;
}

export interface WakeMember {
  /** The state word: working, idle, blocked, done. */
  state: string;
  /** The rest of the row: the handles, and what one is doing. */
  text: string;
}

export interface Wake {
  handle: string;
  room: string;
  fields: WakeField[];
  messages: WakeMessage[];
  members: { title: string; rows: WakeMember[] } | null;
  /** Lines the parser couldn't place. Empty for every wake the hub writes today. */
  unread: string[];
}

const HEADER = /^mycelium wake for @(\S+) in (\S+)$/;
/** "Why:     …", "Mentioned: …", "Next:    1. …", or a heading ending in a colon. */
const FIELD = /^([A-Z][^:]*?):(?:\s+(.*))?$/;
const MEMBERS = /^Members \((.+)\)$/;
const MEMBER_ROW = /^\s+\S\s+(\S+)\s+(.*)$/;
const SHORT_ID = /^[0-9a-f]{8}$/;

/** A box's first line: `@sender · age · place · id`, then any flags. */
function boxHeader(text: string): Pick<WakeMessage, "sender" | "age" | "place" | "id" | "flags"> | null {
  const parts = text.split(" · ");
  if (parts.length < 3 || !parts[0].startsWith("@")) return null;
  const idAt = parts.findIndex((p, i) => i >= 2 && SHORT_ID.test(p));
  const end = idAt === -1 ? parts.length : idAt;
  return {
    sender: parts[0].slice(1),
    age: parts[1],
    place: parts.slice(2, end).join(" · "),
    id: idAt === -1 ? null : parts[idAt],
    flags: idAt === -1 ? [] : parts.slice(idAt + 1),
  };
}

/** The wake in `text`, or null when it isn't one. */
export function parseWake(text: string): Wake | null {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const head = HEADER.exec(lines[0]?.trim() ?? "");
  if (!head) return null;
  const wake: Wake = { handle: head[1], room: head[2], fields: [], messages: [], members: null, unread: [] };

  // What an indented line continues: a field, or the members pane.
  let open: "field" | "members" | null = null;
  // Boxes after "Also asking you" are the others asking, not the one that woke it.
  let also = false;
  let box: WakeMessage | null = null;
  let body: string[] = [];

  for (const line of lines.slice(1)) {
    if (box) {
      if (line.startsWith("│")) {
        body.push(line.slice(2));
        continue;
      }
      if (line.startsWith("└")) {
        box.body = body.join("\n");
        box.note = line.slice(1).trim() || null;
        wake.messages.push(box);
        box = null;
        continue;
      }
      // A box that never closed: keep what it said, and read on.
      box.body = body.join("\n");
      wake.messages.push(box);
      box = null;
    }
    if (line.trim() === "") {
      open = null;
      continue;
    }
    if (line.startsWith("┌ ")) {
      const parsed = boxHeader(line.slice(2));
      if (!parsed) {
        wake.unread.push(line);
        continue;
      }
      box = { ...parsed, body: "", note: null, also };
      body = [];
      open = null;
      continue;
    }
    const members = MEMBERS.exec(line);
    if (members) {
      wake.members = { title: members[1], rows: [] };
      open = "members";
      continue;
    }
    if (/^\s/.test(line)) {
      if (open === "members" && wake.members) {
        const row = MEMBER_ROW.exec(line);
        if (row) wake.members.rows.push({ state: row[1], text: row[2].trim() });
        else wake.unread.push(line);
      } else if (open === "field") {
        wake.fields[wake.fields.length - 1].lines.push(line.trim());
      } else {
        wake.unread.push(line);
      }
      continue;
    }
    // A note in parentheses, such as which earlier asks aren't shown.
    if (/^\(.*\)$/.test(line)) {
      wake.fields.push({ label: "Note", lines: [line.slice(1, -1)] });
      open = null;
      continue;
    }
    const field = FIELD.exec(line);
    if (field) {
      const label = field[1].trim();
      if (label.startsWith("Also asking you")) also = true;
      wake.fields.push({ label, lines: field[2] ? [field[2].trim()] : [] });
      open = "field";
      continue;
    }
    wake.unread.push(line);
  }
  if (box) {
    box.body = body.join("\n");
    wake.messages.push(box);
  }
  return wake;
}

/** A field's lines by its label, or an empty list. */
export function wakeField(wake: Wake, label: string): string[] {
  return wake.fields.find((f) => f.label === label)?.lines ?? [];
}
