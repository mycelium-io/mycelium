// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The resizable shell's sizing contract, in one place.
 *
 * Every size is in pixels rather than a percentage of the group: these are
 * rails holding a fixed amount of chrome (a room row, a tab strip, a memory
 * tree), so what "too narrow" means doesn't change with the window. A panel
 * declared in pixels also keeps the width you dragged it to when the window
 * resizes, which is what `groupResizeBehavior: "preserve-pixel-size"` buys.
 *
 * Minimums are the width at which a rail is still *usable*, not the width at
 * which it stops rendering — the inspector's tab strip drops to icons before
 * its minimum (see `TAB_LABELS_MIN_WIDTH`), so 260px is a floor with the tabs
 * already in their compact form and the panel bodies still legible.
 */

/** Group ids. Also the localStorage keys the saved layouts live under. */
export const SHELL_GROUP_ID = "mycelium:shell";
export const ROOM_GROUP_ID = "mycelium:room";

/** Panel ids within those groups. Stable — a saved layout is keyed by them. */
export const PANEL_ROOMS = "rooms";
export const PANEL_WORKSPACE = "workspace";
export const PANEL_MAIN = "main";
export const PANEL_INSPECTOR = "inspector";

/** The rooms rail: wide enough for a monogram plus a room name. */
export const ROOMS_PANEL = {
  default: "236px",
  min: "180px",
  max: "420px",
} as const;

/** Whatever the page puts beside the rooms rail. Its minimum is what stops the
 *  rail's maximum from swallowing the page on a small window. */
export const WORKSPACE_PANEL = {
  min: "420px",
} as const;

/** The room's conversation. A hard floor so the inspector can't crush chat. */
export const MAIN_PANEL = {
  min: "360px",
} as const;

/** The inspector rail: members / episodes / memory. Collapses to a strip of
 *  tab icons rather than to nothing, so the rail is always one click away. */
export const INSPECTOR_PANEL = {
  default: "340px",
  min: "260px",
  max: "620px",
  /** The icon strip's width. Matches the collapsed `<aside>`'s `w-12`. */
  collapsed: "48px",
} as const;

/**
 * Below this the inspector's tab strip can't hold "Members / Episodes /
 * Memory" as words, so the tabs drop to icons alone. Measured against the
 * rail, not the viewport: the rail is what the tabs have to fit inside.
 */
export const TAB_LABELS_MIN_WIDTH = 312;

/**
 * A panel is "collapsed" once it's near its collapsed size. The library
 * reports pixel widths mid-animation, so this is a threshold rather than an
 * equality check on `collapsed`.
 */
export const COLLAPSED_THRESHOLD_PX = 72;

/**
 * `useDefaultLayout` reads its storage during render, so the library's
 * `localStorage` default throws on the server. This shim answers "nothing
 * saved" there and hands the real value back once hydrated (React re-renders
 * off the server snapshot), and stays quiet when storage is unavailable —
 * a private-mode browser loses the remembered layout, not the app.
 */
export const layoutStorage = {
  getItem(key: string): string | null {
    if (typeof window === "undefined") return null;
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  },
  setItem(key: string, value: string): void {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(key, value);
    } catch {
      // Storage denied (private mode, quota). The layout just isn't remembered.
    }
  },
};
