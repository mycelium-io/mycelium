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
// The aligner brokers a real NEGMAS Stacked Alternating Offers round-robin over
// three issues (price, seats, term); each natural-language reply is followed by
// the aligner's interpreted move as a coordination_tick, so the Channel narrates
// and the Negotiate tab's offer board + swim lanes fill in live.
const PRICING_EPISODE = "urn:ioc:mycelium:episode:pricing-model:b2d0";
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
const pricingTimeline: StreamStep[] = [
  // Round 1
  { delayMs: 1500, message: say("s1", "growth", "Opening ask: $29, 50 seats, annual term — land-and-expand. @finance") },
  { delayMs: 1600, message: tick("s2", 1, "growth", "propose", { price: "29", seats: "50", term: "annual" }) },
  { delayMs: 2200, message: say("s3", "finance", "$29 kills our margin. Counter: $49, same seats.") },
  { delayMs: 1600, message: tick("s4", 1, "finance", "counter", { price: "49", seats: "50", term: "annual" }) },
  // Round 2
  { delayMs: 2200, message: say("s5", "growth", "Meet me at $35 — but I need 75 seats to justify it.") },
  { delayMs: 1600, message: tick("s6", 2, "growth", "counter", { price: "35", seats: "75", term: "annual" }) },
  { delayMs: 2200, message: say("s7", "finance", "$39 and we hold margin above 60%. 75 seats is fine.") },
  { delayMs: 1600, message: tick("s8", 2, "finance", "counter", { price: "39", seats: "75", term: "annual" }) },
  // Round 3 — convergence
  { delayMs: 2200, message: say("s9", "growth", "Deal. $39, 75 seats, annual. ✅") },
  { delayMs: 1500, message: tick("s10", 3, "growth", "accept", { price: "39", seats: "75", term: "annual" }) },
  { delayMs: 1400, message: tick("s11", 3, "finance", "accept", { price: "39", seats: "75", term: "annual" }) },
  { delayMs: 1800, message: { id: "s12", sender_handle: "backend", message_type: "coordination_consensus", content: JSON.stringify({ plan: "pricing agreed", assignments: { price: "39", seats: "75", term: "annual" }, plan_file: "plan/tasks.md", episode: PRICING_EPISODE, metrics: { gar: 0.86 } }), episode: PRICING_EPISODE } },
  // After the plan lands, summon the synthesizer: it distills the room's memory
  // (goal, the new decision, the plan) into a shared briefing at context/synthesis.
  { delayMs: 2000, message: say("s13", "operator", "@synthesizer brief the room on where we landed.") },
  { delayMs: 1800, message: say("s14", "synthesizer", "Distilled the outcome → context/synthesis: Pro launches at $39/seat, 75 seats, annual — margin held above 60%.") },
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
