// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * What a room message says, in a line.
 *
 * Every surface that renders a room message as prose — the channel feed, the
 * board's daily log — reads it through {@link parseEvent}, and every surface
 * that needs the parsed envelope without the prose (the notification
 * classifier, the L9 inspector) shares {@link unwrapContent}, the
 * parse-and-fall-back preamble: content may be a JSON string or an object,
 * the payload may be nested under `.payload`, fall back rather than throw.
 * A change to a payload's shape lands here once, not once per surface.
 */

import { NOTICE_TYPE, PING_TYPE, noticeOf, pingOf } from "@/lib/threads";

export interface Event {
  /** Render key only — synthesized, so a message republished by a status
   *  transition can't collide with the row it updates. */
  id: string;
  /** The backend's id for this message, where it has one. Stable across reads
   *  (the transcript derives it from the envelope id), which is what a search
   *  result points at. */
  messageId: string | null;
  type: string;
  content: string;
  sender: string;
  recipient: string | null;
  time: string;
  /** The full stamp, for ordering two reads into one feed. */
  at: string;
  // The L9 episode URN this event belongs to, when it rode one. Negotiation
  // turns share their mediator's episode; casual chat carries the room default
  // or none. Lets the feed group/fold one negotiation's turns together.
  episode: string | null;
  /** The id of the message this one revises, when it is an amendment. The feed
   *  folds it into that message rather than showing it as a row of its own. */
  amends: string | null;
  /** True once an amendment has revised this message's text. */
  edited: boolean;
  /** The thread a **ping** is about — never the episode the ping itself rode,
   *  which is the room. Null on everything that is not a ping. */
  thread: string | null;
  /** Who wrote in the thread, on a ping. The row's own sender is the system
   *  that raised it, which is nobody, so the writer is read from the payload. */
  pingSenders: string[];
  raw: Record<string, unknown>;
}

export const CHAT_TYPES = new Set(["broadcast", "direct", "announce", "delegate"]);

const messageType = (msg: Record<string, unknown>): string =>
  (msg.message_type as string) || (msg.type as string) || "unknown";

/**
 * The envelope a wire message carries, unwrapped.
 *
 * Chat messages carry a plain string in `content` (returned as `{text}` — the
 * shape the chat branches read); coordination events carry a JSON blob, as a
 * string or already an object. Nothing to unwrap means the message itself is
 * the payload (route-level events carry their fields flat), and an unparseable
 * blob falls back the same way rather than throwing — a reader never fails
 * because one frame was malformed.
 */
export function unwrapContent(msg: Record<string, unknown>): Record<string, unknown> {
  const mtype = messageType(msg);
  try {
    if (typeof msg.content === "string") {
      if (CHAT_TYPES.has(mtype)) return { text: msg.content };
      return JSON.parse(msg.content) as Record<string, unknown>;
    }
    if (msg.content) return msg.content as Record<string, unknown>;
    return msg;
  } catch {
    return CHAT_TYPES.has(mtype) ? { text: msg.content } : msg;
  }
}

