// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The browser's single live connection.
 *
 * Every pushed update in the UI — room messages, the L9 wire, app events,
 * notifications — arrives over one `EventSource` against `/api/stream`, which
 * this module owns and fans out to subscribers by channel. Components ask for
 * the feed they care about and never touch `EventSource` themselves.
 *
 * This is the connection-count analogue of `room-data.ts`: that module makes N
 * readers of a resource share one request, this one makes N live consumers
 * share one stream. It matters because a browser allows ~6 concurrent
 * connections per origin over HTTP/1.1 and a held stream occupies one for its
 * lifetime: every stream the app parks is one the page's REST calls can't have,
 * and an exhausted pool stalls both.
 *
 * The set of open rooms is part of the URL, so subscribing to a room the
 * connection doesn't already carry reconnects it — but subscriptions are
 * deduped into that URL, so the room feed and the L9 inspector both watching
 * the same room is one connection, opened once. Navigating between rooms
 * therefore reconnects, which the room view covers by replaying the transcript
 * over REST on arrival.
 */

import { useEffect, useRef, useSyncExternalStore } from "react";
import {
  STREAM_READY_EVENT,
  STREAM_RETRY_MS,
  STREAM_CHANNELS,
  type StreamChannel,
  type StreamEnvelope,
} from "@/lib/sse";

export type StreamHandler = (data: unknown) => void;

interface Subscription {
  channel: StreamChannel;
  /** Set on `room` subscriptions; frames for any other room are not delivered. */
  room: string | null;
  handler: StreamHandler;
}

const subscriptions = new Set<Subscription>();
const statusListeners = new Set<() => void>();

let source: EventSource | null = null;
let sourceUrl: string | null = null;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let connected = false;

function streamUrl(rooms: string[]): string {
  const params = new URLSearchParams();
  for (const room of rooms) params.append("room", room);
  const query = params.toString();
  return query ? `/api/stream?${query}` : "/api/stream";
}

/** The rooms currently subscribed, in a stable order so an unchanged set
 *  produces an unchanged URL and never triggers a reconnect. */
function activeRooms(): string[] {
  const rooms = new Set<string>();
  for (const sub of subscriptions) if (sub.room) rooms.add(sub.room);
  return [...rooms].sort();
}

function setConnected(next: boolean): void {
  if (connected === next) return;
  connected = next;
  for (const listener of statusListeners) listener();
}

function dispatch(channel: StreamChannel, raw: string): void {
  let envelope: StreamEnvelope;
  try {
    envelope = JSON.parse(raw) as StreamEnvelope;
  } catch {
    return;
  }
  // Snapshot: a handler is free to unsubscribe (or mount something that
  // subscribes) while the frame is being delivered. And one consumer throwing
  // must not cost the others their frame — they no longer have their own
  // connection to fall back on.
  for (const sub of [...subscriptions]) {
    if (sub.channel !== channel) continue;
    if (sub.room !== null && sub.room !== envelope.room) continue;
    try {
      sub.handler(envelope.data);
    } catch (err) {
      console.error(`[mycelium] stream handler failed on the ${channel} channel`, err);
    }
  }
}

function close(): void {
  clearTimeout(retryTimer);
  retryTimer = undefined;
  source?.close();
  source = null;
  sourceUrl = null;
  setConnected(false);
}

function open(url: string): void {
  clearTimeout(retryTimer);
  const es = new EventSource(url);
  source = es;
  sourceUrl = url;
  es.onopen = () => setConnected(true);
  // The multiplexer's own open marker: the connection is up even while an
  // upstream feed behind it is still redialling.
  es.addEventListener(STREAM_READY_EVENT, () => setConnected(true));
  for (const channel of STREAM_CHANNELS) {
    es.addEventListener(channel, (e) => dispatch(channel, (e as MessageEvent).data));
  }
  es.onerror = () => {
    es.close();
    if (source !== es) return; // already superseded by a newer connection
    setConnected(false);
    source = null;
    sourceUrl = null;
    // Redial through `sync` rather than reopening `url`: the open room may have
    // changed while the connection was down.
    retryTimer = setTimeout(sync, STREAM_RETRY_MS);
  };
}

/**
 * Reconcile the connection with what is subscribed: the URL is a pure function
 * of the subscribed rooms, so a subscription that doesn't change it — a second
 * consumer of a room already on the wire — costs nothing.
 */
function sync(): void {
  if (typeof window === "undefined") return;
  if (subscriptions.size === 0) {
    close();
    return;
  }
  const url = streamUrl(activeRooms());
  if (url === sourceUrl) return;
  close();
  open(url);
}

function subscribe(sub: Subscription): () => void {
  subscriptions.add(sub);
  sync();
  return () => {
    subscriptions.delete(sub);
    sync();
  };
}

/** Drop the connection and every subscription. For tests. */
export function resetStreamHub(): void {
  subscriptions.clear();
  close();
  statusListeners.clear();
}

/**
 * Subscribe to a feed for as long as the component is mounted. The handler is
 * held in a ref, so a caller passing an inline function re-renders freely
 * without churning the subscription (and, through it, the connection).
 */
function useStream(channel: StreamChannel, room: string | null, handler: StreamHandler): void {
  const ref = useRef(handler);
  useEffect(() => {
    ref.current = handler;
  });
  useEffect(() => {
    return subscribe({ channel, room, handler: (data) => ref.current(data) });
  }, [channel, room]);
}

/** Live messages for one room — the room feed and the L9 wire. */
export function useRoomStream(room: string, handler: StreamHandler): void {
  useStream("room", room, handler);
}

/** Global app events: rooms created and deleted. */
export function useAppStream(handler: StreamHandler): void {
  useStream("app", null, handler);
}

/** Activity across every room, whichever one (if any) is open. */
export function useNotificationStream(handler: StreamHandler): void {
  useStream("notification", null, handler);
}

/** Whether the one connection is up — what every "Live / Reconnecting…"
 *  indicator in the app now reflects, since they all ride the same stream.
 *  Rendered as disconnected on the server, where there is no connection yet. */
export function useStreamConnected(): boolean {
  return useSyncExternalStore(
    (onChange) => {
      statusListeners.add(onChange);
      return () => {
        statusListeners.delete(onChange);
      };
    },
    () => connected,
    () => false,
  );
}
