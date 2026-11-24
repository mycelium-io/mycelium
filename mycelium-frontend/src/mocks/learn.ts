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

import type { UpstreamRef } from "@/lib/board/upstream";
import type { UPSTREAM_CHANGES } from "@/lib/threads";
import { Director, once, sleep, titleOf } from "./director";
import type { MockMemory, MockMessage, RoomFixture } from "./fixtures";

export const LEARN_TAKES = [
  "pair-idea",
  "pair-setup",
  "pair-checkin",
  "side-quest",
  "pairing-work",
  "github",
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
const ep = (short: string): string => `urn:mycelium:episode:${LEARN_ROOM}:${short}`;

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
    wire: [],
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

function cartRoom(): RoomFixture {
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
  fx.messages.push(msg("c0", ALEX, "Joined. Pairing with Sam on carts today.", 32), ...cartOpening());
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

/** Point a row at a pull request in a given state, the way the hub's cache would
 *  answer, and say what changed with the hub's `upstream` notice: the chat
 *  shows it opening, merging or going red, and the rail all of it. */
function setPr(
  d: Director,
  key: string,
  id: string,
  state: UpstreamRef["state"],
  label: string,
  change: (typeof UPSTREAM_CHANGES)[number],
): void {
  const status = d.fx.status;
  if (!status) return;
  const ref = pr(id, state, label, key, 5);
  status.refs = [...status.refs.filter((r) => r.id !== id), ref];
  status.rows[`memory:${key}`] = [ref.ref];
  const r = d.fx.memories.find((m) => m.key === key);
  if (!r) return;
  d.patchRow(key, {}, String(r.updated_by ?? "coder"));
  d.notice({ subkind: "upstream", key, title: titleOf(r), episode: r.episode, change, ref: `#${id.split("#")[1]}`, url: ref.url });
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
  setPr(d, row.key, TAX_PR, "pending", "CI running", "opened");
  d.say(owner, `Opened ${TAX_PR} ("Fixes #118"), and put it on this task so the room follows it.`, thread);
  await sleep(4200);
  d.patchRow(row.key, { ci: "green" }, owner);
  setPr(d, row.key, TAX_PR, "pending", "CI green", "ci_passed");
  await sleep(2000);
  setPr(d, row.key, TAX_PR, "pending", "awaiting review", "review_requested");
  await sleep(3800);
  setPr(d, row.key, TAX_PR, "ok", "approved", "approved");
  await sleep(3200);
  setPr(d, row.key, TAX_PR, "done", "merged", "merged");
  await d.think(owner, thread, 1400);
  d.say(owner, "#616 is merged, and GitHub closed #118 from it. Resolving.", thread);
  d.resolve(row.key, owner);
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
      return cartRoom();
    case "github":
      return githubRoom();
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
}
