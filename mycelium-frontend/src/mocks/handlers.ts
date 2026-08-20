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
import type { SearchHit, SearchResultType } from "@/lib/search";

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const notFound = (detail: string): Response => json({ detail }, 404);

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
      return json({
        id: ROOMS.length + 1,
        name,
        created_at: new Date(0).toISOString(),
        is_public: true,
        is_persistent: true,
        mas_id: null,
        title: null,
      });
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
            score: (m.content_text ?? m.value ?? "").toLowerCase().includes(q) ? 0.92 - i * 0.05 : 0,
          }))
          .filter((r) => r.score > 0)
          .slice(0, 10);
        // Fall back to the top few so search always shows *something* to design against.
        const chosen = hits.length ? hits : fx.memories.slice(0, 3).map((m, i) => ({ memory: m, score: 0.7 - i * 0.1 }));
        return json({ results: chosen.map((r) => ({ memory: r.memory, similarity: r.score })), total: chosen.length });
      }
      if (method !== "GET") return null;
      // GET /memory/:key — the key is a path, so it spans the remaining segments.
      if (sub.length > 1) {
        const key = sub.slice(1).map(decodeURIComponent).join("/");
        const found = fx.memories.find((m) => m.key === key);
        return found ? json(found) : notFound(`memory ${key} not found (mock)`);
      }
      // GET /memory?prefix=
      const prefix = searchParams.get("prefix");
      const items = prefix ? fx.memories.filter((m) => m.key.startsWith(prefix)) : fx.memories;
      return json(items);
    }

    case "plan": {
      // PUT /plan/title
      if (sub[1] === "title" && method === "PUT") {
        const body = await readJson(req);
        return json({ title: String(body.text ?? "") });
      }
      // POST /plan/tasks  (and /plan/tasks/:id/toggle)
      if (sub[1] === "tasks") {
        if (sub[2] && sub[3] === "toggle" && method === "POST") {
          const body = await readJson(req);
          const id = decodeURIComponent(sub[2]);
          const existing = fx.plan.tasks.find((t) => t.id === id);
          return json({ ...(existing ?? { id, slug: "tasks", line: 0, text: "task" }), done: body.done === true });
        }
        if (method === "POST") {
          const body = await readJson(req);
          return json({ id: `t${fx.plan.tasks.length + 1}`, slug: String(body.slug ?? "tasks"), line: 0, text: String(body.text ?? ""), done: false });
        }
      }
      // GET /plan
      if (method === "GET") return json(fx.plan);
      return null;
    }

    case "messages": {
      if (method === "GET") {
        // The backend serves newest-first; the UI reverses to oldest-first.
        const limit = Number(searchParams.get("limit") ?? "0");
        const ordered = [...fx.messages].reverse();
        const messages = limit > 0 ? ordered.slice(0, limit) : ordered;
        return json({ messages, total: fx.messages.length });
      }
      if (method === "POST") {
        const body = await readJson(req);
        return json({
          id: `sent-${fx.messages.length + 1}`,
          sender_handle: String(body.sender_handle ?? "operator"),
          message_type: String(body.message_type ?? "broadcast"),
          content: String(body.content ?? ""),
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
        .map((m) => ({
          handle: m.key.slice(7),
          adapter: /adapter:\s*(\S+)/.exec(m.value)?.[1] ?? "claude_code",
          kind: /kind:\s*(\S+)/.exec(m.value)?.[1] ?? null,
          description: /description:\s*"?([^"\n]*)"?/.exec(m.value)?.[1] ?? "",
          cwd: null,
          owner: /owner:\s*@?(\S+)/.exec(m.value)?.[1] ?? null,
          team: /team:\s*(\S+)/.exec(m.value)?.[1] ?? null,
          allow_from: [],
        }));
      return json(agents);
    }

    case "sessions": {
      // Presence: nobody is live in the fixtures — there is no SLIM node here.
      if (sub[1] === "members" && method === "GET") return json({ members: [] });
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
        const text = m.content_text ?? m.value ?? "";
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
        const adapter = /adapter:\s*(\S+)/.exec(m.value)?.[1] ?? "claude_code";
        if (kinds.length && !kinds.includes(adapter.toLowerCase())) continue;
        push({ type: "agent", room, id: handle, title: handle, subtitle: `${room} · ${adapter}`,
          snippet: m.value, kind: adapter, timestamp: "", score: score(handle, m.value) });
      }
    }
  }

  const counts: Record<string, number> = {};
  for (const hit of hits) counts[hit.type] = (counts[hit.type] ?? 0) + 1;
  hits.sort((a, b) => b.score - a.score || b.timestamp.localeCompare(a.timestamp));

  return { query: raw, scope, results: hits.slice(0, limit), counts };
}
