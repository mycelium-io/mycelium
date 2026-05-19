// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

import { describe, expect, it } from "vitest";
import { buildSessionKey } from "../src/session-key.js";

describe("buildSessionKey", () => {
  it("produces the exact format OpenClaw's buildAgentPeerSessionKey emits for group peers", () => {
    // Format: agent:{agentId}:{channel}:group:{peerId}
    // See openclaw src/routing/session-key.ts:buildAgentPeerSessionKey.
    // Any change to this format WILL break routing on the OpenClaw side
    // because resolveSessionAgentId parses this string to pick the agent.
    expect(buildSessionKey("julia-agent", "my-project")).toBe(
      "agent:julia-agent:mycelium-room:group:my-project",
    );
  });

  it("lowercases the agentId", () => {
    expect(buildSessionKey("Julia-Agent", "my-project")).toBe(
      "agent:julia-agent:mycelium-room:group:my-project",
    );
  });

  it("lowercases the room name", () => {
    expect(buildSessionKey("julia-agent", "My-Project")).toBe(
      "agent:julia-agent:mycelium-room:group:my-project",
    );
  });

  it("handles single-word agent IDs", () => {
    expect(buildSessionKey("main", "default")).toBe(
      "agent:main:mycelium-room:group:default",
    );
  });

  it("handles agent IDs with numeric suffixes", () => {
    expect(buildSessionKey("exp-5988-data-engineer", "rewrite-test")).toBe(
      "agent:exp-5988-data-engineer:mycelium-room:group:rewrite-test",
    );
  });

  it("produces distinct keys for different agents in the same room", () => {
    const julia = buildSessionKey("julia", "proj");
    const selina = buildSessionKey("selina", "proj");
    expect(julia).not.toBe(selina);
  });

  it("produces distinct keys for the same agent in different rooms", () => {
    const roomA = buildSessionKey("julia", "room-a");
    const roomB = buildSessionKey("julia", "room-b");
    expect(roomA).not.toBe(roomB);
  });
});
