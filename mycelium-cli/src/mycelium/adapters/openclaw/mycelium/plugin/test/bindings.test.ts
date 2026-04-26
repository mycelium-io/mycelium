// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { describe, expect, it, beforeEach } from "vitest";

import {
  bindAgentToRoom,
  clearAllBindings,
  getAllBoundRooms,
  getMostRecentRoomForAgent,
  getRoomsForAgent,
} from "../src/channel/bindings.js";

describe("channel/bindings", () => {
  beforeEach(() => clearAllBindings());

  it("registers a fresh binding and returns true", () => {
    expect(bindAgentToRoom("alpha", "room-1")).toBe(true);
    expect(getRoomsForAgent("alpha").has("room-1")).toBe(true);
  });

  it("is idempotent for repeated bindings", () => {
    expect(bindAgentToRoom("alpha", "room-1")).toBe(true);
    expect(bindAgentToRoom("alpha", "room-1")).toBe(false);
  });

  it("supports multiple rooms per agent and returns most recent", () => {
    bindAgentToRoom("alpha", "room-1");
    bindAgentToRoom("alpha", "room-2");
    bindAgentToRoom("alpha", "room-3");
    expect(getMostRecentRoomForAgent("alpha")).toBe("room-3");
    expect(getRoomsForAgent("alpha").size).toBe(3);
  });

  it("returns undefined for unknown agent", () => {
    expect(getMostRecentRoomForAgent("ghost")).toBeUndefined();
    expect(getRoomsForAgent("ghost").size).toBe(0);
  });

  it("aggregates bound rooms across all agents", () => {
    bindAgentToRoom("alpha", "room-1");
    bindAgentToRoom("alpha", "room-2");
    bindAgentToRoom("beta", "room-2");
    bindAgentToRoom("beta", "room-3");
    const all = getAllBoundRooms();
    expect(all.size).toBe(3);
    expect(all.has("room-1")).toBe(true);
    expect(all.has("room-2")).toBe(true);
    expect(all.has("room-3")).toBe(true);
  });

  it("rejects empty agentId or room", () => {
    expect(bindAgentToRoom("", "room-1")).toBe(false);
    expect(bindAgentToRoom("alpha", "")).toBe(false);
  });

  it("clearAllBindings empties the registry", () => {
    bindAgentToRoom("alpha", "room-1");
    bindAgentToRoom("beta", "room-2");
    clearAllBindings();
    expect(getAllBoundRooms().size).toBe(0);
    expect(getMostRecentRoomForAgent("alpha")).toBeUndefined();
  });
});
