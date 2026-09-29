import { describe, expect, it } from "vitest";
import { intentById, ready } from "./intents";

describe("intents", () => {
  it("says what it will send, in the engine's own grammar", () => {
    const review = intentById("review");
    expect(review.summon({ roles: { author: "codex", reviewer: "claude" }, group: [] }, "fix the flaky test")).toBe(
      "@conductor review @codex @claude: fix the flaky test",
    );
    expect(intentById("split").summon({ roles: {}, group: ["a", "b"] }, "")).toBe(
      "@conductor swarm @a @b: the task above",
    );
    expect(intentById("settle").summon({ roles: {}, group: ["a", "b"] }, "the cutover day")).toBe(
      "@aligner @a @b: the cutover day",
    );
  });

  it("is ready only with every role filled by a different agent", () => {
    const review = intentById("review");
    expect(ready(review, { roles: { author: "codex" }, group: [] })).toBe(false);
    expect(ready(review, { roles: { author: "codex", reviewer: "codex" }, group: [] })).toBe(false);
    expect(ready(review, { roles: { author: "codex", reviewer: "claude" }, group: [] })).toBe(true);
  });

  it("needs enough agents for a group intent, and none to catch up", () => {
    expect(ready(intentById("split"), { roles: {}, group: ["a"] })).toBe(false);
    expect(ready(intentById("split"), { roles: {}, group: ["a", "b"] })).toBe(true);
    expect(ready(intentById("catch-up"), { roles: {}, group: [] })).toBe(true);
  });
});
