// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  layoutFlow,
  stepStates,
  stepWho,
  takenEdges,
  COLUMN_NODE_W,
  GAP_X,
  GAP_Y,
  LANE_GAP,
  LOOP_BASE,
  NODE_H,
  NODE_W,
  PAD,
} from "@/lib/flow-graph";
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

  it("draws a branch as one edge per target, stances joined, and marks the loop back", () => {
    const layout = layoutFlow(gated);
    expect(layout.direction).toBe("row");
    expect(layout.edges).toEqual([
      { from: "propose", to: "review", label: null, back: false, rail: null },
      { from: "review", to: "approved", label: "accept", back: false, rail: null },
      { from: "review", to: "propose", label: "reject / default", back: true, rail: 0 },
    ]);
    expect(layout.height).toBe(PAD * 2 + NODE_H + LOOP_BASE + LANE_GAP);
  });

  it("leaves no room for loops when there are none", () => {
    const line: EpisodeFlow = { name: "x", steps: [{ id: "a", to: "each", next: "d" }, { id: "d", end: "resolved" }] };
    expect(layoutFlow(line).height).toBe(PAD * 2 + NODE_H);
    expect(layoutFlow(line).edges).toEqual([{ from: "a", to: "d", label: null, back: false, rail: null }]);
  });

  it("stands a longer flow as a column, loops on the left and skips on the right", () => {
    const train: EpisodeFlow = {
      name: "train",
      steps: [
        { id: "plan", to: "each", next: "review" },
        { id: "review", to: "each", next: { accept: "ship", reject: "plan", silent: "escalate" } },
        { id: "escalate", to: "each", next: { accept: "ship", default: "escalate" } },
        { id: "ship", end: "resolved" },
      ],
    };
    const layout = layoutFlow(train);
    expect(layout.direction).toBe("column");
    // Two loops (review→plan, escalate→escalate) take two lanes on the left,
    // so the column starts past them; one skip (review→ship) takes a lane on
    // the right.
    expect(layout.nodes.map((n) => n.x)).toEqual([PAD + 2 * LANE_GAP, PAD + 2 * LANE_GAP, PAD + 2 * LANE_GAP, PAD + 2 * LANE_GAP]);
    expect(layout.nodes.map((n) => n.y)).toEqual([PAD, PAD + NODE_H + GAP_Y, PAD + 2 * (NODE_H + GAP_Y), PAD + 3 * (NODE_H + GAP_Y)]);
    expect(layout.width).toBe(PAD * 2 + 2 * LANE_GAP + COLUMN_NODE_W + LANE_GAP);
    expect(layout.height).toBe(PAD * 2 + 4 * NODE_H + 3 * GAP_Y);
    expect(layout.edges).toEqual([
      { from: "plan", to: "review", label: null, back: false, rail: null },
      { from: "review", to: "ship", label: "accept", back: false, rail: 0 },
      { from: "review", to: "plan", label: "reject", back: true, rail: 0 },
      { from: "review", to: "escalate", label: "silent", back: false, rail: null },
      { from: "escalate", to: "ship", label: "accept", back: false, rail: null },
      { from: "escalate", to: "escalate", label: "default", back: true, rail: 1 },
    ]);
  });

  it("reads a group target in plain words", () => {
    expect(stepWho({ id: "x", to: "each" }, gated)).toBe("everyone");
    expect(stepWho({ id: "x", to: "workers" }, gated)).toBe("the workers");
    // With a cast on the flow, a group step names who it asks: everyone for
    // each/all, everyone not bound to a role for workers.
    const cast = { ...gated, bound: { proposer: "api" }, cast: ["api", "sec", "ops"] };
    expect(stepWho({ id: "x", to: "each" }, cast)).toBe("api, sec, ops");
    expect(stepWho({ id: "x", to: "workers" }, cast)).toBe("sec, ops");
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
