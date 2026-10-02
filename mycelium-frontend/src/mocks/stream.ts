// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Mock SSE for the room message stream.
 *
 * Replays a scripted "live" negotiation so the room's CHANNEL view feels alive
 * during design work — the connection badge goes LIVE, events arrive on a timer,
 * and a consensus lands. Rooms without a scripted timeline just get heartbeats
 * (still LIVE, just quiet). Mirrors the real SSE: each frame is a JSON message
 * object on the default `message` event (see `event-stream.tsx`).
 */

import { subscribe } from "./live";

interface StreamStep {
  delayMs: number;
  message: Record<string, unknown>;
}

// An in-progress negotiation for `subscription-pricing` that resolves while you
// watch. The aligner brokers a real NEGMAS Stacked Alternating Offers
// round-robin over three issues (price, bags, billing); each natural-language
// reply is followed by the aligner's interpreted move as a coordination_tick, so
// the Channel narrates and the Network pane's L9 feed fills in live.
const PRICING_EPISODE = "urn:ioc:mycelium:episode:subscription-pricing:b2d0";
const tick = (id: string, round: number, who: string, action: string, offer: Record<string, string>): StreamStep["message"] => ({
  id,
  sender_handle: "aligner",
  message_type: "coordination_tick",
  content: JSON.stringify({ payload: { round, participant_id: who, action, current_offer: offer } }),
  episode: PRICING_EPISODE,
});
const say = (id: string, who: string, text: string): StreamStep["message"] => ({
  id,
  sender_handle: who,
  message_type: "broadcast",
  content: text,
});
// The "is responding…" signal the backend raises when a participant starts
// generating: a presence-style frame, never a message (see `lib/activity.ts`).
// Each agent line below is preceded by one, and the line itself settles it.
const responding = (who: string, episode: string | null = null): StreamStep["message"] => ({
  type: "agent_activity",
  message_type: "agent_activity",
  handle: who,
  sender_handle: who,
  state: "responding",
  episode,
  ttl_s: 90,
});
const pricingTimeline: StreamStep[] = [
  // Round 1
  { delayMs: 1500, message: say("s1", "growth", "Start at $18 a month for two bags. People need to try it before they commit. @finance") },
  // The aligner's turn lands in the negotiation's thread, not the channel, so
  // the channel names where it is going; the tick that follows settles it.
  { delayMs: 400, message: responding("aligner", PRICING_EPISODE) },
  { delayMs: 1200, message: tick("s2", 1, "growth", "propose", { price: "18", bags: "2", billing: "monthly" }) },
  { delayMs: 600, message: responding("finance") },
  { delayMs: 1600, message: say("s3", "finance", "Two bags cost us $13.30 with shipping. $18 leaves almost nothing. $26.") },
  { delayMs: 1600, message: tick("s4", 1, "finance", "counter", { price: "26", bags: "2", billing: "monthly" }) },
  // Round 2
  { delayMs: 600, message: responding("growth") },
  { delayMs: 1600, message: say("s5", "growth", "Meet me at $20, and I'll push the yearly plan hard.") },
  { delayMs: 1600, message: tick("s6", 2, "growth", "counter", { price: "20", bags: "2", billing: "monthly" }) },
  { delayMs: 600, message: responding("finance") },
  { delayMs: 1600, message: say("s7", "finance", "$22 keeps us at 40%. That's the middle of the market too.") },
  { delayMs: 1600, message: tick("s8", 2, "finance", "counter", { price: "22", bags: "2", billing: "monthly" }) },
  // Round 3: they agree
  { delayMs: 600, message: responding("growth") },
  { delayMs: 1600, message: say("s9", "growth", "Deal. $22 a month for two bags.") },
  { delayMs: 1500, message: tick("s10", 3, "growth", "accept", { price: "22", bags: "2", billing: "monthly" }) },
  { delayMs: 1400, message: tick("s11", 3, "finance", "accept", { price: "22", bags: "2", billing: "monthly" }) },
  { delayMs: 1800, message: { id: "s12", sender_handle: "backend", message_type: "coordination_consensus", content: JSON.stringify({ plan: "subscription price agreed", assignments: { price: "22", bags: "2", billing: "monthly" }, plan_file: "plan/tasks.md", episode: PRICING_EPISODE, metrics: { gar: 0.86 } }), episode: PRICING_EPISODE } },
];

const TIMELINES: Record<string, StreamStep[]> = {
  "subscription-pricing": pricingTimeline,
};

export function mockStream(roomName: string): Response {
  const encoder = new TextEncoder();
  const timeline = TIMELINES[roomName] ?? [];
  let canceled = false;
  let unsubscribe = () => {};
  const timers: ReturnType<typeof setTimeout>[] = [];

  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      // Open the connection (EventSource fires `onopen`) and set a retry hint.
      controller.enqueue(encoder.encode("retry: 5000\n: connected\n\n"));

      let elapsed = 0;
      for (const step of timeline) {
        elapsed += step.delayMs;
        timers.push(
          setTimeout(() => {
            if (canceled) return;
            const frame = { created_at: new Date().toISOString(), ...step.message };
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
          }, elapsed),
        );
      }

      // What the room's writes put on the stream (live.ts), as they happen.
      unsubscribe = subscribe(roomName, (frame) => {
        if (!canceled) controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
      });

      // Heartbeat so the badge stays LIVE after the timeline drains.
      const beat = setInterval(() => {
        if (canceled) return;
        controller.enqueue(encoder.encode(": heartbeat\n\n"));
      }, 15_000);
      timers.push(beat as unknown as ReturnType<typeof setTimeout>);
    },
    cancel() {
      canceled = true;
      unsubscribe();
      for (const t of timers) clearTimeout(t);
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
