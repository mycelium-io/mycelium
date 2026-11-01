// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The demo scenario: the checkout room *before* the double-charge story, and a
 * director that plays the agents' side of it when a person does their part.
 *
 * `MYCELIUM_UI_MOCK_SCENARIO=demo` swaps this room in for the default
 * `checkout` (the other rooms are untouched), so the default fixtures, the
 * committed screenshots and the tests never see it. It exists for the product
 * demo recorded under `mycelium-promo/`, which drives the real UI through it:
 *
 *   1. you name yourself, and add @builder from your machine;
 *   2. you welcome it by name in the channel, and it answers;
 *   3. you add a task on the board for @builder, and it takes it;
 *   4. in the task's thread @builder asks @reviewer to check the fix, and the
 *      two go back and forth by mentioning each other;
 *   5. @builder uploads a recording of the fix, @reviewer approves it, and you
 *      tell @builder to ship it;
 *   6. later (`POST /api/demo/busy`, behind the take's fade): the room has
 *      grown to a team, and its threads move at once, for the channel, the
 *      Stream and the board.
 *
 * Times are real (relative to when the dev server booted), so the board reads
 * "2h", not the default fixtures' fixed clock. Each act runs once per boot.
 */

import type { PresenceMember } from "@/lib/api";
import type { MockMemory, MockMessage, RoomFixture } from "./fixtures";
import { Director, once, sleep } from "./director";
import { liveEpisode, memoryChangedFrame, publish, respondingFrame } from "./live";
import { addUpload } from "./uploads";

export function isDemoScenario(): boolean {
  return (process.env.MYCELIUM_UI_MOCK_SCENARIO ?? "").toLowerCase() === "demo";
}

const ROOM = "checkout";
const BOOT = Date.now();
const ago = (mins: number): string => new Date(BOOT - mins * 60_000).toISOString();
const now = (): string => new Date().toISOString();
const ep = (short: string): string => `urn:ioc:mycelium:episode:${ROOM}:${short}`;
const LIVE = liveEpisode(ROOM);

/** The person the demo is recorded as; the machine's runner is theirs. */
export const DEMO_PERSON = { handle: "sam-rivera", name: "Sam Rivera", home: "/Users/sam" };

/** The recording @builder uploads: `mycelium-promo/record.mjs` makes it and names it here. */
const CLIP = "double-tap-one-charge.mp4";

const manifest = (description: string, adapter = "claude_code", extra = ""): string =>
  `adapter: ${adapter}\ndescription: "${description}"\n${extra}`;

// ── the room as it stands before the story ────────────────────────────────────

function boardRow(
  key: string,
  title: string,
  meta: Record<string, unknown>,
  by: string,
  mins: number,
  short: string,
): MockMemory {
  return {
    key,
    value: title,
    content_text: title,
    meta,
    created_by: by,
    updated_by: by,
    version: 1,
    updated_at: ago(mins),
    episode: ep(short),
  };
}

export function demoCheckout(): RoomFixture {
  const memories: MockMemory[] = [
    {
      key: "agents/reviewer",
      value: manifest("Reviews checkout changes and places test orders on real phones."),
      created_by: "operator",
      version: 1,
      updated_at: ago(60 * 26),
      episode: ep("b3d5f7"),
    },
    {
      key: "context/goal",
      value: "Make checkout faster and stop double charges before the spring sale.",
      content_text: "Make checkout faster and stop double charges before the spring sale.",
      created_by: "operator",
      version: 1,
      updated_at: ago(60 * 25),
      episode: ep("f7b9d1"),
    },
    {
      key: "status/this-week",
      value: "Stripe payments are live. Apple Pay is in review; test orders on real phones thursday.",
      content_text: "Stripe payments are live. Apple Pay is in review; test orders on real phones thursday.",
      created_by: "reviewer",
      version: 2,
      updated_at: ago(95),
      episode: ep("a8c0e2"),
    },
    boardRow(
      "work/stripe-payments",
      "Move card payments to Stripe",
      { kind: "action", status: "resolved", assignment: "resolved", owner: "@reviewer", priority: "urgent", ci: "green", pr: "#499" },
      "operator",
      60 * 20,
      "e1a3c5",
    ),
    boardRow(
      "work/add-apple-pay",
      "Add Apple Pay to checkout",
      {
        kind: "action",
        status: "open",
        assignment: "held",
        owner: "@reviewer",
        claimed_at: ago(12),
        ttl_minutes: 240,
        priority: "high",
        branch: "feat/apple-pay",
        ci: "green",
        pr: "#502",
      },
      "operator",
      12,
      "d6f8b0",
    ),
    boardRow(
      "work/payment-alerts",
      "Alert us when payments start failing",
      { kind: "action", status: "open", assignment: "unclaimed", branch: "feat/payment-alerts", ci: "running" },
      "operator",
      60 * 3,
      "f2b4d6",
    ),
    boardRow(
      "work/turn-on-apple-pay",
      "Turn on Apple Pay for everyone",
      { kind: "action", status: "open", assignment: "unclaimed", priority: "high", "depends-on": "work/add-apple-pay" },
      "operator",
      60 * 2,
      "a3c5e7",
    ),
  ];

  const messages: MockMessage[] = [
    {
      id: "d1",
      sender_handle: "operator",
      message_type: "broadcast",
      content: "Morning! Spring sale is in two weeks. Apple Pay first, then whatever is still making checkout flaky.",
      created_at: ago(60 * 3 + 5),
      episode: null,
    },
    {
      id: "d2",
      sender_handle: "reviewer",
      message_type: "broadcast",
      content: "Apple Pay is up for review on #502. I'll place test orders on real phones thursday.",
      created_at: ago(14),
      episode: null,
    },
    {
      id: "d3",
      sender_handle: "operator",
      message_type: "broadcast",
      content: "Two customers wrote in this morning: they were charged twice when they double-clicked Pay. Both on phones, both on a slow connection.",
      created_at: ago(6),
      episode: null,
    },
  ];

  const presence: PresenceMember[] = [{ handle: "reviewer", kind: "lease", last_seen: ago(1), title: "Add Apple Pay to checkout" }];

  return {
    room: {
      id: 1,
      name: ROOM,
      created_at: ago(60 * 26),
      is_public: true,
      is_persistent: true,
      mas_id: "mas_7c1e9a2b",
    },
    memories,
    messages,
    episodes: [],
    episodeDetails: {},
    presence,
    floors: [],
    wire: [],
  };
}

// ── the director ──────────────────────────────────────────────────────────────

// The writes an agent's side makes, through the shared director (director.ts),
// bound to the demo's room.
const on = (fx: RoomFixture): Director => new Director(ROOM, fx);
const say = (fx: RoomFixture, who: string, content: string, episode: string | null = null) => on(fx).say(who, content, episode);
const join = (fx: RoomFixture, handle: string, intent: string, episode: string) => on(fx).join(handle, intent, episode);
const patchRow = (fx: RoomFixture, key: string, meta: Record<string, unknown>, by: string) => on(fx).patchRow(key, meta, by);
const claim = (fx: RoomFixture, key: string, who: string) => on(fx).claim(key, who);
const resolveRow = (fx: RoomFixture, key: string, who: string, extra: Record<string, unknown> = {}) => on(fx).resolve(key, who, extra);
const setPresence = (fx: RoomFixture, handle: string, title?: string) => on(fx).present(handle, title);
const rowOf = (fx: RoomFixture, episode: string | null | undefined) => on(fx).rowOf(episode);

/** An agent visibly thinking, then the beat it takes. */
async function think(who: string, episode: string | null, ms: number): Promise<void> {
  publish(ROOM, respondingFrame(who, episode));
  await sleep(ms);
}

const isAgent = (fx: RoomFixture, handle: string) => fx.memories.some((m) => m.key === `agents/${handle}`);

/** The handles a message mentions out loud (`@x` or `@!x`, not a silent `@~x`). */
const mentioned = (text: string): string[] =>
  [...text.matchAll(/(?:^|[^\w@])@!?([a-z0-9][\w.-]*)/gi)].map((m) => m[1].toLowerCase());

// Act 1 — an agent added from your machine joins the room.
export function demoOnLaunch(fx: RoomFixture, room: string, handle: string): void {
  if (room !== ROOM || !once(`launch:${handle}`)) return;
  void (async () => {
    // The runner reports the start after a couple of seconds; the agent is a
    // member from then on.
    await sleep(2600);
    if (!isAgent(fx, handle)) {
      fx.memories.push({
        key: `agents/${handle}`,
        value: manifest("Writes the checkout code, on Sam's machine in ~/code/shop.", "claude_code", `owner: ${DEMO_PERSON.handle}\n`),
        created_by: DEMO_PERSON.handle,
        version: 1,
        updated_at: now(),
        episode: ep("a2c4e6"),
      });
    }
    setPresence(fx, handle);
    publish(ROOM, memoryChangedFrame(`agents/${handle}`, 1, DEMO_PERSON.handle));
    join(fx, handle, "joined from Sam's machine", LIVE);
  })();
}

// Act 2 — welcomed by name in the channel, the new agent answers.
function welcome(fx: RoomFixture, handle: string): void {
  if (!once(`welcome:${handle}`)) return;
  void (async () => {
    await think(handle, null, 2000);
    say(
      fx,
      handle,
      "Thanks! I'm on Sam's machine in ~/code/shop, with the checkout repo open. Put something on the board for me and I'll pick it up.",
    );
  })();
}

// Act 3 — a task added on the board for an agent: it takes it, and works it in
// the task's thread with the agent who reviews checkout changes.
export function demoOnTask(fx: RoomFixture, room: string, row: MockMemory): void {
  if (room !== ROOM) return;
  const owner = String(row.meta?.assignee ?? "").replace(/^@/, "");
  if (!owner || !row.episode) return;
  takeOn(fx, row, owner);
}

function takeOn(fx: RoomFixture, row: MockMemory, owner: string): void {
  if (!row.episode || !once(`task:${row.key}`)) return;
  const thread = row.episode;
  const reviewer = "reviewer";
  void (async () => {
    await sleep(1200);
    await think(owner, thread, 2000);
    claim(fx, row.key, owner);
    setPresence(fx, owner, String(row.value));
    say(fx, owner, "On it. I can reproduce it: two quick taps on Pay send two payment requests, and Stripe charges both.", thread);

    // Act 4 — the two coordinate in the thread, by mentioning each other.
    await sleep(2600);
    await think(owner, thread, 3200);
    patchRow(fx, row.key, { branch: "fix/double-charge", pr: "#504", ci: "green" }, owner);
    say(
      fx,
      owner,
      "Fix is up on #504: each checkout gets one payment ID, so a second tap reuses it and Stripe can't charge twice. " +
        `@${reviewer} can you try it on a slow connection?`,
      thread,
    );
    await think(reviewer, thread, 3400);
    say(
      fx,
      reviewer,
      `Tapped Pay five times on a throttled phone: one charge. But nothing tests it, so it can come back. @${owner} can you add a test?`,
      thread,
    );
    await think(owner, thread, 3000);
    patchRow(fx, row.key, { ci: "running" }, owner);
    say(fx, owner, `Added one: it double-taps Pay against a slow Stripe and expects one charge. CI is green. @${reviewer}`, thread);
    patchRow(fx, row.key, { ci: "green" }, owner);

    // Act 5 — the work's evidence goes in the room, where everyone can see it.
    await think(owner, thread, 2600);
    const clip = await clipBytes();
    if (clip) addUpload(ROOM, fx, CLIP, clip, owner);
    publish(ROOM, memoryChangedFrame(`uploads/${CLIP}`, 1, owner));
    say(fx, owner, `And a recording of it on a throttled phone, five taps and one charge: [[uploads/${CLIP}]]`, thread);
    await think(reviewer, thread, 3000);
    say(fx, reviewer, `Watched it and ran the test: one charge every time. Approved. @${DEMO_PERSON.handle} good to ship.`, thread);
  })();
}

/** The clip's bytes, from the file `record.mjs` names; none outside a take. */
async function clipBytes(): Promise<ArrayBuffer | null> {
  const path = process.env.MYCELIUM_DEMO_CLIP;
  if (!path) return null;
  try {
    const { readFile } = await import("node:fs/promises");
    const buf = await readFile(path);
    return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) as ArrayBuffer;
  } catch {
    return null;
  }
}

