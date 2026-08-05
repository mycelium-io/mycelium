# START HERE — The SAO Mediator Agent (kill the AI theatre)

> **Status: exploratory / design track.** This is a thinking-out-loud spec for a real
> architectural pivot, written so we can track it and look at it holistically as one feature.
> Nothing here is committed to a release. The build plan front-loads the one cheap experiment
> that can *falsify* the whole idea before we invest in the harness swap.
>
> **⇒ Rung 0 PASSED, Rung 1 BUILT.** Rung 0 (the behavioral de-risk — the whole bet) passed
> (`experiments/sao-mediator-spike/`). **Rung 1's code is now merged**: the `@aligner` gained a
> `mediator` mode that drives a real NEGMAS SAO over SLIM (`app/services/mediator.py` +
> `aligner.py:mediate`, `tests/test_mediator.py`). It is proven node-free but **not yet run
> against live cold-spawned agents.** ⇒ **CURRENT ENTRY POINT:
> [`START_HERE_MEDIATOR_RUNG2.md`](./START_HERE_MEDIATOR_RUNG2.md)** — validate Rung 1 live,
> then Rung 2 (Pi + OpenShell). The rung descriptions below remain the design reference.

You are picking up the **coordination redesign** that the H5 demo surfaced. H5 got a full
`converge → plan → memory` run working with live agents (see
[`START_HERE_H5_DEMO.md`](./START_HERE_H5_DEMO.md)) — but in doing so it exposed that the
*shape* of our coordination is wrong. This doc is the plan to fix the shape.

## The problem (what the demo proved)

The H5 demo works, and that's exactly how we found the bug. Watch the `demo-final` transcript:
three agents (@growth/@risk/@execution) lock the agreement — **30% tech / 25% cap on every
other sector** — by roughly the **5th message**. Then they spend **seven more turns**
re-stating that same agreement in slightly different words until something finally summons the
aligner.

That is **AI theatre** — the precise failure Mycelium exists to kill (README, "The Problem":
*"agents that talk over each other, repeat work already done, fail to recognise disagreement,
fail to negotiate trade-offs"*). Our coordination layer didn't *prevent* the theatre; it
*hosted* it.

**Root cause:** the aligner is a passive, post-hoc **observer**. It only wakes when summoned,
reads a finished transcript, and grades confidence math. Nothing *runs* the negotiation while
it happens, so there is no mechanism that says "you agreed — stop." Agents fill the silence by
re-agreeing. The confidence-marker parse added in the H5 fix
(`connector.py:parse_position_marker`) makes the observer *score*, but it doesn't make anything
*drive*.

## The core idea

Flip the aligner from **scorekeeper** to **mediator** — a "camp counselor" that owns the
structure of the conversation and lets each agent speak in turn:

1. It **interprets** each agent's natural-language message (no structured markers required of
   the agents — that burden goes away).
2. It maps those interpretations into a real **NEGMAS Stacked Alternating Offers (SAO)**
   negotiation — the exact mechanism the original CFN used.
3. **NEGMAS owns termination.** The mechanism — not vibes, not an LLM's mood — decides the
   instant everyone has accepted the standing offer, and it *stops there*. That single fact is
   what kills the theatre.

Crucially, the mediator **is itself an agent** (on-thesis with the broader pivot: the
cognition-engine becomes an agent *in* the MAS, not backend code — see
`project_cfn_teardown_l9_pivot` and the coordination-transport-pivot doc). It reasons with an
LLM and drives NEGMAS as a tool.

## Definition of done

Re-run the equivalent of `mycelium demo`: several real agents negotiate, and a **mediator
agent** actively runs the rounds over SLIM — addressing agents in turn, interpreting their
replies, stepping a NEGMAS SAO — and **terminates the moment agreement is reached** (no
restating loop). On termination it emits the agreed `issue = value` map, which compiles to
`plan/tasks.md` and syncs to memory exactly as today. The transcript shows a *bounded*
negotiation, not seven rounds of "we're agreed."

