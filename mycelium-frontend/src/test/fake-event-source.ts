// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// A minimal EventSource stand-in for component tests. jsdom has no
// EventSource; the components open one to consume the room's SSE. Tests grab
// the latest instance and drive it (`open()`, `emit()`) to simulate the bus.
export class FakeEventSource {
  static instances: FakeEventSource[] = [];

  url: string;
  onmessage: ((e: { data: string }) => void) | null = null;
  onopen: (() => void) | null = null;
  onerror: (() => void) | null = null;
  closed = false;

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

  open(): void {
    this.onopen?.();
  }

  emit(payload: unknown): void {
    this.onmessage?.({ data: JSON.stringify(payload) });
  }

  close(): void {
    this.closed = true;
  }
}
