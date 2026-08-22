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

/**
 * How much room to leave above the width where a layout stops fitting, so a
 * rail folds a step before the squeeze rather than in the middle of it. One
 * rail's worth of chrome — enough that a window dragged quickly still crosses
 * the fold before it crosses the floor.
 */
const FOLD_MARGIN = 60;

/** Group ids. Also the localStorage keys the saved layouts live under. */
export const SHELL_GROUP_ID = "mycelium:shell";
export const ROOM_GROUP_ID = "mycelium:room";

/** Panel ids within those groups. Stable — a saved layout is keyed by them. */
export const PANEL_ROOMS = "rooms";
export const PANEL_WORKSPACE = "workspace";
export const PANEL_MAIN = "main";
export const PANEL_INSPECTOR = "inspector";

/**
 * The id lists `useDefaultLayout` takes, as constants rather than array
 * literals at the call site. The hook memoizes the layout it reads back out of
 * storage on the identity of this array, and hands the group a new one whenever
 * it changes — which a fresh literal does on every render, re-applying the
 * stored layout over whatever the group is currently doing.
 */
export const SHELL_PANEL_IDS = [PANEL_ROOMS, PANEL_WORKSPACE];
export const ROOM_PANEL_IDS = [PANEL_MAIN, PANEL_INSPECTOR];

/** The rooms rail: wide enough for a monogram plus a room name. Collapses to a
 *  strip of room monograms rather than to nothing, so every room stays one
 *  click away on a window too narrow to hold their names. */
export const ROOMS_PANEL = {
  default: "236px",
  min: "180px",
  max: "420px",
  /** The monogram strip's width. Matches the inspector's collapsed strip. */
  collapsed: "48px",
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

/** The hairline a `ResizableHandle` draws between two panels. */
const SEAM = 1;

const px = (value: string) => Number.parseInt(value, 10);

/**
 * Viewport widths at which each rail folds itself away, and unfolds again.
 *
 * Derived from the panels rather than picked as round numbers, and with the
 * margin deliberate: a rail has to fold *before* the window is too narrow to
 * hold it, not at the moment it already is. A group whose minimums no longer
 * fit can't satisfy them, and `react-resizable-panels` answers an unsatisfiable
 * constraint set by refusing to move anything at all — the collapse that would
 * have made everything fit included. Folding a step early keeps the layout
 * solvable at every width, so the collapse is always a move the group can make.
 * Each rail's *default* is the width in the sum, not its minimum: a rail that
 * folds before anything squeezes it folds at the width it will unfold to.
 *
 * The window is the measure rather than the group beside the rail: it's what
 * the reader is actually resizing, and it doesn't move when they drag a seam.
 * A rail dragged wide on a small window squeezes its neighbour, as it always
 * has — that squeeze is the reader's own doing, and their drag undoes it.
 */
export const INSPECTOR_FOLD_WIDTH =
  px(ROOMS_PANEL.default) + px(MAIN_PANEL.min) + px(INSPECTOR_PANEL.default) + 2 * SEAM + FOLD_MARGIN;

/** With the inspector already a strip by the time this matters. */
export const ROOMS_FOLD_WIDTH =
  px(ROOMS_PANEL.default) + px(MAIN_PANEL.min) + px(INSPECTOR_PANEL.collapsed) + 2 * SEAM + FOLD_MARGIN;

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
