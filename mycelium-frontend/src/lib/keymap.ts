// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** The app's keyboard vocabulary.
 *
 *  One table, declared once: the keybind dispatcher, the reveal badges drawn on
 *  the targets themselves, and the `?` cheatsheet all read from here, so a
 *  binding can't exist in one surface and be missing from another.
 *  `findConflicts` is asserted empty by a unit test, so a duplicate is a red
 *  gate rather than a key that silently stops working.
 *
 *  Notation: a chord is an optional `mod+` (⌘ on macOS, Ctrl elsewhere) and
 *  `alt+` (⌥ on macOS) prefix followed by the key — case-sensitive for bare
 *  letters, so "J" means shift+j. */

export type KeyScope = "global" | "room";

export interface Binding {
  /** Action id a component registers a handler for. */
  id: string;
  /** Chords that trigger it; any one of them fires the action. */
  keys: string[];
  label: string;
  /** Cheatsheet section. */
  group: string;
  /** Where the binding is live — "global" everywhere, "room" inside a room. */
  scope: KeyScope;
  /** List the chords as a first…last range; for runs like ⌥1 through ⌥9. */
  abbreviate?: boolean;
  /** Set false to keep the binding out of the command palette: a key that holds
   *  an overlay open, or one the palette itself answers better. */
  palette?: boolean;
}

/** The modifier that, held on its own, reveals every navigation key as a badge
 *  on the thing it selects. ⌥ rather than ⌘/Ctrl because the obvious mnemonic
 *  chords there — ⌘C, ⌘L, ⌘P, ⌘S — are all taken by the browser. */
export const REVEAL_MODIFIER_KEY = "Alt";

/** Home-row characters for the room hint labels, in the order they're handed
 *  out. `hintLabels` widens to 2-char labels once a room list outgrows these. */
export const HINT_ALPHABET = "asdfghjkl";

const ROOM_DIGIT_KEYS = ["1", "2", "3", "4", "5", "6", "7", "8", "9"].map(d => `alt+${d}`);

export const KEYMAP: Binding[] = [
  {
    id: "palette.open",
    keys: ["mod+k"],
    label: "Command palette",
    group: "Help",
    scope: "global",
    // The palette can't offer itself a way in.
    palette: false,
  },
  // The other half of the pair: ⌘K runs actions, `/` finds content (bare key).
  {
    id: "search.open",
    keys: ["/"],
    label: "Search everything",
    group: "Search",
    scope: "global",
  },

  {
    id: "rooms.digit",
    keys: ROOM_DIGIT_KEYS,
    abbreviate: true,
    label: "Jump to one of the first nine rooms",
    group: "Rooms",
    scope: "global",
    // The palette lists the rooms themselves, by name and past the ninth.
    palette: false,
  },
  { id: "rooms.next", keys: ["]", "J"], label: "Next room", group: "Rooms", scope: "global" },
  { id: "rooms.prev", keys: ["[", "K"], label: "Previous room", group: "Rooms", scope: "global" },
  {
    id: "rooms.toggle",
    keys: ["alt+b"],
    label: "Collapse / expand the rooms rail",
    group: "Rooms",
    scope: "global",
  },
  { id: "nav.home", keys: ["alt+h"], label: "Command center", group: "Navigate", scope: "global" },

  { id: "pane.channel", keys: ["alt+c"], label: "Channel", group: "Panes", scope: "room" },
  { id: "pane.negotiate", keys: ["alt+n"], label: "Negotiate", group: "Panes", scope: "room" },
  { id: "pane.board", keys: ["alt+p"], label: "Board", group: "Panes", scope: "room" },
  // Network = the merged SLIM diagnostics rail + L9 protocol feed. ⌥W (netWork);
  // ⌥N is taken by Negotiate.
  { id: "pane.network", keys: ["alt+w"], label: "Network", group: "Panes", scope: "room" },

  { id: "rail.agents", keys: ["alt+a"], label: "Members", group: "Inspector", scope: "room" },
  // Not ⌥E: Alt+E opens the browser menu on Windows and Linux.
  { id: "rail.episodes", keys: ["alt+i"], label: "Episodes", group: "Inspector", scope: "room" },
  { id: "rail.memory", keys: ["alt+m"], label: "Memory", group: "Inspector", scope: "room" },
  { id: "rail.toggle", keys: ["\\"], label: "Collapse / expand the rail", group: "Inspector", scope: "room" },

  { id: "focus.chat", keys: ["i", "Enter"], label: "Write a message", group: "Focus", scope: "room" },
  {
    id: "mode.command",
    keys: ["Escape"],
    label: "Leave the input — back to command mode",
    group: "Focus",
    scope: "global",
    // Nothing to run: it's what leaving the palette already does.
    palette: false,
  },

  { id: "help.keys", keys: ["?"], label: "Keyboard shortcuts", group: "Help", scope: "global" },
];

