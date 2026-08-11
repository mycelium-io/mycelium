# Episodes

An episode is one recorded negotiation. Summoning the [aligner](#aligner) on a
[room](#rooms) opens an episode: a scoped, membership-tagged round on the room's
existing SLIM channel (a tag on that channel, *not* a separate channel). Each
convening is a distinct episode with its own id, its own slice of the transcript,
and a 1:1 record at `log/episodes/{id}.md` (the full causally-linked
[L9](#l9-protocol) envelope chain). Rooms persist; an episode is the arc of a
single question being converged on.

There is no session to create, join, or await, and no join window. You address
the room and the aligner directly.

## The lifecycle

1. **Openings.** Each participant posts their opening position with
   `mycelium respond --handle <handle> "<position>"`. The backend records it for
   the aligner to read.
2. **Summon.** A human summons the mediator: `mycelium engine invoke aligner
   "converge on <the question>"`. This opens the episode.
3. **Rounds.** Participants loop: `mycelium await --handle <handle> --json` reads
   the prompt the aligner `@`-addressed to them, then `mycelium respond --handle
   <handle> "<accept / reject / counter + one line why>"` replies. The aligner
   runs a real NEGMAS Stacked Alternating Offers negotiation, brokering one agent
   at a time.
4. **Termination.** NEGMAS owns the stop: the episode ends the instant everyone
   agrees, never looping to a cap.
5. **Consensus → plan.** On agreement the aligner emits `commit:converged` with
   the agreed `{issue: value}` map, the episode is recorded, and `plan_compiler`
   builds the room's shared [`plan/tasks.md`](#plan) before consensus is
   announced (so the plan exists when `await` returns).

The arc doesn't stop at consensus; it flows into work: **converge → plan →
work**. Consensus decides *what*; the plan is *how the team carries it out*.
Agents read it with `mycelium plan tasks -r <room>` and work their `@handle` tasks.

## Rooms vs episodes

| | Room | Episode |
|---|------|---------|
| Lifetime | Persistent | One recorded negotiation |
| Purpose | Namespace for memory + coordination | Converge on a single question |
| Channel | Owns the SLIM channel | A membership-scoped tag on it |
| Memory | Yes, scoped to the room | Uses the room's memory; recorded to it |
| Multiple | One room, many episodes over time | Each convening is a distinct episode |

## Epistemic annotations

An episode carries an optional epistemic layer from the [L9 protocol](#l9-protocol):

- A reply can append an inline position marker with its confidence and stance,
  e.g. `mycelium respond --handle me "I can move to 30% [[mycelium: confidence=0.85
  stance=accept]]"`. The backend lifts it onto the L9 payload so the aligner can
  score it, and strips it from the posted prose.
- On convergence the record carries consensus quality metrics: **MPC** (mean
  posterior confidence), **GAR** (genuine agreement ratio, how many agents
  actually moved toward the outcome), and **SCR** (social compliance ratio:
  accepts made to yield rather than from conviction), with a derived
  `provenance_weight`.

All of it is optional. Agents that ignore it negotiate exactly the same. See
[L9 Protocol](#l9-protocol) for the envelope format and the metric definitions.

## Multiple episodes

A room hosts many episodes over time. When one closes, summon the aligner again
for the next decision. The room's memory persists across all of them, so each
episode starts with full context from the ones before it.

```bash
# First episode
mycelium respond --handle planner "Prioritize the database migration" -r sprint-plan
mycelium engine invoke aligner "converge on the sprint's first priority" -r sprint-plan

# ... it converges, plan/tasks.md is written ...

# Second episode (room memory carries over)
mycelium respond --handle planner "Now let's plan the API layer" -r sprint-plan
mycelium engine invoke aligner "converge on the API layer scope" -r sprint-plan
```
