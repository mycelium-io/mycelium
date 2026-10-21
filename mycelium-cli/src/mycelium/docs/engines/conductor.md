# Conductor

The conductor runs a **flow** inside a task. A flow is a set sequence of
turns. For example, one member proposes something and another approves or
rejects it. A rejection sends it back for another try. The conductor makes sure
each member speaks when it's their turn and only then.

It doesn't use a model. The members do all the thinking. The conductor only
decides who goes next, based on the flow and on how the last member answered.

In the app, the **Review** and **Split** choices under **+** in a task's thread
run conductor flows. From the command line:

```bash
mycelium engine create conductor --kind conductor --room sprint-plan

mycelium board coordinate work/rotate-signing-key conductor \
  "gated @~api @~sec: rotate the signing key without downtime"
```

The message starts with the flow's name. Then come the members in the order of
the flow's roles, and then the question. Here `api` is the proposer and `sec`
is the guardian. Write the members as `@~name`: that names them for the flow
without waking them, and the conductor wakes each one when it's their turn. A
plain `@` wakes all of them at once, and their early replies are refused. A flow always runs on a task in that task's thread. To see the
flows a room can run, use `mycelium engine invoke conductor "list"`.

## Built-in flows

| Flow | Roles | What happens |
|---|---|---|
| `gated` | proposer, guardian | The proposer says what it plans to do and the guardian approves or rejects it. A rejection goes back to the proposer with the reason. This repeats until the guardian approves or the step limit is reached. |
| `review` | author, reviewer | The author does the work. The reviewer checks it and either approves it or sends findings back, until it's approved. The app's **Review** runs this. |
| `fan-out` | lead | Every other member named gets the question at the same time. The lead gets all the answers and combines them into one. |
| `round-robin` | none | The members named speak one after another for two rounds. Each one sees what the others said. |
| `swarm` | lead | Each member says which part it would take. Then the lead splits the task into one child task per member. The app's **Split** and [`mycelium swarm`](#swarm) run this. |
| `concord` | none | Helps members agree on one of a few options. See below. |
| `accord` | none | Gets everyone to the same understanding of the task before work starts. See below. |

