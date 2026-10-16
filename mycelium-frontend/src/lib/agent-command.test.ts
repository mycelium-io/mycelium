// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { memoryCommand, roomCommand, taskCommand } from "./agent-command";

describe("commands for an agent", () => {
  it("reads a memory", () => {
    expect(memoryCommand("checkout", "context/api")).toBe("mycelium memory get context/api --room checkout");
  });

  it("reads a task and its thread, one command a line", () => {
    expect(taskCommand("checkout", "work/apple-pay").split("\n")).toEqual([
      "mycelium memory get work/apple-pay --room checkout",
      "mycelium board messages work/apple-pay --room checkout",
    ]);
  });

  it("catches up on a room", () => {
    expect(roomCommand("checkout").split("\n")).toEqual([
      "mycelium board --room checkout",
      "mycelium room messages --room checkout",
    ]);
  });

  it("quotes a value the shell would split", () => {
    expect(memoryCommand("my room", "notes/it's here")).toBe(
      "mycelium memory get 'notes/it'\\''s here' --room 'my room'",
    );
  });
});
