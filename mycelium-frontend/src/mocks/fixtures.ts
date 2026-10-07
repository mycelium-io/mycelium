// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Canonical mock data for the UI's fake-backend mode.
 *
 * These fixtures mirror the shapes the real backend serves (see
 * `src/lib/api.ts`), so with `MYCELIUM_UI_MOCK=1` the *real* UI renders every
 * surface — populated, in-progress, and empty — with no SLIM node, no LLM, and
 * no backend server. This is the frontend analogue of the backend/CLI fake
 * stacks: one place to reach any state, for design + visual work.
 *
 * Every room is a small online coffee shop at work, so a screenshot reads as
 * something a team actually does rather than as our own vocabulary:
 *   - `checkout`             — a rich, converged room: Apple Pay and the
 *     double-charge fix, a decision the aligner brokered, flows running in
 *     task threads, pull requests with CI;
 *   - `subscription-pricing` — an in-progress negotiation over what the coffee
 *     subscription costs (nothing compiled yet), with a bridged A2A agent;
 *   - `storefront`           — the room under load: a dozen people and three
 *     dozen agents each working one website ticket;
 *   - `scratch`              — a brand-new empty room (empty states).
 */

import type {
  A2aBridgeState,
  EpisodeDetail,
  EpisodeSummary,
  FlowStep,
  MyceliumMessage,
  MemoryGraph,
  MemoryGraphEdge,
  MemoryGraphNode,
  PresenceMember,
  RoomFloor,
} from "@/lib/api";
import type { RoomStatus } from "@/lib/board/upstream";
import { demoCheckout, isDemoScenario } from "./demo";
import { LEARN_ROOM, learnRoom } from "./learn";
import { PATTERN_ROOMS } from "./patterns";

// A fixed "now" so relative timestamps render deterministically. Callers
// offset from this; nothing here calls Date.now(), so snapshots stay stable.
const NOW = Date.parse("2026-08-28T17:30:00Z");
const iso = (minsAgo: number): string => new Date(NOW - minsAgo * 60_000).toISOString();

export interface MockRoom {
  id: number;
  name: string;
  created_at: string;
  is_public: boolean;
  is_persistent: boolean;
  mas_id?: string | null;
  owner?: string | null;
  members?: string[];
  /** The pattern a room was loaded from, and the task its flow runs in. */
  pattern?: string | null;
  pattern_task?: string | null;
}

export interface MockMemory {
  key: string;
  /** Prose (most memories) or an object — the store's *structured value*
   *  shape, which `MemoryCreate.value` as an object round-trips to; the
   *  board projects a row's typed fields straight from it. Object-valued
   *  memories must also set `content_text` for search and previews. */
  value: string | Record<string, unknown>;
  /** Frontmatter the store doesn't own, read back from `MemoryRead.meta`. This
   *  is where a lease lands and where a board action writes, so a row's fields
   *  can come from here rather than from a structured value. */
  meta?: Record<string, unknown> | null;
  content_text?: string;
  created_by: string;
  updated_by?: string;
  version: number;
  updated_at?: string;
  room_name?: string;
  tags?: string[];
  expandable?: boolean;
  /** The episode URN binding this row to the thread its coordination happens in
   *  (`MemoryRead.episode`). Store-owned rather than part of `meta`, so a write
   *  carries it forward rather than replacing it — the board folds the bound
   *  episode into this row instead of drawing a second one beside it. */
  episode?: string | null;
}

export interface MockMessage {
  id: string;
  sender_handle: string;
  message_type: string;
  content: string;
  created_at: string;
  recipient_handle?: string | null;
  episode?: string | null;
  /** A structured line a surface draws instead of the prose (a conductor post's). */
  metadata?: Record<string, unknown> | null;
}

export interface RoomFixture {
  room: MockRoom;
  memories: MockMemory[];
  messages: MockMessage[];
  episodes: EpisodeSummary[];
  episodeDetails: Record<string, EpisodeDetail>;
  /** Live presence set, served at GET /sessions/members. A resident agent
   *  (one whose handle appears here) projects a board row; without a SLIM node
   *  there is otherwise no presence, so the board's resident rows come from here. */
  presence?: PresenceMember[];
  /** Floors held in the room's threads right now, served beside presence. */
  floors?: RoomFloor[];
  /** The room's link graph (#599/#611) — undefined means "no link index yet",
   *  the same degrade-to-empty case the real backend serves for an unlinked room. */
  links?: MemoryGraph;
  // Wire frames served at GET /messages/wire, feeding the Network pane's message feed.
  // Shaped like the persister's bus frames (a bare `{header, payload}` envelope
  // under `content`, plus the flat fields the inspector reads).
  wire?: Record<string, unknown>[];
  /** The room's A2A bridge, served at GET /a2a/state. Undefined means "no
   *  bridge" — the handler answers with an empty one, like the backend. */
  a2a?: A2aBridgeState;
  /** Resolved upstream state, served at GET /status. Keyed by the board row ids
   *  that mention each reference, exactly as the hub returns it, so the mock
   *  exercises the same attach path the real one does. */
  status?: RoomStatus;
}

/**
 * Builds a `MemoryGraph` from a room's memories plus a hand-authored edge list,
 * deriving each node's `inbound`/`outbound` the same way the backend does
 * (`app/services/links.py:graph`): `outbound` counts every parsed link from that
 * memory, `inbound` counts only the edges that actually resolved — so a memory
 * that is only the *target* of a broken link still reads as a root (inbound=0,
 * outbound=0 → orphan; inbound=0, outbound>0 → root).
 */
function buildMockGraph(
  memories: MockMemory[],
  edges: MemoryGraphEdge[],
): MemoryGraph {
  const outbound = new Map<string, number>();
  const inbound = new Map<string, number>();
  for (const edge of edges) {
    outbound.set(edge.source, (outbound.get(edge.source) ?? 0) + 1);
    if (edge.resolved) inbound.set(edge.target, (inbound.get(edge.target) ?? 0) + 1);
  }
  const nodes: MemoryGraphNode[] = memories.map((m) => ({
    key: m.key,
    expandable: false,
    outbound: outbound.get(m.key) ?? 0,
    inbound: inbound.get(m.key) ?? 0,
  }));
  return { nodes, edges };
}

// ── agent manifests (YAML strings — the UI parses description/adapter) ─────────

const agentManifest = (description: string, adapter = "claude_code", owner?: string): string =>
  `adapter: ${adapter}\ndescription: "${description}"\n` + (owner ? `owner: ${owner}\n` : "");

/** An external A2A agent's manifest: the card the hub resolved plus what it
 *  advertises, the fields the roster and the Network pane read. */
const a2aManifest = (description: string, card: string, skills: string[]): string =>
  `adapter: a2a\ndescription: "${description}"\n` +
  `a2a_card: ${card}\na2a_endpoint: ${card}/a2a\n` +
  `a2a_skills: [${skills.join(", ")}]\n`;

// ── checkout: the rich, converged room ────────────────────────────────────────
//
// Morgan (@operator) runs a small online coffee shop and wants checkout ready
// for the spring sale: Apple Pay added, and the double charges stopped. Two
// agents do the work: @builder writes the code, @reviewer reviews it and places
// test orders on real phones.

const checkoutEpisode = (shortId: string): string =>
  `urn:ioc:mycelium:episode:checkout:${shortId}`;

// The launch-day call the aligner brokered. It is an *orphan* episode — no board
// row is bound to it — because a task's thread is the task's own, not the
// conversation that produced it. The two tasks it compiled each carry their own
// thread below; this URN stays the negotiation's record (Episodes rail, message feed).
const CHECKOUT_EPISODE = checkoutEpisode("e4f1a2");
// The room's own channel. A message with no thread lands here, and a ping about
// a thread is raised here — which is why the ping's own episode is this one and
// the thread it names is in its payload.
const CHECKOUT_LIVE = checkoutEpisode("live");
// The "turn on Apple Pay" task's own thread: where builder and reviewer stage
// that one row, and what the pings below point at. Its own episode, minted when
// the row was, not the negotiation's.
const LAUNCH_THREAD = checkoutEpisode("f1a5c7");
// The "remove the old card form" task's thread.
const OLD_FORM_THREAD = checkoutEpisode("d2b8e0");
// The "add Apple Pay" task's thread, where the release flow runs.
const APPLE_PAY_THREAD = checkoutEpisode("d6f8b0");

// The one call the aligner brokered: which day Apple Pay goes on. Morgan wanted
// thursday, before the sale; builder wanted a day of test orders first and
// countered friday morning. They settled on friday morning, before the sale
// email. A short, ordinary decision, not a set piece.
//
// The *chat* is the source. Each reply is a channel broadcast (`say`), and the
// aligner reads it and emits the structured messages it implies. So one move drives
// three things — the broadcast, the coordination_tick it interprets that from,
// and the message the Network feed shows — and they can't disagree. `ask`
// is the aligner's prompt that precedes a reply (it addresses one at a time).
const CHECKOUT_CONSENSUS = { launch: "friday am" };
interface CheckoutMove {
  round: number;
  who: string;
  action: string;
  offer: Record<string, string>;
  say: string;
  ask?: string;
}
const checkoutMoves: CheckoutMove[] = [
  { round: 1, who: "operator", action: "propose", offer: { launch: "thursday" },
    ask: "when does apple pay go on? thursday, or after the sale starts? @operator?",
    say: "thursday. the sale starts friday and i want apple pay there for it." },
  { round: 1, who: "builder", action: "counter", offer: { launch: "friday am" },
    ask: "@builder, workable?",
    say: "thursday's tight. the code's done, but i want a full day of test orders on real phones first. friday morning, before the sale email goes out." },
  { round: 2, who: "operator", action: "accept", offer: CHECKOUT_CONSENSUS,
    ask: "standing: test orders thursday, apple pay on friday morning. accept?",
    say: "yes, as long as it's on before the email." },
  { round: 2, who: "builder", action: "accept", offer: CHECKOUT_CONSENSUS,
    say: "agreed." },
];

const checkoutMessageChain: MyceliumMessage[] = [
  ...checkoutMoves.map((m, i) => ({
    header: {
      protocol: "ioc",
      kind: "exchange",
      subkind: "tick",
      participants: { actors: [{ id: "aligner", role: "mediator" }, { id: m.who, role: "agent" }] },
      message: { id: `m${i + 1}`, parents: i ? [`m${i}`] : [], episode: CHECKOUT_EPISODE },
      context: { topic: "urn:concept:mycelium:checkout" },
    },
    payload: { type: m.action, data: { round: m.round, offer: m.offer } },
  })),
  {
    header: {
      protocol: "ioc",
      kind: "commit",
      subkind: "converged",
      participants: {
        actors: [
          { id: "aligner", role: "mediator" },
          { id: "operator", role: "human" },
          { id: "builder", role: "agent" },
        ],
      },
      message: { id: `m${checkoutMoves.length + 1}`, parents: [`m${checkoutMoves.length}`], episode: CHECKOUT_EPISODE },
      context: { topic: "urn:concept:mycelium:checkout" },
    },
    payload: {
      type: "consensus",
      data: { assignments: CHECKOUT_CONSENSUS, metrics: { mpc: 0.86, gar: 0.79, scr: 0.0 } },
    },
  },
];

// The mediated negotiation as it appears on the wire: for each move, the
// aligner's optional prompt and the agent's reply (both chat broadcasts, shown
// in the channel), then the coordination_tick the aligner emits from that reply
// (feeds the Network pane, filtered out of the channel). Interleaved and
// timestamped so the transcript reads in order — the chat drives the messages.
const checkoutNegotiation: MockMessage[] = (() => {
  const out: MockMessage[] = [];
  let at = 46; // minutes ago; ticks down as the exchange proceeds
  const step = () => iso((at -= 0.2));
  checkoutMoves.forEach((m, i) => {
    if (m.ask) {
      out.push({ id: `neg-ask-${i}`, sender_handle: "aligner", message_type: "broadcast", content: m.ask, created_at: step() });
    }
    out.push({ id: `neg-say-${i}`, sender_handle: m.who, message_type: "broadcast", content: m.say, created_at: step() });
    out.push({
      id: `tick-${i + 1}`,
      sender_handle: "aligner",
      message_type: "coordination_tick",
      content: JSON.stringify({ round: m.round, participant_id: m.who, action: m.action, current_offer: m.offer, episode: CHECKOUT_EPISODE }),
      created_at: step(),
      episode: CHECKOUT_EPISODE,
    });
  });
  return out;
})();

// The message chain as persister bus frames: bare `{header, payload}` under content,
// with the flat sender_handle/message_type/created_at the inspector reads.
const checkoutWireFrames: Record<string, unknown>[] = checkoutMessageChain.map((env, i) => ({
  message_type: `l9_${env.header.kind}`,
  sender_handle: env.header.participants?.actors?.[0]?.id ?? "aligner",
  created_at: iso(44 - i),
  content: env,
}));

/**
 * A thread's activity as the room hears it: a **ping**, and only a ping.
 *
 * The shape the backend raises (`room_channels.raise_ping`) — an exchange
 * envelope in `live` naming the thread that moved, who wrote and which message,
 * carrying no prose, so there is nothing here to echo even by accident.
 *
 * A ping is a control frame: it belongs to the wire feed, not the message
 * list. The conversational read drops it; the transcript replay is where it
 * survives a reload.
 */
