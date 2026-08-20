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
 * Three rooms cover the states worth designing against:
 *   - `atlas-migration` — a rich, converged room (memories, agents, a compiled
 *     plan, a finished L9 episode);
 *   - `pricing-model`   — an in-progress negotiation (no plan yet, a pending
 *     consent invite, a live-looking episode);
 *   - `scratch`         — a brand-new empty room (empty states).
 */

import type {
  EpisodeDetail,
  EpisodeSummary,
  HostInfo,
  L9Envelope,
  MemoryGraph,
  MemoryGraphEdge,
  MemoryGraphNode,
  PendingInvite,
  PlanResponse,
} from "@/lib/api";

// A fixed "now" so relative timestamps render deterministically. Callers offset
// from this; nothing here calls Date.now(), so snapshots stay stable.
const NOW = Date.parse("2026-08-12T17:30:00Z");
const iso = (minsAgo: number): string => new Date(NOW - minsAgo * 60_000).toISOString();

export interface MockRoom {
  id: number;
  name: string;
  created_at: string;
  is_public: boolean;
  is_persistent: boolean;
  mas_id?: string | null;
  title?: string | null;
}

export interface MockMemory {
  key: string;
  value: string;
  content_text?: string;
  created_by: string;
  updated_by?: string;
  version: number;
  updated_at?: string;
  room_name?: string;
}

export interface MockMessage {
  id: string;
  sender_handle: string;
  message_type: string;
  content: string;
  created_at: string;
  recipient_handle?: string | null;
  episode?: string | null;
}

