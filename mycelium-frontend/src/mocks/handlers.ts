// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The mock request router: maps an incoming `/api/*` request to a fixture-backed
 * JSON response, mirroring the real backend's routes (see `src/lib/api.ts`).
 *
 * Returns `null` when nothing matches, so the caller (the `/api/[...path]` proxy)
 * falls through — a route we haven't mocked simply 404s rather than hanging.
 * The SSE stream is handled separately in `stream.ts`.
 */

import {
  BACKEND_METRICS,
  ROOMS,
  ROOM_FIXTURES,
  USAGE_KPIS,
  getRoomFixture,
  usageKpis,
} from "./fixtures";
import {
  getJob,
  getRunner,
  launchedHandles,
  listJobs,
  listRunners,
  queueJob,
  runnerAgentOf,
} from "./runners";
import type { MockMemory, MockMessage, RoomFixture } from "./fixtures";
import { demoOnLaunch, demoOnMessage, demoOnTask, isDemoScenario } from "./demo";
import {
  LEARN_PERSON,
  LEARN_TEAMMATE,
  isLearnScenario,
  learnOnLaunch,
  learnOnMessage,
  learnOnSwarm,
  learnOnTask,
  learnOnThreadRead,
} from "./learn";
import { memoryChangedFrame, noticeFrame, publish } from "./live";
import { mockMessageSearch } from "./message-search";
import { PATTERN_ROOMS, fromExplorer, patternList, patternRead } from "./patterns";
import type { A2aBridgeState, MemoryGraph, MemoryGraphEdge, MemoryLink, Protocol } from "@/lib/api";
import type { SearchHit, SearchResultType } from "@/lib/search";

/** One item of a POST /memory batch, as the editor sends it. */
interface MockMemoryWrite {
  key: string;
  value: string | Record<string, unknown>;
  content_text?: string;
  tags?: string[];
  base_version?: number;
  meta?: Record<string, unknown>;
}

const EMPTY_GRAPH: MemoryGraph = { nodes: [], edges: [] };

/** A memory's text for search: its prose value, or `content_text` when the
 *  value is an object. */
const memText = (m: MockMemory): string =>
  m.content_text ?? (typeof m.value === "string" ? m.value : "");

/** A memory's manifest source — only the string-valued `agents/*` memories have
 *  one; object-valued rows return empty so the manifest regexes see no match. */
/** Rooms whose status has been read once. The first read of each is answered
 *  cold, so the mock passes through the same resolving state a real one does. */
const statusWarmed = new Set<string>();

const manifestText = (m: MockMemory): string => (typeof m.value === "string" ? m.value : "");

/** The backend's built-in flows (`protocols.BUILTIN_PROTOCOLS`), as its route lists them. */
const MOCK_PROTOCOLS: Protocol[] = [
  {
    name: "accord",
    description:
      "Get on the same page. Agree what the task is, what's out of scope, what done means and what the key words mean, before work starts.",
    roles: ["lead"],
  },
  {
    name: "concord",
    description:
      "Help them agree. Everyone suggests, everyone rates, the least happy agent suggests a fix, until one option clears the bar for all.",
    roles: [],
  },
  { name: "fan-out", description: "A lead asks every worker at once, then combines what came back.", roles: ["lead"] },
  {
    name: "gated",
    description: "A proposer proposes, a guardian approves or blocks; a block sends it back.",
    roles: ["proposer", "guardian"],
  },
  {
    name: "review",
    description:
      "An author does the work, a reviewer checks it against evidence; findings go back until the reviewer approves.",
    roles: ["author", "reviewer"],
  },
  { name: "round-robin", description: "Every member speaks in turn, for a fixed number of rounds.", roles: [] },
  {
    name: "swarm",
    description: "A team kicks off a task: each member checks in, then the lead splits the work.",
    roles: ["lead"],
  },
].map((p) => ({ ...p, source: "builtin" as const }));

/** A graph edge's `raw` markdown, synthesized for display — the fixtures only
 *  need to carry the parsed shape (source/target/kind), not the literal text. */
function synthesizeRaw(edge: MemoryGraphEdge): string {
  if (edge.kind === "transclusion") return `![[${edge.target}]]`;
  if (edge.kind === "uri") return `myc://${edge.target}`;
  if (edge.kind === "relation") return `${edge.relation ?? "relates-to"}: [[${edge.target}]]`;
  return `[[${edge.target}]]`;
}

/** The backward cursor's test, as the backend applies it: strictly before, and
 *  a row with no readable stamp is kept rather than filtered out. */
function olderThan(stamp: string | undefined, before: string | null): boolean {
  if (!before) return true;
  const at = Date.parse(stamp ?? "");
  const cursor = Date.parse(before);
  if (Number.isNaN(at) || Number.isNaN(cursor)) return true;
  return at < cursor;
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const notFound = (detail: string): Response => json({ detail }, 404);

/** The epoch a fixture with no timestamp of its own is dated to. */
const MOCK_EPOCH = new Date(0).toISOString();

/**
 * A UUID derived from a string, so a memory keeps the same id across requests
 * without every fixture carrying one. Not cryptographic — it only has to be
 * stable, distinct, and shaped like the ids the store issues.
 */
/** A board notice on the stream, kept in the room's replay so a reload shows it. */
function publishNotice(fx: RoomFixture, room: string, data: Parameters<typeof noticeFrame>[1]): void {
  const frame = { ...noticeFrame(room, data), created_at: new Date().toISOString() };
  (fx.l9 ??= []).push(frame);
  publish(room, frame);
}

/** A task's key fragment, as `services/tasks.py:slugify` makes it. */
function slug(title: string): string {
  const s = title.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48).replace(/-+$/, "");
  return s || "task";
}

