# Accord

Accord gets every member to the same understanding of a task before work
starts. Nobody leads it and nobody votes. Each member says what the task is
from where they sit, the points are merged in code, and whatever doesn't line
up is flagged for a person to settle.

The room needs the conductor once. In the room's chat:

```text
/engine conductor
```

Then start accord in the task's thread, naming who takes part:

> @conductor accord @~pm @~web @~api: what scheduled gift delivery is, before anyone starts

Write the members as `@~name`. That names them for the flow without waking
them; the conductor wakes each one when it's their turn. A plain `@` wakes
all of them at once, and their early replies are refused.

Or from a terminal:

```bash
mycelium board coordinate work/scheduled-gifts conductor \
  "accord @pm @web @api: what scheduled gift delivery is, before anyone starts"
```

It runs in four steps, and the thread shows each one as it goes:

1. **Say what the task is.** Each member gives the few points that matter most
   to them, each on its own line after a label: `objective`, `constraint`,
   `assumption`, `sub_goal`, `deliverable` or `out_of_scope`.

   ```text
   [[mycelium: objective]] A customer picks the day a gift arrives.
   [[mycelium: out_of_scope]] Repeat deliveries.
   ```

2. **Merge.** Points that say the same thing become one, and each keeps track
   of who said it. Everyone is shown the merged list and adds what's missing,
   for up to three rounds, until a round adds nothing.
3. **Define the words.** Members say what they mean by any word they're using
   in a specific sense, and how they'd check a point is done. If two members
   use one word in different senses, they're asked to say it again, once.

   ```text
   [[mycelium: term=schedule]] Pick one delivery date at checkout.
   [[mycelium: check covers=p1,p2]] Order with a date three days out; it ships that morning.
   ```

4. **Save.** The summary is saved to the room's memory as
   `context/summary/<task>`, for this task `context/summary/scheduled-gifts`.

What comes out is one page the whole team works from: the points, who said
each, the words and what they mean, how done will be checked, and a list of
open items. An open item is a point only one member made, two points that
conflict, a word still used in two senses, or a member who didn't answer.
Accord never settles those. They're the things a person should look at before
the work starts.

Everything that runs on the task afterwards sees the summary: the agents'
wakes name it, and a later flow can use it. Running accord again updates it.
