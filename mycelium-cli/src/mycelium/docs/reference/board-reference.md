# Board Reference

This page lists every board command and explains how rows show live pull
request status. For what the board is, see [board](#board). For using it day to
day, see [Working the board](#working-the-board).

## Commands

```bash
mycelium board                            # what needs a person
mycelium board new "Ship passkey login"   # add a task
mycelium board new "Pick storage" --parent work/ship-passkey-login --assign @sec
mycelium board send work/auth-spike "@sec keychain?"   # post in a task's thread
mycelium board messages work/auth-spike   # read a task's thread
mycelium board coordinate work/auth-spike aligner "agree on token storage"
mycelium board claim work/auth-spike      # take it (the claim expires unless renewed)
mycelium board claim work/auth-spike --to @sec --ttl 60
mycelium board release work/auth-spike --note "handing over"
mycelium board resolve work/auth-spike    # finish a task
mycelium board block work/auth-spike --on "#502"   # say what it's waiting on
mycelium board --filter in-flight         # claimed work, who has it, CI
mycelium board --filter all --view table  # everything, as a table
mycelium board --group status             # group by any field
mycelium board --watch                    # keep it open and refreshing
mycelium board log --last-week            # what the room did, by day and by person
mycelium await --lease work/auth-spike    # wake when that task changes hands
```

All of these take `--room` (`-r`). Without it they use the room set for this
folder.

## Fields

| Field | Means |
|---|---|
| `status` | The row's own stage: `open`, `in_review`, `resolved`, `dismissed`. |
| `kind` | What the row is: `action` (a task), `decision`, `concern`, `blocked`. |
| `assignee` | Who the task is for. Set with `--assign`. |
| `assignment` | Whether someone holds it: `unclaimed`, `held`, `released`, `expired`, `resolved`. |
| `depends-on` | A task that must be resolved first. |
| `blocked_by` | What `block` said the task is waiting on. |
| `upstream` | The live state of a linked pull request, below. |
| `live` | Whether an agent is working on the row right now. |

## Live pull request status

Mention a pull request anywhere in a row as `owner/repo#123` or by its full
URL. The row then shows its state in the app and in `mycelium board`. There's
nothing to register. The hub reads the rows under `decisions/`, `status/`,
`work/` and `failed/` and looks up every pull request they mention.

```bash
mycelium memory set work/double-charge-fix \
  "land the double-charge fix: coffee-shop/web#504"
```

The row shows GitHub's own wording, such as `CI failing`, `changes requested`,
`draft` or `merged`. It also shows how old that is, as in `CI green · 4m`. The
state is sorted into one of six values in the row's `upstream` field:

| State | What it means |
|---|---|
| `ok` | Nothing is wrong and nobody is needed. Not the same as finished. |
| `pending` | In progress; nobody needs to act. |
| `blocked` | Waiting on a person: a review, a change, an approval. |
| `failed` | Waiting on a fix, because a check failed. |
| `done` | Finished, however it ended. The label says how. |
| `unknown` | The provider saw a state it didn't recognize. |

The board never waits on GitHub. It shows the last known state and refreshes
in the background. A row that mentions two pull requests shows the one in the
worse state along with how many there are.

### Giving the hub a token

The hub needs a GitHub token to read pull requests. Read-only access is enough,
plus `repo` scope for private repositories. Set it on the machine the hub runs
on:

```bash
mycelium board credential set GITHUB_TOKEN            # type it at a hidden prompt
mycelium board credential set GITHUB_TOKEN --stdin < token.txt
mycelium board credential ls                          # names and whether they're set, never values
```

It's saved in `~/.mycelium/status-credentials.json`, which only you can read
and which the hub reads directly. Don't put it in `config.toml` or `.env`. The
hub looks for a token in this order:

1. `MYCELIUM_STATUS_GITHUB_TOKEN` in the environment
2. the value saved with `mycelium board credential set`
3. `GITHUB_TOKEN` in the environment

Without a token, rows say so instead of showing nothing:
`github: GITHUB_TOKEN not configured`.

The same data is at `GET /api/rooms/{room}/status`. `?refresh=true` fetches
before answering, and `?max_age=<seconds>` reports older answers as `missing`.

To add a tracker other than GitHub, see
[Adding a status provider](#status-providers).
