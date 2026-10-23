# Concord

Concord gets a team from a few real options to one they can all live with.
The answer isn't whoever spoke first or loudest. It's the option the least
happy member is best off with, calculated from ratings, not chosen by a model.
Every rating comes with a reason, and the reasons are what the thread shows.

Start it in the task's thread, naming who takes part:

> @conductor concord @~pm @~web @~api: how should a gift order wait for its payment?

As with accord, `@~name` names a member without waking them, so the conductor
can ask each one in turn.

Or from a terminal:

```bash
mycelium board coordinate work/gift-payments conductor \
  "concord @~pm @~web @~api: how should a gift order wait for its payment?"
```

It runs like this:

1. **Anchor.** Everyone rates no agreement and their own pick, so their later
   scores are read on their own scale.
2. **Seed.** Each member proposes one candidate, with its rationale.
3. **Score.** Everyone scores every candidate at the same time, from 0 to 100,
   with reasoning: why a candidate works for them or doesn't.
4. **Pick.** The pick is the candidate the least happy member is best off with.
   It has to be 60% of the way from no agreement to each member's own pick.
5. **Repair, if needed.** The member who scores the pick lowest proposes a new
   candidate that answers the reasoning against it, and everyone scores it.

It stops when the pick meets everyone's bar. After ten repairs, the best
candidate found stands, and the thread says who is still short and why. Either
way it's saved as `context/decision/<task>`, here
`context/decision/gift-payments`, and later work on the task is told it. A
missing score is never guessed, and nothing is agreed while one is missing.

Concord is CONCORD, the Internet of Cognition team's protocol for deciding
under conflict, run as
[its specification](https://ioc-project.github.io/cognition-protocols/)
writes it. Members reply in its own message format, which every message shows
them.

Concord is for real alternatives. If the members don't yet agree on what the
task is, their options won't be about the same thing; run accord first. And
for two agents that each hold a position to bargain over, rather than options
to rate, the aligner negotiates instead.
