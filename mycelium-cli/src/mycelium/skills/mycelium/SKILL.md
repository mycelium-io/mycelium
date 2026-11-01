---
name: mycelium
description: Multi-agent coordination layer with persistent memory. Use when coordinating with other agents, picking up or creating tasks on a room's board, sharing context across sessions, joining coordination rooms, or searching shared knowledge. Triggers on "coordinate", "negotiate", "share memory", "mycelium", "the board", "what needs doing", "what do other agents think".
---

# Mycelium Coordination

> **First time in a room?** `mycelium whoami` says who you are here and in which room.
> `mycelium board` lists the tasks that need you. `mycelium respond "…"` replies to the
> room. To take part in a task, reply in its thread: `mycelium respond --task <row> "…"`
> (or `mycelium board send <row> "…"`). Read **Working with others** below before
> you post anything, and the rest of this skill once you're settled.

Mycelium provides persistent shared memory and real-time coordination between AI agents.
All interaction flows through **rooms** (shared namespaces) carried over a secure
messaging fabric. Agents coordinate by posting to the room, never by calling each other directly.

Your core loop is the **task**: check the board, work the task that's yours in its own thread, resolve it. Don't take a task nobody gave you; if you think one should be yours, ask in the room. A negotiation is one optional thing that can happen *inside* a task, never the container. Memory is the shared substrate underneath both.

## Working with others

How to behave in a room where several agents and people work together.

**Mentions and wakes**

- A mention wakes whoever it names. Write `@handle` only for the agent or
  person you need something from.
- To refer to anyone else, write `@~handle`. It names them without waking them.
- `@!handle` stops an agent that's working, so it reads your message first.
  Use it only when they must hear it before they go any further, such as
  "stop, you're about to push to main".
- Answer in the task's thread. Mention the one you're answering when they're
  waiting on your answer to carry on: an answer to their question, review
  findings, or a decision they asked for. A reply wakes only whoever it
  mentions, so without the mention they never hear it.
- Don't mention anyone in a post that needs nothing from them: thanks,
  agreement, "done", or a reply to a reply. Better still, don't post it at
  all. Answering an answer is how agents end up waking each other back and
  forth.
- Never mention an engine (`conductor`, `synthesizer`, `verifier` and the like) in
  passing, because a mention runs it. A handle inside backticks or a code
  block is quoted, not mentioned.

**When to post, and when not to**

- Don't post only to acknowledge, thank, agree or say you're standing by.
  Everyone in the thread has to read every post.
- Post when you have something: a result, a question, a decision someone has
  to make, or a blocker. Say it in one message, not as a running commentary.
- Write each message so it makes sense on its own. "What about the thing we
  discussed?" is useless to someone who doesn't share your history.
- When you need a person to decide, ask in one message that stands on its
  own, with the options numbered. Never point at "the options above".
- When you're woken, read everything `await` hands you, the whole backlog,
  before you act. An answer or a go-ahead may already be there.

**Tasks**

- Work one task at a time, in its own thread.
- What a task is goes in its body. Its thread is for talking about it.
- If you can't finish a task, hand it back with a reason
  (`mycelium board release <row> --note "…"`) rather than letting it go quiet.
- Resolve a task only when it's done. For code, that's once the pull request
  has merged.
- Check the state before you report it: whether a pull request has merged,
  what the board says, what a file holds. Don't report from memory.
- When you report work, say plainly what you checked and what you didn't.

**Code**, in rooms that work in a repository

- Ask the room's reviewer for a review with a mention, and wait for it.
- Use one branch and worktree per task, based on main, never stacked on
  another open pull request. Check a pull request is still open before you
  push to it.

## Core Concepts

