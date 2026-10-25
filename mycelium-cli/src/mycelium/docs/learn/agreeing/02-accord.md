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

`terms:` names the words the team could mean differently. Leave it out and the
members name them first.

It runs like this, and the thread shows each step as it goes:

1. **Say what the task is.** Each member gives a few points, one per line,
   starting with its kind: `objective`, `constraint`, `assumption`,
   `sub_goal`, `deliverable` or `out_of_scope`.

   ```text
   objective: A customer picks the day a gift arrives.
   out of scope: Repeat deliveries.
   ```

2. **Merge.** Points that say the same thing become one, keeping who said
   them, and everyone adds what's missing, once. When two points say the same
   thing in different words, a member says so and they become one:

   ```text
   same: p6 = p1
   ```
3. **Terms and checks.** Members say what each key term means, with units, and
   how they'd confirm points; each check is its writer's job. A term meant two
   ways is restated once, with an example, and both meanings are kept.

   ```text
   delivery date: The calendar day the gift arrives, in the recipient's time zone.
   check p1, p2: Order with a date three days out; it ships that morning.
   ```

4. **Save.** The summary is saved as `context/summary/<task>`, here
   `context/summary/scheduled-gifts`.

The summary lists open items: a point only one member made, two points that
conflict, a term used in two senses, a member who didn't answer. Accord never
settles those; a person should look at them before the work starts. Later work
in the task is told what the summary says, and a line starting `conflict:` in
the task's thread adds to its open items.
