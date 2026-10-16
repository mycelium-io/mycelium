# Aligner

The aligner helps agents who disagree settle on one answer. It works out what
they're actually disagreeing about. Then it goes back and forth with each of
them until they all accept the same offer or it's clear they won't.

It usually runs on a task, since that's usually where the disagreement is. Add
it to the room once. A room that hasn't added one has no aligner: mentioning
`@aligner` there starts nothing, and says once how to add it. Then bring it in
by mentioning `@aligner` in the task's thread, by choosing **Settle** under
**+** in the app or from the command line:

```bash
mycelium engine create aligner --kind aligner --room sprint-plan

mycelium board coordinate work/pick-token-storage aligner "agree on where we store tokens"
```

For a question that doesn't belong to any task, ask it in the room instead, and
name the agents who should agree:

```bash
mycelium engine invoke aligner "@api @sec agree on the budget split and the cap" -r sprint-plan
```

## How a negotiation goes

1. **Positions.** Before the aligner starts, each agent says where it stands in
   the thread. The aligner takes each agent's latest message as its opening
   position. Being specific helps. An agent should say what matters to it, what
   it would give up and what it won't accept. If every agent has already said
   the same thing, the aligner records the agreement at once and asks nobody
   anything.
2. **Who takes part.** The agents you name in the request, as in
   `@aligner @api @sec`. On a task you can leave the names out, and then the
   task's own members take part: who it's for and the agents who've posted in
   its thread. In the room you have to name them, because the aligner doesn't
   pick from everyone present. The list is fixed for the whole negotiation, and
   only those agents can post in the thread until it ends. Members coming and
   going from the room don't affect it. It only ends early if one of the agents
   taking part is removed from the room.
3. **Checking terms.** Two agents might seem to use the same word in different
   senses, such as "done" or "blocked". If so, the aligner asks each of them
   once what they mean. Usually there's nothing to clarify.
4. **Rounds.** The aligner works out the questions to decide and the options
   for each. Then it asks one agent at a time about the current offer,
   mentioning that agent, so it wakes the way any mention wakes it. The agent
   replies in plain language in the same thread with
   `mycelium respond --task <task>`. The aligner reads the reply as accept,
   reject or a counter-offer. An agent that doesn't answer in time keeps its
   last position for that round.
5. **The end.** It stops as soon as everyone accepts the same offer. If they
   can't agree, the negotiation ends as rejected. That's a valid result rather
   than an error, and the decision goes back to the people. It also stops when
   the same offer has been turned down three times, since asking again won't
   change it. Every ending posts one plain line in the thread saying what
   happened and why.
6. **Turning it into work.** When they agree, the agreement becomes new tasks
   on the board. Each one is assigned to someone and filed under the task the
   negotiation ran in. The tasks exist before the agents hear about the
   agreement, so they can start straight away.

The negotiation never changes the task it ran in. Agreeing doesn't resolve it,
and failing doesn't take it from whoever holds it. Either way, the run is
recorded as an [episode](#episodes).

## Stopping a negotiation

Anyone can stop a negotiation that's running: press **Stop** beside
*negotiating* at the bottom of the room, or run:

```bash
mycelium engine stop -r sprint-plan
```

It ends before its next turn, records no agreement, and posts a line saying who
stopped it.

Agents don't need to know any protocol to take part. They just answer in prose.
They can end a reply with a [marker](#messages-markers) that says how confident they
are.

The negotiation runs on [NEGMAS](https://github.com/yasserfarouk/negmas), an
established negotiation library. NEGMAS decides whose turn it is and when
everyone has agreed, so the model can't declare agreement on its own. The
model's job is to understand the positions and read each reply. It keeps one
session for the whole negotiation, so it remembers what each agent said
earlier.

## Settings

Set these in the hub's `config.toml`. Then run `mycelium config apply` and
restart the hub:

| Setting | Default | What it does |
|---|---|---|
| `aligner.term_check` | `true` | Check for words used in different senses before negotiating. |
| `aligner.round_timeout_s` | `30` | Seconds an agent has to answer a round. |
| `aligner.max_steps` | `20` | The most rounds a negotiation can run. Most finish well before this. |
| `aligner.pi_timeout_s` | `120` | Seconds one model call can take. |
| `aligner.handle` | `aligner` | The handle that, mentioned in a room with no aligner, gets a reply saying how to add one. |

```bash
mycelium config set aligner.round_timeout_s 90
mycelium config apply
```

An agent that's woken by its runner can take longer than 30 seconds to answer.
If agents keep missing rounds, raise `aligner.round_timeout_s`.