function stableUuid(seed: string): string {
  let hash = 0x811c9dc5;
  const digits: string[] = [];
  for (let i = 0; i < 32; i++) {
    hash ^= seed.charCodeAt(i % seed.length) + i;
    hash = Math.imul(hash, 0x01000193) >>> 0;
    digits.push((hash % 16).toString(16));
  }
  const hex = digits.join("");
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20, 32)].join("-");
}

/**
 * A fixture memory in the backend's `MemoryRead` shape. `id`, `room_name` and
 * `created_at` are required by the spec and derived here rather than repeated
 * across every fixture, the same way the real store derives them.
 */
function memoryRead(room: string, memory: MockMemory): Record<string, unknown> {
  const updated = memory.updated_at ?? MOCK_EPOCH;
  return {
    ...memory,
    id: stableUuid(`${room}/${memory.key}`),
    room_name: memory.room_name ?? room,
    created_at: updated,
    updated_at: updated,
  };
}

/** A room with no A2A bridge: no bridged members, no traffic — but still served
 *  as an A2A agent of its own, since every room's card is reachable. */
function emptyBridge(room: string): A2aBridgeState {
  return {
    room,
    agents: [],
    exchanges: [],
    outbound_ok: 0,
    outbound_failed: 0,
    exposure: {
      card_url: `http://localhost:8000/api/rooms/${room}/.well-known/agent-card.json`,
      rpc_url: `http://localhost:8000/api/rooms/${room}/a2a`,
      skills: [],
      card_fetches: 0,
      messages: 0,
      last_card_fetch_at: null,
      last_message_at: null,
    },
  };
}

/** A canned expansion of a member's brief, naming one of the room's agents as its reviewer. */
function mockNotesDraft(brief: string, fx: RoomFixture): string {
  const mate = fx.memories
    .map((m) => m.key.match(/^agents\/([^/]+)$/)?.[1])
    .find(Boolean);
  const said = brief.replace(/[.\s]+$/, "");
  return [
    `Your job here: ${said}. That is what you own in this room; leave the rest to its owners.`,
    "",
    "- Take tasks for this off the board, claim one before you start, and work it in its own thread.",
    "- Post what you did and what you found in that thread, briefly, with file and line where it helps.",
    mate
      ? `- Ask @${mate} to review before you resolve a task, and say plainly what you want them to check.`
      : "- Ask a teammate to review before you resolve a task, and say plainly what you want them to check.",
    "- When something is unclear or outside what you own, ask in the thread rather than guessing.",
    "",
    "A good result is one a teammate can pick up without asking you anything.",
  ].join("\n");
}

async function readJson(req: Request): Promise<Record<string, unknown>> {
  try {
    return (await req.json()) as Record<string, unknown>;
  } catch {
    return {};
  }
}

/** `/api/runners/...`, answered from `./runners`. */
async function handleRunners(req: Request, method: string, rest: string[]): Promise<Response | null> {
  if (rest.length === 0) return method === "GET" ? json(listRunners()) : null;
  const runner = getRunner(decodeURIComponent(rest[0]));
  if (!runner) return notFound("Runner not found");
  const [, sub, a, b, c] = rest;
  if (sub === undefined) return method === "GET" ? json(runner) : null;
  if (sub === "jobs" && method === "GET") {
    if (a === undefined) return json(listJobs(runner.id));
    const job = getJob(runner.id, decodeURIComponent(a));
    return job ? json(job) : notFound("Job not found");
  }
  if (sub === "scan" && method === "POST") return json(queueJob(runner.id, "scan", {}), 201);
  if (sub === "restart" && method === "POST") {
    const body = await readJson(req);
    return json(queueJob(runner.id, "restart", { all: Boolean(body.all), agents: body.agents ?? [] }), 201);
  }
  if (sub === "agents" && method === "POST") {
    if (a !== undefined && b !== undefined && c === "stop") {
      const spec = { room: decodeURIComponent(a), handle: decodeURIComponent(b) };
      return json(queueJob(runner.id, "stop", spec), 201);
    }
    if (a !== undefined) return null;
    const body = await readJson(req);
    const handle = String(body.handle ?? "");
    if (!/^[a-z0-9][a-z0-9_-]*$/.test(handle)) {
      return json({ detail: "Handle must be a lowercase slug (a-z, 0-9, '-', '_') starting alphanumeric." }, 422);
    }
    if (!runner.herdr) {
      return json({ detail: `herdr isn't running on ${runner.label}, so it can't start agents.` }, 422);
    }
    const framework = runner.frameworks.find((f) => f.id === body.framework);
    if (!framework?.installed || !framework.launchable) {
      return json({ detail: `${String(body.framework)} isn't an agent CLI ${runner.label} can start.` }, 422);
    }
    const spec = {
      room: String(body.room ?? ""),
      handle,
      framework: framework.id,
      cwd: typeof body.cwd === "string" ? body.cwd : runner.roots[0],
    };
    const job = queueJob(runner.id, "launch", spec, typeof body.created_by === "string" ? body.created_by : null);
    const fx = isDemoScenario() ? getRoomFixture(spec.room) : undefined;
    if (fx) demoOnLaunch(fx, spec.room, handle);
    const lfx = isLearnScenario() ? getRoomFixture(spec.room) : undefined;
    if (lfx) learnOnLaunch(lfx, spec.room, handle, spec.cwd ?? null);
    return json(job, 201);
  }
  return null;
}

/**
 * The hub's user records: the people in the fixtures, named, and anyone the
 * app adds (the first-load "What should we call you?"), kept in memory until
 * the mock restarts.
 */
