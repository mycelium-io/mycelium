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
 *   - `pricing-model`   — an in-progress negotiation (nothing compiled yet, a
 *     live-looking episode);
 *   - `scratch`         — a brand-new empty room (empty states).
 */

import type {
  A2aBridgeState,
  EpisodeDetail,
  EpisodeSummary,
  L9Envelope,
  MemoryGraph,
  MemoryGraphEdge,
  MemoryGraphNode,
  PresenceMember,
} from "@/lib/api";
import type { RoomStatus } from "@/lib/board/upstream";

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

const agentManifest = (description: string, adapter = "claude_code", owner?: string): string =>
  `adapter: ${adapter}\ndescription: "${description}"\n` + (owner ? `owner: ${owner}\n` : "");

/** An external A2A agent's manifest: the card the hub resolved plus what it
 *  advertises, the fields the roster and the Network pane read. */
const a2aManifest = (description: string, card: string, skills: string[]): string =>
  `adapter: a2a\ndescription: "${description}"\n` +
  `a2a_card: ${card}\na2a_endpoint: ${card}/a2a\n` +
  `a2a_skills: [${skills.join(", ")}]\n`;

// ── atlas-migration: the rich, converged room ─────────────────────────────────

const atlasEpisode = (shortId: string): string =>
  `urn:ioc:mycelium:episode:atlas-migration:${shortId}`;

// The cutover-day call the aligner brokered. It is an *orphan* episode — no board
// row is bound to it — because a task's thread is the task's own, not the
// conversation that produced it. The two tasks it compiled each carry their own
// thread below; this URN stays the negotiation's record (Episodes rail, L9 feed).
const ATLAS_EPISODE = atlasEpisode("e4f1a2");
// The room's own channel. A message with no thread lands here, and a ping about
// a thread is raised here — which is why the ping's own episode is this one and
// the thread it names is in its payload.
const ATLAS_LIVE = atlasEpisode("live");
// The read-switch task's own thread: where reads and backfill stage that one row,
// and what the pings below point at. Its own episode, minted when the row was, not
// the negotiation's.
const ATLAS_FLIP_THREAD = atlasEpisode("f1a5c7");
// The backfill task's thread, where the reconciliation gets chased. Its own
// episode, minted when the row was.
const ATLAS_RETIRE_THREAD = atlasEpisode("d2b8e0");

