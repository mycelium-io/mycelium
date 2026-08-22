// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The UI's one held SSE connection.
 *
 * `GET /api/stream?room=<name>&room=<other>` merges every feed the page needs —
 * global app events, the notification aggregate, and one stream per open room —
 * into a single response, tagging each frame with the channel it came off (see
 * `src/lib/sse.ts`). That leaves the browser's ~6-connections-per-origin cap
 * over HTTP/1.1 to be spent on the page's REST calls.
 *
 * Each upstream feed is supervised independently: one that fails or ends is
 * redialled on a delay while the others keep flowing, so a backend hiccup on
 * one feed costs neither the client's connection nor the other feeds.
 */

import { getBackendUrl } from "@/lib/backend";
import { upstreamSseHeaders } from "@/lib/session";
import {
  STREAM_READY_EVENT,
  STREAM_RETRY_MS,
  encodeSseFrame,
  readSseEvents,
  type StreamChannel,
} from "@/lib/sse";
import { isMockMode, mockStream } from "@/mocks";

export const dynamic = "force-dynamic";

const SSE_HEADERS = {
  "Content-Type": "text/event-stream",
  "Cache-Control": "no-cache, no-transform",
  Connection: "keep-alive",
  "X-Accel-Buffering": "no",
};

/** Idle upstreams still have to be held open, or an intermediary reaps them. */
const HEARTBEAT_MS = 15_000;

/** A feed to merge in: which channel it lands on, and how to (re)open it. */
interface Source {
  channel: StreamChannel;
  room: string | null;
  open: (signal: AbortSignal) => Promise<Response>;
}

/** Rooms are a query parameter, so cap the fan-out a single request can ask
 *  the backend for. The UI opens one room at a time; this is the guard rail. */
const MAX_ROOMS = 8;

function sources(rooms: string[]): Source[] {
  const backend = getBackendUrl();
  const upstream = (path: string) => async (signal: AbortSignal) => {
    return fetch(`${backend}${path}`, {
      headers: await upstreamSseHeaders(),
      cache: "no-store",
      signal,
    });
  };

  const mock = isMockMode();
  const list: Source[] = [
    {
      channel: "app",
      room: null,
      open: mock ? idleStream : upstream("/api/events/stream"),
    },
    {
      channel: "notification",
      room: null,
      open: mock ? idleStream : upstream("/api/notifications/stream"),
    },
  ];
  for (const room of rooms) {
    list.push({
      channel: "room",
      room,
      // Fake-backend mode replays a scripted negotiation on the room channel;
      // the global channels have nothing to say, so they idle.
      open: mock
        ? async () => mockStream(room)
        : upstream(`/api/rooms/${encodeURIComponent(room)}/messages/stream`),
    });
  }
  return list;
}

/** A stream that opens and then says nothing — the mock stand-in for a feed
 *  with no scripted traffic. */
async function idleStream(): Promise<Response> {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(": idle\n\n"));
      },
    }),
    { headers: SSE_HEADERS },
  );
}

export async function GET(req: Request): Promise<Response> {
  const rooms = [
    ...new Set(
      new URL(req.url).searchParams.getAll("room").map((r) => r.trim()).filter(Boolean),
    ),
  ].slice(0, MAX_ROOMS);

  const encoder = new TextEncoder();
  const abort = new AbortController();
  let closed = false;
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  // Every redial in flight, so cancelling the response wakes them immediately
  // instead of leaving a timer holding the whole pipeline open.
  const waiting = new Set<() => void>();
  // Upstream bodies currently being read. `abort` ends the fetched ones; a mock
  // feed isn't fetched at all, so teardown cancels these directly.
  const bodies = new Set<ReadableStream<Uint8Array>>();

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const send = (chunk: string) => {
        if (closed) return;
        try {
          controller.enqueue(encoder.encode(chunk));
        } catch {
          // The client went away between the disconnect and our next write.
          closed = true;
        }
      };

      // Open the connection before any upstream answers: the client's stream is
      // live as soon as the multiplexer is, and stays live across upstream churn.
      send(`retry: ${STREAM_RETRY_MS}\n\n`);
      send(encodeSseFrame(STREAM_READY_EVENT, { rooms }));

      heartbeat = setInterval(() => send(": keep-alive\n\n"), HEARTBEAT_MS);

      for (const source of sources(rooms)) void pump(source, send);

      async function pump(source: Source, emit: (chunk: string) => void) {
        while (!closed) {
          try {
            const res = await source.open(abort.signal);
            if (res.ok && res.body) {
              const body = res.body;
              bodies.add(body);
              try {
                for await (const event of readSseEvents(body)) {
                  if (closed) break;
                  // Upstream's own open marker isn't news to the client.
                  if (event.event === "ping") continue;
                  let data: unknown;
                  try {
                    data = JSON.parse(event.data);
                  } catch {
                    continue;
                  }
                  emit(encodeSseFrame(source.channel, { room: source.room, data }));
                }
              } finally {
                bodies.delete(body);
                await body.cancel().catch(() => {});
              }
            }
          } catch {
            // Unreachable or torn-down upstream: fall through and redial.
          }
          if (closed) break;
          await sleep(STREAM_RETRY_MS);
        }
      }
    },
    cancel() {
      teardown();
    },
  });

  function teardown() {
    if (closed) return;
    closed = true;
    clearInterval(heartbeat);
    abort.abort();
    for (const body of bodies) body.cancel().catch(() => {});
    bodies.clear();
    for (const wake of waiting) wake();
    waiting.clear();
  }

  function sleep(ms: number): Promise<void> {
    return new Promise((resolve) => {
      const timer = setTimeout(done, ms);
      function done() {
        clearTimeout(timer);
        waiting.delete(done);
        resolve();
      }
      waiting.add(done);
    });
  }

  req.signal?.addEventListener("abort", teardown);

  return new Response(stream, { headers: SSE_HEADERS });
}
