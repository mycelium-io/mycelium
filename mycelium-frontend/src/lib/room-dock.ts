// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The room's center as tabs and splits: what a tab can be, its id, and the
 * layout remembered per room in this browser.
 *
 * Every view in the center is one kind of tab. The room's own views (Channel,
 * Board, Schedules, Raw messages) have fixed ids; a memory and a thread are
 * keyed by what they show, so opening one that is already open shows it rather
 * than a second copy.
 */

export type View = "channel" | "board" | "schedules" | "raw";

export type DockPanelKind = View | "memory" | "thread";

export const ROOM_VIEWS: readonly View[] = ["channel", "board", "schedules", "raw"];

export const VIEW_LABELS: Record<View, string> = {
  channel: "Channel",
  board: "Board",
  schedules: "Schedules",
  raw: "Raw messages",
};

/** The id the raw message feed had while it was the Network tab. A layout
 *  saved then opens the feed in the same place. */
const LEGACY_IDS: Record<string, { id: View; title: string }> = {
  network: { id: "raw", title: VIEW_LABELS.raw },
};

/** A saved layout with its tabs' old ids replaced by the ones this version
 *  draws: every string equal to an old id (the panel's key, its component,
 *  and its place in the grid), and the tab's title with it. */
export function migrateLayout(layout: unknown): unknown {
  const walk = (node: unknown): unknown => {
    if (typeof node === "string") return LEGACY_IDS[node]?.id ?? node;
    if (Array.isArray(node)) return node.map(walk);
    if (!node || typeof node !== "object") return node;
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(node)) {
      const legacy = LEGACY_IDS[key];
      const next = walk(value);
      if (legacy && next && typeof next === "object" && "title" in next) {
        (next as Record<string, unknown>).title = legacy.title;
      }
      out[legacy?.id ?? key] = next;
    }
    return out;
  };
  return walk(layout);
}

/** The params a tab carries in the saved layout: only what names it. */
export type DockPanelParams = { key: string } | { episode: string } | Record<string, never>;

export function memoryPanelId(key: string): string {
  return `memory:${key}`;
}

export function threadPanelId(episode: string): string {
  return `thread:${episode}`;
}

/** What a panel id names. `null` for an id this version doesn't draw. */
export function parsePanelId(
  id: string,
): { kind: View } | { kind: "memory"; key: string } | { kind: "thread"; episode: string } | null {
  if ((ROOM_VIEWS as readonly string[]).includes(id)) return { kind: id as View };
  if (id.startsWith("memory:") && id.length > 7) return { kind: "memory", key: id.slice(7) };
  if (id.startsWith("thread:") && id.length > 7) return { kind: "thread", episode: id.slice(7) };
  return null;
}

/** The Channel is the room's home: every other tab can close, it can't. */
export function isClosable(id: string): boolean {
  return id !== "channel";
}

const STORAGE_PREFIX = "mycelium.dock.";

/** The saved layout for a room, or null when there is none or it can't be read. */
export function loadLayout(room: string): unknown {
  try {
    const raw = window.localStorage.getItem(STORAGE_PREFIX + room);
    return raw ? migrateLayout(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

export function saveLayout(room: string, layout: unknown): void {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + room, JSON.stringify(layout));
  } catch {
    // Storage full or blocked: the layout just isn't remembered.
  }
}

export function forgetLayout(room: string): void {
  try {
    window.localStorage.removeItem(STORAGE_PREFIX + room);
  } catch {
    // Nothing to forget.
  }
}

interface SerializedPanel {
  id: string;
  contentComponent?: string;
  params?: unknown;
}

/**
 * A saved layout this version can restore: every panel it names is one it can
 * draw, with the component that draws it, and the Channel is among them. A
 * layout from an older or newer version that fails any of that is dropped
 * rather than half-restored.
 */
export function restorableLayout(layout: unknown): boolean {
  if (!layout || typeof layout !== "object") return false;
  const panels = (layout as { panels?: Record<string, SerializedPanel> }).panels;
  if (!panels || typeof panels !== "object") return false;
  const ids = Object.keys(panels);
  if (!ids.includes("channel")) return false;
  return ids.every(id => {
    const parsed = parsePanelId(id);
    return parsed !== null && panels[id]?.contentComponent === parsed.kind;
  });
}
