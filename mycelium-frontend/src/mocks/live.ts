// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The mock's live half: what a write does after it lands.
 *
 * On the hub a write is followed by frames on the room's stream — the message
 * itself, `memory_changed`, a notice — and the app draws from those rather
 * than polling. The mock does the same, so a message typed in the composer
 * shows up and a filed task raises its notice.
 *
 * The REST routes and the SSE route are separate route modules, and Next's
 * dev server does not promise them one module instance, so the subscribers
 * hang off `globalThis` where both can reach them.
 */

type Listener = (frame: Record<string, unknown>) => void;

interface LiveState {
  listeners: Map<string, Set<Listener>>;
}

const g = globalThis as typeof globalThis & { __myceliumMockLive?: LiveState };
const state: LiveState = (g.__myceliumMockLive ??= { listeners: new Map() });

/** Listen to one room's frames; returns the unsubscribe. */
export function subscribe(room: string, fn: Listener): () => void {
  let set = state.listeners.get(room);
  if (!set) state.listeners.set(room, (set = new Set()));
  set.add(fn);
  return () => set.delete(fn);
}

/** Listens to every room, the way the hub's notification stream does. */
const EVERY_ROOM = "*";

/** Listen to every room's frames, each tagged with its `room_name`; returns
 *  the unsubscribe. The mock's notification feed. */
export function subscribeAll(fn: Listener): () => void {
  return subscribe(EVERY_ROOM, fn);
}

/** Put a frame on a room's stream, stamped now unless it carries a time. */
export function publish(room: string, frame: Record<string, unknown>): void {
  const stamped = { created_at: new Date().toISOString(), ...frame };
  const deliver = (set: Set<Listener> | undefined, f: Record<string, unknown>) => {
    for (const fn of set ?? []) {
      try {
        fn(f);
      } catch {
        /* a closed stream; its cancel unsubscribes it */
      }
    }
  };
  deliver(state.listeners.get(room), stamped);
  deliver(state.listeners.get(EVERY_ROOM), { room_name: room, ...stamped });
}

/** The room's live channel URN, where room-level notices ride. */
export const liveEpisode = (room: string): string => `urn:ioc:mycelium:episode:${room}:live`;

/** A board notice frame, shaped the way the persister puts one on the bus. */
export function noticeFrame(
  room: string,
  data: {
    subkind: string;
    key: string;
    title?: string;
    episode?: string | null;
    by?: string;
    kind?: string;
    for?: string;
    speakers?: string;
    released?: string;
    /** Any other flat field a subkind carries, such as a `check` notice's. */
    [field: string]: string | null | undefined;
  },
): Record<string, unknown> {
  const clean = Object.fromEntries(Object.entries(data).filter(([, v]) => v !== undefined && v !== null && v !== ""));
  return envelope(room, `notice-${data.subkind}-${data.key}-${Date.now()}`, { type: "notice", data: clean });
}

/** A thread ping: something moved in a task's thread. */
export function pingFrame(room: string, data: { episode: string; sender: string; message: string }): Record<string, unknown> {
  return envelope(room, `ping-${data.message}`, { type: "ping", data });
}

/** A control payload as the persister puts it on the bus: an exchange in `live`. */
function envelope(room: string, id: string, payload: Record<string, unknown>): Record<string, unknown> {
  const live = liveEpisode(room);
  return {
    id,
    sender_handle: "system",
    message_type: "l9_exchange",
    room_name: room,
    episode: live,
    content: {
      l9: {
        header: {
          kind: "exchange",
          message: { id, parents: [], episode: live },
          participants: { actors: [{ id: "system", role: "coordinator" }] },
        },
        payload,
      },
    },
  };
}

/** An agent is working on a reply (in a thread, when `episode` names one). */
export function respondingFrame(handle: string, episode: string | null = null, ttl = 90): Record<string, unknown> {
  return {
    type: "agent_activity",
    message_type: "agent_activity",
    handle,
    sender_handle: handle,
    state: "responding",
    episode,
    ttl_s: ttl,
  };
}

/** What the hub sends after any memory write: the app revalidates on it. */
export function memoryChangedFrame(key: string, version: number, by: string): Record<string, unknown> {
  return { type: "memory_changed", message_type: "memory_changed", key, version, updated_by: by };
}
