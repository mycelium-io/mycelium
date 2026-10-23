import { describe, expect, it } from "vitest";
import type { EpisodeSummary } from "@/lib/api";
import { runState } from "./flow-panel";

function run(over: Partial<EpisodeSummary>): EpisodeSummary {
  return {
    short_id: "e1",
    episode: "urn:ioc:mycelium:episode:demo:t1",
    topic: "",
    outcome: "open",
    subkind: null,
    participants: [],
    metrics: null,
    assignments: null,
    tasks: [],
    message_count: 0,
    updated_at: "",
    updated_by: "",
    within: null,
    flow: {
      name: "concord",
      steps: [
        { id: "score", to: "all", next: "pick" },
        { id: "agreed", end: "converged" },
        { id: "no_deal", end: "rejected" },
      ],
    },
    trace: [],
    current_step: null,
    ...over,
  } as EpisodeSummary;
}

describe("a run's state in the flow's header", () => {
  it("says the step a walking run is at, and done once it has finished", () => {
    expect(runState(run({ current_step: "score" })).said).toBe("at score");
    expect(runState(run({ outcome: "converged" })).said).toBe("done");
    expect(runState(run({ outcome: "resolved" })).said).toBe("done");
    expect(runState(run({ outcome: "rejected" })).said).toBe("rejected");
  });

  it("reads a run whose last step led to an end as finished, before its record says so", () => {
    expect(runState(run({ current_step: "agreed" }))).toEqual({ said: "done", tone: "var(--green)" });
    expect(runState(run({ current_step: "no_deal" })).said).toBe("rejected");
  });
});
