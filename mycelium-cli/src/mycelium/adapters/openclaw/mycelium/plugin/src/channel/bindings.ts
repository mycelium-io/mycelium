// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Per-agent room bindings.
 *
 * Background: the channel plugin originally subscribed to a single fixed
 * `cfg.room` (e.g. "mycelium_room") for SSE push and tick dispatch. That worked
 * for the case the plugin was designed for — long-lived shared rooms — but
 * broke for dynamic per-test rooms ("dist-e2e-<uuid>"). When an agent was
 * mentioned in a Matrix message that asked them to join a dynamic Mycelium
 * room, the plugin had no mechanism to learn about that room, so the
 * coordination push path was silent and agents fell back to polling via
 * `mycelium session await` (which deadlocks under OpenClaw's exec/yield model
 * and is explicitly banned by the plugin's own SKILL.md).
 *
 * This module is the per-agent room registry. The session module's
 * `message_received` handler extracts a room name from the inbound prompt
 * text and calls `bindAgentToRoom(agentId, room)`. The channel module's
 * session-sub-room poll consults `getAllBoundRooms()` to know which parent
 * rooms to watch for `:session:` sub-rooms.
 *
 * Bindings are additive: once an agent is bound to a room we keep watching
 * it until gateway stop, so cross-test stragglers can still wake up. Memory
 * footprint is bounded by the number of distinct test rooms a gateway sees
 * in its lifetime.
 */

const _agentRooms = new Map<string, Set<string>>();

/**
 * Register that `agentId` is participating in `room`. Idempotent. Returns
 * true if this is a new binding (caller may want to log or kick a poll),
 * false if the binding already existed.
 */
export function bindAgentToRoom(agentId: string, room: string): boolean {
  if (!agentId || !room) return false;
  let rooms = _agentRooms.get(agentId);
  if (!rooms) {
    rooms = new Set<string>();
    _agentRooms.set(agentId, rooms);
  }
  if (rooms.has(room)) return false;
  rooms.add(room);
  return true;
}

/**
 * Most-recently-bound room for the given agent (if any). Used by
 * before_agent_start to know which room's latest tick to pull into the
 * agent's prompt context. Falls back to undefined if no binding has been
 * recorded — caller is expected to fall back to channelCfg.room.
 */
export function getMostRecentRoomForAgent(agentId: string): string | undefined {
  const rooms = _agentRooms.get(agentId);
  if (!rooms || rooms.size === 0) return undefined;
  // Set iteration is insertion-ordered — last() = newest binding.
  let last: string | undefined;
  for (const r of rooms) last = r;
  return last;
}

/** All rooms across all agents — used by the channel poll to widen its watch set. */
export function getAllBoundRooms(): Set<string> {
  const all = new Set<string>();
  for (const rooms of _agentRooms.values()) {
    for (const r of rooms) all.add(r);
  }
  return all;
}

/** Rooms a specific agent is currently bound to (defensive copy). */
export function getRoomsForAgent(agentId: string): Set<string> {
  return new Set(_agentRooms.get(agentId) ?? []);
}

/** Reset all bindings — called from gateway_stop. Tests may call this too. */
export function clearAllBindings(): void {
  _agentRooms.clear();
}
