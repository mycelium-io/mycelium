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

import { BACKEND_METRICS, COLLECTOR_METRICS, HOSTS, ROOMS, ROOM_FIXTURES, getRoomFixture } from "./fixtures";
import type { MockMemory } from "./fixtures";
import type { A2aBridgeState, MemoryGraph, MemoryGraphEdge, MemoryLink } from "@/lib/api";
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

/** A memory's text for search/parse: its prose value, or its `content_text`
 *  when the value is a frontmatter object (the board's typed rows). */
const memText = (m: MockMemory): string =>
  m.content_text ?? (typeof m.value === "string" ? m.value : "");

/** A memory's manifest source — only the string-valued `agents/*` memories have
 *  one; object-valued rows return empty so the manifest regexes see no match. */
/** Rooms whose status has been read once. The first read of each is answered
 *  cold, so the mock passes through the same resolving state a real one does. */
const statusWarmed = new Set<string>();

const manifestText = (m: MockMemory): string => (typeof m.value === "string" ? m.value : "");

/** A graph edge's `raw` markdown, synthesized for display — the fixtures only
 *  need to carry the parsed shape (source/target/kind), not the literal text. */
function synthesizeRaw(edge: MemoryGraphEdge): string {
  if (edge.kind === "transclusion") return `![[${edge.target}]]`;
  if (edge.kind === "uri") return `myc://${edge.target}`;
  if (edge.kind === "relation") return `${edge.relation ?? "relates-to"}: [[${edge.target}]]`;
  return `[[${edge.target}]]`;
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

async function readJson(req: Request): Promise<Record<string, unknown>> {
  try {
    return (await req.json()) as Record<string, unknown>;
  } catch {
    return {};
  }
}

export async function handleMock(req: Request): Promise<Response | null> {
  const { pathname, searchParams } = new URL(req.url);
  const method = req.method.toUpperCase();
  // Normalize: drop a trailing slash, split into segments after `/api`.
  const segs = pathname.replace(/\/+$/, "").split("/").filter(Boolean);
  if (segs[0] !== "api") return null;
  const rest = segs.slice(1); // e.g. ["rooms", "atlas-migration", "plan"]

  // ── /api/observability* ─────────────────────────────────────────────────────
  if (rest[0] === "observability") {
    if (rest.length === 1) return json(BACKEND_METRICS);
    if (rest[1] === "collector") return json(COLLECTOR_METRICS);
    if (rest[1] === "hosts") return json({ hosts: HOSTS });
    return notFound("unknown observability route (mock)");
  }

  // ── /health ─────────────────────────────────────────────────────────────────
  if (rest[0] === "health")
    return json({
      status: "ok",
      mock: true,
      coordination: {
        endpoint: "http://mycelium-slim:46357",
        slim_enabled: true,
        channels_live: 2,
        provisions_ok: 2,
        provisions_failed: 0,
        invite_failures: 0,
        rooms: [
          {
            room: "atlas-migration",
            provisioned: true,
            persister_alive: true,
            members: ["planner", "avery"],
            pending_invites: 1,
            episode_active: true,
            reserves: 3,
            reserve_failures: 0,
            reserve_skipped: 0,
            receive_errors: 0,
            transient_errors: 0,
          },
          {
            room: "design-review",
            provisioned: true,
            persister_alive: true,
            members: [],
            pending_invites: 0,
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
    if (method === "GET") return json(ROOMS);
    if (method === "POST") {
      const body = await readJson(req);
      const name = String(body.name ?? "new-room");
      // 201, like the real route.
      return json(
        {
          id: ROOMS.length + 1,
          name,
          created_at: MOCK_EPOCH,
          is_public: true,
          is_persistent: true,
          mas_id: null,
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
    if (method !== "GET") return null;
    return fx ? json(fx.room) : notFound(`room ${roomName} not found (mock)`);
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
      if (resolved.refs.length > 0 && !statusWarmed.has(roomName)) {
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
      // GET /messages/l9 — the L9 wire feed for the Network pane.
      if (sub[1] === "l9" && method === "GET") {
        return json(fx.l9 ?? []);
      }
      if (method === "GET") {
        // The backend serves newest-first; the UI reverses to oldest-first.
        const limit = Number(searchParams.get("limit") ?? "0");
        // `?episode=` narrows to one conversation — a thread, or the room's own
        // `live` URN. Exact-match, as the backend filters, so the mock can't let
        // a thread pane pass while the real read returns everything.
        const episode = searchParams.get("episode");
        const scoped = episode ? fx.messages.filter((m) => m.episode === episode) : fx.messages;
        const ordered = [...scoped].reverse();
        const messages = limit > 0 ? ordered.slice(0, limit) : ordered;
        return json({ messages, total: scoped.length });
      }
      if (method === "POST") {
        const body = await readJson(req);
        return json({
          id: `sent-${fx.messages.length + 1}`,
          sender_handle: String(body.sender_handle ?? "operator"),
          message_type: String(body.message_type ?? "broadcast"),
          content: String(body.content ?? ""),
          episode: body.episode ?? null,
          created_at: new Date(0).toISOString(),
        });
      }
      return null;
    }

    case "agents": {
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
          };
        });
      return json(agents);
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
      if (sub[1] === "members" && method === "GET") return json({ members: fx.presence ?? [] });
      return null;
    }

    case "invites": {
      // POST /invites/:id/accept|decline
      if (sub[1] && (sub[2] === "accept" || sub[2] === "decline") && method === "POST") {
        const id = decodeURIComponent(sub[1]);
        const inv = fx.invites.find((i) => i.id === id);
        return json({ ...(inv ?? { id, room: roomName, agent: "?", requested_by: "?", trigger_text: "", created_at: "" }), status: sub[2] === "accept" ? "accepted" : "declined" });
      }
      if (method === "GET") return json({ invites: fx.invites });
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
