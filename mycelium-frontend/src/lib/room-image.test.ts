// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";

import { loadsHere } from "@/lib/room-image";

const ORIGIN = "http://127.0.0.1:3717";

describe("which images load in the reader's app", () => {
  it("loads a room upload's bytes or thumbnail, by path or by the app's own address", () => {
    expect(loadsHere("/api/rooms/checkout/uploads/a.png/raw", ORIGIN)).toBe(true);
    expect(loadsHere("/api/rooms/checkout/uploads/a.png/thumb", ORIGIN)).toBe(true);
    expect(loadsHere("/api/rooms/my%20room/uploads/chart%202.png/raw", ORIGIN)).toBe(true);
    expect(loadsHere(`${ORIGIN}/api/rooms/checkout/uploads/a.png/raw`, ORIGIN)).toBe(true);
  });

  it("loads one with the desktop app's signature on it", () => {
    expect(loadsHere("/api/rooms/checkout/uploads/a.png/raw?exp=1790000000&sig=abc", ORIGIN)).toBe(true);
  });

  it("doesn't load any other path on the app's own origin", () => {
    // The runner's long-poll hands over the next job to whoever asks.
    expect(loadsHere("/api/runners/r1/jobs/next", ORIGIN)).toBe(false);
    expect(loadsHere("/api/rooms/checkout/uploads/a.png", ORIGIN)).toBe(false);
    expect(loadsHere("/api/rooms/checkout/board", ORIGIN)).toBe(false);
    expect(loadsHere("/api/rooms/checkout/uploads/a.png/raw/../../../../runners/r1/jobs/next", ORIGIN)).toBe(false);
    expect(loadsHere("uploads/a.png", ORIGIN)).toBe(false);
    expect(loadsHere("/room/checkout", ORIGIN)).toBe(false);
  });

  it("doesn't load one from another site, port or scheme", () => {
    expect(loadsHere("https://tracker.example/api/rooms/x/uploads/a.png/raw", ORIGIN)).toBe(false);
    expect(loadsHere("//tracker.example/pixel.png", ORIGIN)).toBe(false);
    expect(loadsHere("http://127.0.0.1:8080/api/rooms/x/uploads/a.png/raw", ORIGIN)).toBe(false);
    expect(loadsHere("data:image/png;base64,AAAA", ORIGIN)).toBe(false);
  });

  it("doesn't load anything when there's no address or no page to compare with", () => {
    expect(loadsHere("", ORIGIN)).toBe(false);
    expect(loadsHere("/api/rooms/checkout/uploads/a.png/raw", "")).toBe(false);
  });
});
