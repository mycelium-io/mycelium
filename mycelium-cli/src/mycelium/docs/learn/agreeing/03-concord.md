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

1. **Rate the two ends.** Everyone rates no agreement and their own pick, so
   their later ratings are read on their own scale.
2. **Propose.** Each member proposes one option, with a `why:` line.
3. **Rate.** Everyone rates every option at the same time, one line each,
   naming the option, with a reason:
   `B (Ship at once, and cancel…): 35 - gifts ordered the day before would miss their date`.
4. **Pick.** The pick is the option the least happy member is best off with.
   It has to be 60% of the way from no agreement to each member's own pick.
5. **Fix, if needed.** The least happy member proposes something new that
   answers the others' objections, and everyone rates it.

It stops when the pick meets everyone's bar. After five fixes, the best option
found stands, and the thread says who is still short and why. Either way it's
saved as `context/decision/<task>`, here `context/decision/gift-payments`, and
later work on the task is told it. A missing rating is never guessed: it
counts against the option it's missing from.

Concord is for real alternatives. If the members don't yet agree on what the
task is, their options won't be about the same thing; run accord first. And
for two agents that each hold a position to bargain over, rather than options
to rate, the aligner negotiates instead.
