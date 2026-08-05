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
| 1 | Mediator drives live over SLIM (`aligner.py:mediate` + `mediator.py`) | ✅ code merged · ❌ **not run live** (Part A) |
| 2 | Pi + OpenShell brain for the *internal* mediator (`pi_brain.py`, `ALIGNER_BRAIN`) | ✅ code built (node-free) · ❌ **not run live** (Part B) |
| 3 | Retire the old surface (observer + `parse_position_marker`) | ⬜ later — deletion rung |

**The scope correction still holds** (see `START_HERE_MEDIATOR_RUNG2.md`): Pi is the runtime
for mycelium's *internal* cognition agents **only**. User/participant agents keep their own
framework (claude_code, cursor, …); Pi is never imposed on them, and Rung 2 changed **no**
user-facing adapter, `AGENT_ADAPTERS`, or `daemon/dispatch.py`/`runner.py` path.

---

## Gate A — validate Rung 1 live (do this first)

This is unchanged from `START_HERE_MEDIATOR_RUNG2.md` Part A — reproduced as a checklist.
Lean on `docs/SMOKE_TEST_HANDOFF.md` to bring the stack up.

- [ ] Backend + SLIM node up (dev compose); `llm.model` + `llm.api_key` configured
      (`mycelium config set …` → `mycelium config apply`; recreate the backend container).
- [ ] `ALIGNER_MODE=mediator` set on the backend. (Leave `ALIGNER_BRAIN=litellm` for Gate A —
      isolate one variable at a time.) Optionally lower `ALIGNER_MEDIATOR_MAX_STEPS` for a
      cheaper first run.
- [ ] Two or three real user agents (e.g. `claude_code`) in a room, each having posted a
      genuinely conflicting **opening position** into the transcript.
- [ ] Summon the mediator (`@aligner`). In backend logs: `discover_issues` logs the issues,
      then per-step `mediator step N: @handle PROPOSE …` / `… ACCEPT on …`.
- [ ] **Payoff:** agents reach agreement and the mediator **stops** (no seven-round restating
      tail). It emits `commit:converged` with the `issue = value` map, `plan_sync` compiles
      `plan/tasks.md`, memory syncs. **Capture the transcript** — this is the before/after vs.
      the H5 theatre.

**Most likely break points** (debug order): interpretation drift on messy prose (watch the
echo-back `recording @growth as counter → …`; strengthen `mediator.py:interpret` /
`aligner.py:_fold_reading` if a misread isn't visible); turn timing (raise
`ALIGNER_ROUND_TIMEOUT_S` if real cold-spawns exceed 30s — a slow reply reads as `""` → a
reject); no opening positions (discovery rejects cleanly — ensure agents speak first); silent
SLIM degradation (bible debts D3/D6 — if "nothing happens," check backend + daemon logs).

---

## Gate B — validate the Pi brain live (only after Gate A)

Gate A proved the *loop*; Gate B swaps only the mediator's **brain** and re-proves the same
payoff. Because the seam is default-off, this is a config flip, not a redeploy.

- [ ] `pi` on PATH under the user the backend runs as (`which pi`; 0.65.0 verified in dev).
      Confirm `pi` is configured with a provider/model + key that matches `LLM_MODEL` —
      **note the endpoint caveat below.**
- [ ] Set `ALIGNER_BRAIN=pi` on the backend (keep `ALIGNER_MODE=mediator`). Recreate the
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

Code: `app/services/pi_brain.py` (`PiBrain`, `parse_pi_json_output`),
`app/services/aligner.py` (`_make_brain`), `app/config.py`, `tests/test_pi_brain.py`.

---

## After both gates pass

- **Rung 3 (deletion rung, later):** remove the observer engine +
  `daemon/connector.py:parse_position_marker` + the preamble's "position marker" block; flip
  the mediator to the default mode; update the CLI skill/preamble. **Still touches no user
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
