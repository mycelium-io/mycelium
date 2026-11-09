// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Where an agent's terminal window sits: a window you drag and resize,
 * remembered per agent in this browser, so an agent opens where you left it.
 * What's remembered is put back inside the window you have now, so a terminal
 * never opens off-screen after the window shrank or a display went.
 */

export interface WindowRect {
  x: number;
  y: number;
  width: number;
  height: number;
}

const STORAGE_KEY = "mycelium.terminal-windows";

/** The smallest a terminal window gets: a few lines of a narrow one. */
export const MIN_WINDOW = { width: 320, height: 240 } as const;

/** The gap it keeps from the edges of the app's window. */
const MARGIN = 8;

/** Room left above it for the title bar, and below it for the status bar. */
const TOP = 56;
const BOTTOM = 40;

/** A first window's place: on the right, over Members, as tall as the room.
 *  A terminal is tall, so it starts that way. */
export function defaultRect(viewport: { width: number; height: number }): WindowRect {
  const width = Math.min(600, viewport.width - 32);
  const height = Math.max(MIN_WINDOW.height, viewport.height - TOP - BOTTOM);
  return { x: Math.max(16, viewport.width - width - 8), y: TOP, width, height };
}

/** `rect` made to fit `viewport`: wholly inside it, no smaller than the
 *  minimum. In a window too small for even that, its top left stays on it,
 *  so its header can still be reached. */
export function clampRect(rect: WindowRect, viewport: { width: number; height: number }): WindowRect {
  const width = Math.max(MIN_WINDOW.width, Math.min(rect.width, viewport.width - 2 * MARGIN));
  const height = Math.max(MIN_WINDOW.height, Math.min(rect.height, viewport.height - 2 * MARGIN));
  const x = Math.max(MARGIN, Math.min(rect.x, viewport.width - width - MARGIN));
  const y = Math.max(MARGIN, Math.min(rect.y, viewport.height - height - MARGIN));
  return { x, y, width, height };
}

/** The most `rect` may grow from its corner, so it stays inside `viewport`. */
export function maxSize(rect: WindowRect, viewport: { width: number; height: number }) {
  return {
    width: Math.max(MIN_WINDOW.width, viewport.width - rect.x - MARGIN),
    height: Math.max(MIN_WINDOW.height, viewport.height - rect.y - MARGIN),
  };
}

function readAll(): Record<string, WindowRect> {
  try {
    const parsed = JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}") as unknown;
    return parsed && typeof parsed === "object" && !Array.isArray(parsed) ? (parsed as Record<string, WindowRect>) : {};
  } catch {
    return {};
  }
}

function isRect(v: unknown): v is WindowRect {
  const r = v as WindowRect | null;
  return !!r && [r.x, r.y, r.width, r.height].every((n) => typeof n === "number" && Number.isFinite(n));
}

/** Where `handle`'s window was left, or null for one never popped out. */
export function savedRect(handle: string): WindowRect | null {
  const r = readAll()[handle.toLowerCase()];
  return isRect(r) ? r : null;
}

export function saveRect(handle: string, rect: WindowRect): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...readAll(), [handle.toLowerCase()]: rect }));
  } catch {
    // A browser refusing storage just forgets it.
  }
}