function checkoutPing(message: string, sender: string, minutesAgo: number): Record<string, unknown> {
  return {
    id: `ping-${message}`,
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: iso(minutesAgo),
    room_name: "checkout",
    episode: CHECKOUT_LIVE,
    content: {
      l9: {
        header: {
          kind: "exchange",
          message: { id: `ping-${message}`, parents: [], episode: CHECKOUT_LIVE },
          participants: { actors: [{ id: "system", role: "coordinator" }] },
        },
        payload: { type: "ping", data: { episode: LAUNCH_THREAD, sender, message } },
      },
    },
  };
}

/**
 * A board event as the room hears it: a **notice** — a task filed, claimed,
 * handed back or resolved.
 *
 * The mirror of {@link checkoutPing} — an exchange envelope in `live` naming the
 * task the event was about (key, title, thread to open, who moved it), so the
 * board's changes read as something the room *did*, in sequence with the chat,
 * rather than appearing silently on another tab. ``kind`` rides on a ``filed``
 * notice so the line reads "New decision", not always "New task".
 */
function checkoutNotice(
  subkind: string,
  key: string,
  title: string,
  episode: string,
  by: string,
  minutesAgo: number,
  kind?: string,
  assignee?: string,
): Record<string, unknown> {
  const id = `notice-${subkind}-${key}`;
  return {
    id,
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: iso(minutesAgo),
    room_name: "checkout",
    episode: CHECKOUT_LIVE,
    content: {
      l9: {
        header: {
          kind: "exchange",
          message: { id, parents: [], episode: CHECKOUT_LIVE },
          participants: { actors: [{ id: "system", role: "coordinator" }] },
        },
        payload: {
          type: "notice",
          data: { subkind, key, title, episode, by, ...(kind ? { kind } : {}), ...(assignee ? { for: assignee } : {}) },
        },
      },
    },
  };
}

const checkoutEpisodeSummary: EpisodeSummary = {
  short_id: "e4f1a2",
  episode: CHECKOUT_EPISODE,
  topic: "urn:concept:mycelium:checkout",
  outcome: "converged",
  subkind: "converged",
  participants: ["operator", "builder", "aligner"],
  metrics: { mpc: 0.86, gar: 0.79, scr: 0.91, provenance_weight: 0.74, participants: 3 },
  assignments: { launch: "friday am" },
  tasks: ["work/turn-on-apple-pay", "work/remove-old-card-form"],
  message_count: 3,
  updated_at: iso(42),
  updated_by: "aligner",
};

// A run the conductor is walking right now inside the "turn on Apple Pay"
// task's thread: builder asked to switch it on without the test day, Morgan
// blocked it, and it is back with builder. Its record is an episode of its own,
// nested in the thread (``within``) and reading the same slice (``episode``):
// the task stays one row and one thread.
const checkoutGatedEpisode: EpisodeSummary = {
  short_id: "f10a2c",
  episode: LAUNCH_THREAD,
  topic: "urn:concept:mycelium:checkout",
  outcome: "open",
  subkind: null,
  participants: ["builder", "operator", "conductor"],
  metrics: null,
  assignments: null,
  tasks: [],
  message_count: 5,
  updated_at: iso(2),
  updated_by: "conductor",
  within: LAUNCH_THREAD,
  current_step: "propose",
  flow: {
    name: "gated",
    description: "A proposer proposes, a guardian approves or blocks; a block sends it back.",
    roles: ["proposer", "guardian"],
    max_steps: 6,
    bound: { proposer: "builder", guardian: "operator" },
    cast: ["builder", "operator"],
    ask: "turn Apple Pay on for everyone today, without the test day",
    steps: [
      { id: "propose", to: "proposer", next: "review", prompt: "{ask}\n\nState exactly what you intend to do." },
      { id: "review", to: "guardian", next: { accept: "approved", reject: "propose", default: "propose" }, prompt: "A proposal is on the table:\n\n{reply}\n\nApprove it or block it." },
      { id: "approved", end: "resolved" },
    ],
  },
  trace: [
    { step: "propose", turn: 1, asked: ["builder"], stances: { builder: null }, stance: null, next: "review", at: iso(6) },
    { step: "review", turn: 2, asked: ["operator"], stances: { operator: "reject" }, stance: "reject", next: "propose", at: iso(3) },
  ],
};

// The other two built-in flows, and one a room wrote for itself, so the pane
// has every shape a flow can take: a fan-out in progress, a round-robin that
// finished, and a long branching one deep in its loops.
const checkoutFanOutEpisode: EpisodeSummary = {
  short_id: "a2b3c4",
  episode: OLD_FORM_THREAD,
  topic: "urn:concept:mycelium:checkout",
  outcome: "open",
  subkind: null,
  participants: ["operator", "builder", "reviewer", "conductor"],
  metrics: null,
  assignments: null,
  tasks: [],
  message_count: 4,
  updated_at: iso(4),
  updated_by: "conductor",
  within: OLD_FORM_THREAD,
  current_step: "combine",
  flow: {
    name: "fan-out",
    description: "A lead asks every worker at once, then combines what came back.",
    roles: ["lead"],
    max_steps: 6,
    bound: { lead: "operator" },
    cast: ["operator", "builder", "reviewer"],
    ask: "plan the test day: who tries which phones and which cards",
    steps: [
      { id: "gather", to: "workers", next: "combine", prompt: "{ask}\n\nAnswer with what you can contribute, what you would need, and any blocker you see." },
      { id: "combine", to: "lead", next: "done", prompt: "You asked the team: {ask}\n\nThey answered:\n{replies}\n\nCombine those into one plan." },
      { id: "done", end: "resolved" },
    ],
  },
  trace: [
    { step: "gather", turn: 1, asked: ["builder", "reviewer"], stances: { builder: null, reviewer: null }, stance: null, next: "combine", at: iso(5) },
  ],
};

// An earlier run in the launch thread, finished: the pane shows the latest run
// and reaches this one from its record.
const checkoutRoundRobinEpisode: EpisodeSummary = {
  short_id: "c7d8e9",
  episode: LAUNCH_THREAD,
  topic: "urn:concept:mycelium:checkout",
  outcome: "resolved",
  subkind: null,
  participants: ["builder", "reviewer", "operator", "conductor"],
  metrics: null,
  assignments: null,
  tasks: [],
  message_count: 8,
  updated_at: iso(40),
  updated_by: "conductor",
  within: LAUNCH_THREAD,
  current_step: null,
  flow: {
    name: "round-robin",
    description: "Every member speaks in turn, for a fixed number of rounds.",
    roles: [],
    max_steps: 12,
    bound: {},
    cast: ["builder", "reviewer", "operator"],
    ask: "should the old card form stay as a fallback during the sale, and for how long",
    steps: [
      { id: "round", to: "each", rounds: 2, next: "done", prompt: "Round {round} of {rounds}.\n\nThe question: {ask}" },
      { id: "done", end: "resolved" },
    ],
  },
  trace: [
    { step: "round", turn: 1, asked: ["builder", "reviewer", "operator"], stances: { builder: null, reviewer: null, operator: null }, stance: null, next: "round", at: iso(44) },
    { step: "round", turn: 2, asked: ["builder", "reviewer", "operator"], stances: { builder: "accept", reviewer: "accept", operator: "accept" }, stance: "accept", next: "done", at: iso(41) },
  ],
};

// A flow the room wrote for itself: ship Apple Pay as one release, with a
// security review, test orders and a sign-off, any of which can send it back.
const checkoutReleaseEpisode: EpisodeSummary = {
  short_id: "d4e5f6",
  episode: APPLE_PAY_THREAD,
  topic: "urn:concept:mycelium:checkout",
  outcome: "open",
  subkind: null,
  participants: ["builder", "reviewer", "operator", "conductor"],
  metrics: null,
  assignments: null,
  tasks: [],
  message_count: 14,
  updated_at: iso(1),
  updated_by: "conductor",
  within: APPLE_PAY_THREAD,
  current_step: "security",
  flow: {
    name: "release",
    description: "Plan with the team, pass a security review, place test orders, get sign-off; any block sends it back.",
    roles: ["lead", "guardian", "human", "tester"],
    max_steps: 24,
    bound: { lead: "builder", guardian: "reviewer", human: "operator", tester: "builder" },
    cast: ["builder", "reviewer", "operator"],
    ask: "ship Apple Pay as one release",
    steps: [
      { id: "triage", to: "lead", next: "plan", prompt: "{ask}\n\nSay what has to be true before this ships." },
      { id: "plan", to: "each", next: "combine", prompt: "{ask}\n\nWhat is your part, and what do you need?" },
      { id: "combine", to: "lead", next: "security", prompt: "The team said:\n{replies}\n\nCombine into one plan." },
      { id: "security", to: "guardian", next: { accept: "test-orders", reject: "revise", silent: "escalate", default: "revise" }, prompt: "Review the plan for anything that could leak card details or charge someone twice:\n{reply}" },
      { id: "revise", to: "lead", next: "security", prompt: "The review found a problem:\n{reply}\n\nFix the plan." },
      { id: "escalate", to: "human", next: { accept: "test-orders", reject: "abandoned", default: "escalate" }, prompt: "The review didn't answer. Go ahead anyway?" },
      { id: "test-orders", to: "tester", next: { accept: "signoff", reject: "rollback" }, prompt: "Place ten test orders on real phones and report." },
      { id: "signoff", to: "guardian", next: { accept: "shipped", reject: "rollback" }, prompt: "Test orders went through. Sign off?" },
      { id: "rollback", to: "tester", next: "revise", prompt: "Switch Apple Pay off and say what you saw." },
      { id: "shipped", end: "resolved" },
      { id: "abandoned", end: "rejected" },
    ],
  },
  trace: [
    { step: "triage", turn: 1, asked: ["builder"], stances: { builder: null }, stance: null, next: "plan", at: iso(30) },
    { step: "plan", turn: 2, asked: ["builder", "reviewer", "operator"], stances: { builder: null, reviewer: null, operator: null }, stance: null, next: "combine", at: iso(27) },
    { step: "combine", turn: 3, asked: ["builder"], stances: { builder: null }, stance: null, next: "security", at: iso(24) },
    { step: "security", turn: 4, asked: ["reviewer"], stances: { reviewer: "reject" }, stance: "reject", next: "revise", at: iso(21) },
    { step: "revise", turn: 5, asked: ["builder"], stances: { builder: null }, stance: null, next: "security", at: iso(18) },
    { step: "security", turn: 6, asked: ["reviewer"], stances: { reviewer: null }, stance: "silent", next: "escalate", at: iso(15) },
    { step: "escalate", turn: 7, asked: ["operator"], stances: { operator: "accept" }, stance: "accept", next: "test-orders", at: iso(12) },
    { step: "test-orders", turn: 8, asked: ["builder"], stances: { builder: "reject" }, stance: "reject", next: "rollback", at: iso(9) },
    { step: "rollback", turn: 9, asked: ["builder"], stances: { builder: null }, stance: null, next: "revise", at: iso(6) },
    { step: "revise", turn: 10, asked: ["builder"], stances: { builder: null }, stance: null, next: "security", at: iso(3) },
  ],
};

// "Help them agree" (concord) run on the double-charge decision: reviewer
// wants refunds automatic, builder wants support to check first, and Morgan
// is least happy with the first pick. Morgan's fix clears the bar for all
// three, and the run ends agreed. Scorecards and the close carry structured
// lines, so the thread draws them as tables and a result line.
const REFUND_THREAD = checkoutEpisode("a1c3e5");
const REFUND_CAST = ["builder", "reviewer", "operator"];
const refundOptions = [
  { label: "A", text: "Refund the second charge automatically, right away.", authors: ["reviewer"] },
  { label: "B", text: "Send every double charge to support to check before refunding.", authors: ["builder"] },
  {
    label: "C",
    text: "Refund automatically when the second charge is under $50; support checks anything larger within a day.",
    authors: ["operator"],
  },
];
const refundFirstPick = {
  outcome: "infeasible" as const,
  pick: "A",
  text: refundOptions[0].text,
  threshold: 70,
  options: refundOptions.slice(0, 2),
  table: {
    A: { builder: 60, reviewer: 90, operator: 40 },
    B: { builder: 80, reviewer: 35, operator: 75 },
  },
  cast: REFUND_CAST,
  ratings: { builder: 60, reviewer: 90, operator: 40 },
  lowest: 40,
  missing: [],
  least_happy: "operator",
};
const refundAgreed = {
  outcome: "feasible" as const,
  pick: "C",
  text: refundOptions[2].text,
  threshold: 70,
  options: refundOptions,
  table: { ...refundFirstPick.table, C: { builder: 78, reviewer: 85, operator: 88 } },
  cast: REFUND_CAST,
  ratings: { builder: 78, reviewer: 85, operator: 88 },
  lowest: 78,
  missing: [],
  least_happy: null,
};
const concordSteps: FlowStep[] = [
  { id: "propose", to: "all", collect: "options", next: "score" },
  { id: "score", to: "all", collect: "scores", next: "pick" },
  {
    id: "pick",
    kind: "select",
    threshold: 0.7,
    max_repairs: 2,
    next: { feasible: "agreed", infeasible: "repair", stuck: "no_deal" },
  },
  { id: "repair", to: "bottleneck", collect: "options", next: "rescore" },
  { id: "rescore", to: "all", collect: "scores", next: "pick" },
  { id: "agreed", end: "converged" },
  { id: "no_deal", end: "rejected" },
];
const checkoutConcordEpisode: EpisodeSummary = {
  short_id: "b9c1d3",
  episode: REFUND_THREAD,
  topic: "urn:concept:mycelium:checkout",
  outcome: "converged",
  subkind: "converged",
  participants: [...REFUND_CAST, "conductor"],
  // The summary carries the aligner's quality numbers only; a run's
  // satisfaction is in its record and on its close.
  metrics: null,
  assignments: { decision: refundOptions[2].text },
  tasks: [],
  message_count: 16,
  updated_at: iso(2.6),
  updated_by: "conductor",
  within: REFUND_THREAD,
  current_step: null,
  flow: {
    name: "concord",
    description:
      "Help them agree. Everyone suggests, everyone rates, the least happy agent suggests a fix, until one option clears the bar for all.",
    roles: [],
    max_steps: 9,
    bound: {},
    cast: REFUND_CAST,
    ask: "when someone is charged twice, refund it automatically or send it to support first?",
    steps: concordSteps,
  },
  trace: [
    { step: "propose", turn: 1, asked: REFUND_CAST, stances: {}, stance: null, next: "score", at: iso(5.2) },
    { step: "score", turn: 2, asked: REFUND_CAST, stances: {}, stance: null, next: "pick", at: iso(4.6) },
    {
      step: "pick",
      turn: 2,
      select: { outcome: "infeasible", pick: "A", lowest: 40, missing: [], least_happy: "operator" },
      next: "repair",
      at: iso(4.5),
    },
    { step: "repair", turn: 3, asked: ["operator"], stances: {}, stance: null, next: "rescore", at: iso(3.8) },
    { step: "rescore", turn: 4, asked: REFUND_CAST, stances: {}, stance: null, next: "pick", at: iso(2.8) },
    {
      step: "pick",
      turn: 4,
      select: { outcome: "feasible", pick: "C", lowest: 78, missing: [], least_happy: null },
      next: "agreed",
      at: iso(2.7),
    },
  ],
};

