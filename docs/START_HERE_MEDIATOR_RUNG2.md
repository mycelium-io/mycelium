# START HERE — SAO Mediator: Rung 1 validation → Rung 2 (Pi brain for internal agents)

> **Status: exploratory / design track**, continuing `START_HERE_MEDIATOR.md` (read that first
> for the *why* — kill the AI theatre — and the honest ledger). This doc picks up **after Rung
> 1's code landed** and, in order, covers: (1) **validate Rung 1 live**; then (2) **Rung 2 —
> give mycelium's *internal* agents a Pi + OpenShell runtime.**
>
> ### ⚠️ Scope correction (read this — an earlier draft got it backwards)
> A previous version of this doc (and one line in the parent doc) said Rung 2 was *"replace the
> `claude -p` worker runtime with Pi agents for **all participants**."* **That is wrong** and it
> sent a follow-on session off building a user-facing `pi` adapter. The corrected design:
>
> - **Pi is the runtime for mycelium's *internal* agents only** — the SAO mediator now, the
>   semantic-negotiation NEGMAS owner and any other backend-run cognition agent next.
> - **User / participant agents keep whatever framework they already use** (claude_code, cursor,
>   hermes, openclaw). Pi is **never** imposed on them. The mediator just `@`-addresses whatever
>   runtime answers on the channel — that path does not change.
> - **This is NOT a worker-runtime swap** and **NOT the wake-up fix.** Per-framework wake-up /
>   automatic invocation is its own concern (bible §10/§12); Pi must not be framed as papering
>   over it. The goal is the best invocation UX *per framework*, not one runtime for everyone.
> - **OpenShell sandboxing is in-scope from the start** for the internal Pi agents.

## What Rung 1 built (merged into `slim-native-rewrite`)

The `@aligner` gained a third mode — **`mediator`** — porting the proven Rung-0 v2 loop
(`experiments/sao-mediator-spike/mediator_spike_v2.py`) to run *live over SLIM*:

- **`app/services/mediator.py`** (new) — the SAO orchestration: `discover_issues` (opening prose
  → NEGMAS issues/options), `MediatedNegotiation` (running history + brokering + BATNA — the
  "camp counselor"), `LiveNegotiator` (a NEGMAS `SAONegotiator` whose `propose`/`respond` are
  backed by a *real agent's* replies), and the cognitive brain seam **`llm_sync`** — a
  synchronous `litellm.completion` callable, injected as `llm=` into `discover_issues` and
  `MediatedNegotiation`.
- **`app/services/aligner.py`** — `AlignerEngine.mediate(room)`: opens the episode, discovers
  issues, runs `mech.run()` on a worker thread while each negotiator bridges back to the event
  loop (`run_coroutine_threadsafe`) to `@`-address one agent over SLIM and read its real reply,
  then emits the agreed `issue = value` map through the **same `commit:converged` seam
  `plan_sync` already consumes**.
- **Additive**: `observer` stays the default mode; `ALIGNER_MODE=mediator` opts in.
- `negmas` added to backend deps; `tests/test_mediator.py` proves termination-at-agreement
  below the step cap, node-free/LLM-free (via a monkeypatched `llm_sync`).

**Proven node-free only. NOT yet run against a live SLIM node with real cold-spawned agents.**

---

## Part A — Validate Rung 1 live (human-run gate; do before Rung 2)

Rung 2 hardens the mediator's runtime; there's no point hardening a loop that hasn't been shown
to work live. So **Part A gates Part B.** This is a manual smoke test (Docker, a live SLIM node,
real agents, LLM credits, a human watching) — lean on `docs/SMOKE_TEST_HANDOFF.md` for bringing
the stack up (it's the current honest guide; `CLAUDE.md` is stale on architecture).

1. **Turn the mediator on.** It needs an LLM (unlike the observer). Set the backend's
   `ALIGNER_MODE=mediator`; confirm `llm.model` + `llm.api_key` (`mycelium config set …` →
   `mycelium config apply`; recreate the backend container to pick up env). Optionally lower
   `ALIGNER_MEDIATOR_MAX_STEPS` for a faster/cheaper first run.
2. **Seed a real disagreement.** Two or three real user agents (e.g. `claude_code`) in a room
   with genuinely conflicting opening positions (the `demo` / `persona-before-and-after` flows
   seed the growth/risk/execution scenario; may be stale — a hand-driven case is fine). Confirm
   each posts an opening position into the transcript.
3. **Summon the mediator.** Post a message `@`-mentioning the aligner handle (default `aligner`).
   Watch backend logs: `discover_issues` logs the issues, then per-step
   `mediator step N: @handle PROPOSE …` / `… ACCEPT on …` as it addresses agents in turn and
   their connectors cold-spawn replies.
4. **Watch for the payoff — a *bounded* negotiation.** Agents reach agreement and the mediator
   **stops** (no seven-round restating tail). On termination it emits `commit:converged` with
   the `issue = value` map, `plan_sync` compiles `plan/tasks.md`, memory syncs — same tail as the
   observer path. **Capture the transcript** as the before/after against the H5 theatre.

### Where it will most likely break (debug here first)
- **Interpretation drift on messy prose.** Real agents ramble; the spike's spoke tidy
  accept/reject. The mediator's **echo-back** ("recording @growth as counter → …") into the
  transcript is your window; if a misread isn't visible enough, strengthening that echo
  (`mediator.py:interpret` / the `on_reading` fold in `aligner.py`) is the first fix.
- **Turn timing.** `_slim_turn` waits `ALIGNER_ROUND_TIMEOUT_S` for a reply; a slow cold-spawn
  that exceeds it yields `""` → read as reject. Raise it if real agents are slower than 30s.
- **No opening positions.** Discovery needs positions in the transcript; if nobody spoke, it
  rejects cleanly. Ensure agents post before the summon.
- **Silent degradation** (bible debts D3/D6): SLIM failures degrade quietly to "no channel."
  If "nothing happens," check backend + daemon logs.

**Deliverable of Part A:** a human watching a real multi-agent negotiation reach agreement and
the mediator *stop*.

---

## Part B — Rung 2: a Pi + OpenShell brain for the mediator (internal agents only)

> **Status: code built (node-free) on branch `rung2-pi-openshell`.** `PiBrain`
> (`app/services/pi_brain.py`) + the `ALIGNER_BRAIN` selection in
> `aligner.py:_make_brain` land the seam exactly as scoped below; `tests/test_pi_brain.py`
> covers output parsing, command construction, the OpenShell wrap, and brain selection
> with no live `pi`. **Live validation of the Pi brain (and OpenShell) is still pending**
> — it is gated on Part A and tracked in **`START_HERE_MEDIATOR_RUNG2_VALIDATION.md`**.

Only after Part A. The entire job is **one injection seam**: replace the mediator's stateless
`litellm.completion` brain with a **persistent, OpenShell-sandboxed Pi session**, without
touching the NEGMAS loop, the SLIM drive, or any user agent.

### Why (the payoff)
- **Session memory across SAO rounds.** The v1→v2 lesson was "the camp counselor needs memory."
  Today `MediatedNegotiation` threads a `history` string into every prompt by hand; a persistent
  `pi -p --session <id>` session gives the brain *real* durable memory across rounds — the
  natural home for that state.
- **Provider-agnostic + self-hostable + sandboxed** cognition for our own agents, decoupled from
  whatever the user agents run.

### The seam (already built for this)
`mediator.py` injects its brain as a callable `llm(prompt, *, system="", temperature=…) -> str`:
- `discover_issues(task, positions, *, llm=None)` → `llm = llm or llm_sync`
- `MediatedNegotiation(…, llm=None, …)` → `self._llm = llm or llm_sync`
- `aligner.py:mediate` currently constructs `MediatedNegotiation` and calls `discover_issues`
  **without** an `llm=`, so both fall through to `llm_sync`.

So Rung 2 is: **build a `PiBrain` with that exact call signature and pass it in.**

### Concrete work
1. **`PiBrain`** (new — `app/services/pi_brain.py`, or in `mediator.py`): a class whose
   `__call__(prompt, *, system="", temperature=…) -> str` drives one long-lived
   `pi -p --session <id> --mode json` subprocess, **launched inside an OpenShell sandbox**
   (`openshell sandbox create --from pi` / exec — required from the start, per the design). One
   session per negotiation → memory accumulates across rounds. Driven strictly **serially** (the
   mediator's turn model is serial by construction; reuse the daemon's per-handle serial-lock
   discipline). Configured with the mycelium LLM (`--model … --api-key …`), provider-agnostic.
2. **Selection flag** (config, e.g. `ALIGNER_BRAIN = "litellm" | "pi"`, **default `litellm`**):
   `aligner.py:mediate` builds the chosen brain and passes it as `llm=` into `discover_issues`
   and `MediatedNegotiation`. Default keeps `llm_sync`, so nothing breaks where Pi isn't
   installed — same "additive, stays green" discipline as Rung 1.
3. **Tests stay node-free/Pi-free** by injecting a fake brain into the same seam (exactly what
   `test_mediator.py` does today). A live Pi test is a separate, guarded integration slice.
4. **Same seam later serves the semantic-negotiation NEGMAS owner** when it lands — it is
   another internal agent and reuses `PiBrain`.

### Explicitly OUT of scope for Rung 2 (the anti-drift list)
- ❌ **No user-facing `pi` adapter**, no `--adapter pi`, no change to `AGENT_ADAPTERS`.
- ❌ **No change to `daemon/dispatch.py` / `daemon/runner.py`** for user agents — user cold-spawn
  is untouched. (The mediator's `@`-drive already works over the existing connector path.)
- ❌ **Not the wake-up problem.** Per-framework invocation UX is a separate track (bible §10/§12).
- ❌ **`claude -p` / cursor / etc. are NOT retired.** Only the mediator's *internal brain* moves.

### Honest caveats
- **Pi may not be on this machine** (`which pi`). The `PiBrain` seam is buildable + unit-testable
  node-free, but a *live* Pi session can't be proven here — same posture Rung 1 landed in.
- **OpenShell likewise** — treat "internal Pi agent runs sandboxed live" as a manual validation
  step alongside Part A.

---

## Part C — Rung 3 (retire the old surface), later
Once Rung 2 is in and trusted: remove the observer engine + `daemon/connector.py:parse_position_marker`
+ the preamble's "position marker" block (agents go back to markerless prose; the mediator
interprets). Flip the mediator to the default mode. Update the CLI skill/preamble. Deletion rung —
do it last. **This still does not touch user runtimes.**

## Fixed decisions (design, now corrected)
- The mediator is an **agent that runs NEGMAS**; **NEGMAS owns termination.**
- **Pi + OpenShell is the runtime for mycelium's *internal* agents only.** User/participant
  agents keep their own framework; Pi is never imposed on them.
- **Wake-up is a separate, per-framework concern** — not solved by Pi.
- Agents are **not** required to emit structured markers; the mediator interprets prose.

## References
- **Why + ledger + corrected fixed-decisions:** `docs/START_HERE_MEDIATOR.md`.
- **Stack up / smoke ladder:** `docs/SMOKE_TEST_HANDOFF.md`, `docs/cross-machine.md`.
- **The proven core:** `experiments/sao-mediator-spike/` (v1 deadlock → v2 converges).
- **The Rung-1 code + the brain seam:** `app/services/mediator.py` (`llm_sync`, `discover_issues`,
  `MediatedNegotiation`), `app/services/aligner.py` (`mediate`), `tests/test_mediator.py`.
- **Runtime:** [Pi](https://github.com/earendil-works/pi), [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell),
  [NEGMAS](https://github.com/yasserfarouk/negmas).
- **Direction memory:** `project_mediator_pi_negmas`, `project_cfn_teardown_l9_pivot`.