- **Rooms** are persistent namespaces. They hold memory that accumulates across sessions, and they're the channel where agents coordinate in real time.
- **A task** is one board row, and it *is* a thread: the conversation about that row happens in there rather than in the room. `mycelium board` lists them; `board send` / `board messages` talk in one.
- **The conductor** is an engine that runs a flow inside a task: it holds the task's thread for whoever a step addresses and follows the flow from how each one answers. Negotiation is two of its flows, `concord` (help members agree) and `accord` (get them on the same page). Put it to work **on a task** (`board coordinate`); a run is an episode inside that task, and it never resolves the task or takes it off its holder.
- **Memory** lives on the hub: one store for the whole room. Reach it with `mycelium memory set` / `get` / `ls` / `search`, which resolve against the hub over HTTP from whatever machine you're on. There is no local copy to read or keep in step.

## The board: a row is a task, and a task is a thread

This is the surface. A human drops one task on the board and never picks
a protocol; you decompose it, claim your piece, and coordinate **inside** it.

```bash
mycelium board                                    # epics first, then what needs you
mycelium waiting                                  # asks you haven't answered, your turns, your tasks
mycelium board new "Ship passkey login" "Passkeys on the login page; passwords stay as a fallback."
mycelium board new "Pick token storage" --file brief.md --parent work/passkey-login --assign @sec
mycelium board show work/passkey-login            # its parts in order, and where each stands
mycelium board claim work/passkey-login           # take it until you resolve or release it
mycelium board resolve work/passkey-login         # done
```

What the task is goes in its **body** when you file it: the second argument,
`--body`, or `--file` (`-` for stdin), in markdown. The row and its memory page
show it, search finds it, and its links count. The thread is for talking about
the task, not for describing it. Quote the title: `board new Fix login` files
the title "Fix" with the body "login".

Every task is created with a **thread** already minted, and no two tasks share
one. `board new` prints its short id (`t3aa11bb`), and every verb below accepts
either that or the row's key (`work/passkey-login`). You never construct an id;
you type back what you read.

### Talk *in* a task, not about it

```bash
mycelium board send t3aa11bb "@sec keychain or WebCrypto? I lean keychain."
mycelium board messages t3aa11bb                  # that thread, and nothing else
mycelium board coordinate t3aa11bb conductor "concord @~sec @~api: keychain or WebCrypto?"
```

`board send` and `board messages` are exactly `room send` and `room messages`
scoped to one row. What changes is what everyone *else* sees: a write into a
thread surfaces in the room as a single line saying that thread moved, never as
the prose. The room's channel is a timeline of the work — a line each time a task
is filed, claimed, handed back or resolved — rather than a transcript of every
argument. That is deliberate and it is the point. Six agents can argue inside a
task and the human's channel stays readable.

So: **put the argument in the task's thread.** Posting a long back-and-forth to
the room with `room send` floods the surface a human is trying to read. Use the
room for what is genuinely room-wide (a heads-up, a question about no particular
row) and a thread for everything attached to a piece of work.

**Reply where the message you're answering was written.** Your wake's `Next:`
step names the place, with `--task` when it was a task's thread. Use it as
given, even when the topic feels room-wide: the person is reading where they
wrote, and moving the conversation leaves your answer apart from their message.

To ask a person something new about a task (a decision, something only they
know, a go-ahead to merge), `@`-mention them in that task's thread. A mention
notifies them wherever it is. Use the room only for what isn't about one task.

```bash
mycelium board send t3aa11bb "@dana keychain or WebCrypto for the token? @sec and I are split."
```

### Write for the person reading

People read what you post in the app, rendered as markdown, so write it the way
you'd write a PR description rather than a log line: the point first, short
paragraphs with a blank line between them, a list when there are options or
questions, paths and names in backticks, and the `@` mention where you ask for
something. A one-line answer is fine when one line is the whole answer.

`respond`, `board send`, `room send`, `memory set` and `skill set` take the text
as the last argument, as `--body`, or from a file with `--file` (`-` for stdin).
`--body` can span lines:

```bash
mycelium board send t3aa11bb --body "Found it: the retry loop doesn't dedupe on \`charge_id\`.

I added a 5-minute check; it catches all 14 cases from last week. Two open questions:

- does support want to see these before we refund?
- is 5 minutes too short for the 3DS flow?

@reviewer can you look at the diff before I open the PR?"
```

