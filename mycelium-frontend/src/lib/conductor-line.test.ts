import { describe, expect, it } from "vitest";

import {
  conductorLineOf,
  runProgress,
  describeConductorLine,
  isSuccess,
  named,
  optionNames,
  leastSatisfied,
  pickSummary,
  ratingsByReply,
  shortName,
  standings,
  stepSentence,
  turnRuns,
  verdict,
  views,
  type ConductorLine,
  type LockRecord,
  type PickRecord,
} from "./conductor-line";

describe("a run, seen from the channel", () => {
  const open = { event: "open", protocol: "concord", roles: {}, members: ["a", "b", "c"], steps: [] } as ConductorLine;
  const turn = (to: string, step = "score") =>
    ({ event: "turn", protocol: "concord", step, to, turn: 3, cap: 20 }) as ConductorLine;
  const c = (conductor: ConductorLine) => ({ sender: "conductor", conductor, chat: true });
  const said = (sender: string) => ({ sender, conductor: null, chat: true });

  it("says what the members are doing and how many have answered, while it walks", () => {
    const run = runProgress([c(open), c(turn("a", "anchor")), said("a"), c(turn("a")), c(turn("b")), c(turn("c")), said("b"), said("b"), said("a")]);
    expect(run).toMatchObject({ protocol: "concord", open: true, doing: { what: "scoring", asked: 3, answered: 2 } });
  });

  it("stops being live once it closes, and keeps the summary's counts", () => {
    const lock: LockRecord = { outcome: "locked", memory: "m", saved: true, points: 17, shared: 0, contested: 2, checks: 2, flagged: 4, quiet: [] };
    const run = runProgress([
      c(open),
      c(turn("a", "verify")),
      said("a"),
      c({ event: "lock", step: "lock", next: "locked", lock }),
      c({ event: "close", protocol: "accord", outcome: "resolved", steps: 7, reason: "" }),
    ]);
    expect(run).toMatchObject({ open: false, doing: null, lock: { points: 17 } });
    expect(runProgress([said("a")])).toBeNull();
  });

});

describe("how satisfied each member is", () => {
  const record: PickRecord = {
    outcome: "feasible",
    pick: "A",
    text: "Cents math",
    threshold: 60,
    options: [
      { label: "A", text: "Cents math", authors: ["builder"] },
      { label: "B", text: "Floats", authors: ["reviewer"] },
    ],
    table: { A: { builder: 90, reviewer: 80, designer: 75 }, B: { builder: 85, reviewer: 70 } },
    placed: { A: { builder: 1, reviewer: 0.88, designer: 0.81 }, B: { builder: 0.94, reviewer: 0.75 } },
    reasons: { A: { designer: "format left open" } },
    cast: ["builder", "reviewer", "designer"],
    ratings: { builder: 90, reviewer: 80, designer: 75 },
    lowest: 0.81,
    missing: [],
    least_happy: null,
  };

  it("orders members most satisfied first, and names the least", () => {
    expect(standings(record, "A").map((s) => s.member)).toEqual(["builder", "reviewer", "designer"]);
    expect(standings(record, "B").map((s) => s.member)).toEqual(["builder", "reviewer", "designer"]);
    expect(standings(record, "B")[2].placed).toBeUndefined();
    expect(leastSatisfied(record)).toEqual({ member: "designer", placed: 0.81 });
    expect(pickSummary(record)).toBe("A (Cents math), least satisfied: designer at 81%");
  });

  it("gives each rating reply its member's row of the pick that read it", () => {
    const turn = (to: string, step: string) =>
      ({ event: "turn", protocol: "concord", step, to, turn: 3, cap: 20 }) as ConductorLine;
    const events = [
      { id: "t1", sender: "conductor", conductor: turn("builder", "score"), chat: true },
      { id: "t2", sender: "conductor", conductor: turn("reviewer", "score"), chat: true },
      { id: "r1", sender: "builder", conductor: null, chat: true },
      // Something else builder says before the pick isn't its answer.
      { id: "aside", sender: "builder", conductor: null, chat: true },
      { id: "r2", sender: "reviewer", conductor: null, chat: true },
      // Asked again: the answer to that asking is the one that counts.
      { id: "t3", sender: "conductor", conductor: turn("reviewer", "score"), chat: true },
      { id: "r3", sender: "reviewer", conductor: null, chat: true },
      { id: "j", sender: "designer", conductor: null, chat: false },
      { id: "s", sender: "conductor", conductor: { event: "select", step: "pick", next: "agreed", select: record } as ConductorLine, chat: true },
      // Said after the pick, so no pick read it.
      { id: "r4", sender: "builder", conductor: null, chat: true },
    ];
    const rated = ratingsByReply(events);
    expect([...rated.keys()]).toEqual(["r1", "r3"]);
    expect(rated.get("r1")).toEqual({ record, member: "builder" });
  });
});

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
      "B (10% off), least satisfied: success at 55%",
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
    expect(describeConductorLine(agreed)).toBe("Picked C");
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
