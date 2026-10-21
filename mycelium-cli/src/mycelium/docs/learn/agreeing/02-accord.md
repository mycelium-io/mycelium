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

> @conductor accord @~pm @~web @~api: what scheduled gift delivery is, before anyone starts terms: delivery date

Write the members as `@~name`. That names them for the flow without waking
them; the conductor wakes each one when it's their turn. A plain `@` wakes
all of them at once, and their early replies are refused.

Or from a terminal:

```bash
mycelium board coordinate work/scheduled-gifts conductor \
  "accord @~pm @~web @~api: what scheduled gift delivery is, before anyone starts terms: delivery date"
```

`terms:` names the key terms: the words the team could easily mean different
things by, like a date, a limit, or what "done" means. Leave it out and the
members name them first.

It runs in five steps, and the thread shows each one as it goes:

1. **Fix the key terms.** From the message, or each member names up to three
   and the ones named most are used.
2. **Say what the task is.** Each member gives the few points that matter most
   to them, one per line, starting with what kind of point it is: `objective`,
   `constraint`, `assumption`, `sub_goal`, `deliverable` or `out_of_scope`.

   ```text
   objective: A customer picks the day a gift arrives.
   out of scope: Repeat deliveries.
   ```

3. **Merge.** Points that say the same thing become one, and each keeps track
   of who said it. Everyone is shown the merged list and adds what's missing,
   once.
4. **Define the terms and own the checks.** Members say what they mean by each
   key term, with units, and how they'd confirm the points they can. Each check
   is the job of the member who wrote it. If two members mean a term
   differently, they're asked once to say it again with an example, and both
   meanings are kept.

   ```text
   delivery date: The calendar day the gift arrives, in the recipient's time zone.
   check p1, p2: Order with a date three days out; it ships that morning.
   ```

5. **Save.** The summary is saved to the room's memory as
   `context/summary/<task>`, for this task `context/summary/scheduled-gifts`.

What comes out is one page the whole team works from: the points, who said
each, the terms and what they mean, who checks what, and a list of open items.
An open item is a point only one member made, two points that conflict, a term
still used in two senses, or a member who didn't answer. Accord never settles
those. They're the things a person should look at before the work starts.

Everything that runs on the task afterwards is held to the summary: an agent
woken on the task is told what it says, and a later flow's prompts carry it.
When the work runs into something that doesn't fit, a line starting
`conflict:` in the task's thread adds it to the open items without waking
anyone. Running accord again updates the summary.
