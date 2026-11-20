// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Who is responding right now.
 *
 * The backend raises an `agent_activity` frame on the room stream when a
 * participant starts generating (the conductor handing a step to Pi, a resident
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

/** What herdr last said an agent on a machine is doing, and when that changed
 *  (ms since epoch). `at` moves only when the status does, so a poll that
 *  reads the same state again says nothing new. */
export interface HerdrState {
  status: string;
  at: number;
}

/** Fold one read of the room's members into what herdr says, keeping each
 *  unchanged handle's time. Returns the same map when nothing changed. */
export function noteHerdr(
  prev: ReadonlyMap<string, HerdrState>,
  members: Iterable<{ handle: string; status?: string | null }>,
  now: number,
): ReadonlyMap<string, HerdrState> {
  const next = new Map<string, HerdrState>();
  let changed = false;
  for (const m of members) {
    if (!m.status) continue;
    const handle = norm(m.handle);
    const was = prev.get(handle);
    if (was?.status === m.status) next.set(handle, was);
    else {
      next.set(handle, { status: m.status, at: now });
      changed = true;
    }
  }
  return changed || next.size !== prev.size ? next : prev;
}

/** Remember which thread each handle's latest turn went to, so an agent herdr
 *  says is working is shown where it was last asked, after its frame expired. */
export function noteTurnEpisode(
  prev: ReadonlyMap<string, string | null>,
  frame: ActivityFrame,
): ReadonlyMap<string, string | null> {
  if (frame.state !== "responding") return prev;
  const handle = norm(frame.handle);
  const episode = frame.episode ?? null;
  return prev.has(handle) && prev.get(handle) === episode ? prev : new Map(prev).set(handle, episode);
}

/**
 * Who is responding, with herdr deciding for the agents it runs. An agent herdr
 * says is working is responding however long its turn takes; one it says is
 * idle, blocked or done is not, even if it finished without a message. The
 * hub's frames still decide for every member herdr doesn't run (engines, an
 * agent looping `await` itself), and for a turn that started after herdr's
 * last change, since herdr's reading arrives on a poll and may not have
 * caught up with it yet.
 */
export function withHerdrState(
  entries: Responding[],
  herdr: ReadonlyMap<string, HerdrState>,
  turnEpisodes: ReadonlyMap<string, string | null>,
): Responding[] {
  const shown = entries.filter((r) => {
    const h = herdr.get(r.handle);
    return !h || h.status === "working" || r.since > h.at;
  });
  for (const [handle, h] of herdr) {
    if (h.status !== "working" || shown.some((r) => r.handle === handle)) continue;
    shown.push({ handle, episode: turnEpisodes.get(handle) ?? null, since: h.at, until: Infinity });
  }
  return shown;
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
