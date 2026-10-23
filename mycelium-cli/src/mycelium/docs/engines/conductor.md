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

`concord` and `accord` come from the Internet of Cognition team's ACCORD and
CONCORD protocols, from *Agreeing on Purpose, Deciding Under Conflict* (L9 and
MAS-Lab, Outshift by Cisco, October 2026). Their specification is at
[ioc-project.github.io/cognition-protocols](https://ioc-project.github.io/cognition-protocols/).
`concord` runs CONCORD as it's written there, with the conductor in the
initiator's place.

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
  "concord @~builder @~reviewer @~julia: refund double charges automatically, or send them to support?"
```

1. **Anchor.** Everyone rates no agreement and their own pick, so each
   member's later scores are read on their own scale.
2. **Seed.** Everyone proposes one candidate, with its rationale. Each is
   named by who proposed it, like `seed-reviewer`.
3. **Score.** Everyone scores every candidate from 0 to 100, with reasoning.
4. **Pick.** The pick is the candidate the least happy member is best off
   with, calculated from the scores, not by a model. It has to be 60% of the
   way from no agreement to each member's own pick (`bar=70` sets another).
5. **Repair, if needed.** The member who scores the pick lowest proposes a new
   candidate that answers the reasoning against it (`r1-reviewer`), and
   everyone scores it. After 10 repairs (`fixes=3` sets another), the best
   candidate found stands.

Each message is CONCORD's own element (`<concord-anchor>`, `<concord-score>`
and the rest), and members reply in the reply element the message shows. A
reply that doesn't match is asked for once more, saying what it lacked. A
score still missing after that is never guessed, and nothing is agreed while
one is. The run ends with `<concord-commit>`.

The thread shows how each member sees the pick and why, with the numbers a
click away. The result is saved under `context/decision/`, named after the
task without its `work/` prefix, saying who is short of the bar and why.

For agents that hold positions rather than pick between options, the
[aligner](#aligner) negotiates instead.

## Getting on the same page

Before work starts, `accord` gets everyone to the same understanding of the
task:

```bash
mycelium board coordinate work/acme-renewal conductor \
  "accord @~success @~finance @~legal: agree what the Acme renewal is before we start terms: renewal, discount"
```

1. **Key terms.** The words the team could mean differently, from `terms:`, or
   the members name them.
2. **Say what the task is.** Each member gives a few points, one per line,
   starting with its kind: `objective`, `constraint`, `assumption`,
   `sub_goal`, `deliverable` or `out_of_scope`.

   ```
   objective: Renew Acme on terms finance can sign.
   constraint (pricing): A discount of at most 15%.
   ```

3. **Merge.** Points that say the same thing are combined, keeping who said
   them, and everyone adds what's missing, once.
4. **Terms and checks.** Everyone says what each key term means, with units,
   and how they'd confirm points (`check p1, p2: Finance signs the order
   form.`). Each check belongs to its writer. A term meant two ways is
   restated once, and both meanings are kept.
5. **Save.** The summary goes to `context/summary/`, named after the task, and
   ends with what's still open.

Later work in the task is told what the summary says. A line starting
`conflict:` in the task's thread adds to its open items. Running `accord` again
updates it.

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
