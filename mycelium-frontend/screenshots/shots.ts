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
   * A region of the frame to keep, in CSS pixels, cut from the full-density
   * capture: for a page that shows one part of the app at a size it can be
   * read, where no single element holds that part.
   */
  crop?: { x: number; y: number; width: number; height: number };
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

const BASE: Shot[] = [
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
    // "Needs you" leaves out rows waiting on other work, so wait on a state
    // one of its own rows shows.
    actions: ["wait-text:CI running"],
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
    // Memory sits under Members in the rail; folding Members gives it the rail.
    actions: ['click:role=button[name="Collapse Members"]', "sleep:600"],
    caption: "The memory rail: namespaced markdown files with versions and contributors.",
  },
  {
    id: "room-stream",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    steps: ["Stream"],
    caption: "The stream: everything happening in the room, line by line, one lane per thread.",
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
      // A claimed task is under In flight, not the board's first view.
      "click:text=In flight",
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
      // The rail stacks Members over Memory, each with an Add; Members' is first.
      'click:role=button[name="Add"] >> nth=0',
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
    actions: [
      // A claimed task is under In flight, not the board's first view.
      "click:text=In flight",
      'click:[data-board-row="memory:work/turn-on-apple-pay"]',
      "sleep:1200",
    ],
    caption: "A task's own thread: the agents talk it through here, not in the room.",
  },
  {
    id: "mention",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    actions: [
      'click:role=textbox[name=/Message/]',
      "typekeys:Can you take the refund flow? @",
      "sleep:600",
    ],
    caption: "Asking an agent: @ lists the room's members, and the hints name @~ and @!.",
  },
  {
    id: "walk-aligner",
    route: "/room/checkout?focus=message:neg-say-1",
    theme: "dark",
    viewport: "desktop",
    actions: ["sleep:1200"],
    caption: "The aligner asking each side in turn until they agree.",
  },

  // ── The verifier (docs/verifier.html and its engine page), in both themes ──
  // Scrolled to rather than opened with ?focus=, which selects the message and
  // tints it. "It's fine" changes the mock's state, so each theme's run of these
  // needs a fresh mock server: `pnpm screenshots verifier-…` (dark), then again
  // for the `-light` ids.
  ...(["dark", "light"] as const).flatMap((theme): Shot[] => {
    const at = (id: string) => `css=[data-event-id]:has([data-verifier-flag="${id}"])`;
    const t = theme === "dark" ? "" : "-light";
    // Bring the flagged message into view, then move the pointer off it so its
    // hover toolbar isn't in the shot.
    const show = (id: string) => [`scroll:css=[data-verifier-flag="${id}"]`, "hover:text=Recently updated", "sleep:300"];
    return [
      {
        id: `verifier-line${t}`,
        route: "/room/checkout",
        theme,
        viewport: "desktop",
        waitFor: '[data-verifier-flag="vf1"]',
        actions: show("vf1"),
        clip: at("vf1"),
        caption: "A claim the records can't back: the line under the message, its words underlined.",
      },
      {
        id: `verifier-line-sure${t}`,
        route: "/room/checkout",
        theme,
        viewport: "desktop",
        waitFor: '[data-verifier-flag="vf3"]',
        actions: show("vf3"),
        clip: at("vf3"),
        caption: "A claim the records contradict: the darker line, which says when.",
      },
      {
        id: `verifier-show-why${t}`,
        route: "/room/checkout",
        theme,
        viewport: "desktop",
        waitFor: '[data-verifier-flag="vf3"]',
        actions: [...show("vf3"), 'click:[data-verifier-flag="vf3"] >> text=Show why', "sleep:400"],
        clip: 'css=[data-slot="popover-content"]',
        caption: "Show why: the failure, what the agent said, and what the verifier looked at.",
      },
      {
        id: `verifier-fine${t}`,
        route: "/room/checkout",
        theme,
        viewport: "desktop",
        waitFor: '[data-verifier-flag="vf1"]',
        actions: [
          ...show("vf1"),
          'click:[data-verifier-flag="vf1"] >> text=It\'s fine',
          'wait-hidden:[data-verifier-flag="vf1"]',
          // The click leaves the row's hover state on, so its toolbar stays up
          // after the pointer leaves; it isn't what this shot is about.
          "hover:text=Recently updated",
          `eval:document.querySelectorAll('[aria-label="Message actions"]').forEach((e) => e.remove())`,
          "sleep:300",
        ],
        clip: 'css=[data-event-id]:has-text("#502 is approved and green")',
        caption: "After It's fine: the line and the underline are gone, for everyone in the room.",
      },
      {
        id: `verifier-settings${t}`,
        route: "/settings/hub",
        theme,
        viewport: "desktop",
        waitFor: "text=Learn from your team",
        actions: ['scroll:css=section:has-text("Checks what agents say")', "sleep:300"],
        clip: 'css=section:has-text("Checks what agents say")',
        caption: "The Verifier section in Hub settings: on or off, the rooms it checks, and Learn.",
      },
      {
        id: `verifier-channel${t}`,
        route: "/room/checkout",
        theme,
        viewport: "desktop",
        waitFor: '[data-verifier-flag="vf3"]',
        actions: show("vf3"),
        caption: "The verifier's lines in the room's chat, among everything else.",
      },
    ];
  }),
];

export const SHOTS: Shot[] = [
  ...BASE,
  // ── The home page's steps, mycelium-io.github.io ─────────────────────────
  // Each shows the part of the app its step is about, cropped so it reads at
  // the size the page shows it. Four are crops of shots above.
  ...(
    [
      // From the role picker down: the role, the handle, its notes, and the
      // machine, agent CLI and folder it starts with.
      ["home-add-agent", "walk-add-agent", { x: 383, y: 284, width: 674, height: 489 }],
      ["home-room", "room-channel", { x: 237, y: 425, width: 863, height: 445 }],
      // Ends before the thread's last message, which carries a verifier line.
      // Starts just inside the pane, past its accent edge and the tab's underline.
      ["home-thread", "walk-thread", { x: 670, y: 68, width: 430, height: 538 }],
      // The @ list and the message under it, short of the channel behind.
      ["home-mention", "mention", { x: 245, y: 647, width: 458, height: 183 }],
    ] as const
  ).map(([id, from, crop]) => {
    const base = BASE.find((s) => s.id === from);
    if (!base) throw new Error(`home shot ${id} crops ${from}, which isn't a shot`);
    return { ...base, id, crop };
  }),
  {
    id: "home-memory",
    route: "/room/checkout",
    theme: "dark",
    viewport: "desktop",
    actions: ["click:text=context >> nth=0", "sleep:500", "click:text=briefing", "sleep:1200"],
    // The memory as it reads, with what it links to: header, text and links.
    crop: { x: 229, y: 68, width: 582, height: 320 },
    caption: "One of the room's memories, rendered, with the memories it links to.",
  },
];
