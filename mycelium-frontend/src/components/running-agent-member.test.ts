// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { sessionsNote } from "@/components/running-agent-member";

describe("sessionsNote", () => {
  it("names the agent CLIs whose sessions can be brought in, as a sentence", () => {
    expect(sessionsNote(["Claude Code", "Codex"])).toBe("Sessions can be brought in from Claude Code and Codex so far.");
    expect(sessionsNote(["Claude Code", "Codex", "Cursor Agent"])).toBe(
      "Sessions can be brought in from Claude Code, Codex, and Cursor Agent so far.",
    );
    expect(sessionsNote(["Codex"])).toBe("Sessions can be brought in from Codex so far.");
    expect(sessionsNote([])).toBe("Sessions can't be brought in from these machines yet.");
  });
});
