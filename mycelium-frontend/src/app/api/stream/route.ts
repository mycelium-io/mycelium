// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The UI's held SSE connections.
 *
 * `GET /api/stream` serves the global feeds — app events and the notification
 * aggregate. `GET /api/stream?room=<name>&room=<other>` serves those rooms'
 * message feeds. Either way the response is one stream carrying many feeds,
 * each frame tagged with the channel it came off (see `src/lib/sse.ts`), so the
 * browser's ~6-connections-per-origin cap over HTTP/1.1 is left for the page's
 * REST calls.
 *
 * The split is what keeps the global feeds off the room's lifecycle: opening a
 * different room re-dials only the room request, so notifications — which the
 * backend does not replay — are not interrupted by navigation.
 *
 * Each upstream feed is supervised independently: one that fails or ends is
 * redialed on a delay while the others keep flowing, and its health is
 * reported to the client as a `status` frame rather than inferred from whether
 * the connection is up.
 */

import { getBackendUrl } from "@/lib/backend";
import { upstreamSseHeaders } from "@/lib/session";
import {
  STREAM_RETRY_MS,
  STREAM_STATUS_EVENT,
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

/** Rooms are a query parameter, so cap the fan-out a single request can ask
 *  the backend for. The UI opens one room at a time; this is the guard rail. */
const MAX_ROOMS = 8;

/** A feed to merge in: which channel it lands on, and how to (re)open it. */
interface Source {
  channel: StreamChannel;
  room: string | null;
  open: (signal: AbortSignal) => Promise<Response>;
}

/**
 * The feeds this request carries. Auth headers are resolved once, by the
 * caller, and reused for every redial: `bearer()` writes a refreshed session
 * back to a cookie, which only lands while the request is still assembling its
 * response. A redial minutes into a stream cannot persist one, so it must not
 * try — an upstream 401 ends the response instead, and the browser's reconnect
 * refreshes the token in a request scope where the write survives.
 */
function sources(rooms: string[], headers: Record<string, string>): Source[] {
  const backend = getBackendUrl();
  const upstream = (path: string) => (signal: AbortSignal) =>
    fetch(`${backend}${path}`, { headers, cache: "no-store", signal });

  const mock = isMockMode();
  if (rooms.length > 0) {
    return rooms.map((room) => ({
      channel: "room" as const,
      room,
      // Fake-backend mode replays a scripted negotiation on the room channel.
      open: mock
        ? async () => mockStream(room)
        : upstream(`/api/rooms/${encodeURIComponent(room)}/messages/stream`),
    }));
  }
  return [
    { channel: "app", room: null, open: mock ? idleStream : upstream("/api/events/stream") },
    {
      channel: "notification",
      room: null,
      open: mock ? idleStream : upstream("/api/notifications/stream"),
    },
  ];
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

  // Resolved here, in the request scope, where a refreshed session can still be
  // written back to a cookie. See `sources`.
  const headers = await upstreamSseHeaders();

  const encoder = new TextEncoder();
  const abort = new AbortController();
  let controller: ReadableStreamDefaultController<Uint8Array> | undefined;
  let closed = false;
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  // Every redial in flight, so tearing down wakes them immediately instead of
  // leaving a timer holding the whole pipeline open.
  const waiting = new Set<() => void>();

  const stream = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
      const send = (chunk: string) => {
        if (closed) return;
        try {
          c.enqueue(encoder.encode(chunk));
        } catch {
          // The client went away between its disconnect and this write; the
          // pumps, heartbeat and upstream sockets still have to be released.
          teardown();
        }
      };

      const report = (source: Source, up: boolean) =>
        send(
          encodeSseFrame(STREAM_STATUS_EVENT, { channel: source.channel, room: source.room, up }),
        );

      send(`retry: ${STREAM_RETRY_MS}\n\n`);
      heartbeat = setInterval(() => send(": keep-alive\n\n"), HEARTBEAT_MS);

      for (const source of sources(rooms, headers)) void pump(source);

      async function pump(source: Source) {
        while (!closed) {
          try {
            const res = await source.open(abort.signal);
            if (res.status === 401) {
              // The token this request was built with has expired. End the
              // response so the browser reconnects and mints a fresh one.
              await res.body?.cancel().catch(() => {});
              teardown();
              return;
            }
            if (res.ok && res.body) {
              report(source, true);
              for await (const event of readSseEvents(res.body, abort.signal)) {
                if (closed) break;
                // Upstream's own open marker isn't news to the client.
                if (event.event === "ping") continue;
                let data: unknown;
                try {
                  data = JSON.parse(event.data);
                } catch {
                  continue;
                }
                send(encodeSseFrame(source.channel, { room: source.room, data }));
              }
            } else {
              // Nothing will read this body; release it rather than leak one
              // per redial for as long as the tab stays open.
              await res.body?.cancel().catch(() => {});
            }
          } catch {
            // Unreachable or torn-down upstream: fall through and redial.
          }
          if (closed) break;
          report(source, false);
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
    // Ends the fetched upstreams, and cancels the readers on mock feeds, which
    // are never fetched and so have no request to abort.
    abort.abort();
    for (const wake of waiting) wake();
    waiting.clear();
    // End the client's stream too, or a teardown we initiated (an upstream 401)
    // leaves the browser holding a response that will never say another word.
    try {
      controller?.close();
    } catch {
      // Already closed or errored by the client's own disconnect.
    }
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
