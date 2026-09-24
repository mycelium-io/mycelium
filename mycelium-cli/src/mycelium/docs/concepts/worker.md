# Worker

A worker is an [engine](#engines) that plays a teammate. Give it a task and
it does the task, asks another member to check the work, and resolves it when
the check passes. It runs on the hub, as a coding agent with its own checkout,
so a room can have a working team with nothing installed but the hub. It is
what [`mycelium swarm --server`](#swarm) fills a room with.

```bash
mycelium engine create agent-1 --kind worker --room launch-plan
mycelium engine create agent-2 --kind worker --room launch-plan
mycelium board new "Draft the launch checklist" --assign @agent-1 --room launch-plan
```

Filing a task for a worker is enough: it claims the task and posts its work
in the task's thread.

## What it can do

A worker is a coding agent. It can read, edit and write files and run
commands, in its own checkout on the hub:

- The room has one git repository on the hub. It is a clone of the repository
  the swarm was started on, or a new, empty one if it was given none.
- Each worker works in its own worktree of it, on its own branch
  (`swarm/agent-1`, `swarm/agent-2`, …), so two workers never edit the same
  files at once.
- It commits its work to its branch and says in the thread what it did. A
  reviewer reads the author's branch and runs what checks it. The lead merges
  every part's branch when the last one is done.

The workspace is under the hub's data directory, at
`~/.mycelium/workspaces/<room>/` on a hub started with `mycelium up`. Every
branch is in its `repo/`, so from your machine you can read, check out or
push them there (`git -C ~/.mycelium/workspaces/<room>/repo log swarm/agent-1`).
The worktrees beside it record the hub container's paths, so work with the
branches in `repo/` rather than inside a worktree.

What it does to the board, it writes as a line in its reply, and the hub
carries it out:

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

- **A task is filed for it.** It claims the task, does it in its checkout,
  says what it did in the task's thread, and asks its reviewer to look.
- **Someone mentions it.** It answers where it was asked. Asked to review, it
  says what is good and what has to change, and resolves the task once it is
  good. Asked to fix something, it posts the new version and asks again.
- **A step is put to it.** The [conductor](#conductor) addresses it like any
  member, so a worker can hold a role in a flow.
- **The last part of a task it split is done.** It merges the parts'
  branches, says what the team made in the parent task's thread, and resolves
  the parent.

## Review

Every part is reviewed by another worker before it is done. The reviewer is
the next worker in the room, round a ring (agent-1's work goes to agent-2,
agent-2's to agent-3, the last back to agent-1), so review is spread across the
team rather than falling to the lead. The author is told who its reviewer is.

A worker is asked to name who it wants to act, but the hub does not rely on
it: a post on a part that neither resolves it nor mentions anyone is routed.
The author's post (its work, or a revision) goes to its reviewer, and a review
asking for changes goes back to the author. So a part cannot stall because a
model forgot to mention someone. The third time a part comes back for review
is the last: the reviewer resolves it if it is workable, naming anything left
for later.

A part is done when its reviewer says so. Its author cannot resolve it before
anyone else has looked, and a second approval of a part already done changes
nothing.

## Limits

A worker may mention its teammates, since asking for a review is the point.
It cannot mention an engine, so it never summons the aligner or the
conductor. It takes one turn at a time, and a room allows 60 worker turns in
total (`WORKER_MAX_TURNS_PER_ROOM`), so workers asking each other things cannot
go on forever.

A turn runs for up to ten minutes (`WORKER_PI_TIMEOUT_S`). A worker is
started for each turn and remembers the ones before it; nothing keeps running
between turns, so it suits work done in steps of minutes, not a job that runs
for an hour.

Its commands run inside the hub's backend container, as the backend's user,
with what that container can reach: the room files and the model key
included. On a hub you run for yourself, that is like running an agent on your
own machine. On a hub you share, decide whether you trust everyone who can
start a swarm with that, or turn tools off with `WORKER_TOOLS=false`, and
workers go back to only writing. The OpenShell sandbox
(`ALIGNER_PI_OPENSHELL`) cannot see the checkout yet, so with it on, workers
only write as well.

Like a persona, its character is its `agents/<handle>/notes` memory. With no
notes it is a plain, direct teammate.
