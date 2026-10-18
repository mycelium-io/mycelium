// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The words on the board people read.
 *
 * The hub works out the epics, their paths and what is waiting on whom
 * (`GET /rooms/{room}/board`, `GET /rooms/{room}/waiting`); this only says it.
 * Every label is a plain phrase or a whole sentence, and numbers stay in
 * sentences ("1 of 5 parts done").
 */

import type { BoardEpic, BoardPart, PartState, WaitingItem } from "@/lib/api";

// Frozen in contracts/board-vocabulary.json under `epic`.
export const PART_STATES: PartState[] = ["done", "blocked", "waiting", "working", "open"];
export const WAITING_KINDS: WaitingItem["kind"][] = ["ask", "turn", "task"];

/** How long a thread can go without a word before a running task reads as quiet. */
export const QUIET_AFTER_MS = 3 * 60 * 60 * 1000;

const bare = (handle: string | null | undefined) => (handle ?? "").replace(/^@/, "");

/** Who a part is with: "you", a handle, or "nobody yet". */
export function whoHasIt(part: BoardPart, you: string): string {
  const who = bare(part.holder) || bare(part.assignee);
  if (!who) return "nobody yet";
  return who === bare(you) ? "you" : who;
}

/** Every task an epic names, key to title, so a part can be named by its title. */
export function titlesOf(epic: BoardEpic): Map<string, string> {
  const titles = new Map<string, string>([[epic.key, epic.title]]);
  for (const part of epic.path) titles.set(part.key, part.title);
  return titles;
}

/** Where a part stands, said plainly. A running part shows its latest line
 *  where it has one, which says more than any state could. */
export function whereItStands(part: BoardPart, titles: Map<string, string> = new Map()): string {
  switch (part.state) {
    case "done":
      return "Done";
    case "blocked":
      return part.blocked_by ? `Blocked by ${part.blocked_by}` : "Blocked";
    case "waiting": {
      const after = part.waiting_on.map(key => titles.get(key) ?? key);
      return after.length ? `Starts after ${joinNames(after)}` : "Waiting";
    }
    case "working":
      return part.latest ? `${part.latest.sender}: ${part.latest.text}` : "Being worked on";
    default:
      return "Ready for someone to pick up";
  }
}

/** "1 of 5 parts done". */
export function progressOf(epic: BoardEpic): string {
  return `${epic.done} of ${epic.total} ${epic.total === 1 ? "part" : "parts"} done`;
}

/** "Quiet for 3 hours" when nothing has been said in a running task's thread
 *  for a while, else null. A task nobody is on isn't quiet, it's waiting. */
export function quietFor(parts: BoardPart[], now: number): string | null {
  const running = parts.filter(p => p.state === "working");
  if (running.length === 0 || !now) return null;
  const last = Math.max(
    ...running.map(p => Date.parse(p.latest?.at ?? p.updated_at ?? "") || 0),
  );
  if (!last || now - last < QUIET_AFTER_MS) return null;
  const hours = Math.floor((now - last) / 3_600_000);
  if (hours < 24) return `Quiet for ${hours} ${hours === 1 ? "hour" : "hours"}`;
  const days = Math.floor(hours / 24);
  return `Quiet for ${days} ${days === 1 ? "day" : "days"}`;
}

/** The standalone tasks split the way the board shows them: the ones someone
 *  is working on sit with the epics, the rest are up next. */
export function splitTasks(tasks: BoardPart[]): { running: BoardPart[]; next: BoardPart[] } {
  const running = tasks.filter(t => t.state === "working" || t.state === "blocked");
  const next = tasks.filter(t => t.state === "open" || t.state === "waiting");
  return { running, next };
}

/** What a waiting item says on its row. An ask is its own words, less the
 *  mention of you it opens with: the row is already yours. */
export function waitingText(item: WaitingItem, you = ""): string {
  if (item.kind === "ask") {
    const text = (item.text ?? "").replace(new RegExp(`^@!?${escape(bare(you))}\\b[,:]?\\s*`, "i"), "");
    if (!text) return `${item.sender} asked you something`;
    return you && text !== item.text ? text.charAt(0).toUpperCase() + text.slice(1) : text;
  }
  if (item.kind === "turn") return `It's your turn in ${item.title ?? "a flow"}`;
  return `${item.title ?? "A task"} is yours to do`;
}

function escape(text: string): string {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function joinNames(names: string[]): string {
  if (names.length <= 1) return names[0] ?? "";
  return `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}`;
}
