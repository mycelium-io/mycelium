// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors
/**
 * IDs of messages we posted, used to skip them when they echo back through
 * the SSE stream. Mutated by the router (which calls `.delete()` on match)
 * and by `postToRoom` (which calls `.add()` after a successful POST).
 *
 * Exported so route.ts can inspect it at routing time and tests can pass a
 * fresh Set.
 */
export const _ownMessageIds = new Set();
export async function postToRoom(cfg, senderHandle, content, targetRoom = cfg.room) {
    const url = `${cfg.backendUrl}/api/rooms/${encodeURIComponent(targetRoom)}/messages`;
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
                if (body?.id)
                    _ownMessageIds.add(body.id);
            }
            catch {
                /* non-fatal */
            }
        }
        return res.ok;
    }
    catch {
        return false;
    }
}
