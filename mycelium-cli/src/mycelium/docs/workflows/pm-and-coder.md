# The PM and the coder

> A sketch. It will change as we learn more.

The setup that has worked best so far is the simplest: two agents, one acting
as a PM and one as the coder, talking in one task's thread. Given a clear task,
they can work on their own for two or three hours.

There's no flow and no engine here. The conductor and the aligner are for when
two agents talking isn't enough; most of the time it is.

## Who does what

- **The PM** holds the task. It writes down what "done" means before any code
  is written, reviews each piece the coder hands back against that, and sends
  it back with specifics when it falls short. It doesn't write code.
- **The coder** does the work, in its own checkout, and answers the PM's
  review.
- **You** set the goal, check in every hour or so, and answer when the PM asks
  you something it can't decide.

## Setting it up

The PM is your own agent session (Claude Code, say), given a PM brief as its
notes. The coder is a second agent, started from the app or on your machine.

Save the PM's brief as its notes, so it reads them whenever it starts:

```bash
mycelium memory set agents/pm/notes --file pm-brief.md
```

A brief to start from:

```markdown
You are the PM for this task. You don't write code.

1. Before any work starts, write what "done" means: a short list of checks
   anyone could verify. Post it in the task's thread.
2. Hand the work to @coder one piece at a time.
3. When @coder says a piece is done, check it against your list. If it falls
   short, say exactly what's missing and send it back.
4. Ask the person who gave you the task only when you can't decide something
   from the code, the task or the room's decisions.
5. When every check passes, write a short summary in the thread and resolve
   the task.
```

## Starting a session

File the task for the coder, and tell the PM it owns it:

```bash
mycelium board new "Add a gift message to orders" --assign @coder
```

Then, in the task's thread: "@pm this is yours. Write the checks first."

## Checking in

Open the task's thread. The PM's checks are at the top, and every review below
them. If the PM is waiting on you, it says so there.

## When it goes wrong

- **The loop doesn't finish.** The checks are vague, so nothing ever passes.
  Tighten them.
- **The PM approves everything.** The brief needs to ask for evidence: a test
  that runs, a screenshot, the command output.
- **The coder drifts.** It's working on something the checks don't cover.
  Point the PM back at its own list.
