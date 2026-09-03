// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The notification center's data model: classifying a raw wire frame from
// `/api/notifications/stream` into something worth showing, and the
// localStorage-backed store (+ cross-tab sync) that backs the bell's inbox.
// Framework-agnostic on purpose — `notifications-provider.tsx` is the only
// React-aware consumer, so this stays unit-testable without rendering.

import { unwrapContent } from "@/lib/room-events";

export type NotificationKind = "mention" | "direct" | "consensus" | "knowledge" | "join" | "message";

export interface ClassifiedNotification {
  id: string;
  room: string;
  kind: NotificationKind;
  summary: string;
  sender: string;
  time: string;
  /** True for the kinds that ring the bell (mention/direct/consensus/knowledge);
   *  false for ambient activity that only badges (a plain broadcast or a join). */
  needsMe: boolean;
}

export interface StoredNotification extends ClassifiedNotification {
  read: boolean;
  /** True when this reached the bell inbox + sound/desktop ("loud"); false when
   *  it only bumps the room's unread badge ("quiet"). Missing on legacy entries,
   *  which were all loud — treat `!== false` as loud. */
  alert?: boolean;
}

export type NotificationScope = "needs-me" | "everything";

/** Per-room notification level (Discord-style), overriding the global default.
 *  all = every message is loud; mentions = only @you/consensus is loud, the rest
 *  just badges; muted = nothing (no badge, no bell). */
export type RoomLevel = "all" | "mentions" | "muted";

export interface NotificationSettings {
  scope: NotificationScope;
  soundEnabled: boolean;
  soundVolume: number;
  desktopEnabled: boolean;
  dnd: boolean;
  mutedRooms: string[];
  /** Per-room overrides of the scope-derived default. */
  roomLevels: Record<string, RoomLevel>;
}

export const DEFAULT_SETTINGS: NotificationSettings = {
  scope: "needs-me",
  soundEnabled: true,
  soundVolume: 0.5,
  desktopEnabled: false,
  dnd: false,
  mutedRooms: [],
  roomLevels: {},
};

/** The effective level for a room: an explicit per-room override wins, else a
 *  legacy mute reads as "muted", else the global scope's default ("everything" →
 *  all, "needs-me" → mentions). */
export function roomLevel(settings: NotificationSettings, room: string): RoomLevel {
  const override = settings.roomLevels?.[room];
  if (override) return override;
  if (settings.mutedRooms.includes(room)) return "muted";
  return settings.scope === "everything" ? "all" : "mentions";
}

/** Is this notification "loud" — bell inbox + sound/desktop — vs badge-only?
 *  Loud when the room is on "all", or the item needs you and the room isn't muted. */
export function isAlert(n: ClassifiedNotification, settings: NotificationSettings): boolean {
  const level = roomLevel(settings, n.room);
  if (level === "muted") return false;
  return level === "all" || n.needsMe;
}

const MENTION_RE = /@([\w-]+)/g;

function mentionsHandle(text: string, handle: string): boolean {
  if (!handle) return false;
  MENTION_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = MENTION_RE.exec(text))) {
    if (m[1].toLowerCase() === handle) return true;
  }
  return false;
}

/**
 * Classify one raw frame off `/api/notifications/stream` (the same wire shape
 * as a room's SSE stream, tagged with `room_name`), or return null when it
 * isn't notification-worthy — a room lifecycle frame, a keepalive, or a
 * message type this system doesn't surface (e.g. `plan_updated`, which
 * narrates the same knowledge push already carried by `l9_knowledge`).
 */
export function classify(raw: Record<string, unknown>, principal: string): ClassifiedNotification | null {
  const mtype = (raw.message_type as string) || "";
  const room = raw.room_name as string | undefined;
  if (!room) return null;

  const sender = (raw.sender_handle as string) || "system";
  const recipient = (raw.recipient_handle as string) || null;
  const time = (raw.created_at as string) || new Date().toISOString();
  const id = (raw.id as string) || `${room}:${mtype}:${time}:${sender}`;
  const handle = principal.trim().replace(/^@/, "").toLowerCase();

  const content = unwrapContent(raw);

  switch (mtype) {
    case "l9_exchange": {
      const text = (content.content as string) || "";
      // Your own post is never a notification to yourself.
      if (sender.toLowerCase() === handle) return null;
      const directed = recipient !== null && recipient.toLowerCase() === handle;
      const mentioned = mentionsHandle(text, handle);
      // A message that neither addresses nor mentions you is ambient room
      // activity: it badges the room (quiet) but doesn't ring the bell.
      const kind = directed ? "direct" : mentioned ? "mention" : "message";
      return {
        id,
        room,
        sender,
        time,
        kind,
        summary: text.slice(0, 160),
        needsMe: directed || mentioned,
      };
    }
    case "l9_commit": {
      const l9env = (content.l9 as Record<string, unknown> | undefined) ?? {};
      const header = (l9env.header as Record<string, unknown> | undefined) ?? {};
      const converged = header.subkind === "converged";
      const fallback = converged ? "Consensus reached" : "Negotiation ended without agreement";
      const text = (content.content as string) || fallback;
      return { id, room, sender, time, kind: "consensus", summary: text.slice(0, 160), needsMe: true };
    }
    case "l9_knowledge": {
      const text = (content.content as string) || "Room memory updated";
      return { id, room, sender, time, kind: "knowledge", summary: text.slice(0, 160), needsMe: true };
    }
    case "coordination_join": {
      const joinedHandle = (content.handle as string) || sender;
      return { id, room, sender, time, kind: "join", summary: `${joinedHandle} joined`, needsMe: false };
    }
    default:
      return null;
  }
}

