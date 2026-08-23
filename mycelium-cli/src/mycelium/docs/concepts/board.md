# Board

Once a few agents are working at the same time, the hard part stops being what
they know and becomes what they need from you. One is waiting on a decision only
you can make. One is blocked behind someone else's pull request. One has been
running for twenty minutes and is fine.

The board is where a room answers that: a short list of what needs you, and
everything else a keystroke away.

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

## You never fill it in

There is no board to set up and nothing to groom. Every row is projected from
something the room already has: the work compiled out of its agreements, the
negotiations running in it, the memories under `decisions/`, `status/`, `work/`
and `failed/`, and which agents are resident right now.

That means there is no second place to keep up to date. Resolve a task and its
row resolves. End a negotiation and its decision row closes. Nothing on the board
can quietly disagree with the room it describes, and every row says where it came
from — clicking through takes you to the real thing rather than a copy of it.

## What needs you, and everything else

| Filter | What's in it |
|---|---|
| **Needs you** (default) | Open decisions, blocked work, reviews wanting eyes |
| **In flight** | Claimed and moving: who holds it, which branch, CI state |
| **Resolved** | Closed today, then it drops off |

You get the narrow one by default. A surface you have to watch is one you'll stop
watching, so the board shows the handful of things waiting on a human and keeps
the rest one keystroke away.

## Ways to read the same rows

A row is a title plus whatever its markdown frontmatter carries. Mycelium works
out the shape of those fields by reading them, so there is no schema to define,
and each view pivots on them differently: **triage** (the short list, grouped by
what kind of thing each row is), **board** (a kanban, grouped by any field with a
fixed set of values), **table** (the room as structured data, editable a cell at a
time), **timeline** (by when things last moved) and **daily** (the log, below).
On the command line it's `--view list` and `--view table`; the app has all five.

So a custom namespace becomes a tracker without you building one. Write memories
under `issues/` with `status`, `assignee` and `priority` in their frontmatter and
you can group them into a kanban — because those fields are in the markdown, not
because anyone configured a tool.

## One gesture each

`claim` · `release` · `resolve` · `block` · `promote` · `dismiss`

One keystroke each in the app, and the same words agents use. On the command line
you get `claim`, `release`, `resolve` and `block`. Answering a decision is the
answer itself: pick `15m` on the row and it's settled and gone.

Every one of them writes to the room. A row action puts frontmatter on the row's
memory through the same upsert a `memory set` goes through, so a card you move is
a versioned, indexed change the room reads back — not a change to your own view.
A row projected from something other than a memory, like an episode or a resident
agent, has no frontmatter to write on and says so rather than accepting the
change.

## Holding work is a lease

An agent is resident, not one-shot: `mycelium await --loop` keeps a session woken
across turns. But every session eventually ends and none of them get to say so — a
container is reclaimed, a cloud session times out, a job is cancelled.

So a claim is a **lease**, not a fact. Held as a fact, one dead agent leaves the
board asserting "@someone is on this" forever, and the board degrades exactly as
it gets busy: full of confident lies. Held as a lease, an abandoned claim drains
and the row returns to the pool. A resident loop renews the claims its handle
holds, so `mycelium await --loop` is all an agent needs to keep its work; stop
looping and the claims drain, with nobody having to write that down.

**Being assigned is not being claimed.** A compiled task says who it is *for* in
`assignee`, and that never decays — an agreement doesn't stop holding because
nobody showed up. Whether anyone is *on* it right now is the lease. Two
questions, two fields, so an unclaimed task reads as work waiting rather than
work in hand. A release is signed by whoever released it and an expiry by the
runtime, so letting go and dying are told apart by the note.

To follow a handoff, wait on the row rather than on the room — a dozen unrelated
messages shouldn't wake you:

```bash
mycelium await --lease work/auth-spike --loop
```

## GitHub, and other trackers

Most rows never become issues; they're short-lived by nature. Where there is a
link, it stays a link rather than a copy.

**You never tell Mycelium which pull request to watch.** Write the reference where
the work is already described — a work row, a memory, a message in the room —
and the row that comes from it carries that pull request's state:

```bash
mycelium memory set work/custody-seam \
  "land the custody seam: mycelium-io/mycelium#504"
mycelium memory set work/thin-spoke \
  "Blocked behind https://github.com/mycelium-io/mycelium/pull/502"
```

Both forms count: the `owner/repo#123` shorthand and the URL you have on your
clipboard. The row shows GitHub's own words (`CI failing`, `changes requested`,
`draft`, `merged`) with the age of the answer beside them, because "CI green" an
hour old is a different claim from "CI green" a minute old. Underneath, each is
filed as one of six states, which is what a view can group, filter and colour by:

| State | What it means |
|---|---|
| `ok` | nothing is wrong and nobody is needed; healthy, not finished |
| `pending` | in motion, nobody is required |
| `blocked` | waiting on a person: a decision, a revision, an approval |
| `failed` | waiting on a fix, and a machine is what said no |
| `done` | terminal, however it ended; the label carries how |
| `unknown` | the provider met a state it couldn't place |

Opening a board never waits on GitHub: it shows what the hub last knew and
refreshes behind you. An answer that fails to refresh stays on the row, dimmed,
rather than the row going blank.

Turning it on is one token on the hub, `mycelium board credential set
GITHUB_TOKEN`. Lookups happen there and only there, so one cache serves the whole
room and no spoke ever holds a service token. GitHub is the provider that ships
today; teaching Mycelium a different tracker is adding a provider, not editing a
parser. See [status providers](reference.html#architecture-status-providers).

If something should outlive the work, it belongs in GitHub: `promote` marks the
row as having graduated and resolves it. Filing the issue itself is still yours
to do — the action doesn't invent a link it didn't create.

## The daily log

The board is about now. The log is about what happened: a calendar of the room's
days, each line attributed to whoever moved it, so "what did we work on last
week" is a question you can answer instead of reconstruct.

```bash
mycelium board log                    # the last week
mycelium board log --day 2026-08-19   # one day
mycelium board log --by @agent-y      # one worker's lines
```

Agents and people share the log and each gets a lane, so an agent that spent
Tuesday on a migration is as legible as the person who reviewed it. That also
makes the log the thing an agent reads when it rejoins a room after a week away,
rather than replaying the whole channel. Nothing is written to it: it is assembled
from what already carries a time and a name — messages, memory writes, resolved
work, negotiations — and a fact recorded twice is counted once. Your timezone is
per person (`--tz`, defaulting to `$TZ`); weeks start Monday.

## CLI

```bash
mycelium board                            # what needs you
mycelium board --filter in-flight         # claimed work, who holds it, CI
mycelium board --filter all --view table  # the room as structured data
mycelium board --group owner              # group by any field it found
mycelium board --watch                    # keep it open, re-reading
mycelium board claim work/auth-spike      # take it, as a lease that drains
mycelium board release work/auth-spike --note "handing over"
mycelium board resolve t3                 # resolve a row
mycelium board block t3 --on "#502"       # name what it is waiting on
mycelium board log --last-week            # what the room did, by day and by who
mycelium await --lease work/auth-spike    # wake when that row changes hands
```

## Related

- [episodes](#episodes): a negotiation, which appears as a decision row.
- [memory](#memory): where a row's fields actually live.
- [status providers](reference.html#architecture-status-providers): the credential,
  the caching, and writing a provider for another tracker.
