// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { BoardPart } from "@/lib/api";
import {
  PART_STATES,
  WAITING_KINDS,
  quietFor,
  splitTasks,
  waitingText,
  whereItStands,
  whoHasIt,
} from "./people";

const CONTRACT = JSON.parse(
  readFileSync(resolve(__dirname, "../../../../contracts/board-vocabulary.json"), "utf8"),
).epic;

const part = (state: BoardPart["state"], more: Partial<BoardPart> = {}): BoardPart => ({
  key: "work/x",
  title: "X",
  state,
  waiting_on: [],
  parts: 0,
  parts_done: 0,
  ...more,
});

describe("the people's board words", () => {
  it("uses the states and kinds the contract freezes", () => {
    expect(PART_STATES).toEqual(CONTRACT.part_states);
    expect(WAITING_KINDS).toEqual(CONTRACT.waiting_kinds);
  });

  it("says who has a part, and calls you you", () => {
    expect(whoHasIt(part("working", { holder: "builder" }), "julia")).toBe("builder");
    expect(whoHasIt(part("waiting", { assignee: "@julia" }), "julia")).toBe("you");
    expect(whoHasIt(part("open"), "julia")).toBe("nobody yet");
  });

  it("says where a part stands in a phrase", () => {
    const titles = new Map([["work/a", "Add Apple Pay"], ["work/b", "Fix the charges"]]);
    expect(whereItStands(part("done"))).toBe("Done");
    expect(whereItStands(part("waiting", { waiting_on: ["work/a", "work/b"] }), titles)).toBe(
      "Starts after Add Apple Pay and Fix the charges",
    );
    expect(whereItStands(part("working", { latest: { sender: "builder", text: "Opened #502." } }))).toBe(
      "builder: Opened #502.",
    );
    expect(whereItStands(part("working"))).toBe("Being worked on");
    expect(whereItStands(part("blocked", { blocked_by: "CI" }))).toBe("Blocked by CI");
    expect(whereItStands(part("open"))).toBe("Ready for someone to pick up");
  });

  it("calls a running task quiet only after three hours without a word", () => {
    const now = Date.parse("2026-10-17T12:00:00Z");
    const said = (at: string) => part("working", { latest: { sender: "b", text: "t", at } });
    expect(quietFor([said("2026-10-17T10:00:00Z")], now)).toBeNull();
    expect(quietFor([said("2026-10-17T08:30:00Z")], now)).toBe("Quiet for 3 hours");
    expect(quietFor([said("2026-10-15T08:00:00Z")], now)).toBe("Quiet for 2 days");
    expect(quietFor([part("open", { updated_at: "2026-10-01T00:00:00Z" })], now)).toBeNull();
  });

  it("puts lone tasks someone is on with the epics, and the rest up next", () => {
    const { running, next } = splitTasks([
      part("working", { key: "a" }),
      part("blocked", { key: "b" }),
      part("open", { key: "c" }),
      part("waiting", { key: "d" }),
    ]);
    expect(running.map(p => p.key)).toEqual(["a", "b"]);
    expect(next.map(p => p.key)).toEqual(["c", "d"]);
  });

  it("words each kind of waiting item", () => {
    expect(waitingText({ kind: "ask", text: "Ship it?", count: 1 })).toBe("Ship it?");
    expect(waitingText({ kind: "ask", text: "@julia can I close this?", count: 1 }, "julia")).toBe(
      "Can I close this?",
    );
    expect(waitingText({ kind: "ask", text: "@ana can I close this?", count: 1 }, "julia")).toBe(
      "@ana can I close this?",
    );
    expect(waitingText({ kind: "turn", title: "Review", count: 1 })).toBe("It's your turn in Review");
    expect(waitingText({ kind: "task", title: "Test it", count: 1 })).toBe("Test it is yours to do");
  });
});
