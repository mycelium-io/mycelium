// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import type { Memory, Room } from "@/lib/api";
import { latestRoomOf, standingOf, withStance } from "@/lib/patterns";

const room = (name: string, pattern: string | null, created_at: string): Room => ({
  name,
  pattern,
  created_at,
  is_persistent: true,
});

describe("latestRoomOf", () => {
  it("is the newest room loaded from the pattern, and none for a pattern never run", () => {
    const rooms = [
      room("gate", "approval-gate-agent", "2026-10-01T10:00:00Z"),
      room("gate-2", "approval-gate-agent", "2026-10-02T10:00:00Z"),
      room("other", null, "2026-10-03T10:00:00Z"),
    ];
    expect(latestRoomOf(rooms, "approval-gate-agent")?.name).toBe("gate-2");
    expect(latestRoomOf(rooms, "supervisor-worker")).toBeNull();
  });
});

describe("standingOf", () => {
  const memory = (meta: Record<string, unknown> | null): Memory => ({
    key: "context/standing",
    value: "",
    version: 1,
    created_by: "system",
    updated_at: "",
    meta,
  });

  it("reads the headline, detail and state the hub wrote", () => {
    expect(standingOf(memory({ headline: "Held", detail: "Names first.", state: "running" }))).toEqual({
      headline: "Held",
      detail: "Names first.",
      state: "running",
    });
  });

  it("is nothing without a headline", () => {
    expect(standingOf(memory({ detail: "x" }))).toBeNull();
    expect(standingOf(null)).toBeNull();
  });
});

describe("withStance", () => {
  it("carries the marker the conductor reads, with a reason or a plain word", () => {
    expect(withStance("Show me the list.", "reject")).toBe("Show me the list.\n\n[[mycelium: stance=reject]]");
    expect(withStance("  ", "accept")).toBe("Approved.\n\n[[mycelium: stance=accept]]");
  });
});
