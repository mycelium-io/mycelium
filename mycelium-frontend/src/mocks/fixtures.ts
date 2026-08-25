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
 *     compiled work, a finished L9 episode);
 *   - `pricing-model`   — an in-progress negotiation (nothing compiled yet, a pending
 *     consent invite, a live-looking episode);
 *   - `scratch`         — a brand-new empty room (empty states).
 */

import type {
  A2aBridgeState,
  EpisodeDetail,
  EpisodeSummary,
  HostInfo,
  L9Envelope,
  MemoryGraph,
  MemoryGraphEdge,
  MemoryGraphNode,
  PendingInvite,
  PresenceMember,
} from "@/lib/api";
import type { RoomStatus } from "@/lib/board/upstream";

// A fixed "now" so relative timestamps render deterministically. Callers offset
// from this; nothing here calls Date.now(), so snapshots stay stable. The board
// ages rows against the reader's real clock, so a stale anchor makes a lively
// room look abandoned (drained TTL bars, "seen 10d ago") — pull this forward
// when it drifts too far behind the present.
const NOW = Date.parse("2026-08-22T17:30:00Z");
const iso = (minsAgo: number): string => new Date(NOW - minsAgo * 60_000).toISOString();

export interface MockRoom {
  id: number;
  name: string;
  created_at: string;
  is_public: boolean;
  is_persistent: boolean;
  mas_id?: string | null;
}

export interface MockMemory {
  key: string;
  /** Prose (most memories) or an object — the board projects a row's typed
   *  fields straight from an object value. This is the store's *structured
   *  value* shape (a memory whose `value:` frontmatter key holds a mapping —
   *  what `MemoryCreate.value` as an object round-trips to). Object-valued
   *  memories must also set `content_text` so search and previews have a string
   *  to read. */
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
}