## What's proven vs. not (honest ledger)

**Proven (this session, hands-on):**
- **Pi gives us the session primitive `claude -p` buries.** `pi -p --session <path> --mode
  json` — two separate processes against the same `--session` retained context (planted "42",
  recalled it; JSONL appended 5→7 lines). A long-lived mediator can hold one stable session
  across every SAO round, driven by our configured LLM (`--model anthropic/... --api-key`),
  provider-agnostic. Pi = [earendil-works/pi](https://github.com/earendil-works/pi), TS/Node,
  MIT, ~84k★.
- **OpenShell is real and ships Pi as a preset.** [NVIDIA/OpenShell](https://github.com/NVIDIA/OpenShell)
  — policy-enforced agent sandbox; `openshell sandbox create --from pi` is documented.
- **NEGMAS SAO is stable** and was already driven *externally* in the original CFN
  (`ioc-cfn-cognition-engines/semantic_negotiation/app/agent/callback_negotiator.py`).
- **The converge → plan → memory tail already works** (H5): aligner verdict → `plan_sync` →
  `plan_compiler` → `memory_sync`. We are replacing the *front* of that pipe, not the back.

**Proven (Rung 0 — the whole bet, `experiments/sao-mediator-spike/`):**
- **An LLM mediator drives a real NEGMAS SAO from natural-language chatter and terminates at
  agreement.** Both halves hold: NL→SAO interpretation is reliable, and NEGMAS owns the stop
  (converged in 2 steps, no restating tail — the anti-theatre property). The v1→v2 delta pinned
  the design spec: bare-offer relaying to *stateless* agents deadlocks; the fix is **memory + a
  brokering mediator + BATNA** (the "camp counselor" is the literal mechanism). v1 (amnesiac)
  never converged; v2 (per-agent running history + mediator framing + "no deal = no rebalance")
  converged and stopped. Same model, same personas — only the mediator's role changed.

**Still open (Rung 1+ will surface these against real agents):**
- Does it hold with **live SLIM agents** (not simulated personas) — real replies, real latency,
  the daemon's cold-spawn turn model?
- Concession dynamics at scale (more issues/agents, longer runs) and interpretation drift on
  messier prose than the spike's tidy accept/reject.

## Target architecture

- **Pi is the runtime for mycelium's *internal* agents — not for user agents.** The SAO
  mediator (and, as they land, the semantic-negotiation NEGMAS owner and any other
  backend-run cognition agent) run on Pi (`pi -p --session <id> --mode json`), OpenShell-
  sandboxed, driven by the mycelium-configured LLM. **User/participant agents keep whatever
  framework they already use** — claude_code, cursor, hermes, openclaw. We do **not** homogenize
  them onto Pi; the mediator just `@`-addresses whatever runtime answers on the channel. (An
  earlier draft of this doc said "all participants are Pi coding agents" — that was wrong and
  is the source of the Rung-2 drift; see `START_HERE_MEDIATOR_RUNG2.md`.)
- **The mediator is a long-lived agent for the duration of one negotiation.** Recommended
  factoring for the Node/Python seam (NEGMAS is Python, Pi is Node):
  > The mediator is a **Python** process that holds the NEGMAS `SAOMechanism` natively
  > in-process and drives its Pi "brain" via `pi -p --session <id> --mode json` (the exact
  > calls already validated). NEGMAS state stays in Python where it's trivial; Pi handles only
  > the LLM turn + conversation memory. No cross-language state.
- **Drive is native over SLIM.** The mediator publishes `@`-addressed prompts that wake a
  participant's connector (reuse `aligner._prompt_round`'s unicast publish); it reads replies
  from the transcript (reuse `_collect_round`); it interprets them with its LLM; it steps
  NEGMAS; it repeats. It "still uses `@` commands" — that's how it addresses the next proposer.
- **The backend shrinks to what it's good at:** moderate the SLIM channel, persist the
  transcript, freeze membership for the episode, compile the agreed plan. It stops doing
  cognition.

## How it maps to what exists (scouted — reuse vs. new)

Reuse (mechanics are production-grade):
- Unicast publish to one agent — `aligner.py:_prompt_round` → `managed.channel.send` with L9
  `recipients=[handle]`.
- Reply collection — `aligner.py:_collect_round` polls `persister.log.records`.
- Episode freeze/drain — `room_channels.open_episode` / `close_episode` (membership freeze,
  queued-invite flush).
- Summon seam — `persister.find_summons` → `on_summon` (`@aligner` still the entry point).
- Converged tail — `plan_sync.handle_converged` → `plan_compiler` → `memory_sync`.

New (the SAO-specific orchestration + interpretation):
- **Standing offer + proposer rotation + unanimity-stop** (today's `drive` loop just asks
  "state your position and confidence" and folds MPC — no offer, no rotation, no early stop).
- **Issue/option discovery** from opening prose — port `intent_discovery.py` +
  `options_generation.py` (LLM stages) from the sibling repo.
- **NL → NEGMAS interpretation** — the mediator's LLM reading "I can live with 30/25 if beta
  holds" → a NEGMAS response against the standing offer.
- **Echo-back for trust** — the counselor restates its reading ("recording @growth as: counter
  → 35% tech") so a misread is corrected *in-band* before it commits.

## Build plan (rungs — start where it can break)

**Rung 0 — falsify the behavioral core (cheap, no harness). ✅ DONE — PASSED.**
`experiments/sao-mediator-spike/` (litellm→haiku, *not* claude -p): NEGMAS `SAOMechanism` + an
LLM interpreter + LLM-simulated personas. `mediator_spike.py` (v1, stateless) deadlocked but
proved the NEGMAS drive + NL→SAO interpretation both work; `mediator_spike_v2.py` added memory +
brokering + BATNA and **converged in 2 steps, terminating at agreement**. Finding baked into the
dir's README and `project_mediator_pi_negmas` memory. **Don't repeat this — start at Rung 1.**

**Rung 1 — the mediator drives live over SLIM, still on today's worker agents. ✅ CODE BUILT
(node-free); live validation pending → see `START_HERE_MEDIATOR_RUNG2.md`.**
Port the *proven v2 loop* (`experiments/sao-mediator-spike/mediator_spike_v2.py`: discover →
NEGMAS rounds → interpret prose → terminate on agreement) into the `@aligner` driver: on summon,
open the episode, run rounds by `@`-addressing agents over SLIM and reading their real replies
from the transcript, terminate on agreement, hand the `issue=value` map to `plan_sync`. Carry
over the v1→v2 lesson — the mediator must give agents context (they have persistent memory via
the room transcript today, Pi sessions later), broker, and surface BATNA. This proves the
theatre is dead against *real* agents, before touching the Pi/OpenShell harness swap (Rung 2).
Extension seams (publish/collect/episode) are mapped in "How it maps to what exists" above.

**Rung 2 — give mycelium's *internal* agents a Pi + OpenShell runtime.** Move the mediator's
cognitive brain off stateless in-process `litellm` calls onto a persistent, OpenShell-sandboxed
Pi session (`pi -p --session <id> --mode json`), dropped into the existing `mediator.py:llm_sync`
seam. Same for the semantic-negotiation NEGMAS owner as it lands. **User agents are untouched** —
this is *not* a worker-runtime swap. Independent payoff (session memory across SAO rounds,
provider-agnostic, sandboxed) and independent risk from the mediator loop. **Not** the wake-up
problem — that stays a separate, per-framework concern (bible §10/§12); Pi does not paper over it.

**Rung 3 — retire the old surface.** Remove the backend SIEP observer engine and the
`parse_position_marker` reply-marker hack; agents go back to markerless prose (the mediator
interprets). Update the skill/preamble.

## Fixed decisions

- The mediator is an **agent that runs NEGMAS**, not re-ported SAO math in the backend.
- **NEGMAS owns termination.** Agreement is when the mechanism says so; the mediator does not
  "decide to stop."
- **Pi + OpenShell is the runtime for mycelium's *internal* agents only** (the mediator, the
  neg engines). **User/participant agents keep their own framework** — Pi is never imposed on
  them, and homogenizing all participants onto one runtime is explicitly *not* the goal.
- **Wake-up / automatic invocation is a separate, per-framework concern** (bible §10/§12). Pi
  is not the wake-up mechanism; do not conflate the two.
- Agents are **not** required to emit structured markers; the mediator interprets prose.

## Open questions (each has a recommended default — use it, note it, flag it)

- **Mediator lifecycle host language** → *Python process holding NEGMAS, driving Pi via CLI.*
  (Alternative: Node/Pi-SDK mediator shelling to a Python NEGMAS sidecar — more moving parts.)
- **Trigger** → *explicit `@aligner` summon hands the room to the mediator* (deterministic;
  the demo already does this). Auto-start on detected negotiation is a later nicety.
- **Session locking** → drive the mediator's Pi session **strictly serially** (turn-based, so
  safe by construction) and reuse the daemon's per-handle serial-lock discipline. Run a
  deliberate concurrent-write test before trusting Pi sessions under any parallelism.
