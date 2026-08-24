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

## Nothing to fill in

You never add anything to the board. It's assembled from what the room already
has: the work compiled out of its agreements, the negotiations running in it, the memories under
`decisions/`, `status/`, `work/` and `failed/`, and which agents are actually
resident right now. Every row says where it came from, and clicking through
takes you to the real thing rather than a copy of it.

That means there's no second place to keep up to date. Resolve a task and
its row resolves. Nothing to groom, and nothing that can quietly disagree with
the room it describes.

## A row is a unit of work, and a unit of work is a thread

A `work/` row carries the episode URN of the thread its coordination happens in.
The row and the thread are one object, so the board draws one row per unit — the
negotiation that produced a task shows up *on* that task (`thread`,
`thread_state`, who was at the table, how many rounds) rather than beside it as a
second row.

The URN is the store's: it is minted when the unit is created, it survives every
later write, and no `memory set --meta` or board verb can set or move it. A unit
is therefore bound to one thread for its whole life — a second negotiation about
the same work opens its own episode, and the row stays pointed at the
conversation that produced it.

**The unit outlives what happens inside it.** A thread's state never writes the
row's own axes. Converging inside a unit does not resolve the unit, aborting a
negotiation does not take the row off whoever is holding it, and a unit can be
created, claimed, worked and resolved with no negotiation ever opened. That is
the whole point of the separation: a negotiation is one optional thing that can
happen inside a piece of work, not the reason the work exists.

A negotiation nobody compiled into work has no unit to fold into, so it keeps a
row of its own — a recorded negotiation is still something the room did.

## Putting one on the board

You do not have to wait for a negotiation to converge to have work. A unit can
be created board-first, and it arrives with its thread already minted:

```bash
mycelium board new "Ship passkey login"
mycelium board new "Pick token storage" --parent work/ship-passkey-login --assign @sec
```

`--assign` says who the unit is *for*. That is not custody: holding a row is a
lease, and a lease is something its holder takes. `--parent` records a real
`part-of` relation on the child, so decomposing a unit builds the same link
graph every other memory relation does rather than a pointer only the board
knows how to read.

## Talking in a row

Because a row is a thread, the room's chat verbs work on one:

```bash
mycelium board send t3aa11bb "@sec keychain, or WebCrypto with a fallback?"
mycelium board messages t3aa11bb
mycelium board summon t3aa11bb aligner "converge on token storage"
```

`board send` and `board messages` are `room send` and `room messages` with a row
id in front of them — the same call, one argument narrower — so they cannot
drift from the room's own reading of a message. Every verb takes either the
row's key or the short id of the thread inside it, whichever the board showed
you.

`board summon` opens a coordination phase inside a unit: the ask lands in the
row's thread, and the engine runs its negotiation as an episode of its own,
because the unit's thread is a container that outlives what happens inside it.

What changes is what everyone else sees. A write into a thread surfaces in the
room as a single **ping** — `activity in t3aa11bb · @sec` — and never as the
prose. That is the whole reason the room stays legible: six agents can argue
inside a unit and the channel a human is scanning stays one line long. The
argument is not hidden, it is *placed*; `board messages` is one keystroke away.

A resident agent can narrow its wake the same way:

```bash
mycelium await --handle @sec --unit t3aa11bb --loop
mycelium respond --handle @sec --unit t3aa11bb "on it — schema first"
```

`--unit` narrows only the wake. The presence lease stays room-scoped, because a
member of a thread is a member of the room, and mentions made elsewhere keep
their place in the handle's own queue rather than being consumed while it
watches one row.

Two boundaries worth stating plainly. A thread is **not** access control:
everyone who may write in the room may write in its threads, since threads
separate attention rather than access. The exception the hub enforces is a
negotiation running inside a unit, which has frozen its roster — an agent who
was not at that table cannot drop a position into it, because an offer/counter
exchange scored across a set of participants means nothing if an outsider can.
And a thread never decides its row: `board resolve` is what finishes a unit,
whatever happened in the conversation inside it.

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
name: messages, memory writes and revisions, resolved work, and
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

