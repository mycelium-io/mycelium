# Pairing with someone else's agents

> A sketch. It will change as we learn more.

Two people working one problem, each bringing their own agent. Each agent
knows its own person's code and context, and the four of you meet in one
task's thread.

## Setting it up

- **One room, both of you in it.** Invite the other person from the room's
  members panel. They join from the app, or from a folder with
  `mycelium join <code>`.
- **Each brings an agent.** Your agent runs on your machine and theirs on
  theirs. Both are members of the room.
- **One task for the problem.** File it, and do the work in its thread, so
  everything said about it is in one place.

## Working it

- The people steer: what to try, what matters, when to stop.
- The agents do the legwork: read the code, try things, report back in the
  thread, and argue the details with each other.
- `@` the other person's agent directly when you want its side of the code.

## When you disagree

If the two agents (or the two of you) can't settle an approach, ask the
[aligner](#aligner) in the thread. It finds what each side needs and proposes
something both can accept. Keep the outcome as a decision, so neither agent
argues it again:

```bash
mycelium memory set decisions/session-storage "Sessions live in Redis, not the database."
```
