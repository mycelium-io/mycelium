// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import {
  chordFor,
  chordKey,
  eventToChord,
  findConflicts,
  formatChord,
  hintLabels,
  isRevealChord,
  KEYMAP,
  matchBinding,
  type Binding,
} from "@/lib/keymap";

function chord(init: Partial<KeyboardEvent> & { key: string }): KeyboardEvent {
  return { code: "", ...init } as KeyboardEvent;
}

describe("keymap", () => {
  it("declares no conflicting bindings", () => {
    expect(findConflicts()).toEqual([]);
  });

  it("catches a duplicate chord and a reused id", () => {
    const dupe: Binding[] = [
      { id: "a", keys: ["alt+c"], label: "a", group: "g", scope: "global" },
      { id: "b", keys: ["alt+c"], label: "b", group: "g", scope: "room" },
    ];
    expect(findConflicts(dupe)).toHaveLength(1);

    const reused: Binding[] = [
      { id: "a", keys: ["x"], label: "a", group: "g", scope: "room" },
      { id: "a", keys: ["y"], label: "a", group: "g", scope: "room" },
    ];
    expect(findConflicts(reused)).toContain('duplicate action id "a"');
  });

  it("leaves bindings from another scope unmatched", () => {
    expect(matchBinding("alt+c", ["global", "room"])?.id).toBe("pane.channel");
    expect(matchBinding("alt+c", ["global"])).toBeUndefined();
  });

  it("matches every chord a binding declares", () => {
    expect(matchBinding("]", ["global"])?.id).toBe("rooms.next");
    expect(matchBinding("J", ["global"])?.id).toBe("rooms.next");
    expect(matchBinding("j", ["global"])).toBeUndefined();
  });

  it("keeps every navigation key on one modifier so a single hold reveals them", () => {
    const revealable = KEYMAP.filter(b => ["Navigate", "Rooms", "Panes", "Inspector"].includes(b.group))
      .flatMap(b => b.keys)
      .filter(isRevealChord);
    expect(revealable.length).toBeGreaterThan(0);
    expect(revealable.every(c => c.startsWith("alt+"))).toBe(true);
  });

  it("keeps the pane and rail keys clear of the browser's own chords", () => {
    // ⌘/Ctrl + C, L, N, P, S are copy / address bar / new window / print /
    // save — a page can't have them, so the reveal modifier is ⌥ alone. ⌘K is
    // not among them, and is the chord everyone already tries for a palette.
    const reserved = ["c", "l", "n", "p", "s"].map(k => `mod+${k}`);
    const taken = KEYMAP.flatMap(b => b.keys).filter(c => reserved.includes(c));
    expect(taken).toEqual([]);
  });

  it("renders modifiers per platform", () => {
    expect(formatChord("alt+c", true)).toBe("⌥C");
    expect(formatChord("alt+c", false)).toBe("Alt+C");
    expect(formatChord("mod+k", true)).toBe("⌘K");
    expect(formatChord("Escape", false)).toBe("Esc");
    expect(chordKey("alt+1")).toBe("1");
  });

  it("resolves an action to the chord its badge draws", () => {
    expect(chordFor("pane.network")).toBe("alt+w");
    expect(chordFor("nope")).toBeUndefined();
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
  it("reads a modified chord off the physical key", () => {
    // ⌥C reports key "ç" on macOS; the binding still has to fire.
    expect(eventToChord(chord({ key: "ç", code: "KeyC", altKey: true }), true)).toBe("alt+c");
    expect(eventToChord(chord({ key: "1", code: "Digit1", altKey: true }), false)).toBe("alt+1");
  });

  it("reads an unmodified chord off the character, so shift stays meaningful", () => {
    expect(eventToChord(chord({ key: "J", code: "KeyJ", shiftKey: true }), false)).toBe("J");
    expect(eventToChord(chord({ key: "]", code: "BracketRight" }), false)).toBe("]");
    expect(eventToChord(chord({ key: " ", code: "Space" }), false)).toBe("Space");
  });

  it("prefixes the platform command modifier and inerts the other one", () => {
    expect(eventToChord(chord({ key: "k", code: "KeyK", metaKey: true }), true)).toBe("mod+k");
    expect(eventToChord(chord({ key: "k", code: "KeyK", ctrlKey: true }), false)).toBe("mod+k");
    // ⌃C on macOS must not read as the bare `c` binding.
    expect(eventToChord(chord({ key: "c", code: "KeyC", ctrlKey: true }), true)).toBe("foreign+c");
  });
});
