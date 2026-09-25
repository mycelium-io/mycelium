import { describe, expect, it } from "vitest";

import { conductorLineOf, describeConductorLine } from "./conductor-line";

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
