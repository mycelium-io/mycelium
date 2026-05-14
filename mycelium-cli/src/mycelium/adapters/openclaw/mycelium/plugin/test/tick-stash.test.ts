// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { beforeEach, describe, expect, it } from "vitest";

import {
  _allStashedTicks,
  clearAllTickStash,
  clearTickStashBySessionRoom,
  lookupTick,
  stashTick,
} from "../src/channel/tick-stash.js";

const log = { info: () => {}, warn: () => {} };

describe("tick-stash", () => {
  beforeEach(() => clearAllTickStash());

  it("stash + lookup round trip returns the same payload", () => {
    const payload = { round: 2, current_offer: { price: "500" }, valid_keys: ["price", "timeline"] };
    stashTick("julia-agent", "room-a:session:abc", payload, log);
    const got = lookupTick("julia-agent");
    expect(got).toBeDefined();
    expect(got!.sessionRoom).toBe("room-a:session:abc");
    expect(got!.payload).toEqual(payload);
  });

  it("returns undefined for agents that have no stashed tick", () => {
    stashTick("julia-agent", "room-a:session:abc", { round: 1 }, log);
    expect(lookupTick("selina-agent")).toBeUndefined();
  });

  it("overwrites on subsequent stashes — latest tick wins", () => {
    stashTick("julia-agent", "room-a:session:abc", { round: 1 }, log);
    stashTick("julia-agent", "room-a:session:abc", { round: 2 }, log);
    expect(lookupTick("julia-agent")!.payload).toEqual({ round: 2 });
  });

  it("clearTickStashBySessionRoom drops only entries matching that room", () => {
    stashTick("julia-agent", "room-a:session:abc", { round: 1 }, log);
    stashTick("selina-agent", "room-b:session:xyz", { round: 1 }, log);
    clearTickStashBySessionRoom("room-a:session:abc");
    expect(lookupTick("julia-agent")).toBeUndefined();
    expect(lookupTick("selina-agent")).toBeDefined();
  });

  it("clearAllTickStash empties the stash", () => {
    stashTick("julia-agent", "room-a:session:abc", { round: 1 }, log);
    stashTick("selina-agent", "room-b:session:xyz", { round: 1 }, log);
    clearAllTickStash();
    expect(_allStashedTicks().size).toBe(0);
  });

  it("records a receivedAt timestamp so consumers can reason about freshness", () => {
    const before = Date.now();
    stashTick("julia-agent", "room-a:session:abc", { round: 1 }, log);
    const after = Date.now();
    const got = lookupTick("julia-agent")!;
    expect(got.receivedAt).toBeGreaterThanOrEqual(before);
    expect(got.receivedAt).toBeLessThanOrEqual(after);
  });
});
