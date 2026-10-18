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

/** A part's state as a word, and the color it wears. Color only where it
 *  means something: red for what's stopped. Everything else is muted, so the
 *  accent finds what needs you and yellow finds a task gone quiet. */
export const STANDING: Record<PartState, Standing> = {
  done: { word: "Done", tone: "var(--faint)" },
  blocked: { word: "Blocked", tone: "var(--red)" },
  waiting: { word: "Waiting", tone: "var(--muted-foreground)" },
  working: { word: "Working", tone: "var(--muted-foreground)" },
  open: { word: "Not started", tone: "var(--muted-foreground)" },
};

/** What each kind of waiting item is, as a word in the state column: the
 *  accent, since these are the rows that need you. */
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
 *  "2 things need you. 4 tasks are being worked on. 3 are up next."
 *  `tasks` are the standalone tasks as the board lists them, so the counts
 *  are of rows the reader can see. */
export function summary(epics: BoardEpic[], tasks: BoardPart[], waiting: WaitingItem[]): string {
  const { running, next } = splitTasks(tasks);
  const working = [...epics.flatMap(e => e.path), ...running].filter(p => p.state === "working").length;
  const said: string[] = [];
  said.push(
    waiting.length === 0
      ? "Nothing needs you."
      : `${waiting.length} ${waiting.length === 1 ? "thing needs" : "things need"} you.`,
  );
  if (working > 0) {
    said.push(working === 1 ? "1 task is being worked on." : `${working} tasks are being worked on.`);
  }
  if (next.length > 0) said.push(`${next.length} ${next.length === 1 ? "is" : "are"} up next.`);
  return said.join(" ");
}

/** An epic's own line: the newest thing said in any of its parts' threads. */
export function epicLine(epic: BoardEpic, titles: Map<string, string> = new Map()): string {
  const said = epic.path.filter(p => p.latest);
  if (said.length === 0) return "";
  const newest = said.reduce((a, b) => (lastMoved(b) > lastMoved(a) ? b : a));
  return humanLine(newest, titles);
}

/** What runs at the same time as a part, for the tooltip on its step number. */
export function sideBySide(key: string, step: string[], titles: Map<string, string>): string | undefined {
  const others = step.filter(k => k !== key).map(k => titles.get(k) ?? k);
  return others.length ? `Runs at the same time as ${joinNames(others)}` : undefined;
}

/** An epic's progress, said once, in its state column: "1 of 5 done". */
export function progressOf(epic: BoardEpic): string {
  return `${epic.done} of ${epic.total} done`;
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