`concord` and `accord` are simplified versions of two protocols from the
[Internet of Cognition](https://outshift.cisco.com/blog/ai-ml/mind-the-semantic-gap-osi-model)
L9 work.

Members approve or reject by ending their reply with
`[[mycelium: stance=accept]]` or `[[mycelium: stance=reject]]`. A reply with no
stance takes the step's default path. In `gated` and `review`, that sends the
work back. A flow you write can make a step require a stance. If a member
replies without one, the conductor asks them once more. A second reply without
a stance counts as a reject. Every marker is listed under
[Markers](#messages-markers).

To change a built-in flow or add your own, see [Writing flows](#flows).

## Helping members agree

Sometimes members disagree about how to do a task and there are a few clear
options. `concord` gets them to one they can all live with:

```bash
mycelium board coordinate decisions/double-charge-refunds conductor \
  "concord @~builder @~reviewer @~julia: refund double charges automatically, or send them to support? bad: customers wait days and we refund real orders ideal: true duplicates go back the same day and nothing else does"
```

`bad:` and `ideal:` go after the question. They're two outcomes everyone
rates, so a member's ratings can be read on their own scale. Leave them out
and the first member drafts them. `bar=70` sets the bar (60 if you don't) and
`fixes=3` how many fixes to try (5 if you don't).

1. **Rate the two outcomes.** Everyone says how good the bad and the ideal
   outcome would be for their part of the work, from 0 to 100, with why. Every
   later rating is placed between those two, so a member who rates everything
   low isn't read as unhappy.
2. **Propose.** Everyone proposes one option and says why, on a line starting
   `why:`. Each option gets a letter.
3. **Rate.** Everyone rates every option at the same time, one line each, with
   a reason: `B: 40 - the Friday window breaks certification`. A rating
   without a reason is asked for again.
4. **Pick.** The pick is the option the least happy member is best off with.
   It meets the bar when it's at least that far (60% by default) from each
   member's bad outcome to their ideal. The pick is calculated from the
   ratings. No model makes it.
5. **Fix, if needed.** The member least happy with the pick proposes something
   new that answers the objections the others wrote. An option already on the
   table is sent back once. Everyone rates the new one.
6. **Stop.** It stops as soon as the pick meets everyone's bar. When the fixes
   run out, the best option found stands, and the thread says who is still
   short and why.

After each pick the thread shows how each member sees it, in words: whether
it meets their bar and the reason they gave. The numbers are a click away.
The result is saved to the room's memory under `context/decision/`, named after
the task without its `work/` prefix, with the reasons first. A missing rating
is never guessed. It counts against the option it's missing from.

For agents that hold positions rather than pick between options, the
[aligner](#aligner) negotiates instead.

## Getting on the same page

Before work starts, `accord` gets everyone to the same understanding of the
task:

```bash
mycelium board coordinate work/acme-renewal conductor \
  "accord @~success @~finance @~legal: agree what the Acme renewal is before we start terms: renewal, discount"
```

1. **Fix the key terms.** These are the words the team could easily mean
   different things by. Name them after `terms:` in the message. Otherwise each
   member names up to three, and the ones named most are used.
2. **Say what the task is.** Each member gives the points that matter most to
   them, one per line, starting with what kind of point it is:

   ```
   objective: Renew Acme on terms finance can sign.
   constraint (pricing): A discount of at most 15%.
   out of scope: Changing the product tier.
   ```

   The kinds are `objective`, `constraint`, `assumption`, `sub_goal`,
   `deliverable` and `out_of_scope`. A word in brackets says what a point is
   about.
3. **Merge.** Points that say the same thing are combined, and each one keeps
   track of who said it. Everyone is shown the list and adds what's missing,
   once. The thread numbers the points `p1`, `p2` and so on.
4. **Define the terms and own the checks.** Everyone says what they mean by
   each key term, with units where it has them, and how they'd confirm the
   points they can:

   ```
   renewal: The same product for a new 12-month term.
   check p1, p2: Finance signs the order form.
   ```

   Each check belongs to the member who wrote it. If two members mean a term
   differently, they're asked once to say it again with an example. Nobody
   has to give way: both meanings are kept.
5. **Save.** The shared summary is saved to the room's memory under
   `context/summary/`. It's named after the task without its `work/` prefix,
   so here it's `context/summary/acme-renewal`. It ends with what's still open.
   That includes points only one person made, conflicting points, terms used in
   different senses and anyone who didn't answer.

Everything that runs on the task afterwards is held to the summary: an agent
woken on the task is told what it says, and a later flow's prompts carry it.
When work runs into something in it that doesn't fit, a line starting
`conflict:` in the task's thread adds it to the open items, without waking
anyone. Running `accord` again updates the summary.

## Who can take part

Any member can fill a role, including your own agent, a [persona](#persona), a
[worker](#worker) or you. To take a role yourself, put your own handle in the
message. When it's your turn, reply in the task's thread in the app. From a
terminal, you take your turn the way an agent does:

```bash
mycelium await --handle julia
mycelium respond --handle julia "Not without a canary. [[mycelium: stance=reject]]"
```

## Taking turns

While a flow runs, only the member whose turn it is can post in the task's
thread. Anyone else gets an error saying whose turn it is. The room's chat and
other tasks' threads stay open to everyone.

In the thread, each question from the conductor shows as one line such as
`review → sec · turn 2 of 6`. Click it to see the full prompt. The app also
draws the flow at the top of the thread. It highlights the current step and
shows the path taken so far.

![A gated flow at the top of a task's thread, waiting on the step that proposes](app-thread-flow.png)

## How a flow ends

A flow ends as `resolved` when it reaches the end. It ends as `rejected` when
it gives up or hits its step limit. A `concord` run that everyone agrees on
ends as `converged`. These describe the flow, not the task. Finishing a flow
leaves the task open. Resolve the task as usual with `mycelium board resolve`.

Each run is saved as an [episode](#episodes) under `log/episodes/`. The record
holds the flow, who played each role and every step taken.
