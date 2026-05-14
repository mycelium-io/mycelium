// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Tick stash: latest coordination_tick payload observed per agent, keyed by
 * agentId. Captured every time the channel SSE delivers a tick (overwrite —
 * latest wins), used by `session/before_agent_start` to inject the full
 * payload (current_offer keys, valid_keys on error ticks, etc.) into the
 * agent's prompt.
 *
 * Why a stash and not an HTTP fetch?
 *
 * The channel module already holds the parsed tick when it dispatches the
 * formatted instruction to the agent. Having `before_agent_start` re-query
 * the backend by parent room (the prior design) doesn't work — ticks are
 * attached to the CoordinationSession, not to any room. Rather than teach
 * the session module to resolve coord-session display names and walk the
 * `/api/coordination-sessions/{id}/messages` endpoint, we mirror the
 * existing return-address pattern: channel observes once, stashes, session
 * reads back.
 *
 * Keying:
 *   - Return-address keys by (sessionRoom, agentId) because consensus
 *     delivery has both in hand at lookup time.
 *   - Tick stash keys by agentId alone — `before_agent_start` has the
 *     agentId but not the session sub-room. If an agent ever participates
 *     in two concurrent negotiations (not supported today), latest wins,
 *     which is also what the prompt should reflect.
 */

type Logger = { info: (s: string) => void; warn: (s: string) => void };

export type StashedTick = {
  sessionRoom: string;
  payload: any;
  receivedAt: number;
};

const _stash = new Map<string, StashedTick>();

export function stashTick(
  agentId: string,
  sessionRoom: string,
  payload: any,
  log: Logger,
): void {
  _stash.set(agentId, { sessionRoom, payload, receivedAt: Date.now() });
  const round = payload?.round ?? "?";
  log.info(`[mycelium-room] tick stashed: ${agentId} ← round ${round} (${sessionRoom})`);
}

export function lookupTick(agentId: string): StashedTick | undefined {
  return _stash.get(agentId);
}

/**
 * Drop any stashed ticks associated with a given session sub-room. Called
 * when the session reaches a terminal state and SSE is torn down — same
 * lifecycle point that clears the return-address stash.
 */
export function clearTickStashBySessionRoom(sessionRoom: string): void {
  for (const [agentId, entry] of _stash) {
    if (entry.sessionRoom === sessionRoom) _stash.delete(agentId);
  }
}

export function clearAllTickStash(): void {
  _stash.clear();
}

/** Test/debug helper. */
export function _allStashedTicks(): Map<string, StashedTick> {
  return _stash;
}
