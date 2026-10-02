// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The patterns explorer's fixtures: a pack of three patterns and the rooms two
 * of them ran in. The adversarial review is mid-run, the approval gate is
 * waiting on the person, and supervisor and workers has not been run.
 *
 * The rooms are listed only to the explorer's own pages, so the rest of the
 * mock app (and every screenshot taken of it) keeps the rooms it had.
 */

import type { EpisodeFlow, EpisodeSummary, FlowStep } from "@/lib/api";
import type { RoomFixture, MockMessage, MockRoom } from "./fixtures";

const NOW = Date.parse("2026-08-28T17:30:00Z");
const iso = (minsAgo: number): string => new Date(NOW - minsAgo * 60_000).toISOString();

// ── the pack ─────────────────────────────────────────────────────────────────

const GATED: EpisodeFlow = {
  name: "gated",
  description: "A proposer proposes, a guardian approves or blocks; a block sends it back.",
  roles: ["proposer", "guardian"],
  max_steps: 6,
  steps: [
    { id: "propose", to: "proposer", next: "review" },
    { id: "review", to: "guardian", next: { accept: "approved", reject: "propose", default: "propose" } },
    { id: "approved", end: "resolved" },
  ] satisfies FlowStep[],
};

const ADVERSARIAL: EpisodeFlow = {
  name: "adversarial-review",
  description: "A proposer defends a proposal against a critic for up to three rounds; what is left standing is the result.",
  roles: ["proposer", "critic"],
  max_steps: 7,
  steps: [
    { id: "propose", to: "proposer", next: "challenge" },
    { id: "challenge", to: "critic", next: { accept: "settled", reject: "answer", default: "answer" } },
    { id: "answer", to: "proposer", next: "challenge" },
    { id: "settled", end: "resolved" },
  ] satisfies FlowStep[],
};

const FAN_OUT: EpisodeFlow = {
  name: "fan-out",
  description: "A lead asks every worker at once, then combines what came back.",
  roles: ["lead"],
  max_steps: 6,
  steps: [
    { id: "gather", to: "workers", next: "combine" },
    { id: "combine", to: "lead", next: "done" },
    { id: "done", end: "resolved" },
  ] satisfies FlowStep[],
};

interface MockPattern {
  pattern: string;
  title: string;
  summary: string;
  flow: string;
  roles: string[];
  members: { handle: string; kind: string; description: string; notes?: string }[];
  scenario: Record<string, unknown>;
  flow_spec: EpisodeFlow;
}