export interface RoomFixture {
  room: MockRoom;
  memories: MockMemory[];
  messages: MockMessage[];
  episodes: EpisodeSummary[];
  episodeDetails: Record<string, EpisodeDetail>;
  invites: PendingInvite[];
  /** Live presence set, served at GET /sessions/members. A resident agent
   *  (one whose handle appears here) projects a board row; without a SLIM node
   *  there is otherwise no presence, so the board's resident rows come from here. */
  presence?: PresenceMember[];
  /** The room's link graph (#599/#611) — undefined means "no link index yet",
   *  the same degrade-to-empty case the real backend serves for an unlinked room. */
  links?: MemoryGraph;
  // Wire frames served at GET /messages/l9, feeding the Network pane's L9 feed.
  // Shaped like the persister's bus frames (a bare `{header, payload}` envelope
  // under `content`, plus the flat fields the inspector reads).
  l9?: Record<string, unknown>[];
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

const agentManifest = (description: string, adapter = "claude_code"): string =>
  `adapter: ${adapter}\ndescription: "${description}"\n`;

/** An external A2A agent's manifest: the card the hub resolved plus what it
 *  advertises, the fields the roster and the Network pane read. */
const a2aManifest = (description: string, card: string, skills: string[]): string =>
  `adapter: a2a\ndescription: "${description}"\n` +
  `a2a_card: ${card}\na2a_endpoint: ${card}/a2a\n` +
  `a2a_skills: [${skills.join(", ")}]\n`;

// ── atlas-migration: the rich, converged room ─────────────────────────────────

const atlasEpisode = (shortId: string): string =>
  `urn:ioc:mycelium:episode:atlas-migration:${shortId}`;

// The negotiation growth and risk ran. It is an *orphan* episode — no board row
// is bound to it — because a task's thread is the task's own, not the
// conversation that produced it. The two tasks it compiled each carry their own
// thread below; this URN stays the negotiation's record (Episodes rail, L9 feed).
const ATLAS_EPISODE = atlasEpisode("e4f1a2");
// The room's own channel. A message with no thread lands here, and a ping about
// a thread is raised here — which is why the ping's own episode is this one and
// the thread it names is in its payload.
const ATLAS_LIVE = atlasEpisode("live");
// The flip-reads task's own thread: where growth and risk work that one row, and
// what the pings below point at. Its own episode, minted when the row was, not
// the negotiation's.
const ATLAS_FLIP_THREAD = atlasEpisode("f1a5c7");
// The retire-legacy task's thread. Its own, and still silent — a blank thread is
// the common case, and the board shows the row with a thread to open regardless.
const ATLAS_RETIRE_THREAD = atlasEpisode("d2b8e0");

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

/**
 * A thread's activity as the room hears it: a **ping**, and only a ping.
 *
 * The shape the backend raises (`room_channels.raise_ping`) — an exchange
 * envelope in `live` naming the thread that moved, who wrote and which message,
 * carrying no prose, so there is nothing here to echo even by accident.
 *
 * It belongs to the L9 wire feed and *not* to the message list, which is where
 * the backend puts it too: a ping is a control frame, so the conversational
 * read drops it and the transcript replay is where it survives a reload. A mock
 * that served it from both would hide the merge the channel actually does.
 */
function atlasPing(message: string, sender: string, minutesAgo: number): Record<string, unknown> {
  return {
    id: `ping-${message}`,
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: iso(minutesAgo),
    room_name: "atlas-migration",
    episode: ATLAS_LIVE,
    content: {
      l9: {
        header: {
          kind: "exchange",
          message: { id: `ping-${message}`, parents: [], episode: ATLAS_LIVE },
          participants: { actors: [{ id: "system", role: "coordinator" }] },
        },
        payload: { type: "ping", data: { episode: ATLAS_FLIP_THREAD, sender, message } },
      },
    },
  };
}

/**
 * A board event as the room hears it: a **notice** — a task filed, claimed,
 * handed back or resolved.
 *
 * The mirror of {@link atlasPing} — an exchange envelope in `live` naming the
 * task the event was about (key, title, thread to open, who moved it), so the
 * board's changes read as something the room *did*, in sequence with the chat,
 * rather than appearing silently on another tab. ``kind`` rides on a ``filed``
 * notice so the line reads "New decision", not always "New task".
 */
function atlasNotice(
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
    room_name: "atlas-migration",
    episode: ATLAS_LIVE,
    content: {
      l9: {
        header: {
          kind: "exchange",
          message: { id, parents: [], episode: ATLAS_LIVE },
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

const atlasEpisodeSummary: EpisodeSummary = {
  short_id: "e4f1a2",
  episode: ATLAS_EPISODE,
  topic: "urn:concept:mycelium:atlas-migration",
  outcome: "converged",
  subkind: "converged",
  participants: ["growth", "risk", "aligner"],
  metrics: { mpc: 0.86, gar: 0.79, scr: 0.91, provenance_weight: 0.74, participants: 3 },
  assignments: { cutover: "phased", window: "48h" },
  tasks: ["work/flip-reads-behind-a-flag", "work/retire-the-legacy-store"],
  message_count: 3,
  updated_at: iso(42),
  updated_by: "aligner",
};

// Coordination-state memories the board projects into rows. Every one is what
// the docs promise a task is: a markdown file with frontmatter — prose in the
// body (`value`), the row's typed fields in `meta`. The board reads status,
// owner, priority, ci, pr, branch, blocks and choices from that frontmatter, the
// same keys a `memory set --meta` writes. And every row carries its own
// `episode`: a thread is per-item, minted when the row is, so each has one to
// open whether or not anyone has spoken in it yet. Together they give the board
// something in every attention filter (needs-you, in-flight, resolved) and a
// column for every inferred field, without any in-app demo layer.
const atlasBoardRows: MockMemory[] = [
  // What the atlas agreement compiled into. Two tasks from one negotiation are
  // two tasks with two threads, not two rows sharing the conversation that
  // produced them — so each carries its own episode, not the negotiation's.
  {
    key: "work/flip-reads-behind-a-flag",
    value:
      "flip reads behind a flag\n\n" +
      "Gate the read path on `atlas.reads.v2` (default off). Flip only once replica " +
      "lag has held under a second for an hour, and keep it reversible through the " +
      "48h soak. Gated on #502 (auth) and #504 (custody seam).",
    meta: { kind: "action", status: "open", assignee: "@growth", priority: "high", issue: "#502" },
    content_text: "flip reads behind a flag — gated on #502 and #504.",
    created_by: "aligner",
    updated_by: "aligner",
    version: 1,
    updated_at: iso(40),
    episode: ATLAS_FLIP_THREAD,
  },
  {
    key: "work/retire-the-legacy-store",
    value: "48h soak, then retire the legacy store",
    meta: { kind: "action", status: "open", assignee: "@risk", issue: "#499" },
    content_text: "48h soak, then retire the legacy store.",
    created_by: "aligner",
    updated_by: "aligner",
    version: 1,
    updated_at: iso(40),
    episode: ATLAS_RETIRE_THREAD,
  },
  {
    key: "decisions/token-ttl",
    value: "JWT access-token TTL: 15m or 60m?",
    meta: {
      status: "open",
      kind: "decision",
      owner: null,
      priority: "urgent",
      choices: ["15m", "60m"],
      asked_by: "@risk",
      ttl_minutes: 120,
    },
    content_text: "JWT access-token TTL: 15m or 60m? Risk wants 15m; growth wants 60m to cut re-auth churn.",
    created_by: "risk",
    updated_by: "risk",
    version: 1,
    updated_at: iso(6),
    episode: atlasEpisode("a1c3e5"),
  },
  {
    key: "failed/thin-spoke",
    value: "Enable thin-spoke join without a local replica",
    meta: {
      status: "blocked",
      kind: "blocked",
      owner: "@julia",
      priority: "high",
      blocked_by: ["#502"],
      issue: "#502",
    },
    content_text: "Thin-spoke join is blocked on the custody seam in #502.",
    created_by: "julia",
    updated_by: "julia",
    version: 1,
    updated_at: iso(40),
    episode: atlasEpisode("b4d6f8"),
  },
  {
    key: "work/custody-review",
    value: "@risk opened PR #504 — eyes on the custody seam",
    meta: {
      status: "in_review",
      kind: "review",
      owner: "@risk",
      priority: "high",
      pr: "#504",
      ci: "green",
      branch: "feat/custody-seam",
      ttl_minutes: 720,
    },
    content_text: "PR #504 opened on feat/custody-seam; CI green; wants a review.",
    created_by: "risk",
    updated_by: "risk",
    version: 1,
    updated_at: iso(12),
    episode: atlasEpisode("c5e7a9"),
  },
  {
    key: "work/jwt-auth",
    value: "Migrate auth → JWT",
    meta: {
      status: "in_progress",
      kind: "action",
      owner: "@growth",
      priority: "high",
      branch: "feat/jwt-auth",
      pr: "#502",
      ci: "green",
      blocks: ["Enable thin-spoke join"],
    },
    content_text: "Auth migration to JWT in progress on feat/jwt-auth; PR #502; CI green.",
    created_by: "growth",
    updated_by: "growth",
    version: 2,
    updated_at: iso(12),
    episode: atlasEpisode("d6f8b0"),
  },
  {
    key: "work/cache-sweep",
    value: "Cache TTL sweep across the memory index",
    meta: {
      status: "in_progress",
      kind: "action",
      owner: "@julia",
      priority: "normal",
      branch: "feat/cache",
      ci: "running",
    },
    content_text: "Sweeping cache TTLs across the memory index on feat/cache; CI running.",
    created_by: "julia",
    updated_by: "julia",
    version: 1,
    updated_at: iso(3),
    episode: atlasEpisode("e7a9c1"),
  },
  {
    key: "failed/offer-snap",
    value: "Aligner stalls when a proposer replies with prose only",
    meta: {
      status: "in_review",
      kind: "concern",
      owner: "@risk",
      priority: "normal",
      ci: "red",
      branch: "fix/offer-snap",
      ttl_minutes: 1440,
    },
    content_text: "Aligner stalls on prose-only replies; fix on fix/offer-snap; CI red.",
    created_by: "risk",
    updated_by: "risk",
    version: 1,
    updated_at: iso(55),
    episode: atlasEpisode("f8b0d2"),
  },
  {
    key: "work/path-traversal",
    value: "Fix path traversal in the memory key encoder",
    meta: {
      status: "resolved",
      kind: "action",
      owner: "@risk",
      priority: "urgent",
      pr: "#499",
      ci: "green",
      ttl_minutes: 1440,
    },
    content_text: "Path traversal in the memory key encoder fixed and merged (PR #499).",
    created_by: "risk",
    updated_by: "risk",
    version: 2,
    updated_at: iso(62),
    episode: atlasEpisode("a9c1e3"),
  },
  {
    key: "decisions/spire-retire",
    value: "Retire the SPIRE identity tier",
    meta: {
      status: "resolved",
      kind: "concern",
      owner: "@julia",
      priority: "normal",
      issue: "#668",
      promoted: true,
      ttl_minutes: 1440,
    },
    content_text: "SPIRE identity tier retired; promoted to #668.",
    created_by: "julia",
    updated_by: "julia",
    version: 1,
    updated_at: iso(200),
    episode: atlasEpisode("b0d2f4"),
  },
];

const atlas: RoomFixture = {
  room: {
    id: 1,
    name: "atlas-migration",
    created_at: iso(60 * 26),
    is_public: true,
    is_persistent: true,
    mas_id: "mas_7c1e9a2b",
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
    ...atlasBoardRows,
  ],
  // The channel is the room's whole history, so every row on the board is a thing
  // it once filed: the chat lines below set up each filing, and the task-created
  // notices in the `l9` feed are the filings themselves. Read top to bottom it is
  // one arc — stand up the room, do the early security/architecture work, spin up
  // the auth migration and the work that depends on it, broker the cutover, file
  // what it breaks into, then keep going.
  messages: [
    // ── standing the room up, and the early work (a day ago) ──
    { id: "h1", sender_handle: "operator", message_type: "broadcast", content: "Standing up the Atlas migration room. Goal: move the catalog off the legacy store with zero downtime.", created_at: iso(60 * 25) },
    { id: "h2", sender_handle: "julia", message_type: "broadcast", content: "First call: we're not keeping the SPIRE tier. Filing the decision so it's on the record.", created_at: iso(1440) },
    { id: "h3", sender_handle: "risk", message_type: "broadcast", content: "And the path-traversal hole in the key encoder is a hard blocker for anything public — taking it now.", created_at: iso(1400) },
    // ── the auth migration and the work hanging off it ──
    { id: "h4", sender_handle: "growth", message_type: "broadcast", content: "Auth has to move to JWT before the cutover. I've got it — PR #502 is open.", created_at: iso(140) },
    { id: "h5", sender_handle: "julia", message_type: "broadcast", content: "Thin-spoke join needs that landed first, so I'm filing it blocked on #502.", created_at: iso(130) },
    { id: "h6", sender_handle: "julia", message_type: "broadcast", content: "Also sweeping the cache TTLs across the memory index while I'm in here.", created_at: iso(95) },
    { id: "h7", sender_handle: "risk", message_type: "broadcast", content: "Filing a concern: the aligner stalls when a proposer replies with prose only. Fix is on fix/offer-snap but CI's red.", created_at: iso(58) },
    // ── the cutover negotiation ──
    { id: "a1", sender_handle: "operator", message_type: "broadcast", content: "@growth @risk let's settle the cutover strategy — approach and window. @aligner, broker it.", created_at: iso(48) },
    { id: "a2", sender_handle: "growth", message_type: "coordination_join", content: JSON.stringify({ handle: "growth", intent: "ship the migration this week", episode: ATLAS_EPISODE }), created_at: iso(47), episode: ATLAS_EPISODE },
    { id: "a3", sender_handle: "risk", message_type: "coordination_join", content: JSON.stringify({ handle: "risk", intent: "no downtime, no data loss", episode: ATLAS_EPISODE }), created_at: iso(47), episode: ATLAS_EPISODE },
    // The aligner brokers four rounds of alternating offers. Each agent reply is
    // a chat broadcast; the aligner reads it and emits the coordination_tick the
    // Negotiate/Network panes reconstruct. The chat is the source (see atlasMoves).
    ...atlasNegotiation,
    { id: "a6", sender_handle: "aligner", message_type: "coordination_consensus", content: JSON.stringify({ assignments: { cutover: "phased", window: "48h" }, episode: ATLAS_EPISODE, metrics: { gar: 0.79 } }), created_at: iso(41), episode: ATLAS_EPISODE },
    // The room files the work the agreement breaks into. The two task-created
    // notices land right after this line (see the `l9` feed below), so the chat
    // reads "here is the work" → the tasks, in sequence, instead of them just
    // appearing on the board.
    { id: "file1", sender_handle: "aligner", message_type: "broadcast", content: "Settled: phased cutover over 48h. Filing the work it breaks into for us to pick up:", created_at: iso(40) },
    { id: "a7", sender_handle: "growth", message_type: "broadcast", content: "Dual-write is live in staging. ✅", created_at: iso(30) },
    // ── follow-on work after the agreement ──
    { id: "h8", sender_handle: "risk", message_type: "broadcast", content: "PR #504 is up for the custody seam — filing it for review.", created_at: iso(14) },
    { id: "h9", sender_handle: "risk", message_type: "broadcast", content: "One more thing to settle before auth ships: access-token TTL, 15m or 60m. Filing the decision.", created_at: iso(6) },
    // Two agents working the flag row talk inside its thread. The channel does
    // not carry this — that is the whole point — so the room hears the pings
    // below instead, and the prose reads in the thread pane.
    { id: "t1", sender_handle: "growth", message_type: "broadcast", content: "Flag is wired: reads flip on `atlas.reads.v2`, default off.", created_at: iso(22), episode: ATLAS_FLIP_THREAD },
    { id: "t2", sender_handle: "risk", message_type: "broadcast", content: "Hold the flip until replica lag has been under a second for an hour.", created_at: iso(21), episode: ATLAS_FLIP_THREAD },
    { id: "t3", sender_handle: "growth", message_type: "broadcast", content: "Agreed — gating the flip on the lag alarm.", created_at: iso(20), episode: ATLAS_FLIP_THREAD },
  ],
  episodes: [atlasEpisodeSummary],
  episodeDetails: { e4f1a2: { ...atlasEpisodeSummary, messages: atlasL9Chain } },
  invites: [],
  // growth holds an open SLIM socket; risk is present on a server-held await
  // lease. Both are agents in the roster, so the board projects a resident row
  // for each — the presence signal that a live SLIM node would otherwise supply.
  presence: [
    { handle: "growth", kind: "slim", last_seen: null },
    { handle: "risk", kind: "lease", last_seen: iso(1) },
  ],
  // Every board row's origin, as the notice the room filed it with — each timed
  // just after the chat line that sets it up, so the channel reads talk → filing
  // for all ten, not just the two the negotiation compiled. The episode on each
  // matches its board row, so a notice opens the same thread the row's chip does.
  l9: [
    ...atlasL9Frames,
    // Every board row's origin — a `filed` notice — and, for two of them, the rest
    // of the lifecycle the room saw: path-traversal resolved long ago, flip-reads
    // claimed by growth just before he worked it. Read in order it is filed →
    // claimed → activity → resolved, the whole arc of a unit of work.
    atlasNotice("filed", "decisions/spire-retire", "Retire the SPIRE identity tier", atlasEpisode("b0d2f4"), "julia", 1439.8, "decision"),
    atlasNotice("filed", "work/path-traversal", "Fix path traversal in the memory key encoder", atlasEpisode("a9c1e3"), "risk", 1399.8, "action"),
    atlasNotice("resolved", "work/path-traversal", "Fix path traversal in the memory key encoder", atlasEpisode("a9c1e3"), "risk", 1200),
    atlasNotice("filed", "work/jwt-auth", "Migrate auth → JWT", atlasEpisode("d6f8b0"), "growth", 139.8, "action"),
    atlasNotice("filed", "failed/thin-spoke", "Enable thin-spoke join without a local replica", atlasEpisode("b4d6f8"), "julia", 129.8, "blocked"),
    atlasNotice("blocked", "failed/thin-spoke", "Enable thin-spoke join without a local replica", atlasEpisode("b4d6f8"), "julia", 128),
    atlasNotice("filed", "work/cache-sweep", "Cache TTL sweep across the memory index", atlasEpisode("e7a9c1"), "julia", 94.8, "action"),
    atlasNotice("filed", "failed/offer-snap", "Aligner stalls when a proposer replies with prose only", atlasEpisode("f8b0d2"), "risk", 57.8, "concern"),
    // The two the cutover agreement compiled, filed by the aligner right after its
    // "filing the work" line (iso(40)).
    atlasNotice("filed", "work/flip-reads-behind-a-flag", "flip reads behind a flag", ATLAS_FLIP_THREAD, "aligner", 39.9, "action", "@growth"),
    atlasNotice("filed", "work/retire-the-legacy-store", "48h soak, then retire the legacy store", ATLAS_RETIRE_THREAD, "aligner", 39.8, "action", "@risk"),
    atlasNotice("filed", "work/custody-review", "@risk opened PR #504 — eyes on the custody seam", atlasEpisode("c5e7a9"), "risk", 13.8, "review"),
    atlasNotice("filed", "decisions/token-ttl", "JWT access-token TTL: 15m or 60m?", atlasEpisode("a1c3e5"), "risk", 5.8, "decision"),
    // growth takes the flag row before working it, then the thread moves.
    atlasNotice("claimed", "work/flip-reads-behind-a-flag", "flip reads behind a flag", ATLAS_FLIP_THREAD, "growth", 23),
    atlasPing("t2", "risk", 21),
    atlasPing("t3", "growth", 20),
  ],
  // Three work rows name pull requests; the hub resolved them. The first row
  // mentions two, one green and one failing, so it shows the failing one and says
  // there was another. The shapes are GitHub's own wording.
  status: {
    room: "atlas-migration",
    field: "upstream",
    providers: ["github"],
    refs: [
      {
        ref: "github:pull_request:mycelium-io/mycelium#502",
        provider: "github", kind: "pull_request", id: "mycelium-io/mycelium#502",
        url: "https://github.com/mycelium-io/mycelium/pull/502",
        freshness: "fresh", state: "failed", label: "CI failing",
        age_seconds: 95, error: null,
        origins: ["memory:work/flip-reads-behind-a-flag"],
      },
      {
        ref: "github:pull_request:mycelium-io/mycelium#504",
        provider: "github", kind: "pull_request", id: "mycelium-io/mycelium#504",
        url: "https://github.com/mycelium-io/mycelium/pull/504",
        freshness: "fresh", state: "ok", label: "approved",
        age_seconds: 95, error: null,
        origins: ["memory:work/flip-reads-behind-a-flag"],
      },
      {
        ref: "github:pull_request:mycelium-io/mycelium#499",
        provider: "github", kind: "pull_request", id: "mycelium-io/mycelium#499",
        url: "https://github.com/mycelium-io/mycelium/pull/499",
        freshness: "stale", state: "blocked", label: "changes requested",
        age_seconds: 5400, error: null,
        origins: ["memory:work/retire-the-legacy-store"],
      },
    ],
    rows: {
      "memory:work/flip-reads-behind-a-flag": [
        "github:pull_request:mycelium-io/mycelium#502",
        "github:pull_request:mycelium-io/mycelium#504",
      ],
      "memory:work/retire-the-legacy-store": ["github:pull_request:mycelium-io/mycelium#499"],
    },
    refreshing: false,
  },
};

// The synthesized briefing links out to the three memories it summarizes; the
// decision itself relates to the goal and wikilinks a memory that isn't a
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
  { source: "decisions/cutover", target: "work/cutover-runbook", kind: "wikilink", resolved: false, error: "not_found" },
];
atlas.links = buildMockGraph(atlas.memories, ATLAS_LINK_EDGES);

// ── pricing-model: an in-progress negotiation, nothing compiled yet ───────────

const PRICING_EPISODE = "urn:ioc:mycelium:episode:pricing-model:b2d0";

const pricing: RoomFixture = {
  room: {
    id: 2,
    name: "pricing-model",
    created_at: iso(180),
    is_public: true,
    is_persistent: true,
    mas_id: "mas_31ab77c0",
  },
  memories: [
    { key: "agents/finance", value: agentManifest("Protects margin; models unit economics."), created_by: "operator", version: 1, updated_at: iso(160) },
    { key: "agents/growth", value: agentManifest("Wants adoption; favors a low entry price."), created_by: "operator", version: 1, updated_at: iso(160) },
    { key: "agents/aligner", value: agentManifest("First-party mediator (NEGMAS SAO).", "engine"), created_by: "operator", version: 1, updated_at: iso(160) },
    { key: "agents/synthesizer", value: agentManifest("Distills room memory into a shared briefing.", "engine"), created_by: "operator", version: 1, updated_at: iso(160) },
    { key: "agents/market-data", value: a2aManifest("External competitor pricing feed.", "https://market-data.example", ["quote", "benchmark"]), created_by: "operator", version: 1, updated_at: iso(30) },
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
      tasks: [],
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
  // The bridge state to design against: one external A2A agent consulted during
  // the negotiation (one answered call, one dead one), and the room's own card
  // having been read from outside.
  a2a: {
    room: "pricing-model",
    agents: [
      {
        handle: "market-data",
        description: "External competitor pricing feed.",
        card: "https://market-data.example",
        endpoint: "https://market-data.example/a2a",
        skills: ["quote", "benchmark"],
        calls_ok: 2,
        calls_failed: 1,
        last_call_at: iso(8),
        proxied: true,
      },
    ],
    exchanges: [
      {
        id: "a2a-1",
        handle: "market-data",
        direction: "outbound",
        status: "ok",
        at: iso(10),
        endpoint: "https://market-data.example/a2a",
        peer: "finance",
        prompt: "@finance: what are comparable Pro tiers charging per seat?",
        reply: "Comparable Pro tiers cluster at $35–$45/seat, median $39.",
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
        prompt: "Partner desk asks: is the annual term negotiable below 75 seats?",
        reply: "Delivered to room 'pricing-model'.",
        detail: null,
        duration_ms: null,
      },
      {
        id: "a2a-3",
        handle: "market-data",
        direction: "outbound",
        status: "error",
        at: iso(8),
        endpoint: "https://market-data.example/a2a",
        peer: "growth",
        prompt: "@growth: churn at $29 vs $39?",
        reply: "",
        detail: "send failed: timeout after 120s",
        duration_ms: 120_004,
      },
    ],
    outbound_ok: 2,
    outbound_failed: 1,
    exposure: {
      card_url: "http://localhost:8000/api/rooms/pricing-model/.well-known/agent-card.json",
      rpc_url: "http://localhost:8000/api/rooms/pricing-model/a2a",
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
  room: { id: 3, name: "scratch", created_at: iso(4), is_public: true, is_persistent: true, mas_id: null },
  memories: [],
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
