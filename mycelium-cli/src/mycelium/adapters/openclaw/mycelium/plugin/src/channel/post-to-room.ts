// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Cisco Systems, Inc. and its affiliates

/**
 * Outbound POST to a Mycelium room with echo-loop prevention.
 *
 * Every message we post is tracked by ID in _ownMessageIds. When the SSE
 * stream echoes it back, we recognize it and skip dispatch — otherwise the
 * plugin would try to dispatch its own replies to itself.
 */

import type { ChannelConfig } from "../config.js";

/**
 * IDs of messages we posted, used to skip them when they echo back through
 * the SSE stream. Mutated by the router (which calls `.delete()` on match)
 * and by `postToRoom` (which calls `.add()` after a successful POST).
 *
 * Exported so route.ts can inspect it at routing time and tests can pass a
 * fresh Set.
 */
export const _ownMessageIds = new Set<string>();

export async function postToRoom(
  cfg: ChannelConfig,
  senderHandle: string,
  content: string,
): Promise<boolean> {
  const url = `${cfg.backendUrl}/rooms/${encodeURIComponent(cfg.room)}/messages`;
  try {
    const res = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        content,
        message_type: "broadcast",
        sender_handle: senderHandle,
      }),
    });
    if (res.ok) {
      try {
        const body = await res.json();
        if (body?.id) _ownMessageIds.add(body.id);
      } catch {
        /* non-fatal */
      }
    }
    return res.ok;
  } catch {
    return false;
  }
}
