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
import type { EpisodeFlow, FlowTraceEntry } from "@/lib/api";

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

// The concord built-in as the hub's `protocols.spec_of` hands it over (prompts
// left out): a pick node, three ways out of it, and the loop back to the pick.
const concord: EpisodeFlow = {
  name: "concord",
  roles: [],
  cast: ["success", "finance", "legal"],
  steps: [
    { id: "propose", to: "all", collect: "options", next: "score" },
    { id: "score", to: "all", collect: "scores", next: "pick" },
    {
      id: "pick",
      kind: "select",
      threshold: 0.7,
      max_repairs: 2,
      next: { feasible: "agreed", infeasible: "repair", stuck: "no_deal" },
    },
    { id: "repair", to: "bottleneck", collect: "options", next: "rescore" },
    { id: "rescore", to: "all", collect: "scores", next: "pick" },
    { id: "agreed", end: "converged" },
    { id: "no_deal", end: "rejected" },
  ],
};

describe("laying out an agreement flow", () => {
  it("draws the pick as a pick, and the fix as the least happy member's", () => {
    const layout = layoutFlow(concord);
    const node = (id: string) => layout.nodes.find((n) => n.id === id)!;
    expect(node("pick").code).toBe(true);
    expect(node("pick").what).toBe("picks · bar 70");
    expect(node("pick").who).toBeNull();
    expect(node("score").code).toBe(false);
    expect(node("repair").what).toBe("asks the least happy");
    expect(node("repair").who).toBeNull();
    expect(node("agreed").end).toBe("converged");
  });

  it("labels the three ways out of a pick and loops the re-rating back to it", () => {
    const layout = layoutFlow(concord);
    const edge = (from: string, to: string) => layout.edges.find((e) => e.from === from && e.to === to);
    expect(edge("pick", "agreed")?.label).toBe("feasible");
    expect(edge("pick", "repair")?.label).toBe("infeasible");
    expect(edge("pick", "no_deal")?.label).toBe("stuck");
    expect(edge("rescore", "pick")?.back).toBe(true);
  });

  it("reaches the converged end, and a second asking takes no edge", () => {
    const run = [
      { step: "propose", turn: 1, next: "score" },
      { step: "score", turn: 3, again: true, asked: ["legal"] } as unknown as FlowTraceEntry,
      { step: "score", turn: 2, next: "pick" },
      {
        step: "pick",
        turn: 3,
        next: "agreed",
        select: { outcome: "feasible" as const, pick: "B", lowest: 72, missing: [], least_happy: null },
      },
    ];
    expect(stepStates(concord, run, null, "converged").get("agreed")).toBe("reached");
    expect([...takenEdges(run)]).toEqual(["propose→score", "score→pick", "pick→agreed"]);
  });
});

// The accord built-in as `protocols.spec_of` hands it over (prompts left
// out): two counts and the shared summary, all made in code, and a restating
// step put to whoever used a word in a different sense.
const accord: EpisodeFlow = {
  name: "accord",
  roles: [],
  bound: {},
  cast: ["a", "b", "c"],
  max_steps: 8,
  steps: [
    { id: "frame", to: "all", collect: "pieces", require: "pieces", next: "added" },
    { id: "added", kind: "tally", of: "points", max_rounds: 3, next: { grew: "more", settled: "ground", empty: "nothing" } },
    { id: "more", to: "all", collect: "pieces", next: "added" },
    { id: "ground", to: "all", collect: "pieces", next: "words" },
    { id: "words", kind: "tally", of: "terms", max_rounds: 2, next: { contested: "restate", clear: "lock" } },
    { id: "restate", to: "contested", collect: "pieces", next: "words" },
    { id: "lock", kind: "lock", next: { locked: "locked", empty: "nothing" } },
    { id: "locked", end: "resolved" },
    { id: "nothing", end: "rejected" },
  ],
};

describe("laying out a shared-summary flow", () => {
  const layout = layoutFlow(accord);
  const node = (id: string) => layout.nodes.find((n) => n.id === id)!;
  const edge = (from: string, to: string) => layout.edges.find((e) => e.from === from && e.to === to);

  it("draws the counts and the summary as made in code, asking nobody", () => {
    expect(["added", "words", "lock"].map((id) => node(id).code)).toEqual([true, true, true]);
    expect(["frame", "more", "restate", "locked"].map((id) => node(id).code)).toEqual([false, false, false, false]);
    expect(node("added").what).toBe("counts new points · up to 3 rounds");
    expect(node("words").what).toBe("checks the words");
    expect(node("lock").what).toBe("saves the shared summary");
    expect(node("added").who).toBeNull();
    expect(node("frame").who).toBe("a, b, c");
  });

  it("puts the restating to those who differ, named only at run time", () => {
    expect(node("restate").what).toBe("asks those who differ");
    expect(node("restate").who).toBeNull();
    expect(stepWho({ id: "x", to: "contested" }, accord)).toBeNull();
  });

  it("labels the ways out of each count and of the summary", () => {
    expect(edge("added", "more")?.label).toBe("grew");
    expect(edge("added", "ground")?.label).toBe("settled");
    expect(edge("added", "nothing")?.label).toBe("empty");
    expect(edge("words", "restate")?.label).toBe("contested");
    expect(edge("words", "lock")?.label).toBe("clear");
    expect(edge("lock", "locked")?.label).toBe("locked");
    expect(edge("lock", "nothing")?.label).toBe("empty");
    expect(edge("more", "added")?.back).toBe(true);
    expect(edge("restate", "words")?.back).toBe(true);
  });

  it("reaches the resolved end through the counts and the summary", () => {
    const run: FlowTraceEntry[] = [
      { step: "frame", turn: 1, asked: ["a", "b", "c"], next: "added" },
      {
        step: "added",
        turn: 1,
        tally: { of: "points", round: 1, max_rounds: 3, outcome: "settled", added: 0, points: 4, capped: false },
        next: "ground",
      },
      { step: "ground", turn: 2, asked: ["a", "b", "c"], next: "words" },
      {
        step: "words",
        turn: 2,
        tally: { of: "terms", round: 1, max_rounds: 2, outcome: "clear", words: 1, contested: [] },
        next: "lock",
      },
      {
        step: "lock",
        turn: 2,
        lock: {
          outcome: "locked",
          memory: "context/summary/x",
          saved: true,
          points: 4,
          shared: 2,
          contested: 0,
          checks: 0,
          flagged: 2,
          quiet: [],
        },
        next: "locked",
      },
    ];
    const states = stepStates(accord, run, null, "resolved");
    expect(states.get("locked")).toBe("reached");
    expect(states.get("more")).toBe("untouched");
    expect([...takenEdges(run)]).toEqual(["frame→added", "added→ground", "ground→words", "words→lock", "lock→locked"]);
  });
});
