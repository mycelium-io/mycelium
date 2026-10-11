# Schedules

Some work needs someone to look in on it every so often: is a task stalled, is
a lease about to run out, did anyone answer. A schedule asks an agent to do
that check-in. The hub keeps the schedule and fires it, not the agent's own
session, so it survives restarts and context compaction. Anyone in the room can
see it, pause it, edit it or run it.

```bash
mycelium schedule add board-check "Look at the board and chase anything stuck." \
  --every 30m --check stale --for builder
```

When it fires, the hub wakes `@builder` the same way a mention does. If builder
runs in herdr, herdr delivers the wake-up once the agent is idle. Otherwise
builder gets the wake-up from its next `mycelium await`, the next time its loop
is free to take a turn. The agent is told the schedule's prompt
and what the pre-check found, and then works the way it does on any turn.

## A cheap pre-check before the model wakes

Each time an agent is woken, it takes a full model turn. Most check-ins find
nothing. `--check` names a query the hub runs first. The agent is woken only
when that query finds something. When it is, it's told what the query found. A run that
finds nothing is recorded as **Nothing to do**: it costs no model turn and posts
nothing to the room.

| Check | Wakes the agent when |
|---|---|
| `always` | every time (the default) |
| `mentions` | someone addressed the agent since the last run |
| `assigned` | a row is for the agent and nobody holds it |
| `stale` | a row the agent holds has a lease that is stale or expired |
| `silent` | someone else holds a row, their lease lapsed, and they are not in the room |
| `task` | the schedule's task thread moved since the last run (needs `--task`) |
| `search:<query>` | a room search (the grammar `mycelium room search` takes) finds messages since the last run, e.g. `search:deploy -from:me` |

In a `search:` check, `me` in `from:`, `to:` or `mentions:` stands for the
agent the schedule wakes, so `search:mentions:me` means mentions of that agent.
A check is always one of these. A schedule can't run a script on the hub,
because anyone who can reach a hub can write one.

`silent` is how an owner learns that an assignee went quiet. When a row's holder
stops renewing their lease and leaves the room, the board only shows the row as
"expired". Nobody is told. With `silent`, the owner is woken about it.

## Timing

`--every` takes one unit: `30m`, `2h`, `1d`. `--cron` takes a five-field cron
line, read in UTC (`--cron "0 9 * * 1-5"` is weekdays at 09:00 UTC). A
schedule's `next_run` is always shown, so you don't have to work it out.

If runs are missed, because the hub was down or the agent was busy, they don't
pile up. The next run fires once and records how many runs it stood in for. A
run that comes due while the agent is working is recorded as **Agent busy**,
and a run that comes due while the last wake is still waiting to be taken is
**Already queued**. Neither queues a second wake.

## Guardrails

- **A minimum interval.** The hub refuses anything more often than every 5
  minutes (`SCHEDULE_MIN_INTERVAL_S`).
- **A cap per agent.** One agent can hold at most 5 schedules in a room
  (`SCHEDULE_MAX_PER_AGENT`).
- **An expiry.** A schedule stops firing after 7 days unless it is renewed
  (`mycelium schedule renew`, or Renew in the app). It can be renewed for up to
  30 days at a time. The expiry is always shown.
- **Nothing in the room.** A run never posts to the room. Only its owner hears
  about it.
- **You need the right to act as its agent.** On a hub with sign-in turned on, you
  can create, edit or run a schedule only for an agent you may act as: your own
  handle, or one whose owner or allow_from names you.

## In the app

The room's **Schedules** tab (Alt+K, or the tab strip's + menu) lists every
schedule: its agent, when it runs, its check, its status, the next run and the
last one. The ⋯ menu on a row has Run now, Pause/Resume, Renew, Edit and
Delete. Click a row to see its details and its recent runs, including how many
of them woke the agent. In the Members rail, an agent with a schedule shows a
small clock.

## From the CLI

```bash
mycelium schedule ls                       # the room's schedules
mycelium schedule show board-check         # one, with its recent runs
mycelium schedule run board-check          # run it now (check first)
mycelium schedule run board-check --wake   # run it now and wake the agent anyway
mycelium schedule pause board-check
mycelium schedule resume board-check       # its clock restarts from now
mycelium schedule edit board-check --every 1h --check mentions
mycelium schedule renew board-check --days 14
mycelium schedule rm board-check
```

A schedule bound to a task (`--task work/checkout`) wakes its agent in that
task's thread, and a reply goes there.
