// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { layoutFlow, stepStates, stepWho, takenEdges, NODE_W, GAP_X, PAD, LOOP_H, NODE_H } from "@/lib/flow-graph";
import type { EpisodeFlow } from "@/lib/api";

const gated: EpisodeFlow = {
  name: "gated",
  roles: ["proposer", "guardian"],
  bound: { proposer: "api", guardian: "sec" },
  steps: [
    { id: "propose", to: "proposer", next: "review" },
    { id: "review", to: "guardian", next: { accept: "approved", reject: "propose", default: "propose" } },
    { id: "approved", end: "resolved" },
  ],
};

describe("laying out a flow", () => {
  it("ranks steps in declaration order, left to right", () => {
    const layout = layoutFlow(gated);
    expect(layout.nodes.map((n) => n.id)).toEqual(["propose", "review", "approved"]);
    expect(layout.nodes.map((n) => n.x)).toEqual([PAD, PAD + NODE_W + GAP_X, PAD + 2 * (NODE_W + GAP_X)]);
    expect(layout.width).toBe(PAD * 2 + 3 * NODE_W + 2 * GAP_X);
  });

  it("names who each step is put to, and what an end step does", () => {
    const [propose, review, approved] = layoutFlow(gated).nodes;
    expect(propose.who).toBe("api");
    expect(propose.what).toBe("asks proposer");
    expect(review.who).toBe("sec");
    expect(approved.who).toBeNull();
    expect(approved.what).toBe("ends resolved");
    expect(approved.end).toBe("resolved");
  });

  it("draws a branch as one edge per stance and marks the loop back", () => {
    const layout = layoutFlow(gated);
    expect(layout.edges).toEqual([
      { from: "propose", to: "review", label: null, back: false },
      { from: "review", to: "approved", label: "accept", back: false },
      { from: "review", to: "propose", label: "reject", back: true },
      { from: "review", to: "propose", label: "default", back: true },
    ]);
    expect(layout.height).toBe(PAD * 2 + NODE_H + LOOP_H);
  });

  it("leaves no room for loops when there are none", () => {
    const line: EpisodeFlow = { name: "x", steps: [{ id: "a", to: "each", next: "d" }, { id: "d", end: "resolved" }] };
    expect(layoutFlow(line).height).toBe(PAD * 2 + NODE_H);
    expect(layoutFlow(line).edges).toEqual([{ from: "a", to: "d", label: null, back: false }]);
  });

  it("reads a group target in plain words", () => {
    expect(stepWho({ id: "x", to: "each" }, gated)).toBe("everyone");
    expect(stepWho({ id: "x", to: "workers" }, gated)).toBe("the workers");
    expect(stepWho({ id: "x", to: "lead" }, { name: "f", steps: [] })).toBe("lead");
  });
});

describe("where a run stands", () => {
  const trace = [
    { step: "propose", turn: 1, stance: null, next: "review" },
    { step: "review", turn: 2, stance: "reject", next: "propose" },
  ];

  it("lights the current step of an open run and dims what it has taken", () => {
    const states = stepStates(gated, trace, "propose", "open");
    expect(states.get("propose")).toBe("current");
    expect(states.get("review")).toBe("visited");
    expect(states.get("approved")).toBe("untouched");
  });

  it("marks the end a finished run reached", () => {
    const done = [...trace, { step: "propose", turn: 3, stance: null, next: "review" }, { step: "review", turn: 4, stance: "accept", next: "approved" }];
    const states = stepStates(gated, done, null, "resolved");
    expect(states.get("approved")).toBe("reached");
    expect(states.get("review")).toBe("visited");
  });

  it("stands at the first step before anything was taken", () => {
    expect(stepStates(gated, [], "propose", "open").get("propose")).toBe("current");
  });

  it("knows which edges were taken", () => {
    expect([...takenEdges(trace)]).toEqual(["propose→review", "review→propose"]);
  });
});
