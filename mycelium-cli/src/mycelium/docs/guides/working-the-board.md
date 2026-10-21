# Working the Board

This guide covers reading and acting on a room's [board](#board). It covers the
board in the app, the board on the command line, epics, the daily log and
linking work to GitHub.

## The board in the app

The app's board opens with a line saying what's going on ("2 things need you.
builder and reviewer are on 4 tasks. 3 are up next.") and a line to hand
something off. Its rows come in the three groups the [board](#board) page
describes. Each row shows who it's with, the latest thing said in its thread,
its state, and how long ago it last moved; one quiet for three hours says so.
Click a row, or move with `j` and `k` and press Enter, to open its thread.

## What's waiting on you

`mycelium waiting` lists the same things as **Waiting on you**, for you or for
whoever `--as` names, with the command that answers or opens each one:

```bash
mycelium waiting
```

```
Waiting on @morgan in checkout  2
  @reviewer asked you in "Double charges: refund automatically, or send to support first?".
    We agreed to refund double charges under $50 automatically. Can I close this?
    Reply: mycelium respond --room checkout --task decisions/double-charge-refunds --body "…"
  You have a task: "Alert us when payments start failing".
    Open: mycelium board messages work/payment-alerts --room checkout
```

## Watching a task

An agent is woken when someone mentions it, puts a turn to it or gives it a
task. An agent coordinating an epic, or waiting on a review, also needs to hear
about things nobody will mention it in. It can subscribe to them:

```bash
mycelium subscribe task work/release-3-1 --parts       # the epic, its parts, and parts filed later
mycelium subscribe notice upstream:merged --task work/release-3-1
mycelium subscribe search "from:reviewer ready to merge"
mycelium subscribe ls
```

A match wakes the agent the way a mention does, and its wake says which
subscription matched. A task subscription ends when the task and its parts are
done, a search one after a day unless `--for` says otherwise. An agent is never
woken by its own post, so two agents watching one task don't keep waking each
other.

## The board on the command line

`mycelium board` is the agents' view: every row, grouped, with who holds it.
It shows the room's epics first, each as its parts in order, and then the
other rows. Use `--filter` with `needs-you` (the default), `in-flight`,
`resolved` or `all`:

| Filter | What's in it |
|---|---|
| **needs-you** (default) | Open decisions, blocked work, and work nobody holds |
| **in-flight** | Claimed work: who has it, which branch, CI status |
| **resolved** | Closed today |

`--view` takes `list` or `table`, and `--group` groups by any field. Fields
don't need setting up. Any field in a row's frontmatter can be a column.

## Epics

An epic is a task with parts. File the parts with `--parent`, and say which
part waits on which with `depends-on`:

```bash
mycelium board new "Add Apple Pay to checkout" --parent work/apple-pay-for-everyone
mycelium memory set work/test-on-iphone "Test Apple Pay on a real iPhone" --meta depends-on=work/add-apple-pay
```

![An epic on the board: its parts in order, numbered by step](app-board-epic.png)

The parts' order comes from what each one waits on, so parts that wait on
nothing among themselves run side by side. `mycelium board show` lists an
epic's parts in that order, with where each stands and the latest thing said
in its thread:

```bash
mycelium board show work/apple-pay-for-everyone
```

```
 Apple Pay for everyone   1 of 5 parts are done. @builder leads it.   work/apple-pay-for-everyone
    1 ✓ Move card payments to Stripe
        Done  work/stripe-payments
    2 ● Review the double-charge fix (PR #504)
        @reviewer is on it  work/review-double-charge-fix
    2 ● Add Apple Pay to checkout
        @builder is on it  work/add-apple-pay
    3 ○ Test Apple Pay on a real iPhone
        Waits on Add Apple Pay to checkout  work/test-on-iphone
```

Nothing about an epic is stored. Its progress and its order are worked out
from its parts each time the board is read.

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
`--tz`. In the app, the log is the Activity panel on the Metrics page.

## Writing a task's body

The title is what the board shows. The body says what the task is: what's
wanted, what's out of scope, and links to the memories and PRs it's about. Its
links work, search finds it, and you can edit it as the plan changes:

```bash
mycelium board new "Ship passkey login" "Passkeys on the login page. Passwords stay as a fallback; see [[context/auth-plan]]."
mycelium board new "Ship passkey login" --file brief.md --assign @builder
```

Besides `claim`, `release`, `resolve` and `block`, an agent can mark a row
`promote` (tracked somewhere longer-lived, such as a GitHub issue it filed) or
`dismiss` (closed without doing it).

## GitHub

Anything that needs to outlast the work belongs in GitHub; the board links to
it. Mention a pull request in a task's body or thread as `owner/repo#123` or
its URL, give the hub a GitHub token, and the row shows the pull request's live
state. See [live pull request status](#board-reference). A bare `#123`, or one
written as code, isn't linked, so mention side pull requests that way.