const MOCK_USERS = new Map<string, { handle: string; display_name: string; teams: string[]; notify: string | null; owns: never[] }>(
  [
    ["operator", "Morgan Reyes"],
    ["ada@example.com", "Ada Lindqvist"],
    ["june@example.com", "June Park"],
    ...(isLearnScenario()
      ? [
          [LEARN_PERSON.handle, LEARN_PERSON.name],
          [LEARN_TEAMMATE.handle, LEARN_TEAMMATE.name],
        ]
      : []),
  ].map(([handle, display_name]) => [handle, { handle, display_name, teams: [], notify: null, owns: [] }]),
);

async function handleUsers(req: Request, method: string, rest: string[]): Promise<Response | null> {
  if (rest.length === 0 && method === "GET") {
    return json({ users: [...MOCK_USERS.values()], total: MOCK_USERS.size });
  }
  if (rest.length === 0 && method === "POST") {
    const body = await readJson(req);
    const handle = String(body.handle ?? "").trim().toLowerCase();
    if (!handle) return json({ detail: "handle is required" }, 422);
    const user = {
      handle,
      display_name: String(body.display_name ?? ""),
      teams: Array.isArray(body.teams) ? (body.teams as string[]) : [],
      notify: (body.notify as string | null) ?? null,
      owns: [] as never[],
    };
    MOCK_USERS.set(handle, user);
    return json(user, 201);
  }
  if (rest.length === 1 && method === "GET") {
    const user = MOCK_USERS.get(decodeURIComponent(rest[0]).toLowerCase());
    return user ? json(user) : notFound("no such user (mock)");
  }
  if (rest.length === 2 && rest[1] === "room-folders") {
    const handle = decodeURIComponent(rest[0]).toLowerCase();
    if (method === "GET") return json(MOCK_ROOM_FOLDERS.get(handle) ?? { folders: [] });
    if (method === "PUT") {
      const body = await readJson(req);
      const layout = { folders: Array.isArray(body.folders) ? body.folders : [] };
      MOCK_ROOM_FOLDERS.set(handle, layout);
      return json(layout);
    }
  }
  return notFound("unknown users route (mock)");
}

/** Each person's room folders, kept until the mock restarts. Everyone starts
 *  with none, so the rooms list looks as it always has until someone files one. */
const MOCK_ROOM_FOLDERS = new Map<string, { folders: unknown[] }>();

