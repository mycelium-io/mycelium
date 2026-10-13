// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The verifier in the mock app: on for the hub, added to checkout, on its
// starting model. A room's flags come from its fixture; *It's fine* and Learn
// are session-local, like the rest of the mock's writes.

import type { VerifierFlag, VerifierSettings } from "@/lib/api";
import type { RoomFixture } from "./fixtures";
import { noticeFrame, publish } from "./live";

/** How far one read moves a running Learn, so the progress bar is seen to move. */
const LEARN_STEP = 600;

export const VERIFIER: VerifierSettings = {
  enabled: true,
  rooms: ["checkout"],
  model: "BAAI/bge-small-en-v1.5",
  using: "starting",
  learned: null,
  answers_since_learned: 0,
  estimate: { messages: 2431, approx_tokens: 600_000, approx_usd: 1 },
  learning: { state: "idle", done: 0, total: 0, error: null },
};

/** The settings as read now, a running Learn stepped forward once. */
export function verifierSettingsRead(): VerifierSettings {
  const learning = VERIFIER.learning;
  if (learning.state === "running") {
    learning.done = Math.min(learning.total, learning.done + LEARN_STEP);
    if (learning.done >= learning.total) {
      VERIFIER.learning = { ...learning, state: "done" };
      VERIFIER.using = "learned";
      VERIFIER.learned = learning.total;
      VERIFIER.answers_since_learned = 0;
    }
  }
  return { ...VERIFIER, rooms: [...VERIFIER.rooms], learning: { ...VERIFIER.learning } };
}

function json(data: unknown, status = 200): Response {
  return new Response(JSON.stringify(data), { status, headers: { "Content-Type": "application/json" } });
}

/** GET /rooms/{room}/verifier/flags and POST …/flags/{id}/fine. */
export async function handleVerifierFlags(
  req: Request,
  roomName: string,
  fx: RoomFixture,
  sub: string[],
): Promise<Response | null> {
  const flags: VerifierFlag[] = (fx.verifierFlags ??= []);
  if (sub[1] !== "flags") return null;
  if (sub.length === 2 && req.method === "GET") return json(flags);
  if (sub.length === 4 && sub[3] === "fine" && req.method === "POST") {
    const flag = flags.find((f) => f.flag_id === decodeURIComponent(sub[2]));
    if (!flag) return json({ detail: "No such flag in this room" }, 404);
    const body = (await req.json().catch(() => ({}))) as { by?: string };
    flag.state = "fine";
    flag.fine_by = body.by || "someone";
    VERIFIER.answers_since_learned += 1;
    // The same notice the hub raises, so every open channel takes the line away.
    publish(
      roomName,
      noticeFrame(roomName, {
        subkind: "check",
        key: flag.key,
        message_id: flag.message_id,
        flag_id: flag.flag_id,
        state: "fine",
        fine_by: flag.fine_by,
      }),
    );
    return json(flag);
  }
  return null;
}
