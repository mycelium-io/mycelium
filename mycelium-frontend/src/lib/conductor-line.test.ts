import { describe, expect, it } from "vitest";

import {
  conductorLineOf,
  runProgress,
  describeConductorLine,
  isSuccess,
  turnRuns,
  type ConductorLine,
} from "./conductor-line";

describe("a run, seen from the channel", () => {
  const open = { event: "open", protocol: "fan-out", roles: {}, members: ["a", "b", "c"], steps: [] } as ConductorLine;
  const turn = (to: string, step = "gather") =>
    ({ event: "turn", protocol: "fan-out", step, to, turn: 3, cap: 20 }) as ConductorLine;
  const c = (conductor: ConductorLine) => ({ sender: "conductor", conductor, chat: true });
  const said = (sender: string) => ({ sender, conductor: null, chat: true });

  it("names the step being asked and how many have answered, while it walks", () => {
    const run = runProgress([c(open), c(turn("a", "plan")), said("a"), c(turn("a")), c(turn("b")), c(turn("c")), said("b"), said("b"), said("a")]);
    expect(run).toMatchObject({ protocol: "fan-out", open: true, doing: { what: "gather", asked: 3, answered: 2 } });
  });

  it("stops being live once it closes", () => {
    const run = runProgress([
      c(open),
      c(turn("a", "verify")),
      said("a"),
      c({ event: "close", protocol: "fan-out", outcome: "resolved", steps: 7, reason: "" }),
    ]);
    expect(run).toMatchObject({ open: false, doing: null });
    expect(runProgress([said("a")])).toBeNull();
  });

  it("folds a step put to everyone at once into one row, and leaves turns taken one by one apart", () => {
    const t = (id: string, step: string, to: string, n: number) => ({
      id,
      conductor: { event: "turn" as const, protocol: "fan-out", step, to, turn: n, cap: 20 },
    });
    const reply = (id: string) => ({ id, conductor: null });
    const runs = turnRuns([
      t("1", "gather", "pm", 3),
      t("2", "gather", "web", 3),
      t("3", "gather", "api", 3),
      reply("4"),
      t("5", "combine", "web", 4),
      reply("6"),
      t("7", "combine", "web", 4),
    ]);
    expect(runs.get("1")).toEqual(["pm", "web", "api"]);
    expect(runs.get("2")).toBeNull();
    expect(runs.get("3")).toBeNull();
    expect(runs.has("4")).toBe(false);
    expect(runs.get("5")).toEqual(["web"]);
    expect(runs.get("7")).toEqual(["web"]);
  });
});

const turn = { event: "turn", protocol: "fan-out", step: "gather", to: "agent-2", turn: 1, cap: 6 };

describe("conductorLineOf", () => {
  it("reads the line a reload carries in the message's metadata", () => {
    expect(conductorLineOf({ content: "fan-out · gather · …", metadata: { conductor: turn } })).toEqual(
      turn,
    );
  });

  it("reads the line the live stream carries in the envelope's payload", () => {
    const content = JSON.stringify({
      content: "fan-out · gather · …",
      l9: { payload: { type: "message", data: { step: "gather", conductor: turn } } },
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
        protocol: "fan-out",
        roles: { lead: "agent-1" },
        members: ["agent-2", "agent-3"],
        steps: [],
      }),
    ).toBe("Running fan-out · agent-1 as lead · agent-2, agent-3");
    expect(describeConductorLine(turn as never)).toBe("gather → agent-2 · turn 1 of 6");
    expect(describeConductorLine({ ...(turn as object), again: true } as ConductorLine)).toBe(
      "gather → agent-2 (asked again) · turn 1 of 6",
    );
    expect(
      describeConductorLine({ event: "edge", step: "review", who: "sec", stance: "reject", next: "propose" }),
    ).toBe("review: sec blocked, on to propose");
    expect(
      describeConductorLine({ event: "close", protocol: "fan-out", outcome: "resolved", steps: 2, reason: "" }),
    ).toBe("fan-out done · 2 steps");
    expect(
      describeConductorLine({ event: "close", protocol: "gated", outcome: "rejected", steps: 3, reason: "blocked" }),
    ).toBe("gated rejected · blocked");
  });

  it("counts a resolved run a success, and a rejected one not", () => {
    expect(isSuccess("resolved")).toBe(true);
    expect(isSuccess("rejected")).toBe(false);
  });
});
