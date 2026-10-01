import { describe, expect, it } from "vitest";
import { agentLabel } from "./agent-label";

describe("agentLabel", () => {
  it("names the agent CLI an agent runs, not how it takes part", () => {
    expect(agentLabel({ adapter: "claude_code", kind: null, framework: "codex" })).toBe("codex");
  });

  it("falls back to the adapter when nothing recorded the CLI", () => {
    expect(agentLabel({ adapter: "claude_code", kind: null })).toBe("claude_code");
    expect(agentLabel({ adapter: "a2a", kind: null, framework: null })).toBe("a2a");
  });

  it("names an engine by what it runs", () => {
    expect(agentLabel({ adapter: "engine", kind: "aligner", framework: null })).toBe("engine · aligner");
  });
});
