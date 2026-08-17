// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  paletteFilter,
  paletteSections,
  pushRecent,
  recencyBonus,
  RECENT_HEADING,
  RECENT_LIMIT,
  RECENT_SHOWN,
  ROOMS_SHOWN,
  type PaletteCommand,
} from "@/lib/commands";

const command = (id: string, title: string, group: string): PaletteCommand => ({
  id,
  title,
  group,
  run: () => {},
});

const COMMANDS = [
  command("room:pricing", "pricing-model", "Rooms"),
  command("room:ops", "ops", "Rooms"),
  command("pane.plan", "Plan", "Panes"),
  command("pane.network", "Network", "Panes"),
];

describe("recent commands", () => {
  it("moves a re-run command to the front rather than repeating it", () => {
    const recent = pushRecent(pushRecent(["a", "b"], "c"), "b");
    expect(recent).toEqual(["b", "c", "a"]);
  });

  it("keeps the list bounded", () => {
    const recent = Array.from({ length: RECENT_LIMIT + 10 }, (_, i) => `c${i}`).reduce(
      (acc, id) => pushRecent(acc, id),
      [] as string[],
    );
    expect(recent).toHaveLength(RECENT_LIMIT);
  });

  it("is worth more the more recently it ran, and nothing at all if it never did", () => {
    const recent = ["first", "second", "third"];
    expect(recencyBonus(recent, "first")).toBeGreaterThan(recencyBonus(recent, "third"));
    expect(recencyBonus(recent, "third")).toBeGreaterThan(0);
    expect(recencyBonus(recent, "never")).toBe(0);
  });
});

describe("paletteFilter", () => {
  it("breaks a tie between equal matches toward the one used more recently", () => {
    const filter = paletteFilter(["room:ops"]);
    expect(filter("room:ops", "room", [])).toBeGreaterThan(filter("room:pricing", "room", []));
  });

  it("leaves a command the query rules out hidden, however recently it ran", () => {
    const filter = paletteFilter(["room:ops"]);
    expect(filter("room:ops", "zzzzz", [])).toBe(0);
  });

  it("does not let recency outrank a decisively better match", () => {
    const filter = paletteFilter(["pane.network"]);
    expect(filter("room:pricing", "pricing", ["pricing-model"])).toBeGreaterThan(
      filter("pane.network", "pricing", ["Network"]),
    );
  });
});

describe("paletteSections", () => {
  it("opens on the rooms, whichever component registered first", () => {
    const offered = [
      command("theme.dark", "Dark theme", "Preferences"),
      command("engine.invite", "Invite an engine", "Inspector"),
      command("room:ops", "ops", "Rooms"),
      command("x", "Something else", "Elsewhere"),
    ];
    expect(paletteSections(offered, [], "").map(s => s.heading)).toEqual([
      "Rooms",
      "Inspector",
      "Preferences",
      "Elsewhere",
    ]);
  });

  it("groups the commands, in the order they were offered", () => {
    expect(paletteSections(COMMANDS, [], "")).toEqual([
      { heading: "Rooms", commands: [COMMANDS[0], COMMANDS[1]] },
      { heading: "Panes", commands: [COMMANDS[2], COMMANDS[3]] },
    ]);
  });

  it("leads with what was run recently, and doesn't repeat it below", () => {
    const sections = paletteSections(COMMANDS, ["pane.plan", "room:ops"], "");
    expect(sections[0]).toEqual({
      heading: RECENT_HEADING,
      commands: [COMMANDS[2], COMMANDS[1]],
    });
    expect(sections.flatMap(s => s.commands).filter(c => c.id === "pane.plan")).toHaveLength(1);
    expect(sections[1]).toEqual({ heading: "Rooms", commands: [COMMANDS[0]] });
  });

  it("shows only the last few recents", () => {
    const many = Array.from({ length: RECENT_SHOWN + 3 }, (_, i) => command(`c${i}`, `c${i}`, "Rooms"));
    const sections = paletteSections(many, many.map(c => c.id), "");
    expect(sections[0].commands).toHaveLength(RECENT_SHOWN);
  });

  it("ignores a recent command that isn't available here", () => {
    const sections = paletteSections(COMMANDS, ["pane.channel"], "");
    expect(sections.map(s => s.heading)).toEqual(["Rooms", "Panes"]);
  });

  it("drops the recent section once there's a query, so scoring owns the order", () => {
    const sections = paletteSections(COMMANDS, ["pane.plan"], "pl");
    expect(sections.map(s => s.heading)).toEqual(["Rooms", "Panes"]);
  });

  it("caps the standing Rooms list to the recent head, but never the actions", () => {
    const rooms = Array.from({ length: ROOMS_SHOWN + 4 }, (_, i) => command(`room:r${i}`, `r${i}`, "Rooms"));
    const withAction = [...rooms, command("room.create", "Create a room", "Rooms")];
    const [section] = paletteSections(withAction, [], "");
    expect(section.commands.filter(c => c.id.startsWith("room:"))).toHaveLength(ROOMS_SHOWN);
    expect(section.commands.some(c => c.id === "room.create")).toBe(true);
  });

  it("drops the Rooms cap once there's a query, so every room is searchable", () => {
    const rooms = Array.from({ length: ROOMS_SHOWN + 4 }, (_, i) => command(`room:r${i}`, `r${i}`, "Rooms"));
    const [section] = paletteSections(rooms, [], "r");
    expect(section.commands.filter(c => c.id.startsWith("room:"))).toHaveLength(ROOMS_SHOWN + 4);
  });
});
