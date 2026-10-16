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

const points = {
  of: "points" as const,
  round: 1,
  max_rounds: 3,
  outcome: "grew" as const,
  added: 4,
  points: 4,
  capped: false,
};
const terms = {
  of: "terms" as const,
  round: 1,
  max_rounds: 2,
  outcome: "contested" as const,
  words: 2,
  contested: ["renewal"],
  asked: ["a", "b"],
};
const lock = {
  outcome: "locked" as const,
  memory: "context/summary/acme-renewal",
  saved: true,
  points: 5,
  shared: 1,
  contested: 0,
  checks: 1,
  flagged: 4,
  quiet: ["c"],
};

describe("a shared summary's lines", () => {
  it("reads a count and a summary line off either place a line arrives", () => {
    const counted = { event: "tally", step: "added", next: "more", tally: points };
    expect(conductorLineOf({ metadata: { conductor: counted } })).toEqual(counted);
    const locked = { event: "lock", step: "lock", next: "locked", lock };
    const content = JSON.stringify({ l9: { payload: { data: { conductor: locked } } } });
    expect(conductorLineOf({ content })).toEqual(locked);
  });

  it("says how the points are coming in, in plain words", () => {
    const say = (tally: object) =>
      describeConductorLine({ event: "tally", step: "added", next: null, tally } as ConductorLine);
    expect(say(points)).toBe("Round 1: 4 new points, 4 in all");
    expect(say({ ...points, round: 2, outcome: "settled", added: 0, points: 5 })).toBe(
      "Nobody added anything new: 5 points",
    );
    expect(say({ ...points, outcome: "empty", added: 0, points: 0 })).toBe("Nobody gave any points");
    expect(say({ ...points, round: 3, outcome: "settled", added: 2, points: 7, capped: true })).toBe(
      "Points were still coming when the rounds ran out: 7 in all",
    );
  });

  it("names a word used in different senses, and who is asked again", () => {
    const say = (tally: object) =>
      describeConductorLine({ event: "tally", step: "words", next: null, tally } as ConductorLine);
    expect(say(terms)).toBe("Words used in different senses: renewal. Asking a, b again");
    expect(say({ ...terms, outcome: "clear", contested: [], asked: [] })).toBe("No word used in different senses");
    expect(say({ ...terms, round: 2, outcome: "clear" })).toBe("Still used in different senses: renewal");
  });

  it("says what the shared summary holds, or that there was nothing to put in it", () => {
    const say = (l: object) =>
      describeConductorLine({ event: "lock", step: "lock", next: null, lock: l } as ConductorLine);
    expect(say(lock)).toBe(
      "Shared summary: 5 points, 1 stated by more than one person, 1 check, 4 open items · no answer from c",
    );
    expect(say({ ...lock, quiet: [], contested: 2 })).toBe(
      "Shared summary: 5 points, 1 stated by more than one person, 2 words used in different senses, 1 check, 4 open items",
    );
    expect(say({ ...lock, outcome: "empty", memory: null, saved: false, points: 0 })).toBe(
      "Nothing to put in a shared summary",
    );
  });

  it("says where a run saved what it settled to, or that it could not", () => {
    const close = { event: "close" as const, protocol: "accord", outcome: "resolved", steps: 4, reason: "" };
    expect(describeConductorLine({ ...close, memory: "context/summary/acme-renewal" })).toBe(
      "accord done · 4 steps · saved as context/summary/acme-renewal",
    );
    expect(describeConductorLine({ ...close, memory: null })).toBe("accord done · 4 steps · could not be saved");
    expect(describeConductorLine(close)).toBe("accord done · 4 steps");
  });
});
