// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { floorLabel, floorsByHandle } from "@/lib/floors";
import type { RoomFloor } from "@/lib/api";

const floor = (over: Partial<RoomFloor> = {}): RoomFloor => ({
  thread: "t3aa11bb",
  episode: "urn:ioc:mycelium:episode:atlas:t3aa11bb",
  holder: "conductor",
  speakers: ["api"],
  ...over,
});

describe("the floor, read for the roster", () => {
  it("folds a floor onto its holder and every speaker, by lowercased handle", () => {
    const byHandle = floorsByHandle([floor({ speakers: ["API", "sec"] })]);
    expect([...byHandle.keys()].sort()).toEqual(["api", "conductor", "sec"]);
  });

  it("keeps one entry per handle across threads", () => {
    const a = floor();
    const b = floor({ thread: "t9", holder: "reviewer", speakers: ["sec"] });
    const byHandle = floorsByHandle([a, b]);
    expect(byHandle.get("api")).toBe(a);
    expect(byHandle.get("sec")).toBe(b);
    expect(byHandle.size).toBe(4);
  });

  it("says a speaker has the floor and the holder holds it, naming the thread", () => {
    const f = floor();
    expect(floorLabel("api", f)).toBe("has the floor · t3aa11bb");
    expect(floorLabel("Conductor", f)).toBe("holds the floor · t3aa11bb");
  });

  it("reads nothing when no floor is held", () => {
    expect(floorsByHandle([]).size).toBe(0);
  });
});