// Act 5, closed — you tell the agent to ship it.
function ship(fx: RoomFixture, row: MockMemory, owner: string): void {
  if (!row.episode || !once(`ship:${row.key}`)) return;
  const thread = row.episode;
  void (async () => {
    await think(owner, thread, 2200);
    say(fx, owner, "Merged #504 and deployed. Closing this.", thread);
    resolveRow(fx, row.key, owner, { pr: "#504" });
    setPresence(fx, owner);
  })();
}

/** A message someone posted: a mention of an agent is how the story moves. */
export function demoOnMessage(fx: RoomFixture, room: string, msg: MockMessage): void {
  if (room !== ROOM) return;
  const text = msg.content.trim();
  const thread = msg.episode && msg.episode !== LIVE ? msg.episode : null;
  const named = mentioned(text).find((h) => isAgent(fx, h));
  if (!named) return;
  const row = thread ? rowOf(fx, thread) : undefined;
  if (row) ship(fx, row, named);
  else if (!thread) welcome(fx, named);
}

// ── act 6: later, a team ──────────────────────────────────────────────────────

/** The agents the room has grown to, each holding a task of its own. */
const TEAM: { handle: string; description: string; row: string; title: string; short: string; meta?: Record<string, unknown> }[] = [
  {
    handle: "builder",
    description: "Writes the checkout code, on Sam's machine in ~/code/shop.",
    row: "work/loyalty-card",
    title: "Loyalty card: every tenth coffee free",
    short: "b1c2d3",
    meta: { branch: "feat/loyalty", ci: "running", pr: "#511" },
  },
  {
    handle: "designer",
    description: "Designs the shop's pages and menus, on Priya's machine.",
    row: "work/spring-menu-photos",
    title: "New photos for the spring menu",
    short: "c2d3e4",
  },
  {
    handle: "support",
    description: "Answers customer email and files what it can't fix.",
    row: "work/refund-emails",
    title: "Answer this week's refund emails",
    short: "d3e4f5",
  },
  {
    handle: "qa",
    description: "Load-tests and places test orders before anything ships.",
    row: "work/load-test-checkout",
    title: "Load-test checkout for the spring sale",
    short: "e4f5a6",
    meta: { priority: "high" },
  },
  {
    handle: "ops",
    description: "Keeps payments, alerts and deploys running.",
    row: "work/payment-alerts",
    title: "Alert us when payments start failing",
    short: "f2b4d6",
  },
  {
    handle: "growth",
    description: "Runs the numbers and the spring sale's emails, on Jordan's machine.",
    row: "work/spring-sale-email",
    title: "Spring sale email to the mailing list",
    short: "a6b7c8",
  },
];