const PACK: MockPattern[] = [
  {
    pattern: "adversarial-review-agents",
    title: "Adversarial review",
    summary: "A proposer defends a recommendation against a critic, for a bounded number of rounds, and the objections are kept.",
    flow: "adversarial-review",
    roles: ["proposer", "critic"],
    members: [
      {
        handle: "proposer",
        kind: "persona",
        description: "Recommends the commitment and defends it.",
        notes: "You are the proposer. You recommend a three-year commitment to a data warehouse vendor, for a company of 120 people. State your assumptions, and answer each objection directly.",
      },
      {
        handle: "critic",
        kind: "persona",
        description: "Looks for the weakest assumptions in the proposal.",
        notes: "You are the critic. Find what is wrong with the proposal, not to be agreeable and not to be nitpicky. Accept only when your objections have been answered.",
      },
      { handle: "you", kind: "human", description: "Sees the result and any objection left standing." },
    ],
    scenario: {
      task: { title: "Commit to a three-year data warehouse contract?" },
      summon: { flow: "adversarial-review", members: ["proposer", "critic"], ask: "Should we commit to the three-year data warehouse contract?" },
      before: {
        headline: "Sign for three years at 38% off",
        detail: "Saves about $410,000, assuming usage grows 25% a year, prices otherwise rise 8% a year, and the company never switches vendors.",
      },
      after: { track: "The recommendation as it now stands, the saving it claims, and which objections are answered or open." },
      guide: [
        { at: "before", title: "Where it starts", text: "This is the proposer's recommendation as it walks in: a large saving that rests on three assumptions nobody has checked yet." },
        { at: "members", title: "Two agents, two jobs", text: "The proposer defends the deal. The critic is told to break it, on substance rather than wording. Neither is scripted: each is a model playing a role written in plain English." },
        { at: "flow", title: "The rules of the exchange", text: "The critic objects, the proposer answers, and it goes round again, at most three times. The conductor follows this graph to decide whose turn it is. It has no model of its own." },
        { at: "after", title: "Watch it move", text: "This fills in as they argue. Watch the saving: when an objection lands, the proposal changes rather than repeating itself. Anything still open at the end comes to you." },
      ],
    },
    flow_spec: ADVERSARIAL,
  },
  {
    pattern: "approval-gate-agent",
    title: "Approval gate",
    summary: "An agent proposes a spend, and a person approves or blocks it before anything happens.",
    flow: "gated",
    roles: ["proposer", "guardian"],
    members: [
      {
        handle: "ops",
        kind: "persona",
        description: "Prepares refunds and proposes them for approval.",
        notes: "You are the ops agent. You prepare refunds. You may not issue them: anything over the policy limits has to be approved by a person first.",
      },
      { handle: "you", kind: "human", description: "The approver." },
    ],
    scenario: {
      task: { title: "Refund 23 duplicate charges from Thursday's payment outage" },
      summon: { flow: "gated", members: ["ops", "you"], ask: "Refund the 23 duplicate charges from Thursday's payment outage." },
      before: {
        headline: "$8,400 in refunds, ready to go",
        detail: "23 customers were charged twice in Thursday's outage. The batch is over the $5,000 limit, so a person has to sign off before anything is issued.",
      },
      after: { track: "Whether the refunds were approved or are still held, and how the proposal changed to meet the approver." },
      guide: [
        { at: "before", title: "Where it starts", text: "A refund batch is ready, and it is over the limit a person has to approve. Nothing has been refunded yet." },
        { at: "members", title: "An agent that cannot act alone", text: "ops can prepare refunds but may not issue them. You are in the room as the approver." },
        { at: "flow", title: "A gate, not a suggestion", text: "The proposal goes to review. Approve and it ends; block and it goes back to ops, which has to answer your reason. Silence is not approval." },
        { at: "turn", title: "Your call", text: "Approve, or block with a reason. Try blocking once and watch ops answer your objection instead of arguing past it." },
      ],
    },
    flow_spec: GATED,
  },
  {
    pattern: "supervisor-worker",
    title: "Supervisor and workers",
    summary: "A supervisor asks three specialists at once, then combines what each found into one answer.",
    flow: "fan-out",
    roles: ["lead"],
    members: [
      { handle: "supervisor", kind: "persona", description: "Takes the question, asks the specialists, combines their answers.", notes: "You are the supervisor. You do not know the answer yourself." },
      { handle: "docs", kind: "persona", description: "Knows the written documentation.", notes: "You know only the written documentation." },
      { handle: "code", kind: "persona", description: "Knows what changed in the code.", notes: "You know only the change history." },
      { handle: "tickets", kind: "persona", description: "Knows what customers and support have reported.", notes: "You know only the support queue." },
    ],
    scenario: {
      task: { title: "Why did checkout latency double after Tuesday's release?" },
      summon: { flow: "fan-out", members: ["supervisor", "docs", "code", "tickets"], ask: "Why did checkout latency double after Tuesday's release?" },
      before: {
        headline: "Checkout is twice as slow, and nobody knows why",
        detail: "Three specialists each hold one slice of what is known: the docs, the code history and the support queue.",
      },
      after: { track: "The cause the team settled on, the evidence for it, and what is still unexplained." },
      guide: [
        { at: "before", title: "Where it starts", text: "A slowdown with no explanation. The answer exists, but it is split across three people who each see one part." },
        { at: "members", title: "Each one knows a slice", text: "The supervisor knows nothing itself. docs, code and tickets each answer only from their own source." },
        { at: "flow", title: "Ask everyone at once", text: "The supervisor puts the question to all three together, then combines what comes back." },
      ],
    },
    flow_spec: FAN_OUT,
  },
];

export function patternList(): Record<string, unknown> {
  return {
    patterns: PACK.map(({ pattern, title, summary, flow, roles, members }) => ({
      pattern,
      title,
      summary,
      flow,
      roles,
      members: members.map(({ handle, kind, description }) => ({ handle, kind, description })),
    })),
    skipped: {},
  };
}

