// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";

import { loadsHere } from "@/lib/room-image";

const ORIGIN = "http://127.0.0.1:3717";

describe("which images load in the reader's app", () => {
  it("loads one the app serves, by path or by its own address", () => {
    expect(loadsHere("/api/rooms/checkout/uploads/a.png/raw", ORIGIN)).toBe(true);
    expect(loadsHere("uploads/a.png", ORIGIN)).toBe(true);
    expect(loadsHere(`${ORIGIN}/api/rooms/checkout/uploads/a.png/raw`, ORIGIN)).toBe(true);
  });

  it("doesn't load one from another site, port or scheme", () => {
    expect(loadsHere("https://tracker.example/pixel.png", ORIGIN)).toBe(false);
    expect(loadsHere("//tracker.example/pixel.png", ORIGIN)).toBe(false);
    expect(loadsHere("http://127.0.0.1:8080/a.png", ORIGIN)).toBe(false);
    expect(loadsHere("data:image/png;base64,AAAA", ORIGIN)).toBe(false);
  });

  it("doesn't load anything when there's no address or no page to compare with", () => {
    expect(loadsHere("", ORIGIN)).toBe(false);
    expect(loadsHere("/a.png", "")).toBe(false);
  });
});
