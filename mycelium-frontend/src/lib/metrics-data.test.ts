// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { episodeState, rollupEpisodes, type FleetEpisode } from "@/lib/metrics-data";
import { fmtPct, subCounters } from "@/lib/metrics-format";

function ep(overrides: Partial<FleetEpisode> = {}): FleetEpisode {
  return {
    room: "atlas",
    short_id: "ep",
    episode: "urn:ioc:episode:ep",
    topic: "cutover",
    outcome: "converged",
    subkind: "converged",
    participants: ["a", "b"],
    metrics: { mpc: 0.8, gar: 0.6, scr: 0.2, provenance_weight: 0.48 },
    assignments: null,
    tasks: ["work/one"],
    message_count: 3,
    updated_at: "2026-01-01T00:00:00Z",
    updated_by: "aligner",
    ...overrides,
  };
}

describe("rollupEpisodes", () => {
  it("counts an episode by its commit subkind, not the record's outcome text", () => {
    const rollup = rollupEpisodes([
      ep({ short_id: "a" }),
      ep({ short_id: "b", subkind: "resolved", outcome: "resolved" }),
      ep({ short_id: "c", subkind: "rejected", outcome: "rejected", metrics: null }),
      ep({ short_id: "d", subkind: null, outcome: "open", metrics: null }),
    ]);

    expect(rollup.total).toBe(4);
    expect(rollup.converged).toBe(2);
    expect(rollup.rejected).toBe(1);
    expect(rollup.open).toBe(1);
  });

  it("averages quality over the episodes that carry metrics, not over all of them", () => {
    const rollup = rollupEpisodes([
      ep({ short_id: "a", metrics: { mpc: 0.9, gar: 0.8, scr: 0.1, provenance_weight: 0.72 } }),
      ep({ short_id: "b", metrics: { mpc: 0.7, gar: 0.6, scr: 0.3, provenance_weight: 0.42 } }),
      ep({ short_id: "c", subkind: null, outcome: "open", metrics: null }),
    ]);

    expect(rollup.scored).toBe(2);
    expect(rollup.mpc).toBeCloseTo(0.8);
    expect(rollup.gar).toBeCloseTo(0.7);
    expect(rollup.scr).toBeCloseTo(0.2);
  });

  it("leaves quality unclaimed when nothing has committed", () => {
    const rollup = rollupEpisodes([ep({ subkind: null, outcome: "open", metrics: null })]);

    expect(rollup.scored).toBe(0);
    expect(rollup.mpc).toBeNull();
    expect(rollup.avgParticipants).toBe(2);
  });

  it("orders the recent list newest first across rooms", () => {
    const rollup = rollupEpisodes([
      ep({ room: "atlas", short_id: "old", updated_at: "2026-01-01T00:00:00Z" }),
      ep({ room: "pricing", short_id: "new", updated_at: "2026-03-01T00:00:00Z" }),
    ]);

    expect(rollup.recent.map((e) => e.short_id)).toEqual(["new", "old"]);
    expect(rollup.tasks).toBe(2);
  });
});

describe("episodeState", () => {
  it("prefers the commit subkind over the projected outcome", () => {
    expect(episodeState(ep({ subkind: "rejected", outcome: "committed" }))).toBe("rejected");
    expect(episodeState(ep({ subkind: null, outcome: "open" }))).toBe("open");
  });
});

describe("subCounters", () => {
  const llm = {
    calls: 41,
    "by_operation.task_compile": 12,
    "by_operation.task_compile.input_tokens": 900,
    "by_operation.health_probe": 29,
    "by_model.anthropic/claude-sonnet-4-6": 41,
  };

  it("reads a dimension biggest first and drops its nested totals", () => {
    expect(subCounters(llm, "by_operation")).toEqual([
      ["health_probe", 29],
      ["task_compile", 12],
    ]);
  });

  it("keeps a dotted value whole when the dimension allows one", () => {
    expect(subCounters({ "by_model.openai/gpt-4.1": 7 }, "by_model", true)).toEqual([
      ["openai/gpt-4.1", 7],
    ]);
  });

  it("has nothing to say about a namespace the backend never touched", () => {
    expect(subCounters(undefined, "by_operation")).toEqual([]);
  });
});

describe("fmtPct", () => {
  it("reports a rate over nothing as unknown rather than zero", () => {
    expect(fmtPct(0, 0)).toBe("-");
    expect(fmtPct(undefined, 96)).toBe("0%");
    expect(fmtPct(72, 96)).toBe("75%");
  });
});
