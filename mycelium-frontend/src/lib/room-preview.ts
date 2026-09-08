// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import type { RoomMessage } from "@/lib/api";

export interface RoomPreview {
  /** Who spoke. Empty for a room event that had no author. */
  sender: string;
  /** One line, already collapsed and trimmed. */
  text: string;
  at: string;
}

/** Message types whose `content` is prose a person wrote or an agent replied. */
const CHAT_TYPES = new Set(["broadcast", "direct", "announce", "delegate"]);

/** Room events worth a line of their own when nobody has spoken recently — the
 *  transcript's own punctuation, phrased the way the room would say it. */
const EVENT_TEXT: Record<string, string> = {
  coordination_start: "negotiation opened",
  coordination_end: "negotiation closed",
  coordination_join: "joined the room",
  consensus: "consensus reached",
  memory_update: "memory updated",
};

/** How far back to look for something readable before giving up. A room whose
 *  last dozen messages are all protocol ticks has nothing to preview. */
const SCAN = 12;

function oneLine(value: string, limit = 180): string {
  const flat = value.replace(/\s+/g, " ").trim();
  return flat.length > limit ? `${flat.slice(0, limit - 1)}…` : flat;
}

/** The prose inside a chat message. Chat carries a bare string, but a message
 *  that came in over the wire can arrive as `{"text": …}` instead, so both are
 *  unwrapped and anything else is treated as not-prose. */
function chatText(content: unknown): string {
  if (typeof content === "string") {
    const trimmed = content.trim();
    if (!trimmed.startsWith("{")) return oneLine(trimmed);
    try {
      const parsed: unknown = JSON.parse(trimmed);
      const text = (parsed as { text?: unknown })?.text;
      return typeof text === "string" ? oneLine(text) : "";
    } catch {
      return oneLine(trimmed);
    }
  }
  if (content && typeof content === "object") {
    const text = (content as { text?: unknown }).text;
    if (typeof text === "string") return oneLine(text);
  }
  return "";
}

/** The last thing that happened in a room, as one line for an inbox row.
 *
 *  Takes the transcript newest-first (the order the backend serves) and returns
 *  the newest message that reads as something a person would recognize. What a
 *  room actually said outranks what its protocol did, so a chat line is
 *  preferred over the coordination events that may sit on top of it; an event
 *  only wins when no one has spoken inside the scanned window. */
export function latestPreview(messages: RoomMessage[]): RoomPreview | null {
  const window = messages.slice(0, SCAN);
  let fallback: RoomPreview | null = null;

  for (const msg of window) {
    const type = msg.message_type ?? msg.type ?? "";
    const sender = msg.sender_handle ?? msg.updated_by ?? "";
    const at = msg.created_at ?? "";

    if (CHAT_TYPES.has(type)) {
      const text = chatText(msg.content);
      if (text) return { sender, text, at };
      continue;
    }
    // Keep only the newest event, and only as a standby — a chat line further
    // down the window still wins.
    if (!fallback && EVENT_TEXT[type]) fallback = { sender, text: EVENT_TEXT[type], at };
  }

  return fallback;
}
