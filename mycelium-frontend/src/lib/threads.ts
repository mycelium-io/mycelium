// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Threads, and how the room hears about them.
 *
 * A task's coordination happens in a **thread** — an episode URN tagged over
 * the room's own channel, not a channel of its own. The room itself is an
 * episode too (the `live` URN), which is what makes "the room without its
 * threads" a question this module can answer rather than a special case.
 *
 * What surfaces in the room when a thread moves is a **ping**: which thread,
 * who wrote, and the message's id. Deliberately no prose — a thread exists so
 * an argument inside a task does not become the room's problem, and echoing it
 * here would undo that. The backend produces the ping
 * (`room_channels.raise_ping`) and the CLI reads it (`slim.l9.ping_of`); this
 * is the third reader, so the constants below are frozen in
 * `contracts/slim-l9-wire.json` and asserted by `threads.contract.test.ts`.
 */

/** The session literal naming a room's own channel among its episodes. */
export const LIVE_SESSION = "live";

/** The payload type a thread's activity surfaces into the room as. */
export const PING_PAYLOAD_TYPE = "ping";

/** The whole of a ping. A reader expecting prose here would draw an empty line. */
export const PING_PAYLOAD_FIELDS = ["episode", "sender", "message"] as const;

/**
 * The normalized type a ping wears once parsed.
 *
 * A ping arrives as an `l9_exchange` like any other message, so it would
 * otherwise render as a chat row from `system` with nothing in it. Naming it
 * here is what lets the feed render it as the notice it is.
 */
export const PING_TYPE = "thread_ping";

/** The URN of a room episode, from the room and the session (short id) it tags. */
export function episodeUrn(room: string, session: string): string {
  return `urn:ioc:mycelium:episode:${room}:${session}`;
}

/** The URN of a room's own channel — where a message with no thread lands. */
export function liveEpisodeUrn(room: string): string {
  return episodeUrn(room, LIVE_SESSION);
}

/**
 * Whether this episode is the room itself rather than a thread inside it.
 *
 * A missing episode is the room: rows written before threading carry none, and
 * reading them as a thread would empty the channel of its own history.
 */
export function isLiveEpisode(room: string, episode: string | null | undefined): boolean {
  return !episode || episode === liveEpisodeUrn(room);
}

/** The short id a thread is named by — the tail of its URN. */
export function threadShortId(episode: string | null | undefined): string | null {
  if (!episode) return null;
  const tail = episode.split(":").pop();
  return tail && tail !== LIVE_SESSION ? tail : null;
}

/** What a ping says: the thread that moved, who wrote, and what they wrote. */
export interface Ping {
  episode: string;
  sender: string | null;
  message: string | null;
}

/**
 * The ping a wire frame carries, or null when it isn't one.
 *
 * Reads the L9 envelope's own payload rather than the frame's `episode` field:
 * a ping rides in `live` (that is the point of it) and names the thread it is
 * about in its payload, so the two answer different questions.
 */
export function pingOf(raw: Record<string, unknown> | null | undefined): Ping | null {
  const envelope = (raw?.l9 ?? null) as Record<string, unknown> | null;
  const payload = (envelope?.payload ?? null) as Record<string, unknown> | null;
  if (!payload || payload.type !== PING_PAYLOAD_TYPE) return null;
  const data = (payload.data ?? {}) as Record<string, unknown>;
  const episode = data.episode;
  if (typeof episode !== "string" || !episode) return null;
  return {
    episode,
    sender: typeof data.sender === "string" ? data.sender : null,
    message: typeof data.message === "string" ? data.message : null,
  };
}

/** The payload type the room's board events surface into the timeline as. */
export const NOTICE_PAYLOAD_TYPE = "notice";

/** The normalized type a notice wears once parsed. */
export const NOTICE_TYPE = "notice";

/** What a board event did to a task — the closed set the backend raises, frozen
 *  in `contracts/slim-l9-wire.json` and asserted by `threads.contract.test.ts`. */
export const NOTICE_SUBKINDS = [
  "filed",
  "claimed",
  "released",
  "resolved",
  "blocked",
  "unblocked",
  "expired",
] as const;

export type NoticeSubkind = (typeof NOTICE_SUBKINDS)[number];

/** What a notice says: what happened, to which task, and the thread to open. */
export interface Notice {
  subkind: string;
  key: string;
  title: string | null;
  episode: string | null;
  by: string | null;
  /** The board kind, on a `filed` notice, so the line reads "New decision". */
  kind: string | null;
  /** Who a `filed` task is for (its assignee), so the line can read "for @x". */
  assignee: string | null;
}

/**
 * The notice a wire frame carries, or null when it isn't one.
 *
 * The sibling of {@link pingOf}: a notice rides in `live` and names the task the
 * board event was about, so the channel can render "New task" / "@x is on it" /
 * "resolved" in sequence with the chat and open the same thread the row does.
 */
export function noticeOf(raw: Record<string, unknown> | null | undefined): Notice | null {
  const envelope = (raw?.l9 ?? null) as Record<string, unknown> | null;
  const payload = (envelope?.payload ?? null) as Record<string, unknown> | null;
  if (!payload || payload.type !== NOTICE_PAYLOAD_TYPE) return null;
  const data = (payload.data ?? {}) as Record<string, unknown>;
  const key = data.key;
  const subkind = data.subkind;
  if (typeof key !== "string" || !key || typeof subkind !== "string" || !subkind) return null;
  const str = (v: unknown) => (typeof v === "string" && v ? v : null);
  return {
    subkind,
    key,
    title: str(data.title),
    episode: str(data.episode),
    by: str(data.by),
    kind: str(data.kind),
    assignee: str(data.for),
  };
}

/** What the room calls a thing it just filed, by its board kind. A decision is
 *  not a task, so the notice says so — otherwise the timeline mislabels half of
 *  what the room does. */
const FILED_AS: Record<string, string> = {
  decision: "decision",
  concern: "concern",
  blocked: "blocker",
  review: "task",
  action: "task",
  signal: "note",
};

/** The label a notice wears in the timeline, by subkind (and, when filed, kind). */
export function noticeLabel(subkind: string, kind: string | null | undefined): string {
  switch (subkind) {
    case "filed":
      return `New ${(kind && FILED_AS[kind]) || "task"}`;
    case "claimed":
      return "Claimed";
    case "released":
      return "Released";
    case "resolved":
      return "Resolved";
    case "blocked":
      return "Blocked";
    case "unblocked":
      return "Unblocked";
    case "expired":
      return "Expired";
    default:
      return subkind;
  }
}
