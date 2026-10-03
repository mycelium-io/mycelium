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
 *   2. you hand @builder a task, and it claims it in the task's thread;
 *   3. in that thread you summon `@conductor review @builder @reviewer`, and
 *      the review flow runs: build, review, a finding sent back, a fix, approval;
 *   4. @reviewer files the decision the fix raised, and the two disagree in it;
 *   5. you summon `@aligner`, the negotiation converges, and the agreement
 *      compiles into new rows on the board.
 *
 * Times are real (relative to when the dev server booted), so the board reads
 * "2h", not the default fixtures' fixed clock. Each act runs once per boot.
 */

import type { EpisodeSummary, FlowStep, PresenceMember, RoomFloor } from "@/lib/api";
import type { MockMemory, MockMessage, RoomFixture } from "./fixtures";
import { Director, once, sleep } from "./director";
import { liveEpisode, memoryChangedFrame, publish, respondingFrame } from "./live";

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

const manifest = (description: string, adapter = "claude_code", extra = ""): string =>
  `adapter: ${adapter}\ndescription: "${description}"\n${extra}`;

const REVIEW_STEPS: FlowStep[] = [
  { id: "build", to: "author", next: "review", prompt: "Task {task}: {ask}\n\nDo the work on your own branch." },
  {
    id: "review",
    to: "reviewer",
    next: { accept: "approved", reject: "fix", default: "fix" },
    prompt: "Review the work on {task}. Approve only what you ran and saw hold.",
  },
  { id: "fix", to: "author", next: "review", prompt: "The reviewer sent {task} back:\n\n{reply}" },
  { id: "approved", end: "resolved" },
];

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
      key: "agents/aligner",
      value: manifest("Helps members agree when they disagree.", "engine", "kind: aligner\n"),
      created_by: "operator",
      version: 1,
      updated_at: ago(60 * 26),
      episode: ep("c4e6a8"),
    },
    {
      key: "agents/conductor",
      value: manifest("Walks a flow inside a task's thread, passing the floor step by step.", "engine", "kind: conductor\n"),
      created_by: "operator",
      version: 1,
      updated_at: ago(60 * 26),
      episode: ep("d5f7b9"),
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
      content:
        "Two customers wrote in this morning saying they were charged twice. Both on phones, both on a slow connection.",
      created_at: ago(6),
      episode: null,
    },
  ];

  const presence: PresenceMember[] = [
    { handle: "reviewer", kind: "lease", last_seen: ago(1), title: "Add Apple Pay to checkout" },
    { handle: "aligner", kind: "lease", last_seen: ago(1) },
    { handle: "conductor", kind: "lease", last_seen: ago(1) },
  ];

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
    l9: [],
  };
}

// ── the director ──────────────────────────────────────────────────────────────

// The writes an agent's side makes, through the shared director (director.ts),
// bound to the demo's room.
const on = (fx: RoomFixture): Director => new Director(ROOM, fx);
const say = (fx: RoomFixture, who: string, content: string, episode: string | null = null, conductor?: Record<string, unknown>) =>
  on(fx).say(who, content, episode, conductor);
const join = (fx: RoomFixture, handle: string, intent: string, episode: string) => on(fx).join(handle, intent, episode);
const patchRow = (fx: RoomFixture, key: string, meta: Record<string, unknown>, by: string) => on(fx).patchRow(key, meta, by);
const fileRow = (fx: RoomFixture, key: string, title: string, meta: Record<string, unknown>, by: string, short: string) =>
  on(fx).fileRow(key, title, meta, by, short);
const claim = (fx: RoomFixture, key: string, who: string) => on(fx).claim(key, who);
const resolveRow = (fx: RoomFixture, key: string, who: string, extra: Record<string, unknown> = {}) => on(fx).resolve(key, who, extra);
const setPresence = (fx: RoomFixture, handle: string, title?: string) => on(fx).present(handle, title);
const setFloor = (fx: RoomFixture, floor: RoomFloor | null, episode: string) => on(fx).floor(floor, episode);
const rowOf = (fx: RoomFixture, episode: string | null | undefined) => on(fx).rowOf(episode);

/** An agent visibly thinking, then the beat it takes. */
async function think(who: string, episode: string | null, ms: number): Promise<void> {
  publish(ROOM, respondingFrame(who, episode));
  await sleep(ms);
}

