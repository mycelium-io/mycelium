// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** The app's keyboard vocabulary.
 *
 *  One table, declared once: the keybind dispatcher, the `?` cheatsheet, and
 *  anything else that wants to speak about keys read from here, so a binding
 *  can't exist in one surface and be missing from another. `findConflicts` is
 *  asserted empty by a unit test, so a duplicate or a shadowed prefix is a red
 *  gate rather than a key that silently stops working.
 *
 *  Notation: a binding's `keys` are sequences of chords separated by spaces
 *  ("g c" = press g, then c). A chord is an optional `mod+` (⌘ on macOS, Ctrl
 *  elsewhere) and `alt+` prefix followed by the `KeyboardEvent.key` value —
 *  case-sensitive, so "J" means shift+j. */

export type KeyScope = "global" | "room";

export interface Binding {
  /** Action id a component registers a handler for. */
  id: string;
  /** Chord sequences that trigger it; any one of them fires the action. */
  keys: string[];
  label: string;
  /** Cheatsheet section. */
  group: string;
  /** Where the binding is live — "global" everywhere, "room" inside a room. */
  scope: KeyScope;
  /** Cheatsheet rendering when listing every key would be noise ("1 … 9"). */
  display?: string;
}

/** Home-row characters for the room hint labels, in the order they're handed
 *  out. `hintLabels` widens to 2-char labels once a room list outgrows these. */
export const HINT_ALPHABET = "asdfghjkl";

const DIGIT_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"];

export const KEYMAP: Binding[] = [
  {
    id: "rooms.hints",
    keys: ["f"],
    label: "Room hints — hold to peek, press a label to jump",
    group: "Rooms",
    scope: "global",
  },
  { id: "rooms.next", keys: ["]", "J"], label: "Next room", group: "Rooms", scope: "global" },
  { id: "rooms.prev", keys: ["[", "K"], label: "Previous room", group: "Rooms", scope: "global" },
  {
    id: "rooms.digit",
    keys: DIGIT_KEYS,
    display: "1 … 9",
    label: "Jump to one of the first nine rooms",
    group: "Rooms",
    scope: "global",
  },
  { id: "nav.home", keys: ["g h"], label: "Command center", group: "Rooms", scope: "global" },

  { id: "pane.channel", keys: ["g c"], label: "Channel", group: "Panes", scope: "room" },
  { id: "pane.negotiate", keys: ["g n"], label: "Negotiate", group: "Panes", scope: "room" },
  { id: "pane.l9", keys: ["g l"], label: "L9", group: "Panes", scope: "room" },
  { id: "pane.plan", keys: ["g p"], label: "Plan", group: "Panes", scope: "room" },
  { id: "pane.slim", keys: ["g s"], label: "SLIM", group: "Panes", scope: "room" },

  { id: "rail.agents", keys: ["g a"], label: "Members", group: "Inspector", scope: "room" },
  { id: "rail.episodes", keys: ["g e"], label: "Episodes", group: "Inspector", scope: "room" },
  { id: "rail.memory", keys: ["g m"], label: "Memory", group: "Inspector", scope: "room" },
  { id: "rail.toggle", keys: ["\\"], label: "Collapse / expand the rail", group: "Inspector", scope: "room" },

  { id: "focus.chat", keys: ["i"], label: "Write a message", group: "Focus", scope: "room" },
  {
    id: "mode.command",
    keys: ["Escape"],
    label: "Leave the input — back to command mode",
    group: "Focus",
    scope: "global",
  },

  { id: "help.keys", keys: ["?"], label: "Keyboard shortcuts", group: "Help", scope: "global" },
];

const MODIFIER_KEYS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock", "OS", "AltGraph"]);

/** True for the keydown a modifier fires on its own — pressing ⇧ to reach `J`
 *  must not land in the sequence buffer as a chord of its own. */
export function isModifierKey(key: string): boolean {
  return MODIFIER_KEYS.has(key);
}

export function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPad|iPod/i.test(navigator.userAgent);
}

/** The chord a key event denotes, in the notation `keys` uses. The platform's
 *  *other* command modifier maps to an inert `foreign+` prefix that no binding
 *  can declare, so ⌃C on macOS never fires the binding on `c`. */