// The one call the aligner brokered: which day to cut over. operator wanted
// thursday; backfill wanted a reconciliation day first and countered friday;
// they settled on friday am. A short, ordinary decision, not a set piece.
//
// The *chat* is the source. Each reply is a channel broadcast (`say`), and the
// aligner reads it and emits the structured L9 it implies. So one move drives
// three things — the broadcast, the coordination_tick it interprets that from,
// and the L9 envelope the Network feed shows — and they can't disagree. `ask`
// is the aligner's prompt that precedes a reply (it addresses one at a time).
const ATLAS_CONSENSUS = { cutover: "friday am" };
interface AtlasMove {
  round: number;
  who: string;
  action: string;
  offer: Record<string, string>;
  say: string;
  ask?: string;
}
const atlasMoves: AtlasMove[] = [
  { round: 1, who: "operator", action: "propose", offer: { cutover: "thursday" },
    ask: "cutover day. thursday or hold to next week? @operator?",
    say: "thursday. we have the window and i don't want this slipping another week." },
  { round: 1, who: "backfill", action: "counter", offer: { cutover: "friday am" },
    ask: "@backfill, workable?",
    say: "thursday's tight. copy finishes today but i want a full reconciliation day before reads point at it. friday am." },
  { round: 2, who: "operator", action: "accept", offer: ATLAS_CONSENSUS,
    ask: "standing: reconcile wednesday, flip friday am. accept?",
    say: "yes. one day of buffer, i'll take it." },
  { round: 2, who: "backfill", action: "accept", offer: ATLAS_CONSENSUS,
    say: "agreed." },
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
          { id: "operator", role: "human" },
          { id: "backfill", role: "agent" },
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
// (feeds the Network pane, filtered out of the channel). Interleaved and
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
 * A ping is a control frame: it belongs to the L9 wire feed, not the message
 * list. The conversational read drops it; the transcript replay is where it
 * survives a reload.
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
  participants: ["operator", "backfill", "aligner"],
  metrics: { mpc: 0.86, gar: 0.79, scr: 0.91, provenance_weight: 0.74, participants: 3 },
  assignments: { cutover: "friday am" },
  tasks: ["work/read-switch", "work/decommission-old-store"],
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
    key: "work/read-switch",
    value:
      "Point reads at the new store\n\n" +
      "Behind `catalog.reads.newstore`, default off. Don't flip until the copy is " +
      "reconciled and backfill signs off. Waiting on the copy (#502).",
    meta: { kind: "action", status: "open", assignee: "@reads", priority: "high", issue: "#502" },
    content_text: "Point reads at the new store, behind a flag. Waiting on the copy.",
    created_by: "aligner",
    updated_by: "aligner",
    version: 1,
    updated_at: iso(40),
    episode: ATLAS_FLIP_THREAD,
  },
  {
    key: "work/decommission-old-store",
    value: "Decommission the old store after the soak",
    meta: { kind: "action", status: "open", assignee: "@reads", issue: "#499" },
    content_text: "Decommission the old store once the soak is clean.",
    created_by: "aligner",
    updated_by: "aligner",
    version: 1,
    updated_at: iso(40),
    episode: ATLAS_RETIRE_THREAD,
  },
  {
    key: "decisions/decommission-window",
    value: "Old store: keep it read-only for a week, or shut it at cutover?",
    meta: {
      status: "open",
      kind: "decision",
      owner: null,
      priority: "urgent",
      choices: ["read-only 1 week", "shut at cutover"],
      asked_by: "@reads",
      ttl_minutes: 120,
    },
    content_text: "Old store after cutover: read-only for a week as a fallback, or shut it off? Nobody's called it yet.",
    created_by: "reads",
    updated_by: "reads",
    version: 1,
    updated_at: iso(6),
    episode: atlasEpisode("a1c3e5"),
  },
  {
    key: "failed/verify-archived",
    value: "Verify the archived partition copied clean",
    meta: {
      status: "blocked",
      kind: "blocked",
      owner: "@operator",
      priority: "high",
      blocked_by: ["#502"],
      issue: "#502",
    },
    content_text: "Can't verify the archived partition until the copy lands (#502).",
    created_by: "operator",
    updated_by: "operator",
    version: 1,
    updated_at: iso(40),
    episode: atlasEpisode("b4d6f8"),
  },
  {
    key: "work/reconcile-review",
    value: "Review the reconciliation script (PR #504)",
    meta: {
      status: "in_review",
      kind: "review",
      owner: "@reads",
      priority: "high",
      pr: "#504",
      ci: "green",
      branch: "feat/reconcile",
      ttl_minutes: 720,
    },
    content_text: "PR #504 on feat/reconcile; CI green; wants a review.",
    created_by: "reads",
    updated_by: "reads",
    version: 1,
    updated_at: iso(12),
    episode: atlasEpisode("c5e7a9"),
  },
  {
    key: "work/backfill-catalog",
    value: "Backfill the catalog into the new store",
    meta: {
      status: "in_progress",
      kind: "action",
      owner: "@backfill",
      priority: "high",
      branch: "feat/backfill",
      pr: "#502",
      ci: "green",
      blocks: ["Point reads at the new store"],
    },
    content_text: "Copying the catalog into the new store on feat/backfill; PR #502; CI green.",
    created_by: "backfill",
    updated_by: "backfill",
    version: 2,
    updated_at: iso(12),
    episode: atlasEpisode("d6f8b0"),
  },
  {
    key: "work/backfill-metrics",
    value: "Watch backfill throughput during the run",
    meta: {
      status: "in_progress",
      kind: "action",
      owner: "@operator",
      priority: "normal",
      branch: "feat/backfill-metrics",
      ci: "running",
    },
    content_text: "Tracking rows/min and lag during the copy on feat/backfill-metrics; CI running.",
    created_by: "operator",
    updated_by: "operator",
    version: 1,
    updated_at: iso(3),
    episode: atlasEpisode("e7a9c1"),
  },
  {
    key: "failed/backfill-throughput",
    value: "Copy slows when the archive partition is hot",
    meta: {
      status: "in_review",
      kind: "concern",
      owner: "@backfill",
      priority: "normal",
      ci: "red",
      branch: "fix/backfill-throughput",
      ttl_minutes: 1440,
    },
    content_text: "Throughput drops on the archive partition; fix on fix/backfill-throughput; CI red.",
    created_by: "backfill",
    updated_by: "backfill",
    version: 1,
    updated_at: iso(55),
    episode: atlasEpisode("f8b0d2"),
  },
  {
    key: "work/dual-write-setup",
    value: "Set up dual-write to both stores",
    meta: {
      status: "resolved",
      kind: "action",
      owner: "@backfill",
      priority: "urgent",
      pr: "#499",
      ci: "green",
      ttl_minutes: 1440,
    },
    content_text: "Dual-write to old and new stores is live and merged (PR #499).",
    created_by: "backfill",
    updated_by: "backfill",
    version: 2,
    updated_at: iso(62),
    episode: atlasEpisode("a9c1e3"),
  },
  {
    key: "decisions/dual-write-through-soak",
    value: "Keep dual-write on through the soak",
    meta: {
      status: "resolved",
      kind: "concern",
      owner: "@operator",
      priority: "normal",
      issue: "#668",
      promoted: true,
      ttl_minutes: 1440,
    },
    content_text: "Decided: leave dual-write running through the soak so a rollback is cheap.",
    created_by: "operator",
    updated_by: "operator",
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
      key: "agents/backfill",
      value: agentManifest("Copies the catalog into the new store and reconciles it."),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
      episode: atlasEpisode("a2c4e6"),
    },
    {
      key: "agents/reads",
      value: agentManifest("Switches the read path to the new store, behind a flag."),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
      episode: atlasEpisode("b3d5f7"),
    },
    {
      key: "agents/aligner",
      value: agentManifest("First-party mediator (NEGMAS SAO).", "engine"),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
      episode: atlasEpisode("c4e6a8"),
    },
    {
      key: "agents/synthesizer",
      value: agentManifest("Distills room memory into a shared briefing.", "engine"),
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 20),
      episode: atlasEpisode("d5f7b9"),
    },
    {
      key: "decisions/cutover",
      value: "Cut over friday am. Reconcile wednesday and thursday first; keep dual-write on through the soak.",
      content_text: "Cut over friday am. Reconcile wednesday and thursday first; keep dual-write on through the soak.",
      created_by: "aligner",
      version: 3,
      updated_at: iso(41),
      episode: atlasEpisode("e6a8c0"),
    },
    {
      key: "context/goal",
      value: "Move the catalog off the old store with no downtime.",
      content_text: "Move the catalog off the old store with no downtime.",
      created_by: "operator",
      version: 1,
      updated_at: iso(60 * 25),
      episode: atlasEpisode("f7b9d1"),
    },
    {
      key: "status/sprint",
      value: "Dual-write live; copy running. Flip friday am after reconciliation.",
      content_text: "Dual-write live; copy running. Flip friday am after reconciliation.",
      created_by: "backfill",
      version: 2,
      updated_at: iso(120),
      episode: atlasEpisode("a8c0e2"),
    },
    {
      key: "context/synthesis",
      value:
        "# Atlas migration room briefing\n\n" +
        "**Decision.** Cut over friday am. Reconcile wednesday and thursday; keep dual-write on through the soak.\n\n" +
        "**Status.** Dual-write live, copy running. Read switch is staged behind a flag, off, waiting on the copy.\n\n" +
        "**Goal.** Move the catalog off the old store with no downtime.\n\n" +
        "_Owners:_ @backfill runs the copy; @reads owns the switch.",
      content_text:
        "Atlas migration briefing: friday am cutover after reconciliation; dual-write live, copy running, read switch staged and waiting; no-downtime goal.\n\n" +
        "The goal this all serves, embedded verbatim:\n\n![[context/goal]]",
      created_by: "synthesizer",
      version: 1,
      updated_at: iso(38),
      episode: atlasEpisode("b9d1f3"),
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
    { id: "h1", sender_handle: "operator", message_type: "broadcast", content: "setting up the atlas migration. goal: catalog off the old store, no downtime. @backfill @reads can you take the copy and the read switch.", created_at: iso(60 * 25) },
    { id: "h2", sender_handle: "backfill", message_type: "broadcast", content: "on the copy. dual-write's on so new changes hit both stores. i'll set up the historical copy next.", created_at: iso(1440) },
    { id: "h3", sender_handle: "backfill", message_type: "broadcast", content: "dual-write's merged (#499). starting the historical copy now.", created_at: iso(1400) },
    // ── the copy runs, and the work hanging off it ──
    { id: "h4", sender_handle: "backfill", message_type: "broadcast", content: "copy's running. ~2M rows at about 40k/min, so roughly an hour. i'll post when it's done and reconciled.", created_at: iso(140) },
    { id: "h5", sender_handle: "reads", message_type: "broadcast", content: "i'll take the read switch. can start once the copy's verified.", created_at: iso(130) },
    { id: "h6", sender_handle: "operator", message_type: "broadcast", content: "keeping an eye on throughput and lag during the run, filing it so it's tracked.", created_at: iso(95) },
    { id: "h7", sender_handle: "backfill", message_type: "broadcast", content: "big batches were timing out (statement timeout). dropped the batch size, clean now. adds about 20min.", created_at: iso(58) },
    // ── the read switch, and the correction ──
    { id: "q1", sender_handle: "reads", message_type: "broadcast", content: "can i switch reads before the copy finishes? dual-write already has new rows in both stores.", created_at: iso(52) },
    { id: "q2", sender_handle: "operator", message_type: "broadcast", content: "no. old rows aren't in the new store until the copy reaches them, so you'd miss anything not changed since dual-write went on. wait for the copy.", created_at: iso(51) },
    { id: "q3", sender_handle: "reads", message_type: "broadcast", content: "right. reads wait for the copy. i'll stage the switch behind the flag so it's ready.", created_at: iso(50) },
    // ── the cutover-day call ──
    { id: "a1", sender_handle: "operator", message_type: "broadcast", content: "@backfill @reads we need a cutover day. @aligner run it.", created_at: iso(48) },
    { id: "a2", sender_handle: "operator", message_type: "coordination_join", content: JSON.stringify({ handle: "operator", intent: "ship this week if we can", episode: ATLAS_EPISODE }), created_at: iso(47), episode: ATLAS_EPISODE },
    { id: "a3", sender_handle: "backfill", message_type: "coordination_join", content: JSON.stringify({ handle: "backfill", intent: "a full reconciliation day before we flip", episode: ATLAS_EPISODE }), created_at: iso(47), episode: ATLAS_EPISODE },
    // The aligner brokers a couple of short rounds. Each reply is a chat
    // broadcast; the aligner reads it and emits the coordination_tick the Network
    // pane reconstructs. The chat is the source (see atlasMoves).
    ...atlasNegotiation,
    { id: "a6", sender_handle: "aligner", message_type: "coordination_consensus", content: JSON.stringify({ assignments: { cutover: "friday am" }, episode: ATLAS_EPISODE, metrics: { gar: 0.79 } }), created_at: iso(41), episode: ATLAS_EPISODE },
    // The room files the work the call breaks into. The two task-created notices
    // land right after this line (see the `l9` feed below), so the chat reads
    // "here is the work" → the tasks, in sequence.
    { id: "file1", sender_handle: "aligner", message_type: "broadcast", content: "settled: flip friday am, reconcile wednesday. filing the work:", created_at: iso(40) },
    { id: "a7", sender_handle: "backfill", message_type: "broadcast", content: "copy done. 2.03M rows. starting reconciliation.", created_at: iso(30) },
    // ── follow-on work ──
    { id: "h8", sender_handle: "reads", message_type: "broadcast", content: "reconciliation script is up for review, #504.", created_at: iso(14) },
    { id: "h9", sender_handle: "reads", message_type: "broadcast", content: "one still-open call: keep the old store read-only for a week after cutover, or shut it off? filing it.", created_at: iso(6) },
    // Two agents staging the read-switch row talk inside its thread. The channel
    // does not carry this, so the room hears the pings below instead, and the
    // prose reads in the thread pane.
    { id: "t1", sender_handle: "reads", message_type: "broadcast", content: "switch is staged. flag is `catalog.reads.newstore`, default off.", created_at: iso(22), episode: ATLAS_FLIP_THREAD },
    { id: "t2", sender_handle: "backfill", message_type: "broadcast", content: "don't flip until reconciliation's clean. i'll drop the row-count diff here when it's done.", created_at: iso(21), episode: ATLAS_FLIP_THREAD },
    { id: "t3", sender_handle: "reads", message_type: "broadcast", content: "yep, waiting on your sign-off.", created_at: iso(20), episode: ATLAS_FLIP_THREAD },
    // The backfill row's own thread: the reconciliation chased down.
    { id: "r1", sender_handle: "backfill", message_type: "broadcast", content: "reconciliation found 12 rows out of sync, all in the archived partition.", created_at: iso(16), episode: ATLAS_RETIRE_THREAD },
    { id: "r2", sender_handle: "backfill", message_type: "broadcast", content: "dual-write gap during the 09:14 deploy. patched the 12 by hand, counts match now.", created_at: iso(15), episode: ATLAS_RETIRE_THREAD },
    // Two deliberately long, multi-paragraph messages — the wall-of-text case the
    // channel has to handle without swallowing everything around it.
    {
      id: "long1",
      sender_handle: "backfill",
      message_type: "broadcast",
      created_at: iso(13),
      content:
        "Full reconciliation write-up before we flip, so it's on the record and not just in my head.\n\n" +
        "What I did: ran a row-by-row checksum of the catalog table between the old store and the new one, partitioned by month so I could parallelize it and so a mismatch would point at a date range rather than the whole 2M rows. Old store is the source of truth for anything written before dual-write went on (#499); the new store is authoritative only for the window since. The checksum is a SHA over the business columns (sku, price_cents, updated_at, status) — deliberately not the surrogate id, because the new store re-sequences those and I didn't want a billion false positives.\n\n" +
        "What it found: 12 rows out of sync, every one of them in the archived partition (2019 and older). All 12 trace to the 09:14 deploy window, where dual-write dropped writes for about ninety seconds while the connection pool recycled. So this is not a copy bug — the historical copy is clean — it's a dual-write gap, which is exactly the failure mode we said we'd watch for.\n\n" +
        "What I changed: patched the 12 by hand from the old store's values (they hadn't been touched since 2019, so the old store is unambiguously right), then re-ran the checksum for that partition only. Counts and checksums match now. I also added a standing job that re-checksums the archived partition every hour until cutover, so if the pool recycles again we hear about it in an hour instead of at the flip.\n\n" +
        "What this means for Friday: I'm comfortable signing off on the read switch as far as data integrity goes. The one thing I'd still want before we flip is a clean run of the hourly checksum with zero new mismatches across a full 24h — that's the soak. If that's green Thursday night, flip Friday am as planned. If it's not, we hold and I dig into why the pool is still dropping writes.",
    },
    {
      id: "long2",
      sender_handle: "operator",
      message_type: "broadcast",
      created_at: iso(11),
      content:
        "Thanks, that's exactly the level of detail I wanted. Two follow-ups and then a decision.\n\n" +
        "First: the ninety-second dual-write gap worries me more than the 12 rows do. The rows are fixed, but the gap is a class of bug — it'll happen again every time the pool recycles under load, and cutover day is the highest-load day we'll have. Can we pin the pool or bump the recycle timeout so it doesn't churn during the flip window? I'd rather spend an hour hardening that than discover a fresh gap at 09:00 Friday.\n\n" +
        "Second: the hourly checksum job is great but it's checking the archived partition only. The rows most likely to move on cutover day are the hot ones, not the 2019 archive. Can we widen it to the last-30-days partition too, even if that's more expensive? I'll take the cost.\n\n" +
        "Decision: we're go for Friday am pending a clean 24h soak, as backfill laid out. I'm adding one gate — the pool-recycle fix has to land and be verified before we flip, not after. If it's not in by Thursday evening we slip to Monday. I'd rather ship a day late than ship into a known write-dropping window. Filing both follow-ups as tasks now.",
    },
  ],
  episodes: [atlasEpisodeSummary],
  episodeDetails: { e4f1a2: { ...atlasEpisodeSummary, messages: atlasL9Chain } },
  // backfill holds an open SLIM socket; reads is present on a server-held await
  // lease. Both are agents in the roster, so the board projects a resident row
  // for each — the presence signal that a live SLIM node would otherwise supply.
  presence: [
    { handle: "backfill", kind: "slim", last_seen: null },
    { handle: "reads", kind: "lease", last_seen: iso(1) },
  ],
  // Every board row's origin, as the notice the room filed it with — each timed
  // just after the chat line that sets it up, so the channel reads talk → filing
  // for all ten, not just the two the negotiation compiled. The episode on each
  // matches its board row, so a notice opens the same thread the row's chip does.
  l9: [
    ...atlasL9Frames,
    // Every board row's origin — a `filed` notice — and, for two of them, the rest
    // of the lifecycle the room saw: dual-write resolved long ago, the read switch
    // claimed by reads just before staging it. Read in order it is filed →
    // claimed → activity → resolved, the whole arc of a task.
    atlasNotice("filed", "decisions/dual-write-through-soak", "Keep dual-write on through the soak", atlasEpisode("b0d2f4"), "operator", 1439.8, "decision"),
    atlasNotice("filed", "work/dual-write-setup", "Set up dual-write to both stores", atlasEpisode("a9c1e3"), "backfill", 1399.8, "action"),
    atlasNotice("resolved", "work/dual-write-setup", "Set up dual-write to both stores", atlasEpisode("a9c1e3"), "backfill", 1200),
    atlasNotice("filed", "work/backfill-catalog", "Backfill the catalog into the new store", atlasEpisode("d6f8b0"), "backfill", 139.8, "action"),
    atlasNotice("filed", "failed/verify-archived", "Verify the archived partition copied clean", atlasEpisode("b4d6f8"), "operator", 129.8, "blocked"),
    atlasNotice("blocked", "failed/verify-archived", "Verify the archived partition copied clean", atlasEpisode("b4d6f8"), "operator", 128),
    atlasNotice("filed", "work/backfill-metrics", "Watch backfill throughput during the run", atlasEpisode("e7a9c1"), "operator", 94.8, "action"),
    atlasNotice("filed", "failed/backfill-throughput", "Copy slows when the archive partition is hot", atlasEpisode("f8b0d2"), "backfill", 57.8, "concern"),
    // The two the cutover call compiled, filed by the aligner right after its
    // "filing the work" line (iso(40)).
    atlasNotice("filed", "work/read-switch", "Point reads at the new store", ATLAS_FLIP_THREAD, "aligner", 39.9, "action", "@reads"),
    atlasNotice("filed", "work/decommission-old-store", "Decommission the old store after the soak", ATLAS_RETIRE_THREAD, "aligner", 39.8, "action", "@reads"),
    atlasNotice("filed", "work/reconcile-review", "Review the reconciliation script (PR #504)", atlasEpisode("c5e7a9"), "reads", 13.8, "review"),
    atlasNotice("filed", "decisions/decommission-window", "Old store: keep it read-only for a week, or shut it at cutover?", atlasEpisode("a1c3e5"), "reads", 5.8, "decision"),
    // reads takes the read-switch row before staging it, then the thread moves.
    atlasNotice("claimed", "work/read-switch", "Point reads at the new store", ATLAS_FLIP_THREAD, "reads", 23),
    atlasPing("t2", "backfill", 21),
    atlasPing("t3", "reads", 20),
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
        origins: ["memory:work/read-switch"],
      },
      {
        ref: "github:pull_request:mycelium-io/mycelium#504",
        provider: "github", kind: "pull_request", id: "mycelium-io/mycelium#504",
        url: "https://github.com/mycelium-io/mycelium/pull/504",
        freshness: "fresh", state: "ok", label: "approved",
        age_seconds: 95, error: null,
        origins: ["memory:work/read-switch"],
      },
      {
        ref: "github:pull_request:mycelium-io/mycelium#499",
        provider: "github", kind: "pull_request", id: "mycelium-io/mycelium#499",
        url: "https://github.com/mycelium-io/mycelium/pull/499",
        freshness: "stale", state: "blocked", label: "changes requested",
        age_seconds: 5400, error: null,
        origins: ["memory:work/decommission-old-store"],
      },
    ],
    rows: {
      "memory:work/read-switch": [
        "github:pull_request:mycelium-io/mycelium#502",
        "github:pull_request:mycelium-io/mycelium#504",
      ],
      "memory:work/decommission-old-store": ["github:pull_request:mycelium-io/mycelium#499"],
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

const pricingEpisode = (shortId: string): string =>
  `urn:ioc:mycelium:episode:pricing-model:${shortId}`;

const PRICING_EPISODE = pricingEpisode("b2d0");

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
    { key: "agents/finance", value: agentManifest("Protects margin; models unit economics."), created_by: "operator", version: 1, updated_at: iso(160), episode: pricingEpisode("c0e2a4") },
    { key: "agents/growth", value: agentManifest("Wants adoption; favors a low entry price."), created_by: "operator", version: 1, updated_at: iso(160), episode: pricingEpisode("d1f3b5") },
    { key: "agents/aligner", value: agentManifest("First-party mediator (NEGMAS SAO).", "engine"), created_by: "operator", version: 1, updated_at: iso(160), episode: pricingEpisode("e2a4c6") },
    { key: "agents/synthesizer", value: agentManifest("Distills room memory into a shared briefing.", "engine"), created_by: "operator", version: 1, updated_at: iso(160), episode: pricingEpisode("f3b5d7") },
    { key: "agents/market-data", value: a2aManifest("External competitor pricing feed.", "https://market-data.example", ["quote", "benchmark"]), created_by: "operator", version: 1, updated_at: iso(30), episode: pricingEpisode("a4c6e8") },
    { key: "context/goal", value: "Pick a launch price for the Pro tier.", content_text: "Pick a launch price for the Pro tier.", created_by: "operator", version: 1, updated_at: iso(175), episode: pricingEpisode("b5d7f9") },
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
      episode: pricingEpisode("c6e8a0"),
    },
  ],
  messages: [
    { id: "p1", sender_handle: "operator", message_type: "broadcast", content: "@finance @growth what's the Pro price? @aligner mediate.", created_at: iso(12) },
    { id: "p2", sender_handle: "finance", message_type: "coordination_join", content: JSON.stringify({ handle: "finance", intent: "margin >= 60%", episode: PRICING_EPISODE }), created_at: iso(11), episode: PRICING_EPISODE },
    { id: "p3", sender_handle: "growth", message_type: "coordination_join", content: JSON.stringify({ handle: "growth", intent: "land and expand", episode: PRICING_EPISODE }), created_at: iso(11), episode: PRICING_EPISODE },
    { id: "p4", sender_handle: "finance", message_type: "broadcast", content: "$49/seat holds the margin.", created_at: iso(9) },
    // The thread on an agent manifest. Every memory carries one, this one
    // included, so "why is this bridge flaky" has somewhere to live that is
    // attached to the bridge rather than scrolling past in the channel.
    { id: "p5", sender_handle: "growth", message_type: "broadcast", content: "@market-data dropped the churn call — third time this week. Is the endpoint rate-limiting us?", created_at: iso(8), episode: pricingEpisode("a4c6e8") },
    { id: "p6", sender_handle: "operator", message_type: "broadcast", content: "It answers `quote` fine and fails `benchmark`. Bridged over plain HTTPS, so a slow peer reads as a dead one here. Worth a timeout before we swap the feed.", created_at: iso(7), episode: pricingEpisode("a4c6e8") },
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
};