// Act 1 — an agent added from your machine joins and says hello.
export function demoOnLaunch(fx: RoomFixture, room: string, handle: string): void {
  if (room !== ROOM || !once(`launch:${handle}`)) return;
  void (async () => {
    // The runner reports the start after a couple of seconds; the agent is a
    // member from then on.
    await sleep(2600);
    if (!fx.memories.some((m) => m.key === `agents/${handle}`)) {
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
    await think(handle, null, 1800);
    say(fx, handle, "Hi! I'm in ~/code/shop on Sam's machine, with the checkout repo checked out. Hand me something.");
  })();
}

// Act 2 — a task handed to an agent: it claims the row and starts in its thread.
export function demoOnTask(fx: RoomFixture, room: string, row: MockMemory): void {
  if (room !== ROOM) return;
  const owner = String(row.meta?.assignee ?? "").replace(/^@/, "");
  if (!owner || !row.episode || !once(`task:${row.key}`)) return;
  const thread = row.episode;
  void (async () => {
    await sleep(1400);
    await think(owner, thread, 2200);
    claim(fx, row.key, owner);
    setPresence(fx, owner, String(row.value));
    say(
      fx,
      owner,
      "Taking this. I can reproduce it: two quick taps on Pay send two payment requests, and Stripe charges both. " +
        "@reviewer, want to review the fix when it's up?",
      thread,
    );
    await think("reviewer", thread, 1800);
    say(fx, "reviewer", "Yes. Run it through review and I'll test it on a slow connection.", thread);
  })();
}

// Act 3 — the review flow, walked by the conductor in the task's thread.
function reviewFlow(fx: RoomFixture, thread: string, author: string, reviewer: string): void {
  if (!once(`review:${thread}`)) return;
  const row = rowOf(fx, thread);
  const title = row ? String(row.value) : null;
  // The run's record is the thread's own episode, as a run in a task is: the
  // board folds it into the row rather than drawing a row of its own.
  const short = thread.split(":").pop() ?? thread;
  const run: EpisodeSummary = {
    short_id: short,
    episode: thread,
    topic: `urn:concept:mycelium:${ROOM}`,
    outcome: "open",
    subkind: null,
    participants: [author, reviewer, "conductor"],
    metrics: null,
    assignments: null,
    tasks: [],
    message_count: 0,
    updated_at: now(),
    updated_by: "conductor",
    within: thread,
    current_step: "build",
    flow: {
      name: "review",
      description: "An author does the work, a reviewer checks it against evidence; findings go back until the reviewer approves.",
      roles: ["author", "reviewer"],
      max_steps: 9,
      bound: { author, reviewer },
      cast: [author, reviewer],
      ask: title ?? "the task",
      steps: REVIEW_STEPS,
    },
    trace: [],
  };
  fx.episodes.push(run);
  const floorFor = (who: string): RoomFloor => ({
    thread: short,
    episode: thread,
    key: row?.key ?? null,
    title,
    holder: "conductor",
    speakers: [who],
  });
  let turnNo = 0;
  const stepTo = (step: string, who: string) => {
    turnNo += 1;
    run.current_step = step;
    run.updated_at = now();
    setFloor(fx, floorFor(who), thread);
    say(fx, "conductor", `review · ${step} · turn ${turnNo} of 9 · ${who}`, thread, {
      event: "turn",
      protocol: "review",
      step,
      to: who,
      turn: turnNo,
      cap: 9,
    });
  };
  const took = (step: string, who: string, stance: string | null, next: string) => {
    run.trace = [
      ...(run.trace ?? []),
      { step, turn: turnNo, asked: [who], stances: { [who]: stance }, stance, next, at: now() },
    ];
    run.message_count += 1;
    run.updated_at = now();
    say(fx, "conductor", `${step} → ${next}`, thread, { event: "edge", step, who, stance, next });
  };

  void (async () => {
    await sleep(900);
    say(fx, "conductor", `Running review in this task: @${author} builds, @${reviewer} reviews.`, thread, {
      event: "open",
      protocol: "review",
      description: run.flow?.description,
      roles: { author, reviewer },
      members: [author, reviewer],
      steps: REVIEW_STEPS,
    });
    await sleep(1200);

    stepTo("build", author);
    await think(author, thread, 3200);
    say(
      fx,
      author,
      "Fixed in #504: each checkout now gets one payment ID, so a second tap reuses it and Stripe can't charge twice. " +
        "The Pay button also locks after the first tap. Branch fix/double-charge, CI is green.",
      thread,
    );
    if (row) patchRow(fx, row.key, { branch: "fix/double-charge", pr: "#504", ci: "green" }, author);
    took("build", author, null, "review");
    await sleep(800);

    stepTo("review", reviewer);
    await think(reviewer, thread, 3400);
    say(
      fx,
      reviewer,
      "Tapped Pay five times on a throttled connection: one charge. Good. But nothing tests it, so it can come back. Back to you.",
      thread,
    );
    took("review", reviewer, "reject", "fix");
    await sleep(800);

    stepTo("fix", author);
    if (row) patchRow(fx, row.key, { ci: "running" }, author);
    await think(author, thread, 3000);
    say(fx, author, "Added a test that double-taps Pay against a slow Stripe mock and asserts one charge. CI is green.", thread);
    if (row) patchRow(fx, row.key, { ci: "green" }, author);
    took("fix", author, null, "review");
    await sleep(800);

    stepTo("review", reviewer);
    await think(reviewer, thread, 2600);
    say(fx, reviewer, "Ran the new test and tapped it by hand again: one charge every time. Approved.", thread);
    took("review", reviewer, "accept", "approved");
    run.outcome = "resolved";
    run.subkind = "resolved";
    run.current_step = null;
    run.updated_at = now();
    setFloor(fx, null, thread);
    say(fx, "conductor", "✓ Done: @reviewer approved after one round of fixes.", thread, {
      event: "close",
      protocol: "review",
      outcome: "resolved",
      steps: 4,
      reason: "reached `approved`",
    });
    if (row) resolveRow(fx, row.key, reviewer);
    publish(ROOM, {
      id: `commit-${run.short_id}`,
      sender_handle: "conductor",
      message_type: "l9_commit",
      episode: run.episode,
      content: {
        l9: {
          header: { kind: "commit", subkind: "resolved", message: { id: `commit-${run.short_id}`, parents: [], episode: run.episode } },
          payload: { data: { protocol: "review", steps: 4, assignments: {}, metrics: {} } },
        },
      },
    });
    setPresence(fx, author);

    await sleep(2400);
    await think(reviewer, null, 1800);
    say(
      fx,
      reviewer,
      "One thing the fix doesn't answer: the customers already charged twice. Do we refund them automatically, or send them to support first? Filing it.",
    );
    await sleep(600);
    fileRow(
      fx,
      "decisions/double-charge-refunds",
      "Double charges: refund automatically, or send to support first?",
      { kind: "decision", status: "open", priority: "urgent", choices: ["refund automatically", "send to support"] },
      reviewer,
      "e9f1a3",
    );
    const decision = ep("e9f1a3");
    await think(author, decision, 2200);
    say(fx, author, "Refund automatically. They already paid twice, and making them wait on support makes it worse.", decision);
    await think(reviewer, decision, 2400);
    say(fx, reviewer, "Send to support. If our check is wrong, we'd refund someone's real second order.", decision);
  })();
}

// Act 4 — the aligner, summoned into the decision's thread.
function negotiate(fx: RoomFixture, thread: string): void {
  if (!once(`aligner:${thread}`)) return;
  const row = rowOf(fx, thread);
  const a = "builder";
  const b = "reviewer";
  // The negotiation is recorded on the decision's thread, so its outcome folds
  // into the decision's row.
  const neg = thread;
  const issue = "double charges";
  const tick = (round: number, who: string, action: string, offer: Record<string, string>) =>
    publish(ROOM, {
      id: `tick-${round}-${who}-${action}`,
      sender_handle: "aligner",
      message_type: "coordination_tick",
      episode: neg,
      content: JSON.stringify({ payload: { round, participant_id: who, action, current_offer: offer } }),
    });
  const summary: EpisodeSummary = {
    short_id: thread.split(":").pop() ?? thread,
    episode: neg,
    topic: `urn:concept:mycelium:${ROOM}`,
    outcome: "open",
    subkind: null,
    participants: [a, b, "aligner"],
    metrics: null,
    assignments: null,
    tasks: [],
    message_count: 0,
    updated_at: now(),
    updated_by: "aligner",
    within: thread,
  };
  fx.episodes.push(summary);

  void (async () => {
    for (const who of [a, b]) {
      join(fx, who, issue, neg);
      await sleep(300);
    }
    await think("aligner", thread, 2600);
    say(
      fx,
      "aligner",
      "You agree on the goal: whoever was charged twice gets their money back. You differ on one case, a second charge " +
        "that is a real order. So the issue is how sure we must be before refunding without a person looking.",
      thread,
    );
    tick(1, a, "propose", { refund: "automatic" });
    await sleep(900);
    tick(1, b, "counter", { refund: "support first" });
    await think("aligner", thread, 2600);
    say(
      fx,
      "aligner",
      "Proposal: refund automatically when the two charges match to the cent within two minutes of each other, which is " +
        "the button bug. Anything else goes to support, answered within a day. @builder?",
      thread,
    );
    tick(2, "aligner", "propose", { refund: "automatic if same amount within 2 min", else: "support within a day" });
    await think(a, thread, 1900);
    say(fx, a, "Works for me. Nearly every case we've seen is an exact match seconds apart.", thread);
    tick(2, a, "accept", { refund: "automatic if same amount within 2 min", else: "support within a day" });
    await think("aligner", thread, 900);
    say(fx, "aligner", "@reviewer?", thread);
    await think(b, thread, 2200);
    say(fx, b, "Yes. A real second order is never the same amount seconds later, so that covers my worry.", thread);
    tick(2, b, "accept", { refund: "automatic if same amount within 2 min", else: "support within a day" });
    await sleep(700);

    const assignments = {
      "exact duplicates": "refund automatically",
      "everything else": "support reviews within a day",
    };
    summary.outcome = "converged";
    summary.subkind = "converged";
    summary.assignments = assignments;
    summary.metrics = { mpc: 1, gar: 0.92, scr: 1, provenance_weight: 1 } as EpisodeSummary["metrics"];
    summary.tasks = ["work/auto-refund-exact-duplicates", "work/support-reviews-other-duplicates"];
    summary.updated_at = now();
    publish(ROOM, {
      id: `consensus-${neg}`,
      sender_handle: "backend",
      message_type: "coordination_consensus",
      episode: neg,
      content: JSON.stringify({ plan: "double charges", assignments, episode: neg, metrics: { gar: 0.92 } }),
    });
    say(
      fx,
      "aligner",
      "✓ Agreed: exact duplicates are refunded automatically; anything else goes to support, answered within a day.",
      thread,
    );
    if (row) resolveRow(fx, row.key, "aligner", { decision: "refund exact duplicates automatically; support for the rest" });

    await sleep(1600);
    fileRow(
      fx,
      "work/auto-refund-exact-duplicates",
      "Refund duplicate charges that match to the cent within two minutes",
      { kind: "action", status: "open", assignee: "builder", priority: "high", "part-of": row?.key },
      "aligner",
      "c2e4a6",
    );
    await sleep(500);
    fileRow(
      fx,
      "work/support-reviews-other-duplicates",
      "Send other duplicate charges to support, answered within a day",
      { kind: "action", status: "open", assignee: "reviewer", "part-of": row?.key },
      "aligner",
      "d3f5b7",
    );
    await sleep(1400);
    claim(fx, "work/auto-refund-exact-duplicates", a);
    say(fx, a, "On it.", ep("c2e4a6"));
  })();
}

/** A message someone posted: a summon of an engine starts its act. */
export function demoOnMessage(fx: RoomFixture, room: string, msg: MockMessage): void {
  if (room !== ROOM) return;
  const text = msg.content.trim();
  const thread = msg.episode && msg.episode !== LIVE ? msg.episode : null;
  if (/^@conductor\b/i.test(text) && /\breview\b/i.test(text) && thread) {
    const handles = [...text.matchAll(/@([a-z0-9][\w.-]*)/gi)].map((m) => m[1].toLowerCase()).filter((h) => h !== "conductor");
    reviewFlow(fx, thread, handles[0] ?? "builder", handles[1] ?? "reviewer");
    return;
  }
  if (/@aligner\b/i.test(text) && thread) negotiate(fx, thread);
}
