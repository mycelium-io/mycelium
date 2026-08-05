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
| 1 | Mediator drives live over SLIM (`aligner.py:mediate` + `mediator.py`) | ✅ **run live against real cold-spawned agents** — architecture proven, 3 bugs found + fixed (see Gate A below); ⬜ pristine re-run on a fresh room still to capture |
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

### Still to capture ⬜
- A **pristine end-to-end transcript** on a *fresh* room (new room + agents, single setup, no
  mid-run backend rebuilds) showing the fixed loop: single wake per turn, replies in seconds
  (not the timeout), a genuine two-sided convergence, and every turn visible in the room. The
  first live run's re-confirmation was muddied by repeated backend recreates in one session
  (which lose in-memory channel/membership state and left the mediator not firing on re-summon —
  an orchestration artifact, separate from the three fixes above). Do this fresh.

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