/** The run's posts in the decision's thread: the conductor's lines and what
 *  each member answered, oldest first. */
function refundThread(): MockMessage[] {
  let n = 0;
  const at = (mins: number) => iso(mins);
  const post = (sender: string, content: string, mins: number, conductor?: Record<string, unknown>): MockMessage => ({
    id: `cc${++n}`,
    sender_handle: sender,
    message_type: "broadcast",
    content,
    created_at: at(mins),
    episode: REFUND_THREAD,
    ...(conductor ? { metadata: { conductor } } : {}),
  });
  const turn = (step: string, to: string, turnNo: number, mins: number) =>
    post("conductor", `concord · ${step} · turn ${turnNo} of 9 · ${to}`, mins, {
      event: "turn",
      protocol: "concord",
      step,
      to,
      turn: turnNo,
      cap: 9,
    });
  return [
    post("conductor", "Running concord with builder, reviewer, operator as members.", 5.5, {
      event: "open",
      protocol: "concord",
      roles: {},
      members: REFUND_CAST,
      steps: concordSteps,
    }),
    ...REFUND_CAST.map((h) => turn("propose", h, 1, 5.4)),
    post("builder", "Send them to support first. Some double charges are two real orders, and refunding those loses money.", 5.3),
    post("reviewer", "Refund automatically, right away. The customer did nothing wrong and shouldn't have to wait.", 5.3),
    post("operator", "Refund automatically, right away.", 5.2),
    ...REFUND_CAST.map((h) => turn("score", h, 2, 5.0)),
    post("builder", "A risks refunding real repeat orders; B is safe but slow for the customer.", 4.8),
    post("reviewer", "B makes a customer wait on something that's our fault.", 4.7),
    post("operator", "A is right for small amounts but I'm not comfortable refunding big orders blind. B is slow.", 4.6),
    post("conductor", "pick: A, @operator at 40", 4.5, { event: "select", step: "pick", next: "repair", select: refundFirstPick }),
    turn("repair", "operator", 3, 4.4),
    post(
      "operator",
      "Refund automatically when the second charge is under $50; support checks anything larger within a day. Small ones are nearly always the button bug, and big ones are worth a look.",
      3.8,
    ),
    ...REFUND_CAST.map((h) => turn("rescore", h, 4, 3.6)),
    post("builder", "Most real repeat orders are over $50, so this covers my worry.", 3.2),
    post("reviewer", "Fast for nearly everyone, and a day is fine for the rest.", 3.0),
    post("operator", "This is what I'd sign off on.", 2.9),
    post("conductor", "pick: C, everyone at 70+", 2.7, { event: "select", step: "pick", next: "agreed", select: refundAgreed }),
    post("conductor", "✓ Everyone's on board: going with C.", 2.6, {
      event: "close",
      protocol: "concord",
      outcome: "converged",
      steps: 4,
      reason: "reached `agreed`",
      pick: "C",
      text: refundOptions[2].text,
    }),
  ];
}

// "Get on the same page" (accord) run on the payment-alerts task before the
// work starts: everyone says what the alert is for, what's out of scope and
// what done means, a second round adds nothing new, "failing" turns out to
// mean two things and is restated, and the points are merged into a shared
// summary saved as a memory. The counts, the summary and the close carry
// structured lines, so the thread draws them as lines rather than prose.
const ALERTS_THREAD = checkoutEpisode("e7a9c1");
const ALERTS_CAST = ["builder", "reviewer", "operator"];
const ALERTS_SUMMARY = "context/summary/payment-alerts";
const accordSteps: FlowStep[] = [
  { id: "frame", to: "all", collect: "pieces", require: "pieces", next: "added" },
  { id: "added", kind: "tally", of: "points", max_rounds: 3, next: { grew: "more", settled: "ground", empty: "nothing" } },
  { id: "more", to: "all", collect: "pieces", next: "added" },
  { id: "ground", to: "all", collect: "pieces", next: "words" },
  { id: "words", kind: "tally", of: "terms", max_rounds: 2, next: { contested: "restate", clear: "lock" } },
  { id: "restate", to: "contested", collect: "pieces", next: "words" },
  { id: "lock", kind: "lock", next: { locked: "locked", empty: "nothing" } },
  { id: "locked", end: "resolved" },
  { id: "nothing", end: "rejected" },
];
const alertsFirstCount = {
  of: "points" as const,
  round: 1,
  max_rounds: 3,
  outcome: "grew" as const,
  added: 5,
  points: 5,
  capped: false,
};
const alertsSecondCount = { ...alertsFirstCount, round: 2, outcome: "settled" as const, added: 0 };
const alertsWordsSplit = {
  of: "terms" as const,
  round: 1,
  max_rounds: 2,
  outcome: "contested" as const,
  words: 2,
  contested: ["failing"],
  asked: ["builder", "operator"],
};
const alertsWordsClear = { ...alertsWordsSplit, round: 2, outcome: "clear" as const, contested: [], asked: [] };
const alertsLock = {
  outcome: "locked" as const,
  memory: ALERTS_SUMMARY,
  saved: true,
  points: 5,
  shared: 3,
  contested: 0,
  checks: 1,
  flagged: 2,
  quiet: [],
};
const checkoutAccordEpisode: EpisodeSummary = {
  short_id: "c3e5a7",
  episode: ALERTS_THREAD,
  topic: "urn:concept:mycelium:checkout",
  outcome: "resolved",
  subkind: "resolved",
  participants: [...ALERTS_CAST, "conductor"],
  metrics: null,
  assignments: null,
  tasks: [],
  message_count: 22,
  updated_at: iso(3.4),
  updated_by: "conductor",
  within: ALERTS_THREAD,
  current_step: null,
  flow: {
    name: "accord",
    description:
      "Get on the same page. Everyone says what the task is, what's out of scope, what done means and what the key words mean; it's merged into one shared summary, with anything that doesn't line up flagged, and saved.",
    roles: [],
    max_steps: 8,
    bound: {},
    cast: ALERTS_CAST,
    ask: "agree what the payment alert is for before building it",
    steps: accordSteps,
  },
  trace: [
    { step: "frame", turn: 1, asked: ALERTS_CAST, stances: {}, stance: null, next: "added", at: iso(9.0) },
    { step: "added", turn: 1, tally: alertsFirstCount, next: "more", at: iso(8.9) },
    { step: "more", turn: 2, asked: ALERTS_CAST, stances: {}, stance: null, next: "added", at: iso(7.6) },
    { step: "added", turn: 2, tally: alertsSecondCount, next: "ground", at: iso(7.5) },
    { step: "ground", turn: 3, asked: ALERTS_CAST, stances: {}, stance: null, next: "words", at: iso(6.2) },
    { step: "words", turn: 3, tally: alertsWordsSplit, next: "restate", at: iso(6.1) },
    { step: "restate", turn: 4, asked: ["builder", "operator"], stances: {}, stance: null, next: "words", at: iso(4.4) },
    { step: "words", turn: 4, tally: alertsWordsClear, next: "lock", at: iso(4.3) },
    { step: "lock", turn: 4, lock: alertsLock, next: "locked", at: iso(3.5) },
  ],
};

/** The run's posts in the payment-alerts thread, oldest first. */
function alertsThread(): MockMessage[] {
  let n = 0;
  const post = (sender: string, content: string, mins: number, conductor?: Record<string, unknown>): MockMessage => ({
    id: `ac${++n}`,
    sender_handle: sender,
    message_type: "broadcast",
    content,
    created_at: iso(mins),
    episode: ALERTS_THREAD,
    ...(conductor ? { metadata: { conductor } } : {}),
  });
  const turn = (step: string, to: string, turnNo: number, mins: number) =>
    post("conductor", `accord · ${step} · turn ${turnNo} of 8 · ${to}`, mins, {
      event: "turn",
      protocol: "accord",
      step,
      to,
      turn: turnNo,
      cap: 8,
    });
  return [
    post("conductor", "Running accord with builder, reviewer, operator as members.", 9.6, {
      event: "open",
      protocol: "accord",
      roles: {},
      members: ALERTS_CAST,
      steps: accordSteps,
    }),
    ...ALERTS_CAST.map((h) => turn("frame", h, 1, 9.5)),
    post("builder", "It's for hearing about broken payments before customers do. Out of scope: alerts for slow pages. Done means the alert fires in a test where I make payments fail on purpose.", 9.3),
    post("reviewer", "It's for hearing about broken payments before customers do. Done means one message to the team channel, not one per failed payment.", 9.2),
    post("operator", "It's for catching a broken checkout during the sale. More than 3 failing payments in 10 minutes should alert us.", 9.1),
    post("conductor", "Round 1: 5 new points, 5 in all", 8.9, { event: "tally", step: "added", next: "more", tally: alertsFirstCount }),
    ...ALERTS_CAST.map((h) => turn("more", h, 2, 8.8)),
    post("builder", "Nothing to add.", 8.0),
    post("reviewer", "Nothing new from me.", 7.9),
    post("operator", "That covers it.", 7.8),
    post("conductor", "Nobody added anything new: 5 points", 7.5, { event: "tally", step: "added", next: "ground", tally: alertsSecondCount }),
    ...ALERTS_CAST.map((h) => turn("ground", h, 3, 7.4)),
    post("builder", "\"Failing\" means Stripe returned an error. \"The team channel\" is #checkout.", 6.8),
    post("reviewer", "\"The team channel\" is #checkout.", 6.6),
    post("operator", "\"Failing\" means the customer didn't get through checkout, whatever the reason.", 6.4),
    post("conductor", "Words used in different senses: failing. Asking builder, operator again", 6.1, {
      event: "tally",
      step: "words",
      next: "restate",
      tally: alertsWordsSplit,
    }),
    turn("restate", "builder", 4, 6.0),
    turn("restate", "operator", 4, 6.0),
    post("builder", "Fair: a card the bank declines is the customer's problem, not ours. \"Failing\" means Stripe returned an error.", 5.0),
    post("operator", "Agreed, a declined card isn't a broken checkout. \"Failing\" means Stripe returned an error.", 4.6),
    post("conductor", "No word used in different senses", 4.3, { event: "tally", step: "words", next: "lock", tally: alertsWordsClear }),
    post("conductor", "Shared summary: 5 points, 3 stated by more than one person, 1 check, 2 open items", 3.5, {
      event: "lock",
      step: "lock",
      next: "locked",
      lock: alertsLock,
    }),
    post(
      "conductor",
      `✓ accord: resolved after 4 step(s). 5 point(s), 3 stated by more than one person, 1 check(s). The shared summary is saved as ${ALERTS_SUMMARY}.`,
      3.4,
      { event: "close", protocol: "accord", outcome: "resolved", steps: 4, reason: "reached `locked`", memory: ALERTS_SUMMARY },
    ),
  ];
}

