# Spike — LLM mediator driving a real NEGMAS SAO

The original spike that de-risked the aligner's core question: *can an LLM mediator read
natural-language agent chatter, map it into NEGMAS offers, and terminate at agreement?*
(Now productionized as `app/services/aligner.py` + `mediator.py` + `pi_brain.py`.)

- `mediator_spike.py` (v1) — stateless agents + bare offers. **Deadlocks** (amnesiac hardliner
  never concedes). Finding: NEGMAS drive ✓ and NL→SAO interpretation ✓, but statelessness
  kills convergence. The failure is the harness, not the model or `claude -p` (never used it —
  it's litellm→haiku direct).
- `mediator_spike_v2.py` — adds MEMORY (per-agent running history, i.e. what a persistent Pi
  session gives you), a BROKERING mediator (frames where everyone stands + nudges to close),
  and BATNA (no deal = no rebalance). **Converges in 2 steps and NEGMAS terminates at
  agreement — no restating theatre.**

Verdict: PASS. The mediator's job is memory + brokering + BATNA framing (the "camp counselor"),
with NEGMAS owning the protocol and the stop.

Run: `ANTHROPIC_API_KEY=... uv run --with negmas --with litellm python mediator_spike_v2.py`
