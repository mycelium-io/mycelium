import { describe, expect, it } from "vitest";

import {
  conductorLineOf,
  describeConductorLine,
  isSuccess,
  pickSummary,
  type ConductorLine,
  type PickRecord,
} from "./conductor-line";

const turn = { event: "turn", protocol: "swarm", step: "check-in", to: "agent-2", turn: 1, cap: 4 };

describe("conductorLineOf", () => {
  it("reads the line a reload carries in the message's metadata", () => {
    expect(conductorLineOf({ content: "swarm · check-in · …", metadata: { conductor: turn } })).toEqual(
      turn,
    );
  });

  it("reads the line the live stream carries in the envelope's payload", () => {
    const content = JSON.stringify({
      content: "swarm · check-in · …",
      l9: { payload: { type: "message", data: { step: "check-in", conductor: turn } } },
    });
    expect(conductorLineOf({ content })).toEqual(turn);
  });

  it("is null for a message that carries none, or a shape it does not know", () => {
    expect(conductorLineOf({ content: "just talking" })).toBeNull();
    expect(conductorLineOf({ content: "{not json" })).toBeNull();
    expect(conductorLineOf({ content: "hi", metadata: { conductor: { event: "dance" } } })).toBeNull();
    expect(conductorLineOf({ content: "hi", metadata: { kind: "event" } })).toBeNull();
  });
});

describe("describeConductorLine", () => {
  it("says each kind of line in a few words", () => {
    expect(
      describeConductorLine({
        event: "open",
        protocol: "swarm",
        roles: { lead: "agent-1" },
        members: ["agent-2", "agent-3"],
        steps: [],
      }),
    ).toBe("Running swarm · agent-1 as lead · agent-2, agent-3");
    expect(describeConductorLine(turn as never)).toBe("check-in → agent-2 · turn 1 of 4");
    expect(
      describeConductorLine({ event: "edge", step: "review", who: "sec", stance: "reject", next: "propose" }),
    ).toBe("review: sec blocked, on to propose");
    expect(
      describeConductorLine({ event: "close", protocol: "swarm", outcome: "resolved", steps: 2, reason: "" }),
    ).toBe("swarm done · 2 steps");
  });
});

const pick: PickRecord = {
  outcome: "infeasible",
  pick: "B",
  text: "10% off",
  threshold: 70,
  options: [
    { label: "A", text: "20% off", authors: ["success"] },
    { label: "B", text: "10% off", authors: ["finance"] },
  ],
  table: { A: { success: 95, finance: 30 }, B: { success: 55, finance: 90 } },
  cast: ["success", "finance", "legal"],
  ratings: { success: 55, finance: 90 },
  lowest: 55,
  missing: ["legal"],
  least_happy: "success",
};

describe("an agreement's lines", () => {
  it("reads a pick line off the payload, and says where it stands", () => {
    const line = { event: "select", step: "pick", next: "repair", select: pick };
    expect(conductorLineOf({ metadata: { conductor: line } })).toEqual(line);
    expect(describeConductorLine(line as ConductorLine)).toBe(
      "pick: B, @success at 55; no rating from @legal",
    );
    expect(pickSummary({ ...pick, outcome: "feasible", missing: [], ratings: { a: 80 } })).toBe(
      "B, everyone at 70+",
    );
  });

  it("says an agreement is an agreement, and counts it a success", () => {
    const agreed = {
      event: "close" as const,
      protocol: "concord",
      outcome: "converged",
      steps: 4,
      reason: "reached `agreed`",
      pick: "C",
      text: "15% off for two years",
    };
    expect(describeConductorLine(agreed)).toBe("Everyone's on board: going with C");
    expect(describeConductorLine({ ...agreed, outcome: "rejected" })).toBe(
      "Couldn't get everyone there · best was C",
    );
    expect(isSuccess("converged")).toBe(true);
    expect(isSuccess("resolved")).toBe(true);
    expect(isSuccess("rejected")).toBe(false);
  });
});
