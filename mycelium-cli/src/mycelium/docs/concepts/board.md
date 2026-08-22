# Board

**Orchestrate effectively across your team's agents.**

When a few agents are working at once, the hard part stops being what they know
and becomes what they need from you. One is waiting on a decision only you can
make. One is blocked behind someone else's pull request. One has been running
for twenty minutes and is fine. The board is where a room answers that: a short
list of what needs you, and the rest a keystroke away.

```bash
mycelium board
```

```
atlas-migration   3 need you · 4 in flight · 6 resolved today

Decisions 1
 ? d3f   JWT access-token TTL — 15m or 60m?              urgent
         @agent-y · episode d3f   unowned   [15m] [60m]      6m

Blocked 1
 ⊘ a91   Enable thin-spoke join without a local replica
         linked to #502   @julia   waiting on #502           40m

Review 1
 ◉ 7c2   @agent-z opened PR #504, wants eyes on the custody seam
         @agent-z   feat/custody-seam   CI green   #504       12m
```

> **Experimental.** The board reads real room state today. The triage verbs act
> on your own view: `resolve` writes through to a plan task, and the rest change
> what you see without yet writing back to the room.

## Nothing to fill in

You never add anything to the board. It's assembled from what the room already
has: the tasks in its plan, the negotiations running in it, the memories under
`decisions/`, `status/`, `work/` and `failed/`, and which agents are actually
resident right now. Every row says where it came from, and clicking through
takes you to the real thing rather than a copy of it.

That means there's no second place to keep up to date. Mark a plan task done and
its row resolves. End a negotiation and its decision row closes. Nothing to
groom, and nothing that can quietly disagree with the room it describes.

## Three lenses

| Lens | What's in it |
|---|---|
| **Needs you** (default) | Open decisions, blocked work, reviews wanting eyes |
| **In flight** | Claimed and moving: who holds it, which branch, CI state |
| **Resolved** | Closed today, then it drops off |

You get the narrow one by default. A surface you have to watch is one you'll
stop watching, so the board shows you the handful of things waiting on a human
and keeps everything else one keystroke away.

## Five ways to read the same rows

A row is a title plus whatever its markdown frontmatter carries. Mycelium works
out the shape of those fields by reading them, so you never define a schema, and
each view pivots on them differently:

- **Cockpit**: the short list, grouped by what kind of thing each row is.
- **Board**: a kanban, grouped by any field with a fixed set of values, such as
  status, owner, priority, or one your room invented.
- **Table**: the room as structured data, editable a cell at a time. A dropdown
  offers the values that namespace already uses.
- **Timeline**: the same rows by when they last moved, so you can see what
  happened while you were away.
- **Docs**: the plan's prose, for when you want to read rather than triage.

So a custom namespace becomes a tracker without you building one. Write memories
under `issues/` with `status`, `assignee` and `priority` in their frontmatter and
you can group them into a kanban, because those fields are in the markdown and
not because anyone configured a tool.

## One gesture each

`claim` · `resolve` · `block` · `promote` · `dismiss`

One keystroke each in the interface, one word each on the command line, and the
same words agents use. Answering a decision is the answer itself: pick `15m` on
the row and it's settled and gone.

Captured concerns expire if nobody claims them, so the board stays a picture of
now instead of turning into a backlog. Anything that should outlive the work
gets `promote`d into a GitHub issue and leaves, with a link left behind.

## You can hear it

The board is meant to be ignored until it matters, so it makes a sound when it
changes: rising when something opens and wants you, falling when something
closes. Only a new row in your "needs you" lens interrupts. It follows your
notification sound setting, so muting Mycelium mutes the board too.

## GitHub, by reference

Most rows never become issues, since they're short-lived by nature. Where there
is a link, it's a link and not a copy:

- An issue being actively worked shows its live state on the row: who has it,
  which branch, whether CI is green.
- `promote` turns a row into an issue and drops it from the board.
- Most rows point at a branch or a pull request instead.

If it should outlive the work, it belongs in GitHub and Mycelium just points at
it. The board holds what's live right now.

## CLI

```bash
mycelium board                            # what needs you
mycelium board --lens in-flight           # claimed work, who holds it, CI
mycelium board --lens all --view table    # the room as structured data
mycelium board --group owner              # group by any field it found
mycelium board --watch                    # keep it open, re-reading
mycelium board resolve t3                 # resolve a row
```

Add `--demo` to see the shape of a busy board before your room is one; those
rows are always marked, and never mixed up with yours.

## Related

- [plan](#plan): the room's prose and checklists, which the board reads from.
- [episodes](#episodes): a negotiation, which appears as a decision row.
- [memory](#memory): where a row's fields actually live.
