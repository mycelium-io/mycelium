// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { afterEach, describe, expect, it } from "vitest";
import {
  activeKeymap,
  applyOverrides,
  bindingsInScope,
  canSwap,
  conflictsFor,
  defaultKeys,
  findConflicts,
  isBrowserKept,
  isOverridden,
  KEYMAP,
  matchBinding,
  setKeyOverrides,
} from "@/lib/keymap";

afterEach(() => setKeyOverrides({}));

describe("keymap overrides", () => {
  it("fires an action on its new key and not its old one", () => {
    setKeyOverrides({ "rail.memory": ["alt+y"] });
    expect(matchBinding("alt+y", ["global", "room"])?.id).toBe("rail.memory");
    expect(matchBinding("alt+m", ["global", "room"])).toBeUndefined();
    expect(isOverridden("rail.memory")).toBe(true);
    expect(defaultKeys("rail.memory")).toEqual(["alt+m"]);
  });

  it("shows the person's keys in what the cheatsheet lists", () => {
    setKeyOverrides({ "nav.home": ["alt+g"] });
    expect(bindingsInScope(["global"]).find((b) => b.id === "nav.home")?.keys).toEqual(["alt+g"]);
  });

  it("ignores an override for a fixed action or an empty one", () => {
    const applied = applyOverrides(KEYMAP, { "rooms.digit": ["alt+x"], "mode.command": ["q"], "nav.home": [] });
    expect(applied.find((b) => b.id === "rooms.digit")?.keys).toEqual(KEYMAP.find((b) => b.id === "rooms.digit")?.keys);
    expect(applied.find((b) => b.id === "mode.command")?.keys).toEqual(["Escape"]);
    expect(applied.find((b) => b.id === "nav.home")?.keys).toEqual(["alt+h"]);
  });

  it("names what a new key would collide with, where both are live", () => {
    // ⌥C is the channel, a room binding; the home key is global, so they meet.
    expect(conflictsFor("nav.home", ["alt+c"]).map((b) => b.id)).toEqual(["pane.channel"]);
    expect(conflictsFor("nav.home", ["alt+z"])).toEqual([]);
  });

  it("won't swap onto a fixed action's key", () => {
    // Recording ⌥1 for Home clashes with the room keys, which can't move.
    const clashes = conflictsFor("nav.home", ["alt+1"]);
    expect(clashes.map((b) => b.id)).toEqual(["rooms.digit"]);
    expect(canSwap(clashes)).toBe(false);
    expect(canSwap(conflictsFor("nav.home", ["alt+c"]))).toBe(true);
  });

  it("keeps the table conflict-free after a swap", () => {
    setKeyOverrides({ "nav.home": ["alt+c"], "pane.channel": ["alt+h"] });
    expect(findConflicts(activeKeymap())).toEqual([]);
  });

  it("knows the chords a browser keeps for itself", () => {
    expect(isBrowserKept("mod+w")).toBe(true);
    expect(isBrowserKept("mod+k")).toBe(false);
  });
});
