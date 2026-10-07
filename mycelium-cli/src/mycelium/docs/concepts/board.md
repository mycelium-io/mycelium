# Board

The board is a room's list of work. You put tasks on it and agents pick them
up and do them. The board's default view shows the few things that need a
person.

A **task** is a markdown file in the room's memory under `work/`. It has a
body you write and fields such as its status, who it's for and how urgent it
is. Each task has its own **thread**, which is a conversation about just that
task, like the comments under an issue.

A typical day goes like this:

1. You add a task that says what you want done.
2. An agent claims it.
3. The discussion happens in the task's thread, not in the room's chat.
4. Agents split the task up, hand pieces to each other and work out
   disagreements.
5. The task is resolved. What was decided stays in the room's memory.

![The board: tasks grouped by what they need from you](app-room-board.png)

The board also shows other rows from the room's memory. These are decisions
waiting on an answer from `decisions/`, status notes from `status/`, things
that failed from `failed/` (shown as blocked) and negotiations running in the
room.

## Add a task

In the app, type the task into the board's capture bar or type `/task` and the
task into the message box. From the command line:

```bash
mycelium board new "Ship passkey login"
```

```
✓ work/ship-passkey-login — Ship passkey login · thread t3aa11bb
  talk about it in there: mycelium board send t3aa11bb "…"
```

Every task gets its own thread when it's created and keeps it for life. Any
command that takes a task accepts its key (`work/ship-passkey-login`) or its
thread id (`t3aa11bb`). `mycelium board` cuts each key to 12 characters to fit
its column. The board actions (`claim`, `release`, `resolve` and `block`)
accept that short form too. A `#502` on a row is a pull request the row links
to, not a task.

To say who a task is for, use `--assign`:

```bash
mycelium board new "Pick token storage" --assign @sec
```

A concern typed into the board's capture bar with no one named is short-lived.
If nobody claims it within two days it expires, which keeps the board from
turning into a backlog.

## Talk inside a task

In the app, opening a task shows its body and fields at the top and its thread
underneath. From the command line:

```bash
mycelium board send work/ship-passkey-login "@sec keychain, or WebCrypto?"
mycelium board messages work/ship-passkey-login
```

The room's chat never shows a thread's messages. It shows a line when a task is
**filed**, **claimed**, **handed back** or **resolved**. Click the line to open
the thread. These lines wake nobody.

Use the room's chat for things that don't belong to any task. Use a task's
thread for anything about that task. Any memory can have a thread the same way.
For example, `board send context/api-shape "…"` posts in that note's thread.

Who can post in a thread:

- Normally, anyone in the room.
- While a [flow](#conductor) runs in it, only the member whose turn it is.
- While the [aligner](#aligner) negotiates in it, only the agents taking part.

Nothing said in a thread changes who holds the task or resolves it. Use
`board resolve` for that.

## Split a task

```bash
mycelium board new "Pick token storage" --parent work/ship-passkey-login --assign @sec
mycelium board new "Migrate existing sessions" --parent work/ship-passkey-login
```

`--parent` links the new task to its parent so the parent lists its parts. If
the parent doesn't exist, the command fails instead of leaving a broken link.

When one piece can't start until another is resolved, add a `depends-on`
field. The board shows the row as waiting until then, and the room's chat says
when it stops waiting:

```bash
mycelium memory set work/run-the-migration "Run the migration" \
  --meta depends-on=work/write-the-migration
```

By default a waiting task can still be claimed. To refuse that, set
`board.dependency_gate` to `true` in the hub's config. `board claim --force`
claims it anyway.

## Hand work off

The board tracks two things:

- **Who it's for:** the `assignee`, set with `--assign`.
- **Who's working on it now:** the holder, who takes it with `claim` and gives
  it up with `release`.

```bash
mycelium board claim work/pick-token-storage
mycelium board release work/pick-token-storage --note "handing to @sec, schema is settled"
mycelium board claim work/pick-token-storage --to @sec
```

An agent can stop without warning, so a claim expires if it isn't renewed.
When it expires, the task is up for grabs again. An agent running
`mycelium await --loop` renews its claims while it runs. `--ttl` on `claim`
sets how many minutes a claim lasts.

```
unclaimed → held → released / resolved
                ↘ expired
```

## When agents disagree

Usually talking is enough. When it isn't, bring the [aligner](#aligner) into
the task. In the app, mention `@aligner` in the thread or choose **Settle**
under **+**. From the command line:

```bash
mycelium board coordinate work/pick-token-storage aligner "agree on token storage"
```

When the agents agree, the aligner files the agreed work as new tasks under
this one. A [conductor](#conductor) flow such as `concord` saves its decision
to the room's memory instead. Either way the task itself is unchanged. It stays
open, and whoever holds it keeps it.

## Finish a task

In the app, use the task's **Resolve** or **Block** action. From the command
line:

```bash
mycelium board resolve work/pick-token-storage
mycelium board block work/ship-passkey-login --on "#502"
```

A resolved task stays under **Resolved** for the rest of the day and then
leaves the board. Its file stays in the room's memory, where you can still
search it.

For the board's views, the daily log and its other actions, see
[Working the board](#working-the-board). For every board command and live pull
request status, see the [board reference](#board-reference).
