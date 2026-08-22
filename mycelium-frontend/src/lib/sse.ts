// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The multiplexed stream's wire contract.
 *
 * A browser allows ~6 concurrent connections per origin over HTTP/1.1, and a
 * held `EventSource` occupies one for its whole lifetime. So what matters is
 * the number of streams held open, not what they carry: the UI holds exactly
 * one, and the SSE event *name* says which feed a frame came off.
 *
 * Shared by the server that merges the upstream feeds
 * (`src/app/api/stream/route.ts`) and the browser-side hub that fans them back
 * out (`src/lib/stream-hub.ts`).
 */

/** The feeds carried over the one connection. */
export const STREAM_CHANNELS = ["room", "app", "notification"] as const;

export type StreamChannel = (typeof STREAM_CHANNELS)[number];

/** One frame as it crosses the multiplexed stream. */
export interface StreamEnvelope {
  /** Which room a `room` frame belongs to; null on the global channels. */
  room: string | null;
  /** The upstream payload, verbatim. */
  data: unknown;
}

/** Emitted at open so `EventSource.onopen` fires even while every upstream is
 *  down — the connection is the multiplexer's, not any one feed's. */
export const STREAM_READY_EVENT = "ready";

/** How long the server waits before redialling a dropped upstream feed, and
 *  the `retry:` hint handed to the browser for the connection itself. */
export const STREAM_RETRY_MS = 5000;

export function encodeSseFrame(event: string, payload: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
}

export interface SseEvent {
  /** The `event:` field, or "message" when the frame omits one. */
  event: string;
  /** The `data:` field, with multi-line values joined by newlines. */
  data: string;
}

/**
 * Incremental SSE decoder: feed it whatever arrives off the socket, get back
 * the frames that completed. A frame ends at a blank line, which can land in
 * any chunk (or split one), so the tail is buffered until it does.
 */
export function createSseDecoder(): (chunk: string) => SseEvent[] {
  let buffer = "";
  let event = "";
  const data: string[] = [];

  return (chunk: string): SseEvent[] => {
    buffer += chunk;
    const out: SseEvent[] = [];
    let nl: number;
    while ((nl = buffer.indexOf("\n")) !== -1) {
      const line = buffer.slice(0, nl).replace(/\r$/, "");
      buffer = buffer.slice(nl + 1);

      // Blank line dispatches the frame; a frame with no data (a lone comment,
      // or a bare `retry:`) carries nothing and is dropped.
      if (line === "") {
        if (data.length > 0) out.push({ event: event || "message", data: data.join("\n") });
        event = "";
        data.length = 0;
        continue;
      }
      // Comments (`: keep-alive`) exist to hold the socket open, nothing more.
      if (line.startsWith(":")) continue;

      const colon = line.indexOf(":");
      const field = colon === -1 ? line : line.slice(0, colon);
      // One optional space after the colon is part of the framing, not the value.
      const value = colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");
      if (field === "event") event = value;
      else if (field === "data") data.push(value);
    }
    return out;
  };
}

/** The decoder above, driven off a response body. Ends when the body does. */
export async function* readSseEvents(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  const decode = createSseDecoder();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      for (const event of decode(decoder.decode(value, { stream: true }))) yield event;
    }
  } finally {
    reader.releaseLock();
  }
}
