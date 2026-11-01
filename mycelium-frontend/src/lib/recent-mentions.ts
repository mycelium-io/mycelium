// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Who you last @-mentioned in a room, so the composer's `@` list puts them
 * first. Kept per browser and per room, as a convenience: losing it (a private
 * window, cleared storage) only means the list falls back to the roster's order.
 */

const PREFIX = "mycelium.recentMentions.";
/** Said when a send records new mentions, so every composer on the page re-reads. */
export const RECENT_MENTIONS_CHANGED = "mycelium:recent-mentions";
/** How many handles a room remembers; the rest are forgotten oldest first. */
const KEEP = 50;

export type RecentMentions = Record<string, number>;

export function readRecentMentions(room: string): RecentMentions {
  try {
    const raw = window.localStorage.getItem(PREFIX + room);
    const parsed: unknown = raw ? JSON.parse(raw) : {};
    if (!parsed || typeof parsed !== "object") return {};
    return Object.fromEntries(
      Object.entries(parsed as Record<string, unknown>).filter(
        (e): e is [string, number] => typeof e[1] === "number",
      ),
    );
  } catch {
    return {};
  }
}

/** Record that ``handles`` were mentioned in ``room`` just now. */
export function recordMentions(room: string, handles: string[], at: number = Date.now()): void {
  if (handles.length === 0) return;
  try {
    const next = readRecentMentions(room);
    for (const h of handles) next[h.toLowerCase()] = at;
    const kept = Object.entries(next)
      .sort((a, b) => b[1] - a[1])
      .slice(0, KEEP);
    window.localStorage.setItem(PREFIX + room, JSON.stringify(Object.fromEntries(kept)));
    window.dispatchEvent(new Event(RECENT_MENTIONS_CHANGED));
  } catch {
    // Storage unavailable: the list keeps the roster's order.
  }
}
