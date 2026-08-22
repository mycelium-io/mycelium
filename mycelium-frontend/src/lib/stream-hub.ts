// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The browser's live connections.
 *
 * Every pushed update in the UI — room messages, the L9 wire, app events,
 * notifications — arrives over a connection this module owns and fans out to
 * subscribers by channel. Components ask for the feed they care about and never
 * touch `EventSource` themselves.
 *
 * This is the connection-count analogue of `room-data.ts`: that module makes N
 * readers of a resource share one request, this one makes N live consumers
 * share one stream. It matters because a browser allows ~6 concurrent
 * connections per origin over HTTP/1.1 and a held stream occupies one for its
 * lifetime: every stream the app parks is one the page's REST calls can't have,
 * and an exhausted pool stalls both.
 *
 * There are two. Global feeds (app events, notifications) ride a connection
 * whose URL never changes, so it is never re-dialled; the open rooms ride a
 * second one, whose URL they are part of. The notification feed has no replay,
 * so its connection must survive navigation; the room feed is replayed over
 * REST when a room opens, so re-dialling that one costs nothing.
 *
 * Health is per feed, reported by the server, not inferred from the socket: the
 * multiplexer answers even when the backend behind it is down, so "the
 * connection is open" is not the same claim as "this feed is delivering".
 */

import { useCallback, useEffect, useRef, useSyncExternalStore } from "react";
import {
  STREAM_CHANNELS,
  STREAM_RETRY_MS,
  STREAM_STATUS_EVENT,
  feedKey,
  type StreamChannel,
  type StreamEnvelope,
  type StreamStatus,
} from "@/lib/sse";

export type StreamHandler = (data: unknown) => void;

interface Subscription {
  channel: StreamChannel;
  /** Set on `room` subscriptions; frames for any other room are not delivered. */
  room: string | null;
  handler: StreamHandler;
}

interface Connection {
  source: EventSource;
  /** Feeds this connection carries, and whether each is delivering. Dropped
   *  wholesale when the connection goes, so health never outlives its wire. */
  health: Map<string, boolean>;
}

const GLOBAL_URL = "/api/stream";

const subscriptions = new Set<Subscription>();
const healthListeners = new Set<() => void>();
const connections = new Map<string, Connection>();
/** Redials pending after a drop, keyed by the URL they will reopen. */
const retries = new Map<string, ReturnType<typeof setTimeout>>();

/** The URLs the current subscriptions call for: the global feeds, and the open
 *  rooms. Room order is stable so an unchanged set is an unchanged URL. */
function desiredUrls(): Set<string> {
  const urls = new Set<string>();
  const rooms = new Set<string>();
  for (const sub of subscriptions) {
    if (sub.room) rooms.add(sub.room);
    else urls.add(GLOBAL_URL);
  }
  if (rooms.size > 0) {
    const params = new URLSearchParams();
    for (const room of [...rooms].sort()) params.append("room", room);
    urls.add(`${GLOBAL_URL}?${params}`);
  }
  return urls;
}

function notifyHealth(): void {
  for (const listener of healthListeners) listener();
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

function cancelRetry(url: string): void {
  clearTimeout(retries.get(url));
  retries.delete(url);
}

function closeConnection(url: string): void {
  cancelRetry(url);
  const conn = connections.get(url);
  if (!conn) return;
  conn.source.close();
  connections.delete(url);
  if (conn.health.size > 0) notifyHealth();
}

function openConnection(url: string): void {
  cancelRetry(url);
  const conn: Connection = { source: new EventSource(url), health: new Map() };
  connections.set(url, conn);

  conn.source.addEventListener(STREAM_STATUS_EVENT, (e) => {
    let status: StreamStatus;
    try {
      status = JSON.parse((e as MessageEvent).data) as StreamStatus;
    } catch {
      return;
    }
    conn.health.set(feedKey(status.channel, status.room), status.up);
    notifyHealth();
  });

  for (const channel of STREAM_CHANNELS) {
    conn.source.addEventListener(channel, (e) => dispatch(channel, (e as MessageEvent).data));
  }

  conn.source.onerror = () => {
    conn.source.close();
    if (connections.get(url) !== conn) return; // already superseded
    connections.delete(url);
    // Its feeds are unreachable now, whatever they last reported.
    if (conn.health.size > 0) notifyHealth();
    // Redial through `sync`: the open rooms may have changed while it was down,
    // and a connection nothing subscribes to any more is not reopened at all.
    retries.set(
      url,
      setTimeout(() => {
        retries.delete(url);
        sync();
      }, STREAM_RETRY_MS),
    );
  };
}

/**
 * Reconcile the open connections with what is subscribed. Each URL is a pure
 * function of the subscriptions, so one that doesn't change — the global feeds,
 * or a room already on the wire — is left strictly alone.
 */
function sync(): void {
  if (typeof window === "undefined") return;
  const wanted = desiredUrls();
  for (const url of [...connections.keys()]) {
    if (!wanted.has(url)) closeConnection(url);
  }
  for (const url of wanted) {
    if (!connections.has(url)) openConnection(url);
  }
}

function subscribe(sub: Subscription): () => void {
  subscriptions.add(sub);
  sync();
  return () => {
    subscriptions.delete(sub);
    sync();
  };
}

/** Whether one feed is delivering, as last reported by the server. */
function isFeedUp(channel: StreamChannel, room: string | null): boolean {
  const key = feedKey(channel, room);
  for (const conn of connections.values()) {
    if (conn.health.get(key)) return true;
  }
  return false;
}

/** Drop every connection and subscription. For tests. */
export function resetStreamHub(): void {
  subscriptions.clear();
  for (const url of [...retries.keys()]) cancelRetry(url);
  for (const url of [...connections.keys()]) closeConnection(url);
  healthListeners.clear();
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

function useFeedConnected(channel: StreamChannel, room: string | null): boolean {
  const subscribeHealth = useCallback((onChange: () => void) => {
    healthListeners.add(onChange);
    return () => {
      healthListeners.delete(onChange);
    };
  }, []);
  return useSyncExternalStore(
    subscribeHealth,
    () => isFeedUp(channel, room),
    () => false,
  );
}

/** Whether this room's messages are actually arriving — what the room view's
 *  "Live / Reconnecting…" badge reports. False while the backend behind the
 *  multiplexer is unreachable, even though the connection itself is up. */
export function useRoomConnected(room: string): boolean {
  return useFeedConnected("room", room);
}

/** Whether the cross-room activity feed is arriving. */
export function useNotificationsConnected(): boolean {
  return useFeedConnected("notification", null);
}
