// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  eventToChord,
  findConflicts,
  formatSequence,
  hintLabels,
  isSequencePrefix,
  KEYMAP,
  matchBinding,
  type Binding,
} from "@/lib/keymap";

function chord(init: Partial<KeyboardEvent> & { key: string }): KeyboardEvent {
  return init as KeyboardEvent;
}

describe("keymap", () => {
  it("declares no conflicting bindings", () => {
    expect(findConflicts()).toEqual([]);
  });

  it("catches a duplicate binding, a shadowed prefix, and a reused id", () => {
    const dupe: Binding[] = [
      { id: "a", keys: ["g c"], label: "a", group: "g", scope: "global" },
      { id: "b", keys: ["g c"], label: "b", group: "g", scope: "room" },
    ];
    expect(findConflicts(dupe)).toHaveLength(1);

    const shadow: Binding[] = [
      { id: "a", keys: ["g"], label: "a", group: "g", scope: "global" },
      { id: "b", keys: ["g c"], label: "b", group: "g", scope: "room" },
    ];
    expect(findConflicts(shadow)[0]).toContain("shadows");

    const reused: Binding[] = [
      { id: "a", keys: ["x"], label: "a", group: "g", scope: "room" },
      { id: "a", keys: ["y"], label: "a", group: "g", scope: "room" },
    ];
    expect(findConflicts(reused)).toContain('duplicate action id "a"');
  });

  it("leaves bindings from another scope unmatched", () => {
    expect(matchBinding("g c", ["global", "room"])?.id).toBe("pane.channel");
    expect(matchBinding("g c", ["global"])).toBeUndefined();
  });

  it("holds a leader open only while it can still complete", () => {
    expect(isSequencePrefix("g", ["global", "room"])).toBe(true);
    expect(isSequencePrefix("g", ["global"])).toBe(true); // g h → home
    expect(isSequencePrefix("x", ["global", "room"])).toBe(false);
  });

  it("matches every key a binding declares", () => {
    expect(matchBinding("]", ["global"])?.id).toBe("rooms.next");
    expect(matchBinding("J", ["global"])?.id).toBe("rooms.next");
    expect(matchBinding("j", ["global"])).toBeUndefined();
  });

  it("renders modifiers per platform", () => {
    expect(formatSequence("g c", false)).toEqual(["g", "c"]);
    expect(formatSequence("mod+k", true)).toEqual(["⌘k"]);
    expect(formatSequence("mod+k", false)).toEqual(["Ctrl+k"]);
    expect(formatSequence("Escape", false)).toEqual(["Esc"]);
  });

  it("gives every KEYMAP entry a label and a group", () => {
    for (const binding of KEYMAP) {
      expect(binding.keys.length).toBeGreaterThan(0);
      expect(binding.label).not.toBe("");
      expect(binding.group).not.toBe("");
    }
  });

  it("uses single home-row hints while the alphabet fits", () => {
    expect(hintLabels(3)).toEqual(["a", "s", "d"]);
    expect(hintLabels(9)).toHaveLength(9);
    expect(hintLabels(9).every(l => l.length === 1)).toBe(true);
  });

  it("widens to prefix-free multi-char hints past the alphabet", () => {
    const labels = hintLabels(12);
    expect(labels).toHaveLength(12);
    expect(labels.every(l => l.length === 2)).toBe(true);
    expect(new Set(labels).size).toBe(12);
    expect(labels.slice(0, 2)).toEqual(["aa", "as"]);

    const many = hintLabels(200);
    expect(many).toHaveLength(200);
    expect(many.every(l => l.length === 3)).toBe(true);
    expect(new Set(many).size).toBe(200);
  });

  it("has no hints for an empty list", () => {
    expect(hintLabels(0)).toEqual([]);
  });
});

describe("eventToChord", () => {
  it("prefixes the platform command modifier and inerts the other one", () => {
    expect(eventToChord(chord({ key: "c" }), true)).toBe("c");
    expect(eventToChord(chord({ key: "k", metaKey: true }), true)).toBe("mod+k");
    expect(eventToChord(chord({ key: "k", ctrlKey: true }), false)).toBe("mod+k");
    // ⌃c on macOS must not read as the bare `c` binding.
    expect(eventToChord(chord({ key: "c", ctrlKey: true }), true)).toBe("foreign+c");
    expect(eventToChord(chord({ key: " " }), false)).toBe("Space");
  });
});