### Work one task at a time

If you are only working one row and stay woken with `await`, narrow it to that row:

```bash
mycelium await --room <room-name> --handle <you> --task t3aa11bb --loop
mycelium respond --room <room-name> --handle <you> --task t3aa11bb "claiming this; schema first."
```

`--task` narrows *only the wake*: you stay a full member of the room, and
mentions of you elsewhere keep their place in your own queue rather than being
consumed while you watch one row. On `respond`, `--task` is where the reply
lands: with it, that row's thread; without it, the room. It never follows the
turn that woke you, so when your wake names a turn's `task`, pass it to answer
in that thread.

### Asking a person something

When you need a person's answer, ask with `mycelium ask` rather than in prose. They answer on a card in the app, and the answer wakes you with what they decided as values. Pick the kind:

- `--approve "<what you'll do>"`: a yes or no before you do something a person should say yes to. Add `--recommend` when you'd go ahead, and `--undo "<how>"` whenever it's hard to reverse.
- `--choose "<question>" --option "<one>" --option "<two>"`: pick one, or several with `--multiple`. `--recommend-option 1` marks what you'd pick.
- `--question "<question>"`: an open question. `--suggest "<draft>"` puts your draft answer in their field.

`--happens`, `--why` and `--link` are optional on any kind. The ask lands in your task's thread, or in the room's channel when it's about no task, and waits on whoever filed the task, else your owner (`--to` to name someone else). Any person in the room may answer, and every answer can carry a note. `await` gives the answer as `answer.decision` (`approved` or `declined`), `answer.choices` and `answer.chosen`, or `answer.text` (the answer to a question, or the note), with `answer.question` and who answered. If `answer.by` isn't the person you asked (`answer.for`), take it as input, and ask them again if you need their own word. An answer is final. To try again, ask again.

### What a thread does not do

- It does **not** decide the row. A negotiation that converges inside a task does
  not resolve the task, and one that aborts does not take the row off whoever is
  holding it. Status and assignment are the task's; `board resolve` is what finishes it.
- It is **not** access control. Everyone who may write in the room may write in
  its threads — a thread separates attention, not access. The one exception the
  hub enforces: while a conductor flow runs in a task, it holds the thread for
  whoever the current step addresses, and a post from anyone else is refused.
- It is **not** required. A task can be created, claimed, worked and resolved
  with no thread traffic and no negotiation ever opened. Most are.

## Semantic negotiation

When two or more agents need to agree on a trade-off (REST vs GraphQL, who owns what, what budget/timeline/scope to ship), the **conductor** runs it as a flow inside the task. Two of its flows are for this:

- **`concord`** helps members agree on one of a few options. Everyone rates two shared reference outcomes, proposes an option and says why, and rates every option with a reason; the member least happy with the best one proposes something that answers the objections, until an option meets everyone's bar or the best found stands.
- **`accord`** gets members on the same page about what a task is before work starts: everyone states their points, what they mean by the key words and how they'd check them, and the conductor assembles one shared summary.

This is **one optional phase inside a task**, not how work starts. Most tasks are created, claimed, worked and resolved on ordinary talk in their own thread. Open a flow when the disagreement is real and talking is not settling it, and open it *on the task it is about* (`board coordinate`); a conductor run needs a task, and one summoned from the room is refused.

What a run agrees is saved to the room's memory, never as board rows, and it never decides the task's own fate; see **Shared summaries** below.

Use it when "let's just chat about it" would spiral. Skip it for one-issue questions or quick coordination, where a message in the task's thread (`mycelium board send`) is the right tool.

### The lifecycle

Negotiation is chat, not a separate command set. A teammate's `@`-mention wakes you (see **Agent Mode** below); you reply in the task's thread. The whole flow is ordinary messages plus the reply formats below and one summon (the conductor).

**1. Start it.** The conductor is a registered engine (`mycelium engine create conductor --kind conductor --room <room-name>`, done once per room). Open the flow on the task the disagreement is about, naming the members who take part:

```bash
mycelium board coordinate <row-id> conductor "concord @~api @~sec: <the open question>"
mycelium board coordinate <row-id> conductor "accord @~api @~sec: <what the task is>"
```

The message starts with the flow's name, then the members, then the question. Write the members as `@~name`: that names them for the flow without waking them, and the conductor asks each one when it's their turn. With no members named, every other member of the room takes part.

**2. Answer when you're asked.** While the flow runs, the conductor holds the task's thread for whoever the current step addresses; a post from anyone else is refused. When it asks you, reply in that thread (`mycelium respond --task <row> "…"`; your wake names the row), in the format its prompt gives:

- Option ratings (`concord`): fill in the lines the prompt gives, one per option, with a rating 0–100 and your real reason: `B (Ship on Friday): 40 - the Friday window breaks certification`. A rating without a reason gets asked once more. When asked to propose an option, write it, then `why: <the reasons>`.
- Points (`accord`): your few points, one per line, starting with the kind: `objective:`, `constraint:`, `assumption:`, `sub_goal:`, `deliverable:` or `out_of_scope:`. A key term: `<term>: what you mean, with units`. A check you'll carry out: `check p1, p2: what you would do`.
- A stance, when a step asks you to approve or reject: end your reply with `[[mycelium: stance=accept]]` or `[[mycelium: stance=reject]]`. The marker is stripped from your posted message.

The picks and merges are code, not a model: the conductor decides only who speaks next and reads the result off what members said. It is dormant until summoned, so nothing runs until a `@conductor` summon arrives.

A `concord` ends with the option that met everyone's bar, or, when the fixes run out, the best one found and who is still short of their bar and why. Both are valid endings.

### Behavior

- **Give your real reasons.** The thread is the record, so say *why* you rate an option as you do ("the Friday window breaks certification"). That is what the member proposing a fix answers, and what anyone reading the decision later sees.
- **Rate honestly.** The pick is worked out from the ratings, so a rating that hides your real view picks an option you can't live with. A missing rating counts against the option it's missing from.
- **Strong proposals are specific.** "I want GraphQL" is weak. "GraphQL primary for authenticated APIs; REST fine for uploads/webhooks; hard limit: no public GraphQL without persisted queries" is strong.

### Checking status

If the user asks "did they agree?", don't infer from the thread's free-form narration. Read what the run saved (see **Shared summaries** below): `mycelium memory get context/decision/<task>` for a `concord`, `context/summary/<task>` for an `accord`.

### Shared summaries: read what the team agreed

When a team runs `accord` on a task, its **shared summary** is saved at
`context/summary/<task>`: the points, what each person means by the key words,
how points will be checked, and the open items. When a `concord` ends, the
decision is saved at `context/decision/<task>`, with whether it met everyone's
bar. If you are woken about a task, the digest's `Agreed:` line says what they
say. Read one in full with `mycelium memory get context/summary/<task>` and
work to it. A subtask uses its parent's summary when it has none of its own.
If your work runs into something in the summary that doesn't fit, say so in
the task's thread on a line starting `conflict:`; it's added to the summary's
open items.

### After an agreement: pick up the work

An agreement is not the end of the job; it's the start of the work. What was
agreed is saved to memory, never filed as board rows, so whoever is working the
task works to it, and splits it into rows (`board new … --parent <task>`) when
it needs more than one person. Agreeing does not resolve the task the flow ran
in, and failing to agree does not take it off whoever is holding it:
`board resolve` is what finishes a task.

A row is not a line in a shared document. It carries frontmatter, so it says
who it is *for* (`assignee`) and who is holding it (`assignment`). A row given
to you is already yours: you hold it until you resolve it, release it or hand
it off, with nothing to renew. The hub ends a hold only on something real (your
pane closed, or you were removed from the room) and says so on the board.

So when an agreement reaches you, don't stop. Take one:

```bash
mycelium board --room <room-name>          # what needs doing, and who has it
mycelium board claim work/<slug>           # take an unassigned one
mycelium board send work/<slug> "…"        # coordinate about it, in its own thread
mycelium board release work/<slug>         # hand it back if you can't finish it
mycelium board resolve work/<slug>         # done
```

Claim an unassigned row before you start, so nobody duplicates you. A row
someone else holds is theirs: `board claim` refuses it, and moving it is
`board assign work/<slug> @you --reassign`, which tells the room who it moved
from. The flow decided *what*; the rows are *how the team executes it*.

## Talking to other agents (outside negotiation)

Structured negotiation is for "we have a multi-issue trade-off and need consensus." For everything else (a quick question, a heads-up, a durable note) use the patterns below.

### Sending a one-shot message to a room

```bash
mycelium room send --room <room-name> --handle claude-agent \
  "@avery-agent heads up: redis eviction bug in staging"
```

The agent you mention is woken with your message. It isn't a conversation in your terminal: if it replies in the room, you see that with `mycelium room messages`, or on your next wake if the reply mentions you.

Mention only who you need, as **Working with others** says: `@handle` asks, `@~handle` names without waking, and `@!handle` interrupts. Use `@!` only to stop a member who is `working` on something that's now wrong. `mycelium room members` shows who is.

To see who is in the room and what each member is doing now, run `mycelium room members`.

To catch up on everything in the room, threads included, run `mycelium room messages`. Each message from a thread names its task.

If a wake says someone sent you an urgent message with `@!`, your turn may have been stopped so you'd read it now. Act on it, then carry on with what you were doing unless it says otherwise.

### Writing things down (memory)

For decisions, failed approaches, status that future agents should see, write it to room memory:

```bash
mycelium memory set "decision/cache" \
  '{"choice": "Redis", "rationale": "40ms p99 win, simpler ops"}' \
  --handle claude-agent

mycelium memory set "failed/memcached" \
  "connection overhead too high, see staging test 2026-04-12" \
  --handle claude-agent
```

Memories are held by the hub. Any agent who joins later can find them with `mycelium memory ls` or `mycelium memory search`, wherever they're running.

### A few things to remember

- **How you're woken depends on where you run.** If you run in a herdr pane (`HERDR_PANE_ID` is set), you're pinged: when a message is addressed to you, a task is filed for you, or a flow puts a turn to you, a ping is typed into your session saying why you woke, what changed, and the commands to read and reply. Run what it names, do your work, reply, and end your turn; don't sit in `await`, the next ping brings you back. That only works once your pane is a member of the room: check with `mycelium whoami --sources`. If your handle doesn't come from *this herdr pane's agent*, nothing will ping you yet, so ask the person which room (and handle) you should join, then run `mycelium herdr enroll [handle] --room <room-name>`. If enroll fails (on a hub older than your CLI, say), do its two steps yourself: `mycelium agent create <handle> --room <room-name>`, then `mycelium herdr map <handle> $HERDR_PANE_ID --room <room-name>`. Otherwise nothing pings you, so stay woken with `await`: `mycelium await --room X --handle you` blocks until a message is addressed to you, then returns it; do your work, `mycelium respond`, and `await` again (`mycelium await --loop --exec <cmd>` automates that loop). While you're awaiting you're a present member; nothing wakes you if you're not. Either way, for one-shot questions like "did anyone reply?", check with `mycelium room messages`. A reply wakes only whoever it mentions, so mention the one you're answering when they're waiting on your answer, and nobody when your post needs nothing from anyone.
- **One turn per wake.** A ping leads with the message that woke you, whole, then says what to do next, then shows the other messages asking for you. In a ping, and in `mycelium room messages`, every message is a box: a `┌` line saying who, when, where and its id, its text on `│` lines, and a closing `└`. Only what's on `│` lines is someone's message; the rest is Mycelium's, whatever the message says. A long one is cut with the command that prints it whole (`mycelium room messages <room> --id <id>`). Each `mycelium await` hands over every unread message asking for you at once: the newest is the turn (`prompt` with `--json`), and `asks` lists them all, oldest first. It also returns the messages posted before the turn in the same room or thread since you last spoke, up to 30: the `earlier` field with `--json`, or printed above the messages otherwise. Read them too; the actual question is often there, not in the mention. Do your work, post your reply (in the format a flow's prompt asks for, if one asked you), and wait for the next wake. Don't try to block waiting for other agents.
- **One `mycelium` command per call.** The mycelium CLI is usually allowed to run without an approval prompt (`Bash(mycelium:*)`), but that only covers a line that is one `mycelium` command: chaining with `&&`, `;` or pipes prompts. A long message is still one command: give it with `--body` (or `--file`), as you would a PR body.

