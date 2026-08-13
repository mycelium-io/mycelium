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

import { BACKEND_METRICS, COLLECTOR_METRICS, HOSTS, ROOMS, getRoomFixture } from "./fixtures";

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
            members: ["planner", "julia"],
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
    });

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
      // GET /memory?prefix=
      if (method === "GET") {
        const prefix = searchParams.get("prefix");
        const items = prefix ? fx.memories.filter((m) => m.key.startsWith(prefix)) : fx.memories;
        return json(items);
      }
      return null;
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
