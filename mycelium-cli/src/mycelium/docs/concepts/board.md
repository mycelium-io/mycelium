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
 ? d3f   JWT access-token TTL: 15m or 60m?              urgent
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
- **Daily**: the log, described below.
- **Docs**: the plan's prose, for when you want to read rather than triage.

So a custom namespace becomes a tracker without you building one. Write memories
under `issues/` with `status`, `assignee` and `priority` in their frontmatter and
you can group them into a kanban, because those fields are in the markdown and
not because anyone configured a tool.

## The daily log

The board is about now. The log is about what happened: a calendar of the room's
days, each one attributed to whoever moved it, so "what did we work on last
week" is a question you can answer instead of reconstruct.

```bash
mycelium board log                    # the last week
mycelium board log --last-week        # the week before
mycelium board log --day 2026-08-19   # one day
mycelium board log --by @agent-y      # one worker's lines
```

Agents and people share the log, and each gets a lane: an agent that spent
Tuesday on a migration is as legible as the person who reviewed it. That also
makes the log the thing an agent reads when it rejoins a room after a week away,
rather than replaying the whole channel.

Nothing is written to it. It is assembled from what already carries a time and a
name: messages, memory writes and revisions, finished plan tasks, and
negotiations. A fact recorded in two places is counted once.

### Whose day is it

A day only means something in some timezone. Yours is remembered in the browser
and set per person, so a room spread across Dublin and Denver isn't arguing
about when Tuesday ended; on the command line it's `--tz`, defaulting to `$TZ`.
Weeks start Monday.

### Filling it in

Each day shows how full it is against a modest target, with the current streak
and the longest one beside it. The heat calendar goes back ten weeks. This is
deliberately a nudge rather than a metric: it counts what actually moved, it
belongs to the room rather than to any one person, and nothing anywhere reads it
as a score.

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

### Live status: how it will work

> **Not built yet.** The rest of this section describes what linked pull requests
> *will* do. The backend has the resolver that answers for a reference — see
> [status providers](#architecture) — but nothing attaches its answers to a row,
> so no row shows a pull request's state today.

Mentioning the pull request will be the whole of it. Write the link where the
work is already described — a plan task, a memory, a message in the room — and
the row that comes from it will carry that pull request's state, with nothing to
attach and no per-row setting:

```bash
mycelium plan task add "land the custody seam — mycelium-io/mycelium#504"
mycelium memory set work/thin-spoke \
  "Blocked behind https://github.com/mycelium-io/mycelium/pull/502"
```

Both forms will count: the `owner/repo#123` shorthand, and the URL you have on
your clipboard when you're talking about a pull request. Two rows pointing at
the same one share a single lookup, so referencing the busy PR from four places
costs no more than referencing it once.

The row will show GitHub's own words — `CI failing`, `changes requested`,
`draft`, `merged` — because that's the phrasing you already recognise.
Underneath, each is filed as one of six states, which is what a surface can
sort, filter and colour by without knowing what a pull request is:

| State | What it means |
|---|---|
| `ok` | nothing is wrong and nobody is needed — healthy, not finished |
| `pending` | in motion, nobody is required |
| `blocked` | waiting on a person: a decision, a revision, an approval |
| `failed` | waiting on a fix, and a machine is what said no |
| `done` | terminal, however it ended — the label carries how |
| `unknown` | the provider met a state it couldn't place |

`ok` and `done` are the pair worth reading carefully, because a board's whole
job is keeping them apart: an approved pull request is `ok` right up until it
merges, and `done` the moment it does.

That answer lands on the row under its own `live` field, never the row's own
`status`. A row already uses `status` for its lifecycle (`open`, `claimed`,
`in_progress`, `blocked`, `resolved`), and both sets of words contain `blocked`
meaning different things: a person has blocked the row, versus the pull request
is waiting on a person. Keeping the provider's reading in a separate field is
what stops the two from being read as one.

GitHub maps onto the six more narrowly than you might guess. `ok` needs an
approval, so green checks with no review yet are `pending` / `awaiting review`.
Changes requested is `blocked` and red CI is `failed` — a person is the fix in
one case, a machine in the other. `unknown` is there for a provider that meets a
state it can't place; the GitHub one never emits it.

### How current it will be

Every status will carry the moment it was fetched, and the row will show its age
(`CI green · 4m`). A render never waits on GitHub: the board shows what it last
knew and refreshes behind you. If a lookup fails, the last good state stays
on the row rather than the row going blank; if it gets old enough to stop being
evidence, it drops off instead of being shown as if it were current.

Reading a room's board never costs a request per row, either: identical
references are answered once, and a tool is asked about many references in one
call rather than one at a time.

For the credential a provider needs, and for teaching Mycelium a tracker other
than GitHub, see [status providers](#architecture).

## CLI

```bash
mycelium board                            # what needs you
mycelium board --lens in-flight           # claimed work, who holds it, CI
mycelium board --lens all --view table    # the room as structured data
mycelium board --group owner              # group by any field it found
mycelium board --watch                    # keep it open, re-reading
mycelium board resolve t3                 # resolve a row
mycelium board log --last-week            # what the room did, by day and by who
```

## Related

- [plan](#plan): the room's prose and checklists, which the board reads from.
- [episodes](#episodes): a negotiation, which appears as a decision row.
- [memory](#memory): where a row's fields actually live.