export interface RoomFixture {
  room: MockRoom;
  memories: MockMemory[];
  plan: PlanResponse;
  messages: MockMessage[];
  episodes: EpisodeSummary[];
  episodeDetails: Record<string, EpisodeDetail>;
  invites: PendingInvite[];
  /** The room's link graph (#599/#611) — undefined means "no link index yet",
   *  the same degrade-to-empty case the real backend serves for an unlinked room. */
  links?: MemoryGraph;
  // Wire frames served at GET /messages/l9, feeding the Network pane's L9 feed.
  // Shaped like the persister's bus frames (a bare `{header, payload}` envelope
  // under `content`, plus the flat fields the inspector reads).
  l9?: Record<string, unknown>[];
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

const agentManifest = (description: string, adapter = "claude_code"): string =>
  `adapter: ${adapter}\ndescription: "${description}"\n`;

// ── atlas-migration: the rich, converged room ─────────────────────────────────

const ATLAS_EPISODE = "urn:ioc:mycelium:episode:atlas-migration:e4f1a2";

// The negotiation the aligner brokered: growth (big-bang, fast) vs risk
// (phased, safe), converging over four rounds of Stacked Alternating Offers.
//
// This models the real flow faithfully: the *chat* is the source. Each agent
// posts a reply in the channel (`say`), and the aligner reads it and emits the
// structured L9 it implies. So one move drives three things — the agent's chat
// broadcast, the coordination_tick the Negotiate pane reconstructs, and the L9
// envelope the Network feed shows — and they can't disagree. `ask` is the
// aligner's prompt that precedes a reply (it @-addresses one agent at a time).
const ATLAS_CONSENSUS = { cutover: "phased", window: "48h" };
interface AtlasMove {
  round: number;
  who: string;
  action: string;
  offer: Record<string, string>;
  say: string;
  ask?: string;
}
const atlasMoves: AtlasMove[] = [
  { round: 1, who: "growth", action: "propose", offer: { cutover: "big-bang", window: "24h" },
    ask: "Brokering. Two issues: cutover approach and window. @growth, opening offer?",
    say: "Big-bang cutover, 24h window. It's simpler to reason about." },
  { round: 1, who: "risk", action: "counter", offer: { cutover: "phased", window: "72h" },
    ask: "@risk, your counter?",
    say: "Phased with dual-write, 72h. Big-bang risks data loss." },
  { round: 2, who: "growth", action: "counter", offer: { cutover: "phased", window: "24h" },
    ask: "@growth, risk won't take big-bang. Move?",
    say: "Fine, phased — but 24h. I don't want to dual-write for days." },
  { round: 2, who: "risk", action: "counter", offer: { cutover: "phased", window: "60h" },
    say: "24h is too tight to verify parity. 60h." },
  { round: 3, who: "growth", action: "counter", offer: { cutover: "phased", window: "48h" },
    say: "Split the difference: 48h." },
  { round: 3, who: "risk", action: "counter", offer: { cutover: "phased", window: "48h" },
    say: "48h works if reads stay behind a flag through the soak." },
  { round: 4, who: "growth", action: "accept", offer: ATLAS_CONSENSUS,
    ask: "Standing offer: phased, 48h. @growth @risk — accept?",
    say: "Agreed. ✅" },
  { round: 4, who: "risk", action: "accept", offer: ATLAS_CONSENSUS,
    say: "Agreed." },
];

const atlasL9Chain: L9Envelope[] = [
  ...atlasMoves.map((m, i) => ({
    header: {
      protocol: "ioc",
      kind: "exchange",
      subkind: "tick",
      participants: { actors: [{ id: "aligner", role: "mediator" }, { id: m.who, role: "agent" }] },
      message: { id: `m${i + 1}`, parents: i ? [`m${i}`] : [], episode: ATLAS_EPISODE },
      context: { topic: "urn:concept:mycelium:atlas-migration" },
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
          { id: "growth", role: "agent" },
          { id: "risk", role: "agent" },
        ],
      },
      message: { id: `m${atlasMoves.length + 1}`, parents: [`m${atlasMoves.length}`], episode: ATLAS_EPISODE },
      context: { topic: "urn:concept:mycelium:atlas-migration" },
    },
    payload: {
      type: "consensus",
      data: { assignments: ATLAS_CONSENSUS, metrics: { mpc: 0.86, gar: 0.79, scr: 0.0 } },
    },
  },
];

// The mediated negotiation as it appears on the wire: for each move, the
// aligner's optional prompt and the agent's reply (both chat broadcasts, shown
// in the channel), then the coordination_tick the aligner emits from that reply
// (feeds Negotiate + Network, filtered out of the channel). Interleaved and
// timestamped so the transcript reads in order — the chat drives the L9.
const atlasNegotiation: MockMessage[] = (() => {
  const out: MockMessage[] = [];
  let at = 46; // minutes ago; ticks down as the exchange proceeds
  const step = () => iso((at -= 0.2));
  atlasMoves.forEach((m, i) => {
    if (m.ask) {
      out.push({ id: `neg-ask-${i}`, sender_handle: "aligner", message_type: "broadcast", content: m.ask, created_at: step() });
    }
    out.push({ id: `neg-say-${i}`, sender_handle: m.who, message_type: "broadcast", content: m.say, created_at: step() });
    out.push({
      id: `tick-${i + 1}`,
      sender_handle: "aligner",
      message_type: "coordination_tick",
      content: JSON.stringify({ round: m.round, participant_id: m.who, action: m.action, current_offer: m.offer, episode: ATLAS_EPISODE }),
      created_at: step(),
      episode: ATLAS_EPISODE,
    });
  });
  return out;
})();

// The L9 chain as persister bus frames: bare `{header, payload}` under content,
// with the flat sender_handle/message_type/created_at the inspector reads.
const atlasL9Frames: Record<string, unknown>[] = atlasL9Chain.map((env, i) => ({
  message_type: `l9_${env.header.kind}`,
  sender_handle: env.header.participants?.actors?.[0]?.id ?? "aligner",
  created_at: iso(44 - i),
  content: env,
}));

const atlasEpisodeSummary: EpisodeSummary = {
  short_id: "e4f1a2",
  episode: ATLAS_EPISODE,
  topic: "urn:concept:mycelium:atlas-migration",
  outcome: "converged",
  subkind: "converged",
  participants: ["growth", "risk", "aligner"],
  metrics: { mpc: 0.86, gar: 0.79, scr: 0.91, provenance_weight: 0.74, participants: 3 },
  assignments: { cutover: "phased", window: "48h" },
  plan_file: "plan/tasks.md",
  message_count: 3,
  updated_at: iso(42),
  updated_by: "aligner",
};

const atlas: RoomFixture = {
  room: {
    id: 1,
    name: "atlas-migration",
    created_at: iso(60 * 26),
    is_public: true,
    is_persistent: true,
    mas_id: "mas_7c1e9a2b",
    title: "Atlas DB Migration",
  },
  memories: [
    {
      key: "agents/growth",
      value: agentManifest("Ships fast; optimizes for delivery velocity."),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
    },
    {
      key: "agents/risk",
      value: agentManifest("Guards reliability; wary of big-bang cutovers."),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
    },
    {
      key: "agents/aligner",
      value: agentManifest("First-party mediator (NEGMAS SAO).", "engine"),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
    },
    {
      key: "agents/synthesizer",
      value: agentManifest("Distills room memory into a shared briefing.", "engine"),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
    },
    {
      key: "decisions/cutover",
      value: "Phased cutover over a 48h window; dual-write then flip reads.",
      content_text: "Phased cutover over a 48h window; dual-write then flip reads.",
      created_by: "aligner",
      version: 3,
      updated_at: iso(41),
    },
    {
      key: "context/goal",
      value: "Move the Atlas catalog off the legacy store with zero downtime.",
      content_text: "Move the Atlas catalog off the legacy store with zero downtime.",
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 25),
    },
    {
      key: "status/sprint",
      value: "Cutover rehearsal green; production flip scheduled Thursday.",
      content_text: "Cutover rehearsal green; production flip scheduled Thursday.",
      created_by: "growth",
      version: 2,
      updated_at: iso(120),
    },
    {
      key: "context/synthesis",
      value:
        "# Atlas migration — room briefing\n\n" +
        "**Decision.** Phased cutover over a 48h window; dual-write then flip reads.\n\n" +
        "**Status.** Cutover rehearsal green; production flip scheduled Thursday.\n\n" +
        "**Goal.** Move the Atlas catalog off the legacy store with zero downtime.\n\n" +
        "_Owners:_ @growth drives delivery; @risk guards reliability.",
      content_text:
        "Atlas migration briefing: phased 48h cutover (dual-write then flip); rehearsal green, flip Thursday; zero-downtime goal.\n\n" +
        "The goal this all serves, embedded verbatim:\n\n![[context/goal]]",
      created_by: "synthesizer",
      version: 1,
      updated_at: iso(38),
    },
  ],
  plan: {
    room: "atlas-migration",
    title: "Atlas DB Migration",
    files: [
      {
        slug: "tasks",
        title: "Cutover plan",
        content:
          "# Cutover plan\n\n- [x] dual-write to the new store @growth\n- [x] backfill + verify parity @risk\n- [ ] flip reads behind a flag @growth\n- [ ] 48h soak, then retire the legacy store @risk",
        updated_at: iso(40),
        updated_by: "aligner",
        tasks: [
          { id: "t1", slug: "tasks", line: 2, text: "dual-write to the new store @growth", done: true },
          { id: "t2", slug: "tasks", line: 3, text: "backfill + verify parity @risk", done: true },
          { id: "t3", slug: "tasks", line: 4, text: "flip reads behind a flag @growth", done: false },
          { id: "t4", slug: "tasks", line: 5, text: "48h soak, then retire the legacy store @risk", done: false },
        ],
      },
    ],
    tasks: [
      { id: "t1", slug: "tasks", line: 2, text: "dual-write to the new store @growth", done: true },
      { id: "t2", slug: "tasks", line: 3, text: "backfill + verify parity @risk", done: true },
      { id: "t3", slug: "tasks", line: 4, text: "flip reads behind a flag @growth", done: false },
      { id: "t4", slug: "tasks", line: 5, text: "48h soak, then retire the legacy store @risk", done: false },
    ],
    open_count: 2,
    done_count: 2,
  },
  messages: [
    { id: "a1", sender_handle: "operator", message_type: "broadcast", content: "@growth @risk let's settle the cutover strategy — approach and window. @aligner, broker it.", created_at: iso(48) },
    { id: "a2", sender_handle: "growth", message_type: "coordination_join", content: JSON.stringify({ handle: "growth", intent: "ship the migration this week", episode: ATLAS_EPISODE }), created_at: iso(47), episode: ATLAS_EPISODE },
    { id: "a3", sender_handle: "risk", message_type: "coordination_join", content: JSON.stringify({ handle: "risk", intent: "no downtime, no data loss", episode: ATLAS_EPISODE }), created_at: iso(47), episode: ATLAS_EPISODE },
    // The aligner brokers four rounds of alternating offers. Each agent reply is
    // a chat broadcast; the aligner reads it and emits the coordination_tick the
    // Negotiate/Network panes reconstruct. The chat is the source (see atlasMoves).
    ...atlasNegotiation,
    { id: "a6", sender_handle: "aligner", message_type: "coordination_consensus", content: JSON.stringify({ plan: "phased cutover agreed", assignments: { cutover: "phased", window: "48h" }, plan_file: "plan/tasks.md", episode: ATLAS_EPISODE, metrics: { gar: 0.79 } }), created_at: iso(41), episode: ATLAS_EPISODE },
    { id: "a7", sender_handle: "growth", message_type: "broadcast", content: "Dual-write is live in staging. ✅", created_at: iso(30) },
  ],
  episodes: [atlasEpisodeSummary],
  episodeDetails: { e4f1a2: { ...atlasEpisodeSummary, messages: atlasL9Chain } },
  invites: [],
  l9: atlasL9Frames,
};