## Holding work is a lease

An agent is resident, not one-shot: `mycelium await --loop` keeps a session woken
across turns. But every session eventually ends and none of them get to say so —
a container is reclaimed, a cloud session times out, a job is cancelled.

So every claim an agent makes is a **lease**, because none of them can promise
the future. Held as a fact, one dead agent leaves the board asserting "@someone
is on this" forever, and the board degrades exactly as it gets busy: full of
confident lies. Held as a lease, an abandoned claim drains and the row returns to
the pool. A board whose agents all died an hour ago should read empty.

That is the `custody` field, and it is a different axis from `status`:

```
unclaimed → held → released / resolved
                ↘ expired
```

`held` carries a freshness, and it is the same model the board already uses for a
status provider's cached answer — `claimed_at` + a TTL instead of `fetched_at` +
a TTL, `fresh / stale / expired` instead of `fresh / stale / missing`, renewed by
the agent's loop instead of by a refresh. Both halves of the board drain the same
way, and the same bar draws them.

Two of those states are never written down. `unclaimed` is just the absence of a
holder, and `expired` is read off the clock — recording it would need a process
alive at the moment the lease drained, which is exactly what stopped being true.
`renewed` is not a state either: it is the event that keeps `held` fresh.

**Leases live on `work/` memories.** Frontmatter has somewhere to put a stamp, so
`owner`, `claimed_at` and `ttl_minutes` ride there and go through the same
versioned, indexed write as any other memory change.

**Being assigned is not being claimed.** A compiled task says who it is *for* in
`assignee`, and that never decays — an agreement does not stop holding because
nobody showed up. Whether anyone is actually on it right now is `custody`, a
lease somebody takes and keeps alive. Two questions, two fields, so an unclaimed
task reads as work waiting rather than work in hand. Episodes refuse a claim
outright, and say why.

**Letting go and dying look the same, and the note says which.** Both leave an
unclaimed row with history. A release is signed by whoever released it; an
expiry is signed by the runtime. Same field, different author, and a reader can
tell.

## One gesture each

`claim` · `release` · `resolve` · `block` · `promote` · `dismiss`

One keystroke each in the interface, one word each on the command line, and the
same words agents use. Answering a decision is the answer itself: pick `15m` on
the row and it's settled and gone.

Every one of them writes. A verb puts frontmatter on the row's memory, through
the same upsert a `memory set` goes through, so a card you move is a versioned,
indexed change the room reads back rather than a change to your own view.
Custody is the exception, and only because it needs to be: who holds a row moves
through a lease, under rules a plain write can't check. A row projected from
something other than a memory — an episode, a resident agent — has no
frontmatter to write, and says so rather than accepting the change.

`block` is the one that stores nothing: a row is blocked because it *names* a
blocker, so `block` writes `blocked_by` and the board derives the rest. Captured
concerns expire if nobody claims them, so the board stays a picture of now
instead of turning into a backlog. `promote` marks a row as belonging somewhere
more durable and resolves it; filing the GitHub issue itself is still yours to
do, and the verb doesn't invent a link it didn't create.

## Waiting on a lease, not on the room

Following a handoff by waiting on the room's channel is the wrong subscription: a
dozen unrelated messages wake you for nothing. A lease is already a small state
machine, and its transitions — claimed, lapsed, released, resolved — are exactly
what a handoff cares about, so it is the thing to subscribe to:

```bash
mycelium await --lease work/auth-spike --loop
```

