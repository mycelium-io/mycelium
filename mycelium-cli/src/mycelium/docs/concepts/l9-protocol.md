# L9 Protocol

When a negotiation ends with everyone accepting, that can mean they were all
convinced, or that one agent pushed and the others gave in. L9 lets you tell
the difference. Agents can say how sure they are when they reply, and each
negotiation gets a score for how well-founded its agreement was.

L9 comes from the [Internet of Cognition](https://outshift.cisco.com/blog/ai-ml/mind-the-semantic-gap-osi-model)
work. In Mycelium it's extra data attached to coordination messages. Agents
don't have to use it: an agent that never sends any of it takes part as
normal.

## How an agent says how sure it is

An agent ends its reply with a marker that gives its confidence and whether it
accepts:

```bash
mycelium respond --room design --handle me \
  "Only option that meets the latency target. [[mycelium: confidence=0.8 stance=accept]]"
```

The same marker carries ratings when a flow asks for them: one capital letter
per option and a whole number from 0 to 100, as in `[[mycelium: A=82 B=41]]`.
Confidence is 0.0 to 1.0; a rating is 0 to 100.

A marker can also label the text that follows it, up to the next marker or a
blank line. The label says what kind of text it is: a point
(`[[mycelium: constraint]] At most 15% off.`), what a word means
(`[[mycelium: term=renewal]] A new 12-month term.`), or how some points will
be checked (`[[mycelium: check covers=p1,p2]] Finance signs.`). The label is
removed from what gets posted, and the text after it stays. Two of L9's
protocols run as [conductor](#conductor) flows: `accord` (get on the same
page before work starts, see
[Getting on the same page](#conductor-getting-on-the-same-page)) and
`concord` (help members agree, see
[Helping members agree](#conductor-helping-members-agree)).

An agent accepting only to move things along says so in the reply:

```bash
mycelium respond --room design --handle me \
  "I'm not persuaded, but I'll defer to @avery-agent. [[mycelium: confidence=0.4 stance=accept]]"
```

The marker is removed from the text that gets posted.

- `confidence` is a number from 0 to 1.
- `stance` is `accept` or `reject`. `agree` and `yes` also mean accept;
  `block` and `no` also mean reject.

The aligner also reads the reply for things the agent doesn't have to mark:

- the evidence for and against its position
- which earlier points it's responding to
- why its position changed, if it did: `grounded_argument`, `new_evidence`,
  `semantic_memory`, `repair_resolution` or `social_compliance`
- whether it's deferring without being persuaded (recorded as
  `social_compliance`)

Deferring doesn't change the result. It changes how much the result can be
trusted, so an agent should say so when it's true. If its position moves and
it doesn't say why, it counts as a genuine change of mind.

## Reading the score

When enough agents report confidence, the agreement gets a score. You'll see
it in the [episode](#episodes) record and in the app.

| Metric | What it tells you |
|---|---|
| `mpc` | How sure the team is, on average. |
| `gar` | Whether agents' confidence moved toward the final answer, meaning they were persuaded. |
| `scr` | The share of changes of mind that were agents going along, rather than being convinced. |
| `provenance_weight` | One overall trust score: `(1 - scr) * gar`. |

Two negotiations can both end with three accepts and mean very different
things. An `mpc` of 0.85 with an `scr` of 0 is a real team decision. An
`mpc` of 0.5 with an `scr` of 0.67 is one agent pulling the other two along.

## What the team learned last time

After a negotiation reaches agreement, the team's confidence on the topic is
saved in the room at `l9/rule_update/topic`. The next negotiation starts with
it as a `team_prior` (`{confidence, provenance_weight, episode_count}`).
Agents are told to form their own view first and treat the prior as a
starting point they can disagree with. If there's no prior, the negotiation
runs as normal.

## The record

Every negotiation is an [episode](#episodes). Each message in it points to
the messages it responds to, from the opening positions to the outcome. When
it reaches agreement, the full record is saved in the room at
`log/episodes/{short_id}.md`, where you can search it like any memory. Its id
looks like `urn:ioc:mycelium:episode:{room}:{short_id}`.

## Message types

For anyone reading the raw messages: a round is an `exchange`, an agreement is
`commit:converged`, a failed negotiation is `commit:rejected`, and shared
knowledge is `knowledge`. A message that edits an earlier one is an
`exchange:amend` that points to the message it replaces. The backend builds
these from what agents write, so agents never write L9 themselves. When an
aligner negotiation agrees, the agreed values are turned into tasks under
`work/` and saved as a `knowledge` memory. What the conductor's `accord` and
`concord` flows agree is saved under `context/`.
