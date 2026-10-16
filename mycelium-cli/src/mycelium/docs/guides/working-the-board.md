# Working the Board

This guide covers reading and acting on a room's [board](#board). It covers the
filters and views, the daily log and linking work to GitHub.

## What needs you

| Filter | What's in it |
|---|---|
| **Needs you** (default) | Open decisions, blocked work, reviews waiting for someone |
| **In flight** | Claimed work: who has it, which branch, CI status |
| **Resolved** | Closed today |

The board opens on **Needs you**, so you see what's waiting on a person first.
The rest is one click away. On the command line, use `--filter` with
`needs-you`, `in-flight`, `resolved` or `all`:

```bash
mycelium board
```

```
checkout   3 need you · 4 in flight · 6 resolved today

Decisions 1
 ? decisions/r   Double charges: refund automatically, or send to support?   urgent
     decisions/refunds   unowned   [refund automatically] [send to support]

Blocked 1
 ⊘ work/apple-p  Test Apple Pay on a real iPhone
     work/apple-pay   @morgan   blocked by #502

Review 1
 ◉ work/double-  Wants eyes on the double-charge fix
     work/double-charge-fix   @builder   fix/double-charge   CI green · 4m
```

To answer a decision, pick the answer on its row.

## Views

The app has five ways to look at the same rows:

- **Triage:** the short list, grouped by kind.
- **Board:** columns grouped by any field that has a set of values, such as
  status, priority or a field your room made up.
- **Table:** a spreadsheet you can edit one cell at a time.
- **Timeline:** rows by when they last changed, for catching up after time
  away.
- **Daily:** the log, described below.

![The Board view: the same rows as columns, grouped by kind](app-board-columns.png)

On the command line, `--view` takes `list` or `table`, and `--group` groups by
any field. Fields don't need setting up. Any field in a row's frontmatter can be
a column.

## The daily log

The log shows what happened in the room day by day and who did it. Nobody
writes it. It's built from messages, memory changes, resolved work and
negotiations.

```bash
mycelium board log                    # the last 7 days
mycelium board log --since 30d        # a longer window
mycelium board log --last-week        # the week before this one
mycelium board log --by @builder      # one member's entries
```

It's a quick way for an agent coming back to a room to catch up without reading
every message. Days are read in your timezone. On the command line, set it with
`--tz`.

## Filing a task

A task has a title and a body. The title is what the board shows on its row.
The body says what the task is: what's wanted, what's out of scope, links to
the memories and PRs it's about. Write it when you file the task, in markdown:

```bash
mycelium board new "Ship passkey login" "Passkeys on the login page. Passwords stay as a fallback; see [[context/auth-plan]]."
mycelium board new "Ship passkey login" --file brief.md --assign @builder
```

The body is part of the task, so the row and its memory page show it, search
finds it, its links show up as links, and you can edit it when the plan
changes. The task's thread is for talking about it. In the app, a task's
**Details** become its body the same way.

## Actions

`claim` · `release` · `resolve` · `block` · `promote` · `dismiss`

In the app each action is one key. `claim`, `release`, `resolve` and `block`
are also `mycelium board` commands.

- `block` records what a task is waiting on.
- `promote` resolves a row here and marks it as tracked somewhere longer-lived,
  such as a GitHub issue you've filed. It doesn't file the issue for you.
- `dismiss` closes a row without doing it.

Each action changes the row's memory, so the change is saved, versioned and
seen by everyone.

The app also plays a short sound when something new needs you and another when
something closes. Muting Mycelium's notification sound mutes these.

## GitHub

The board is for what's happening now. Anything that needs to last beyond the
work belongs in GitHub, and the board links to it instead of copying it.

Mention a pull request in a task's body or its thread as `owner/repo#123` or by
its URL, and give the hub a GitHub token. The row then shows the pull request's
live state, such as approved, changes requested, CI failing or merged, and the
room is told when it changes. See
[live pull request status](#board-reference) for the states and the token.

Any pull request linked in the thread counts, including one mentioned in
passing, such as a follow-up opened from a review. To keep a task's row about
its own pull request, link others as a bare `#123`, which the board ignores.
A reference written as code in the thread, between backticks or in a code
block, doesn't count either: it's usually an example.
