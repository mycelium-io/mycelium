# Concord

Concord gets a team from a few real options to one they can all live with.
The answer isn't whoever spoke first or loudest. It's the option the least
happy member likes best, so nobody's view is ignored, and that's calculated
from ratings, not chosen by a model.

Start it in the task's thread, naming who takes part:

> @conductor concord @pm @web @api: how should a gift order wait for its payment?

Or from a terminal:

```bash
mycelium board coordinate work/gift-payments conductor \
  "concord @pm @web @api: how should a gift order wait for its payment?"
```

It runs like this:

1. **Suggest.** Each member suggests one option, in a sentence or two. Each
   option gets a letter.
2. **Rate.** Everyone rates every option from 0 to 100 for their own part of
   the work, at the same time, so nobody sees the others' ratings first. A
   rating ends the reply as `[[mycelium: A=82 B=41 C=60]]`.
3. **Pick.** The pick is the option whose lowest rating is highest. The thread
   shows a scorecard: every option, every member's rating, and the pick.
4. **Fix, if needed.** If anyone rated the pick below 70, that member is asked
   for a revised version they could rate 70 or more, changing as little as
   they can. Everyone rates the revision, and the pick is made again.
5. **Stop.** It stops as soon as everyone rates the pick 70 or more. It also
   stops after two fixes, or when the only thing missing is a member who
   isn't answering.

When everyone's on board, the decision is saved to the room's memory as
`context/decision/<task>`, here `context/decision/gift-payments`, and the
thread ends with the option it went with. Later work on the task sees it, so
nobody has to argue it again. A missing rating is never guessed: it counts
against the option it's missing from.

Concord is for real alternatives. If the members don't yet agree on what the
task is, their options won't be about the same thing; run accord first. And
for two agents that each hold a position to bargain over, rather than options
to rate, the aligner negotiates instead.
