# Lay out work that hands itself off

Give the lead (your PM, or a swarm's first member) the whole goal, and have it
file the work as a chain: each task for the agent who'll do it, waiting on the
one before it, and all of them part of the goal.

```bash
mycelium memory set work/gift-cards-checkout "Pay with a gift card at checkout" \
  -m assignee=coder -m depends-on=work/gift-cards-api -m part-of=work/ship-gift-cards
```

The board shows a waiting task as **after work/gift-cards-api**, so you can see
the order at a glance. Then three lines in the agents' briefs make the chain run
itself:

```markdown
- When a task is filed for you, claim it right away, even if it's waiting.
- When you resolve a task, @mention whoever is waiting on it.
- When you find work that belongs to someone else, file it for them with
  `mycelium board new "<what>" --assign @<who>`, and say so in your thread.
- Whoever resolves the last part tells the lead, who writes the summary.
```

Claiming at once matters for you as much as for them: a task nobody has claimed
counts as needing you, so a chain whose tasks sit unclaimed fills your "Needs
you" with work that's simply waiting its turn.

> Hub workers in a swarm already do the last step on their own: when the last
> part resolves, the lead combines them. Agents on your machine do it because
> their brief says so.
