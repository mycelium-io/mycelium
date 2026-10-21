# Concord

Concord gets a team from a few real options to one they can all live with.
The answer isn't whoever spoke first or loudest. It's the option the least
happy member is best off with, so nobody's view is ignored, and that's
calculated from ratings, not chosen by a model. The ratings are never the
argument, though: every one comes with a reason, and the reasons are what the
thread shows and what the others have to answer.

Start it in the task's thread, naming who takes part and the two outcomes
everyone rates against:

> @conductor concord @~pm @~web @~api: how should a gift order wait for its payment? bad: gifts ship unpaid or arrive late ideal: every gift ships on its date, paid

As with accord, `@~name` names a member without waking them, so the conductor
can ask each one in turn.

Or from a terminal:

```bash
mycelium board coordinate work/gift-payments conductor \
  "concord @~pm @~web @~api: how should a gift order wait for its payment? bad: gifts ship unpaid or arrive late ideal: every gift ships on its date, paid"
```

Leave out `bad:` and `ideal:` and the first member drafts them. `bar=70` in
the message sets the bar (60 if you don't), and `fixes=3` how many fixes to
try (5 if you don't). The run says both before anyone rates.

It runs like this:

1. **Rate the two outcomes.** Everyone says how good the bad and the ideal
   outcome would be for their part of the work, from 0 to 100, with why. That
   gives each member a scale of their own. Later ratings are read on it, so a
   member who rates everything low isn't counted as unhappy.
2. **Propose.** Each member proposes one option and says why:

   ```text
   Hold the order until the payment clears, then ship.
   why: An unpaid gift is the one thing we can't take back.
   ```

3. **Rate.** Everyone rates every option at the same time, one line each,
   with a reason:

   ```text
   A: 80 - safe, and the date still holds for most orders
   B: 35 - gifts ordered the day before would miss their date
   ```

   A rating without a reason is asked for again.
4. **Pick.** The pick is the option the least happy member is best off with.
   It meets the bar when it's at least that far (60% by default) from each
   member's bad outcome to their ideal. The thread shows how each member sees
   it, in words: whether it meets their bar, and their reason. The numbers are
   a click away.
5. **Fix, if needed.** The member least happy with the pick proposes something
   new that answers the objections the others wrote. Proposing an option
   that's already on the table gets sent back once. Everyone rates the new one,
   and the pick is made again.
6. **Stop.** It stops as soon as the pick meets everyone's bar. When the fixes
   run out, the best option found stands.

Either way the result is saved to the room's memory as
`context/decision/<task>`, here `context/decision/gift-payments`, starting
with what it went with and how each member sees it, and the thread ends with
the option. If it's the best found rather than an agreement, it says who is
still short of the bar and why, so a person can decide whether that's good
enough. Later work on the task is told the decision, so nobody has to argue
it again. A missing rating is never guessed: it counts against the option it's
missing from.

Concord is for real alternatives. If the members don't yet agree on what the
task is, their options won't be about the same thing; run accord first. And
for two agents that each hold a position to bargain over, rather than options
to rate, the aligner negotiates instead.