export function eventToChord(e: KeyboardEvent, mac: boolean): string {
  const parts: string[] = [];
  if (mac ? e.metaKey : e.ctrlKey) parts.push("mod");
  if (mac ? e.ctrlKey : e.metaKey) parts.push("foreign");
  if (e.altKey) parts.push("alt");
  parts.push(e.key === " " ? "Space" : e.key);
  return parts.join("+");
}

const CHORD_LABELS: Record<string, string> = { Escape: "Esc", ArrowUp: "↑", ArrowDown: "↓" };

/** Render one chord for display (⌘ vs Ctrl by platform). */
export function formatChord(chord: string, mac: boolean): string {
  const parts = chord.split("+");
  const key = parts.pop() ?? "";
  const mods = parts.map((m) => (m === "mod" ? (mac ? "⌘" : "Ctrl") : m === "alt" ? (mac ? "⌥" : "Alt") : m));
  return [...mods, CHORD_LABELS[key] ?? key].join(mac ? "" : "+");
}

/** Render a sequence as one display token per chord, e.g. ["g", "c"]. */
export function formatSequence(sequence: string, mac: boolean): string[] {
  return sequence.split(" ").map((chord) => formatChord(chord, mac));
}

function inScope(binding: Binding, scopes: readonly KeyScope[]): boolean {
  return scopes.includes(binding.scope);
}

export function bindingsInScope(scopes: readonly KeyScope[]): Binding[] {
  return KEYMAP.filter((b) => inScope(b, scopes));
}

/** The binding a fully-typed sequence fires, if any. */
export function matchBinding(sequence: string, scopes: readonly KeyScope[]): Binding | undefined {
  return KEYMAP.find((b) => inScope(b, scopes) && b.keys.includes(sequence));
}

/** True when the sequence so far is the start of a longer binding — the caller
 *  holds it open (the leader is "pending") instead of discarding the key. */
export function isSequencePrefix(sequence: string, scopes: readonly KeyScope[]): boolean {
  const prefix = `${sequence} `;
  return KEYMAP.some((b) => inScope(b, scopes) && b.keys.some((k) => k.startsWith(prefix)));
}

/** Every way two bindings can collide: the same sequence twice, a sequence that
 *  shadows a longer one as its prefix, or a reused action id. */
export function findConflicts(bindings: readonly Binding[] = KEYMAP): string[] {
  const conflicts: string[] = [];
  const seenIds = new Set<string>();
  for (const b of bindings) {
    if (seenIds.has(b.id)) conflicts.push(`duplicate action id "${b.id}"`);
    seenIds.add(b.id);
  }
  const overlap = (a: Binding, b: Binding) => a.scope === b.scope || a.scope === "global" || b.scope === "global";
  for (let i = 0; i < bindings.length; i += 1) {
    for (let j = i + 1; j < bindings.length; j += 1) {
      const a = bindings[i];
      const b = bindings[j];
      if (!overlap(a, b)) continue;
      for (const ka of a.keys) {
        for (const kb of b.keys) {
          if (ka === kb) conflicts.push(`${a.id} and ${b.id} both bind "${ka}"`);
          else if (kb.startsWith(`${ka} `)) conflicts.push(`${a.id} ("${ka}") shadows ${b.id} ("${kb}")`);
          else if (ka.startsWith(`${kb} `)) conflicts.push(`${b.id} ("${kb}") shadows ${a.id} ("${ka}")`);
        }
      }
    }
  }
  return conflicts;
}

/** Vimium-style hint labels, one per target in nav order. Labels are uniform
 *  width — single home-row chars while the list fits the alphabet, widening to
 *  2 chars (then 3) past it — so no label is a prefix of another and a typed
 *  label is never ambiguous. */
export function hintLabels(count: number, alphabet: string = HINT_ALPHABET): string[] {
  const chars = [...alphabet];
  if (count <= 0) return [];
  if (chars.length < 2) return chars.slice(0, count);

  let width = 1;
  while (chars.length ** width < count) width += 1;

  const labels: string[] = [];
  const build = (prefix: string) => {
    if (labels.length >= count) return;
    if (prefix.length === width) {
      labels.push(prefix);
      return;
    }
    for (const c of chars) build(prefix + c);
  };
  build("");
  return labels;
}