// The synthesized briefing links out to the three memories it summarizes; the
// decision itself relates to the goal and wikilinks a plan file that isn't a
// memory (so it can't resolve) — a deliberate broken-link example. The four
// `agents/*` manifests and the briefing itself are never linked *to*, so they
// render as roots (inbound=0, outbound>0) in the graph — entry points with no
// referrers yet (#599's graph and #611's rail integrity banner agree on this by
// construction, since both read the same edge list).
const ATLAS_LINK_EDGES: MemoryGraphEdge[] = [
  { source: "context/synthesis", target: "decisions/cutover", kind: "wikilink", resolved: true },
  { source: "context/synthesis", target: "status/sprint", kind: "wikilink", resolved: true },
  { source: "context/synthesis", target: "context/goal", kind: "transclusion", resolved: true },
  { source: "status/sprint", target: "decisions/cutover", kind: "wikilink", resolved: true },
  { source: "decisions/cutover", target: "context/goal", kind: "relation", relation: "depends-on", resolved: true },
  { source: "decisions/cutover", target: "plan/tasks", kind: "wikilink", resolved: false, error: "not_found" },
];
atlas.links = buildMockGraph(atlas.memories, ATLAS_LINK_EDGES);

// ── pricing-model: an in-progress negotiation, no plan yet ─────────────────────

