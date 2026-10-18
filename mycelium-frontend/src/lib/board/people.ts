// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The words on the board people read.
 *
 * The hub works out the epics, their paths and what is waiting on whom
 * (`GET /rooms/{room}/board`, `GET /rooms/{room}/waiting`); this only says it.
 * Every label is a plain phrase or a whole sentence, and numbers stay in
 * sentences ("2 things need you."). A state is a word and one color, the way
 * the activity rail says a task's standing.
 */

import type { BoardEpic, BoardPart, BoardRead, PartState, WaitingItem } from "@/lib/api";

// Frozen in contracts/board-vocabulary.json under `epic`.
export const PART_STATES: PartState[] = ["done", "blocked", "waiting", "working", "open"];
export const WAITING_KINDS: WaitingItem["kind"][] = ["ask", "turn", "task"];

/** How long a thread can go without a word before a running task reads as quiet. */
export const QUIET_AFTER_MS = 3 * 60 * 60 * 1000;

export interface Standing {
  word: string;
  tone: string;
}

/** A part's state as a word, and the one color it wears. Finished work steps
 *  back, so the eye goes to what's still moving. */
export const STANDING: Record<PartState, Standing> = {
  done: { word: "Done", tone: "var(--faint)" },
  blocked: { word: "Blocked", tone: "var(--red)" },
  // Muted: waiting its turn is ordinary. Yellow is kept for a task gone quiet.
  waiting: { word: "Waiting", tone: "var(--muted-foreground)" },
  working: { word: "Working", tone: "var(--accent)" },
  open: { word: "Not started", tone: "var(--muted-foreground)" },
};

/** What each kind of waiting item is, as a word in the state column. */
export const WAITING_STANDING: Record<WaitingItem["kind"], Standing> = {
  ask: { word: "Asks you", tone: "var(--accent)" },
  turn: { word: "Your turn", tone: "var(--accent)" },
  task: { word: "Yours", tone: "var(--accent)" },
};

const bare = (handle: string | null | undefined) => (handle ?? "").replace(/^@/, "");

/** Who a part is with: a handle, "you", or null for nobody yet. */
export function whoHasIt(part: BoardPart, you: string): string | null {
  const who = bare(part.holder) || bare(part.assignee);
  if (!who) return null;
  return who === bare(you) ? "you" : who;
}

/** Every task the board names, key to title, so a task can be named by its title. */
export function titlesOf(board: BoardRead): Map<string, string> {
  const titles = new Map<string, string>();
  for (const epic of board.epics) {
    titles.set(epic.key, epic.title);
    for (const part of epic.path) titles.set(part.key, part.title);
  }
  for (const task of board.tasks) titles.set(task.key, task.title);
  return titles;
}

/** What a task waits on: one by its title, more than one as a count. */
export function startsAfter(part: BoardPart, titles: Map<string, string>): string {
  const after = part.waiting_on;
  if (after.length === 0) return "";
  if (after.length === 1) return `Starts after ${titles.get(after[0]) ?? after[0]}`;
  return `Starts after ${after.length} other tasks`;
}

/** The one human line a row carries: the latest thing said in its thread,
 *  else why it can't go on. Never an engine's report: the hub leaves those
 *  out of `latest`. Empty when there is nothing worth saying. */
export function humanLine(part: BoardPart, titles: Map<string, string> = new Map()): string {
  // Named only when someone other than its holder spoke last: the row
  // already says who has it.
  if (part.latest) {
    const own = bare(part.latest.sender) === (bare(part.holder) || bare(part.assignee));
    return own ? part.latest.text : `${part.latest.sender}: ${part.latest.text}`;
  }
  if (part.state === "blocked") {
    if (part.blocked_by) return `Blocked by ${part.blocked_by}`;
    return part.key.startsWith("failed/") ? "It failed and needs a fix" : "";
  }
  if (part.state === "waiting") return startsAfter(part, titles);
  return "";
}

/** When a task last moved: its latest line, else its last write. */
export function lastMoved(part: BoardPart): number {
  return Date.parse(part.latest?.at ?? part.updated_at ?? "") || 0;
}

/** True when a running task has had nothing said in its thread for a while. */
export function isQuiet(part: BoardPart, now: number): boolean {
  const at = lastMoved(part);
  return part.state === "working" && !!at && !!now && now - at >= QUIET_AFTER_MS;
}

/** The standalone tasks split the way the board shows them: the ones someone
 *  is working on sit with the epics, the rest are up next. */
export function splitTasks(tasks: BoardPart[]): { running: BoardPart[]; next: BoardPart[] } {
  const running = tasks.filter(t => t.state === "working" || t.state === "blocked");
  const next = tasks.filter(t => t.state === "open" || t.state === "waiting");
  return { running, next };
}

/** The line that opens the board: what a person came to find out, in sentences.
 *  "2 things need you. builder and reviewer are on 4 tasks. 3 are up next." */
export function summary(board: BoardRead, waiting: WaitingItem[], you = ""): string {
  const { running, next } = splitTasks(board.tasks);
  const working = [...board.epics.flatMap(e => e.path), ...running].filter(p => p.state === "working");
  const holders = [...new Set(working.map(p => bare(p.holder)).filter(Boolean))];
  // You last, by name: "builder, reviewer and you".
  const who = [...holders.filter(h => h !== bare(you)), ...(holders.includes(bare(you)) ? ["you"] : [])];
  const said: string[] = [];
  said.push(
    waiting.length === 0
      ? "Nothing needs you."
      : `${waiting.length} ${waiting.length === 1 ? "thing needs" : "things need"} you.`,
  );
  if (working.length > 0) {
    const names = who.length > 3 ? `${who.length} members` : joinNames(who);
    said.push(`${names} ${who.length === 1 ? "is" : "are"} on ${working.length} ${working.length === 1 ? "task" : "tasks"}.`);
  }
  if (next.length > 0) said.push(`${next.length} ${next.length === 1 ? "is" : "are"} up next.`);
  return said.join(" ");
}

/** An epic's progress, as the rails count: "1/5". */
export function progressOf(epic: BoardEpic): string {
  return `${epic.done}/${epic.total}`;
}

/** A waiting item's title, the same as every other row's: the task it's in. */
export function waitingTitle(item: WaitingItem): string {
  return item.title ?? "A message in the room";
}

/** A waiting item's one line: the words that ask you (less the mention of you
 *  they open with, since the row is already yours), whose turn it is, or a
 *  task's latest line. */
export function waitingLine(item: WaitingItem, you = ""): string {
  if (item.kind === "ask") {
    const text = (item.text ?? "").replace(new RegExp(`^@!?${escape(bare(you))}\\b[,:]?\\s*`, "i"), "");
    if (!text) return `${item.sender} asked you something`;
    return you && text !== item.text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
  }
  if (item.kind === "turn") return `${item.sender ?? "A flow"} is waiting on you`;
  return item.text ?? "";
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