const MODIFIER_KEYS = new Set(["Shift", "Control", "Alt", "Meta", "CapsLock", "OS", "AltGraph"]);

/** True for the keydown a modifier fires on its own. */
export function isModifierKey(key: string): boolean {
  return MODIFIER_KEYS.has(key);
}

export function isMacPlatform(): boolean {
  if (typeof navigator === "undefined") return false;
  return /Mac|iPhone|iPad|iPod/i.test(navigator.userAgent);
}

/** The physical key behind an event, for chords where the produced character
 *  can't be trusted: ⌥C reports "ç" on macOS, and any non-QWERTY layout moves
 *  the letters around. */
function physicalKey(code: string, fallback: string): string {
  const letter = /^Key([A-Z])$/.exec(code);
  if (letter) return letter[1].toLowerCase();
  const digit = /^Digit([0-9])$/.exec(code);
  if (digit) return digit[1];
  return code || fallback;
}

/** The chord a key event denotes, in the notation `keys` uses. The platform's
 *  *other* command modifier maps to an inert `foreign+` prefix that no binding
 *  can declare, so ⌃C on macOS never fires the binding on `c`. */
export function eventToChord(e: KeyboardEvent, mac: boolean): string {
  const parts: string[] = [];
  if (mac ? e.metaKey : e.ctrlKey) parts.push("mod");
  if (mac ? e.ctrlKey : e.metaKey) parts.push("foreign");
  if (e.altKey) parts.push("alt");
  if (parts.length > 0) parts.push(physicalKey(e.code, e.key));
  else parts.push(e.key === " " ? "Space" : e.key);
  return parts.join("+");
}

const CHORD_LABELS: Record<string, string> = { Escape: "Esc", Backslash: "\\" };

/** True for a chord the reveal modifier fires — the only kind a badge can
 *  honestly draw, since a badge is read while that modifier is held. */
export function isRevealChord(chord: string): boolean {
  return chord.startsWith("alt+");
}

/** True for a ⌘/Ctrl chord (stays live when text input has focus). */
export function isCommandChord(chord: string): boolean {
  return chord.startsWith("mod+");
}

/** The key half of a chord, as it reads on a badge or a keycap: "alt+c" → "C". */
export function chordKey(chord: string): string {
  const key = chord.split("+").pop() ?? "";
  const label = CHORD_LABELS[key] ?? key;
  return label.length === 1 ? label.toUpperCase() : label;
}

/** Render a whole chord for display (⌥⌘ vs Alt/Ctrl by platform). */
export function formatChord(chord: string, mac: boolean): string {
  const parts = chord.split("+");
  parts.pop();
  const mods = parts.map(m => (m === "mod" ? (mac ? "⌘" : "Ctrl") : mac ? "⌥" : "Alt"));
  return [...mods, chordKey(chord)].join(mac ? "" : "+");
}

function inScope(binding: Binding, scopes: readonly KeyScope[]): boolean {
  return scopes.includes(binding.scope);
}

export function bindingsInScope(scopes: readonly KeyScope[]): Binding[] {
  return KEYMAP.filter(b => inScope(b, scopes));
}

/** Bindings a command palette row can stand for: live here, and not opted out. */
export function paletteBindings(scopes: readonly KeyScope[]): Binding[] {
  return bindingsInScope(scopes).filter(b => b.palette !== false);
}

/** The binding a chord fires, if any. */
export function matchBinding(chord: string, scopes: readonly KeyScope[]): Binding | undefined {
  return KEYMAP.find(b => inScope(b, scopes) && b.keys.includes(chord));
}

/** The chord a given action answers to — what a target draws on its badge. */
export function chordFor(id: string): string | undefined {
  return KEYMAP.find(b => b.id === id)?.keys[0];
}

/** Two bindings collide if they share a chord in overlapping scopes, or reuse
 *  an action id. */
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
      for (const chord of a.keys) {
        if (b.keys.includes(chord)) conflicts.push(`${a.id} and ${b.id} both bind "${chord}"`);
      }
    }
  }
  return conflicts;
}

/** Vimium-style hint labels: uniform width, prefix-free (single char to multi-char as count grows). */
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
