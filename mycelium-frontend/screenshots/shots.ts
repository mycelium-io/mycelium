// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The shot manifest: the contract between "what states the mock can render" and
 * "what images we publish". Each entry names a route in `pnpm dev:mock`, the
 * theme + viewport to capture it at, and a selector to wait on before the shot
 * (deterministic fixtures mean we gate on an element, never a timeout).
 *
 * Adding a shot is a manifest edit here plus, if the state doesn't exist yet, a
 * fixture in `src/mocks/fixtures.ts`. `targets.ts` decides where each shot lands.
 */

export type Theme = "dark" | "light";

export interface Viewport {
  width: number;
  height: number;
  /** Device scale factor. 2 gives retina-crisp PNGs for @2x assets. */
  scale: number;
}

export const VIEWPORTS: Record<string, Viewport> = {
  // The product shell is a full-screen app; the viewport is the frame.
  desktop: { width: 1440, height: 900, scale: 2 },
  wide: { width: 1920, height: 1080, scale: 2 },
};

export interface Shot {
  /** Stable id; also the base filename (`<id>.png`, `<id>@2x.png`). */
  id: string;
  /** Route under the mock server, e.g. `/room/atlas-migration`. */
  route: string;
  theme: Theme;
  viewport: keyof typeof VIEWPORTS;
  /**
   * CSS selector to await before capturing. Defaults to the app-shell ready
   * hook (`[data-app-shell="ready"]`). Override for states that need a specific
   * panel mounted (e.g. an open memory detail).
   */
  waitFor?: string;
  /**
   * Optional selector to clip the screenshot to. Omit to capture the full
   * viewport (the shell fills it).
   */
  clip?: string;
  /**
   * Buttons to click (by accessible name) after the page settles and before the
   * shot — how we reach a view/rail that's behind a tab (Negotiate, Network) or
   * inspector rail (Memory) rather than a distinct route.
   */
  steps?: string[];
  /** One-line note on what this shot is meant to show. */
  caption: string;
}

export const SHOTS: Shot[] = [
  {
    id: "room-board",
    route: "/room/atlas-migration",
    theme: "dark",
    viewport: "desktop",
    steps: ["Board"],
    caption: "The board is the surface: task rows grouped by attention, each a row and a thread, with owners, CI and thread activity.",
  },
  {
    id: "room-empty",
    route: "/room/scratch",
    theme: "dark",
    viewport: "desktop",
    caption: "A fresh, empty room — the starting state.",
  },
  {
    id: "room-thread",
    route: "/room/atlas-migration",
    theme: "dark",
    viewport: "desktop",
    steps: ["Board", "flip reads behind a flag"],
    caption: "A task and its thread: the row, its markdown, and the conversation working it out — people and agents in one place.",
  },
  {
    id: "room-memory",
    route: "/room/atlas-migration",
    theme: "dark",
    viewport: "desktop",
    steps: ["Memory"],
    caption: "The memory rail: namespaced markdown files with versions and contributors.",
  },
  {
    id: "room-network",
    route: "/room/atlas-migration",
    theme: "dark",
    viewport: "desktop",
    steps: ["Network"],
    caption: "The network pane: SLIM channel diagnostics over a live L9 protocol feed.",
  },
];
