// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  argValue,
  commandNamed,
  matchChoices,
  memoryKeyChoices,
  missingArg,
  parseCommand,
  parseSummon,
  usage,
} from "./composer-commands";

describe("parseCommand", () => {
  it("is null for a message, an unknown command, or a command glued to more", () => {
    expect(parseCommand("hello")).toBeNull();
    expect(parseCommand("/nope x")).toBeNull();
    expect(parseCommand("/agentx")).toBeNull();
    expect(parseCommand("see /agent")).toBeNull();
  });

  it("has no active argument while the cursor is on the name", () => {
    const p = parseCommand("/agent", 3);
    expect(p?.command.name).toBe("agent");
    expect(p?.active).toBeNull();
  });

  it("moves to the next argument once a space is typed", () => {
    expect(parseCommand("/agent ")?.active).toBe(0);
    expect(parseCommand("/agent scout ")?.active).toBe(1);
    const p = parseCommand("/agent scout cla");
    expect(p?.active).toBe(1);
    expect(p?.word).toEqual({ value: "cla", start: 13, end: 16 });
  });

  it("follows the cursor back into an earlier argument", () => {
    const text = "/agent scout claude ~/code";
    expect(parseCommand(text, 9)?.active).toBe(0);
    expect(parseCommand(text, text.length)?.active).toBe(2);
  });

  it("is past the last argument when more is typed than it takes", () => {
    expect(parseCommand("/engine aligner judge extra")?.active).toBeNull();
  });

  it("gives a rest argument the whole remainder, whatever is in it", () => {
    const p = parseCommand("/task fix the flaky tests @agent-2 !!")!;
    expect(argValue(p, "what")).toBe("fix the flaky tests @agent-2 !!");
    expect(p.active).toBe(0);
  });

  it("reads each argument by name", () => {
    const p = parseCommand("/agent @Scout claude-code ~/code laptop")!;
    expect(argValue(p, "handle")).toBe("@Scout");
    expect(argValue(p, "harness")).toBe("claude-code");
    expect(argValue(p, "folder")).toBe("~/code");
    expect(argValue(p, "machine")).toBe("laptop");
    expect(argValue(p, "nothing")).toBe("");
  });
});

describe("usage and missingArg", () => {
  it("draws required, optional and rest arguments", () => {
    expect(usage(commandNamed("agent")!)).toBe("/agent <handle> <harness> [folder] [machine]");
    expect(usage(commandNamed("task")!)).toBe("/task <what…>");
    expect(usage(commandNamed("memory")!)).toBe("/memory [key] [text…]");
  });

  it("names the first required argument left out", () => {
    expect(missingArg(parseCommand("/agent scout")!)).toBe(
      "Say the harness: /agent <handle> <harness> [folder] [machine]",
    );
    expect(missingArg(parseCommand("/task")!)).toBe("Say what it is: /task <what…>");
    expect(missingArg(parseCommand("/memory")!)).toBeNull();
    expect(missingArg(parseCommand("/agent scout claude")!)).toBeNull();
  });
});

describe("parseSummon", () => {
  const flows = [
    { name: "gated", description: "A proposer proposes…", roles: ["proposer", "guardian"] },
    { name: "concord", description: "Help them agree…", roles: [] },
    { name: "accord", description: "Get on the same page…", roles: [] },
  ];
  const at = (text: string, cursor = text.length) => parseSummon(text, cursor, ["conductor"], flows);

  it("is only a summon when a conductor is mentioned first", () => {
    expect(at("@aligner gated")).toBeNull();
    expect(at("hey @conductor gated")).toBeNull();
    expect(at("@conductor")?.active).toBeNull();
    expect(at("@Conductor ")?.engine).toBe("conductor");
  });

  it("asks for the flow, then each of its roles in order, then what it's about", () => {
    expect(at("@conductor ")?.active).toBe("flow");
    expect(at("@conductor ga")).toMatchObject({ active: "flow", word: { value: "ga" } });
    expect(at("@conductor gated ")).toMatchObject({ active: "member", slot: 0 });
    expect(at("@conductor gated @ana ")).toMatchObject({ active: "member", slot: 1 });
    expect(at("@conductor gated @ana @be")).toMatchObject({ active: "member", slot: 1, word: { value: "@be" } });
    // Every role has someone, so what comes next is the ask.
    expect(at("@conductor gated @ana @ben ")?.active).toBe("ask");
    expect(at("@conductor gated @ana @ben ship it")).toMatchObject({ active: "ask", asked: true });
  });

  it("keeps taking members for a flow with no roles until the ask starts", () => {
    expect(at("@conductor concord @a @b @c ")).toMatchObject({ active: "member", slot: 3 });
    expect(at("@conductor concord @a pick a name ")?.active).toBe("ask");
  });

  it("gives accord no lead to name: every member is one of the cast", () => {
    expect(at("@conductor accord ")).toMatchObject({ active: "member", slot: 0 });
    expect(at("@conductor accord @a @b @c ")).toMatchObject({ active: "member", slot: 3 });
    expect(at("@conductor accord @a @b what done means")?.active).toBe("ask");
  });

  it("reads the flow the way the conductor does: the first word that isn't a mention", () => {
    const s = at("@conductor @ana gated: @ben the fix")!;
    expect(s.protocol?.name).toBe("gated");
    expect(s.members.map((m) => m.value)).toEqual(["@ana", "@ben"]);
    expect(at("@conductor nope ")?.protocol).toBeUndefined();
  });
});

describe("memoryKeyChoices", () => {
  const keys = ["context/goals", "context/plans/q3", "decisions/db", "agents/scout/notes", "readme"];
  const standard = ["context", "decisions", "procedures"];

  it("starts from the folders, busiest first, then the standard ones and the loose memories", () => {
    expect(memoryKeyChoices(keys, standard, "").map((c) => c.value)).toEqual([
      "context/",
      "decisions/",
      "procedures/",
      "readme",
    ]);
  });

  it("lists what's inside a folder once one is typed", () => {
    const inside = memoryKeyChoices(keys, standard, "context/g");
    expect(inside.map((c) => [c.value, Boolean(c.open)])).toEqual([
      ["context/plans/", true],
      ["context/goals", false],
    ]);
    expect(inside[1].about).toMatch(/replaces/);
  });
});

describe("matchChoices", () => {
  const choices = [{ value: "claude-code" }, { value: "codex" }, { value: "cursor-agent" }];

  it("puts what starts with the typed text ahead of what only contains it", () => {
    expect(matchChoices(choices, "c").map((c) => c.value)).toEqual(["claude-code", "codex", "cursor-agent"]);
    expect(matchChoices(choices, "co").map((c) => c.value)).toEqual(["codex", "claude-code"]);
    expect(matchChoices(choices, "AGENT").map((c) => c.value)).toEqual(["cursor-agent"]);
  });

  it("offers everything before anything is typed", () => {
    expect(matchChoices(choices, "")).toHaveLength(3);
  });
});
