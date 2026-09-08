// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Who is responding right now.
 *
 * The backend raises an `agent_activity` frame on the room stream when a
 * participant starts generating (the aligner handing a round to Pi, a resident
 * agent taking an `await` wake) and again when it finishes. It is a
 * presence-style signal, not a message: it never lands in the transcript, so a
 * reload shows none of it, and the channel must never render it as a line.
 *
 * Everything here is pure so the rules can be tested without mounting the
 * stream: a `responding` adds or refreshes one entry per handle, a `done`
 * removes it, a message from the handle settles it (the reply itself is the
 * proof the turn ended, whether or not `done` ever arrives), and an entry
 * nobody has spoken for within its TTL expires, so a turn that died
 * mid-generation cannot leave "@x is responding…" standing all afternoon.
 */

export const ACTIVITY_TYPE = "agent_activity";

/** Fallback when a frame carries no TTL of its own; the backend's is 90s. */
export const DEFAULT_TTL_MS = 90_000;

export interface ActivityFrame {
  type: string;
  handle: string;
  state: "responding" | "done";
  episode?: string | null;
  ttl_s?: number;
}

export interface Responding {
  handle: string;
  /** The thread the turn is in, or null for the room's own channel. */
  episode: string | null;
  /** When the current `responding` arrived (ms since epoch). */
  since: number;
  /** When it is dropped if nothing has been heard from the handle (ms since epoch). */
  until: number;
}

export function isActivityFrame(msg: Record<string, unknown>): msg is ActivityFrame & Record<string, unknown> {
  const type = msg.type ?? msg.message_type;
  return (
    type === ACTIVITY_TYPE &&
    typeof msg.handle === "string" &&
    (msg.state === "responding" || msg.state === "done")
  );
}

const norm = (handle: string): string => handle.replace(/^@/, "").toLowerCase();

/** Fold one frame in: `responding` (re)starts the handle's entry, `done` ends it. */
export function applyActivity(current: Responding[], frame: ActivityFrame, now: number): Responding[] {
  const handle = norm(frame.handle);
  const rest = current.filter((r) => r.handle !== handle);
  if (frame.state === "done") return rest;
  const ttl = typeof frame.ttl_s === "number" && frame.ttl_s > 0 ? frame.ttl_s * 1000 : DEFAULT_TTL_MS;
  return [...rest, { handle, episode: frame.episode ?? null, since: now, until: now + ttl }];
}

/** A message from the handle is the turn ending, whatever the frames said. */
export function settleActivity(current: Responding[], sender: string | null | undefined): Responding[] {
  if (!sender) return current;
  const handle = norm(sender);
  return current.some((r) => r.handle === handle) ? current.filter((r) => r.handle !== handle) : current;
}

/** Drop entries past their TTL. Returns the same array when nothing changed, so
 *  a state setter can skip a render. */
export function expireActivity(current: Responding[], now: number): Responding[] {
  return current.some((r) => r.until <= now) ? current.filter((r) => r.until > now) : current;
}

/** "@x" / "@x and @y" / "@x, @y and 2 others" */
export function respondingNames(entries: Responding[]): string {
  const names = entries.map((r) => `@${r.handle}`);
  if (names.length === 0) return "";
  if (names.length === 1) return names[0];
  if (names.length === 2) return `${names[0]} and ${names[1]}`;
  const more = names.length - 2;
  return `${names[0]}, ${names[1]} and ${more} ${more === 1 ? "other" : "others"}`;
}

/** "@x is responding…" / "@x and @y are responding…". With `where`, the turn
 *  is going somewhere other than the surface reading it — a task's thread — and
 *  the line stops before naming it, so the caller can draw the name as a link:
 *  "@x is responding in". */
export function respondingLabel(entries: Responding[], where: "here" | "elsewhere" = "here"): string {
  if (entries.length === 0) return "";
  const verb = entries.length === 1 ? "is" : "are";
  const names = respondingNames(entries);
  return where === "here" ? `${names} ${verb} responding…` : `${names} ${verb} responding in`;
}

/** The entries whose turn lands on this surface, and those landing in a thread
 *  it does not show. `isHere` says whether an episode is this surface's own. */
export function splitActivity(
  entries: Responding[],
  isHere: (episode: string | null) => boolean,
): { here: Responding[]; elsewhere: Map<string, Responding[]> } {
  const here: Responding[] = [];
  const elsewhere = new Map<string, Responding[]>();
  for (const r of entries) {
    if (isHere(r.episode)) {
      here.push(r);
      continue;
    }
    const key = r.episode ?? "";
    const group = elsewhere.get(key);
    if (group) group.push(r);
    else elsewhere.set(key, [r]);
  }
  return { here, elsewhere };
}