// Coordination-state memories the board projects into rows. Every one is what
// the docs promise a task is: a markdown file with frontmatter — prose in the
// body (`value`), the row's typed fields in `meta`. The board reads status,
// owner, priority, ci, pr, branch, blocks and choices from that frontmatter, the
// same keys a `memory set --meta` writes. And every row carries its own
// `episode`: a thread is per-item, minted when the row is, so each has one to
// open whether or not anyone has spoken in it yet. Together they give the board
// something in every attention filter (needs-you, in-flight, resolved) and a
// column for every inferred field, without any in-app demo layer.
const checkoutBoardRows: MockMemory[] = [
  // What the launch-day agreement compiled into. Two tasks from one negotiation
  // are two tasks with two threads, not two rows sharing the conversation that
  // produced them — so each carries its own episode, not the negotiation's.
  {
    key: "work/turn-on-apple-pay",
    value:
      "Turn on Apple Pay for everyone\n\n" +
      "Behind the `checkout.apple_pay` switch, off for now. Don't turn it on until the " +
      "test orders pass and @reviewer signs off. Waiting on the Apple Pay PR (#502).",
    meta: { "depends-on": ["work/add-apple-pay", "work/review-double-charge-fix"], kind: "action", status: "open", assignee: "@builder", priority: "high", issue: "#502" },
    content_text: "Turn on Apple Pay for everyone, behind a switch. Waiting on the test orders.",
    created_by: "aligner",
    updated_by: "aligner",
    version: 1,
    updated_at: iso(40),
    episode: LAUNCH_THREAD,
  },
  {
    key: "work/remove-old-card-form",
    value: "Remove the old card form after the sale",
    meta: { "depends-on": ["work/turn-on-apple-pay"], kind: "action", status: "open", assignee: "@builder", issue: "#499" },
    content_text: "Remove the old card form once Apple Pay has run clean through the sale.",
    created_by: "aligner",
    updated_by: "aligner",
    version: 1,
    updated_at: iso(40),
    episode: OLD_FORM_THREAD,
  },
  {
    key: "decisions/double-charge-refunds",
    value: "Double charges: refund automatically, or send to support first?",
    meta: {
      status: "open",
      kind: "decision",
      owner: null,
      priority: "urgent",
      choices: ["refund automatically", "send to support"],
      asked_by: "@reviewer",
      ttl_minutes: 120,
    },
    content_text: "When a customer is charged twice, do we refund the second charge automatically, or send it to support to check first? Nobody's called it yet.",
    created_by: "reviewer",
    updated_by: "reviewer",
    version: 1,
    updated_at: iso(6),
    episode: checkoutEpisode("a1c3e5"),
  },
  {
    key: "failed/test-on-real-iphone",
    value: "Test Apple Pay on a real iPhone",
    meta: {
      status: "blocked",
      kind: "blocked",
      owner: "@operator",
      priority: "high",
      blocked_by: ["#502"],
      issue: "#502",
    },
    content_text: "Can't test on a real phone until the Apple Pay PR is on staging (#502).",
    created_by: "operator",
    updated_by: "operator",
    version: 1,
    updated_at: iso(40),
    episode: checkoutEpisode("b4d6f8"),
  },
  {
    key: "work/review-double-charge-fix",
    value: "Review the double-charge fix (PR #504)",
    meta: { "depends-on": ["work/stripe-payments"],
      status: "in_review",
      kind: "review",
      owner: "@reviewer",
      priority: "high",
      pr: "#504",
      ci: "green",
      branch: "fix/double-charge",
      ttl_minutes: 720,
    },
    content_text: "PR #504 on fix/double-charge; CI green; wants a review.",
    created_by: "builder",
    updated_by: "builder",
    version: 1,
    updated_at: iso(12),
    episode: checkoutEpisode("c5e7a9"),
  },
  {
    key: "work/add-apple-pay",
    value: "Add Apple Pay to checkout",
    meta: { "depends-on": ["work/stripe-payments"],
      status: "in_progress",
      kind: "action",
      owner: "@builder",
      priority: "high",
      branch: "feat/apple-pay",
      pr: "#502",
      ci: "green",
      blocks: ["Turn on Apple Pay for everyone"],
    },
    content_text: "Adding Apple Pay to checkout on feat/apple-pay; PR #502; CI green.",
    created_by: "builder",
    updated_by: "builder",
    version: 2,
    updated_at: iso(12),
    episode: APPLE_PAY_THREAD,
  },
  {
    key: "work/payment-alerts",
    value: "Alert us when payments start failing",
    meta: { "depends-on": ["work/stripe-payments"],
      status: "in_progress",
      kind: "action",
      owner: "@operator",
      priority: "normal",
      branch: "feat/payment-alerts",
      ci: "running",
    },
    content_text: "A message to the team when more than 3 payments fail in 10 minutes, on feat/payment-alerts; CI running.",
    created_by: "operator",
    updated_by: "operator",
    version: 1,
    updated_at: iso(3),
    episode: checkoutEpisode("e7a9c1"),
  },
  {
    key: "failed/duplicate-order-emails",
    value: "Order emails go out twice when Stripe retries",
    meta: {
      status: "in_review",
      kind: "concern",
      owner: "@builder",
      priority: "normal",
      ci: "red",
      branch: "fix/duplicate-emails",
      ttl_minutes: 1440,
    },
    content_text: "Some customers get two order confirmation emails when Stripe retries a webhook; fix on fix/duplicate-emails; CI red.",
    created_by: "builder",
    updated_by: "builder",
    version: 1,
    updated_at: iso(55),
    episode: checkoutEpisode("f8b0d2"),
  },
  {
    key: "work/stripe-payments",
    value: "Move card payments to Stripe",
    meta: {
      status: "resolved",
      kind: "action",
      owner: "@builder",
      priority: "urgent",
      pr: "#499",
      ci: "green",
      ttl_minutes: 1440,
    },
    content_text: "Card payments now go through Stripe (PR #499).",
    created_by: "builder",
    updated_by: "builder",
    version: 2,
    updated_at: iso(62),
    episode: checkoutEpisode("a9c1e3"),
  },
  {
    key: "decisions/keep-old-card-form",
    value: "Keep the old card form as a fallback during the sale",
    meta: {
      status: "resolved",
      kind: "concern",
      owner: "@operator",
      priority: "normal",
      issue: "#468",
      promoted: true,
      ttl_minutes: 1440,
    },
    content_text: "Decided: keep the old card form working through the sale, so if Apple Pay breaks, people can still pay.",
    created_by: "operator",
    updated_by: "operator",
    version: 1,
    updated_at: iso(200),
    episode: checkoutEpisode("b0d2f4"),
  },
];