export async function handleMock(req: Request): Promise<Response | null> {
  const { pathname, searchParams } = new URL(req.url);
  const method = req.method.toUpperCase();
  // Normalize: drop a trailing slash, split into segments after `/api`.
  const segs = pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  if (segs[0] !== "api") return null;
  const rest = segs.slice(1); // e.g. ["rooms", "checkout", "plan"]

  // ── /api/observability ──────────────────────────────────────────────────────
  if (rest[0] === "observability") {
    if (rest.length === 1) return json(BACKEND_METRICS);
    if (rest[1] === "usage") {
      const days = Number(searchParams.get("days")) || USAGE_KPIS.days;
      return json(usageKpis(Math.min(Math.max(days, 1), 365)));
    }
    return notFound("unknown observability route (mock)");
  }

  // ── /api/users ──────────────────────────────────────────────────────────────
  if (rest[0] === "users") return handleUsers(req, method, rest.slice(1));

  // ── /api/runners ────────────────────────────────────────────────────────────
  if (rest[0] === "runners") return handleRunners(req, method, rest.slice(1));

  // ── /api/patterns ───────────────────────────────────────────────────────────
  if (rest[0] === "patterns") {
    if (rest.length === 1 && method === "GET") return json(patternList());
    const name = decodeURIComponent(rest[1] ?? "");
    const read = patternRead(name);
    if (!read) return notFound(`No pattern named '${name}' (mock)`);
    if (rest.length === 2 && method === "GET") return json(read);
    if (rest[2] === "load" && method === "POST") {
      // A mock has no conductor to run it, so loading answers with the room the
      // pattern already ran in, or says what it would make.
      const ran = PATTERN_ROOMS[name];
      return json(
        {
          room: name,
          title: read.title,
          members: [],
          memories: [],
          summon: null,
          key: ran?.room.pattern_task ?? null,
          episode: null,
          ran: Boolean(ran),
          dry_run: false,
        },
        201,
      );
    }
    return null;
  }

  // ── /health ─────────────────────────────────────────────────────────────────
  if (rest[0] === "health")
    return json({
      status: "ok",
      mock: true,
      version: "3.0.13",
      coordination: {
        endpoint: "http://mycelium-slim:46357",
        slim_enabled: true,
        channels_live: 2,
        provisions_ok: 2,
        provisions_failed: 0,
        invite_failures: 0,
        rooms: [
          {
            room: "checkout",
            provisioned: true,
            persister_alive: true,
            members: ["builder", "reviewer"],
            deferred_invites: 1,
            episode_active: true,
            reserves: 3,
            reserve_failures: 0,
            reserve_skipped: 0,
            receive_errors: 0,
            transient_errors: 0,
          },
          {
            room: "subscription-pricing",
            provisioned: true,
            persister_alive: true,
            members: [],
            deferred_invites: 0,
            episode_active: false,
            reserves: 0,
            reserve_failures: 0,
            reserve_skipped: 0,
            receive_errors: 0,
            transient_errors: 0,
          },
        ],
      },
      // The default posture a fresh install runs on: PSK channel identity, HTTP
      // API gate off.
      identity: { status: "ok", mode: "psk", message: "psk" },
      auth: { enabled: false, issuers: [], localhost_bypass: true, audience: null },
    });

  // ── /api/search ─────────────────────────────────────────────────────────────
  if (rest[0] === "search" && method === "GET") {
    return json(mockSearch(searchParams.get("q") ?? "", Number(searchParams.get("limit") ?? "20")));
  }

  if (rest[0] !== "rooms") return null;

  // ── /api/rooms ──────────────────────────────────────────────────────────────
  if (rest.length === 1) {
    if (method === "GET") {
      // A private room is listed only for its owner and members, as on the hub.
      const viewer = (searchParams.get("viewer") ?? "").toLowerCase();
      // The rooms patterns ran in are listed to the explorer alone, so the rest
      // of the app keeps the rooms its screenshots show.
      const listed = fromExplorer(req) ? [...ROOMS, ...Object.values(PATTERN_ROOMS).map((f) => f.room)] : ROOMS;
      return json(
        listed.filter(
          (r) => r.is_public || (!!viewer && (r.owner === viewer || (r.members ?? []).includes(viewer))),
        ),
      );
    }
    if (method === "POST") {
      const body = await readJson(req);
      const name = String(body.name ?? "new-room");
      const isPublic = body.is_public !== false;
      // 201, like the real route.
      return json(
        {
          id: ROOMS.length + 1,
          name,
          created_at: MOCK_EPOCH,
          is_public: isPublic,
          is_persistent: true,
          mas_id: null,
          owner: body.owner ?? null,
          members: [],
        },
        201,
      );
    }
    return null;
  }

  // Everything below is room-scoped: /api/rooms/:name/...
  const roomName = decodeURIComponent(rest[1]);
  const fx = getRoomFixture(roomName);
  const sub = rest.slice(2); // e.g. ["plan"], ["memory"], ["episodes", "e4f1a2"]

  // GET /api/rooms/:name
  if (sub.length === 0) {
    if (!fx) return notFound(`room ${roomName} not found (mock)`);
    if (method === "PATCH") {
      // Session-local, like the rest of the mock's writes.
      const body = await readJson(req);
      if (typeof body.is_public === "boolean") {
        fx.room.is_public = body.is_public;
        if (!body.is_public && !fx.room.owner) fx.room.owner = String(body.by ?? "") || null;
      }
      return json(fx.room);
    }
    if (method !== "GET") return null;
    return json(fx.room);
  }

  if (!fx) return notFound(`room ${roomName} not found (mock)`);

  switch (sub[0]) {
    case "memory": {
      // POST /memory/search
      if (sub[1] === "search" && method === "POST") {
        const body = await readJson(req);
        const q = String(body.query ?? "").toLowerCase();
        const hits = fx.memories
          .map((m, i) => ({
            memory: m,
            score: memText(m).toLowerCase().includes(q) ? 0.92 - i * 0.05 : 0,
          }))
          .filter((r) => r.score > 0)
          .slice(0, 10);
        // Fall back to the top few so search always shows *something* to design against.
        const chosen = hits.length ? hits : fx.memories.slice(0, 3).map((m, i) => ({ memory: m, score: 0.7 - i * 0.1 }));
        return json({
          results: chosen.map((r) => ({ memory: memoryRead(roomName, r.memory), similarity: r.score })),
          total: chosen.length,
        });
      }
      // POST /memory — create or upsert one or more memories. Mirrors the real
      // route closely enough to exercise the editor: optimistic-concurrency
      // rejection, tag replacement, and the expandable frontmatter flag.
      if (sub.length === 1 && method === "POST") {
        const body = await req.json() as { items?: MockMemoryWrite[] };
        const items = body.items ?? [];

        for (const item of items) {
          const existing = fx.memories.find((m) => m.key === item.key);
          const currentVersion = existing?.version ?? 0;
          if (item.base_version !== undefined && item.base_version !== currentVersion) {
            return json({
              error: "stale_base",
              message: `Write for '${item.key}' expected version ${item.base_version} but current version is ${currentVersion}`,
              key: item.key,
              current_version: currentVersion,
            }, 409);
          }
        }

        const written: MockMemory[] = [];
        for (const item of items) {
          const text = typeof item.value === "string" ? item.value : (item.value.text as string ?? "");
          const idx = fx.memories.findIndex((m) => m.key === item.key);
          const now = new Date().toISOString();
          const next: MockMemory = {
            ...(idx >= 0 ? fx.memories[idx] : { key: item.key, created_by: "user", version: 0 }),
            value: text,
            content_text: item.content_text ?? text,
            version: (idx >= 0 ? fx.memories[idx].version : 0) + 1,
            updated_at: now,
            // tags and expandable are replaced on every write, not merged —
            // the real store treats both as managed frontmatter.
            tags: item.tags,
            expandable: Boolean(item.meta?.expandable),
          };
          if (idx >= 0) fx.memories[idx] = next; else fx.memories.push(next);
          written.push(next);
        }
        return json(
          written.map((m) => memoryRead(roomName, m)),
          201,
        );
      }
      // DELETE /memory/:key — removes the file; 404 when nothing was there.
      if (sub.length > 1 && method === "DELETE") {
        const key = sub.slice(1).map(decodeURIComponent).join("/");
        const index = fx.memories.findIndex((m) => m.key === key);
        if (index < 0) return notFound(`memory ${key} not found (mock)`);
        fx.memories.splice(index, 1);
        return new Response(null, { status: 204 });
      }
      if (method !== "GET") return null;
      // GET /memory/:key — the key is a path, so it spans the remaining segments.
      if (sub.length > 1) {
        const key = sub.slice(1).map(decodeURIComponent).join("/");
        const index = fx.memories.findIndex((m) => m.key === key);
        return index >= 0
          ? json(memoryRead(roomName, fx.memories[index]))
          : notFound(`memory ${key} not found (mock)`);
      }
      // GET /memory?prefix=
      const prefix = searchParams.get("prefix");
      return json(
        fx.memories
          .map((m) => memoryRead(roomName, m))
          .filter((m) => !prefix || String(m.key).startsWith(prefix)),
      );
    }

    case "status": {
      if (method !== "GET") return null;
      const resolved = fx.status ?? {
        room: roomName,
        field: "upstream",
        providers: ["github"],
        refs: [],
        rows: {},
        refreshing: false,
      };
      // A Learn take opens on a board the hub has already looked up.
      if (resolved.refs.length > 0 && !statusWarmed.has(roomName) && !isLearnScenario()) {
        statusWarmed.add(roomName);
        return json({
          ...resolved,
          refs: resolved.refs.map(ref => ({
            ...ref,
            state: null,
            label: null,
            freshness: "missing" as const,
            age_seconds: null,
          })),
          refreshing: true,
        });
      }
      return json(resolved);
    }

    case "messages": {
      // GET /messages/l9 — the L9 wire feed for the Network pane, and the half
      // of the channel's feed that carries pings and board notices. Oldest
      // first, the last `limit` of what is older than the cursor — the shape
      // the backend's transcript replay serves.
      // GET /messages/search — the find bar's History.
      if (sub[1] === "search" && method === "GET") {
        return json(mockMessageSearch(fx, searchParams.get("q") ?? "", Number(searchParams.get("limit") ?? "20")));
      }
      if (sub[1] === "l9" && method === "GET") {
        const limit = Number(searchParams.get("limit") ?? "200");
        const before = searchParams.get("before");
        const frames = (fx.l9 ?? []).filter((f) => olderThan(f.created_at as string | undefined, before));
        return json(limit > 0 ? frames.slice(-limit) : frames);
      }
      if (method === "GET") {
        // The backend serves newest-first; the UI reverses to oldest-first.
        const limit = Number(searchParams.get("limit") ?? "0");
        // `?episode=` narrows to one conversation — a thread, or the room's own
        // `live` URN. Exact-match, as the backend filters, so the mock can't let
        // a thread pane pass while the real read returns everything.
        const episode = searchParams.get("episode");
        // `?before=` is the backward cursor the channel walks by. Filtered
        // before the count, as the backend counts it — `total` is what is older
        // than the cursor, which is how a reader knows it has reached the start.
        const before = searchParams.get("before");
        if (episode && isLearnScenario()) learnOnThreadRead(fx, roomName, episode);
        const scoped = fx.messages.filter(
          (m) => (!episode || m.episode === episode) && olderThan(m.created_at, before),
        );
        const ordered = [...scoped].reverse();
        const messages = limit > 0 ? ordered.slice(0, limit) : ordered;
        return json({ messages, total: scoped.length });
      }
      if (method === "POST") {
        // Stored and put on the stream, as the hub does: the channel only ever
        // appends what arrives live, and a thread refetches when its episode moves.
        const body = await readJson(req);
        const msg: MockMessage = {
          id: `sent-${fx.messages.length + 1}`,
          sender_handle: String(body.sender_handle ?? "operator"),
          message_type: String(body.message_type ?? "broadcast"),
          content: String(body.content ?? ""),
          episode: typeof body.episode === "string" ? body.episode : null,
          created_at: new Date().toISOString(),
        };
        fx.messages.push(msg);
        publish(roomName, { ...msg, room_name: roomName });
        if (isDemoScenario()) demoOnMessage(fx, roomName, msg);
        if (isLearnScenario()) learnOnMessage(fx, roomName, msg);
        return json(msg, 201);
      }
      return null;
    }

    case "tasks": {
      // POST /tasks — a row and its thread, minted together (services/tasks.py).
      if (sub.length !== 1 || method !== "POST") return null;
      const body = await readJson(req);
      const title = String(body.title ?? "").trim();
      if (!title) return json({ detail: "A task needs a title." }, 422);
      const by = String(body.handle ?? "user");
      const key = typeof body.key === "string" && body.key ? body.key : `work/${slug(title)}`;
      if (fx.memories.some((m) => m.key === key)) return json({ detail: `${key} already exists` }, 409);
      const assignee = typeof body.assignee === "string" && body.assignee ? body.assignee.replace(/^@/, "") : null;
      const kind = key.startsWith("decisions/") ? "decision" : "action";
      const row: MockMemory = {
        key,
        value: title,
        content_text: title,
        meta: { kind, status: "open", ...(assignee ? { assignee } : {}) },
        created_by: by,
        updated_by: by,
        version: 1,
        updated_at: new Date().toISOString(),
        episode: `urn:ioc:mycelium:episode:${roomName}:${stableUuid(`${roomName}/${key}/${Date.now()}`).replace(/-/g, "").slice(0, 8)}`,
      };
      fx.memories.push(row);
      publish(roomName, memoryChangedFrame(key, 1, by));
      publishNotice(fx, roomName, {
        subkind: "filed", key, title: title.split("\n")[0], episode: row.episode, by, kind, for: assignee ?? undefined,
      });
      if (isDemoScenario()) demoOnTask(fx, roomName, row);
      if (isLearnScenario()) learnOnTask(fx, roomName, row);
      return json(memoryRead(roomName, row), 201);
    }

    case "fields": {
      // POST /fields — a row's frontmatter, merged (a board action or an edit).
      if (sub.length !== 1 || method !== "POST") return null;
      const body = await readJson(req);
      const key = String(body.key ?? "");
      const row = fx.memories.find((m) => m.key === key);
      if (!row) return notFound(`memory ${key} not found (mock)`);
      const fields = (body.fields ?? {}) as Record<string, unknown>;
      const by = String(body.handle ?? "user");
      row.meta = { ...(row.meta ?? {}), ...fields };
      row.version += 1;
      row.updated_at = new Date().toISOString();
      row.updated_by = by;
      publish(roomName, memoryChangedFrame(key, row.version, by));
      if (fields.status === "resolved") {
        publishNotice(fx, roomName, { subkind: "resolved", key, title: memText(row).split("\n")[0], episode: row.episode, by });
      }
      return json({ key, fields, version: row.version });
    }

    case "assignments": {
      // POST /assignments/{claim|release|resolve} — who holds a row.
      const action = sub[1];
      if (sub.length !== 2 || method !== "POST" || !["claim", "release", "resolve"].includes(action)) return null;
      const body = await readJson(req);
      const key = String(body.key ?? "");
      const row = fx.memories.find((m) => m.key === key);
      if (!row) return notFound(`memory ${key} not found (mock)`);
      const by = String(body.handle ?? "user");
      const at = new Date().toISOString();
      const patch: Record<string, unknown> =
        action === "claim"
          ? { assignment: "held", owner: `@${by}`, claimed_at: at, ttl_minutes: 120 }
          : action === "release"
            ? { assignment: "released", owner: null, claimed_at: null }
            : { assignment: "resolved", status: "resolved" };
      row.meta = { ...(row.meta ?? {}), ...patch };
      row.version += 1;
      row.updated_at = at;
      row.updated_by = by;
      publish(roomName, memoryChangedFrame(key, row.version, by));
      const subkind = action === "claim" ? "claimed" : action === "release" ? "released" : "resolved";
      publishNotice(fx, roomName, { subkind, key, title: memText(row).split("\n")[0], episode: row.episode, by });
      const meta = row.meta as Record<string, unknown>;
      return json({
        key,
        assignment: meta.assignment,
        owner: meta.owner ?? null,
        claimed_at: meta.claimed_at ?? null,
        ttl_minutes: meta.ttl_minutes ?? null,
        freshness: action === "claim" ? "fresh" : null,
        version: row.version,
        assignment_note: null,
        assignment_note_by: null,
      });
    }

    case "engines": {
      // POST /engines — an engine the hub runs, registered as its manifest.
      if (sub.length !== 1 || method !== "POST") return null;
      const body = await readJson(req);
      const handle = String(body.handle ?? "").trim().toLowerCase();
      const kind = String(body.kind ?? "");
      if (!/^[a-z0-9][a-z0-9_-]*$/.test(handle)) return json({ detail: "Handle must be a lowercase slug." }, 422);
      if (!kind) return json({ detail: "An engine needs a kind." }, 422);
      const key = `agents/${handle}`;
      if (fx.memories.some((m) => m.key === key)) return json({ detail: `@${handle} is already in ${roomName}` }, 409);
      const by = String(body.created_by ?? "user");
      const description = String(body.description ?? "");
      fx.memories.push({
        key,
        value: `adapter: engine\nkind: ${kind}\ndescription: "${description}"\n`,
        created_by: by,
        version: 1,
        updated_at: new Date().toISOString(),
      });
      fx.presence = [...(fx.presence ?? []).filter((p) => p.handle !== handle), { handle, kind: "lease", last_seen: new Date().toISOString() }];
      publish(roomName, memoryChangedFrame(key, 1, by));
      return json(
        {
          handle, adapter: "engine", kind, description, cwd: null, owner: by, team: null, allow_from: [],
          a2a_card: null, a2a_endpoint: null, a2a_skills: [], runner: null, framework: null,
        },
        201,
      );
    }

    case "swarms": {
      // POST /swarms — a team put on a task. Only a Learn take plays one; the
      // default fixtures have no workers to run it.
      if (sub.length !== 1 || method !== "POST") return null;
      const started = isLearnScenario() ? learnOnSwarm(fx, roomName) : null;
      if (!started) return json({ detail: "The mock runs no swarms in this room." }, 501);
      return json({ room: roomName, ...started, job: null }, 201);
    }

    case "agents": {
      // POST /agents/draft-notes — the hub's model expanding a brief; here a
      // canned expansion that keeps what was typed.
      if (sub[1] === "draft-notes" && method === "POST") {
        const body = await readJson(req);
        const brief = String(body.brief ?? "").trim();
        if (!brief) return json({ detail: "Say what the agent is for first." }, 422);
        return json({ notes: mockNotesDraft(brief, fx) });
      }
      // Agents are `agents/<handle>` memories whose body is a YAML manifest —
      // the same projection the backend's agents route does.
      if (method !== "GET") return null;
      const agents = fx.memories
        .filter((m) => m.key.startsWith("agents/") && !m.key.slice(7).includes("/"))
        .map((m) => {
          const manifest = manifestText(m);
          return {
            handle: m.key.slice(7),
            adapter: /adapter:\s*(\S+)/.exec(manifest)?.[1] ?? "claude_code",
            kind: /kind:\s*(\S+)/.exec(manifest)?.[1] ?? null,
            description: /description:\s*"?([^"\n]*)"?/.exec(manifest)?.[1] ?? "",
            cwd: null,
            owner: /owner:\s*@?(\S+)/.exec(manifest)?.[1] ?? null,
            team: /team:\s*(\S+)/.exec(manifest)?.[1] ?? null,
            allow_from: [],
            a2a_card: /a2a_card:\s*(\S+)/.exec(manifest)?.[1] ?? null,
            a2a_endpoint: /a2a_endpoint:\s*(\S+)/.exec(manifest)?.[1] ?? null,
            a2a_skills:
              /a2a_skills:\s*\[([^\]]*)\]/
                .exec(manifest)?.[1]
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean) ?? [],
            runner: runnerAgentOf(roomName, m.key.slice(7))?.runner ?? null,
            framework: runnerAgentOf(roomName, m.key.slice(7))?.framework ?? null,
          };
        });
      // An agent started from the app is registered by the hub; the fixtures
      // don't carry its manifest, so it is listed from the machine instead.
      const listed = new Set(agents.map((a) => a.handle));
      for (const l of launchedHandles(roomName)) {
        if (listed.has(l.handle)) continue;
        agents.push({
          handle: l.handle,
          adapter: "claude_code",
          kind: null,
          description: "",
          cwd: null,
          owner: "operator",
          team: null,
          allow_from: [],
          a2a_card: null,
          a2a_endpoint: null,
          a2a_skills: [],
          runner: l.runner,
          framework: l.framework,
        });
      }
      return json(agents);
    }

    case "protocols": {
      // GET /protocols — the flows a conductor summon can name, as the
      // backend's built-ins describe them. Mock rooms write no protocols/.
      if (sub.length !== 1 || method !== "GET") return null;
      return json(MOCK_PROTOCOLS);
    }

    case "skills": {
      // GET /skills — the composer's `/` autocomplete. A skill is a `skills/…`
      // memory promoted, so this is the same projection the backend's skills
      // route makes: the name is the key past the prefix, the one-line
      // description is frontmatter, the body is what follows it. Served here
      // so a mock room never falls through to a real backend (#755).
      if (sub.length !== 1 || method !== "GET") return null;
      const skills = fx.memories
        .filter((m) => m.key.startsWith("skills/"))
        .map((m) => {
          const text = manifestText(m);
          const fm = /^---\n([\s\S]*?)\n---\n?/.exec(text);
          const description = fm ? /^description:\s*"?(.*?)"?\s*$/m.exec(fm[1])?.[1] ?? "" : "";
          const body = fm ? text.slice(fm[0].length).replace(/^\n+/, "") : text;
          const updated = m.updated_at ?? MOCK_EPOCH;
          return {
            name: m.key.slice("skills/".length),
            description,
            body,
            tags: m.tags ?? null,
            created_by: m.created_by,
            updated_by: m.updated_by ?? null,
            version: m.version,
            created_at: updated,
            updated_at: updated,
          };
        });
      return json({ skills, total: skills.length });
    }

    case "a2a": {
      // GET /a2a/state — the Network pane's bridge strip. A room with no
      // bridge answers with an empty one, exactly like the backend does.
      if (sub[1] !== "state" || method !== "GET") return null;
      return json(fx.a2a ?? emptyBridge(roomName));
    }

    case "links": {
      if (method !== "GET") return null;
      const graph = fx.links ?? EMPTY_GRAPH;
      // GET /links/graph — the whole room, for the full-page graph view (#599).
      if (sub[1] === "graph") return json(graph);
      // GET /links/integrity — derived from the same edge list rather than
      // hand-written, so a fixture can't claim a room is clean while its graph
      // shows a break.
      if (sub[1] === "integrity") {
        return json({
          broken: graph.edges
            .filter((e) => !e.resolved)
            .map((e) => ({ source: e.source, target: e.target, kind: e.kind, resolved: false, error: e.error, raw: synthesizeRaw(e) })),
          // Sorted, like the backend's `integrity()`, so a consumer that ever
          // relies on the order sees the same thing here as in production.
          // orphan = inbound===0 AND outbound===0 (fully isolated)
          // root   = inbound===0 AND outbound>0  (entry point)
          // leaf   = inbound>0  AND outbound===0 (dead end)
          orphans: graph.nodes.filter((n) => n.inbound === 0 && n.outbound === 0).map((n) => n.key).sort(),
          roots: graph.nodes.filter((n) => n.inbound === 0 && n.outbound > 0).map((n) => n.key).sort(),
          leaves: graph.nodes.filter((n) => n.inbound > 0 && n.outbound === 0).map((n) => n.key).sort(),
          total_memories: graph.nodes.length,
          total_links: graph.edges.length,
        });
      }
      // GET /links/expand?key=... — depth-1 transclusion, mirroring the
      // backend: a marker expands only when its target exists, and is left
      // exactly as written when it doesn't.
      if (sub[1] === "expand") {
        const key = searchParams.get("key");
        const source = fx.memories.find((m) => m.key === key);
        if (!key || !source) return json({ key: key ?? "", rendered: "", expansions: [], found: false });
        const expansions: Array<{ raw: string; target: string; resolved: boolean }> = [];
        const rendered = (source.content_text ?? "").replace(/!\[\[([^\]]+)\]\]/g, (raw, target: string) => {
          const embedded = fx.memories.find((m) => m.key === target);
          expansions.push({ raw, target, resolved: Boolean(embedded) });
          return embedded?.content_text ?? raw;
        });
        return json({ key, rendered, expansions, found: true });
      }
      // GET /links?key=... — one memory's outbound links + backlinks (#611),
      // read off the same edge list the graph draws from.
      const key = searchParams.get("key");
      if (!key) return notFound("missing key (mock)");
      const outbound: MemoryLink[] = graph.edges
        .filter((e) => e.source === key)
        .map((e) => ({ target: e.target, kind: e.kind, relation: e.relation, resolved: e.resolved, error: e.error, raw: synthesizeRaw(e) }));
      const backlinks: MemoryLink[] = graph.edges
        .filter((e) => e.target === key && e.resolved)
        .map((e) => ({ target: key, source: e.source, kind: e.kind, relation: e.relation, resolved: true, raw: synthesizeRaw(e) }));
      return json({ outbound, backlinks });
    }

    case "sessions": {
      // Presence: a room's fixture may name resident members (there is no SLIM
      // node here to report them), which the board projects into resident rows.
      if (sub[1] === "members" && method === "GET") {
        return json({ members: fx.presence ?? [], floors: fx.floors ?? [] });
      }
      return null;
    }

    case "episodes": {
      // GET /episodes/:shortId
      if (sub[1] && method === "GET") {
        const detail = fx.episodeDetails[decodeURIComponent(sub[1])];
        return detail ? json(detail) : notFound("episode not found (mock)");
      }
      if (method === "GET") return json({ episodes: fx.episodes });
      return null;
    }

    default:
      return null;
  }
}