/** What the team says, in order: [who, thread short id or null for the room, text]. */
const CHATTER: [string, string | null, string][] = [
  ["designer", "c2d3e4", "Shot the cherry blossom latte and the matcha scone. Cropping for the menu now."],
  ["qa", "e4f5a6", "Ramping to 400 checkouts a minute. Payments hold; the menu page is the slow one."],
  ["support", "d3e4f5", "Six refund emails so far. Four are the double charge, already refunded. Two need a person."],
  ["builder", "b1c2d3", "Stamps save per customer now. @designer what should the stamp card look like?"],
  ["ops", "f2b4d6", "Pager now waits for three failures in a row, and only for card payments."],
  ["growth", "a6b7c8", "Draft is in. Subject line: Spring is brewing, 20% off everything this week."],
  ["designer", "b1c2d3", "@builder ten little cups in a row, the tenth one gold. Sending it over."],
  ["qa", "e4f5a6", "@designer the new menu photos are 4 MB each, that's the slow page. Can you shrink them?"],
  ["sam-rivera", "a6b7c8", "Love it. @growth send it Monday at 8, people check email with their coffee."],
  ["designer", "e4f5a6", "Done, they're 180 KB now and look the same. @qa try again?"],
  ["support", null, "Heads up: two customers asked if the loyalty card works for oat milk drinks. It should."],
  ["builder", "b1c2d3", "It does. Every drink counts. CI is green on #511."],
  ["qa", "e4f5a6", "400 a minute, everything under a second. Good to go for the sale."],
  ["ops", "f2b4d6", "Turned the alert on. Closing this."],
  ["growth", "a6b7c8", "Scheduled for Monday 8:00."],
  // Left unanswered, so the board has something waiting on you.
  ["support", "d3e4f5", "@sam-rivera two of the refunds are over $200. Should I send them, or do you want to look first?"],
];