const checkout: RoomFixture = {
  room: {
    id: 1,
    name: "checkout",
    created_at: iso(60 * 26),
    is_public: true,
    is_persistent: true,
    mas_id: "mas_7c1e9a2b",
  },
  memories: [
    {
      key: "agents/builder",
      value: agentManifest("Writes the checkout code: Apple Pay and the double-charge fix."),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
      episode: checkoutEpisode("a2c4e6"),
    },
    {
      key: "agents/reviewer",
      value: agentManifest("Reviews checkout changes and places test orders on real phones."),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
      episode: checkoutEpisode("b3d5f7"),
    },
    {
      key: "agents/aligner",
      value: agentManifest("Helps members agree when they disagree.", "engine"),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
      episode: checkoutEpisode("c4e6a8"),
    },
    {
      key: "decisions/apple-pay-launch",
      value: "Turn Apple Pay on friday morning, after a day of test orders on real phones. Keep the old card form as a fallback through the sale.",
      content_text: "Turn Apple Pay on friday morning, after a day of test orders on real phones. Keep the old card form as a fallback through the sale.",
      created_by: "aligner",
      version: 3,
      updated_at: iso(41),
      episode: checkoutEpisode("e6a8c0"),
    },
    {
      key: "context/goal",
      value: "Make checkout faster and stop double charges before the spring sale.",
      content_text: "Make checkout faster and stop double charges before the spring sale.",
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 25),
      episode: checkoutEpisode("f7b9d1"),
    },
    {
      key: "status/this-week",
      value: "Stripe payments are live. Apple Pay is built; test orders thursday, switch it on friday morning.",
      content_text: "Stripe payments are live. Apple Pay is built; test orders thursday, switch it on friday morning.",
      created_by: "builder",
      version: 2,
      updated_at: iso(120),
      episode: checkoutEpisode("a8c0e2"),
    },
    {
      key: "context/briefing",
      value:
        "# Checkout: where we are\n\n" +
        "**Decision.** Apple Pay goes on friday morning, after a day of test orders. The old card form stays as a fallback through the sale.\n\n" +
        "**Status.** Stripe payments are live. Apple Pay is built and waiting on test orders. The double-charge fix is in review.\n\n" +
        "**Goal.** Make checkout faster and stop double charges before the spring sale.\n\n" +
        "_Owners:_ @builder writes the code; @reviewer reviews it and places test orders.",
      content_text:
        "Checkout briefing: Apple Pay on friday morning after test orders; Stripe live; double-charge fix in review.\n\n" +
        "The goal this all serves, embedded verbatim:\n\n![[context/goal]]",
      created_by: "operator",
      version: 1,
      updated_at: iso(38),
      episode: checkoutEpisode("b9d1f3"),
    },
    // The shared summary the payment-alerts run saved, as the hub writes it.
    {
      key: ALERTS_SUMMARY,
      value:
        "# Shared summary: Alert us when payments start failing\n\n" +
        "The ask: agree what the payment alert is for before building it\n\n" +
        "Worked out by builder, reviewer, operator.\n\n" +
        "## What it's for\n\n" +
        "- **p1** Hear about broken payments before customers do (stated by 3 of 3: builder, reviewer, operator)\n\n" +
        "## Constraints\n\n" +
        "- **p2** Alert when more than 3 payments fail in 10 minutes (stated by 1 of 3: operator)\n\n" +
        "## Out of scope\n\n" +
        "- **p3** Alerts for slow pages (stated by 1 of 3: builder)\n\n" +
        "## What gets delivered\n\n" +
        "- **p4** One message to #checkout, not one per failed payment (stated by 2 of 3: reviewer, builder)\n" +
        "- **p5** The alert fires in a test that makes payments fail on purpose (stated by 2 of 3: builder, operator)\n\n" +
        "## Words\n\n" +
        "- **failing**: Stripe returned an error; a card the bank declines is not a failure (builder, operator)\n" +
        "- **the team channel**: #checkout (builder, reviewer)\n\n" +
        "## How we'll check\n\n" +
        "- Make payments fail on purpose on staging and see one message in #checkout (builder; covers p4, p5)\n\n" +
        "## Open items\n\n" +
        "- Only one person said this: p2 (operator)\n" +
        "- Only one person said this: p3 (builder)\n",
      content_text: "Shared summary for the payment alert: what it's for, what's out of scope, what done means, and what failing means.",
      meta: { "part-of": ["work/payment-alerts"] },
      created_by: "conductor",
      updated_by: "conductor",
      version: 1,
      updated_at: iso(3.5),
      episode: checkoutEpisode("d1f3b5"),
    },
    ...checkoutBoardRows,
  ],
  // The channel is the room's whole history, so every row on the board is a thing
  // it once filed: the chat lines below set up each filing, and the task-created
  // notices in the `l9` feed are the filings themselves. Read top to bottom it is
  // one arc — set up the room, move payments to Stripe, build Apple Pay, broker
  // the launch day, file what it breaks into, then chase the double charges.
  messages: [
    // ── setting the room up, and the early work (a day ago) ──
    { id: "h1", sender_handle: "operator", message_type: "broadcast", content: "setting up checkout for the spring sale. two things: add apple pay, and stop the double charges. @builder @reviewer can you take the code and the testing?", created_at: iso(60 * 25) },
    { id: "h2", sender_handle: "builder", message_type: "broadcast", content: "on it. moving card payments to stripe first, apple pay is easier on top of that.", created_at: iso(1440) },
    { id: "h3", sender_handle: "builder", message_type: "broadcast", content: "stripe payments are merged (#499). starting on apple pay.", created_at: iso(1400) },
    // ── Apple Pay gets built, and the work hanging off it ──
    { id: "h4", sender_handle: "builder", message_type: "broadcast", content: "apple pay works in the simulator. it's up as #502 so it can go to staging.", created_at: iso(140) },
    { id: "h5", sender_handle: "reviewer", message_type: "broadcast", content: "i'll do the testing. i need it on staging to try real phones and real cards.", created_at: iso(130) },
    { id: "h6", sender_handle: "operator", message_type: "broadcast", content: "adding an alert for when payments start failing, so we hear about it before customers email us.", created_at: iso(95) },
    { id: "h7", sender_handle: "builder", message_type: "broadcast", content: "some order emails are going out twice when stripe retries a webhook. filing it, i'll fix it after apple pay.", created_at: iso(58) },
    // ── the test-first correction ──
    { id: "q1", sender_handle: "reviewer", message_type: "broadcast", content: "can we switch apple pay on before i've tried a real iphone? it passes in the simulator.", created_at: iso(52) },
    { id: "q2", sender_handle: "operator", message_type: "broadcast", content: "no. the simulator doesn't use real cards. if it breaks on a real phone during the sale we lose orders. test first.", created_at: iso(51) },
    { id: "q3", sender_handle: "reviewer", message_type: "broadcast", content: "fair. i'll test on staging and keep it switched off until then.", created_at: iso(50) },
    // ── the launch-day call ──
    { id: "a1", sender_handle: "operator", message_type: "broadcast", content: "@builder @reviewer we need a day to switch apple pay on. @aligner run it.", created_at: iso(48) },
    { id: "a2", sender_handle: "operator", message_type: "coordination_join", content: JSON.stringify({ handle: "operator", intent: "on before the sale email", episode: CHECKOUT_EPISODE }), created_at: iso(47), episode: CHECKOUT_EPISODE },
    { id: "a3", sender_handle: "builder", message_type: "coordination_join", content: JSON.stringify({ handle: "builder", intent: "a full day of test orders first", episode: CHECKOUT_EPISODE }), created_at: iso(47), episode: CHECKOUT_EPISODE },
    // The aligner brokers a couple of short rounds. Each reply is a chat
    // broadcast; the aligner reads it and emits the coordination_tick the Network
    // pane reconstructs. The chat is the source (see checkoutMoves).
    ...checkoutNegotiation,
    { id: "a6", sender_handle: "aligner", message_type: "coordination_consensus", content: JSON.stringify({ assignments: { launch: "friday am" }, episode: CHECKOUT_EPISODE, metrics: { gar: 0.79 } }), created_at: iso(41), episode: CHECKOUT_EPISODE },
    // The room files the work the call breaks into. The two task-created notices
    // land right after this line (see the `l9` feed below), so the chat reads
    // "here is the work" → the tasks, in sequence.
    { id: "file1", sender_handle: "aligner", message_type: "broadcast", content: "settled: test orders thursday, apple pay on friday morning. filing the work:", created_at: iso(40) },
    { id: "a7", sender_handle: "builder", message_type: "broadcast", content: "stripe has been live a full day. 312 orders, no failed payments.", created_at: iso(30) },
    // ── follow-on work ──
    { id: "h8", sender_handle: "builder", message_type: "broadcast", content: "the double-charge fix is up for review, #504.", created_at: iso(14) },
    { id: "h9", sender_handle: "reviewer", message_type: "broadcast", content: "one open question: when someone does get charged twice, do we refund it automatically or send it to support first? filing it.", created_at: iso(6) },
    // Two agents staging the "turn on Apple Pay" row talk inside its thread. The
    // channel does not carry this, so the room hears the pings below instead,
    // and the prose reads in the thread pane.
    { id: "t1", sender_handle: "builder", message_type: "broadcast", content: "apple pay is behind the `checkout.apple_pay` switch, off for now.", created_at: iso(22), episode: LAUNCH_THREAD },
    { id: "t2", sender_handle: "reviewer", message_type: "broadcast", content: "don't switch it on until i've placed test orders on a real phone. i'll post the results here.", created_at: iso(21), episode: LAUNCH_THREAD },
    { id: "t3", sender_handle: "builder", message_type: "broadcast", content: "sounds good, waiting on you.", created_at: iso(20), episode: LAUNCH_THREAD },
    // The old card form's own thread: a leftover chased down.
    { id: "r1", sender_handle: "builder", message_type: "broadcast", content: "12 orders last week still used the old card form after stripe went live. all from one cached page.", created_at: iso(16), episode: OLD_FORM_THREAD },
    { id: "r2", sender_handle: "builder", message_type: "broadcast", content: "cleared the cache. every order today went through stripe.", created_at: iso(15), episode: OLD_FORM_THREAD },
    // The double-charge decision's thread: a "help them agree" run, start to finish.
    ...refundThread(),
    // The payment-alerts thread: a "get on the same page" run before the work.
    ...alertsThread(),
    // Two deliberately long, multi-paragraph messages — the wall-of-text case the
    // channel has to handle without swallowing everything around it.
    {
      id: "long1",
      sender_handle: "builder",
      message_type: "broadcast",
      created_at: iso(13),
      content:
        "Here's what was causing the double charges, so it's written down somewhere.\n\n" +
        "What happened: when the Pay button is slow to respond, some people click it again. Each click sent its own payment request, and Stripe charged both. It only happens when the page takes more than a second or two, which is why we mostly saw it on phones with a weak signal. 23 customers were charged twice in the last month.\n\n" +
        "The fix (#504): every checkout now gets one payment ID when the page loads, and every click sends that same ID. Stripe sees the second request is the same payment and returns the first result instead of charging again. The Pay button also greys out after the first click, but the ID is what actually stops the charge.\n\n" +
        "What I checked: I clicked Pay five times as fast as I could on a slowed-down connection, on a laptop and on a phone. One charge every time. I also refunded the 23 double charges from last month and sent each of those customers a short apology.\n\n" +
        "What's left: this should go out before Apple Pay, since Apple Pay uses the same button. @reviewer has it for review.",
    },
    {
      id: "long2",
      sender_handle: "operator",
      message_type: "broadcast",
      created_at: iso(11),
      content:
        "Thanks, this is exactly what I wanted. Two follow-ups and then a decision.\n\n" +
        "First: can we get an alert if one order is ever charged twice again? The fix should stop it, but I'd rather hear about it from an alert than from a customer.\n\n" +
        "Second: the apology is good. Can we add a 10% code to it? Being charged twice is a bad experience, and I want those people back for the sale.\n\n" +
        "Decision: the fix goes out thursday, before Apple Pay, like builder said. If it isn't reviewed by thursday afternoon, Apple Pay waits for it. I'd rather launch a day late than launch with a known double-charge bug. Filing both follow-ups now.",
    },
  ],
  episodes: [
    checkoutReleaseEpisode,
    checkoutGatedEpisode,
    checkoutConcordEpisode,
    checkoutAccordEpisode,
    checkoutFanOutEpisode,
    checkoutEpisodeSummary,
    checkoutRoundRobinEpisode,
  ],
  episodeDetails: {
    b9c1d3: { ...checkoutConcordEpisode, messages: [] },
    c3e5a7: { ...checkoutAccordEpisode, messages: [] },
    e4f1a2: { ...checkoutEpisodeSummary, messages: checkoutMessageChain },
    f10a2c: { ...checkoutGatedEpisode, messages: [] },
    a2b3c4: { ...checkoutFanOutEpisode, messages: [] },
    c7d8e9: { ...checkoutRoundRobinEpisode, messages: [] },
    d4e5f6: { ...checkoutReleaseEpisode, messages: [] },
  },
  // The floors the running flows hold on their tasks' threads: each names the
  // task, and the member each run is waiting on.
  floors: [
    { thread: "f1a5c7", episode: LAUNCH_THREAD, key: "work/turn-on-apple-pay", title: "Turn on Apple Pay for everyone", holder: "conductor", speakers: ["builder"] },
    { thread: "d2b8e0", episode: OLD_FORM_THREAD, key: "work/remove-old-card-form", title: "Remove the old card form after the sale", holder: "conductor", speakers: ["operator"] },
    { thread: "d6f8b0", episode: APPLE_PAY_THREAD, key: "work/add-apple-pay", title: "Add Apple Pay to checkout", holder: "conductor", speakers: ["reviewer"] },
  ],
  // builder holds an open SLIM socket; reviewer is present on a server-held
  // await lease. Both are agents in the roster, so the board projects a resident
  // row for each — the presence signal that a live SLIM node would otherwise supply.
  presence: [
    { handle: "builder", kind: "slim", last_seen: null },
    { handle: "reviewer", kind: "lease", last_seen: iso(1) },
  ],
  // Every board row's origin, as the notice the room filed it with — each timed
  // just after the chat line that sets it up, so the channel reads talk → filing
  // for all ten, not just the two the negotiation compiled. The episode on each
  // matches its board row, so a notice opens the same thread the row's chip does.
  wire: [
    ...checkoutWireFrames,
    // Every board row's origin — a `filed` notice — and, for two of them, the rest
    // of the lifecycle the room saw: Stripe payments resolved long ago, the
    // Apple Pay switch claimed by builder just before staging it. Read in order
    // it is filed → claimed → activity → resolved, the whole arc of a task.
    checkoutNotice("filed", "decisions/keep-old-card-form", "Keep the old card form as a fallback during the sale", checkoutEpisode("b0d2f4"), "operator", 1439.8, "decision"),
    checkoutNotice("filed", "work/stripe-payments", "Move card payments to Stripe", checkoutEpisode("a9c1e3"), "builder", 1399.8, "action"),
    checkoutNotice("resolved", "work/stripe-payments", "Move card payments to Stripe", checkoutEpisode("a9c1e3"), "builder", 1200),
    checkoutNotice("filed", "work/add-apple-pay", "Add Apple Pay to checkout", APPLE_PAY_THREAD, "builder", 139.8, "action"),
    checkoutNotice("filed", "failed/test-on-real-iphone", "Test Apple Pay on a real iPhone", checkoutEpisode("b4d6f8"), "operator", 129.8, "blocked"),
    checkoutNotice("blocked", "failed/test-on-real-iphone", "Test Apple Pay on a real iPhone", checkoutEpisode("b4d6f8"), "operator", 128),
    checkoutNotice("filed", "work/payment-alerts", "Alert us when payments start failing", checkoutEpisode("e7a9c1"), "operator", 94.8, "action"),
    checkoutNotice("filed", "failed/duplicate-order-emails", "Order emails go out twice when Stripe retries", checkoutEpisode("f8b0d2"), "builder", 57.8, "concern"),
    // The two the launch-day call compiled, filed by the aligner right after its
    // "filing the work" line (iso(40)).
    checkoutNotice("filed", "work/turn-on-apple-pay", "Turn on Apple Pay for everyone", LAUNCH_THREAD, "aligner", 39.9, "action", "@builder"),
    checkoutNotice("filed", "work/remove-old-card-form", "Remove the old card form after the sale", OLD_FORM_THREAD, "aligner", 39.8, "action", "@builder"),
    checkoutNotice("filed", "work/review-double-charge-fix", "Review the double-charge fix (PR #504)", checkoutEpisode("c5e7a9"), "builder", 13.8, "review"),
    checkoutNotice("filed", "decisions/double-charge-refunds", "Double charges: refund automatically, or send to support first?", checkoutEpisode("a1c3e5"), "reviewer", 5.8, "decision"),
    // builder takes the Apple Pay switch row before staging it, then the thread moves.
    checkoutNotice("claimed", "work/turn-on-apple-pay", "Turn on Apple Pay for everyone", LAUNCH_THREAD, "builder", 23),
    checkoutPing("t2", "reviewer", 21),
    checkoutPing("t3", "builder", 20),
  ],
  // Three work rows name pull requests; the hub resolved them. The first row
  // mentions two, one green and one failing, so it shows the failing one and says
  // there was another. The shapes are GitHub's own wording.
  status: {
    room: "checkout",
    field: "upstream",
    providers: ["github"],
    refs: [
      {
        ref: "github:pull_request:coffee-shop/web#502",
        provider: "github", kind: "pull_request", id: "coffee-shop/web#502",
        url: "https://github.com/coffee-shop/web/pull/502",
        freshness: "fresh", state: "failed", label: "CI failing",
        age_seconds: 95, error: null,
        origins: ["memory:work/turn-on-apple-pay"],
      },
      {
        ref: "github:pull_request:coffee-shop/web#504",
        provider: "github", kind: "pull_request", id: "coffee-shop/web#504",
        url: "https://github.com/coffee-shop/web/pull/504",
        freshness: "fresh", state: "ok", label: "approved",
        age_seconds: 95, error: null,
        origins: ["memory:work/turn-on-apple-pay"],
      },
      {
        ref: "github:pull_request:coffee-shop/web#499",
        provider: "github", kind: "pull_request", id: "coffee-shop/web#499",
        url: "https://github.com/coffee-shop/web/pull/499",
        freshness: "stale", state: "blocked", label: "changes requested",
        age_seconds: 5400, error: null,
        origins: ["memory:work/remove-old-card-form"],
      },
    ],
    rows: {
      "memory:work/turn-on-apple-pay": [
        "github:pull_request:coffee-shop/web#502",
        "github:pull_request:coffee-shop/web#504",
      ],
      "memory:work/remove-old-card-form": ["github:pull_request:coffee-shop/web#499"],
    },
    refreshing: false,
  },
};

// The briefing links out to the three memories it summarizes; the decision
// itself relates to the goal and wikilinks a memory that doesn't exist (so it
// can't resolve) — a deliberate broken-link example. The `agents/*` manifests
// and the briefing itself are never linked *to*, so they render as roots
// (inbound=0, outbound>0) in the graph — entry points with no referrers yet
// (#599's graph and #611's rail integrity banner agree on this by construction,
// since both read the same edge list).
const CHECKOUT_LINK_EDGES: MemoryGraphEdge[] = [
  // The order of the work: each row waits on the ones before it, so the board
  // reads "after …" on the rows still blocked and the graph draws the pipeline
  // Stripe → Apple Pay + the double-charge fix → switch it on → remove the old form.
  { source: "work/add-apple-pay", target: "work/stripe-payments", kind: "relation", relation: "depends-on", resolved: true },
  { source: "work/payment-alerts", target: "work/stripe-payments", kind: "relation", relation: "depends-on", resolved: true },
  { source: "work/review-double-charge-fix", target: "work/stripe-payments", kind: "relation", relation: "depends-on", resolved: true },
  { source: "work/turn-on-apple-pay", target: "work/add-apple-pay", kind: "relation", relation: "depends-on", resolved: true },
  { source: "work/turn-on-apple-pay", target: "work/review-double-charge-fix", kind: "relation", relation: "depends-on", resolved: true },
  { source: "work/remove-old-card-form", target: "work/turn-on-apple-pay", kind: "relation", relation: "depends-on", resolved: true },
  { source: "context/briefing", target: "decisions/apple-pay-launch", kind: "wikilink", resolved: true },
  { source: "context/briefing", target: "status/this-week", kind: "wikilink", resolved: true },
  { source: "context/briefing", target: "context/goal", kind: "transclusion", resolved: true },
  { source: "status/this-week", target: "decisions/apple-pay-launch", kind: "wikilink", resolved: true },
  { source: "decisions/apple-pay-launch", target: "context/goal", kind: "relation", relation: "depends-on", resolved: true },
  { source: "decisions/apple-pay-launch", target: "work/launch-checklist", kind: "wikilink", resolved: false, error: "not_found" },
];
checkout.links = buildMockGraph(checkout.memories, CHECKOUT_LINK_EDGES);

// ── subscription-pricing: an in-progress negotiation, nothing compiled yet ────

const pricingEpisode = (shortId: string): string =>
  `urn:ioc:mycelium:episode:subscription-pricing:${shortId}`;

const PRICING_EPISODE = pricingEpisode("b2d0");