// ── /api/search ───────────────────────────────────────────────────────────────

/**
 * A fixture-backed stand-in for the backend's cross-entity search.
 *
 * It follows the same grammar (`#room`, `@handle`, `<type>:`, `kind:`) and
 * returns the same shape, so the search surface can be designed against every
 * result type with no hub. The scoring is deliberately cruder than the real
 * thing — substring hits, no embeddings — since what it exists to exercise is
 * the surface, not the ranking.
 */
const TYPE_TOKENS: Record<string, SearchResultType> = {
  memory: "memory", memories: "memory", mem: "memory",
  episode: "episode", episodes: "episode", ep: "episode",
  message: "message", messages: "message", msg: "message",
  room: "room", rooms: "room",
  agent: "agent", agents: "agent",
};

function mockSearch(raw: string, limit: number) {
  const rooms: string[] = [];
  const actors: string[] = [];
  const types: SearchResultType[] = [];
  const kinds: string[] = [];
  const words: string[] = [];

  for (const token of raw.split(/\s+/).filter(Boolean)) {
    if (token.startsWith("#") && token.length > 1) { rooms.push(token.slice(1).toLowerCase()); continue; }
    if (token.startsWith("@") && token.length > 1) { actors.push(token.slice(1).toLowerCase()); continue; }
    const at = token.indexOf(":");
    if (at > 0) {
      const prefix = token.slice(0, at).toLowerCase();
      const restText = token.slice(at + 1);
      if (prefix === "kind") { if (restText) kinds.push(restText.toLowerCase()); continue; }
      if (prefix in TYPE_TOKENS) {
        types.push(TYPE_TOKENS[prefix]);
        if (restText) words.push(restText.toLowerCase());
        continue;
      }
    }
    words.push(token.toLowerCase());
  }

  const scope = { text: words.join(" "), rooms, actors, types, kinds };
  const wants = (t: SearchResultType) => types.length === 0 || types.includes(t);
  const inScope = (room: string) => rooms.length === 0 || rooms.includes(room);
  const byActor = (...handles: (string | null | undefined)[]) =>
    actors.length === 0 || handles.some((h) => h && actors.includes(h.replace(/^@/, "").toLowerCase()));

  // Every term must land somewhere, and the label is worth more than the body.
  const score = (label: string, body: string): number => {
    if (words.length === 0) return 0.2;
    let total = 0;
    for (const w of words) {
      if (label.toLowerCase() === w) total += 3;
      else if (label.toLowerCase().includes(w)) total += 2;
      else if (body.toLowerCase().includes(w)) total += 1;
    }
    return total / (3 * words.length);
  };

  const hits: SearchHit[] = [];
  const push = (hit: SearchHit) => { if (hit.score > 0) hits.push(hit); };

  for (const fx of Object.values(ROOM_FIXTURES)) {
    const room = fx.room.name;
    if (!inScope(room)) continue;

    // A room has no kind and no author, so either scope rules it out.
    if (wants("room") && actors.length === 0 && kinds.length === 0) {
      push({ type: "room", room, id: room, title: room, subtitle: fx.room.mas_id ?? "",
        snippet: "", kind: null, timestamp: fx.room.created_at, score: score(room, "") });
    }

    if (wants("memory")) {
      for (const m of fx.memories) {
        if (!byActor(m.updated_by, m.created_by)) continue;
        const text = memText(m);
        // A memory's kind is its namespace, matching the backend.
        const namespace = m.key.includes("/") ? m.key.slice(0, m.key.lastIndexOf("/")) : "";
        if (kinds.length && !kinds.includes(namespace.toLowerCase())) continue;
        push({ type: "memory", room, id: m.key, title: m.key,
          subtitle: namespace ? `${room} · ${namespace}` : room, snippet: text.slice(0, 160),
          kind: namespace || null, timestamp: m.updated_at ?? "", score: score(m.key, text) });
      }
    }

    if (wants("episode")) {
      for (const ep of fx.episodes) {
        const state = ep.subkind ?? ep.outcome;
        if (kinds.length && !kinds.includes(state.toLowerCase())) continue;
        if (!byActor(...ep.participants)) continue;
        push({ type: "episode", room, id: ep.short_id, title: `episode ${ep.short_id}`,
          subtitle: `${room} · ${state} · ${ep.message_count} msg`, snippet: ep.participants.join(", "),
          kind: state, timestamp: ep.updated_at, score: score(ep.short_id, `${ep.topic} ${state} ${ep.participants.join(" ")}`) });
      }
    }

    if (wants("message")) {
      for (const msg of fx.messages) {
        if (!byActor(msg.sender_handle, msg.recipient_handle)) continue;
        if (kinds.length && !kinds.includes(msg.message_type.toLowerCase())) continue;
        push({ type: "message", room, id: msg.id, title: msg.content.slice(0, 160),
          subtitle: `${room} · @${msg.sender_handle}`, snippet: msg.content.slice(0, 160),
          kind: msg.message_type, timestamp: msg.created_at, score: score(msg.sender_handle, msg.content) });
      }
    }

    if (wants("agent")) {
      for (const m of fx.memories.filter((x) => x.key.startsWith("agents/"))) {
        const handle = m.key.slice("agents/".length);
        if (handle.includes("/")) continue;
        if (actors.length && !actors.includes(handle.toLowerCase())) continue;
        // An agent's kind is its engine kind, falling back to its adapter.
        const manifest = manifestText(m);
        const adapter = /adapter:\s*(\S+)/.exec(manifest)?.[1] ?? "claude_code";
        if (kinds.length && !kinds.includes(adapter.toLowerCase())) continue;
        push({ type: "agent", room, id: handle, title: handle, subtitle: `${room} · ${adapter}`,
          snippet: manifest, kind: adapter, timestamp: "", score: score(handle, manifest) });
      }
    }
  }

  const counts: Record<string, number> = {};
  for (const hit of hits) counts[hit.type] = (counts[hit.type] ?? 0) + 1;
  hits.sort((a, b) => b.score - a.score || b.timestamp.localeCompare(a.timestamp));

  return { query: raw, scope, results: hits.slice(0, limit), counts };
}