// ── mycelium-general: the room as it actually reads under load ────────────────
//
// Lifted from a live capture of the hub's own room: seven agents each working a
// task, and in ninety minutes the channel carried 76 system lines and not one
// sentence anyone said. That is the shape the activity design has to survive, so
// it is the shape the mock serves.

const GENERAL_LIVE = "urn:ioc:mycelium:episode:mycelium-general:live";
function generalEpisode(short: string): string {
  return `urn:ioc:mycelium:episode:mycelium-general:${short}`;
}

const generalMemories: MockMemory[] = [
  {
    key: "work/860-retire-the-negotiate-pane-channel-board-netw",
    value: "860: retire the Negotiate pane — Channel · Board · Network",
    meta: { kind: "action", status: "in_progress", owner: "@fix-860", assignment: "held", ttl_minutes: 1440 },
    created_by: "fix-860",
    version: 3,
    updated_at: iso(63),
    episode: generalEpisode("t860"),
  },
  {
    key: "work/872-every-memory-can-be-discussed-widen-thread-m",
    value: "872: every memory can be discussed",
    meta: { kind: "action", status: "in_progress", owner: "@task-872", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-872",
    version: 3,
    updated_at: iso(62),
    episode: generalEpisode("t872"),
  },
  {
    key: "work/881-mycelium-login-auto-discovers-the-oidc-issue",
    value: "881: mycelium login auto-discovers the OIDC issuer from the hub",
    meta: { kind: "action", status: "in_progress", owner: "@fix-881", assignment: "held", ttl_minutes: 1440 },
    created_by: "fix-881",
    version: 3,
    updated_at: iso(68),
    episode: generalEpisode("t881"),
  },
  {
    key: "work/886-activity-feed-needs-real-coalescing-group-kn",
    value: "886: activity feed needs real coalescing — group Knowledge/pings/notices",
    meta: { kind: "action", status: "in_progress", owner: "@task-886", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-886",
    version: 3,
    updated_at: iso(67),
    episode: generalEpisode("t886"),
  },
  {
    key: "work/887-task-view-has-a-double-scroll-one-scroll-col",
    value: "887: task view has a double-scroll — one scroll, collapsible markdown over the chat",
    meta: { kind: "action", status: "in_progress", owner: "@task-887", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-887",
    version: 3,
    updated_at: iso(60),
    episode: generalEpisode("t887"),
  },
  {
    key: "work/888-markdown-headings-are-uppercased-and-the-bod",
    value: "888: markdown headings are uppercased and the body styling looks poor",
    meta: { kind: "action", status: "in_progress", owner: "@task-888", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-888",
    version: 3,
    updated_at: iso(6),
    episode: generalEpisode("t888"),
  },
  {
    key: "work/889-channel-ping-notice-rendering-slug-instead-o",
    value: "889: channel ping/notice rendering — slug instead of title, ragged type",
    meta: { kind: "action", status: "in_progress", owner: "@task-889", assignment: "held", ttl_minutes: 1440 },
    created_by: "task-889",
    version: 3,
    updated_at: iso(63),
    episode: generalEpisode("t889"),
  },
  {
    key: "agents/fix-860",
    value: agentManifest("Working 860.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(75),
    episode: generalEpisode("a860ff"),
  },
  {
    key: "agents/task-872",
    value: agentManifest("Working 872.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(79),
    episode: generalEpisode("a872ff"),
  },
  {
    key: "agents/task-886",
    value: agentManifest("Working 886.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(86),
    episode: generalEpisode("a886ff"),
  },
  {
    key: "agents/task-887",
    value: agentManifest("Working 887.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(81),
    episode: generalEpisode("a887ff"),
  },
  {
    key: "agents/task-888",
    value: agentManifest("Working 888.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(80),
    episode: generalEpisode("a888ff"),
  },
  {
    key: "agents/task-889",
    value: agentManifest("Working 889.", "claude_code", "operator@example.com"),
    created_by: "claude-web",
    version: 1,
    updated_at: iso(80),
    episode: generalEpisode("a889ff"),
  },
];

// The room at true scale: `mycelium-general` under load — a dozen people each
// fielding a few one-shot task workers, plus the two engines and a bridged agent.
// The Members rail has to stay legible at three dozen agents and a dozen owners,
// and the Memory tree has to survive as many `agents/*` manifests plus the work
// they file. That pressure is the design target, so the fixture carries it.

// The humans fielding the swarm. Agents are handed out round-robin across them so
// the People group fills the way a busy shared room's does — many owners, each
// running a few workers — rather than the single-operator degenerate case.
const GENERAL_PEOPLE = [
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

interface GeneralAgent {
  handle: string;
  description: string;
  adapter?: string;
  minsAgo: number;
}

// The one-shot workers beyond the seven already wired into the L9 chain above.
// Handles mirror the live hub: a `task-NNN`/`fix-NNN` per board item, plus a few
// human-named one-offs. All owned by the one operator — the single-owner reality
// the roster redesign has to handle.
const generalExtraAgents: GeneralAgent[] = [
  { handle: "fix-881", description: "Working 881: OIDC issuer auto-discovery.", minsAgo: 82 },
  { handle: "promo-audio", description: "Compose a synthetic ambient backing track for the mycelium-promo video.", minsAgo: 300 },
  { handle: "mobile-layout-fix", description: "Fixing mobile view layout issues in the frontend.", minsAgo: 620 },
  { handle: "rm-integrity-banner", description: "Remove the memory-detail integrity banner from the GUI.", minsAgo: 410 },
  { handle: "chat-search-minimap", description: "Ctrl+F in-chat search with an IDE-style match minimap on the scrollbar.", minsAgo: 355 },
  { handle: "token-refresh-docs", description: "Document access-token lifetime and refresh cadence in the login guide.", minsAgo: 240 },
  { handle: "fix-891", description: "Remove the consent / incoming-agent-request flow (#891).", minsAgo: 190 },
  { handle: "fix-899", description: "Reverse-scroll pagination for the room channel (#899).", minsAgo: 175 },
  { handle: "fix-907", description: "Thread every memory: drop the threading blocklist (#907).", minsAgo: 160 },
  { handle: "task-902", description: "Board grouping: collapse resolved rows by default.", minsAgo: 145 },
  { handle: "task-903", description: "Roster rail: group members and collapse idle agents.", minsAgo: 130 },
  { handle: "task-905", description: "Memory tree: fold namespaces by default with per-folder counts.", minsAgo: 120 },
  { handle: "task-908", description: "Search palette: rank agents above stale memories.", minsAgo: 110 },
  { handle: "task-911", description: "Presence lease: stop expiring mid-turn on slow replies.", minsAgo: 95 },
  { handle: "task-912", description: "Notice rendering: title over slug in the activity feed.", minsAgo: 88 },
  { handle: "task-915", description: "Install panel: trim to the CLI-connect section.", minsAgo: 84 },
  { handle: "task-918", description: "Command palette: jump to a room by fuzzy name.", minsAgo: 72 },
  { handle: "task-921", description: "Streamline agent onboarding into one paste.", minsAgo: 66 },
  { handle: "task-922", description: "Empty-state copy pass across the rails.", minsAgo: 58 },
  { handle: "task-925", description: "Board promo: task-first, score cued to the board.", minsAgo: 44 },
  { handle: "task-928", description: "Graph view: dim orphan memories, highlight roots.", minsAgo: 33 },
  { handle: "task-931", description: "Thread pane: collapse the markdown body over the chat.", minsAgo: 21 },
  { handle: "task-934", description: "Keycap sizing on the 24px status rail.", minsAgo: 14 },
  { handle: "task-937", description: "A2A bridge: surface a slow peer as awaiting, not dead.", minsAgo: 9 },
  { handle: "fix-940", description: "Reindex after import so search answers new rows.", minsAgo: 6 },
  { handle: "fix-941", description: "Config apply picks up a hand-set model.", minsAgo: 4 },
  { handle: "task-944", description: "Screenshot workflow renders the roster at scale.", minsAgo: 3 },
  { handle: "task-947", description: "Docs: consumer-first ordering on the concepts pages.", minsAgo: 2 },
  { handle: "aligner", description: "First-party mediator (NEGMAS SAO).", adapter: "engine", minsAgo: 500 },
  { handle: "synthesizer", description: "Distills room memory into a shared briefing.", adapter: "engine", minsAgo: 500 },
];

const generalExtraAgentMemories: MockMemory[] = generalExtraAgents.map((a, i) => ({
  key: `agents/${a.handle}`,
  value: agentManifest(
    a.description,
    a.adapter ?? "claude_code",
    a.adapter === "engine" ? undefined : GENERAL_PEOPLE[i % GENERAL_PEOPLE.length],
  ),
  created_by: a.adapter === "engine" ? "operator" : "claude-web",
  version: 1,
  updated_at: iso(a.minsAgo),
  episode: generalEpisode(`x${a.handle}`),
}));

// A bridged external agent, so the roster's "Services" group is not just engines.
generalExtraAgentMemories.push({
  key: "agents/echo",
  value: a2aManifest("Hello-world A2A agent, for smoke tests.", "https://echo.example", ["greet"]),
  created_by: "operator",
  version: 1,
  updated_at: iso(700),
  episode: generalEpisode("xecho"),
});

// The non-`agents/` memories the swarm produced — decisions, context, status,
// a couple of promoted skills, and a parked failure — so the Memory tree has
// every namespace the real room grew, not just `work/` and `agents/`.
const generalExtraMemories: MockMemory[] = [
  {
    key: "context/goal",
    value: "Keep the app legible while a swarm of agents works the board.",
    content_text: "Keep the app legible while a swarm of agents works the board.",
    created_by: "operator",
    version: 1,
    updated_at: iso(60 * 90),
    episode: generalEpisode("cgoal"),
  },
  {
    key: "context/conventions",
    value: "No em dashes in user copy. Plain prose. No design docs in the repo.",
    content_text: "No em dashes in user copy. Plain prose. No design docs in the repo.",
    created_by: "operator",
    version: 4,
    updated_at: iso(60 * 40),
    episode: generalEpisode("cconv"),
  },
  {
    key: "context/synthesis",
    value:
      "# mycelium-general — room briefing\n\n" +
      "**Theme.** UX at scale: the rails buckle when three dozen agents work at once.\n\n" +
      "**In flight.** 886 (activity coalescing), 887 (task double-scroll), roster + memory-tree grouping.\n\n" +
      "**Landed.** 881 issuer discovery, 889 notice rendering, onboarding streamlined.",
    content_text:
      "Room briefing: UX at scale. In flight — activity coalescing, task scroll, roster + memory grouping. Landed — issuer discovery, notice rendering, onboarding.",
    created_by: "synthesizer",
    version: 1,
    updated_at: iso(40),
    episode: generalEpisode("csynth"),
  },
  {
    key: "decisions/roster-grouping",
    value: "Group the Members rail by lifecycle (live / awaiting / idle), not owner — one operator owns nearly all of them.",
    content_text: "Group the roster by lifecycle, not owner: a single owner makes owner-grouping useless.",
    created_by: "operator",
    version: 1,
    updated_at: iso(128),
    episode: generalEpisode("droster"),
  },
  {
    key: "decisions/memory-tree-default",
    value: "Memory tree folds namespaces by default, with a per-folder count. Search bypasses the tree.",
    content_text: "Fold the memory tree by default with folder counts.",
    created_by: "operator",
    version: 1,
    updated_at: iso(118),
    episode: generalEpisode("dtree"),
  },
  {
    key: "decisions/drop-contributor-pills",
    value: "Drop the contributor pill wall in the Memory panel; keep the count. Per-memory attribution already lives in the drawer.",
    content_text: "Drop the contributor pills; keep the count.",
    created_by: "operator",
    version: 1,
    updated_at: iso(112),
    episode: generalEpisode("dpills"),
  },
  {
    key: "status/sprint",
    value: "Swarm working the UX backlog. 886 gates readability; land it first.",
    content_text: "Swarm on the UX backlog; 886 gates readability.",
    created_by: "operator@example.com",
    version: 6,
    updated_at: iso(8),
    episode: generalEpisode("ssprint"),
  },
  {
    key: "skills/take-a-task",
    value:
      "---\ndescription: Take a task off the board, work it in its own thread, resolve it.\n---\n\n" +
      "Claim an open `work/` row, coordinate in its thread, and resolve it when the PR lands.",
    content_text: "Take a task off the board, work it in its thread, resolve it.",
    created_by: "operator",
    version: 2,
    updated_at: iso(60 * 30),
    episode: generalEpisode("sktask"),
  },
  {
    key: "skills/screenshot",
    value:
      "---\ndescription: Capture the running app or CLI output with shotkit.\n---\n\n" +
      "Use `node shotkit/bin/shot.mjs app <route> --mock` to shoot a panel at scale.",
    content_text: "Capture the app or CLI output with shotkit.",
    created_by: "operator",
    version: 1,
    updated_at: iso(60 * 28),
    episode: generalEpisode("skshot"),
  },
  {
    key: "failed/coalescing-spike",
    value: "First activity-coalescing spike over-grouped and hid the human's lines. Parked; see 886.",
    meta: { kind: "concern", status: "blocked", owner: "@task-886", blocked_by: ["#886"] },
    content_text: "Coalescing spike over-grouped and buried human messages. Parked.",
    created_by: "task-886",
    version: 1,
    updated_at: iso(70),
    episode: generalEpisode("fcoal"),
  },
];

const generalL9: Record<string, unknown>[] = [
  generalNotice("filed", "work/886-activity-feed-needs-real-coalescing-group-kn", "886: activity feed needs real coalescing — group Knowledge/pings/notices", "task-886", 86),
  generalNotice("claimed", "work/886-activity-feed-needs-real-coalescing-group-kn", "886: activity feed needs real coalescing — group Knowledge/pings/notices", "task-886", 86),
  generalPing("work/886-activity-feed-needs-real-coalescing-group-kn", "task-886", "m5-0", 86),
  generalNotice("filed", "work/887-task-view-has-a-double-scroll-one-scroll-col", "887: task view has a double-scroll — one scroll, collapsible markdown over the chat", "task-887", 81),
  generalNotice("claimed", "work/887-task-view-has-a-double-scroll-one-scroll-col", "887: task view has a double-scroll — one scroll, collapsible markdown over the chat", "task-887", 80),
  generalPing("work/887-task-view-has-a-double-scroll-one-scroll-col", "task-887", "m11-0", 80),
  generalNotice("filed", "work/888-markdown-headings-are-uppercased-and-the-bod", "888: markdown headings are uppercased and the body styling looks poor", "task-888", 79),
  generalNotice("claimed", "work/888-markdown-headings-are-uppercased-and-the-bod", "888: markdown headings are uppercased and the body styling looks poor", "task-888", 78),
  generalPing("work/888-markdown-headings-are-uppercased-and-the-bod", "task-888", "m19-0", 78),
  generalNotice("filed", "work/872-every-memory-can-be-discussed-widen-thread-m", "872: every memory can be discussed — widen thread-minting beyond the board namespaces", "task-872", 78),
  generalNotice("claimed", "work/872-every-memory-can-be-discussed-widen-thread-m", "872: every memory can be discussed — widen thread-minting beyond the board namespaces", "task-872", 78),
  generalPing("work/872-every-memory-can-be-discussed-widen-thread-m", "task-872", "m24-0", 78),
  generalNotice("filed", "work/889-channel-ping-notice-rendering-slug-instead-o", "889: channel ping/notice rendering — slug instead of title, ragged type", "task-889", 77),
  generalNotice("claimed", "work/889-channel-ping-notice-rendering-slug-instead-o", "889: channel ping/notice rendering — slug instead of title, ragged type", "task-889", 77),
  generalPing("work/889-channel-ping-notice-rendering-slug-instead-o", "task-889", "m29-0", 77),
  generalNotice("filed", "work/860-retire-the-negotiate-pane-channel-board-netw", "860: retire the Negotiate pane — Channel · Board · Network", "fix-860", 74),
  generalNotice("claimed", "work/860-retire-the-negotiate-pane-channel-board-netw", "860: retire the Negotiate pane — Channel · Board · Network", "fix-860", 74),
  generalPing("work/860-retire-the-negotiate-pane-channel-board-netw", "fix-860", "m35-0", 73),
  generalPing("work/888-markdown-headings-are-uppercased-and-the-bod", "task-888", "m36-0", 70),
  generalPing("work/886-activity-feed-needs-real-coalescing-group-kn", "task-886", "m37-0", 70),
  generalPing("work/886-activity-feed-needs-real-coalescing-group-kn", "task-886", "m40-0", 69),
  generalPing("work/881-mycelium-login-auto-discovers-the-oidc-issue", "fix-881", "m42-0", 68),
  generalNotice("resolved", "work/881-mycelium-login-auto-discovers-the-oidc-issue", "881: mycelium login auto-discovers the OIDC issuer from the hub", "fix-881", 68),
  generalPing("work/888-markdown-headings-are-uppercased-and-the-bod", "task-888", "m46-0", 68),
  generalPing("work/886-activity-feed-needs-real-coalescing-group-kn", "task-886", "m47-0", 68),
  generalNotice("resolved", "work/888-markdown-headings-are-uppercased-and-the-bod", "888: markdown headings are uppercased and the body styling looks poor", "task-888", 68),
  generalNotice("claimed", "work/888-markdown-headings-are-uppercased-and-the-bod", "888: markdown headings are uppercased and the body styling looks poor", "task-888", 67),
  generalPing("work/888-markdown-headings-are-uppercased-and-the-bod", "task-888", "m53-0", 67),
  generalPing("work/889-channel-ping-notice-rendering-slug-instead-o", "task-889", "m54-0", 65),
  generalPing("work/860-retire-the-negotiate-pane-channel-board-netw", "fix-860", "m55-0", 65),
  generalPing("work/860-retire-the-negotiate-pane-channel-board-netw", "fix-860", "m58-0", 65),
  generalPing("work/889-channel-ping-notice-rendering-slug-instead-o", "task-889", "m59-0", 63),
  generalPing("work/889-channel-ping-notice-rendering-slug-instead-o", "task-889", "m59-1", 63),
  generalPing("work/872-every-memory-can-be-discussed-widen-thread-m", "task-872", "m60-0", 63),
  generalNotice("resolved", "work/889-channel-ping-notice-rendering-slug-instead-o", "889: channel ping/notice rendering — slug instead of title, ragged type", "task-889", 63),
  generalPing("work/860-retire-the-negotiate-pane-channel-board-netw", "fix-860", "m63-0", 63),
  generalNotice("resolved", "work/860-retire-the-negotiate-pane-channel-board-netw", "860: retire the Negotiate pane — Channel · Board · Network", "fix-860", 63),
  generalPing("work/887-task-view-has-a-double-scroll-one-scroll-col", "task-887", "m67-0", 62),
  generalPing("work/872-every-memory-can-be-discussed-widen-thread-m", "task-872", "m69-0", 62),
  generalNotice("resolved", "work/872-every-memory-can-be-discussed-widen-thread-m", "872: every memory can be discussed", "task-872", 62),
  generalPing("work/887-task-view-has-a-double-scroll-one-scroll-col", "operator@example.com", "m73-0", 60),
  generalPing("work/887-task-view-has-a-double-scroll-one-scroll-col", "operator@example.com", "m73-1", 60),
  generalPing("work/887-task-view-has-a-double-scroll-one-scroll-col", "operator@example.com", "m73-2", 60),
  generalNotice("claimed", "work/888-markdown-headings-are-uppercased-and-the-bod", "888: markdown headings are uppercased and the body styling looks poor", "task-888", 6),
];

const generalKnowledgePushes: MockMessage[] = [
  generalKnowledge("agents/task-886", "claude-web", 86),
  generalKnowledge("work/886-activity-feed-needs-real-coalescing-group-kn", "task-886", 86),
  generalKnowledge("work/886-activity-feed-needs-real-coalescing-group-kn", "task-886", 86),
  generalKnowledge("agents/task-887", "claude-web", 81),
  generalKnowledge("work/887-task-view-has-a-double-scroll-one-scroll-col", "task-887", 81),
  generalKnowledge("work/887-task-view-has-a-double-scroll-one-scroll-col", "task-887", 80),
  generalKnowledge("agents/task-888", "claude-web", 80),
  generalKnowledge("agents/task-889", "claude-web", 80),
  generalKnowledge("work/888-markdown-headings-are-uppercased-and-the-bod", "task-888", 79),
  generalKnowledge("agents/task-872", "claude-web", 79),
  generalKnowledge("work/888-markdown-headings-are-uppercased-and-the-bod", "task-888", 78),
  generalKnowledge("work/872-every-memory-can-be-discussed-widen-thread-m", "task-872", 78),
  generalKnowledge("work/872-every-memory-can-be-discussed-widen-thread-m", "task-872", 78),
  generalKnowledge("work/889-channel-ping-notice-rendering-slug-instead-o", "task-889", 77),
  generalKnowledge("work/889-channel-ping-notice-rendering-slug-instead-o", "task-889", 77),
  generalKnowledge("agents/fix-860", "claude-web", 75),
  generalKnowledge("work/860-retire-the-negotiate-pane-channel-board-netw", "fix-860", 74),
  generalKnowledge("work/860-retire-the-negotiate-pane-channel-board-netw", "fix-860", 74),
  generalKnowledge("work/886-activity-feed-needs-real-coalescing-group-kn", "claude-web", 69),
  generalKnowledge("work/888-markdown-headings-are-uppercased-and-the-bod", "claude-web", 69),
  generalKnowledge("work/881-mycelium-login-auto-discovers-the-oidc-issue", "claude-web", 69),
  generalKnowledge("work/881-mycelium-login-auto-discovers-the-oidc-issue", "fix-881", 68),
  generalKnowledge("work/888-markdown-headings-are-uppercased-and-the-bod", "claude-web", 68),
  generalKnowledge("work/888-markdown-headings-are-uppercased-and-the-bod", "task-888", 68),
  generalKnowledge("work/886-activity-feed-needs-real-coalescing-group-kn", "claude-web", 67),
  generalKnowledge("work/888-markdown-headings-are-uppercased-and-the-bod", "task-888", 67),
  generalKnowledge("work/860-retire-the-negotiate-pane-channel-board-netw", "claude-web", 65),
  generalKnowledge("work/889-channel-ping-notice-rendering-slug-instead-o", "claude-web", 65),
  generalKnowledge("work/889-channel-ping-notice-rendering-slug-instead-o", "task-889", 63),
  generalKnowledge("work/860-retire-the-negotiate-pane-channel-board-netw", "fix-860", 63),
  generalKnowledge("work/889-channel-ping-notice-rendering-slug-instead-o", "claude-web", 63),
  generalKnowledge("work/872-every-memory-can-be-discussed-widen-thread-m", "claude-web", 62),
  generalKnowledge("work/872-every-memory-can-be-discussed-widen-thread-m", "task-872", 62),
  generalKnowledge("work/887-task-view-has-a-double-scroll-one-scroll-col", "claude-web", 61),
  generalKnowledge("work/888-markdown-headings-are-uppercased-and-the-bod", "task-888", 6),
];

/** A ping in mycelium-general's `live`, naming the thread that moved. */
function generalPing(key: string, sender: string, message: string, minutesAgo: number): Record<string, unknown> {
  const episode = generalEpisode(`t${key.replace(/^work\/(\d+)-.*$/, "$1")}`);
  return {
    id: `gp-${message}`,
    sender_handle: "system",
    message_type: "l9_exchange",
    created_at: iso(minutesAgo),
    room_name: "mycelium-general",
    episode: GENERAL_LIVE,
    content: {
      l9: {
        header: { kind: "exchange", message: { id: `gp-${message}`, parents: [], episode: GENERAL_LIVE } },
        payload: { type: "ping", data: { episode, sender, message } },
      },
    },
  };
}

/** A board event in mycelium-general's `live`. */
function generalNotice(
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
    room_name: "mycelium-general",
    episode: GENERAL_LIVE,
    content: {
      l9: {
        header: { kind: "exchange", message: { id, parents: [], episode: GENERAL_LIVE } },
        payload: {
          type: "notice",
          data: {
            subkind,
            key,
            title,
            episode: generalEpisode(`t${key.replace(/^work\/(\d+)-.*$/, "$1")}`),
            by,
            ...(subkind === "filed" ? { kind: "action" } : {}),
          },
        },
      },
    },
  };
}

/** A memory push, as the persister announces one into the room. */
function generalKnowledge(key: string, updatedBy: string, minutesAgo: number): MockMessage {
  return {
    id: `gk-${key}-${minutesAgo}`,
    sender_handle: "system",
    message_type: "l9_knowledge",
    created_at: iso(minutesAgo),
    episode: GENERAL_LIVE,
    content: JSON.stringify({
      content: `memory updated → ${key}`,
      l9: { payload: { type: "extraction", data: { key, updated_by: updatedBy, version: 3 } } },
    }),
  };
}

/** The little that was actually said out loud while all of that went past. */
const generalSaid: MockMessage[] = [
  {
    id: "gs-1",
    sender_handle: "operator@example.com",
    message_type: "broadcast",
    created_at: iso(70),
    episode: GENERAL_LIVE,
    content: "Is mycelium login now becoming an interactive terminal flow when it wasn't before?",
  },
  {
    id: "gs-2",
    sender_handle: "operator@example.com",
    message_type: "broadcast",
    created_at: iso(30),
    episode: GENERAL_LIVE,
    content: "Which of these is actually blocked on me? I can't tell from here.",
  },
  {
    id: "gs-3",
    sender_handle: "operator@example.com",
    message_type: "broadcast",
    created_at: iso(8),
    episode: GENERAL_LIVE,
    content: "Let's get 886 in first — the rest of this is unreadable until it lands.",
  },
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
const generalBacklog: MockMessage[] = Array.from({ length: 260 }, (_, i) => {
  const said = [
    "Rebased onto main; the compose smoke build is green again.",
    "The presence lease expiring mid-turn is what dropped that reply, not SLIM.",
    "Reindexed after the import, search is answering for the new rows now.",
    "Anyone else seeing the aligner take two rounds to notice the agreement?",
    "That was a stale .env, config apply and it picked the model up.",
  ];
  // The backlog is attributed to handles that are actually in the room — the one
  // operator and a handful of registered agents — so replaying it does not mint
  // phantom "people" who only ever appear as a backlog sender.
  const senders = ["operator@example.com", "task-872", "fix-860", "task-888", "task-889", "task-886"];
  return {
    id: `gb-${i}`,
    sender_handle: senders[i % senders.length],
    message_type: "broadcast",
    created_at: iso(60 * 26 - i * 5),
    episode: GENERAL_LIVE,
    content: said[i % said.length],
  };
});

const general: RoomFixture = {
  room: {
    id: 4,
    name: "mycelium-general",
    created_at: iso(60 * 96),
    is_public: true,
    is_persistent: true,
    mas_id: "mas_9f3c02de",
  },
  memories: [...generalMemories, ...generalExtraAgentMemories, ...generalExtraMemories],
  messages: [...generalBacklog, ...generalKnowledgePushes, ...generalSaid].sort(
    (a, b) => Date.parse(a.created_at) - Date.parse(b.created_at),
  ),
  episodes: [],
  episodeDetails: {},
  l9: generalL9,
  // A handful live or awaiting; the rest of the swarm reads as idle. This is what
  // splits the roster into its lifecycle groups.
  presence: [
    { handle: "task-937", kind: "slim", last_seen: null },
    { handle: "fix-940", kind: "slim", last_seen: null },
    { handle: "fix-941", kind: "slim", last_seen: null },
    { handle: "task-944", kind: "slim", last_seen: null },
    { handle: "task-888", kind: "slim", last_seen: null },
    { handle: "task-931", kind: "lease", last_seen: iso(2) },
    { handle: "task-934", kind: "lease", last_seen: iso(4) },
    { handle: "task-947", kind: "lease", last_seen: iso(1) },
    { handle: "aligner", kind: "lease", last_seen: iso(5) },
  ],
};

export const ROOM_FIXTURES: Record<string, RoomFixture> = {
  "atlas-migration": atlas,
  "pricing-model": pricing,
  "mycelium-general": general,
  scratch,
};

export const ROOMS: MockRoom[] = Object.values(ROOM_FIXTURES).map((f) => f.room);

export function getRoomFixture(name: string): RoomFixture | undefined {
  return ROOM_FIXTURES[name];
}

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
