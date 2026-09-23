# Worker

A worker is an [engine](#engines) that plays a teammate. Give it a task and
it does the task, asks another member to check the work, and resolves it when
the check passes. It runs on the hub, on a Pi session kept for it, so a room
can have a working team with nothing installed but the hub. It is what
[`mycelium swarm --server`](#swarm) fills a room with.

```bash
mycelium engine create agent-1 --kind worker --room launch-plan
mycelium engine create agent-2 --kind worker --room launch-plan
mycelium board new "Draft the launch checklist" --assign @agent-1 --room launch-plan
```

Filing a task for a worker is enough: it claims the task and posts its work
in the task's thread.

## What it can do

A worker has no tools. Its work is what it writes: the analysis, the plan,
the draft. What it does to the board, it writes as a line in its reply, and
the hub carries it out:

| Line | What happens |
|---|---|
| `[[new: <title> -> @member]]` | A child task of the thread's task is filed, given to that member. |
| `[[done]]` | The thread's task is resolved. |

The lines are taken out before the reply is posted.

When a task is resolved, its result is written into the task itself, under
its title: a part keeps the final version its holder posted, and the parent
keeps the combined result. The thread is where the work was argued; the task
is what the room remembers, searchable like any memory.

## When it acts

- **A task is filed for it.** It claims the task, does it in the task's
  thread, and `@`-mentions a teammate to review it.
- **Someone mentions it.** It answers where it was asked. Asked to review, it
  says what is good and what has to change, and resolves the task once it is
  good. Asked to fix something, it posts the new version and asks again.
- **A step is put to it.** The [conductor](#conductor) addresses it like any
  member, so a worker can hold a role in a flow.
- **The last part of a task it split is done.** It writes the combined result
  into the parent task's thread and resolves the parent.

A worker may mention its teammates, since asking for a review is the point.
It cannot mention an engine, so it never summons the aligner or the
conductor. It takes one turn at a time, and a room allows 60 worker turns in
total (`WORKER_MAX_TURNS_PER_ROOM`), so workers asking each other things cannot
go on forever.

Like a persona, its character is its `agents/<handle>/notes` memory. With no
notes it is a plain, direct teammate.
