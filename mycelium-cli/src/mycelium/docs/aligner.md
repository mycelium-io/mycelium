# Aligner

The aligner is the negotiation [engine](#engines): the `kind` that mediates a
decision to consensus. Agents never talk to each other directly; all
coordination flows through it. It reads everyone's opening positions, brokers the
negotiation one agent at a time, and stops the moment the team agrees.

Like every engine, the aligner is *summoned*: nothing runs until you register it
in a [room](#rooms) and invoke it. There is no join window and no auto-start.

```bash
# Register the mediator once per room
mycelium engine create aligner --kind aligner --room sprint-plan

# Summon it to open an episode
mycelium engine invoke aligner "converge on tech allocation and the cap" -r sprint-plan
```

## How it negotiates

The aligner drives a real **NEGMAS Stacked Alternating Offers** negotiation, so
consensus comes out of the mechanism rather than an LLM improvising one. The
mechanism owns proposer rotation and the
unanimity stop; the aligner only supplies each agent's move when NEGMAS asks for
one.

1. **Discover.** It reads the participants' opening positions (posted with
   `mycelium respond`) and derives the negotiable issues and their options.
2. **Broker.** Each round it `@`-addresses one agent at a time over SLIM with the
   standing offer, waits for that agent's `mycelium respond` reply, and interprets
   the natural-language reply into an SAO move (accept / reject / counter). Agents
   answer in prose; they never speak the protocol.
3. **Terminate.** NEGMAS stops the instant everyone accepts the same offer; it
   never loops to the step cap. A negotiation that can't reach agreement commits
   as `rejected`.
4. **Compile.** On agreement the aligner emits `commit:converged` carrying the
   agreed `{issue: value}` map, and `plan_compiler` (a separate LLM stage that
   *consumes* the outcome, distinct from the negotiation engine) turns it into the
   room's [shared plan](#plan), `plan/tasks.md`: a `- [ ]` checklist with
   `@handle` owners. This runs before the consensus is announced, so the plan
   exists by the time `await` returns.

Walking away with no agreement is a legitimate outcome. There's no "concede
gradually" mechanism: if your hard constraints can't be met, keep rejecting.

## Memory across rounds

The aligner's brain is a persistent **Pi** coding-agent session (`pi -p --session
<id>`), spawned fresh per episode and kept alive across every round of that
episode. That persistence is what gives it real memory of the negotiation as it
unfolds: it remembers who moved and why, rather than re-reading a flat
transcript each turn. Pi ships in the backend image and runs only the engine;
participant agents keep their own runtimes.

## Tunables

The aligner is dormant by default and configured through `~/.mycelium/.env`
(backend settings). The common knobs:

| Env var | Default | Purpose |
|---|---|---|
| `ALIGNER_HANDLE` | `aligner` | Reserved handle that a summon is recognised by |
| `ALIGNER_ROUND_TIMEOUT_S` | `30.0` | How long one addressed agent has to reply before the mediator moves on |
| `ALIGNER_MEDIATOR_MAX_STEPS` | `20` | Hard cap on NEGMAS SAO steps, a safety bound; NEGMAS normally stops at agreement well before it |
| `ALIGNER_PI_TIMEOUT_S` | `120.0` | Per-turn wall-clock bound on one Pi brain call |

Convergence is **not** a tunable: it is whatever the mechanism decides. NEGMAS
stops at unanimity and the aligner reports agreement if, and only if, the
mechanism produced one. The confidence agents report feeds the recorded quality
metrics (MPC/GAR/SCR), not the verdict.

See [L9 Protocol](#l9-protocol) for the envelope format, epistemic reply fields,
and the consensus quality metrics the aligner records at close.
