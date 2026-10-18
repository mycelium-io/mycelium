// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Pausing, resuming and stopping agents in the mock app: the hub's
 * `/rooms/{room}/agents/{handle}/pause|resume|stop` and `/agents/pause|resume|paused`,
 * held in memory. Only an agent's owner may, as on the hub.
 */

import type { AgentPause } from "@/lib/api";
import { ROOM_FIXTURES, type RoomFixture } from "./fixtures";

type Pause = { by: string; at: string };

const store = globalThis as { __myceliumMockPauses?: Map<string, Map<string, Pause>> };
const PAUSES = (store.__myceliumMockPauses ??= new Map());

function json(body: unknown, status = 200): Response {
  return Response.json(body, { status });
}

function ownerOf(fx: RoomFixture, handle: string): { found: boolean; owner: string | null } {
  const manifest = fx.memories.find((m) => m.key === `agents/${handle}`);
  if (!manifest) return { found: false, owner: null };
  const raw =
    typeof manifest.value === "string"
      ? /^owner:\s*['"]?@?([\w.-]+)/m.exec(manifest.value)?.[1]
      : (manifest.value.owner as string | undefined);
  return { found: true, owner: raw ? raw.replace(/^@/, "").toLowerCase() : null };
}

function agentsOf(fx: RoomFixture): string[] {
  return fx.memories
    .map((m) => /^agents\/([^/]+)$/.exec(m.key)?.[1])
    .filter((h): h is string => Boolean(h));
}

function result(room: string, handle: string) {
  const p = PAUSES.get(room)?.get(handle);
  return { room, handle, paused: p ? { room, handle, ...p } : null, runner: null, job: null };
}

function apply(room: string, handle: string, verb: string, by: string) {
  const held = PAUSES.get(room) ?? new Map<string, Pause>();
  PAUSES.set(room, held);
  if (verb === "pause" && !held.has(handle)) held.set(handle, { by, at: new Date().toISOString() });
  if (verb === "resume" || verb === "stop") held.delete(handle);
  return result(room, handle);
}

/** The room's paused agents, for its members read. */
export function pausedIn(room: string): AgentPause[] {
  return [...(PAUSES.get(room) ?? new Map<string, Pause>())].map(([handle, p]) => ({ handle, ...p }));
}

/** POST /rooms/{room}/agents/{handle}/{verb}. */
export function controlOne(
  fx: RoomFixture,
  room: string,
  handle: string,
  verb: string,
  by: string,
): Response {
  const { found, owner } = ownerOf(fx, handle);
  if (!found) return json({ detail: `@${handle} isn't an agent in ${room}.` }, 404);
  if (owner && owner !== by) {
    return json({ detail: `Only @${owner}, who owns @${handle}, can pause, resume or stop it.` }, 403);
  }
  return json(apply(room, handle, verb, by));
}

/** /agents/pause, /agents/resume and /agents/paused: every agent `by` owns. */
export function controlMine(method: string, verb: string, by: string): Response | null {
  const mine = Object.entries(ROOM_FIXTURES).flatMap(([room, fx]) =>
    agentsOf(fx)
      .filter((h) => ownerOf(fx, h).owner === by)
      .map((handle) => ({ room, handle })),
  );
  if (verb === "paused" && method === "GET") {
    return json(
      mine.flatMap(({ room, handle }) => {
        const p = PAUSES.get(room)?.get(handle);
        return p ? [{ room, handle, ...p }] : [];
      }),
    );
  }
  if ((verb === "pause" || verb === "resume") && method === "POST") {
    const acted = mine
      .filter(({ room, handle }) => verb === "pause" || PAUSES.get(room)?.has(handle))
      .map(({ room, handle }) => apply(room, handle, verb, by));
    return json({ agents: acted });
  }
  return null;
}