const PRICING_EPISODE = "urn:ioc:mycelium:episode:pricing-model:b2d0";

const pricing: RoomFixture = {
  room: {
    id: 2,
    name: "pricing-model",
    created_at: iso(180),
    is_public: true,
    is_persistent: true,
    mas_id: "mas_31ab77c0",
    title: null,
  },
  memories: [
    { key: "agents/finance", value: agentManifest("Protects margin; models unit economics."), created_by: "operator", version: 1, updated_at: iso(160) },
    { key: "agents/growth", value: agentManifest("Wants adoption; favors a low entry price."), created_by: "operator", version: 1, updated_at: iso(160) },
    { key: "agents/aligner", value: agentManifest("First-party mediator (NEGMAS SAO).", "engine"), created_by: "operator", version: 1, updated_at: iso(160) },
    { key: "agents/synthesizer", value: agentManifest("Distills room memory into a shared briefing.", "engine"), created_by: "operator", version: 1, updated_at: iso(160) },
    { key: "context/goal", value: "Pick a launch price for the Pro tier.", content_text: "Pick a launch price for the Pro tier.", created_by: "operator", version: 1, updated_at: iso(175) },
    {
      key: "context/synthesis",
      value:
        "# Pricing model — room briefing\n\n" +
        "**Goal.** Pick a launch price for the Pro tier.\n\n" +
        "**Outcome.** Pro launches at **$39/seat**, 75 seats, annual term — margin held above 60%.\n\n" +
        "_Owners:_ @finance guards margin; @growth drives adoption.",
      content_text:
        "Pricing briefing: Pro tier launches at $39/seat, 75 seats, annual; margin held above 60%.",
      created_by: "synthesizer",
      version: 1,
      updated_at: iso(6),
    },
  ],
  plan: { room: "pricing-model", title: null, files: [], tasks: [], open_count: 0, done_count: 0 },
  messages: [
    { id: "p1", sender_handle: "operator", message_type: "broadcast", content: "@finance @growth what's the Pro price? @aligner mediate.", created_at: iso(12) },
    { id: "p2", sender_handle: "finance", message_type: "coordination_join", content: JSON.stringify({ handle: "finance", intent: "margin >= 60%", episode: PRICING_EPISODE }), created_at: iso(11), episode: PRICING_EPISODE },
    { id: "p3", sender_handle: "growth", message_type: "coordination_join", content: JSON.stringify({ handle: "growth", intent: "land and expand", episode: PRICING_EPISODE }), created_at: iso(11), episode: PRICING_EPISODE },
    { id: "p4", sender_handle: "finance", message_type: "broadcast", content: "$49/seat holds the margin.", created_at: iso(9) },
  ],
  episodes: [
    {
      short_id: "b2d0",
      episode: PRICING_EPISODE,
      topic: "urn:concept:mycelium:pricing-model",
      outcome: "open",
      subkind: null,
      participants: ["finance", "growth", "aligner"],
      metrics: null,
      assignments: null,
      plan_file: null,
      message_count: 4,
      updated_at: iso(9),
      updated_by: "aligner",
    },
  ],
  episodeDetails: {},
  invites: [
    {
      id: "inv1",
      room: "pricing-model",
      agent: "legal",
      requested_by: "operator",
      trigger_text: "@legal can you weigh in on the discount policy?",
      status: "pending",
      created_at: iso(3),
    },
  ],
};

