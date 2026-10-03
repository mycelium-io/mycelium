// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The Learn scenario: the room each Learn course's videos are filmed in, and a
 * director that plays the agents' side of every take.
 *
 * `MYCELIUM_UI_MOCK_SCENARIO=learn:<take>` adds the `orders` room in the state
 * that take starts from, and Sam's machine with it. A take is one section of a
 * course (`docs/learn/<course>/course.json` names it as the section's `video`),
 * recorded by `mycelium-promo/learn/record.mjs` from the take file of the same
 * name. The other rooms are untouched, so the default fixtures, the committed
 * screenshots and the tests never see any of it.
 *
 * The room is a coffee shop's orders team: gift messages, a flaky checkout
 * test, carts that follow a customer, a receipt that rounds tax the wrong way,
 * a CSV export. Every act plays once per server, and `record.mjs` boots one
 * server per take.
 */

import type { EpisodeSummary } from "@/lib/api";
import type { UpstreamRef } from "@/lib/board/upstream";
import { Director, once, sleep } from "./director";
import type { MockMemory, MockMessage, RoomFixture } from "./fixtures";
import { publish } from "./live";

export const LEARN_TAKES = [
  "pair-idea",
  "pair-setup",
  "pair-checkin",
  "side-quest",
  "pairing-work",
  "pairing-disagree",
  "github",
  "swarm-task",
  "swarm-run",
  "swarm-steer",
  "relay",
] as const;

export type LearnTake = (typeof LEARN_TAKES)[number];

/** The take this server plays, when the scenario is Learn's. */
export function learnTake(): LearnTake | null {
  const m = /^learn:([\w-]+)$/.exec((process.env.MYCELIUM_UI_MOCK_SCENARIO ?? "").toLowerCase());
  return m && (LEARN_TAKES as readonly string[]).includes(m[1]) ? (m[1] as LearnTake) : null;
}

export const isLearnScenario = (): boolean => learnTake() !== null;

export const LEARN_ROOM = "orders";

/** The person every take is recorded as, and their teammate in the pairing course. */
export const LEARN_PERSON = { handle: "sam-rivera", name: "Sam Rivera", home: "/Users/sam" };
export const LEARN_TEAMMATE = { handle: "alex-chen", name: "Alex Chen" };

/** Folders Sam's runner lets agents start in: the checkout, and a worktree for a side quest. */
export const LEARN_ROOTS = [`${LEARN_PERSON.home}/code/shop`, `${LEARN_PERSON.home}/code/shop-flaky-test`];

const SAM = LEARN_PERSON.handle;
const ALEX = LEARN_TEAMMATE.handle;
const BOOT = Date.now();
const ago = (mins: number): string => new Date(BOOT - mins * 60_000).toISOString();
const ep = (short: string): string => `urn:ioc:mycelium:episode:${LEARN_ROOM}:${short}`;

// ── the room's people, agents and threads ─────────────────────────────────────

const manifest = (description: string, extra = "", adapter = "claude_code"): string =>
  `adapter: ${adapter}\ndescription: "${description}"\n${extra}`;

function agent(handle: string, description: string, extra = "", adapter = "claude_code", mins = 60 * 24): MockMemory {
  return {
    key: `agents/${handle}`,
    value: manifest(description, extra, adapter),
    created_by: SAM,
    version: 1,
    updated_at: ago(mins),
  };
}

const engine = (handle: string, kind: string, description: string): MockMemory =>
  agent(handle, description, `kind: ${kind}\n`, "engine");

const PM = agent("pm", "Holds a task to a list of checks and reviews every piece. Doesn't write code.", `owner: ${SAM}\n`);
const CODER = agent("coder", "Writes the shop's code, in ~/code/shop on Sam's machine.", `owner: ${SAM}\n`);

function row(
  key: string,
  title: string,
  meta: Record<string, unknown>,
  by: string,
  mins: number,
  short: string,
  body?: string,
): MockMemory {
  return {
    key,
    value: body ?? title,
    content_text: body ?? title,
    meta,
    created_by: by,
    updated_by: by,
    version: 1,
    updated_at: ago(mins),
    episode: ep(short),
  };
}

const msg = (id: string, who: string, content: string, mins: number, episode: string | null = null): MockMessage => ({
  id,
  sender_handle: who,
  message_type: "broadcast",
  content,
  created_at: ago(mins),
  episode,
});

/** Work the team finished before any take starts, so the board has a history. */
function history(): MockMemory[] {
  return [
    row(
      "work/reorder-button",
      "Add a Reorder button to past orders",
      { kind: "action", status: "resolved", assignment: "resolved", owner: "@coder", pr: "#607", ci: "green" },
      SAM,
      60 * 30,
      "a1b2c3",
    ),
    row(
      "work/delivery-estimate",
      "Show a delivery estimate on the order page",
      { kind: "action", status: "resolved", assignment: "resolved", owner: "@coder", pr: "#609", ci: "green" },
      SAM,
      60 * 22,
      "b2c3d4",
    ),
  ];
}

function baseRoom(): RoomFixture {
  return {
    room: {
      id: 41,
      name: LEARN_ROOM,
      created_at: ago(60 * 24 * 9),
      is_public: true,
      is_persistent: true,
      owner: SAM,
      mas_id: "mas_5d2c8e1f",
    },
    memories: [
      {
        key: "context/goal",
        value: "Make ordering easier for customers who buy coffee as a gift.",
        content_text: "Make ordering easier for customers who buy coffee as a gift.",
        created_by: SAM,
        version: 1,
        updated_at: ago(60 * 24 * 9),
      },
      ...history(),
    ],
    messages: [msg("o1", SAM, "Morning. Gift season starts in three weeks, so gift orders come first.", 60 * 3)],
    episodes: [],
    episodeDetails: {},
    presence: [],
    floors: [],
    l9: [],
  };
}

// ── the pair (course 1) ───────────────────────────────────────────────────────

const GIFT = "work/gift-message";
const GIFT_TITLE = "Add a gift message to orders";
const GIFT_THREAD = ep("9f3a1c");

const KICKOFF = "@pm this is yours. Write the checks first, then hand it to @coder.";
const CHECKS =
  "What done means for this task:\n\n" +
  "1. Checkout takes a gift message, up to 200 characters.\n" +
  "2. It's saved on the order, and shows on the order page and in the email.\n" +
  "3. Orders without one look exactly as they do today.\n" +
  "4. Tests cover 1 to 3, and CI is green.";
const HANDOFF =
  "@coder, start with 1 and 2. When you say a check passes, show me how you know: a test run, a screenshot, the output.";
const CODER_ON_IT = "On it. Starting with the checkout form.";

const PIECE_ONE =
  "1 and 2 are up on `feat/gift-message`. Checkout has a Gift message field (200 characters, counted as you type), " +
  "it's saved on the order, and the order email shows it. `npm test checkout`: 41 passed.";
const PM_SEND_BACK =
  "Check 1 passes: I ran the form test and tried 201 characters, which it refuses.\n\n" +
  "Check 2 doesn't pass yet. The email shows the message, but the order page doesn't: `GET /orders/:id` " +
  "doesn't return it. Send me that response with the message in it.";
const PIECE_ONE_FIXED =
  "Fixed: the order API returns `gift_message`, and the order page shows it under the items. " +
  "Added a test for the API response; here it is with a message in it. CI is green.";
const PM_PASSES = "Checks 1 and 2 pass. I ran the new test and opened an order page with a message on it.\n\n@coder, on to 3 and 4.";

function pairRoom(opts: { withPair: boolean; thread: MockMessage[]; held: boolean; meta?: Record<string, unknown> }): RoomFixture {
  const fx = baseRoom();
  if (opts.withPair) {
    fx.memories.push(PM, CODER);
    fx.presence = [
      { handle: "pm", kind: "lease", last_seen: ago(1), title: GIFT_TITLE },
      { handle: "coder", kind: "lease", last_seen: ago(1), title: GIFT_TITLE },
    ];
  }
  if (opts.held) {
    fx.memories.push(
      row(
        GIFT,
        GIFT_TITLE,
        {
          kind: "action",
          status: "open",
          assignment: "held",
          assignee: "coder",
          owner: "@coder",
          claimed_at: ago(70),
          ttl_minutes: 240,
          priority: "high",
          branch: "feat/gift-message",
          ...(opts.meta ?? {}),
        },
        SAM,
        75,
        "9f3a1c",
      ),
    );
  }
  fx.messages.push(...opts.thread);
  return fx;
}

/** The thread as it stands once the PM has handed out the first piece. */
const threadStart = (mins: number): MockMessage[] => [
  msg("g1", SAM, KICKOFF, mins, GIFT_THREAD),
  msg("g2", "pm", CHECKS, mins - 1, GIFT_THREAD),
  msg("g2b", "pm", HANDOFF, mins - 1, GIFT_THREAD),
  msg("g3", "coder", CODER_ON_IT, mins - 2, GIFT_THREAD),
];

/** An hour and a quarter in, with a question for Sam at the end. */
const threadCheckin = (): MockMessage[] => [
  ...threadStart(76),
  msg("g4", "coder", PIECE_ONE, 58, GIFT_THREAD),
  msg("g5", "pm", PM_SEND_BACK, 56, GIFT_THREAD),
  msg("g6", "coder", PIECE_ONE_FIXED, 47, GIFT_THREAD),
  msg("g7", "pm", PM_PASSES, 45, GIFT_THREAD),
  msg(
    "g8",
    "coder",
    "3 and 4 are done. An order without a message renders the same as before (snapshot test of the order page and " +
      "the email, both unchanged). Opened coffee-shop/web#612; CI is green.",
    24,
    GIFT_THREAD,
  ),
  msg(
    "g9",
    "pm",
    "Checks 3 and 4 pass: I compared the snapshots and CI on #612 is green.\n\n" +
      "One thing I can't decide from the code or the task. @sam-rivera, should the gift message also print on the " +
      "packing slip? The warehouse reads the slip, not the email.",
    21,
    GIFT_THREAD,
  ),
];

/** The pair at work on the first piece: send back, fix, pass. */
async function pairLoop(d: Director): Promise<void> {
  await sleep(1800);
  await d.think("coder", GIFT_THREAD, 3200);
  d.say("coder", PIECE_ONE, GIFT_THREAD);
  await d.think("pm", GIFT_THREAD, 3400);
  d.say("pm", PM_SEND_BACK, GIFT_THREAD);
  await d.think("coder", GIFT_THREAD, 3600);
  d.say("coder", PIECE_ONE_FIXED, GIFT_THREAD);
  d.patchRow(GIFT, { ci: "green" }, "coder");
  await d.think("pm", GIFT_THREAD, 3000);
  d.say("pm", PM_PASSES, GIFT_THREAD);
  await d.think("coder", GIFT_THREAD, 1600);
  d.say("coder", "Starting on 3.", GIFT_THREAD);
}

/** Sam answers the PM's question; the pair finishes and the PM resolves. */
async function pairFinish(d: Director): Promise<void> {
  await d.think("pm", GIFT_THREAD, 2600);
  d.say(
    "pm",
    "Adding check 5: the gift message prints on the packing slip, and a slip without one prints as it does today. " +
      "@coder, over to you.",
    GIFT_THREAD,
  );
  d.patchRow(GIFT, { ci: "running" }, "coder");
  await d.think("coder", GIFT_THREAD, 3600);
  d.say(
    "coder",
    "Done: the packing slip prints the message under the address. A test renders a slip with a message and one " +
      "without; both match the warehouse's sample. Pushed to #612, CI is green.",
    GIFT_THREAD,
  );
  d.patchRow(GIFT, { ci: "green" }, "coder");
  await d.think("pm", GIFT_THREAD, 3200);
  d.say(
    "pm",
    "Check 5 passes: I rendered both slips from the test. **Every check passes.**",
    GIFT_THREAD,
  );
  await d.think("pm", GIFT_THREAD, 1600);
  d.say(
    "pm",
    "Summary: customers can add a gift message at checkout (up to 200 characters). It's saved on the order, shown " +
      "on the order page, in the email and on the packing slip, and orders without one are unchanged. " +
      "coffee-shop/web#612 is ready for your review. Resolving the task.",
    GIFT_THREAD,
  );
  await sleep(700);
  d.resolve(GIFT, "pm");
  d.present("pm");
  d.present("coder");
}

// ── side quests (course 2) ────────────────────────────────────────────────────

const FLAKY_TITLE = "Fix the flaky checkout test";

async function sideQuest(d: Director, row: MockMemory, owner: string): Promise<void> {
  const thread = row.episode;
  if (!thread) return;
  await sleep(1200);
  await d.think(owner, thread, 2200);
  d.claim(row.key, owner);
  d.present(owner, FLAKY_TITLE);
  d.say(
    owner,
    "Taking it. The checkout test fails about one run in ten: it waits a fixed 500ms for the payment mock, and on a " +
      "busy CI runner the mock takes longer.",
    thread,
  );
  // The pair keeps working in its own thread meanwhile.
  await d.think("coder", GIFT_THREAD, 1500);
  d.say("coder", "3 is done: an order without a message renders exactly as before. Snapshot tests attached.", GIFT_THREAD);
  await d.think(owner, thread, 3600);
  d.patchRow(row.key, { branch: "fix/flaky-test", pr: "#615", ci: "green" }, owner);
  d.say(
    owner,
    "Fixed: the test waits for the payment mock to answer instead of sleeping. Ran it 50 times in a row, 50 passes. " +
      "coffee-shop/web#615 changes only the test file. Resolving.",
    thread,
  );
  await sleep(600);
  d.resolve(row.key, owner);
  d.present(owner);
  await d.think("pm", GIFT_THREAD, 1400);
  d.say("pm", "Check 3 passes: I compared the snapshots.", GIFT_THREAD);
}

// ── pairing across teams (course 3) ───────────────────────────────────────────

const CART = "work/cart-across-devices";
const CART_TITLE = "Keep a customer's cart when they switch devices";
const CART_THREAD = ep("4c8d2e");

const cartOpening = (): MockMessage[] => [
  msg(
    "c1",
    ALEX,
    "Customers lose their cart when they move from their phone to their laptop. @web owns the cart screen and @api " +
      "owns the server, so Sam and I are pairing on this one.",
    30,
    CART_THREAD,
  ),
];

const cartArgued = (): MockMessage[] => [
  ...cartOpening(),
  msg("c2", SAM, "@api where does a cart live on the server today?", 26, CART_THREAD),
  msg(
    "c3",
    "api",
    "It doesn't: the cart is only in the browser's local storage. A session lives in Postgres, keyed by the customer's login.",
    25,
    CART_THREAD,
  ),
  msg(
    "c4",
    "web",
    "Then the screen can send the cart up whenever it changes and load it on sign-in. @api, can you give me `PUT /cart` and `GET /cart`?",
    24,
    CART_THREAD,
  ),
  msg("c5", ALEX, "Let's do that. Keep a cart for 30 days.", 22, CART_THREAD),
  msg(
    "c6",
    "web",
    "One thing: the cart changes on every tap. Writing that to Postgres each time is a lot of writes. Put carts in Redis; it's built for this.",
    12,
    CART_THREAD,
  ),
  msg(
    "c7",
    "api",
    "Our Redis isn't durable. A restart would empty every cart, and we just promised 30 days. They belong in Postgres.",
    10,
    CART_THREAD,
  ),
];

function cartRoom(argued: boolean): RoomFixture {
  const fx = baseRoom();
  fx.memories.push(
    agent("web", "Builds the shop's screens. Sam's, in ~/code/shop.", `owner: ${SAM}\nteam: web\n`),
    agent("api", "Owns the shop's server and its database. Alex's, in ~/code/shop-api.", `owner: ${ALEX}\nteam: api\n`),
    row(
      CART,
      CART_TITLE,
      { kind: "action", status: "open", assignment: "unclaimed", priority: "high" },
      ALEX,
      31,
      "4c8d2e",
    ),
  );
  fx.presence = [
    { handle: "web", kind: "lease", last_seen: ago(1) },
    { handle: "api", kind: "lease", last_seen: ago(1) },
    { handle: ALEX, kind: "lease", last_seen: ago(1) },
  ];
  fx.messages.push(msg("c0", ALEX, "Joined. Pairing with Sam on carts today.", 32), ...(argued ? cartArgued() : cartOpening()));
  return fx;
}

async function pairingTalk(d: Director): Promise<void> {
  await d.think("api", CART_THREAD, 2600);
  d.say(
    "api",
    "It doesn't: the cart is only in the browser's local storage. A session lives in Postgres, keyed by the customer's login.",
    CART_THREAD,
  );
  await d.think("web", CART_THREAD, 2600);
  d.say(
    "web",
    "Then the screen can send the cart up whenever it changes and load it on sign-in. @api, can you give me `PUT /cart` and `GET /cart`?",
    CART_THREAD,
  );
  await sleep(1600);
  d.say(ALEX, "Let's do that. Keep a cart for 30 days.", CART_THREAD);
  await d.think("api", CART_THREAD, 2400);
  d.say(
    "api",
    "On it. Here's the shape before I build it:\n\n" +
      "- `PUT /cart` takes the whole cart and returns it with a `version`.\n" +
      "- `GET /cart` returns the signed-in customer's cart, or an empty one.\n\n" +
      "@web, does that work for the screen?",
    CART_THREAD,
  );
  await d.think("web", CART_THREAD, 2000);
  d.say("web", "Yes. I'll send the `version` back so two devices can't overwrite each other.", CART_THREAD);
}

async function negotiate(d: Director, thread: string, a: string, b: string): Promise<void> {
  const tick = (round: number, who: string, action: string, offer: Record<string, string>) =>
    publish(d.room, {
      id: `tick-${round}-${who}-${action}`,
      sender_handle: "aligner",
      message_type: "coordination_tick",
      episode: thread,
      content: JSON.stringify({ payload: { round, participant_id: who, action, current_offer: offer } }),
    });
  const summary: EpisodeSummary = {
    short_id: thread.split(":").pop() ?? thread,
    episode: thread,
    topic: `urn:concept:mycelium:${d.room}`,
    outcome: "open",
    subkind: null,
    participants: [a, b, "aligner"],
    metrics: null,
    assignments: null,
    tasks: [],
    message_count: 0,
    updated_at: new Date().toISOString(),
    updated_by: "aligner",
    within: thread,
  };
  d.fx.episodes.push(summary);
  for (const who of [a, b]) {
    d.join(who, "where carts live", thread);
    await sleep(300);
  }
  await d.think("aligner", thread, 2600);
  d.say(
    "aligner",
    "You agree on the goal: a cart that follows the customer for 30 days. @web is worried about a write on every " +
      "tap, @api about losing carts on a restart. So the issue is where a cart is kept, and how often it's written.",
    thread,
  );
  tick(1, a, "propose", { store: "redis" });
  await sleep(800);
  tick(1, b, "counter", { store: "postgres" });
  await d.think("aligner", thread, 2600);
  const deal = { store: "postgres", writes: "batched, at most one every 5 seconds per cart" };
  d.say(
    "aligner",
    "Proposal: carts live in Postgres, so they survive a restart for 30 days. The server batches a cart's changes " +
      "and writes at most once every 5 seconds, so a burst of taps is one write. @web?",
    thread,
  );
  tick(2, "aligner", "propose", deal);
  await d.think(a, thread, 2000);
  d.say(a, "Works for me. Batching was the whole worry.", thread);
  tick(2, a, "accept", deal);
  await d.think("aligner", thread, 800);
  d.say("aligner", "@api?", thread);
  await d.think(b, thread, 2000);
  d.say(b, "Yes. Durable, and the write load is fine at one every 5 seconds.", thread);
  tick(2, b, "accept", deal);
  await sleep(600);
  const assignments = { "where carts live": "Postgres, for 30 days", writes: "batched, at most one every 5 seconds per cart" };
  Object.assign(summary, {
    outcome: "converged",
    subkind: "converged",
    assignments,
    metrics: { mpc: 1, gar: 0.9, scr: 1, provenance_weight: 1 },
    updated_at: new Date().toISOString(),
  });
  publish(d.room, {
    id: `consensus-${thread}`,
    sender_handle: "backend",
    message_type: "coordination_consensus",
    episode: thread,
    content: JSON.stringify({ plan: "where carts live", assignments, episode: thread, metrics: { gar: 0.9 } }),
  });
  d.say(
    "aligner",
    "✓ Agreed: carts live in Postgres for 30 days, and a cart is written at most once every 5 seconds.",
    thread,
  );
}

// ── GitHub (course 4) ─────────────────────────────────────────────────────────

const TAX_PR = "coffee-shop/web#616";

const pr = (id: string, state: UpstreamRef["state"], label: string, origin: string, age = 60): UpstreamRef => ({
  ref: `github:pull_request:${id}`,
  provider: "github",
  kind: "pull_request",
  id,
  url: `https://github.com/${id.replace("#", "/pull/")}`,
  freshness: "fresh",
  state,
  label,
  age_seconds: age,
  error: null,
  origins: [`memory:${origin}`],
});

function githubRoom(): RoomFixture {
  const fx = pairRoom({
    withPair: true,
    thread: threadCheckin(),
    held: true,
    meta: { pr: "#612", ci: "green" },
  });
  const gift = fx.memories.find((m) => m.key === GIFT);
  if (gift) Object.assign(gift, { value: `${GIFT_TITLE}\n\nPR: coffee-shop/web#612`, content_text: `${GIFT_TITLE}\n\nPR: coffee-shop/web#612` });
  fx.memories.push(
    row(
      "work/delivery-estimate-weekends",
      "Delivery estimate skips weekends",
      { kind: "action", status: "open", assignment: "held", owner: "@coder", claimed_at: ago(40), ttl_minutes: 240, ci: "red" },
      SAM,
      50,
      "c3d4e5",
      "Delivery estimate skips weekends\n\nPR: coffee-shop/web#613",
    ),
    row(
      "work/outlook-spam",
      "Order emails land in spam for some Outlook customers",
      { kind: "action", status: "open", assignment: "unclaimed", priority: "high" },
      "pm",
      35,
      "d4e5f6",
      "Order emails land in spam for some Outlook customers\n\nOur sending domain has no DMARC record. Fixing it needs " +
        "someone with access to DNS, which nobody in this room has.",
    ),
  );
  fx.status = {
    room: LEARN_ROOM,
    field: "upstream",
    providers: ["github"],
    refs: [
      pr("coffee-shop/web#612", "pending", "awaiting review", GIFT),
      pr("coffee-shop/web#613", "failed", "CI failing", "work/delivery-estimate-weekends"),
    ],
    rows: {
      [`memory:${GIFT}`]: ["github:pull_request:coffee-shop/web#612"],
      "memory:work/delivery-estimate-weekends": ["github:pull_request:coffee-shop/web#613"],
    },
    refreshing: false,
  };
  return fx;
}

/** Point a row at a pull request in a given state, the way the hub's cache would answer. */
function setPr(d: Director, key: string, id: string, state: UpstreamRef["state"], label: string): void {
  const status = d.fx.status;
  if (!status) return;
  const ref = pr(id, state, label, key, 5);
  status.refs = [...status.refs.filter((r) => r.id !== id), ref];
  status.rows[`memory:${key}`] = [ref.ref];
  const r = d.fx.memories.find((m) => m.key === key);
  if (r) d.patchRow(key, {}, String(r.updated_by ?? "coder"));
}

async function githubIssue(d: Director, row: MockMemory, owner: string): Promise<void> {
  const thread = row.episode;
  if (!thread) return;
  await sleep(1200);
  await d.think(owner, thread, 2000);
  d.claim(row.key, owner);
  d.say(
    owner,
    "Taking it. Read issue #118: receipts round each line's tax down, then add them up, so a big order can be a few " +
      "cents short. We should add first and round once.",
    thread,
  );
  await d.think(owner, thread, 3200);
  const title = String(row.value).split("\n")[0];
  d.setMemory(row.key, `${title}\n\nPR: ${TAX_PR}`, owner);
  d.patchRow(row.key, { branch: "fix/receipt-tax", pr: "#616", ci: "running" }, owner);
  setPr(d, row.key, TAX_PR, "pending", "CI running");
  d.say(owner, `Opened ${TAX_PR} ("Fixes #118"), and put it on this task so the board follows it.`, thread);
  await sleep(4200);
  d.patchRow(row.key, { ci: "green" }, owner);
  setPr(d, row.key, TAX_PR, "pending", "awaiting review");
  await sleep(3800);
  setPr(d, row.key, TAX_PR, "ok", "approved");
  await sleep(3200);
  setPr(d, row.key, TAX_PR, "done", "merged");
  await d.think(owner, thread, 1400);
  d.say(owner, "#616 is merged, and GitHub closed #118 from it. Resolving.", thread);
  d.resolve(row.key, owner);
}

// ── swarming (course 5) ───────────────────────────────────────────────────────

const EXPORT = "work/csv-export";
const EXPORT_TITLE = "Add CSV export for orders";
const EXPORT_THREAD = ep("7e1f5a");
export const EXPORT_TASK =
  "Add CSV export for orders. Parts: an /api/orders/export endpoint that streams CSV; an Export button on the " +
  "Orders page; tests for both, including an empty list and 10,000 rows. Done when: a person can download this " +
  "month's orders from the Orders page, and the tests pass in CI. Don't change the existing orders API.";
const TEAM = ["agent-1", "agent-2", "agent-3"];
const PARTS = [
  { key: "work/csv-export-endpoint", title: "Export endpoint that streams orders as CSV", who: "agent-1", short: "8a1b2c" },
  { key: "work/csv-export-button", title: "Export button on the Orders page", who: "agent-2", short: "8b2c3d" },
  { key: "work/csv-export-tests", title: "Tests: empty list and 10,000 rows", who: "agent-3", short: "8c3d4e" },
];
const SWARM_STEPS = [
  { id: "check-in", to: "each", next: "split", prompt: "Check in: say which part you would take." },
  { id: "split", to: "lead", next: "done", prompt: "Split the work into child tasks, one per member." },
  { id: "done", end: "resolved" },
];

function swarmMembers(fx: RoomFixture): void {
  fx.memories.push(
    engine("conductor", "conductor", "Walks a flow inside a task's thread."),
    ...TEAM.map((h) => agent(h, "A worker on the hub, in its own worktree of coffee-shop/web.", "kind: worker\n", "engine", 30)),
  );
  fx.presence = TEAM.map((h) => ({ handle: h, kind: "lease" as const, last_seen: ago(1) }));
}

/** The task as the board shows it: its first sentence as the title, the rest as its body. */
const EXPORT_BODY = `${EXPORT_TITLE}\n\n${EXPORT_TASK.slice(EXPORT_TITLE.length + 2)}`;

function swarmRow(): MockMemory {
  return row(EXPORT, EXPORT_TITLE, { kind: "action", status: "open", assignment: "unclaimed", priority: "high" }, SAM, 6, "7e1f5a", EXPORT_BODY);
}

const CHECKINS: Record<string, string> = {
  "agent-1":
    "I'll take the endpoint: `GET /api/orders/export` streaming CSV, month by default, without touching the orders " +
    "API. I need the column list agreed with whoever builds the button.",
  "agent-2":
    "I'll take the Export button on the Orders page. @agent-1, columns: order number, date, customer, items, total. " +
    "I'll assume a download of the month on screen.",
  "agent-3":
    "I'll take the tests: an empty month, 10,000 rows streamed without loading them all, and the button's download. " +
    "I'll write them against the columns above.",
};

const SPLIT =
  "Split into three parts, one each:\n\n" +
  "- **Export endpoint that streams orders as CSV**: @agent-1\n" +
  "- **Export button on the Orders page**: @agent-2\n" +
  "- **Tests: empty list and 10,000 rows**: @agent-3\n\n" +
  "Each of you reviews the next one's part: 1 reviews 2, 2 reviews 3, 3 reviews 1.";

function conductorOpen(d: Director): void {
  d.say("conductor", `Running swarm in this task: @${TEAM[0]} leads, with ${TEAM.slice(1).map((h) => `@${h}`).join(", ")}.`, EXPORT_THREAD, {
    event: "open",
    protocol: "swarm",
    description: "A team kicks off a task: each member checks in, then the lead splits the work.",
    roles: { lead: TEAM[0] },
    members: TEAM,
    steps: SWARM_STEPS,
  });
}

/** The kickoff: everyone checks in, then the lead splits the task into parts. */
async function swarmKickoff(d: Director, opts: { checkInsOnly?: boolean } = {}): Promise<void> {
  let turn = 0;
  for (const who of TEAM) {
    turn += 1;
    d.say("conductor", `swarm · check-in · turn ${turn} of 4 · ${who}`, EXPORT_THREAD, {
      event: "turn",
      protocol: "swarm",
      step: "check-in",
      to: who,
      turn,
      cap: 4,
    });
    await d.think(who, EXPORT_THREAD, 2600);
    d.say(who, CHECKINS[who], EXPORT_THREAD);
    await sleep(500);
  }
  if (opts.checkInsOnly) return;
  d.say("conductor", "check-in → split", EXPORT_THREAD, { event: "edge", step: "check-in", who: "each", stance: null, next: "split" });
  d.say("conductor", `swarm · split · turn 4 of 4 · ${TEAM[0]}`, EXPORT_THREAD, {
    event: "turn",
    protocol: "swarm",
    step: "split",
    to: TEAM[0],
    turn: 4,
    cap: 4,
  });
  await d.think(TEAM[0], EXPORT_THREAD, 2600);
  d.claim(EXPORT, TEAM[0]);
  for (const p of PARTS) {
    d.fileRow(p.key, p.title, { kind: "action", status: "open", assignee: p.who, "part-of": EXPORT }, TEAM[0], p.short);
    await sleep(500);
  }
  d.say(TEAM[0], SPLIT, EXPORT_THREAD);
  d.say("conductor", "✓ swarm done: the work is split.", EXPORT_THREAD, {
    event: "close",
    protocol: "swarm",
    outcome: "resolved",
    steps: 2,
    reason: "reached `done`",
  });
  for (const p of PARTS) {
    await sleep(700);
    d.claim(p.key, p.who);
    d.present(p.who, p.title);
  }
  // The parts get going, each in its own thread.
  const [endpoint, button] = PARTS;
  await d.think(endpoint.who, d.ep(endpoint.short), 2200);
  d.say(
    endpoint.who,
    "Endpoint is up on `swarm/agent-1`: it streams rows as it reads them, so 10,000 orders never sit in memory. @agent-2, can you review it?",
    d.ep(endpoint.short),
  );
  await d.think(button.who, d.ep(endpoint.short), 2400);
  d.say(
    button.who,
    "Reviewed. Streams fine, but a customer name with a comma breaks the row. Quote the fields, then I'll look again.",
    d.ep(endpoint.short),
  );
}

function swarmRoom(stage: "before" | "kicked-off" | "split"): RoomFixture {
  const fx = baseRoom();
  if (stage === "before") return fx;
  swarmMembers(fx);
  fx.memories.push(swarmRow());
  fx.messages.push(msg("s0", SAM, `@conductor swarm @${TEAM.join(" @")}: ${EXPORT_TITLE}`, 6, EXPORT_THREAD));
  if (stage === "kicked-off") return fx;
  // Split, and an hour in: one part done, one under review, one stalled on a question.
  const exportRow = fx.memories.find((m) => m.key === EXPORT);
  if (exportRow) exportRow.meta = { ...exportRow.meta, assignment: "held", owner: "@agent-1", claimed_at: ago(60), ttl_minutes: 240 };
  fx.messages.push(
    ...TEAM.map((h, i) => msg(`s${i + 1}`, h, CHECKINS[h], 64 - i, EXPORT_THREAD)),
    msg("s4", TEAM[0], SPLIT, 60, EXPORT_THREAD),
  );
  const [endpoint, button, tests] = PARTS;
  fx.memories.push(
    row(endpoint.key, endpoint.title, { kind: "action", status: "resolved", assignment: "resolved", owner: "@agent-1", "part-of": EXPORT, branch: "swarm/agent-1" }, TEAM[0], 59, endpoint.short),
    row(button.key, button.title, { kind: "action", status: "open", assignment: "held", owner: "@agent-2", claimed_at: ago(58), ttl_minutes: 240, "part-of": EXPORT, branch: "swarm/agent-2" }, TEAM[0], 59, button.short),
    row(tests.key, tests.title, { kind: "action", status: "in_review", assignment: "held", owner: "@agent-3", claimed_at: ago(58), ttl_minutes: 240, "part-of": EXPORT, branch: "swarm/agent-3" }, TEAM[0], 59, tests.short),
  );
  fx.messages.push(
    msg("p1", endpoint.who, "Endpoint is up on `swarm/agent-1`, streaming. @agent-2, can you review it?", 50, ep(endpoint.short)),
    msg("p2", button.who, "Reviewed. A customer name with a comma breaks the row. Quote the fields.", 47, ep(endpoint.short)),
    msg("p3", endpoint.who, "Quoted, with a test for a comma and a quote in a name.", 40, ep(endpoint.short)),
    msg("p4", button.who, "Ran it: both cases come out right. Approved.", 38, ep(endpoint.short)),
    msg(
      "p5",
      button.who,
      "The button is in, next to Filter. Before I wire it up: should the export use the filters on screen (say, " +
        "only gift orders), or always the whole month? The task doesn't say. @sam-rivera?",
      44,
      ep(button.short),
    ),
    msg("p6", tests.who, "Tests are up on `swarm/agent-3`: empty month, 10,000 rows, and the download. @agent-1, review?", 20, ep(tests.short)),
    msg("p7", endpoint.who, "Looking at them now.", 18, ep(tests.short)),
  );
  return fx;
}


async function swarmFinish(d: Director): Promise<void> {
  const [, button, tests] = PARTS;
  const bt = d.ep(button.short);
  await d.think(button.who, bt, 2400);
  d.say(button.who, "Thanks. Using the filters on screen, so the file is what you're looking at. Wiring it up now.", bt);
  await d.think(button.who, bt, 3000);
  d.say(
    button.who,
    "Done on `swarm/agent-2`: Export downloads `orders-2026-10.csv` with the current filters, and is disabled while " +
      "an export is running. @agent-3, can you review?",
    bt,
  );
  await d.think(tests.who, bt, 2800);
  d.say(tests.who, "Filtered to gift orders and exported: 212 rows, all gifts. The empty month gives a header only. Approved.", bt);
  d.resolve(button.key, tests.who);
  await d.think(TEAM[0], d.ep(tests.short), 1200);
  d.say(TEAM[0], "Ran the suite on a clean checkout: all green, the 10,000-row test in 1.8s. Approved.", d.ep(tests.short));
  d.resolve(tests.key, TEAM[0]);
  d.present(button.who);
  d.present(tests.who);
  await d.think(TEAM[0], EXPORT_THREAD, 1600);
  d.say(
    TEAM[0],
    "**All three parts are done**, and merged into `swarm/agent-1`:\n\n" +
      "- `GET /api/orders/export` streams the month as CSV, with quoted fields. The orders API is unchanged.\n" +
      "- Export on the Orders page downloads what's on screen, filters included.\n" +
      "- Tests cover an empty month, 10,000 rows and the download; CI is green.\n\n" +
      "One call was made on the way: the export follows the filters on screen (Sam's answer, in the button's thread). " +
      "Resolving.",
    EXPORT_THREAD,
  );
  d.resolve(EXPORT, TEAM[0]);
  d.present(TEAM[0]);
}

// ── agents triggering agents (course 5, last section) ─────────────────────────

const TESTER = agent("tester", "Tests the shop end to end, on Sam's machine.", `owner: ${SAM}\n`);
const WRITER = agent("writer", "Writes the shop's help pages, on Sam's machine.", `owner: ${SAM}\n`);

const SHIP = "work/ship-gift-cards";
const STEPS = {
  api: { key: "work/gift-cards-api", title: "Gift card API: issue, redeem, balance", who: "coder", short: "5a1b2c" },
  checkout: { key: "work/gift-cards-checkout", title: "Pay with a gift card at checkout", who: "coder", short: "5b2c3d" },
  tests: { key: "work/gift-cards-tests", title: "Test gift cards end to end", who: "tester", short: "5c3d4e" },
  help: { key: "work/gift-cards-help", title: "Help page: how gift cards work", who: "writer", short: "5d4e5f" },
};
const EXPIRY = { key: "decisions/gift-card-expiry", title: "Do gift cards expire?", short: "5e5f6a" };
const SPLIT_BUG = { key: "work/gift-cards-split-negative", title: "A split payment can leave a negative balance", short: "5f6a7b" };

function relayRoom(): RoomFixture {
  const fx = baseRoom();
  fx.memories.push(PM, CODER, TESTER, WRITER);
  fx.presence = ["pm", "coder", "tester", "writer"].map((h) => ({ handle: h, kind: "lease" as const, last_seen: ago(1) }));
  return fx;
}

/** Sam's answer to the one decision the run needs from a person. */
const g = globalThis as typeof globalThis & { __myceliumLearnAnswer?: { promise: Promise<void>; resolve: () => void } };
function answered(): { promise: Promise<void>; resolve: () => void } {
  if (!g.__myceliumLearnAnswer) {
    let resolve = () => {};
    const promise = new Promise<void>((r) => {
      resolve = r;
    });
    g.__myceliumLearnAnswer = { promise, resolve };
  }
  return g.__myceliumLearnAnswer;
}

/** A row its agent was waiting on is done: the dependents hear about it. */
function unblock(d: Director, ...steps: { key: string; title: string; short: string }[]): void {
  for (const s of steps) d.notice({ subkind: "unblocked", key: s.key, title: s.title, episode: d.ep(s.short), by: "pm" });
}

/** One task to the PM; from there the agents hand the work to each other. */
async function relay(d: Director, parent: MockMemory): Promise<void> {
  const top = parent.episode ?? null;
  const { api, checkout, tests, help } = STEPS;
  await sleep(1200);
  await d.think("pm", top, 2400);
  d.claim(parent.key, "pm");
  d.present("pm", "Ship gift cards");
  d.say(
    "pm",
    "Taking it. Four tasks, in the order they can happen, each for the agent who'll do it: the API first, then " +
      "checkout and the help page, then the tests. Each one starts when the one it waits on is done.",
    top,
  );
  const file = (s: { key: string; title: string; who: string; short: string }, after?: string) => {
    d.fileRow(
      s.key,
      s.title,
      { kind: "action", status: "open", assignee: s.who, "part-of": SHIP, ...(after ? { "depends-on": after } : {}) },
      "pm",
      s.short,
    );
    // Each agent is woken by the row filed for it, and takes it at once.
    d.claim(s.key, s.who);
  };
  await sleep(900);
  file(api);
  await sleep(700);
  file(checkout, api.key);
  await sleep(700);
  file(help, api.key);
  await sleep(700);
  file(tests, checkout.key);
  await sleep(1200);
  d.fileRow(EXPIRY.key, EXPIRY.title, { kind: "decision", status: "open", priority: "high", "part-of": SHIP }, "pm", EXPIRY.short);
  d.say("pm", "One thing only you can decide, so I filed it: do gift cards expire? Everything else goes ahead meanwhile.", top);
  d.present("coder", api.title);

  await d.think("coder", d.ep(api.short), 4200);
  d.say(
    "coder",
    "Done: `POST /gift-cards` issues one, `/redeem` takes from its balance, `GET` shows what's left. Tests pass.",
    d.ep(api.short),
  );
  d.resolve(api.key, "coder");
  unblock(d, checkout, help);
  await sleep(600);
  d.present("coder", checkout.title);
  d.present("writer", help.title);
  // Resolving a row wakes nobody by itself: the agent who finished says so to whoever is next.
  d.say("coder", "The API is in, so the help page can start. @writer, it's yours. I'm on checkout.", d.ep(help.short));
  await d.think("writer", d.ep(help.short), 2000);
  d.say("writer", "On it. Writing the page from the API's endpoints.", d.ep(help.short));

  await answered().promise;
  const decision = d.ep(EXPIRY.short);
  await d.think("pm", decision, 1800);
  d.say("pm", "Never expire, then. Telling @writer for the help page.", decision);
  d.resolve(EXPIRY.key, "pm", { decision: "gift cards never expire" });
  d.say("pm", "@writer gift cards never expire. Say so on the page.", d.ep(help.short));
  await d.think("writer", d.ep(help.short), 3000);
  d.say("writer", "Added a line on it. The page covers buying, redeeming and checking a balance. Done.", d.ep(help.short));
  d.resolve(help.key, "writer");
  d.present("writer");

  await d.think("coder", d.ep(checkout.short), 3200);
  d.say("coder", "Checkout takes a gift card, and puts whatever it doesn't cover on a card. Done.", d.ep(checkout.short));
  d.resolve(checkout.key, "coder");
  unblock(d, tests);
  d.say("coder", "Checkout is in. @tester, over to you.", d.ep(tests.short));
  d.present("tester", tests.title);
  d.present("coder");
  await d.think("tester", d.ep(tests.short), 3000);
  d.say(
    "tester",
    "Found one: a $40 order paid with a $30 card and a declined card leaves the gift card at -$10. Filing it for @coder.",
    d.ep(tests.short),
  );
  d.fileRow(
    SPLIT_BUG.key,
    SPLIT_BUG.title,
    { kind: "action", status: "open", assignee: "coder", priority: "high", "part-of": SHIP },
    "tester",
    SPLIT_BUG.short,
  );
  d.claim(SPLIT_BUG.key, "coder");
  d.present("coder", SPLIT_BUG.title);
  await d.think("coder", d.ep(SPLIT_BUG.short), 3400);
  d.say(
    "coder",
    "Fixed: the gift card is only charged once the rest of the payment goes through. Added a test for it.",
    d.ep(SPLIT_BUG.short),
  );
  d.resolve(SPLIT_BUG.key, "coder");
  d.present("coder");
  await d.think("tester", d.ep(tests.short), 2800);
  d.say("tester", "Re-ran it all: issue, redeem, split payment, declined card, refund. Everything passes.", d.ep(tests.short));
  d.resolve(tests.key, "tester");
  d.say("tester", "@pm the last part is done and tested.", top);
  d.present("tester");

  await d.think("pm", top, 2600);
  d.say(
    "pm",
    "**Gift cards are done.** The API, checkout and the help page are in, and the tests pass, including a " +
      "split-payment bug the tester found and the coder fixed. Gift cards never expire, as you decided. " +
      "Ready for your review: coffee-shop/web#618.",
    top,
  );
  d.resolve(parent.key, "pm");
  d.present("pm");
}

// ── the scenario ──────────────────────────────────────────────────────────────

/** The `orders` room as the current take starts it, or null outside Learn. */
export function learnRoom(): RoomFixture | null {
  switch (learnTake()) {
    case "pair-setup":
      return pairRoom({ withPair: false, thread: [], held: false });
    case "pair-idea":
      return pairRoom({ withPair: true, thread: threadStart(9), held: true });
    case "pair-checkin":
      return pairRoom({ withPair: true, thread: threadCheckin(), held: true, meta: { pr: "#612", ci: "green" } });
    case "side-quest":
      return pairRoom({ withPair: true, thread: [...threadStart(40), msg("g4", "pm", PM_PASSES, 12, GIFT_THREAD)], held: true });
    case "pairing-work":
      return cartRoom(false);
    case "pairing-disagree":
      return cartRoom(true);
    case "github":
      return githubRoom();
    case "swarm-task":
      return swarmRoom("before");
    case "swarm-run":
      return swarmRoom("kicked-off");
    case "swarm-steer":
      return swarmRoom("split");
    case "relay":
      return relayRoom();
    default:
      return null;
  }
}

/** How much longer than the demo an agent takes to answer: a lesson is read, not glanced at. */
const PACE = 1.9;

const directorOf = (fx: RoomFixture): Director => new Director(LEARN_ROOM, fx, PACE);

/** What an agent says when it starts and has read its notes. */
const HELLO: Record<string, string> = {
  pm: "Read my notes. I'm the PM: give me a task and I'll write what done means before anyone starts, then hold the work to it. I don't write code.",
  coder: "I'm in ~/code/shop, on main. Waiting for @pm to hand me something.",
  fixer: "I'm in ~/code/shop-flaky-test, on branch fix/flaky-test, so I won't touch the pair's checkout. What should I look at?",
};

/** An agent started from Sam's machine joins and says hello. */
export function learnOnLaunch(fx: RoomFixture, room: string, handle: string, cwd: string | null): void {
  if (room !== LEARN_ROOM || !once(`learn:launch:${handle}`)) return;
  const d = directorOf(fx);
  void (async () => {
    // The dialog shows the machine asking first; the agent joins once it's running.
    await sleep(5200);
    if (!fx.memories.some((m) => m.key === `agents/${handle}`)) {
      fx.memories.push(agent(handle, `On Sam's machine, in ${cwd ?? "~/code/shop"}.`, `owner: ${SAM}\n`, "claude_code", 0));
    }
    d.present(handle);
    d.join(handle, "joined from Sam's machine");
    await d.think(handle, null, 1800);
    d.say(handle, HELLO[handle] ?? `I'm in ${cwd ?? "~/code/shop"}. Hand me something.`);
  })();
}

/** A task filed for an agent. */
export function learnOnTask(fx: RoomFixture, room: string, row: MockMemory): void {
  if (room !== LEARN_ROOM) return;
  const owner = String(row.meta?.assignee ?? "").replace(/^@/, "");
  if (!owner || !row.episode || !once(`learn:task:${row.key}`)) return;
  const d = directorOf(fx);
  const take = learnTake();
  if (take === "pair-setup" && owner === "coder") {
    void (async () => {
      await sleep(1400);
      await d.think("coder", row.episode ?? null, 1600);
      d.claim(row.key, "coder");
      d.say("coder", "Claimed. I'll wait for @pm's checks before I write anything.", row.episode ?? null);
    })();
  } else if (take === "side-quest") void sideQuest(d, row, owner);
  else if (take === "github") void githubIssue(d, row, owner);
  else if (take === "relay" && owner === "pm") void relay(d, row);
}

/** A message someone posted: the beat it starts, if any. */
export function learnOnMessage(fx: RoomFixture, room: string, m: MockMessage): void {
  if (room !== LEARN_ROOM || m.sender_handle !== SAM) return;
  const d = directorOf(fx);
  const text = m.content.trim();
  const thread = m.episode && m.episode !== d.live ? m.episode : null;
  switch (learnTake()) {
    case "pair-setup":
      if (thread && /@pm\b/.test(text) && once("learn:kickoff")) {
        void (async () => {
          await d.think("pm", thread, 2800);
          d.say("pm", CHECKS, thread);
          d.present("pm", GIFT_TITLE);
          await d.think("pm", thread, 1200);
          d.say("pm", HANDOFF, thread);
          await d.think("coder", thread, 1800);
          d.say("coder", CODER_ON_IT, thread);
          d.present("coder", GIFT_TITLE);
        })();
      }
      break;
    case "pair-checkin":
      if (thread === GIFT_THREAD && once("learn:answer")) void pairFinish(d);
      break;
    case "pairing-work":
      if (thread === CART_THREAD && /@api\b/.test(text) && once("learn:ask-api")) void pairingTalk(d);
      break;
    case "pairing-disagree":
      if (thread === CART_THREAD && /@aligner\b/.test(text) && once("learn:aligner")) void negotiate(d, thread, "web", "api");
      break;
    case "swarm-steer":
      if (thread === d.ep(PARTS[1].short) && once("learn:steer")) void swarmFinish(d);
      break;
    case "relay":
      if (thread === d.ep(EXPIRY.short)) answered().resolve();
      break;
    default:
      break;
  }
}

/** A thread opened in the app: the takes that open on a thread already in motion start here. */
export function learnOnThreadRead(fx: RoomFixture, room: string, episode: string): void {
  if (room !== LEARN_ROOM) return;
  const d = directorOf(fx);
  const take = learnTake();
  if (take === "pair-idea" && episode === GIFT_THREAD && once("learn:loop")) void pairLoop(d);
  if (take === "swarm-run" && episode === EXPORT_THREAD && once("learn:swarm-run")) {
    void (async () => {
      await sleep(1200);
      conductorOpen(d);
      await sleep(900);
      await swarmKickoff(d);
    })();
  }
}

/** A swarm started from the app: the team is registered, the task filed and the kickoff begins. */
export function learnOnSwarm(fx: RoomFixture, room: string): { key: string; episode: string; members: string[] } | null {
  if (room !== LEARN_ROOM || learnTake() !== "swarm-task") return null;
  const d = directorOf(fx);
  if (once("learn:swarm")) {
    swarmMembers(fx);
    const r = swarmRow();
    r.updated_at = new Date().toISOString();
    fx.memories.push(r);
    publish(room, { type: "memory_changed", message_type: "memory_changed", key: EXPORT, version: 1, updated_by: SAM });
    d.notice({ subkind: "filed", key: EXPORT, title: EXPORT_TITLE, episode: EXPORT_THREAD, by: SAM, kind: "action" });
    void (async () => {
      await sleep(600);
      d.say(SAM, `@conductor swarm @${TEAM.join(" @")}: ${EXPORT_TITLE}`, EXPORT_THREAD);
      await sleep(1400);
      conductorOpen(d);
      await sleep(900);
      await swarmKickoff(d, { checkInsOnly: true });
    })();
  }
  return { key: EXPORT, episode: EXPORT_THREAD, members: TEAM };
}
