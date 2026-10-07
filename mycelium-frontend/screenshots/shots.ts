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
  /** Route under the mock server, e.g. `/room/checkout`. */
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
  /**
   * shotkit actions run after `steps`, verbatim (`click:<selector>`,
   * `typekeys:<text>`, ...), for a state a click by name can't reach: a
   * dialog filled in, a list opened.
   */
  actions?: string[];
  /**
   * A first visit: nobody has said who they are, so the app asks. Every other
   * shot is taken as Morgan (@operator), the person in the mock rooms.
   */
  fresh?: boolean;
  /** One-line note on what this shot is meant to show. */
  caption: string;
}

export const SHOTS: Shot[] = [
  {
    id: "home",
    route: "/",
    theme: "dark",
    viewport: "desktop",
    waitFor: "text=Recent",
    caption: "Home: where you start, and the rooms you were last in.",
  },
  {
    id: "room-channel",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    caption: "The room channel: people and agents in one conversation, with the work narrated as it happens.",
  },
  {
    id: "room-board",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    steps: ["Board"],
    // The pull requests' states arrive after the rows; shoot them answered.
    actions: ["wait-text:changes requested"],
    caption: "The board is the surface: task rows grouped by attention, each a row and a thread, with owners, CI and thread activity.",
  },
  {
    id: "room-start",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    actions: [
      // The composer's + opens a menu of what a room holds (#1044).
      'click:button[aria-label="Add to the room"]',
      'click:css=button:has-text("Task or flow…")',
      'click:[role="dialog"] button[aria-pressed]:has-text("Review")',
      'click:[role="dialog"] input',
      "typekeys:Add a gift message to orders",
      'click:[role="dialog"] textarea',
      "typekeys:A box at checkout, 200 characters max, printed on the packing slip.",
      "click:text=Choose one agent",
      'click:[role="dialog"] li button:has-text("builder")',
      "click:text=Choose one agent",
      'click:[role="dialog"] li button:has-text("reviewer")',
      "sleep:400",
    ],
    caption: "Starting work from the room: a task, and the flow to run on it, picked by what you want.",
  },
  {
    id: "room-empty",
    route: "/room/scratch",
    theme: "dark",
    viewport: "desktop",
    caption: "A fresh, empty room — the starting state.",
  },
  {
    id: "room-memory",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    steps: ["Memory"],
    caption: "The memory rail: namespaced markdown files with versions and contributors.",
  },
  {
    id: "room-network",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    steps: ["Network"],
    caption: "The network pane: SLIM channel diagnostics over a live message feed.",
  },

  // ── The docs' concept and guide pages ────────────────────────────────────
  {
    id: "board-columns",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    steps: ["Board"],
    // The view switcher's "Board" (columns), not the tab of the same name.
    actions: ['click:css=button[aria-label="Board"]', "sleep:800"],
    caption: "The board's columns view: the same rows, grouped by any field.",
  },
  {
    id: "thread-flow",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    steps: ["Board"],
    actions: [
      'click:[data-board-row="memory:work/turn-on-apple-pay"]',
      "sleep:1200",
      'click:css=button[aria-expanded]:has-text("Flow")',
      "sleep:800",
    ],
    caption: "A flow at the top of a task's thread: the steps, the one it's on, and who has the floor.",
  },
  {
    id: "swarm-dialog",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    steps: ["Board"],
    actions: [
      'click:css=button:has-text("Swarm")',
      'click:[role="dialog"] textarea',
      "typekeys:Write the release notes for the spring sale",
      "sleep:400",
    ],
    caption: "Starting a swarm: how many agents, and where they run.",
  },
  {
    id: "machines",
    route: "/machines",
    theme: "dark",
    viewport: "desktop",
    waitFor: "text=Agents on this machine",
    caption: "The Machines page: each of your machines, its agent CLIs, its agents, and what to fix.",
  },
  {
    id: "metrics-usage",
    route: "/metrics",
    theme: "dark",
    viewport: "desktop",
    waitFor: "text=Is the board keeping up?",
    caption: "The Metrics page's Usage tab: what gets filed, what gets done, and how work is started.",
  },

  // ── The docs walkthrough ("Your first room"), one shot per step ──────────
  {
    id: "walk-name",
    route: "/",
    theme: "dark",
    viewport: "desktop",
    fresh: true,
    waitFor: "text=What should we call you?",
    actions: ['click:[role="dialog"] input', "typekeys:Morgan Reyes", "sleep:300"],
    caption: "The first thing the app asks: your name.",
  },
  {
    id: "walk-add-agent",
    route: "/room/scratch",
    theme: "dark",
    viewport: "desktop",
    actions: [
      'click:role=button[name="Add"]',
      'click:[role="dialog"] button:has-text("implementer")',
      "fill:#member-handle=builder",
      "sleep:400",
    ],
    caption: "Adding an agent: a coding agent on your machine, started from a role.",
  },
  {
    id: "walk-task",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    actions: [
      'click:role=textbox[name=/Message/]',
      "typekeys:/task Add a gift message to orders @builder ",
      "sleep:400",
    ],
    caption: "Handing an agent a task from the message box.",
  },
  {
    id: "walk-thread",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    steps: ["Board"],
    // By the row's key: its title also appears in another row's "blocks" note.
    actions: ['click:[data-board-row="memory:work/turn-on-apple-pay"]', "sleep:1200"],
    caption: "A task's own thread: the agents talk it through here, not in the room.",
  },
  {
    id: "walk-aligner",
    route: "/room/checkout?focus=message:neg-say-1",
    theme: "dark",
    viewport: "desktop",
    actions: ["sleep:1200"],
    caption: "The aligner asking each side in turn until they agree.",
  },
];
