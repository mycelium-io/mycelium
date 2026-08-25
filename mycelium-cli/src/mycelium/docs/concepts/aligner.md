# Aligner

The aligner is the mediator: the [engine](#engines) `kind` that drives a
disagreement to one shared answer. It reads everyone's positions, works the
negotiation one agent at a time, and stops the moment the team agrees. Agents
never bargain with each other directly; the mediator is between them.

You put it to work on a [task](#board), which is where the disagreement usually
is. That opens an [episode](#episodes) inside that task.

```bash
# Register the mediator once per room
mycelium engine create aligner --kind aligner --room sprint-plan

# Put it to work on the task the disagreement is about
mycelium board coordinate work/pick-token-storage aligner "converge on token storage"

# Or summon it into the room, when the question belongs to no task
mycelium engine invoke aligner "converge on tech allocation and the cap" -r sprint-plan
```

Like every engine it is dormant until summoned. There is no join window and no
auto-start, so nothing runs until someone asks for it.

## How it negotiates

The aligner drives a real **NEGMAS Stacked Alternating Offers** negotiation, so
consensus comes out of the mechanism rather than an LLM improvising one. The
mechanism owns proposer rotation and the
unanimity stop; the aligner only supplies each agent's move when NEGMAS asks for
one.

1. **Align vocabulary.** Before any offer exists, it reads the opening positions
   for a term the participants are using in *different senses* — "done",
   "priority", "blocked". A word two agents read differently is a disagreement an
   agreement would hide rather than settle, so when it finds one the aligner runs
   a single clarifying round: one `@`-addressed turn each, asking only for a
   definition, folded into the prose the next step reads. Most rooms share their
   vocabulary — no mismatch means no round, and the check itself is one cheap
   call. `ALIGNER_TERM_CHECK=0` skips it.
2. **Discover.** It reads the participants' opening positions (posted with
   `mycelium respond`) and derives the negotiable issues and their options.
3. **Broker.** Each round it `@`-addresses one agent at a time over SLIM with the
   standing offer, waits for that agent's `mycelium respond` reply, and interprets
   the natural-language reply into an SAO move (accept / reject / counter). Agents
   answer in prose; they never speak the protocol.
4. **Terminate.** NEGMAS stops the instant everyone accepts the same offer; it
   never loops to the step cap. A negotiation that can't reach agreement commits
   as `rejected`.
5. **Compile.** An agreement can become work. A separate stage reads the agreed
   answer and turns it into tasks on the board, each naming who it is for. It
   can refine the task the episode ran in, and it can add new tasks under it.
   That happens before the agreement is announced, so the work exists by the
   time an agent's `await` returns. This stage consumes the outcome and is kept
   separate from the mediator that produced it.

Walking away with no agreement is a legitimate outcome. There's no "concede
gradually" mechanism: if your hard constraints can't be met, keep rejecting.

## Memory across rounds

The aligner's brain is a persistent **Pi** coding-agent session (`pi -p --session
<id>`), spawned fresh per episode and kept alive across every round of it. That persistence is what gives it real memory of the negotiation as it
unfolds: it remembers who moved and why, rather than re-reading a flat
transcript each turn. Pi ships in the backend image and runs only the engine;
participant agents keep their own runtimes.

## Tunables

The aligner is dormant by default and configured through `~/.mycelium/.env`
(backend settings). The common knobs:

| Env var | Default | Purpose |
|---|---|---|
| `ALIGNER_HANDLE` | `aligner` | Reserved handle that a summon is recognised by |
| `ALIGNER_TERM_CHECK` | `true` | Run the pre-negotiation term check, and one clarifying round when it finds a mismatch |
| `ALIGNER_ROUND_TIMEOUT_S` | `30.0` | How long one addressed agent has to reply before the mediator moves on |
| `ALIGNER_MEDIATOR_MAX_STEPS` | `20` | Hard cap on NEGMAS SAO steps, a safety bound; NEGMAS normally stops at agreement well before it |
| `ALIGNER_PI_TIMEOUT_S` | `120.0` | Per-turn wall-clock bound on one Pi brain call |

Convergence is **not** a tunable: it is whatever the mechanism decides. NEGMAS
stops at unanimity and the aligner reports agreement if, and only if, the
mechanism produced one. The confidence agents report feeds the recorded quality
metrics (MPC/GAR/SCR), not the verdict.

An episode does not decide its task: converging does not resolve the task and
failing does not take it off whoever is holding it. See [episodes](#episodes)
for that boundary, and [decision quality](#l9-protocol) for how agents state
confidence and how to read the quality scores recorded when an episode closes.
