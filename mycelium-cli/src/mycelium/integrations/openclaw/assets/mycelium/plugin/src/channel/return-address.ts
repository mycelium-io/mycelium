// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Return-address stash: per-(sessionSubRoom, agent) record of where the agent
 * was active at the moment they joined the negotiation. Captured once on
 * `coordination_join`, used at `coordination_consensus` to deliver the result
 * back to whatever home channel the agent kicked the negotiation off from.
 *
 * Why "freeze at join time"?
 *
 * If we lookup the agent's most-recent session at consensus time, the answer
 * could have drifted (the user may have ping'd that agent on a different
 * channel mid-negotiation). Capturing at join time is deterministic for this
 * negotiation: whoever woke the agent to run `mycelium session join` is the
 * channel/conversation we want to deliver the consensus to.
 *
 * Source of truth: `~/.openclaw/agents/<agentId>/sessions/sessions.json`. We
 * scan it once at join time, find the most recent non-mycelium-room session,
 * and stash `lastChannel` / `lastTo` / `lastAccountId`. These are exactly the
 * fields the OpenClaw outbound adapters expect on `sendText({to, accountId})`.
 *
 * Limitations:
 *   - Gateway restart loses the stash. Document, then escalate to disk
 *     persistence if it bites.
 *   - Race: if the agent receives a different-channel inbound between
 *     "user types in matrix" and "plugin observes coordination_join", the
 *     stash will point at the wrong channel. Tight window in practice.
 */

import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

import { CHANNEL_ID } from "../config.js";

type Logger = { info: (s: string) => void; warn: (s: string) => void };

export type ReturnAddress = {
  channelName: string;
  to: string;
  accountId: string;
};

const _stash = new Map<string, Map<string, ReturnAddress>>();

function stashKey(sessionRoom: string): string {
  return sessionRoom;
}

/**
 * Read the agent's session store and pick the most-recent non-mycelium-room
 * session entry. Returns its delivery context, or undefined if none found.
 */
export function readHomeAddress(agentId: string, log: Logger): ReturnAddress | undefined {
  const path = join(homedir(), ".openclaw", "agents", agentId, "sessions", "sessions.json");
  let raw: string;
  try {
    raw = readFileSync(path, "utf-8");
  } catch {
    log.info(`[mycelium-room] no session store for ${agentId} at ${path}`);
    return undefined;
  }
  let store: any;
  try {
    store = JSON.parse(raw);
  } catch (err: any) {
    log.warn(`[mycelium-room] sessions.json parse error for ${agentId}: ${err?.message ?? err}`);
    return undefined;
  }
  let best:
    | { entry: any; updatedAt: number }
    | undefined;
  for (const entry of Object.values(store)) {
    const e = entry as any;
    const channel = e?.lastChannel ?? e?.deliveryContext?.channel;
    const to = e?.lastTo ?? e?.deliveryContext?.to;
    const accountId = e?.lastAccountId ?? e?.deliveryContext?.accountId;
    if (!channel || !to) continue;
    if (channel === CHANNEL_ID) continue;
    const updatedAt = typeof e.updatedAt === "number" ? e.updatedAt : 0;
    if (!best || updatedAt > best.updatedAt) {
      best = { entry: { channel, to, accountId }, updatedAt };
    }
  }
  if (!best) return undefined;
  return {
    channelName: best.entry.channel,
    to: best.entry.to,
    accountId: best.entry.accountId ?? "default",
  };
}

/**
 * Capture the agent's home channel at join time. Idempotent — if we've
 * already stashed for this (room, agent) pair, leave the original alone.
 */
export function stashReturnAddress(
  sessionRoom: string,
  agentId: string,
  log: Logger,
): void {
  const key = stashKey(sessionRoom);
  let perAgent = _stash.get(key);
  if (!perAgent) {
    perAgent = new Map();
    _stash.set(key, perAgent);
  }
  if (perAgent.has(agentId)) return;
  const addr = readHomeAddress(agentId, log);
  if (!addr) {
    log.info(
      `[mycelium-room] return-address: no home channel for ${agentId} on join — will skip notify-home`,
    );
    return;
  }
  perAgent.set(agentId, addr);
  log.info(
    `[mycelium-room] return-address stashed: ${agentId} → ${addr.channelName}:${addr.to}`,
  );
}

export function lookupReturnAddress(
  sessionRoom: string,
  agentId: string,
): ReturnAddress | undefined {
  return _stash.get(stashKey(sessionRoom))?.get(agentId);
}

export function clearReturnAddresses(sessionRoom: string): void {
  _stash.delete(stashKey(sessionRoom));
}

/** Test/debug helper. */
export function _allReturnAddresses(): Map<string, Map<string, ReturnAddress>> {
  return _stash;
}