const pricing: RoomFixture = {
  room: {
    id: 2,
    name: "subscription-pricing",
    created_at: iso(180),
    is_public: true,
    is_persistent: true,
    mas_id: "mas_31ab77c0",
  },
  memories: [
    { key: "agents/finance", value: agentManifest("Keeps an eye on the margin on every bag we ship."), created_by: "operator", version: 1, updated_at: iso(160), episode: pricingEpisode("c0e2a4") },
    { key: "agents/growth", value: agentManifest("Wants more subscribers; favors a low price to start."), created_by: "operator", version: 1, updated_at: iso(160), episode: pricingEpisode("d1f3b5") },
    { key: "agents/aligner", value: agentManifest("Helps members agree when they disagree.", "engine"), created_by: "operator", version: 1, updated_at: iso(160), episode: pricingEpisode("e2a4c6") },
    { key: "agents/market-prices", value: a2aManifest("What other coffee subscriptions charge.", "https://market-prices.example", ["prices", "compare"]), created_by: "operator", version: 1, updated_at: iso(30), episode: pricingEpisode("a4c6e8") },
    { key: "context/goal", value: "Pick a price for the monthly coffee subscription.", content_text: "Pick a price for the monthly coffee subscription.", created_by: "operator", version: 1, updated_at: iso(175), episode: pricingEpisode("b5d7f9") },
    {
      key: "context/costs",
      value:
        "# What a subscription costs us\n\n" +
        "Two 12oz bags a month.\n\n" +
        "- Beans: $7.40\n- Bags and labels: $1.10\n- Shipping: $4.80\n\n" +
        "**Total: $13.30 a month.** Anything under $22 puts us below a 40% margin.",
      content_text: "Two bags a month costs us $13.30 with shipping. Under $22 is below a 40% margin.",
      created_by: "finance",
      version: 1,
      updated_at: iso(150),
      episode: pricingEpisode("c6e8a0"),
    },
  ],
  messages: [
    { id: "p1", sender_handle: "operator", message_type: "broadcast", content: "@finance @growth what should the monthly subscription cost? @aligner help them agree.", created_at: iso(12) },
    { id: "p2", sender_handle: "finance", message_type: "coordination_join", content: JSON.stringify({ handle: "finance", intent: "margin at or above 40%", episode: PRICING_EPISODE }), created_at: iso(11), episode: PRICING_EPISODE },
    { id: "p3", sender_handle: "growth", message_type: "coordination_join", content: JSON.stringify({ handle: "growth", intent: "500 subscribers by summer", episode: PRICING_EPISODE }), created_at: iso(11), episode: PRICING_EPISODE },
    { id: "p4", sender_handle: "finance", message_type: "broadcast", content: "$24 a month for two bags keeps us at 40%.", created_at: iso(9) },
    // The thread on an agent manifest. Every memory carries one, this one
    // included, so "why is this bridge flaky" has somewhere to live that is
    // attached to the bridge rather than scrolling past in the channel.
    { id: "p5", sender_handle: "growth", message_type: "broadcast", content: "@market-prices didn't answer the compare call again, third time this week. Is it limiting us?", created_at: iso(8), episode: pricingEpisode("a4c6e8") },
    { id: "p6", sender_handle: "operator", message_type: "broadcast", content: "It answers `prices` fine and fails `compare`. We reach it over plain HTTPS, so a slow answer looks like no answer here. Let's give it a longer timeout before we switch services.", created_at: iso(7), episode: pricingEpisode("a4c6e8") },
  ],
  episodes: [
    {
      short_id: "b2d0",
      episode: PRICING_EPISODE,
      topic: "urn:concept:mycelium:subscription-pricing",
      outcome: "open",
      subkind: null,
      participants: ["finance", "growth", "aligner"],
      metrics: null,
      assignments: null,
      tasks: [],
      message_count: 4,
      updated_at: iso(9),
      updated_by: "aligner",
    },
  ],
  episodeDetails: {},
  // The bridge state to design against: one external A2A agent consulted during
  // the negotiation (one answered call, one dead one), and the room's own card
  // having been read from outside.
  a2a: {
    room: "subscription-pricing",
    agents: [
      {
        handle: "market-prices",
        description: "What other coffee subscriptions charge.",
        card: "https://market-prices.example",
        endpoint: "https://market-prices.example/a2a",
        skills: ["prices", "compare"],
        calls_ok: 2,
        calls_failed: 1,
        last_call_at: iso(8),
        proxied: true,
      },
    ],
    exchanges: [
      {
        id: "a2a-1",
        handle: "market-prices",
        direction: "outbound",
        status: "ok",
        at: iso(10),
        endpoint: "https://market-prices.example/a2a",
        peer: "finance",
        prompt: "@finance: what do other coffee subscriptions charge a month for two bags?",
        reply: "Most charge $18 to $26 a month for two bags. The middle is $22.",
        detail: null,
        duration_ms: 812,
      },
      {
        id: "a2a-2",
        handle: "a2a-guest",
        direction: "inbound",
        status: "ok",
        at: iso(9),
        endpoint: null,
        peer: null,
        prompt: "A partner cafe asks: can they offer the subscription to their own customers at a discount?",
        reply: "Delivered to room 'subscription-pricing'.",
        detail: null,
        duration_ms: null,
      },
      {
        id: "a2a-3",
        handle: "market-prices",
        direction: "outbound",
        status: "error",
        at: iso(8),
        endpoint: "https://market-prices.example/a2a",
        peer: "growth",
        prompt: "@growth: how many people cancel at $18 a month compared to $24?",
        reply: "",
        detail: "send failed: timeout after 120s",
        duration_ms: 120_004,
      },
    ],
    outbound_ok: 2,
    outbound_failed: 1,
    exposure: {
      card_url: "http://localhost:8000/api/rooms/subscription-pricing/.well-known/agent-card.json",
      rpc_url: "http://localhost:8000/api/rooms/subscription-pricing/a2a",
      skills: [],
      card_fetches: 4,
      messages: 1,
      last_card_fetch_at: iso(9),
      last_message_at: iso(9),
    },
  },
};

// ── scratch: a brand-new empty room ───────────────────────────────────────────

const scratch: RoomFixture = {
  // Someone's own room: listed only for its owner.
  room: {
    id: 3,
    name: "scratch",
    created_at: iso(4),
    is_public: false,
    is_persistent: true,
    mas_id: null,
    owner: "operator",
    members: [],
  },
  memories: [],
  messages: [],
  episodes: [],
  episodeDetails: {},
};

// ── storefront: the room as it actually reads under load ──────────────────────
//
// The shop's website room the week before the sale: a dozen people, each with a
// few agents working one ticket apiece. In ninety minutes the channel carried 76
// system lines and three sentences anyone said. That is the shape the activity
// design has to survive, so it is the shape the mock serves.

const STOREFRONT_LIVE = "urn:ioc:mycelium:episode:storefront:live";
function storefrontEpisode(short: string): string {
  return `urn:ioc:mycelium:episode:storefront:${short}`;
}