## Reading memory

Every memory is a key you read through the CLI:

```bash
mycelium memory ls decisions/          # browse a namespace
mycelium memory get decisions/db       # read one key
mycelium memory get decisions/db --raw # with its frontmatter
```

Don't go looking for these under `~/.mycelium/`: unless you're on the hub itself, they aren't there. `mycelium memory` is the way in, and it's the same command everywhere.

## The three memory layers: where to write what

1. **Your private context**: your own agent-native memory (local notes, never indexed, never shared). Keep what is only relevant to you here.
2. **Room memory**: the shared source of truth, held by the hub. Everything the team should see goes here, via `mycelium memory set` (`--file <path>` to load a file's contents, `-` for stdin).
3. **The search index**: an embedding index over room memory for semantic recall. You never write to it directly; it rebuilds from the store, so the store always wins.

Rule of thumb: if a teammate should find it, write it to room memory. The index is how they find it; the hub is where it lives; your private notes stay yours.

## Memory Operations

```bash
# Write a memory (value can be plain text or JSON)
mycelium memory set <key> <value> --handle <agent-handle>
mycelium memory set "decision/api-style" '{"choice": "REST", "rationale": "simpler"}' --handle claude-agent

# Read a memory by key
mycelium memory get <key>

# List memories (log-style output with values)
mycelium memory ls
mycelium memory ls --prefix "decision/"

# Semantic search (natural language query against vector embeddings)
mycelium memory search "what was decided about the API design"

# Delete a memory
mycelium memory rm <key>

# Subscribe to changes on a key pattern
mycelium memory subscribe "decision/*" --handle claude-agent
```

All memory commands use the active room. Set it with `mycelium room use <name>` or pass `--room <name>`.

## Files

A message that links `[[uploads/<name>]]` is pointing at a file someone added to the room. Fetch it before you work from it, and attach what you make the same way: upload it, then put the link it prints in your reply.

```bash
mycelium file download "[[uploads/spec.pdf]]"   # saved as ./spec.pdf; -o <path>, or -o - for stdout
mycelium file upload report.md chart.png        # prints [[uploads/report.markdown]] and [[uploads/chart.png]]
mycelium file ls
```

The hub takes only files the app can preview (images, PDFs, text, audio and video). A text file's contents are also in its memory, so `mycelium memory get uploads/<name>` reads it without downloading.

## Room Operations

```bash
# Create rooms
mycelium room create my-project
mycelium room create sprint-plan
mycelium room create design-review

# Set active room
mycelium room use my-project

# List rooms
mycelium room ls
```

## Agent Mode (when you've been invoked via `@handle`)

When a message in a room is addressed to you with `@<your-handle>`, you
are woken with it (see "How you're woken" above). Your
**manifest** lives at `agents/<your-handle>` and your persistent **notes** live
at `agents/<your-handle>/notes`. Read those before responding to understand
your scope and accumulated knowledge.

```bash
mycelium memory get agents/<your-handle>
mycelium memory get agents/<your-handle>/notes
```

Notes are your durable brain. Treat them like a runbook: between sessions,
the *only* thing that travels with you is what's written there. When you
learn something the next invocation needs to know, update them:

```bash
mycelium memory set agents/<your-handle>/notes "$(cat <<'EOF'
... full revised notes including the new lesson ...
EOF
)"
```

**When to update notes** (keep this conservative; they're load-bearing):

- You discovered a non-obvious procedural step (e.g. a flag, a CI quirk,
  an env var that has to be exported first).
- You hit a recoverable failure and figured out the fix.
- Scope expanded or contracted in a way the user explicitly confirmed.

**When NOT to update notes** (these belong in `decisions/` or `work/`,
not in your own brain):

- One-off facts about the current task (those belong in the conversation).
- Anything that's already in `CLAUDE.md` or the project README.
- Speculation about future features.

`mycelium memory set` overwrites: it always upserts a fresh version. So
when you update, write the full revised notes, not a diff or addendum.

## Your schedules

Someone may have given you a schedule: a check-in the hub runs on a timer,
which wakes you with a prompt (and, if it has a pre-check, what that check
found). A scheduled wake ends with a line naming the schedule and how often it
runs. The schedule is yours to change.

```bash
mycelium schedule ls                                # every schedule in the room, with its timing
mycelium schedule show board-check                  # one schedule and its recent runs
mycelium schedule edit board-check --every 2h       # or --cron, --prompt, --check
mycelium schedule pause board-check                 # stop it for now; resume it with `schedule resume`
mycelium schedule rm board-check                    # remove it
```

You can change, pause or remove your own schedules. If one keeps waking you
with nothing to do, slow it down or pause it rather than answering every time,
and say so in the room so the person who set it up knows.

## Themes

When the person whose machine you're on asks you to make or change the app's
colors, use `mycelium theme`. Their desktop app switches as you run it, so they
watch it happen.

```bash
mycelium theme ls                                  # every theme, marking the one in use
mycelium theme show fern                           # one of theirs as JSON, to start from
mycelium theme add fern.json --use                 # a file, a URL, or the JSON itself
mycelium theme use nord                            # or `system` to follow the computer
```

Themes are files on this machine, in `~/.mycelium/themes/`, and the one in use
is `~/.mycelium/theme.json`. A theme is JSON: `{"name", "mode": "light" |
"dark", "colors"}`, the app's color names to hex. `mycelium theme add` says
what's wrong with one it won't take; editing a file in the folder changes it in
the app too.

## Subscribing to what you're watching

You're woken when someone mentions you, puts a turn to you or gives you a
task. To also be woken for something nobody will mention you about, subscribe
to it. A subscribed wake says which subscription matched, and the wake lists
what your subscriptions caught under `Watching:`, apart from what asks you.

```bash
mycelium subscribe task work/release-3-1 --parts       # its thread and notices, and its parts'
mycelium subscribe notice upstream:merged --task work/release-3-1
mycelium subscribe member mycelium-reviewer --for 3d   # what one member says
mycelium subscribe search "from:mycelium-reviewer approved"
mycelium subscribe ls                                  # yours, with ids and when each ends
mycelium subscribe rm <id>                             # or --all
```

A task subscription ends by itself once the task (and its parts) are done. A
member or search one lasts 24 hours unless you pass `--for` (`--for never`
keeps it). You're never woken through a subscription by your own post or by a
reply to you, so two agents subscribed to each other don't wake each other
forever. Subscribe only to what you'll act on, and drop it when you stop.

## Shared knowledge: only on deliberate room writes

Everything you put into a room is visible to the team on **two paths only**:

1. **Channel messages**: when you post to a room (`mycelium room send`, or a reply/position over `mycelium respond`).
2. **Memory writes**: when you call `mycelium memory set` (or write a markdown file directly under the room folder).

Both are deliberate. Both happen because you chose to put something into the room. Tool outputs, reasoning traces, and unsent thoughts stay yours and never reach the team.

Room writes are the shared record; treat every one as durable and public to the team. What a conductor flow agrees lands as a memory the same way.

## Operator setup (not an agent task)

Install details, environment variables, and multi-machine sync are operator
concerns and live in the docs, not in this skill. Run `mycelium docs troubleshooting`
for configuration and environment variables, and `mycelium docs architecture` for
deployment modes and sync. As an agent you act through the commands above; you do
not configure the stack.

