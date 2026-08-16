// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/** The palette's command model: what a command is, how the list is ordered, and
 *  where "recent" is kept.
 *
 *  Two sources feed one list. Every keymap binding is a command — the palette
 *  reads `lib/keymap.ts` and shows each binding's chord beside it, so a key and
 *  its palette row can't describe different things. Components register the
 *  rest (a room, a dialog, a preference) for as long as they're mounted, which
 *  is what makes the list context-aware: leave a room and its commands go with
 *  it, no scope bookkeeping of their own.
 *
 *  Ranking is cmdk's fuzzy score plus a recency bonus small enough that a
 *  clearly better match still wins — recency breaks ties, it doesn't override
 *  what was typed. */

import { defaultFilter } from "cmdk";

export interface PaletteCommand {
  /** Stable across renders — recency is keyed by it, and a keymap-derived
   *  command reuses its binding id so the two can't drift apart. */
  id: string;
  title: string;
  /** Section heading in the palette. */
  group: string;
  /** Extra words the fuzzy match should see (a room's name, an alias). */
  keywords?: string[];
  /** Chord to draw on the row, in the notation `lib/keymap.ts` uses. Defaults
   *  to the keymap binding of the same id, where there is one. */
  shortcut?: string;
  run: () => void;
}

export interface PaletteSection {
  heading: string;
  commands: PaletteCommand[];
}

/** Ids kept in storage, and how many of them the Recent section shows. */
export const RECENT_LIMIT = 24;
export const RECENT_SHOWN = 5;

export const RECENT_HEADING = "Recent";

/** Ceiling on the recency bonus. cmdk's scores run 0…1, so a fraction this size
 *  reorders near-equal matches and leaves a decisive one alone. */
const RECENCY_BONUS = 0.15;

const RECENT_KEY = "mycelium.palette.recent";

export function loadRecent(): string[] {
  if (typeof localStorage === "undefined") return [];
  try {
    const raw = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(raw) ? raw.filter((id): id is string => typeof id === "string") : [];
  } catch {
    return [];
  }
}

export function saveRecent(ids: readonly string[]): void {
  if (typeof localStorage === "undefined") return;
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(ids));
  } catch {
    // A full or blocked store costs the ordering, not the palette.
  }
}

/** `id` to the front, most recent first, one entry per command. */
export function pushRecent(recent: readonly string[], id: string): string[] {
  return [id, ...recent.filter(r => r !== id)].slice(0, RECENT_LIMIT);
}

/** How much being recently run is worth, decaying to nothing at the tail. */
export function recencyBonus(recent: readonly string[], id: string): number {
  const i = recent.indexOf(id);
  if (i < 0) return 0;
  return (RECENCY_BONUS * (recent.length - i)) / recent.length;
}

/** cmdk's fuzzy filter with that bonus folded in. Items cmdk scores at zero stay
 *  hidden however recently they ran: a command the query rules out is out. */
export function paletteFilter(recent: readonly string[]) {
  return (value: string, search: string, keywords?: string[]): number => {
    const base = defaultFilter(value, search, keywords);
    return base === 0 ? 0 : base + recencyBonus(recent, value);
  };
}

/** Sections in this order, whoever registered first — the palette opens on the
 *  rooms, not on whichever component's effect happened to run earliest. Groups
 *  not listed here follow, in the order they turned up. */
const GROUP_ORDER = ["Rooms", "Navigate", "Panes", "Inspector", "Focus", "Preferences", "Help"];

function byGroup(commands: readonly PaletteCommand[]): PaletteSection[] {
  const sections = new Map<string, PaletteCommand[]>();
  for (const command of commands) {
    const list = sections.get(command.group) ?? [];
    list.push(command);
    sections.set(command.group, list);
  }
  const rank = (heading: string) => {
    const i = GROUP_ORDER.indexOf(heading);
    return i < 0 ? GROUP_ORDER.length : i;
  };
  return [...sections.entries()]
    .map(([heading, list]) => ({ heading, commands: list }))
    .sort((a, b) => rank(a.heading) - rank(b.heading));
}

/** The palette's sections, in render order.
 *
 *  With nothing typed the list is a standing menu, so the few commands actually
 *  used lead it. Once there's a query cmdk is sorting by score across the whole
 *  list, and a Recent section would only duplicate rows out of that order. */
export function paletteSections(
  commands: readonly PaletteCommand[],
  recent: readonly string[],
  query: string,
): PaletteSection[] {
  if (query.trim() !== "") return byGroup(commands);

  const byId = new Map(commands.map(c => [c.id, c]));
  const recentCommands = recent
    .map(id => byId.get(id))
    .filter((c): c is PaletteCommand => c !== undefined)
    .slice(0, RECENT_SHOWN);

  if (recentCommands.length === 0) return byGroup(commands);

  const promoted = new Set(recentCommands.map(c => c.id));
  return [
    { heading: RECENT_HEADING, commands: recentCommands },
    ...byGroup(commands.filter(c => !promoted.has(c.id))),
  ];
}
