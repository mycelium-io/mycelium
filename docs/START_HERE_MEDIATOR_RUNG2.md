# START HERE — The SAO Mediator, Rung 1 validation → Rung 2 (Pi + OpenShell)

> **Status: exploratory / design track**, continuing `START_HERE_MEDIATOR.md`. Read that doc
> first for the *why* (kill the AI theatre) and the honest ledger. This doc picks up **after
> Rung 1's code landed** and covers two things, in order: (1) **validate Rung 1 live** against
> real cold-spawned agents — the code exists but has only been proven node-free; (2) then
> **Rung 2**, swapping the worker runtime to Pi + OpenShell.

## What Rung 1 built (already merged into `slim-native-rewrite`)

The `@aligner` engine gained a third mode — **`mediator`** — that ports the proven Rung-0 v2
loop (`experiments/sao-mediator-spike/mediator_spike_v2.py`) to run *live over SLIM*:

- **`app/services/mediator.py`** (new) — the SAO orchestration: `discover_issues` (opening
  prose → NEGMAS issues/options), a `MediatedNegotiation` run-context (running history +
  brokering + BATNA — the "camp counselor"), the `LiveNegotiator` (a NEGMAS `SAONegotiator`
  whose `propose`/`respond` are backed by a *real agent's* replies), and the LLM seams
  (`llm_sync` — synchronous `litellm.completion`, which also dodges the Bedrock `acompletion`
  breakage).
- **`app/services/aligner.py`** — `AlignerEngine.mediate(room)`: on summon, opens the episode,
  discovers issues from the transcript's opening positions, runs `mech.run()` on a worker
  thread while each negotiator bridges back to the event loop (`run_coroutine_threadsafe`) to
  `@`-address one agent over SLIM and read its real reply, then emits the agreed
  `issue = value` map through the **same `commit:converged` seam `plan_sync` already consumes**.
  **NEGMAS owns termination** — it stops the instant the standing offer is unanimous.
- **`ALIGNER_MODE=mediator`** + **`ALIGNER_MEDIATOR_MAX_STEPS`** (default 20) config.
- **`negmas`** added to `fastapi-backend` deps; **`tests/test_mediator.py`** proves the loop
  terminates at agreement below the step cap (the anti-theatre assertion), node-free/LLM-free.

**The seam that makes this safe:** the mediator is *additive*. `observer` (deterministic,
no-LLM) is still the default mode; nothing changes for existing rooms until an operator flips
`ALIGNER_MODE=mediator`. Rung 3 will retire the observer + the `parse_position_marker` hack.

## Proven vs. NOT (updated ledger)

**Proven (Rung 1, this branch):** the mediated loop drives a real NEGMAS SAO, interprets
simulated agent prose into offers/accepts, and **terminates at agreement without a restating
tail** — asserted in `test_mediator.py` over the same fake channel the aligner tests use.

**NOT yet proven (your job, Rung 1 validation):** the loop against **real cold-spawned worker
agents over a live SLIM node** — real replies, real latency, the daemon's cold-spawn turn
model. This is exactly the gap `START_HERE_MEDIATOR.md`'s "Still open (Rung 1+)" flagged. The
code is written; it has never run end-to-end against a `claude -p` agent.

## Part A — Validate Rung 1 live (do this before Rung 2)

Lean on `docs/SMOKE_TEST_HANDOFF.md` for bringing the stack up (it is the current, honest guide
to the SLIM-native stack; `CLAUDE.md` is stale on architecture). Then, specifically for the
mediator:

1. **Turn the mediator on.** It needs an LLM (unlike the observer). Set the backend's
   `ALIGNER_MODE=mediator` (env on the backend container / process) and confirm `llm.model` +
   `llm.api_key` are configured (`mycelium config set …` → `mycelium config apply`; recreate
   the backend container to pick up env). Optionally lower `ALIGNER_MEDIATOR_MAX_STEPS` for a
   faster, cheaper first run.
2. **Seed a real disagreement.** Get **two or three** real `claude_code` agents into a room
   with genuinely conflicting opening positions (the `demo` / `persona-before-and-after` flows
   seed the classic growth/risk/execution portfolio scenario — they may be stale, so a
   hand-driven minimal case is fine too). Confirm each agent posts an opening position into the
   room transcript.
3. **Summon the mediator.** Post a message that `@`-mentions the aligner handle (default
   `aligner`). Watch the backend logs: `discover_issues` should log the issues, then per-step
   `mediator step N: @handle PROPOSE …` / `… ACCEPT on …` lines as it `@`-addresses agents in
   turn and their connectors cold-spawn replies.
4. **Watch for the payoff — a *bounded* negotiation.** The deliverable that matters (per
   `START_HERE_MEDIATOR.md` "How to work with the human"): the transcript shows agents reaching
   agreement and the mediator **stopping** — no seven-round restating tail. On termination it
   emits `commit:converged` with the `issue = value` map, `plan_sync` compiles `plan/tasks.md`,
   and it syncs to memory exactly as the observer path does today.

### Where it will most likely break (debug here first)

- **Interpretation drift on messy prose.** The spike's agents spoke tidy accept/reject; real
  `claude -p` agents ramble. If `interpret` mis-maps a reply, the mediator's **echo-back** into
  the transcript ("recording @growth as counter → …") is your window — a misread should be
  visible and correctable in-band. If it is *not* visible enough, strengthening that echo is
  the first fix (`mediator.py:interpret` / the `on_reading` fold in `aligner.py`).
- **Turn timing.** `_slim_turn` waits `ALIGNER_ROUND_TIMEOUT_S` for a reply; a slow cold-spawn
  that exceeds it yields `""` → read as a reject → NEGMAS keeps going. If real agents are
  slower than the default 30s, raise it. A silent agent must never hang the loop (that bound is
  the guarantee) but too-tight a bound turns real replies into spurious rejects.
- **No opening positions.** `mediate` seeds `discover_issues` from transcript positions and
  stubs absent agents; if nobody has spoken, discovery has nothing to structure and it rejects
  cleanly. Make sure agents actually post before the summon (or add a real opening-position
  prompt round — noted as a possible enhancement).
- **Silent degradation.** As the smoke-test doc warns (debts D3/D6), SLIM failures degrade
  quietly to "no channel." If "nothing happens," check backend + daemon logs.

**Deliverable of Part A:** a human watching a real multi-agent negotiation reach agreement and
the mediator *stop* — the direct before/after against the H5 theatre. Capture the transcript.

## Part B — Rung 2: swap the worker runtime to Pi + OpenShell

Only after Part A shows the theatre is dead against real agents. This is **independent payoff
and independent risk** from the mediator (provider-agnostic, containerized, self-hostable), so
it is its own rung.

- Replace the `claude -p` cold-spawn worker runtime with **Pi** agents
  (`pi -p --session <id> --mode json`), **OpenShell**-sandboxed. Pi = earendil-works/pi;
  OpenShell = NVIDIA/OpenShell (`openshell sandbox create --from pi`). Both validated as real
  in the Rung-0 session (see `START_HERE_MEDIATOR.md` "Proven, hands-on").
- Workers keep the good coding-agent abstractions (skills, tools, bash); they just *speak* in
  the room. The mediator's `@`-drive is unchanged — it addresses whatever agent runtime answers
  on the channel.
- **Session-locking discipline:** drive Pi sessions **strictly serially** (the mediator's turn
  model is serial by construction). Reuse the daemon's per-handle serial-lock. Run a deliberate
  concurrent-write test before trusting Pi sessions under any parallelism.
- Touch points: the daemon dispatch/runner (`daemon/dispatch.py`, `daemon/runner.py`) and the
  `claude_code` adapter (`integrations/claude_code/**`) are where cold-spawn lives today.

## Part C — Rung 3 (retire the old surface), later

Once Rung 2 is in: remove the observer engine + `daemon/connector.py:parse_position_marker`
and the preamble's "position marker" block (agents go back to markerless prose; the mediator
interprets). Flip the mediator to the default mode. Update the CLI skill/preamble. This is a
deletion rung — do it last, when the mediator has earned the trust to be the only path.

## Fixed decisions (unchanged from `START_HERE_MEDIATOR.md`)

- The mediator is an **agent that runs NEGMAS**, not re-ported SAO math in the backend.
- **NEGMAS owns termination.** Agreement is when the mechanism says so.
- **One framework: Pi coding agents** for all participants, OpenShell-sandboxed (Rung 2).
- Agents are **not** required to emit structured markers; the mediator interprets prose.

## References

- **Why + the ledger:** `docs/START_HERE_MEDIATOR.md`.
- **Stack up / smoke ladder:** `docs/SMOKE_TEST_HANDOFF.md`, `docs/cross-machine.md`.
- **The proven core:** `experiments/sao-mediator-spike/` (v1 deadlock → v2 converges).
- **The Rung-1 code:** `app/services/mediator.py`, `app/services/aligner.py` (`mediate`),
  `tests/test_mediator.py`.
- **Harness (Rung 2):** Pi (earendil-works/pi), NVIDIA/OpenShell, NEGMAS (yasserfarouk/negmas).
- **Direction memory:** `project_mediator_pi_negmas`, `project_cfn_teardown_l9_pivot`.
