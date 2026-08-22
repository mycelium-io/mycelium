// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSseDecoder, type SseEvent } from "@/lib/sse";

vi.mock("@/lib/backend", () => ({ getBackendUrl: () => "http://backend:8000" }));
vi.mock("@/lib/session", () => ({ upstreamSseHeaders: async () => ({}) }));
vi.mock("@/mocks", () => ({ isMockMode: () => false, mockStream: () => new Response() }));

import { GET } from "@/app/api/stream/route";

/** An SSE response body a test can push frames into and later end. */
function upstream() {
  let controller: ReadableStreamDefaultController<Uint8Array>;
  const encoder = new TextEncoder();
  const body = new ReadableStream<Uint8Array>({
    start(c) {
      controller = c;
    },
  });
  return {
    response: new Response(body, { status: 200 }),
    push: (payload: unknown) =>
      controller.enqueue(encoder.encode(`data: ${JSON.stringify(payload)}\n\n`)),
    ping: () => controller.enqueue(encoder.encode("event: ping\ndata: {}\n\n")),
    raw: (text: string) => controller.enqueue(encoder.encode(text)),
    end: () => controller.close(),
  };
}

/** Stub `fetch` so each feed gets its own body — a Response can only be read
 *  once, and the three sources are three separate upstream connections. */
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

/** Read frames off the multiplexed response until `want` of them have landed. */
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
  frames.map((f) => ({ channel: f.event, ...JSON.parse(f.data) }));

describe("GET /api/stream", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("merges every upstream feed onto one response, tagged by channel", async () => {
    const app = upstream();
    const notifications = upstream();
    const room = upstream();
    serve({
      app: () => app.response,
      notification: () => notifications.response,
      room: () => room.response,
    });

    const res = await GET(new Request("http://ui/api/stream?room=sprint"));
    expect(res.headers.get("Content-Type")).toBe("text/event-stream");

    const frames = collect(res, 4);
    await vi.advanceTimersByTimeAsync(0);
    app.push({ type: "room_created" });
    notifications.push({ id: "n1" });
    room.push({ id: "m1" });

    expect(envelopes(await frames)).toEqual([
      // The connection is live before any upstream has spoken.
      { channel: "ready", rooms: ["sprint"] },
      { channel: "app", room: null, data: { type: "room_created" } },
      { channel: "notification", room: null, data: { id: "n1" } },
      { channel: "room", room: "sprint", data: { id: "m1" } },
    ]);
  });

  it("carries one channel per open room", async () => {
    const rooms = new Map([
      ["sprint", upstream()],
      ["atlas", upstream()],
    ]);
    serve({ room: (name) => rooms.get(name)!.response });

    const res = await GET(new Request("http://ui/api/stream?room=sprint&room=atlas"));
    const frames = collect(res, 3);
    await vi.advanceTimersByTimeAsync(0);
    rooms.get("atlas")!.push({ id: "a1" });
    rooms.get("sprint")!.push({ id: "s1" });

    expect(envelopes(await frames).slice(1)).toEqual([
      { channel: "room", room: "atlas", data: { id: "a1" } },
      { channel: "room", room: "sprint", data: { id: "s1" } },
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

    expect(envelopes(await frames)[1]).toEqual({
      channel: "room",
      room: "sprint",
      data: { id: "m1" },
    });
  });

  it("redials a feed that drops, without dropping the client's connection", async () => {
    const first = upstream();
    const second = upstream();
    let dialled = 0;
    serve({ room: () => (++dialled === 1 ? first : second).response });

    const res = await GET(new Request("http://ui/api/stream?room=sprint"));
    const frames = collect(res, 2);
    await vi.advanceTimersByTimeAsync(0);
    first.end();

    // The client's stream stays open across the gap; the feed comes back on the
    // retry delay and its next frame lands on the same connection.
    await vi.advanceTimersByTimeAsync(5000);
    second.push({ id: "after-reconnect" });

    expect(envelopes(await frames)[1]).toEqual({
      channel: "room",
      room: "sprint",
      data: { id: "after-reconnect" },
    });
  });

  it("stays open when an upstream is unreachable from the start", async () => {
    const room = upstream();
    serve({
      app: () => {
        throw new Error("connection refused");
      },
      notification: () => new Response("nope", { status: 502 }),
      room: () => room.response,
    });

    const res = await GET(new Request("http://ui/api/stream?room=sprint"));
    const frames = collect(res, 2);
    await vi.advanceTimersByTimeAsync(0);
    room.push({ id: "m1" });

    expect(envelopes(await frames)).toEqual([
      { channel: "ready", rooms: ["sprint"] },
      { channel: "room", room: "sprint", data: { id: "m1" } },
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

    expect(envelopes(await frames)[1]).toEqual({
      channel: "room",
      room: "sprint",
      data: { id: "m1" },
    });
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
    const frames = collect(res, 1);
    await vi.advanceTimersByTimeAsync(0);
    await frames;

    const roomFeeds = opened.filter((u) => u.includes("/rooms/"));
    expect(roomFeeds).toHaveLength(8);
    expect(roomFeeds.filter((u) => u.includes("/rooms/dup/"))).toHaveLength(1);
  });

  it("tears the upstream feeds down when the client goes away", async () => {
    const aborted: boolean[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init: RequestInit) => {
        init.signal?.addEventListener("abort", () => aborted.push(true));
        return upstream().response;
      }),
    );

    const res = await GET(new Request("http://ui/api/stream?room=sprint"));
    const reader = res.body!.getReader();
    await reader.read();
    await reader.cancel();
    await vi.advanceTimersByTimeAsync(0);

    expect(aborted).toHaveLength(3);
  });
});