/** The epic the team's sale work is part of, and the tasks that are its parts. */
const SALE = "work/spring-sale";
const SALE_PARTS = new Set([
  "work/spring-menu-photos",
  "work/load-test-checkout",
  "work/spring-sale-email",
  "work/loyalty-card",
]);

/** The room, some days later: more members, each on a task, every thread moving. */
export function demoBusy(fx: RoomFixture): void {
  if (!once("busy")) return;
  const d = on(fx);
  // The first task is long done, and the rest of the board has moved on.
  for (const key of ["work/add-apple-pay", "work/turn-on-apple-pay"]) {
    patchRow(fx, key, { status: "resolved", assignment: "resolved" }, "reviewer");
  }
  // The spring sale, as an epic: the board draws it with its parts under it.
  fx.memories.push(
    boardRow(SALE, "Get ready for the spring sale", { kind: "action", status: "open" }, DEMO_PERSON.handle, 60 * 24, "e5f6a7"),
  );
  publish(ROOM, memoryChangedFrame(SALE, 1, DEMO_PERSON.handle));
  for (const [i, m] of TEAM.entries()) {
    const partOf = SALE_PARTS.has(m.row) ? { "part-of": SALE } : {};
    if (!isAgent(fx, m.handle)) {
      fx.memories.push({
        key: `agents/${m.handle}`,
        value: manifest(m.description),
        created_by: DEMO_PERSON.handle,
        version: 1,
        updated_at: ago(60 * 24 * 2),
        episode: ep(`ag${i}`),
      });
      publish(ROOM, memoryChangedFrame(`agents/${m.handle}`, 1, DEMO_PERSON.handle));
    }
    const existing = fx.memories.find((r) => r.key === m.row);
    if (existing) {
      patchRow(fx, m.row, { assignment: "held", owner: `@${m.handle}`, claimed_at: ago(40), ...(m.meta ?? {}), ...partOf }, m.handle);
    } else {
      fx.memories.push(
        boardRow(
          m.row,
          m.title,
          {
            kind: "action",
            status: "open",
            assignment: "held",
            owner: `@${m.handle}`,
            claimed_at: ago(30 + i * 7),
            ...(m.meta ?? {}),
            ...partOf,
          },
          DEMO_PERSON.handle,
          30 + i * 7,
          m.short,
        ),
      );
      publish(ROOM, memoryChangedFrame(m.row, 1, m.handle));
    }
    setPresence(fx, m.handle, m.title);
  }
  setPresence(fx, "reviewer", "Review the loyalty card");
  // New work nobody has taken yet, for the board's Up next.
  for (const [key, title, short] of [
    ["work/oat-milk-stamps", "Count oat milk drinks on the loyalty card", "b8c9d0"],
    ["work/gift-cards", "Sell gift cards at checkout", "c9d0e1"],
  ] as const) {
    fx.memories.push(boardRow(key, title, { kind: "action", status: "open", assignment: "unclaimed" }, "support", 20, short));
    publish(ROOM, memoryChangedFrame(key, 1, "support"));
  }
  // An hour of conversation already in the threads, so each one opens lived in.
  for (const [i, m] of TEAM.entries()) {
    fx.messages.push({
      id: `busy-earlier-${i}`,
      sender_handle: m.handle,
      message_type: "broadcast",
      content: `Picked this up: ${m.title.charAt(0).toLowerCase()}${m.title.slice(1)}.`,
      created_at: ago(30 + i * 7),
      episode: ep(m.short),
    });
  }

  void (async () => {
    await sleep(800);
    for (const [who, short, text] of CHATTER) {
      const thread = short ? ep(short) : null;
      if (who !== DEMO_PERSON.handle) await think(who, thread, 500);
      d.say(who, text, thread);
      if (text.startsWith("Turned the alert on")) resolveRow(fx, "work/payment-alerts", "ops");
      if (text.startsWith("400 a minute")) resolveRow(fx, "work/load-test-checkout", "qa");
      await sleep(1100);
    }
  })();
}
