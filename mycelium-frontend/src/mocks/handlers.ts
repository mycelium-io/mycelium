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

    case "board": {
      // POST /board/capture → a fresh open concern
      if (sub[1] === "capture" && method === "POST") {
        const body = await readJson(req);
        const text = String(body.text ?? "concern");
        return json(
          { id: "cap1", source: "ledger", kind: "concern", state: "open", title: text, needs_you: true, provenance: "captured by you" },
          201,
        );
      }
      // POST /board/items/:id/:verb → no-op success (fixtures are static)
      if (sub[1] === "items" && sub[2] && sub[3] && method === "POST") {
        return new Response(null, { status: 204 });
      }
      // GET /board → project the plan tasks + a few representative ledger rows
      if (method === "GET") {
        const planRows = fx.plan.tasks.map((t) => ({
          id: `plan:${t.id}`,
          source: "plan",
          kind: "action",
          state: t.done ? "resolved" : "in_progress",
          title: t.text,
          provenance: `plan/${t.slug}.md`,
          needs_you: false,
          note: t.done ? "task complete" : null,
        }));
        const ledgerRows = [
          { id: "d3f", source: "ledger", kind: "decision", state: "open", title: "JWT TTL — 15m or 60m?", choices: ["15m", "60m"], owner: { handle: "agent-y", kind: "agent", present: true }, provenance: "from agent-y", age: "6m", needs_you: true },
          { id: "a91", source: "ledger", kind: "concern", state: "blocked", title: "Enable thin-spoke join", waiting_on: "#502", github: { issue: 502, state: "open" }, age: "40m", needs_you: true },
          { id: "7c2", source: "ledger", kind: "review", state: "in_review", title: "agent-z opened a PR, wants eyes", owner: { handle: "agent-z", kind: "agent", present: true }, work: { branch: "feat/path-fix", pr: { number: 504, state: "open" }, ci: "green" }, provenance: "from agent-z", age: "12m", needs_you: true },
          { id: "e45", source: "ledger", kind: "action", state: "in_progress", title: "Cache TTL sweep", owner: { handle: "julia", kind: "human", present: true }, work: { branch: "feat/cache", ci: "running" }, age: "3m", needs_you: false },
          { id: "b90", source: "ledger", kind: "action", state: "resolved", title: "Fix path traversal in loader", owner: { handle: "agent-z", kind: "agent", present: false }, work: { branch: "fix/traversal", pr: { number: 499, state: "merged" }, ci: "green" }, note: "PR #499 merged", age: "1h", needs_you: false },
        ];
        const items = [...ledgerRows, ...planRows];
        const counts = { needs: 0, flight: 0, resolved: 0 };
        for (const it of items) {
          const lens = it.state === "resolved" ? "resolved" : it.needs_you ? "needs" : "flight";
          counts[lens as "needs" | "flight" | "resolved"] += 1;
        }
        return json({ room: roomName, items, members: ["agent-y", "agent-z", "julia"], counts });
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
