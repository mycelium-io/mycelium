// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// EventSource mock for testing; tests drive instances via open()/emit*().
//
// The app holds one multiplexed connection (`/api/stream`, see lib/sse.ts), so
// a frame names its channel and carries a `{room, data}` envelope. The emit
// helpers build that framing, taking the room from the URL the hub dialled.

import type { StreamChannel } from "@/lib/sse";

type Listener = (e: { data: string }) => void;

export class FakeEventSource {
  static instances: FakeEventSource[] = [];

  url: string;
  onmessage: Listener | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

  private listeners = new Map<string, Set<Listener>>();

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  static reset(): void {
    FakeEventSource.instances = [];
  }

  static latest(): FakeEventSource {
    const es = FakeEventSource.instances.at(-1);
    if (!es) throw new Error("no EventSource was constructed");
    return es;
  }

  addEventListener(type: string, listener: Listener): void {
    const set = this.listeners.get(type) ?? new Set();
    set.add(listener);
    this.listeners.set(type, set);
  }

  removeEventListener(type: string, listener: Listener): void {
    this.listeners.get(type)?.delete(listener);
  }

  open(): void {
    this.onopen?.();
  }

  /** Raw dispatch on a named event; `message` also reaches `onmessage`. */
  emitRaw(type: string, data: string): void {
    if (type === "message") this.onmessage?.({ data });
    for (const listener of this.listeners.get(type) ?? []) listener({ data });
  }

  /** One frame on a multiplexed channel, in the envelope the hub expects. */
  emitChannel(channel: StreamChannel, payload: unknown, room: string | null): void {
    this.emitRaw(channel, JSON.stringify({ room, data: payload }));
  }

  /** A room frame for the room this connection was opened against. */
  emit(payload: unknown): void {
    this.emitChannel("room", payload, this.room());
  }

  emitApp(payload: unknown): void {
    this.emitChannel("app", payload, null);
  }

  emitNotification(payload: unknown): void {
    this.emitChannel("notification", payload, null);
  }

  /** The first room in the dialled URL — what `emit()` addresses. */
  room(): string | null {
    const query = this.url.slice(this.url.indexOf("?") + 1);
    return new URLSearchParams(query).get("room");
  }

  close(): void {
    this.closed = true;
  }
}
