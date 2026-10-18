// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The room's center as tabs and splits: what a tab can be, its id, and the
 * layout remembered per room in this browser.
 *
 * Every view in the center is one kind of tab. The room's own views (Channel,
 * Stream, Board, Files, Schedules) have fixed ids; a memory and a thread are
 * keyed by what they show, so opening one that is already open shows it rather
 * than a second copy.
 */

export type View = "channel" | "stream" | "board" | "files" | "schedules";

export type DockPanelKind = View | "memory" | "thread";

export const ROOM_VIEWS: readonly View[] = ["channel", "stream", "board", "files", "schedules"];

export const VIEW_LABELS: Record<View, string> = {
  channel: "Channel",
  stream: "Stream",
  board: "Board",
  files: "Files",
  schedules: "Schedules",
};

/** Tabs a room no longer has: the Network tab, and the Raw messages tab it
 *  became. A layout saved with one open loads without it. */
const RETIRED_IDS: ReadonlySet<string> = new Set(["network", "raw"]);

/** A saved layout without the tabs this version no longer draws. A retired tab
 *  is taken out of its group, and the group shows its first remaining tab if
 *  the retired one was in front. If that leaves a group empty, the layout's
 *  split sizes no longer add up, so `null` is returned and the room opens on
 *  its default layout instead. A memory tab whose key happens to be "raw" is
 *  untouched: only panel ids are compared. */
export function migrateLayout(layout: unknown): unknown {
  if (!layout || typeof layout !== "object") return layout;
  const saved = layout as { panels?: unknown; grid?: unknown };
  let emptied = false;

  const panels =
    saved.panels && typeof saved.panels === "object"
      ? Object.fromEntries(Object.entries(saved.panels as Record<string, unknown>).filter(([id]) => !RETIRED_IDS.has(id)))
      : saved.panels;

  const walkGrid = (node: unknown): unknown => {
    if (Array.isArray(node)) return node.map(walkGrid);
    if (!node || typeof node !== "object") return node;
    const out: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(node)) out[key] = walkGrid(value);
    if (Array.isArray(out.views)) {
      const views = (out.views as unknown[]).filter((v) => !(typeof v === "string" && RETIRED_IDS.has(v)));
      if (views.length === 0) emptied = true;
      if (typeof out.activeView === "string" && RETIRED_IDS.has(out.activeView)) out.activeView = views[0];
      out.views = views;
    }
    return out;
  };

  const grid = walkGrid(saved.grid);
  return emptied ? null : { ...saved, panels, grid };
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

/** The conversations in front, from the tab in front of each group: the
 *  Channel, and each task thread's episode. Other views show no messages. */
export function panesInFront(frontTabs: readonly (string | null | undefined)[]): string[] {
  const panes = new Set<string>();
  for (const id of frontTabs) {
    const parsed = id ? parsePanelId(id) : null;
    if (parsed?.kind === "channel") panes.add("channel");
    else if (parsed?.kind === "thread") panes.add(parsed.episode);
  }
  return [...panes];
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
