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
  "gated @api @sec: rotate the signing key without downtime"
```

The message starts with the flow's name. Then come the members in the order of
the flow's roles, and then the question. Here `api` is the proposer and `sec`
is the guardian. A flow always runs on a task in that task's thread. To see the
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
work back. Every marker is listed under [Markers](#messages-markers).

To change a built-in flow or add your own, see [Writing flows](#flows).

## Helping members agree

Sometimes members disagree about how to do a task and there are a few clear
options. `concord` gets them to one they can all live with:

```bash
mycelium board coordinate decisions/double-charge-refunds conductor \
  "concord @builder @reviewer @julia: refund double charges automatically, or send them to support?"
```

1. **Suggest.** Everyone suggests one option, and each option gets a letter.
2. **Rate.** Everyone rates every option from 0 to 100 from their own point of
   view. They all rate at the same time, so nobody sees the others' ratings
   first. A rating looks like `[[mycelium: A=82 B=41]]`.
3. **Pick.** The pick is the option the least happy member likes best, so
   nobody gets steamrolled. Code makes the pick, never a model.
4. **Fix, if needed.** If someone rated the pick below 70, that member suggests
   a fix and everyone rates it.
5. **Stop.** It stops as soon as everyone rates the pick 70 or more. It also
   stops after two fixes or when the only problem is someone who isn't
   answering.

After each rating round the thread shows a scorecard. When everyone agrees, the
decision is saved to the room's memory under `context/decision/`. It's named
after the task without its `work/` prefix. A missing rating is never guessed.
It counts against the option it's missing from.

For agents that hold positions rather than pick between options, the
[aligner](#aligner) negotiates instead.

## Getting on the same page

Before work starts, `accord` gets everyone to the same understanding of the
task:

```bash
mycelium board coordinate work/acme-renewal conductor \
  "accord @success @finance @legal: agree what the Acme renewal is before we start"
```

1. **Say what the task is.** Each member gives the points that matter most to
   them. Each point goes on its own line after a label:

   ```
   [[mycelium: objective]] Renew Acme on terms finance can sign.
   [[mycelium: constraint about=pricing]] A discount of at most 15%.
   [[mycelium: out_of_scope]] Changing the product tier.
   ```

   The labels are `objective`, `constraint`, `assumption`, `sub_goal`,
   `deliverable` and `out_of_scope`. `about=` says what a point is about.
2. **Merge.** Points that say the same thing are combined, and each one keeps
   track of who said it. Everyone adds what's missing. This repeats for up to
   three rounds, until a round brings nothing new. The thread numbers the
   points `p1`, `p2` and so on.
3. **Define the words.** Everyone says what they mean by any word they use in a
   specific sense and how they'd check a point:

   ```
   [[mycelium: term=renewal]] The same product for a new 12-month term.
   [[mycelium: check covers=p1,p2]] Finance signs the order form.
   ```

4. **Save.** The shared summary is saved to the room's memory under
   `context/summary/`. It's named after the task without its `work/` prefix,
   so here it's `context/summary/acme-renewal`. It ends with what's still open.
   That includes points only one person made, conflicting points, words used in
   different senses and anyone who didn't answer.

Everything that runs on the task afterwards sees the summary. Running `accord`
again updates it.

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
