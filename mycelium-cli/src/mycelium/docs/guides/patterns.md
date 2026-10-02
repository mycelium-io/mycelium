# Patterns

A pattern is a way for a team of agents to work through a problem together: a
supervisor who asks specialists, a critic who tests a proposal, an agent that
proposes and a person who approves. Mycelium runs patterns as **scenarios**: a
small room, ready to go, with its members, what they know, a task and the flow
that sets them working.

## Watch one run

Open **/patterns** in the app. Pick a pattern on the left; the middle column
shows who is in the room, and the rest of the page shows the run:

- **Before and now.** Where the run started, and where it stands. The hub
  restates the second after every step, so you can watch a proposal change as
  the agents argue.
- **The flow.** The steps the [conductor](#engines) walks, with the current
  one lit. The conductor has no model: it only decides whose turn it is.
- **What they said.** Each agent is a model playing a role written in plain
  English; nobody is scripted.

**Run it** starts the pattern in a new room. When the flow asks you something,
like approving a refund, the box at the bottom turns into **Approve** and
**Block**. The **?** button walks through the page.

The agents in a pattern think with the hub's [model](#models), so set one
first.

## Give a hub a pack

Patterns come from a **pack**, a folder of scenarios. Point the hub at one:

```bash
mycelium config set patterns.dir ~/patterns
mycelium config apply
```

The hub reads the pack and never fetches anything a caller names. On a hub
other people can reach, keep it to personas:

```bash
mycelium config set patterns.personas_only true
```

From a terminal, `mycelium pattern ls` lists what a hub offers, and
`mycelium pattern use <name> --run` loads one and starts it.

## Write a scenario

A scenario is one `scenario.yaml` in `scenarios/<pattern>/`:

```yaml
pattern: approval-gate-agent
title: Approval gate
summary: An agent proposes a spend, and a person approves or blocks it.
room: {title: Refund batch needs sign-off}
context:
  - key: context/refund-policy
    text: A batch over $5,000 needs a person's approval.
members:
  - handle: ops
    kind: persona
    description: Prepares refunds and proposes them for approval.
    notes: You are the ops agent. You may not issue refunds yourself...
  - handle: you
    kind: human
task: {title: Refund 23 duplicate charges}
summon: {flow: gated, members: [ops, you], ask: Refund the 23 duplicate charges.}
before:
  headline: $8,400 in refunds, ready to go
  detail: The batch is over the limit, so a person has to sign off.
after:
  track: Whether the refunds were approved, and how the proposal changed.
guide:
  - at: turn
    title: Your call
    text: Approve, or block with a reason.
```

`notes` is a persona's character. `summon.members` fills the flow's roles in
order. A scenario can bring its own flow in a `protocol.yaml` beside it
(`flow_file`). `before`, `after` and `guide` are for whoever watches: where the
run starts, what its result is about (the hub restates it with this in mind),
and a short walk through the page, each step pointed at `before`, `after`,
`members`, `flow`, `chat` or `turn`.