export function patternRead(name: string): Record<string, unknown> | null {
  const p = PACK.find((x) => x.pattern === name);
  if (!p) return null;
  return {
    pattern: p.pattern,
    title: p.title,
    summary: p.summary,
    flow: p.flow,
    roles: p.roles,
    members: p.members.map(({ handle, kind, description }) => ({ handle, kind, description })),
    scenario: { pattern: p.pattern, title: p.title, summary: p.summary, room: { title: p.title }, members: p.members, ...p.scenario },
    flow_body: null,
    flow_spec: p.flow_spec,
  };
}

// ── the rooms they ran in ────────────────────────────────────────────────────

const VIEWER = "operator";

function room(name: string, task: string, minsAgo: number): MockRoom {
  return { id: 900 + name.length, name, created_at: iso(minsAgo), is_public: true, is_persistent: true, owner: VIEWER, pattern: name, pattern_task: task };
}

function thread(room: string): string {
  return `urn:ioc:mycelium:episode:${room}:t0001`;
}

function said(room: string) {
  let n = 0;
  const post = (sender: string, content: string, mins: number, conductor?: Record<string, unknown>): MockMessage => ({
    id: `${room.slice(0, 3)}${++n}`,
    sender_handle: sender,
    message_type: "broadcast",
    content,
    created_at: iso(mins),
    episode: thread(room),
    ...(conductor ? { metadata: { conductor } } : {}),
  });
  return post;
}

// The adversarial review, mid-run: one round answered, the critic on round 2.
const ADV = "adversarial-review-agents";
const ADV_TASK = "work/commit-to-a-three-year-data-warehouse-contract";
const advPost = said(ADV);
const advMessages: MockMessage[] = [
  advPost("conductor", "Running adversarial-review with proposer as proposer, critic as critic.", 3.2, {
    event: "open", protocol: "adversarial-review", roles: { proposer: "proposer", critic: "critic" }, members: [], steps: ADVERSARIAL.steps,
  }),
  advPost("conductor", "propose → proposer", 3.1, { event: "turn", protocol: "adversarial-review", step: "propose", to: "proposer", turn: 1, cap: 7 }),
  advPost(
    "proposer",
    "I recommend we sign the three-year contract. The vendor is offering 38% off the annual price, which saves about $410,000 over the term.\n\nIt rests on three assumptions: usage keeps growing 25% a year, the list price otherwise rises 8% a year, and we won't move to another warehouse in that time.",
    2.9,
  ),
  advPost("conductor", "challenge → critic", 2.8, { event: "turn", protocol: "adversarial-review", step: "challenge", to: "critic", turn: 2, cap: 7 }),
  advPost(
    "critic",
    "Two assumptions carry the whole saving. 25% growth every year is a guess: if usage stays flat, the committed volume is overspend and the saving shrinks by more than half. And \"we won't move\" ignores lock-in: three years removes our leverage at the next renewal.\n\nStill open: the growth figure needs evidence, and the contract needs a way out.",
    2.4,
  ),
  advPost("conductor", "critic rejected; back to answer", 2.35, { event: "edge", step: "challenge", who: "critic", stance: "reject", next: "answer" }),
  advPost("conductor", "answer → proposer", 2.3, { event: "turn", protocol: "adversarial-review", step: "answer", to: "proposer", turn: 3, cap: 7 }),
  advPost(
    "proposer",
    "Fair on growth: the last three years were 31%, 22% and 27%, so 25% is the average, not a stretch. But I'll commit to current volume only, with growth billed at the discount as it comes, and ask for a way out at month 18 for a 10% fee. The saving drops to about $340,000.",
    1.6,
  ),
  advPost("conductor", "challenge → critic", 1.5, { event: "turn", protocol: "adversarial-review", step: "challenge", to: "critic", turn: 4, cap: 7, round: 2, rounds: 3 }),
];

const advRun: EpisodeSummary = {
  short_id: "ar01",
  episode: thread(ADV),
  topic: `urn:concept:mycelium:${ADV}`,
  outcome: "open",
  subkind: null,
  participants: ["proposer", "critic", "conductor"],
  metrics: null,
  assignments: null,
  tasks: [],
  message_count: advMessages.length,
  updated_at: iso(1.5),
  updated_by: "conductor",
  within: thread(ADV),
  current_step: "challenge",
  flow: { ...ADVERSARIAL, bound: { proposer: "proposer", critic: "critic" }, cast: ["proposer", "critic"] },
  trace: [
    { step: "propose", turn: 1, asked: ["proposer"], stance: null, next: "challenge", at: iso(2.9) },
    { step: "challenge", turn: 2, asked: ["critic"], stance: "reject", next: "answer", at: iso(2.4) },
    { step: "answer", turn: 3, asked: ["proposer"], stance: null, next: "challenge", at: iso(1.6) },
  ],
};