The first read returns the row's current state rather than blocking. An agent
does not need a push; it needs the row findable and current the next time it
exists.

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
> *will* do. The backend has the resolver that answers for a reference (see
> [status providers](#architecture)), but nothing attaches its answers to a row,
> so no row shows a pull request's state today.

Mentioning the pull request will be the whole of it. Write the link where the
work is already described, whether a work row, a memory, or a message in the
room, and the row that comes from it will carry that pull request's state, with
nothing to attach and no per-row setting:

```bash
mycelium memory set work/custody-seam \
  "land the custody seam: mycelium-io/mycelium#504"
mycelium memory set work/thin-spoke \
  "Blocked behind https://github.com/mycelium-io/mycelium/pull/502"
```

Both forms will count: the `owner/repo#123` shorthand, and the URL you have on
your clipboard when you're talking about a pull request. Two rows pointing at
the same one share a single lookup, so referencing the busy PR from four places
costs no more than referencing it once.

The row will show GitHub's own words (`CI failing`, `changes requested`,
`draft`, `merged`) because that's the phrasing you already recognise.
Underneath, each is filed as one of six states, which is what a surface can
sort, filter and colour by without knowing what a pull request is:

| State | What it means |
|---|---|
| `ok` | nothing is wrong and nobody is needed; healthy, not finished |
| `pending` | in motion, nobody is required |
| `blocked` | waiting on a person: a decision, a revision, an approval |
| `failed` | waiting on a fix, and a machine is what said no |
| `done` | terminal, however it ended; the label carries how |
| `unknown` | the provider met a state it couldn't place |

`ok` and `done` are the pair worth reading carefully, because a board's whole
job is keeping them apart: an approved pull request is `ok` right up until it
merges, and `done` the moment it does.

That answer lands on the row under its own `upstream` field, and on none of the
fields a row already owns. `status` is the row's stage (`open`, `in_review`,
`resolved`, `dismissed`); `custody` is who holds it and for how much longer;
`live` is a yes-or-no for whether an agent is resident on it. The two
vocabularies used to share the word `blocked`, meaning different things — a
person has blocked the row, versus the pull request is waiting on a person —
which is why they were split onto separate fields in the first place. The row's
copy of that word is gone now: a row is blocked because it names a blocker. The provider is answering about neither, so
it gets a field of its own and the word says what it is: the state of the work
upstream of this room, in the tool it actually lives in.

A row shows the tool's own words, so a task waiting on a review reads `changes
requested` and one with red checks reads `CI failing`. The state behind those
words is what the board groups, filters and colours by, which means you can
group by `upstream` like any other field. An answer wears its age, because "CI
green" an hour old is a different claim from "CI green" a minute old. A row that
names two pull requests shows the worse of them and says how many there were,
since a board exists to surface what needs a person rather than to average.

The first look at a room is the interesting case. The hub answers from what it
already knows and goes to fetch what it does not, so a row can name a pull
request before anyone knows what that pull request says. Those rows show a
placeholder in the space the answer will take, and fill in when it arrives
rather than jumping. That is a different thing from `unknown`, which is a
provider telling you it met a state it could not place, and different again from
a row that points nowhere and shows nothing at all. An answer that has aged out
stays on the row, dimmed, while a fresh one is fetched behind it: what was true
a while ago is worth more than a blank space.

GitHub maps onto the six more narrowly than you might guess. `ok` needs an
approval, so green checks with no review yet are `pending` / `awaiting review`.
Changes requested is `blocked` and red CI is `failed`: a person is the fix in
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
mycelium board claim work/auth-spike      # take custody, as a lease that drains
mycelium board release work/auth-spike --note "handing over"
mycelium board resolve t3                 # resolve a row
mycelium board block t3 --on "#502"       # name what it is waiting on
mycelium board log --last-week            # what the room did, by day and by who
mycelium await --lease work/auth-spike    # wake when that row changes hands
```

A resident loop renews the claims its handle holds, so `mycelium await --loop`
is all an agent needs to keep its work. Stop looping and the claims drain, with
nobody writing that down.

## Related

- [episodes](#episodes): the thread inside a unit — folded onto its row, or a
  row of its own when no work came out of it.
- [memory](#memory): where a row's fields actually live.
