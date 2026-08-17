# Mycelium Demo — Narration Script

**Total runtime target:** ~4 min (hard cap: 5 min)  
**Voice tone:** calm, clear, conversational — not corporate. Like a senior engineer explaining something that genuinely excites them.  
**Delivery notes:** pause briefly at `[pause]` markers. Don't rush the technical moments — let the screen breathe.

---

## SEGMENT 1 — Hook + IoC framing (0:00–0:35)

> Mycelium is a coordination layer for autonomous AI agents — shared rooms, persistent memory, and structured negotiation. It's our amuse-bouche of IoC capabilities.
>
> [pause]
>
> And for this hackathon, we've used it to show two things: what happens when agents genuinely disagree — and how Mycelium makes it possible for a human to step in and break the deadlock.
>
> [pause]
>
> Here's the scenario.

---

## SEGMENT 2 — Pivot to scenario (0:35–0:40)

> To make that concrete — here's the scenario we ran it against.

---

## SEGMENT 3 — The Scenario (1:15–1:40)

> It's Thursday afternoon. There's a checkout bug. Launch is Friday morning.
>
> Four agents need to decide: ship, or slip?
>
> [pause]
>
> Each one has a different hard constraint.
>
> The product manager cannot slip — the customer SLA and a paid marketing campaign both land Friday.
>
> The engineering lead will not ship known data corruption.
>
> The SRE requires a kill switch and under-two-minute rollback.
>
> Security needs an exploitability review — discount code bugs are a known attack surface.
>
> [pause]
>
> No single agent has the full picture. And none of them will just defer.

---

## SEGMENT 4 — Agents Join (1:40–2:20)

> We create a room and each agent joins with their opening position.
>
> [pause — let joins stream in]
>
> You can see each agent registering their intent with the CognitiveEngine — the mediator built into Mycelium that drives structured negotiation.
>
> It doesn't pick a winner. It runs multi-issue negotiation rounds, surfacing where agents agree, where they don't, and what each one considers a hard limit versus a preference they can trade.
>
> [pause]
>
> This is the dissent map — a live view of where the team stands.

---

## SEGMENT 4b — DISCUSSION banner (2:05–2:20)

> Once all agents have joined, the CognitiveEngine structures what's actually being decided — you can see it here in the DISCUSSION banner.
>
> [pause — click to expand]
>
> Expand it and you get each agent's full opening position. These aren't summaries — they're the exact stakes each agent brought in. The CognitiveEngine works from these to frame the negotiation issues: Friday ship, kill switch, exploitability review, staging validation.
>
> This is the map before the territory.

---

## SEGMENT 5 — Negotiation Rounds (2:20–3:20)

> The agents now negotiate. Across twenty rounds, the CognitiveEngine mediates — structuring the issues, pulling from the knowledge memory service, and surfacing considerations the agents themselves may not have raised.
>
> [pause — let messages stream]
>
> Each agent responds to proposals, pushes their constraints, and tries to find ground.
>
> For this demo, we've ensured their positions are irreconcilable. No agreement will be reached.

---

## SEGMENT 6 — Impasse (3:20–3:35)

> We're skipping ahead — the negotiation ran nineteen rounds before the CognitiveEngine confirmed no agreement was possible.
>
> [pause]
>
> That's the impasse. And look — Mycelium surfaces the ruling input right here in the session view. The human doesn't need to go anywhere else. The conflict and the resolution happen in the same place.

---

## SEGMENT 7 — Human Ruling (3:35–3:50)

> The human steps in and writes a ruling directly into the room.
>
> [pause — show ruling being typed]
>
> Ship Friday with checkout behind a feature flag. Run the exploitability review in parallel — two hours. If it flags an issue, or error rate exceeds one percent, pull the flag immediately. The staging run proceeds against the fix branch concurrently. If it passes before end of day Friday, deploy the fix and remove the flag.
>
> [pause]
>
> Every constraint gets addressed. No one just loses.

---

## SEGMENT 8 — Resolution (3:50–4:10)

> Mycelium spawns a second session. The same agents, the same room — but now working within the constraints the human set.
>
> This time they converge. The ruling becomes shared memory, and from it, a plan every agent executes against.

---

## SEGMENT 9 — Wrap (4:20–4:40)

> Human in the loop. Agent dissent with a path forward. A decision every agent inherits.
>
> [pause]
>
> That's what IoC coordination looks like in practice.

---

## Production Notes

- **Total word count:** ~520 words → ~4:10 at natural pace (hard cap: 5:00)
- **Pauses:** intentional — give screen time to show CLI output streaming in; don't fill silence with narration
- **Voice style:** ElevenLabs (`Rachel` or `Adam`) or Kokoro `af_heart` suit the calm-engineer tone well; OpenAI `nova` is a reasonable fallback
- **Music:** optional low ambient track under segments 4–6 only, -18dB under voice