// The approval gate, waiting on the person: ops proposed, the floor is theirs.
const GATE = "approval-gate-agent";
const GATE_TASK = "work/refund-23-duplicate-charges-from-thursdays-payment-outage";
const gatePost = said(GATE);
const gateMessages: MockMessage[] = [
  gatePost("conductor", "Running gated with ops as proposer, operator as guardian.", 1.4, {
    event: "open", protocol: "gated", roles: { proposer: "ops", guardian: VIEWER }, members: [], steps: GATED.steps,
  }),
  gatePost("conductor", "propose → ops", 1.35, { event: "turn", protocol: "gated", step: "propose", to: "ops", turn: 1, cap: 6 }),
  gatePost(
    "ops",
    "I intend to refund 23 customers who were charged twice during Thursday's outage, $8,400 in total, each to the card that was charged. Every one is a duplicate of a charge that also succeeded.\n\nThe batch is over the $5,000 limit in the refund policy, so it needs your approval before I issue anything. No single refund is over $500.",
    1.0,
  ),
  gatePost("conductor", "review → operator", 0.9, { event: "turn", protocol: "gated", step: "review", to: VIEWER, turn: 2, cap: 6 }),
];

const gateRun: EpisodeSummary = {
  short_id: "ag01",
  episode: thread(GATE),
  topic: `urn:concept:mycelium:${GATE}`,
  outcome: "open",
  subkind: null,
  participants: ["ops", VIEWER, "conductor"],
  metrics: null,
  assignments: null,
  tasks: [],
  message_count: gateMessages.length,
  updated_at: iso(0.9),
  updated_by: "conductor",
  within: thread(GATE),
  current_step: "review",
  flow: { ...GATED, bound: { proposer: "ops", guardian: VIEWER }, cast: ["ops", VIEWER] },
  trace: [{ step: "propose", turn: 1, asked: ["ops"], stance: null, next: "review", at: iso(1.0) }],
};

function fixture(
  name: string,
  task: string,
  title: string,
  minsAgo: number,
  messages: MockMessage[],
  run: EpisodeSummary,
  standing: { headline: string; detail: string; state: string },
  speakers: string[],
): RoomFixture {
  return {
    room: room(name, task, minsAgo),
    memories: [
      { key: task, value: title, created_by: VIEWER, version: 1, updated_at: iso(minsAgo), episode: thread(name), meta: { kind: "task", status: "open" } },
      { key: "context/standing", value: `${standing.headline}\n\n${standing.detail}`, created_by: "system", version: 3, updated_at: iso(0.5), meta: standing },
    ],
    messages,
    episodes: [run],
    episodeDetails: {},
    floors: [{ thread: "t0001", episode: thread(name), key: task, title, holder: "conductor", speakers }],
  };
}

export const PATTERN_ROOMS: Record<string, RoomFixture> = {
  [ADV]: fixture(
    ADV,
    ADV_TASK,
    "Commit to a three-year data warehouse contract?",
    3.3,
    advMessages,
    advRun,
    {
      headline: "Sign at today's volume, with a way out at month 18",
      detail: "The saving fell from $410,000 to about $340,000 to meet the critic's two objections; the critic is weighing the revised deal.",
      state: "running",
    },
    ["critic"],
  ),
  [GATE]: fixture(
    GATE,
    GATE_TASK,
    "Refund 23 duplicate charges from Thursday's payment outage",
    1.5,
    gateMessages,
    gateRun,
    {
      headline: "Nothing refunded yet: the batch waits on you",
      detail: "ops has proposed all 23 refunds, $8,400 in total, each to the card that was charged.",
      state: "running",
    },
    [VIEWER],
  ),
};

/** Whether a request comes from the explorer's pages, which alone list these rooms. */
export function fromExplorer(req: Request): boolean {
  const referer = req.headers.get("referer") ?? "";
  try {
    return new URL(referer).pathname.startsWith("/patterns");
  } catch {
    return false;
  }
}
