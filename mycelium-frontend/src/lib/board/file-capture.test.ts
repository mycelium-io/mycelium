import { describe, expect, it } from "vitest";

import { parseCapture } from "./capture";
import { extraFields, taskRequest } from "./file-capture";

const NOW = "2026-09-24T12:00:00.000Z";

describe("filing a capture", () => {
  it("files the task for its owner, with the rest as fields", () => {
    const parsed = parseCapture("fix the flaky tests @agent-2 !! #ci", "julia", NOW);
    expect(taskRequest(parsed, "julia")).toEqual({
      title: "fix the flaky tests",
      handle: "julia",
      assignee: "agent-2",
    });
    expect(extraFields(parsed)).toEqual({ priority: "urgent", tags: ["ci"] });
  });

  it("files a question as a decision", () => {
    const parsed = parseCapture("which store for sessions?", "julia", NOW);
    expect(taskRequest(parsed, "julia").key).toMatch(/^decisions\/which-store-for-sessions/);
  });

  it("leaves out what the line did not set", () => {
    const parsed = parseCapture("write the FAQ", "julia", NOW);
    expect(taskRequest(parsed, "julia")).toEqual({ title: "write the FAQ", handle: "julia" });
    expect(extraFields(parsed)).toEqual({});
  });
});
