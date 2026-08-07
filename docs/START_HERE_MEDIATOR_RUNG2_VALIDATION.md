# START HERE — SAO Mediator: validate Rungs 1 & 2 live (the two open gates)

> **Status: exploratory / design track.** Continues `START_HERE_MEDIATOR_RUNG2.md`. That
> doc's **Part B code is now built** (the Pi brain seam) but two things remain, both
> **human-run live validations** that a code-only session cannot do autonomously (Docker, a
> live SLIM node, real agents, LLM credits, a human watching). This doc is the checklist for
> those two gates and the honest ledger of what's proven vs. not. **No new feature work is
> required to reach the payoff — only validation.**

## Where we are

| Rung | What | State |
|------|------|-------|
| 0 | Behavioral de-risk — LLM mediator drives NEGMAS SAO, terminates at agreement | ✅ **PASSED** (`experiments/sao-mediator-spike/`) |
| 1 | Mediator drives live over SLIM (`aligner.py:mediate` + `mediator.py`) | ✅ **run live against real cold-spawned agents** — architecture proven; converged end-to-end on a fresh room (`{tech:40%, cap:25%}`, single wakes, no timeouts, terminated); 3 bugs found + fixed. Multi-round runs surfaced **4 more open bugs** (discretization misreports the agreement, phantom issues, mediator msgs not in room API, agents cave to BATNA) — see Gate A |
| 2 | Pi + OpenShell brain for the *internal* mediator (`pi_brain.py`, `ALIGNER_BRAIN`) | ✅ code built (node-free) · ❌ **not run live** (Part B) |
| 2.5 | `ALIGNER_MODE` retired — the mediator is unconditionally the aligner (no flag) | ✅ done (pulled forward from Rung 3) |
| 3 | Retire the observer/driver engines + `parse_position_marker` | ⬜ later — deletion rung |

**The scope correction still holds** (see `START_HERE_MEDIATOR_RUNG2.md`): Pi is the runtime
for mycelium's *internal* cognition agents **only**. User/participant agents keep their own
framework (claude_code, cursor, …); Pi is never imposed on them, and Rung 2 changed **no**
user-facing adapter, `AGENT_ADAPTERS`, or `daemon/dispatch.py`/`runner.py` path.

---

## Gate A — validate Rung 1 live (DONE — architecture proven, 3 bugs found + fixed)

Run on 2026-08-05 against **real cold-spawned `claude_code` agents** over a live SLIM node
(dev compose, `llm.model=anthropic/claude-haiku-4-5`). Two agents (`@growth` aggressive /
`@risk` conservative) posted genuinely conflicting openings; `@aligner` was summoned via a human
`POST /messages` broadcast. Note there is **no `ALIGNER_MODE` to set** anymore — a summon
unconditionally mediates.

### Proven ✅
- The full path fires end-to-end: summon → `discover_issues` structures the messy real prose
  into issues+options (e.g. `tech_allocation_percentage ∈ {25,30,35,40}`,
  `per_sector_cap ∈ {20,25,30,no_hard_cap}`) → NEGMAS SAO → the mediator `@`-addresses agents →
  the daemon cold-spawns real `claude -p` turns → replies are interpreted into SAO moves.
- **Real agents genuinely negotiate.** `@growth` conceded 40%→35% and proposed a compromise;
  `@risk` rejected it (consistent with its hard 20%-cap line). Real concession, real
  disagreement — not theatre.
- NEGMAS **owns termination** and emits `commit:converged`, bounded.

### Bugs found → fixed (commit `f15f547`)
The live run surfaced three real defects; all are fixed on this branch with unit tests:

1. **Spurious wakes (the delivery killer).** The connector's `should_wake` wakes an agent on a
   raw `@handle` in the *message text* as well as the L9 recipient. The mediator's prompt embeds
   the broker's summary naming *both* agents, so **every turn woke everyone**, doubling
   cold-spawns and serialising the connectors until the addressed agent's real reply missed the
   round window (turns paced at exactly `ALIGNER_ROUND_TIMEOUT_S`). Fix: `aligner.py` neutralises
   `@` in the outgoing prompt (`_AT_MENTION`); only the L9 recipient wakes now.
2. **Silence was hallucinated, not failed-closed.** On a reply timeout `_slim_turn` returns `""`,
   and `interpret("")` made the LLM *invent* a full offer — so a negotiation could "converge"
   with no real agent input. Fix: `mediator.py:interpret` short-circuits empty prose to an empty
   reading (respond→reject, propose→hold); the interpreter LLM never sees `""`.
