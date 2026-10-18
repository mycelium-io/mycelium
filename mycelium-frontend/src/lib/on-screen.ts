// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// What this window shows of a room: the room, and which of its conversations
// are in front, the Channel and any open task threads (a split shows several).
// The room's dock keeps it current. The bell and reading aloud ask it whether a
// message is already in front of you, by the rule each person picks: the thread
// it was said in is open, the room is, or never skip.

/** The pane a message is said in: a task thread's episode, or the Channel. */
export const CHANNEL = "channel";

export interface OnScreen {
  room: string;
  /** Conversations in front, each an episode or `CHANNEL`. */
  panes: string[];
}

/** What counts as already being in front of you. */
export type SkipRule = "thread" | "room" | "never";

let current: OnScreen | null = null;
const listeners = new Set<() => void>();

/** What this window shows, set by the room's dock. */
export function setOnScreen(next: OnScreen | null): void {
  const same =
    next === current ||
    (next && current && next.room === current.room && next.panes.join("\n") === current.panes.join("\n"));
  current = next;
  if (!same) for (const listener of [...listeners]) listener();
}

/** A room's dock leaving: forget it, unless another room has already replaced it. */
export function clearOnScreen(room: string): void {
  if (current?.room === room) setOnScreen(null);
}

export function onScreenNow(): OnScreen | null {
  return current;
}

export function onOnScreenChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Whether a message is already in front of you on `screen`, by `rule`. */
export function shows(
  screen: OnScreen | null,
  message: { room: string; episode?: string | null },
  rule: SkipRule,
): boolean {
  if (rule === "never" || !screen || screen.room !== message.room) return false;
  if (rule === "room") return true;
  return screen.panes.includes(message.episode ?? CHANNEL);
}