/** Should this notification ring the bell right now — i.e. it's "loud" for the
 *  room's level and global do-not-disturb is off. (A badge-only item is stored
 *  but never admitted here.) Pure predicate; the caller decides what to do. */
export function isAdmitted(n: ClassifiedNotification, settings: NotificationSettings): boolean {
  if (settings.dnd) return false;
  return isAlert(n, settings);
}

const NOTIFICATIONS_KEY = "mycelium.notifications";
const SETTINGS_KEY = "mycelium.notification-settings";
const MAX_STORED = 200;

export function loadNotifications(): StoredNotification[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(NOTIFICATIONS_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveNotifications(list: StoredNotification[]): void {
  if (typeof window === "undefined") return;
  try {
    const trimmed = list.slice(-MAX_STORED);
    window.localStorage.setItem(NOTIFICATIONS_KEY, JSON.stringify(trimmed));
  } catch {
    // Storage quota/private-mode failures are non-fatal — in-memory state carries on.
  }
}

export function loadSettings(): NotificationSettings {
  if (typeof window === "undefined") return DEFAULT_SETTINGS;
  try {
    const raw = window.localStorage.getItem(SETTINGS_KEY);
    if (!raw) return DEFAULT_SETTINGS;
    return { ...DEFAULT_SETTINGS, ...JSON.parse(raw) };
  } catch {
    return DEFAULT_SETTINGS;
  }
}

export function saveSettings(settings: NotificationSettings): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
  } catch {
    // Same as above — best-effort persistence only.
  }
}

// ── Cross-tab coordination ───────────────────────────────────────────────

// "add" isn't part of this protocol: every open tab holds its own SSE
// connection to the same backend, so each tab independently classifies and
// stores a new notification — no need to also forward it over the channel.
// Cross-tab sync exists for the *state that isn't independently derivable*:
// read/dismiss/clear acknowledgements and settings changes.
export type CrossTabMessage =
  | { type: "read"; id: string }
  | { type: "read-all" }
  | { type: "room-read"; room: string }
  | { type: "dismiss"; id: string }
  | { type: "clear" }
  | { type: "settings"; settings: NotificationSettings };

const CHANNEL_NAME = "mycelium-notifications";

/** Thin BroadcastChannel wrapper — a no-op shim where BroadcastChannel isn't
 *  available (older Safari, some embedded webviews), so callers don't need
 *  their own feature-detection branch. */
export function openCrossTabChannel(onMessage: (msg: CrossTabMessage) => void): {
  post: (msg: CrossTabMessage) => void;
  close: () => void;
} {
  if (typeof window === "undefined" || typeof window.BroadcastChannel === "undefined") {
    return { post: () => {}, close: () => {} };
  }
  let closed = false;
  const bc = new BroadcastChannel(CHANNEL_NAME);
  bc.onmessage = (e) => onMessage(e.data as CrossTabMessage);
  return {
    // Posting on a closed channel throws InvalidStateError. React Strict Mode
    // double-mounts the provider (close → reopen), and an effect can fire a post
    // against the just-closed channel in that window — so a post after close is a
    // no-op, not a crash.
    post: (msg) => {
      if (closed) return;
      try {
        bc.postMessage(msg);
      } catch {
        // Channel closed between the guard and the post — ignore.
      }
    },
    close: () => {
      closed = true;
      bc.close();
    },
  };
}

/**
 * Elect a single "leader" tab so only one tab plays the audio ping / requests
 * a desktop Notification for a given event, even with several tabs open and
 * each independently subscribed to the SSE stream. Uses the Web Locks API
 * (broadly supported: Chrome/Edge/Firefox/Safari 15.4+) — a tab that acquires
 * the lock holds it until it closes, so leadership fails over automatically.
 * Where Web Locks is unavailable, every tab is its own leader (degrades to
 * "every open tab pings," same as no coordination at all).
 */
export function electLeader(onLeadership: (isLeader: boolean) => void): void {
  if (typeof navigator === "undefined" || !("locks" in navigator)) {
    onLeadership(true);
    return;
  }
  navigator.locks
    .request("mycelium-notification-leader", () => {
      onLeadership(true);
      return new Promise<void>(() => {
        // Held until the tab unloads (never resolves) — releasing the lock
        // hands leadership to the next queued tab automatically.
      });
    })
    .catch(() => {
      // A held-forever lock request rejects if the page unloads mid-wait;
      // nothing to recover — the tab is going away.
    });
}