export function parseEvent(msg: Record<string, unknown>): Event {
  let mtype = messageType(msg);
  const sender = (msg.sender_handle as string) || (msg.updated_by as string) || "?";
  const recipient = (msg.recipient_handle as string) || null;
  const created = (msg.created_at as string) || new Date().toISOString();
  const time = created.slice(11, 19);

  let content = "";
  let raw = unwrapContent(msg);
  let thread: string | null = null;
  let pingSender: string | null = null;

  switch (mtype) {
    case "broadcast":
    case "direct":
    case "announce":
    case "delegate":
      content = (raw.text as string) || (msg.content as string) || "";
      break;
    case "coordination_join": {
      const handle = (raw.handle as string) || sender;
      const intent = raw.intent as string;
      content = `${handle} joined${intent ? `: ${intent}` : ""}`;
      break;
    }
    case "coordination_start":
      content = `Episode started with ${raw.agent_count || "?"} agents`;
      break;
    case "coordination_tick": {
      // Ticks wrap their fields under .payload
      const tick = (raw.payload as Record<string, unknown>) || raw;
      const round = tick.round ?? "?";
      const action = tick.action ?? "tick";
      const participant = tick.participant_id ?? "?";
      content = `Round ${round}: ${participant} → ${action}`;
      if (tick.current_offer) content += ` ${JSON.stringify(tick.current_offer)}`;
      break;
    }
    case "coordination_consensus": {
      const broken = raw.broken === true;
      const assignments = raw.assignments as Record<string, string>;
      const tasks = Array.isArray(raw.tasks) ? (raw.tasks as string[]) : [];
      content = "";
      if (assignments) content += Object.entries(assignments).map(([k, v]) => `${k}=${v}`).join(", ");
      // Consensus isn't the end; it compiles into work the room can pick up.
      if (!broken && tasks.length) {
        content += ` · compiled → ${tasks.length} ${tasks.length === 1 ? "row" : "rows"}`;
      }
      {
        const metrics = raw.metrics as Record<string, unknown> | undefined;
        const gar = metrics && typeof metrics === "object" ? metrics.gar : undefined;
        if (typeof gar === "number" && Number.isFinite(gar)) content += ` · GAR ${gar.toFixed(2)}`;
      }
      break;
    }
    case "memory_changed": {
      const key = (raw.key || msg.key) as string;
      const version = (raw.version || msg.version) as number;
      const by = (raw.updated_by || msg.updated_by) as string;
      content = `${key} v${version} by ${by}`;
      break;
    }
    case "l9_exchange": {
      // A ping rides the exchange kind like everything else, so it has to be
      // recognised before the prose unwrap below — which would otherwise turn
      // it into an empty chat row from `system`, the one shape a thread exists
      // to keep out of the room.
      const ping = pingOf(raw);
      if (ping) {
        thread = ping.episode;
        pingSender = ping.sender;
        mtype = PING_TYPE;
        break;
      }
      // A board event — a task filed, claimed, handed back, resolved — rides the
      // same exchange kind, named before the prose unwrap for the same reason a
      // ping is: it is a notice about the board, not a chat row. `thread` holds
      // the task's own thread to open.
      const notice = noticeOf(raw);
      if (notice) {
        thread = notice.episode;
        content = notice.title ?? notice.key;
        mtype = NOTICE_TYPE;
        raw = { ...raw, taskKey: notice.key, by: notice.by, kind: notice.kind, subkind: notice.subkind, for: notice.assignee };
        break;
      }
      // The live SSE stream wraps human/agent messages as an L9 exchange
      // envelope, while the REST snapshot (loaded on mount/refresh) delivers the
      // same message as a plain "broadcast". Unwrap the prose and normalise to
      // the chat shape so the live feed matches a refresh instead of silently
      // dropping the message.
      content = (raw.content as string) || "";
      mtype = recipient ? "direct" : "broadcast";
      break;
    }
    case "l9_commit": {
      // Unwrap the L9 commit envelope into the coordination_consensus shape
      // the channel notice row and the L9 inspector both read.
      const l9env = (raw.l9 as Record<string, unknown> | undefined) ?? {};
      const header = (l9env.header as Record<string, unknown> | undefined) ?? {};
      const payload = (l9env.payload as Record<string, unknown> | undefined) ?? {};
      const data = (payload.data as Record<string, unknown> | undefined) ?? {};
      const message = header.message as Record<string, unknown> | undefined;
      content = (raw.content as string) || "";
      raw = {
        ...raw,
        broken: header.subkind !== "converged",
        assignments: data.assignments,
        metrics: data.metrics,
        episode: message?.episode,
      };
      mtype = "coordination_consensus";
      break;
    }
    case "l9_knowledge": {
      // A memory push (e.g. a compiled task landing in the room) rides as
      // an L9 "knowledge" envelope. Recognized as its own system notice rather
      // than falling to the unhandled-type fallback.
      const l9env = (raw.l9 as Record<string, unknown> | undefined) ?? {};
      const payload = (l9env.payload as Record<string, unknown> | undefined) ?? {};
      const data = (payload.data as Record<string, unknown> | undefined) ?? {};
      content = (raw.content as string) || `${(data.key as string) ?? "memory"} updated`;
      raw = { ...raw, key: data.key, updated_by: data.updated_by, version: data.version };
      break;
    }
    default:
      // A message type nothing above handles would otherwise vanish from the
      // channel view without a trace (exactly how l9_exchange hid). Surface it
      // loudly so an unsupported/renamed type can't fail silently again.
      console.warn(
        `[mycelium] EventStream: unhandled message_type "${mtype}" — ` +
          "rendered as a raw fallback and likely hidden from the channel view",
        msg,
      );
      content = (msg.content as string) || JSON.stringify(msg).slice(0, 100);
  }

  const episode =
    (msg.episode as string) ||
    ((raw.header as Record<string, unknown> | undefined)?.message as
      | Record<string, unknown>
      | undefined)?.episode as string ||
    null;

  // An amendment names the message it revises: over SSE that's the L9 envelope's
  // subkind + parents, on the REST snapshot the backend has already folded it and
  // only the `edited_at` stamp survives.
  const l9header = ((raw.l9 as Record<string, unknown> | undefined)?.header ??
    {}) as Record<string, unknown>;
  const parents = (l9header.message as Record<string, unknown> | undefined)?.parents;
  const amends =
    l9header.subkind === "amend" && Array.isArray(parents) && typeof parents[0] === "string"
      ? (parents[0] as string)
      : typeof msg.amends === "string"
        ? msg.amends
        : null;

  return {
    id: `${Date.now()}-${Math.random()}`,
    messageId: typeof msg.id === "string" ? msg.id : null,
    type: mtype,
    content,
    sender,
    recipient,
    time,
    at: created,
    episode,
    amends,
    edited: typeof msg.edited_at === "string",
    thread,
    pingSenders: pingSender ? [pingSender] : [],
    raw,
  };
}
