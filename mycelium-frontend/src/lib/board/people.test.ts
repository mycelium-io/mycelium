// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import type { BoardEpic, BoardPart } from "@/lib/api";
import {
  PART_STATES,
  STANDING,
  WAITING_KINDS,
  WAITING_STANDING,
  humanLine,
  isQuiet,
  splitTasks,
  startsAfter,
  summary,
  waitingText,
  waitingWhere,
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
  it("uses the states and kinds the contract freezes, each with a word", () => {
    expect(PART_STATES).toEqual(CONTRACT.part_states);
    expect(WAITING_KINDS).toEqual(CONTRACT.waiting_kinds);
    expect(Object.keys(STANDING).sort()).toEqual([...CONTRACT.part_states].sort());
    expect(Object.keys(WAITING_STANDING).sort()).toEqual([...CONTRACT.waiting_kinds].sort());
  });

  it("says who has a part, and calls you you", () => {
    expect(whoHasIt(part("working", { holder: "builder" }), "julia")).toBe("builder");
    expect(whoHasIt(part("waiting", { assignee: "@julia" }), "julia")).toBe("you");
    expect(whoHasIt(part("open"), "julia")).toBeNull();
  });

  it("gives a row one human line: its latest message, else why it can't go on", () => {
    const titles = new Map([["work/a", "Add Apple Pay"], ["work/b", "Fix the charges"]]);
    expect(humanLine(part("working", { latest: { sender: "builder", text: "Opened #502." } }))).toBe(
      "builder: Opened #502.",
    );
    expect(humanLine(part("working"))).toBe("");
    expect(humanLine(part("blocked", { blocked_by: "#502" }))).toBe("Blocked by #502");
    expect(humanLine(part("blocked", { key: "failed/iphone" }))).toBe("It failed and needs a fix");
    expect(humanLine(part("waiting", { waiting_on: ["work/a"] }), titles)).toBe("Starts after Add Apple Pay");
    // More than one is a count; a title list would be cut off mid-name.
    expect(startsAfter(part("waiting", { waiting_on: ["work/a", "work/b"] }), titles)).toBe(
      "Starts after 2 other tasks",
    );
  });

  it("calls a running task quiet only after three hours without a word", () => {
    const now = Date.parse("2026-10-17T12:00:00Z");
    const said = (at: string) => part("working", { latest: { sender: "b", text: "t", at } });
    expect(isQuiet(said("2026-10-17T10:00:00Z"), now)).toBe(false);
    expect(isQuiet(said("2026-10-17T08:30:00Z"), now)).toBe(true);
    expect(isQuiet(part("open", { updated_at: "2026-10-01T00:00:00Z" }), now)).toBe(false);
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

  it("opens with what a person came to find out, in sentences", () => {
    const epic: BoardEpic = {
      ...part("working", { key: "e" }),
      lead: "builder",
      done: 0,
      total: 2,
      steps: [],
      path: [part("working", { key: "p1", holder: "builder" }), part("working", { key: "p2", holder: "reviewer" })],
    };
    const board = { epics: [epic], tasks: [part("open", { key: "n1" }), part("waiting", { key: "n2" })] };
    expect(summary(board, [{ kind: "ask", count: 1 }, { kind: "task", count: 1 }])).toBe(
      "2 things need you. builder and reviewer are on 2 tasks. 2 are up next.",
    );
    expect(summary({ epics: [], tasks: [] }, [])).toBe("Nothing needs you.");
  });

  it("words each kind of waiting item, and where it is", () => {
    expect(waitingText({ kind: "ask", text: "Ship it?", count: 1 })).toBe("Ship it?");
    expect(waitingText({ kind: "ask", text: "@julia can I close this?", count: 1 }, "julia")).toBe(
      "Can I close this?",
    );
    expect(waitingText({ kind: "ask", text: "@ana can I close this?", count: 1 }, "julia")).toBe(
      "@ana can I close this?",
    );
    expect(waitingText({ kind: "turn", title: "Review", count: 1 })).toBe("It's your turn in Review");
    expect(waitingText({ kind: "task", title: "Test it", count: 1 })).toBe("Test it");
    expect(waitingWhere({ kind: "ask", title: "Fix it", count: 1 })).toBe("In Fix it");
    expect(waitingWhere({ kind: "ask", title: "Fix it", epic_title: "Apple Pay", count: 1 })).toBe(
      "In Fix it (part of Apple Pay)",
    );
    expect(waitingWhere({ kind: "ask", count: 1 })).toBe("In the room");
  });
});
