// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it, vi } from "vitest";
import { createSseDecoder, encodeSseFrame, readSseEvents } from "@/lib/sse";

describe("createSseDecoder", () => {
  it("reads a named frame", () => {
    const decode = createSseDecoder();
    expect(decode('event: room\ndata: {"a":1}\n\n')).toEqual([
      { event: "room", data: '{"a":1}' },
    ]);
  });

  it("defaults an unnamed frame to `message`", () => {
    const decode = createSseDecoder();
    expect(decode("data: hello\n\n")).toEqual([{ event: "message", data: "hello" }]);
  });

  it("holds a frame split across chunks until its blank line arrives", () => {
    const decode = createSseDecoder();
    expect(decode("event: ro")).toEqual([]);
    expect(decode('om\ndata: {"a":')).toEqual([]);
    expect(decode("1}\n")).toEqual([]);
    expect(decode("\n")).toEqual([{ event: "room", data: '{"a":1}' }]);
  });

  it("reads several frames out of one chunk", () => {
    const decode = createSseDecoder();
    expect(decode("event: app\ndata: 1\n\nevent: room\ndata: 2\n\n")).toEqual([
      { event: "app", data: "1" },
      { event: "room", data: "2" },
    ]);
  });

  it("joins a multi-line data field with newlines", () => {
    const decode = createSseDecoder();
    expect(decode("data: one\ndata: two\n\n")).toEqual([
      { event: "message", data: "one\ntwo" },
    ]);
  });

  it("drops comments and bare retry hints, which carry no payload", () => {
    const decode = createSseDecoder();
    expect(decode(": keep-alive\n\nretry: 5000\n\ndata: real\n\n")).toEqual([
      { event: "message", data: "real" },
    ]);
  });

  it("does not leak the event name of one frame into the next", () => {
    const decode = createSseDecoder();
    decode("event: app\ndata: 1\n\n");
    expect(decode("data: 2\n\n")).toEqual([{ event: "message", data: "2" }]);
  });

  it("handles CRLF line endings and a colon-less field", () => {
    const decode = createSseDecoder();
    expect(decode("event: app\r\ndata: 1\r\n\r\n")).toEqual([{ event: "app", data: "1" }]);
    // A bare `data` line is an empty value, not a dropped frame.
    expect(decode("data\n\n")).toEqual([{ event: "message", data: "" }]);
  });

  it("keeps a colon inside a value", () => {
    const decode = createSseDecoder();
    expect(decode('data: {"urn":"ioc:episode"}\n\n')).toEqual([
      { event: "message", data: '{"urn":"ioc:episode"}' },
    ]);
  });
});

describe("readSseEvents", () => {
  it("decodes a body whose frames straddle chunk boundaries", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode("event: room\nda"));
        controller.enqueue(encoder.encode("ta: 1\n\n: keep-alive\n\n"));
        controller.enqueue(encoder.encode("event: app\ndata: 2\n\n"));
        controller.close();
      },
    });

    const seen = [];
    for await (const event of readSseEvents(body)) seen.push(event);
    expect(seen).toEqual([
      { event: "room", data: "1" },
      { event: "app", data: "2" },
    ]);
  });
});

describe("readSseEvents cancellation", () => {
  // Reading holds a lock, and canceling the stream itself throws on a locked
  // stream — so cancellation has to reach the source through the reader.
  it("releases the underlying source when the signal aborts", async () => {
    const canceled = vi.fn();
    const body = new ReadableStream<Uint8Array>({ start() {}, cancel: canceled });
    const abort = new AbortController();

    const drained = (async () => {
      // eslint-disable-next-line @typescript-eslint/no-unused-vars
      for await (const _ of readSseEvents(body, abort.signal)) {
        // parked on a read that only cancellation will end
      }
    })();
    abort.abort();
    await drained;

    expect(canceled).toHaveBeenCalled();
  });

  it("releases the underlying source when the caller stops reading early", async () => {
    const encoder = new TextEncoder();
    const canceled = vi.fn();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode("data: 1\n\ndata: 2\n\n"));
      },
      cancel: canceled,
    });

    for await (const event of readSseEvents(body)) {
      expect(event.data).toBe("1");
      break;
    }

    expect(canceled).toHaveBeenCalled();
  });

  it("does not start reading a body whose signal has already aborted", async () => {
    const canceled = vi.fn();
    const body = new ReadableStream<Uint8Array>({ start() {}, cancel: canceled });

    const seen = [];
    for await (const event of readSseEvents(body, AbortSignal.abort())) seen.push(event);

    expect(seen).toEqual([]);
    expect(canceled).toHaveBeenCalled();
  });
});

describe("encodeSseFrame", () => {
  it("frames an event name and a JSON payload", () => {
    expect(encodeSseFrame("room", { room: "sprint", data: { id: 1 } })).toBe(
      'event: room\ndata: {"room":"sprint","data":{"id":1}}\n\n',
    );
  });

  it("round-trips through the decoder", () => {
    const decode = createSseDecoder();
    const [frame] = decode(encodeSseFrame("notification", { room: null, data: "x" }));
    expect(frame.event).toBe("notification");
    expect(JSON.parse(frame.data)).toEqual({ room: null, data: "x" });
  });
});
