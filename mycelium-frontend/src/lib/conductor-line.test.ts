import { describe, expect, it } from "vitest";

import {
  conductorLineOf,
  describeConductorLine,
  isSuccess,
  named,
  optionNames,
  pickSummary,
  shortName,
  stepSentence,
  turnRuns,
  verdict,
  views,
  type ConductorLine,
  type PickRecord,
} from "./conductor-line";

describe("a concord or accord step, as a reader follows it", () => {
  it("names an option by its first words, as the hub does", () => {
    expect(named("B", "10% off")).toBe("B (10% off)");
    expect(shortName("Ship at once, and cancel the delivery if the payment fails.")).toBe("Ship at once, and cancel…");
    expect(shortName("Hold it. Then ship (maybe).")).toBe("Hold it…");
    expect(shortName("Three-year renewal at list price")).toBe("Three-year renewal at list price");
  });

  it("names options that start alike by what tells them apart, as the hub does", () => {
    expect(
      optionNames([
        { label: "A", text: "Three-year renewal at 15% off list price, with an expansion review." },
        { label: "B", text: "Three-year renewal at list price, with a dedicated success manager." },
        { label: "C", text: "Three-year renewal at list price with standard liability caps." },
        { label: "D", text: "10% off" },
      ]),
    ).toEqual({
      A: "Three-year renewal at 15% off…",
      B: "…a dedicated success manager",
      C: "…standard liability caps",
      D: "10% off",
    });
  });

  it("says what the members are doing, and leaves other flows' steps alone", () => {
    expect(stepSentence("concord", "score", ["pm", "web", "api"])).toBe("pm, web and api rate every option, with reasons");
    expect(stepSentence("concord", "repair", ["web"])).toBe("web proposes a fix that answers the objections");
    expect(stepSentence("accord", "ground", ["pm", "api"])).toBe("pm and api define the key terms and take on checks");
    expect(stepSentence("gated", "propose", ["api"])).toBeNull();
    expect(describeConductorLine({ event: "turn", protocol: "concord", step: "anchor", to: "pm", turn: 1, cap: 20 })).toBe(
      "pm rates the two ends: nothing agreed, and their own pick",
    );
  });

  it("folds a step put to everyone at once into one row, and leaves turns taken one by one apart", () => {
    const t = (id: string, step: string, to: string, n: number) => ({
      id,
      conductor: { event: "turn" as const, protocol: "concord", step, to, turn: n, cap: 20 },
    });
    const reply = (id: string) => ({ id, conductor: null });
    const runs = turnRuns([
      t("1", "score", "pm", 3),
      t("2", "score", "web", 3),
      t("3", "score", "api", 3),
      reply("4"),
      t("5", "repair", "web", 4),
      reply("6"),
      t("7", "repair", "web", 4),
    ]);
    expect(runs.get("1")).toEqual(["pm", "web", "api"]);
    expect(runs.get("2")).toBeNull();
    expect(runs.get("3")).toBeNull();
    expect(runs.has("4")).toBe(false);
    expect(runs.get("5")).toEqual(["web"]);
    expect(runs.get("7")).toEqual(["web"]);
  });
});

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
  it("reads a pick line off the payload, and says where it stands in words", () => {
    const line = { event: "select", step: "pick", next: "repair", select: pick };
    expect(conductorLineOf({ metadata: { conductor: line } })).toEqual(line);
    // A record from before ratings carried reasons still reads.
    expect(describeConductorLine(line as ConductorLine)).toBe(
      "Picked B (10% off): success is short of the bar; no rating from legal",
    );
    expect(pickSummary({ ...pick, outcome: "feasible", missing: [], ratings: { a: 80 } })).toBe(
      "B (10% off): everyone meets the bar",
    );
  });

  it("leads with each member's reason, placed on their own scale", () => {
    const reasoned: PickRecord = {
      ...pick,
      placed: { A: { success: 0.95, finance: 0.1 }, B: { success: 0.4, finance: 0.95 } },
      reasons: { B: { success: "Ten percent won't keep them", finance: "margin holds" } },
      short: [{ member: "success", placed: 0.4, why: "Ten percent won't keep them" }],
    };
    expect(pickSummary(reasoned)).toBe(
      "B (10% off): success is short of the bar, because ten percent won't keep them; no rating from legal",
    );
    expect(views(reasoned, "B")).toEqual([
      { member: "success", verdict: "short of the bar", why: "Ten percent won't keep them", short: true },
      { member: "finance", verdict: "close to the ideal", why: "margin holds", short: false },
      { member: "legal", verdict: "gave no rating", why: "", short: false },
    ]);
    expect(verdict(0, 0.6)).toBe("no better than the bad outcome");
    expect(verdict(0.6, 0.6)).toBe("meets the bar");
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
    expect(describeConductorLine(agreed)).toBe("Everyone meets the bar: going with C");
    expect(describeConductorLine({ ...agreed, outcome: "resolved" })).toBe(
      "Best found: C, below the bar for some",
    );
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