const storefrontMemories: MockMemory[] = [
  {
    key: "work/412-product-photos-load-slowly-on-phones",
    value: "412: product photos load slowly on phones",
    meta: { kind: "action", status: "in_progress", owner: "@fix-412", assignment: "held", ttl_minutes: 1440 },
    created_by: "fix-412",
    version: 3,
    updated_at: iso(63),
    episode: storefrontEpisode("t412"),
  },
  {
    key: "work/418-add-a-gift-message-to-orders",
    value: "418: add a gift message to orders",
    meta: { kind: "action", status: "in_progress", owner: "@task-418", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-418",
    version: 3,
    updated_at: iso(62),
    episode: storefrontEpisode("t418"),
  },
  {
    key: "work/421-password-reset-link-doesnt-work",
    value: "421: the password reset link doesn't work",
    meta: { kind: "action", status: "in_progress", owner: "@fix-421", assignment: "held", ttl_minutes: 1440 },
    created_by: "fix-421",
    version: 3,
    updated_at: iso(68),
    episode: storefrontEpisode("t421"),
  },
  {
    key: "work/426-show-which-coffees-are-back-in-stock",
    value: "426: show which coffees are back in stock",
    meta: { kind: "action", status: "in_progress", owner: "@task-426", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-426",
    version: 3,
    updated_at: iso(67),
    episode: storefrontEpisode("t426"),
  },
  {
    key: "work/427-search-doesnt-find-decaf",
    value: "427: search doesn't find \"decaf\"",
    meta: { kind: "action", status: "in_progress", owner: "@task-427", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-427",
    version: 3,
    updated_at: iso(60),
    episode: storefrontEpisode("t427"),
  },
  {
    key: "work/428-shipping-to-canada-costs-too-much",
    value: "428: shipping to Canada shows the wrong price",
    meta: { kind: "action", status: "in_progress", owner: "@task-428", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-428",
    version: 3,
    updated_at: iso(6),
    episode: storefrontEpisode("t428"),
  },
  {
    key: "work/429-reviews-show-the-wrong-star-count",
    value: "429: reviews show the wrong star count",
    meta: { kind: "action", status: "in_progress", owner: "@task-429", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-429",
    version: 3,
    updated_at: iso(63),
    episode: storefrontEpisode("t429"),
  },
  {
    key: "agents/fix-412",
    value: agentManifest("Working on 412: product photos load slowly on phones.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(75),
    episode: storefrontEpisode("a412ff"),
  },
  {
    key: "agents/task-418",
    value: agentManifest("Working on 418: gift messages on orders.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(79),
    episode: storefrontEpisode("a418ff"),
  },
  {
    key: "agents/task-426",
    value: agentManifest("Working on 426: back-in-stock labels.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(86),
    episode: storefrontEpisode("a426ff"),
  },
  {
    key: "agents/task-427",
    value: agentManifest("Working on 427: search for decaf.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(81),
    episode: storefrontEpisode("a427ff"),
  },
  {
    key: "agents/task-428",
    value: agentManifest("Working on 428: shipping to Canada.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(80),
    episode: storefrontEpisode("a428ff"),
  },
  {
    key: "agents/task-429",
    value: agentManifest("Working on 429: review stars.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(80),
    episode: storefrontEpisode("a429ff"),
  },
];

// The room at true scale: a dozen people each fielding a few one-ticket agents,
// plus the aligner and a bridged agent. The Members rail has to stay legible at
// three dozen agents and a dozen owners, and the Memory tree has to survive as
// many `agents/*` manifests plus the work they file. That pressure is the design
// target, so the fixture carries it.

// The humans fielding the agents. Agents are handed out round-robin across them
// so the People group fills the way a busy shared room's does — many owners,
// each running a few agents — rather than the single-operator degenerate case.
const STOREFRONT_PEOPLE = [
  "operator@example.com",
  "june@example.com",
  "kesh@example.com",
  "milo@example.com",
  "priya@example.com",
  "dre@example.com",
  "sol@example.com",
  "wen@example.com",
  "tomas@example.com",
  "ada@example.com",
  "nour@example.com",
  "bex@example.com",
];

interface StorefrontAgent {
  handle: string;
  description: string;
  adapter?: string;
  minsAgo: number;
}

// The one-ticket agents beyond the seven already wired into the notices below.
// Handles follow the pattern a team falls into: a `task-NNN`/`fix-NNN` per
// ticket, plus a few named for what they do.
const storefrontExtraAgents: StorefrontAgent[] = [
  { handle: "fix-421", description: "Working on 421: the password reset link.", minsAgo: 82 },
  { handle: "newsletter-copy", description: "Write the spring sale newsletter.", minsAgo: 300 },
  { handle: "mobile-menu-fix", description: "Fix the menu that won't close on phones.", minsAgo: 620 },
  { handle: "remove-popup", description: "Remove the discount popup on the first visit.", minsAgo: 410 },
  { handle: "grind-guide", description: "Add a grind size guide to every product page.", minsAgo: 355 },
  { handle: "shipping-faq", description: "Update the shipping FAQ with the new rates.", minsAgo: 240 },
  { handle: "fix-431", description: "Cart forgets items after logging in (#431).", minsAgo: 190 },
  { handle: "fix-433", description: "Order history is blank for older accounts (#433).", minsAgo: 175 },
  { handle: "fix-435", description: "Discount codes only work in capitals (#435).", minsAgo: 160 },
  { handle: "task-436", description: "Show the roast date on product pages.", minsAgo: 145 },
  { handle: "task-437", description: "Add a \"tell me when it's back\" button to sold-out coffees.", minsAgo: 130 },
  { handle: "task-439", description: "Let people sort the shop by roast level.", minsAgo: 120 },
  { handle: "task-440", description: "Translate checkout into French.", minsAgo: 110 },
  { handle: "task-442", description: "Add alt text to every product photo.", minsAgo: 95 },
  { handle: "task-443", description: "Make the home page load faster on slow connections.", minsAgo: 88 },
  { handle: "task-445", description: "Let subscribers skip a month.", minsAgo: 84 },
  { handle: "task-446", description: "Attach a PDF receipt to order emails.", minsAgo: 72 },
  { handle: "task-448", description: "Add a map of partner cafes.", minsAgo: 66 },
  { handle: "task-449", description: "Show tax before the last checkout step.", minsAgo: 58 },
  { handle: "task-451", description: "Fix the broken links in the footer.", minsAgo: 44 },
  { handle: "task-452", description: "Add a form for cafes that want to buy wholesale.", minsAgo: 33 },
  { handle: "task-454", description: "Shrink product photos when they're uploaded.", minsAgo: 21 },
  { handle: "fix-455", description: "Newsletter sign-up subscribes people twice.", minsAgo: 14 },
  { handle: "fix-456", description: "Gift cards show the wrong balance.", minsAgo: 9 },
  { handle: "task-458", description: "Add dark mode to the account pages.", minsAgo: 6 },
  { handle: "task-459", description: "Write descriptions for the three new single origins.", minsAgo: 4 },
  { handle: "task-461", description: "Put the sale banner on the home page.", minsAgo: 3 },
  { handle: "task-462", description: "Check every page still works on an old iPhone.", minsAgo: 2 },
  { handle: "aligner", description: "Helps members agree when they disagree.", adapter: "engine", minsAgo: 500 },
];

const storefrontExtraAgentMemories: MockMemory[] = storefrontExtraAgents.map((a, i) => ({
  key: `agents/${a.handle}`,
  value: agentManifest(
    a.description,
    a.adapter ?? "claude_code",
    a.adapter === "engine" ? undefined : STOREFRONT_PEOPLE[i % STOREFRONT_PEOPLE.length],
  ),
  created_by: a.adapter === "engine" ? "operator" : "claude-web",
  version: 1,
  updated_at: iso(a.minsAgo),
  episode: storefrontEpisode(`x${a.handle}`),
}));

// A bridged external agent, so the roster's "Services" group is not just engines.
storefrontExtraAgentMemories.push({
  key: "agents/shipping-rates",
  value: a2aManifest("Live shipping prices from the carrier.", "https://shipping-rates.example", ["quote"]),
  created_by: "operator",
  version: 1,
  updated_at: iso(700),
  episode: storefrontEpisode("xrates"),
});

// The non-`agents/` memories the room produced — decisions, context, status,
// a couple of promoted skills, and a parked failure — so the Memory tree has
// every namespace a real room grows, not just `work/` and `agents/`.
const storefrontExtraMemories: MockMemory[] = [
  {
    key: "context/goal",
    value: "Get the website ready for the spring sale.",
    content_text: "Get the website ready for the spring sale.",
    created_by: "operator",
    version: 1,
    updated_at: iso(60 * 90),
    episode: storefrontEpisode("cgoal"),
  },
  {
    key: "context/house-style",
    value: "Write the way we talk to customers: short sentences, no jargon. Every product photo gets alt text.",
    content_text: "Short sentences, no jargon. Every product photo gets alt text.",
    created_by: "operator",
    version: 4,
    updated_at: iso(60 * 40),
    episode: storefrontEpisode("cstyle"),
  },
  {
    key: "context/briefing",
    value:
      "# Storefront: where we are\n\n" +
      "**Focus.** Getting the site ready for the spring sale.\n\n" +
      "**In progress.** Back-in-stock labels (426), search for decaf (427), shipping to Canada (428).\n\n" +
      "**Done.** Password reset links (421), review stars (429), product photos on phones (412).",
    content_text:
      "Storefront briefing: getting ready for the sale. In progress: stock labels, decaf search, Canada shipping. Done: password reset, review stars, photos on phones.",
    created_by: "operator",
    version: 1,
    updated_at: iso(40),
    episode: storefrontEpisode("cbrief"),
  },
  {
    key: "decisions/sale-banner",
    value: "The sale banner goes on the home page only, not on every page.",
    content_text: "Sale banner on the home page only.",
    created_by: "operator",
    version: 1,
    updated_at: iso(128),
    episode: storefrontEpisode("dbanner"),
  },
  {
    key: "decisions/free-shipping",
    value: "Free shipping on orders over $40 during the sale, US only.",
    content_text: "Free shipping over $40 during the sale, US only.",
    created_by: "operator",
    version: 1,
    updated_at: iso(118),
    episode: storefrontEpisode("dship"),
  },
  {
    key: "decisions/no-popups",
    value: "No popups during the sale. The banner is enough.",
    content_text: "No popups during the sale.",
    created_by: "operator",
    version: 1,
    updated_at: iso(112),
    episode: storefrontEpisode("dpopup"),
  },
  {
    key: "status/this-week",
    value: "Working through the sale list. Search (427) matters most: people search for decaf more than anything else.",
    content_text: "Working through the sale list; decaf search matters most.",
    created_by: "operator@example.com",
    version: 6,
    updated_at: iso(8),
    episode: storefrontEpisode("sweek"),
  },
  {
    key: "skills/take-a-task",
    value:
      "---\ndescription: Take a task off the board, work it in its own thread, resolve it.\n---\n\n" +
      "Claim an open `work/` row, talk it through in its thread, and resolve it when the change is live.",
    content_text: "Take a task off the board, work it in its thread, resolve it.",
    created_by: "operator",
    version: 2,
    updated_at: iso(60 * 30),
    episode: storefrontEpisode("sktask"),
  },
  {
    key: "skills/product-photos",
    value:
      "---\ndescription: Get a product photo ready for the shop.\n---\n\n" +
      "1600px wide, WebP, under 200KB, with alt text that says what's in the bag.",
    content_text: "Resize and compress a product photo, and write its alt text.",
    created_by: "operator",
    version: 1,
    updated_at: iso(60 * 28),
    episode: storefrontEpisode("skphoto"),
  },
  {
    key: "failed/search-first-try",
    value: "The first try at fixing search matched \"decaf\" to every coffee. Parked; see 427.",
    meta: { kind: "concern", status: "blocked", owner: "@task-427", blocked_by: ["#427"] },
    content_text: "First search fix matched decaf to everything. Parked.",
    created_by: "task-427",
    version: 1,
    updated_at: iso(70),
    episode: storefrontEpisode("fsearch"),
  },
];

const storefrontWire: Record<string, unknown>[] = [
  storefrontNotice("filed", "work/426-show-which-coffees-are-back-in-stock", "426: show which coffees are back in stock", "task-426", 86),
  storefrontNotice("claimed", "work/426-show-which-coffees-are-back-in-stock", "426: show which coffees are back in stock", "task-426", 86),
  storefrontPing("work/426-show-which-coffees-are-back-in-stock", "task-426", "m5-0", 86),
  storefrontNotice("filed", "work/427-search-doesnt-find-decaf", "427: search doesn't find \"decaf\"", "task-427", 81),
  storefrontNotice("claimed", "work/427-search-doesnt-find-decaf", "427: search doesn't find \"decaf\"", "task-427", 80),
  storefrontPing("work/427-search-doesnt-find-decaf", "task-427", "m11-0", 80),
  storefrontNotice("filed", "work/428-shipping-to-canada-costs-too-much", "428: shipping to Canada shows the wrong price", "task-428", 79),
  storefrontNotice("claimed", "work/428-shipping-to-canada-costs-too-much", "428: shipping to Canada shows the wrong price", "task-428", 78),
  storefrontPing("work/428-shipping-to-canada-costs-too-much", "task-428", "m19-0", 78),
  storefrontNotice("filed", "work/418-add-a-gift-message-to-orders", "418: add a gift message to orders", "task-418", 78),
  storefrontNotice("claimed", "work/418-add-a-gift-message-to-orders", "418: add a gift message to orders", "task-418", 78),
  storefrontPing("work/418-add-a-gift-message-to-orders", "task-418", "m24-0", 78),
  storefrontNotice("filed", "work/429-reviews-show-the-wrong-star-count", "429: reviews show the wrong star count", "task-429", 77),
  storefrontNotice("claimed", "work/429-reviews-show-the-wrong-star-count", "429: reviews show the wrong star count", "task-429", 77),
  storefrontPing("work/429-reviews-show-the-wrong-star-count", "task-429", "m29-0", 77),
  storefrontNotice("filed", "work/412-product-photos-load-slowly-on-phones", "412: product photos load slowly on phones", "fix-412", 74),
  storefrontNotice("claimed", "work/412-product-photos-load-slowly-on-phones", "412: product photos load slowly on phones", "fix-412", 74),
  storefrontPing("work/412-product-photos-load-slowly-on-phones", "fix-412", "m35-0", 73),
  storefrontPing("work/428-shipping-to-canada-costs-too-much", "task-428", "m36-0", 70),
  storefrontPing("work/426-show-which-coffees-are-back-in-stock", "task-426", "m37-0", 70),
  storefrontPing("work/426-show-which-coffees-are-back-in-stock", "task-426", "m40-0", 69),
  storefrontPing("work/421-password-reset-link-doesnt-work", "fix-421", "m42-0", 68),
  storefrontNotice("resolved", "work/421-password-reset-link-doesnt-work", "421: the password reset link doesn't work", "fix-421", 68),
  storefrontPing("work/428-shipping-to-canada-costs-too-much", "task-428", "m46-0", 68),
  storefrontPing("work/426-show-which-coffees-are-back-in-stock", "task-426", "m47-0", 68),
  storefrontNotice("resolved", "work/428-shipping-to-canada-costs-too-much", "428: shipping to Canada shows the wrong price", "task-428", 68),
  storefrontNotice("claimed", "work/428-shipping-to-canada-costs-too-much", "428: shipping to Canada shows the wrong price", "task-428", 67),
  storefrontPing("work/428-shipping-to-canada-costs-too-much", "task-428", "m53-0", 67),
  storefrontPing("work/429-reviews-show-the-wrong-star-count", "task-429", "m54-0", 65),
  storefrontPing("work/412-product-photos-load-slowly-on-phones", "fix-412", "m55-0", 65),
  storefrontPing("work/412-product-photos-load-slowly-on-phones", "fix-412", "m58-0", 65),
  storefrontPing("work/429-reviews-show-the-wrong-star-count", "task-429", "m59-0", 63),
  storefrontPing("work/429-reviews-show-the-wrong-star-count", "task-429", "m59-1", 63),
  storefrontPing("work/418-add-a-gift-message-to-orders", "task-418", "m60-0", 63),
  storefrontNotice("resolved", "work/429-reviews-show-the-wrong-star-count", "429: reviews show the wrong star count", "task-429", 63),
  storefrontPing("work/412-product-photos-load-slowly-on-phones", "fix-412", "m63-0", 63),
  storefrontNotice("resolved", "work/412-product-photos-load-slowly-on-phones", "412: product photos load slowly on phones", "fix-412", 63),
  storefrontPing("work/427-search-doesnt-find-decaf", "task-427", "m67-0", 62),
  storefrontPing("work/418-add-a-gift-message-to-orders", "task-418", "m69-0", 62),
  storefrontNotice("resolved", "work/418-add-a-gift-message-to-orders", "418: add a gift message to orders", "task-418", 62),
  storefrontPing("work/427-search-doesnt-find-decaf", "operator@example.com", "m73-0", 60),
  storefrontPing("work/427-search-doesnt-find-decaf", "operator@example.com", "m73-1", 60),
  storefrontPing("work/427-search-doesnt-find-decaf", "operator@example.com", "m73-2", 60),
  storefrontNotice("claimed", "work/428-shipping-to-canada-costs-too-much", "428: shipping to Canada shows the wrong price", "task-428", 6),
];

const storefrontKnowledgePushes: MockMessage[] = [
  storefrontKnowledge("agents/task-426", "claude-web", 86),
  storefrontKnowledge("work/426-show-which-coffees-are-back-in-stock", "task-426", 86),
  storefrontKnowledge("work/426-show-which-coffees-are-back-in-stock", "task-426", 86),
  storefrontKnowledge("agents/task-427", "claude-web", 81),
  storefrontKnowledge("work/427-search-doesnt-find-decaf", "task-427", 81),
  storefrontKnowledge("work/427-search-doesnt-find-decaf", "task-427", 80),
  storefrontKnowledge("agents/task-428", "claude-web", 80),
  storefrontKnowledge("agents/task-429", "claude-web", 80),
  storefrontKnowledge("work/428-shipping-to-canada-costs-too-much", "task-428", 79),
  storefrontKnowledge("agents/task-418", "claude-web", 79),
  storefrontKnowledge("work/428-shipping-to-canada-costs-too-much", "task-428", 78),
  storefrontKnowledge("work/418-add-a-gift-message-to-orders", "task-418", 78),
  storefrontKnowledge("work/418-add-a-gift-message-to-orders", "task-418", 78),
  storefrontKnowledge("work/429-reviews-show-the-wrong-star-count", "task-429", 77),
  storefrontKnowledge("work/429-reviews-show-the-wrong-star-count", "task-429", 77),
  storefrontKnowledge("agents/fix-412", "claude-web", 75),
  storefrontKnowledge("work/412-product-photos-load-slowly-on-phones", "fix-412", 74),
  storefrontKnowledge("work/412-product-photos-load-slowly-on-phones", "fix-412", 74),
  storefrontKnowledge("work/426-show-which-coffees-are-back-in-stock", "claude-web", 69),
  storefrontKnowledge("work/428-shipping-to-canada-costs-too-much", "claude-web", 69),
  storefrontKnowledge("work/421-password-reset-link-doesnt-work", "claude-web", 69),
  storefrontKnowledge("work/421-password-reset-link-doesnt-work", "fix-421", 68),
  storefrontKnowledge("work/428-shipping-to-canada-costs-too-much", "claude-web", 68),
  storefrontKnowledge("work/428-shipping-to-canada-costs-too-much", "task-428", 68),
  storefrontKnowledge("work/426-show-which-coffees-are-back-in-stock", "claude-web", 67),
  storefrontKnowledge("work/428-shipping-to-canada-costs-too-much", "task-428", 67),
  storefrontKnowledge("work/412-product-photos-load-slowly-on-phones", "claude-web", 65),
  storefrontKnowledge("work/429-reviews-show-the-wrong-star-count", "claude-web", 65),
  storefrontKnowledge("work/429-reviews-show-the-wrong-star-count", "task-429", 63),
  storefrontKnowledge("work/412-product-photos-load-slowly-on-phones", "fix-412", 63),
  storefrontKnowledge("work/429-reviews-show-the-wrong-star-count", "claude-web", 63),
  storefrontKnowledge("work/418-add-a-gift-message-to-orders", "claude-web", 62),
  storefrontKnowledge("work/418-add-a-gift-message-to-orders", "task-418", 62),
  storefrontKnowledge("work/427-search-doesnt-find-decaf", "claude-web", 61),
  storefrontKnowledge("work/428-shipping-to-canada-costs-too-much", "task-428", 6),
];

/** A ping in the storefront's `live`, naming the thread that moved. */
function storefrontPing(key: string, sender: string, message: string, minutesAgo: number): Record<string, unknown> {
  const episode = storefrontEpisode(`t${key.replace(/^work\/(\d+)-.*$/, "$1")}`);
  return {
    id: `gp-${message}`,
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: iso(minutesAgo),
    room_name: "storefront",
    episode: STOREFRONT_LIVE,
    content: {
      l9: {
        header: { kind: "exchange", message: { id: `gp-${message}`, parents: [], episode: STOREFRONT_LIVE } },
        payload: { type: "ping", data: { episode, sender, message } },
      },
    },
  };
}

/** A board event in the storefront's `live`. */
function storefrontNotice(
  subkind: string,
  key: string,
  title: string,
  by: string,
  minutesAgo: number,
): Record<string, unknown> {
  const id = `gn-${subkind}-${key}-${minutesAgo}`;
  return {
    id,
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: iso(minutesAgo),
    room_name: "storefront",
    episode: STOREFRONT_LIVE,
    content: {
      l9: {
        header: { kind: "exchange", message: { id, parents: [], episode: STOREFRONT_LIVE } },
        payload: {
          type: "notice",
          data: {
            subkind,
            key,
            title,
            episode: storefrontEpisode(`t${key.replace(/^work\/(\d+)-.*$/, "$1")}`),
            by,
            ...(subkind === "filed" ? { kind: "action" } : {}),
          },
        },
      },
    },
  };
}

/** A memory push, as the persister announces one into the room. */
function storefrontKnowledge(key: string, updatedBy: string, minutesAgo: number): MockMessage {
  return {
    id: `gk-${key}-${minutesAgo}`,
    sender_handle: "system",
    message_type: "l9_knowledge",
    created_at: iso(minutesAgo),
    episode: STOREFRONT_LIVE,
    content: JSON.stringify({
      content: `memory updated → ${key}`,
      l9: { payload: { type: "extraction", data: { key, updated_by: updatedBy, version: 3 } } },
    }),
  };
}

/** The little that was actually said out loud while all of that went past. */
const storefrontSaid: MockMessage[] = [
  {
    id: "gs-1",
    sender_handle: "operator@example.com",
    message_type: "broadcast",
    created_at: iso(70),
    episode: STOREFRONT_LIVE,
    content: "Did the password reset fix go out? A customer just emailed about it again.",
  },
  {
    id: "gs-2",
    sender_handle: "operator@example.com",
    message_type: "broadcast",
    created_at: iso(30),
    episode: STOREFRONT_LIVE,
    content: "Which of these needs me? I can't tell from here.",
  },
  {
    id: "gs-3",
    sender_handle: "operator@example.com",
    message_type: "broadcast",
    created_at: iso(8),
    episode: STOREFRONT_LIVE,
    content: "Let's get search (427) in first. People can't find decaf, and it's our best seller.",
  },
];

/** What was said inside the tasks' threads, by the id each ping names. */
function storefrontThreadMessage(
  id: string,
  key: string,
  sender: string,
  minutesAgo: number,
  content: string,
): MockMessage {
  return {
    id,
    sender_handle: sender,
    message_type: "broadcast",
    created_at: iso(minutesAgo),
    episode: storefrontEpisode(`t${key.replace(/^work\/(\d+)-.*$/, "$1")}`),
    content,
  };
}

const storefrontThreadSaid: MockMessage[] = [
  storefrontThreadMessage("m19-0", "work/428-shipping-to-canada-costs-too-much", "task-428", 78, "Taking this. Canada checkout pulls the US price table; checking where the region is read."),
  storefrontThreadMessage("m35-0", "work/412-product-photos-load-slowly-on-phones", "fix-412", 73, "Product photos ship at 4000px. Resizing them at upload and serving WebP."),
  storefrontThreadMessage("m36-0", "work/428-shipping-to-canada-costs-too-much", "task-428", 70, "Found it: the region comes from the IP, and our CDN puts Canadian traffic in the US."),
  storefrontThreadMessage("m40-0", "work/426-show-which-coffees-are-back-in-stock", "task-426", 69, "Restock dates come from the warehouse sheet; adding a nightly import."),
  storefrontThreadMessage("m42-0", "work/421-password-reset-link-doesnt-work", "fix-421", 68, "PR #508 is merged: reset links now last 24 hours instead of 10 minutes."),
  storefrontThreadMessage("m53-0", "work/428-shipping-to-canada-costs-too-much", "task-428", 67, "PR #512 is up: shipping reads the address country, not the IP. @reviewer can you look?"),
  storefrontThreadMessage("m59-1", "work/429-reviews-show-the-wrong-star-count", "task-429", 63, "Review passed. The star count was rounding the average before summing."),
  storefrontThreadMessage("m63-0", "work/412-product-photos-load-slowly-on-phones", "fix-412", 63, "Done: product pages load in 0.9s on a mid-range phone, from 4.2s."),
  storefrontThreadMessage("m69-0", "work/418-add-a-gift-message-to-orders", "task-418", 62, "Gift messages print on the packing slip now. Merged as PR #510."),
  storefrontThreadMessage("m73-2", "work/427-search-doesnt-find-decaf", "operator@example.com", 60, "Can search also match \"decaffeinated\" and \"DECAF\"? That's what people type."),
];

/**
 * The room before today — the half that used to be unreachable.
 *
 * The channel's window was the newest fifty messages with no way back, so a
 * room like this one read as whatever churn happened last. A fixture that only
 * carries what fits in one window cannot show that being fixed, or show it
 * regressing: this is deep enough that the mock room has to be walked back
 * through several pages to reach its start.
 */
const storefrontBacklog: MockMessage[] = Array.from({ length: 260 }, (_, i) => {
  const said = [
    "Merged the photo change. Product pages load in under a second on my phone now.",
    "The sale banner is up on staging if anyone wants to look.",
    "Canada shipping was using the US price table. Fixed on staging.",
    "Anyone know why the reviews show 4 stars for every coffee?",
    "That was an old cache. Cleared it, and the stock labels are right now.",
  ];
  // The backlog is attributed to handles that are actually in the room — the one
  // operator and a handful of registered agents — so replaying it does not mint
  // phantom "people" who only ever appear as a backlog sender.
  const senders = ["operator@example.com", "task-418", "fix-412", "task-428", "task-429", "task-426"];
  return {
    id: `gb-${i}`,
    sender_handle: senders[i % senders.length],
    message_type: "broadcast",
    created_at: iso(60 * 26 - i * 5),
    episode: STOREFRONT_LIVE,
    content: said[i % said.length],
  };
});

const storefront: RoomFixture = {
  room: {
    id: 4,
    name: "storefront",
    created_at: iso(60 * 96),
    is_public: true,
    is_persistent: true,
    mas_id: "mas_9f3c02de",
  },
  memories: [...storefrontMemories, ...storefrontExtraAgentMemories, ...storefrontExtraMemories],
  messages: [
    ...storefrontBacklog,
    ...storefrontKnowledgePushes,
    ...storefrontSaid,
    ...storefrontThreadSaid,
  ].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
  ),
  episodes: [],
  episodeDetails: {},
  wire: storefrontWire,
  // A handful live or awaiting; the rest read as idle. This is what splits the
  // roster into its lifecycle groups.
  presence: [
    { handle: "task-462", kind: "slim", last_seen: null },
    { handle: "fix-455", kind: "slim", last_seen: null },
    { handle: "fix-456", kind: "slim", last_seen: null },
    { handle: "task-461", kind: "slim", last_seen: null },
    { handle: "task-428", kind: "slim", last_seen: null },
    { handle: "task-454", kind: "lease", last_seen: iso(2) },
    { handle: "task-458", kind: "lease", last_seen: iso(4) },
    { handle: "task-459", kind: "lease", last_seen: iso(1) },
    { handle: "aligner", kind: "lease", last_seen: iso(5) },
  ],
};

// One store for the dev server's life. The REST routes and the stream route are
// separate route modules, and a write made through one has to be what the other
// reads, so the rooms hang off `globalThis` rather than living per module.
const store = globalThis as typeof globalThis & { __myceliumMockRooms?: Record<string, RoomFixture> };

export const ROOM_FIXTURES: Record<string, RoomFixture> = (store.__myceliumMockRooms ??= {
  // The demo scenario starts the checkout room before its story (see demo.ts).
  checkout: isDemoScenario() ? demoCheckout() : checkout,
  "subscription-pricing": pricing,
  storefront,
  scratch,
});

// A Learn take (see learn.ts) adds the room its course is filmed in.
const learn = learnRoom();
if (learn && !ROOM_FIXTURES[LEARN_ROOM]) ROOM_FIXTURES[LEARN_ROOM] = learn;

export const ROOMS: MockRoom[] = Object.values(ROOM_FIXTURES).map((f) => f.room);

export function getRoomFixture(name: string): RoomFixture | undefined {
  return ROOM_FIXTURES[name] ?? PATTERN_ROOMS[name];
}

// ── usage ─────────────────────────────────────────────────────────────────────

// A hub in steady, growing use: what `/api/observability/usage` adds up from
// the usage events the hub records. The month repeats back in time, a little
// quieter each month, so the 90-day view has a shape to it.
const USAGE_MONTH = [
  [2, 1], [0, 0], [3, 2], [4, 3], [1, 2], [0, 0], [0, 1], [5, 3], [3, 4], [2, 2],
  [6, 4], [2, 3], [0, 0], [0, 0], [4, 2], [3, 3], [5, 4], [2, 3], [4, 3], [0, 1],
  [0, 0], [6, 5], [4, 4], [3, 4], [5, 3], [2, 3], [0, 0], [1, 0], [7, 5], [4, 3],
] as const;

export function usageKpis(days: number) {
  const daily = Array.from({ length: days }, (_, i) => {
    const back = days - 1 - i;
    const [f, r] = USAGE_MONTH[(USAGE_MONTH.length - 1 - (back % 30) + 30) % 30];
    const damp = 1 - Math.floor(back / 30) * 0.25;
    return {
      day: iso(back * 1440).slice(0, 10),
      filed: Math.round(f * damp),
      resolved: Math.round(r * damp),
    };
  });
  const filed = daily.reduce((n, d) => n + d.filed, 0);
  const resolved = daily.reduce((n, d) => n + d.resolved, 0);
  const k = resolved / 68;
  const n = (x: number) => Math.max(0, Math.round(x * k));
  return {
    days,
    sharing: false,
    tasks: {
      filed,
      resolved,
      filed_by: { person: Math.round(filed * 0.53), agent: filed - Math.round(filed * 0.53) },
      median_hours_open: 5.4,
      median_hours_open_by: { person: 9.1, agent: 2.4 },
    },
    flows: {
      review: { resolved: n(14), rejected: n(2) },
      swarm: { resolved: n(5), rejected: n(1) },
      gated: { resolved: n(3), rejected: n(1) },
    },
    negotiations: { converged: n(6), rejected: n(1) },
    agents_joined: { claude_code: n(9), cursor: n(2), worker: n(3) },
    active_days: daily.filter(d => d.filed + d.resolved > 0).length,
    daily,
    work_total: 142,
    first_value_hours: 0.8,
  };
}

export const USAGE_KPIS = usageKpis(30);

// ── observability / metrics ───────────────────────────────────────────────────

// The shape `/api/observability` actually returns: the four counter namespaces
// `app/services/metrics.py` files under, with dimensions flattened into the key,
// and one histogram per measured latency. Token and cost counters stay zero
// because cognition runs through `pi`, which reports no per-turn usage.
export const BACKEND_METRICS = {
  started_at: iso(214),
  updated_at: iso(0),
  counters: {
    memory: {
      writes: 148,
      "writes.namespace": 148,
      writes_embedded: 148,
      searches: 96,
      search_hits: 88,
      search_misses: 8,
      results_returned: 402,
    },
    embeddings: {
      computed: 512,
      "by_source.local": 512,
      estimated_tokens: 31_400,
      estimated_cost_avoided_usd: 0.000628,
    },
    indexer: {
      runs: 34,
      files_indexed: 148,
      files_skipped: 12,
      files_pruned: 3,
      errors: 0,
      "by_target.room": 152,
      "by_target.watcher": 8,
    },
    llm: {
      calls: 41,
      "by_operation.task_compile": 12,
      "by_operation.health_probe": 29,
      "by_model.anthropic/claude-sonnet-4-6": 41,
      input_tokens: 0,
      output_tokens: 0,
      cost_usd: 0,
      errors: 1,
      "by_operation.health_probe.errors": 1,
    },
  },
  histograms: {
    "memory.search_latency_ms": { count: 96, sum: 1832.4, min: 8.2, max: 61.3 },
    "embeddings.latency_ms": { count: 512, sum: 6144, min: 6.1, max: 48.7 },
    "indexer.duration_ms": { count: 34, sum: 4216, min: 41, max: 610.5 },
    "llm.latency_ms": { count: 41, sum: 128_400, min: 810, max: 9240 },
    "llm.latency_ms.task_compile": { count: 12, sum: 74_400, min: 3100, max: 9240 },
    "llm.latency_ms.health_probe": { count: 29, sum: 54_000, min: 810, max: 3020 },
  },
};
