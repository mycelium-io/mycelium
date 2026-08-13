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

interface StreamStep {
  delayMs: number;
  message: Record<string, unknown>;
}

// An in-progress negotiation for `pricing-model` that resolves while you watch.
const PRICING_EPISODE = "urn:ioc:mycelium:episode:pricing-model:b2d0";
const pricingTimeline: StreamStep[] = [
  { delayMs: 1500, message: { id: "s1", sender_handle: "growth", message_type: "broadcast", content: "$49 is too steep for land-and-expand. Counter: $29. @finance" } },
  { delayMs: 3000, message: { id: "s2", sender_handle: "aligner", message_type: "coordination_tick", content: JSON.stringify({ payload: { round: 1, participant_id: "finance", action: "counter", current_offer: { price: "39" } } }), episode: PRICING_EPISODE } },
  { delayMs: 2500, message: { id: "s3", sender_handle: "finance", message_type: "broadcast", content: "$39 keeps margin above 60%. I can live with that." } },
  { delayMs: 2500, message: { id: "s4", sender_handle: "growth", message_type: "broadcast", content: "Deal. $39 it is. ✅" } },
  { delayMs: 2000, message: { id: "s5", sender_handle: "backend", message_type: "coordination_consensus", content: JSON.stringify({ plan: "price agreed", assignments: { price: "39" }, plan_file: "plan/tasks.md", episode: PRICING_EPISODE, metrics: { gar: 0.83 } }), episode: PRICING_EPISODE } },
];

const TIMELINES: Record<string, StreamStep[]> = {
  "pricing-model": pricingTimeline,
};

export function mockStream(roomName: string): Response {
  const encoder = new TextEncoder();
  const timeline = TIMELINES[roomName] ?? [];
  let cancelled = false;
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
            if (cancelled) return;
            const frame = { created_at: new Date().toISOString(), ...step.message };
            controller.enqueue(encoder.encode(`data: ${JSON.stringify(frame)}\n\n`));
          }, elapsed),
        );
      }

      // Heartbeat so the badge stays LIVE after the timeline drains.
      const beat = setInterval(() => {
        if (cancelled) return;
        controller.enqueue(encoder.encode(": heartbeat\n\n"));
      }, 15_000);
      timers.push(beat as unknown as ReturnType<typeof setTimeout>);
    },
    cancel() {
      cancelled = true;
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
