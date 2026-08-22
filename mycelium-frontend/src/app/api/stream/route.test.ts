// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSseDecoder, type SseEvent } from "@/lib/sse";

vi.mock("@/lib/backend", () => ({ getBackendUrl: () => "http://backend:8000" }));

const upstreamSseHeaders = vi.fn(async () => ({ Authorization: "Bearer t0" }));
vi.mock("@/lib/session", () => ({ upstreamSseHeaders: () => upstreamSseHeaders() }));
vi.mock("@/mocks", () => ({ isMockMode: () => false, mockStream: () => new Response() }));

import { GET } from "@/app/api/stream/route";

/** An SSE response body a test can push frames into, end, and inspect for
 *  whether the runtime actually released it. */
function upstream(status = 200) {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  const encoder = new TextEncoder();
  const cancelled = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
    cancel: cancelled,
  });
  return {
    response: new Response(body, { status }),
    cancelled,
    push: (payload: unknown) =>
      controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`)),
    ping: () => controller.enqueue(encoder.encode("event: ping\ndata: {}\n\n")),
    raw: (text: string) => controller.enqueue(encoder.encode(text)),
    end: () => controller.close(),
  };
}

/** Stub `fetch` so each feed gets its own body — a Response can only be read
 *  once, and the feeds are separate upstream connections. */
function serve(feeds: {
  app?: () => Response;
  notification?: () => Response;
  room?: (name: string) => Response;
}) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (url.endsWith("/api/events/stream")) return (feeds.app ?? (() => upstream().response))();
      if (url.endsWith("/api/notifications/stream")) {
        return (feeds.notification ?? (() => upstream().response))();
      }
      const name = decodeURIComponent(url.split("/rooms/")[1].split("/")[0]);
      return (feeds.room ?? (() => upstream().response))(name);
    }),
  );
}

/** Read frames off the multiplexed response until `want` have landed, or the
 *  response ends. */
async function collect(res: Response, want: number): Promise<SseEvent[]> {
  const reader = res.body!.getReader();
  const decoder = new TextDecoder();
  const decode = createSseDecoder();
  const frames: SseEvent[] = [];
  while (frames.length < want) {
    const { done, value } = await reader.read();
    if (done) break;
    frames.push(...decode(decoder.decode(value, { stream: true })));
  }
  await reader.cancel();
  return frames;
}

const envelopes = (frames: SseEvent[]) =>
  frames.map((f) => ({ event: f.event, ...JSON.parse(f.data) }));

describe("GET /api/stream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    upstreamSseHeaders.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  describe("feed selection", () => {
    // The global feeds must not ride the room's lifecycle: opening another room
    // re-dials only the room request, so notifications are never interrupted.
    it("serves only the global feeds when no room is asked for", async () => {
      const dialled: string[] = [];
      vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => {
          dialled.push(url);
          return upstream().response;
        }),
      );

      const res = await GET(new Request("http://ui/api/stream"));
      await collect(res, 2);

      expect(dialled).toEqual([
        "http://backend:8000/api/events/stream",
        "http://backend:8000/api/notifications/stream",
      ]);
    });

    it("serves only the room feeds when rooms are asked for", async () => {
      const dialled: string[] = [];
      vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => {
          dialled.push(url);
          return upstream().response;
        }),
      );

      const res = await GET(new Request("http://ui/api/stream?room=sprint&room=atlas"));
      await collect(res, 2);

      expect(dialled).toEqual([
        "http://backend:8000/api/rooms/sprint/messages/stream",
        "http://backend:8000/api/rooms/atlas/messages/stream",
      ]);
    });

    it("deduplicates and caps the rooms a single request can open", async () => {
      const opened: string[] = [];
      vi.stubGlobal(
        "fetch",
        vi.fn(async (url: string) => {
          opened.push(url);
          return upstream().response;
        }),
      );

      const many = Array.from({ length: 12 }, (_, i) => `room=r${i}`).join("&");
      const res = await GET(new Request(`http://ui/api/stream?room=dup&room=dup&${many}`));
      await collect(res, 1);

      expect(opened).toHaveLength(8);
      expect(opened.filter((u) => u.includes("/rooms/dup/"))).toHaveLength(1);
    });
  });

  describe("framing", () => {
    it("tags each frame with the channel and room it came off", async () => {
      const rooms = new Map([
        ["sprint", upstream()],
        ["atlas", upstream()],
      ]);
      serve({ room: (name) => rooms.get(name)!.response });

      const res = await GET(new Request("http://ui/api/stream?room=sprint&room=atlas"));
      const frames = collect(res, 4);
      await vi.advanceTimersByTimeAsync(0);
      rooms.get("atlas")!.push({ id: "a1" });
      rooms.get("sprint")!.push({ id: "s1" });

      expect(envelopes(await frames).filter((f) => f.event === "room")).toEqual([
        { event: "room", room: "atlas", data: { id: "a1" } },
        { event: "room", room: "sprint", data: { id: "s1" } },
      ]);
    });

    it("swallows an upstream's own open marker", async () => {
      const room = upstream();
      serve({ room: () => room.response });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const frames = collect(res, 2);
      await vi.advanceTimersByTimeAsync(0);
      room.ping();
      room.push({ id: "m1" });

      expect(envelopes(await frames).filter((f) => f.event === "room")).toEqual([
        { event: "room", room: "sprint", data: { id: "m1" } },
      ]);
    });

    it("drops a frame whose payload isn't JSON rather than forwarding it", async () => {
      const room = upstream();
      serve({ room: () => room.response });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const frames = collect(res, 2);
      await vi.advanceTimersByTimeAsync(0);
      room.raw("data: <html>a proxy error page</html>\n\n");
      room.push({ id: "m1" });

      expect(envelopes(await frames).filter((f) => f.event === "room")).toEqual([
        { event: "room", room: "sprint", data: { id: "m1" } },
      ]);
    });
  });

  describe("feed health", () => {
    // The response is served whether or not the backend answers, so the client
    // is told per feed rather than left to infer it from the socket.
    it("reports a feed up once it is delivering", async () => {
      const room = upstream();
      serve({ room: () => room.response });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const frames = collect(res, 1);
      await vi.advanceTimersByTimeAsync(0);

      expect(envelopes(await frames)).toEqual([
        { event: "status", channel: "room", room: "sprint", up: true },
      ]);
    });

    it("reports a feed down when its upstream is unreachable", async () => {
      serve({
        room: () => {
          throw new Error("connection refused");
        },
      });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const frames = collect(res, 1);
      await vi.advanceTimersByTimeAsync(0);

      expect(envelopes(await frames)).toEqual([
        { event: "status", channel: "room", room: "sprint", up: false },
      ]);
    });

    it("reports a feed down when its upstream drops, then up on redial", async () => {
      const first = upstream();
      const second = upstream();
      let dialled = 0;
      serve({ room: () => (++dialled === 1 ? first : second).response });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const frames = collect(res, 4);
      await vi.advanceTimersByTimeAsync(0);
      first.end();
      await vi.advanceTimersByTimeAsync(5000);
      second.push({ id: "after-reconnect" });

      expect(envelopes(await frames)).toEqual([
        { event: "status", channel: "room", room: "sprint", up: true },
        { event: "status", channel: "room", room: "sprint", up: false },
        { event: "status", channel: "room", room: "sprint", up: true },
        { event: "room", room: "sprint", data: { id: "after-reconnect" } },
      ]);
    });
  });

  describe("lifecycle", () => {
    // `bearer()` persists a refreshed session to a cookie, which only lands
    // while the request is still assembling its response. A redial minutes in
    // cannot write one, so it must reuse what the request scope resolved.
    it("resolves the upstream auth headers once, not per redial", async () => {
      const first = upstream();
      let dialled = 0;
      serve({ room: () => (++dialled === 1 ? first.response : upstream().response) });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const frames = collect(res, 3);
      await vi.advanceTimersByTimeAsync(0);
      first.end();
      await vi.advanceTimersByTimeAsync(5000);
      await frames;

      expect(dialled).toBeGreaterThan(1);
      expect(upstreamSseHeaders).toHaveBeenCalledOnce();
    });

    it("sends the resolved bearer on every upstream dial", async () => {
      serve({ room: () => upstream().response });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      await collect(res, 1);

      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        "http://backend:8000/api/rooms/sprint/messages/stream",
        expect.objectContaining({ headers: { Authorization: "Bearer t0" } }),
      );
    });

    // The token this request was built with cannot be refreshed from here, so
    // the response ends and the browser reconnects into a fresh request scope.
    it("ends the response when an upstream rejects the token", async () => {
      const unauthorized = upstream(401);
      serve({ room: () => unauthorized.response });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const reader = res.body!.getReader();
      await vi.advanceTimersByTimeAsync(0);

      // Drain to the end of the response rather than hanging on it.
      for (;;) {
        const { done } = await reader.read();
        if (done) break;
      }
      expect(unauthorized.cancelled).toHaveBeenCalled();
    });

    it("releases the body of an upstream it will not read", async () => {
      const notFound = upstream(404);
      let dialled = 0;
      serve({ room: () => (++dialled === 1 ? notFound.response : upstream().response) });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const frames = collect(res, 1);
      await vi.advanceTimersByTimeAsync(0);
      await frames;

      // Otherwise one body leaks per redial for as long as the tab is open.
      expect(notFound.cancelled).toHaveBeenCalled();
    });

    // Reading holds a lock, and cancelling the stream itself throws on a locked
    // stream — so cancellation has to go through the reader to reach the source.
    it("cancels an in-flight upstream read when the client goes away", async () => {
      const room = upstream();
      serve({ room: () => room.response });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const reader = res.body!.getReader();
      await reader.read();
      await vi.advanceTimersByTimeAsync(0);
      await reader.cancel();
      await vi.advanceTimersByTimeAsync(0);

      expect(room.cancelled).toHaveBeenCalled();
    });

    it("leaves no timers running once the client goes away", async () => {
      serve({ room: () => upstream().response });

      const res = await GET(new Request("http://ui/api/stream?room=sprint"));
      const reader = res.body!.getReader();
      await reader.read();
      await vi.advanceTimersByTimeAsync(0);
      expect(vi.getTimerCount()).toBeGreaterThan(0); // the heartbeat

      await reader.cancel();
      await vi.advanceTimersByTimeAsync(0);

      expect(vi.getTimerCount()).toBe(0);
    });

    it("aborts the upstream fetches when the client goes away", async () => {
      const aborted: boolean[] = [];
      vi.stubGlobal(
        "fetch",
        vi.fn(async (_url: string, init: RequestInit) => {
          init.signal?.addEventListener("abort", () => aborted.push(true));
          return upstream().response;
        }),
      );

      const res = await GET(new Request("http://ui/api/stream"));
      const reader = res.body!.getReader();
      await reader.read();
      await reader.cancel();
      await vi.advanceTimersByTimeAsync(0);

      expect(aborted).toHaveLength(2);
    });
  });
});