- **Utilities for NEGMAS** → start with the mediator inferring a coarse per-agent utility from
  stated positions/hard-lines; refine only if Rung 0 shows it needs it.

## What this retires

- `app/services/aligner.py` — the observer/driver SIEP engine (replaced by the mediator agent).
- `daemon/connector.py:parse_position_marker` + the preamble's "position marker" block (the
  H5 confidence-marker hack — no longer needed once the mediator interprets prose).
- The mediator's stateless in-process `litellm` brain (`mediator.py:llm_sync`) → a persistent,
  OpenShell-sandboxed Pi session (Rung 2). **The user-facing `claude -p` / cursor / etc. worker
  runtimes are NOT retired** — those stay; only mycelium's *internal* agent brain moves to Pi.

## Prereqs

- Backend + slim node up (dev compose); exactly one daemon.
- `pi` on PATH (0.65.0 verified) and an LLM key — `pi -p --session <path> --mode json` is the
  proven drive call. NEGMAS: `uv add negmas` in whatever process hosts the mediator.
- The captured `demo-final` transcript for Rung 0 (pull via the room `messages` API).

## References

- **The problem, live:** `START_HERE_H5_DEMO.md` (the demo this exposed), README "The Problem".
- **Original SAO mechanism (port from):** `ioc-cfn-cognition-engines/semantic_negotiation/app/agent/`
  — `callback_negotiator.py` (the round loop + external drive), `semantic_negotiation.py`
  (pipeline + commit envelope), `intent_discovery.py`, `options_generation.py`,
  `offer_validation.py`.
- **Current coordination internals (extend/retire):** `app/services/aligner.py`,
  `l9_episode.py`, `room_channels.py`, `persister.py`, `plan_sync.py`, `plan_compiler.py`.
- **Harness:** [Pi](https://github.com/earendil-works/pi) (`pi-ai`, `pi-agent-core`, session
  docs), [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell), [NEGMAS](https://github.com/yasserfarouk/negmas).
- **Direction memory:** `project_mediator_pi_negmas`, `project_cfn_teardown_l9_pivot`.

## How to work with the human

Rung by rung, evidence after each — but the deliverable that matters is a **bounded**
negotiation: a human watching agents reach agreement and the mediator *stop*, versus the H5
theatre. Rung 0 is a spike; expect to throw code away. Treat surprises in the LLM→NEGMAS
interpretation as the real findings — that's the unproven core, and it's the whole point of
building this at all.