// ── scratch: a brand-new empty room ───────────────────────────────────────────

const scratch: RoomFixture = {
  room: { id: 3, name: "scratch", created_at: iso(4), is_public: true, is_persistent: true, mas_id: null, title: null },
  memories: [],
  plan: { room: "scratch", title: null, files: [], tasks: [], open_count: 0, done_count: 0 },
  messages: [],
  episodes: [],
  episodeDetails: {},
  invites: [],
};

export const ROOM_FIXTURES: Record<string, RoomFixture> = {
  "atlas-migration": atlas,
  "pricing-model": pricing,
  scratch,
};

export const ROOMS: MockRoom[] = Object.values(ROOM_FIXTURES).map((f) => f.room);

export function getRoomFixture(name: string): RoomFixture | undefined {
  return ROOM_FIXTURES[name];
}

// ── observability / metrics ───────────────────────────────────────────────────

export const BACKEND_METRICS = {
  counters: {
    llm: { calls: 128 },
    cfn: { calls: 42, "calls.mgmt": 12, "calls.node": 30 },
    embeddings: { computed: 356 },
    memory: { writes: 61, reads: 240 },
    coordination: { sessions_started: 7, sessions_converged: 5 },
  },
  histograms: {},
};

export const COLLECTOR_METRICS = {
  counters: {
    tokens: {
      total: { input: 184_300, output: 52_100, cache_read: 90_400, cache_write: 12_800, total: 339_600 },
      by_agent: {
        growth: { input: 82_000, output: 21_000, cache_read: 40_000, cache_write: 5_000, total: 148_000 },
        risk: { input: 61_000, output: 18_000, cache_read: 30_000, cache_write: 4_000, total: 113_000 },
        aligner: { input: 41_300, output: 13_100, cache_read: 20_400, cache_write: 3_800, total: 78_600 },
        synthesizer: { input: 12_600, output: 3_400, cache_read: 6_000, cache_write: 900, total: 22_900 },
      },
      by_model: {
        "anthropic/claude-sonnet-4-6": { input: 143_000, output: 39_000, cache_read: 70_000, cache_write: 9_000, total: 261_000 },
        "anthropic/claude-haiku-4-5": { input: 41_300, output: 13_100, cache_read: 20_400, cache_write: 3_800, total: 78_600 },
      },
    },
    cost_usd: {
      total: 4.82,
      by_agent: { growth: 2.1, risk: 1.6, aligner: 1.12, synthesizer: 0.28 },
      by_model: { "anthropic/claude-sonnet-4-6": 3.9, "anthropic/claude-haiku-4-5": 0.92 },
    },
    messages: { processed: 214 },
  },
  histograms: {
    by_agent: {
      growth: { calls: 46, last: iso(28) },
      risk: { calls: 38, last: iso(31) },
      aligner: { calls: 22, last: iso(42) },
      synthesizer: { calls: 6, last: iso(38) },
    },
  },
};

export const HOSTS: HostInfo[] = [
  { host: "hub-a.lan", span_count: 1820, trace_count: 143, last_seen: iso(2), agents: ["growth", "aligner"], error_count: 1 },
  { host: "worker-b.lan", span_count: 940, trace_count: 77, last_seen: iso(6), agents: ["risk"], error_count: 0 },
];
