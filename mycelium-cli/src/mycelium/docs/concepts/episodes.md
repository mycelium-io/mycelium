# Episodes

**An episode is one scoped conversation inside a room.**

A room has a single channel, and an episode is a tagged slice of it: a set of
messages that belong together and can be read on their own. Two things are
episodes.

The first is a [task](#board)'s **thread**. Every task gets one when it is
created, no two tasks share one, and it lasts as long as the task does. That is
the ordinary case, and it needs no ceremony: you talk in a task and you are
talking in its episode.

The second is a **coordination phase**: a bounded stretch of work inside a
task's thread, driven by an engine, with a record of its own. Two engines open
one. The [aligner](#aligner) mediates a disagreement: two or more agents
differ on a trade-off with several moving parts, someone puts the mediator on
the task, and it drives them to one answer or to a clean failure to agree. The
[conductor](#conductor) walks a fixed interaction shape, a proposer and a
guardian, a lead and its workers, members speaking in turn; its record carries
the flow and every step taken, so the phase shows the shape of the interaction
and where it stands, not only its messages.

A coordination phase is a recorded slice of the task's own thread, not a
thread of its own. So a room holds tasks, a task holds its thread, and a
coordination phase is something that can happen inside that thread. The task
outlives it.

## Opening one

```bash
mycelium board coordinate work/pick-token-storage aligner "converge on token storage"
```

The ask lands in the task's thread and the [aligner](#aligner) starts working.
There is no session to create, join or wait for.

When the question belongs to no task, summon the engine into the room instead:

```bash
mycelium engine invoke aligner "converge on the Q3 migration plan" -r sprint-plan
```

Register the mediator once per room before either form works:

```bash
mycelium engine create aligner --kind aligner --room sprint-plan
```

## The lifecycle

1. **Positions.** Participants say what they want and why, in the task's thread
   or with `mycelium respond`. A position is ordinary prose. Being specific
   matters more than being brief: a stake, a concession you would make, and a
   hard limit.
2. **Open.** Someone runs `board coordinate`. That starts the episode.
3. **Rounds.** The aligner works out what is actually in dispute, then addresses
   one agent at a time with the offer on the table and waits for that agent's
   reply. Agents answer in prose; the mediator reads each reply as an accept, a
   reject or a counter-offer. An agent stays in `mycelium await` and answers when
   addressed.
4. **Termination.** The mechanism stops the instant every participant accepts
   the same offer. It does not keep going to a step cap, and it does not
   re-state an agreement that already happened.
5. **Outcome.** Either the team agreed on one answer, or it did not. Both are
   real endings, and a failure to agree is recorded as one rather than papered
   over.

An agreement can become work: it can refine the task it ran in, and it can add
new tasks to the board, each with its own thread. Those rows carry who each
task is for and land before the agreement is announced, so the work exists by
the time an agent's `await` returns.

## What a coordination phase does not decide

- **It does not resolve the task.** Converging inside a task does not finish it;
  `board resolve` does.
- **It does not change custody.** One that fails does not take the task off
  whoever is holding it.
- **It is not required.** A task can be created, claimed, worked and resolved
  with no coordination phase ever opened. Most are.

While a coordination phase is running, its participants are fixed. An agent
who was not at the table cannot drop a position into it, because a round of offers scored
across a set of participants means nothing if an outsider can add to it midway.
That is the one case where a thread restricts who may speak.

## Rooms, tasks and episodes

| | Room | Task | Coordination phase |
|---|---|---|---|
| Lifetime | Persistent | Until it resolves | One bounded stretch of talk |
| Holds | Memory, tasks, the channel | Its own thread and lifecycle | Its rounds and its outcome |
| How many | One per team or project | Many per room | Zero or more per task |
| Ends when | You delete it | Someone resolves it | The team agrees, or does not |

## The record

Every coordination phase is recorded to the room's memory at
`log/episodes/{id}.md`: who took part, what was offered, how it ended. It is a memory like any other, so it
is searchable by meaning and readable months later when someone asks why the
team decided this.

If enough participants said how confident they were, the record also carries
quality scores for the agreement: how sure the team was, how many were actually
persuaded rather than going along with it, and a single trust number combining
the two. Those are worth reading, because two episodes can both end in
unanimous agreement and mean very different things. See
[decision quality](#l9-protocol) for how to state confidence and how to read the
scores.

## Many over time

A room hosts many of both. The room's memory persists across all of them, so
each one starts with the context of everything decided before it.

```bash
# A disagreement inside one task
mycelium board coordinate work/pick-token-storage aligner "converge on token storage"

# ... it agrees, the task is refined and child tasks land ...

# A later question, in its own task, with the room's memory carried over
mycelium board new "Plan the API layer"
mycelium board coordinate work/plan-the-api-layer aligner "converge on the API layer scope"
```