3. **The negotiation was invisible in the room.** The mediator published turn-prompts over SLIM
   but never recorded them locally, so the room/UI showed only the openings and the verdict —
   forcing all debugging into backend logs. Fix: `_slim_turn` records each prompt via
   `persister.ingest_local` (the same seam `publish_human` uses), so humans can follow along.

### Pristine converged run ✅ (fresh room `mediator-final`, post-fix)
With the three fixes in and a clean single-setup stack, a summon drove a real end-to-end
convergence:
```
step 0: @growth PROPOSE      (40% tech, 25% cap)
step 0: @risk   ACCEPT_OFFER (40% tech, 25% cap)
→ aligner (mediator) room mediator-final → agreement in 1 step
   {tech_allocation: 40%, per_sector_cap: 25%}
```
Wakes were **single per turn** (`@growth` 18:19:55, `@risk` 18:20:08 — 13s apart, no wake-storm),
replies landed in ~10s (no timeouts → the fail-closed path never fired), and NEGMAS **terminated**
on the unanimous accept. The anti-theatre property, confirmed live. (One-round because risk found
growth's opening offer acceptable — a clean agreement, not a long bargain.)

### Bugs found → NOT yet fixed (surfaced by the multi-round bargain runs)
Forcing a *multi-round* bargain (rooms `mediator-bargain` / `bargain2`, slow-concession personas
walking 40→30 vs 20→30, ZOPA at 30%) exposed deeper interpretation defects:

1. **Discretization can misreport the agreement — the important one.** In `bargain2` the agents
   genuinely bargained to **30%** in the room (`@risk`: *"tech must come down to 30%"* → `@growth`:
   *"Accept — 30% is exactly my floor"*), but the mediator **recorded 25%**. Cause: `discover_issues`
   fixes a *discrete* option set up front (here tech ∈ {…,25,35,…} with **no 30**), so NEGMAS runs
   on a grid the real agreement point isn't on, and `interpret`/`to_outcome` snaps the agreed "30"
   to a wrong option. **So the emitted `issue = value` map can differ from what the agents actually
   agreed to.** Sketch of the fix: constrain the option set to values the agents actually raise,
   use a finer/continuous scale, and **re-read the final agreement from the accepting agent's prose**
   rather than trusting the discretized outcome.
2. **`discover_issues` invents phantom issues.** Openings that mentioned only a tech percentage
   still produced 3–4 issues (`rebalancing_frequency`, `growth_vs_stability_tradeoff`,
   `performance_review_trigger`) the agents never raised — the discovery LLM pads the portfolio
   scenario. Discovery should be constrained to dimensions actually present in the positions.
3. **The mediator's own messages don't reach the room API.** Its turn-prompts *and* the final
   verdict never surfaced in `GET /messages` (only agent replies did), so a human watching the
   room sees the agents converge but not the mediator's proposals or the agreement. The
   `ingest_local` fix (fix #3 above) records them to the persister's log but they aren't reaching
   the list store the API/UI read — a second seam to wire.
4. **Agents cave under the mediator's BATNA push.** Even with rigid "hold your floor" personas,
   `@growth` repeatedly accepted below its floor. The mediator appends a strong BATNA to every
   agent prompt (`mediator.py:_BATNA` — *"a compromise you can live with beats no deal… concede
   everything secondary"*), which by design pushes agents to close fast. That's the anti-theatre
   goal working, but it fights a genuine multi-round bargain and can override stated hard lines —
   worth a knob to soften for scenarios where holding out matters.

### Still to capture ⬜
- Gate B (Pi brain live) and the OpenShell sandbox — see below.

### Operational notes (learned the hard way)
- **Raise `ALIGNER_ROUND_TIMEOUT_S`** well above a cold-spawn's latency (we used 90–150s); the
  default 30s turns real replies into timeouts.
- **Setup order:** register the agents, then `mycelium agent invoke` each once — that joins their
  connectors to the room channel *and* seeds openings — **then** summon `@aligner`. Summoning
  before the connectors join means the mediator has no one to address.
- **Backend restarts lose channel/member state.** After a recreate, re-invoke the agents to
  rejoin before summoning. Avoid rebuilding mid-negotiation.

---

## Gate B — validate the Pi brain live (only after Gate A)

Gate A proved the *loop*; Gate B swaps only the mediator's **brain** and re-proves the same
payoff. Because the seam is default-off, this is a config flip, not a redeploy.

- [ ] `pi` on PATH under the user the backend runs as (`which pi`; 0.65.0 verified in dev).
      Confirm `pi` is configured with a provider/model + key that matches `LLM_MODEL` —
      **note the endpoint caveat below.**
- [ ] Set `ALIGNER_BRAIN=pi` on the backend (a summon already mediates — no mode flag). Recreate the
      container to pick up env.
- [ ] Re-run the Gate A scenario. Expect the **same** bounded negotiation. In logs, the
      mediator's discover/broker/interpret turns now come from `pi` subprocesses; a session
      file appears under `<tmpdir>/mycelium-pi-sessions/<episode-slug>.jsonl` and **grows
      across rounds** (the point — real memory, not a re-threaded history string).
- [ ] **Payoff of Gate B:** identical converge → plan → memory outcome, now on a persistent,
      provider-agnostic, self-hostable internal runtime.

### Known rough edges to resolve during Gate B
- **Custom endpoints (`LLM_BASE_URL`) don't forward.** Pi has no `--base-url` flag;
  `PiBrain` logs a warning and sends to pi's default endpoint. If mycelium is pointed at a
  custom endpoint (vLLM, a Bedrock gateway, ollama), configure that provider in
  `~/.pi/agent/models.json` for the daemon's user and set `LLM_MODEL` to match. This is the
  most likely first failure — verify pi answers a bare `pi -p --model <model> "hi"` before
  blaming the mediator.
- **Temperature is ignored.** Pi exposes no temperature flag, so the mediator's
  discover(0.0)/broker(0.3)/interpret(0.0) temperatures are best-effort only. If interpretation
  drift is worse under Pi than litellm, that determinism gap is a suspect.
- **OpenShell sandbox is unvalidated.** `openshell` was **not installed** on the build host, so
  `PiBrain._sandbox_wrap` ships the documented best-guess invocation
  (`openshell sandbox exec --from pi -- …`) gated behind `ALIGNER_PI_OPENSHELL=false`. To
  validate: install NVIDIA/OpenShell, confirm the real exec syntax, correct `_sandbox_wrap` if
  it differs, then run Gate B with `ALIGNER_PI_OPENSHELL=true`. **Do not flip this on until the
  syntax is confirmed live** — a wrong prefix fails every turn (→ every move reads as a reject).
- **Serial-only.** One `PiBrain` == one session == one negotiation, driven strictly serially
  (the mediator's turn model guarantees it). Before trusting Pi sessions under *any*
  parallelism (e.g. two rooms mediating at once), run a deliberate concurrent-write test — a
  second negotiation gets its own `PiBrain`/session by construction (`_make_brain` keys the
  session file on the episode URN), but confirm no shared-session corruption.

---

## The config surface (Rung 2)

| Setting | Default | Meaning |
|---------|---------|---------|
| `ALIGNER_BRAIN` | `litellm` | `litellm` (stateless `llm_sync`) or `pi` (persistent Pi session). |
| `ALIGNER_PI_BINARY` | `pi` | Path/name of the `pi` binary. |
| `ALIGNER_PI_OPENSHELL` | `false` | Wrap each Pi session in an OpenShell sandbox. |
| `ALIGNER_PI_TIMEOUT_S` | `120.0` | Per-turn wall-clock bound before a Pi turn is killed. |
| `ALIGNER_ROUND_TIMEOUT_S` | `30.0` | How long the mediator waits for one agent's reply. **Raise to 90–150s for real cold-spawns** or their replies time out. |
| `ALIGNER_MEDIATOR_MAX_STEPS` | `20` | Hard SAO step cap (bounds cost). Lower (6–8) for cheap runs. |

Code: `app/services/pi_brain.py` (`PiBrain`, `parse_pi_json_output`),
`app/services/aligner.py` (`_make_brain`), `app/config.py`, `tests/test_pi_brain.py`.

---

## After both gates pass

- **Rung 3 (deletion rung, later):** the mode flag is already gone (Rung 2.5). What remains:
  delete the now-unreachable `observe`/`drive` methods + their helpers (kept only for
  `scripts/l9_slim_roundtrip.py` today), remove `daemon/connector.py:parse_position_marker` +
  the preamble's "position marker" block, and update the CLI skill/preamble. **Touches no user
  runtime.**
- **Reuse:** when the semantic-negotiation NEGMAS owner lands, it is another internal agent —
  give it the **same `PiBrain` seam**, no new machinery.

## References
- **Why + ledger:** `docs/START_HERE_MEDIATOR.md`. **The corrected Rung-2 spec:**
  `docs/START_HERE_MEDIATOR_RUNG2.md`.
- **Stack up / smoke ladder:** `docs/SMOKE_TEST_HANDOFF.md`, `docs/cross-machine.md`.
- **The proven core:** `experiments/sao-mediator-spike/`.
- **Runtime:** [Pi](https://github.com/earendil-works/pi), [NVIDIA OpenShell](https://github.com/NVIDIA/OpenShell),
  [NEGMAS](https://github.com/yasserfarouk/negmas).
- **Direction memory:** `project_mediator_pi_negmas`, `project_cfn_teardown_l9_pivot`.
