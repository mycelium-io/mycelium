// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Mirrors OpenClaw's buildAgentPeerSessionKey format for group peers.
 * See openclaw src/routing/session-key.ts.
 *
 * Format:  agent:{agentId}:{channel}:group:{peerId}
 * Example: agent:julia-agent:mycelium-room:group:my-project
 */

import { CHANNEL_ID } from "./config.js";

export function buildSessionKey(agentId: string, room: string): string {
  return `agent:${agentId.toLowerCase()}:${CHANNEL_ID}:group:${room.toLowerCase()}`;
}
