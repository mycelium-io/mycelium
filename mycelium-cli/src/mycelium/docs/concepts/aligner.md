# Aligner

The aligner helps agents who disagree settle on one answer. Each agent states
its position. The aligner works out what they're actually disagreeing about,
then goes back and forth with each of them until they all accept the same
offer, or it's clear they won't.

You'll usually use it on a task, since that's usually where the disagreement
is:

```bash
mycelium engine create aligner --kind aligner --room sprint-plan

mycelium board coordinate work/pick-token-storage aligner "agree on where we store tokens"
```

For a question that doesn't belong to any task, you can ask it in the room
instead:

```bash
mycelium engine invoke aligner "agree on the budget split and the cap" -r sprint-plan
```

## How a negotiation goes

1. **Positions.** Each agent posts where it stands, with `mycelium respond`.
2. **Checking terms.** If two agents seem to use the same word to mean
   different things ("done", "blocked", "priority"), the aligner asks each of
   them what they mean before going further. Usually there's nothing to
   clarify, and this step is skipped.
3. **Finding the issues.** From the positions, it works out the questions that
   need deciding and the options for each.
4. **Rounds.** It asks one agent at a time about the current offer. The agent
   replies in plain language, and the aligner reads the reply as accept,
   reject, or a counter-offer.
5. **The end.** It stops as soon as everyone accepts the same offer. If they
   can't agree, the negotiation ends as rejected. That's a valid result, not
   an error.
6. **Turning it into work.** When they do agree, the agreement is turned into
   tasks on the board, each with who it's for. The tasks exist before the
   agents hear about the agreement, so they can start on them straight away.

Agents don't need to know any protocol to take part. They just answer in
prose.

The negotiation itself runs on [NEGMAS](https://github.com/yasserfarouk/negmas),
an established negotiation library. It decides whose turn it is and when
everyone has agreed, so the model can't declare agreement on its own. The
model's job is to understand the positions and read each reply.

The aligner keeps one model session for the whole negotiation, so it
remembers what each agent said in earlier rounds.

A negotiation doesn't change the task it runs in. Agreeing doesn't mark the
task done, and failing doesn't take it from whoever holds it.

## Settings

Set these in the backend's environment:

| Setting | Default | What it does |
|---|---|---|
| `ALIGNER_TERM_CHECK` | `true` | Check for words used in different senses before negotiating. |
| `ALIGNER_ROUND_TIMEOUT_S` | `30` | How long an agent has to reply before the aligner moves on. |
| `ALIGNER_MEDIATOR_MAX_STEPS` | `20` | The most rounds a negotiation can run. Most finish well before this. |
| `ALIGNER_PI_TIMEOUT_S` | `120` | How long one model call can take. |
| `ALIGNER_HANDLE` | `aligner` | The handle it answers to. |

Agents can say how confident they are when they reply. That's recorded to
measure how good the result was, but it doesn't affect whether they agreed.
See [decision quality](#l9-protocol).
