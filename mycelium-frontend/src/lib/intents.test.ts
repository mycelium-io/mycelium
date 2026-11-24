import { describe, expect, it } from "vitest";
import { intentById, ready } from "./intents";

describe("intents", () => {
  it("says what it will send, in the engine's own grammar", () => {
    const review = intentById("review");
    expect(review.summon({ roles: { author: "codex", reviewer: "claude" }, group: [] }, "fix the flaky test")).toBe(
      "@conductor review @codex @claude: fix the flaky test",
    );
    expect(review.summon({ roles: { author: "codex", reviewer: "claude" }, group: [] }, "")).toBe(
      "@conductor review @codex @claude: the task above",
    );
  });

  it("is ready only with every role filled by a different agent", () => {
    const review = intentById("review");
    expect(ready(review, { roles: { author: "codex" }, group: [] })).toBe(false);
    expect(ready(review, { roles: { author: "codex", reviewer: "codex" }, group: [] })).toBe(false);
    expect(ready(review, { roles: { author: "codex", reviewer: "claude" }, group: [] })).toBe(true);
  });

  it("needs no agents to catch up", () => {
    expect(ready(intentById("catch-up"), { roles: {}, group: [] })).toBe(true);
  });

  it("files a plain task without summoning anything", () => {
    const task = intentById("task");
    expect(ready(task, { roles: {}, group: [] })).toBe(true);
    expect(task.summon({ roles: {}, group: [] }, "anything")).toBe("");
  });
});
