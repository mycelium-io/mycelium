# Start Agents From the App

The app can start coding agents on your own computer. It can start one agent
with its own instructions or a whole swarm on a task. The program that does
this is the **runner**, which runs on that computer. The runner also keeps your
agents in touch with the room. When someone mentions an agent, gives it a turn
or assigns it a task, the runner wakes it. It also tells the hub whether each
agent is busy.

The desktop app runs the runner for you. Anywhere else, start it and leave it
running:

```bash
mycelium runner --detach     # start in the background
mycelium runner status       # is it running, and does the hub see it?
mycelium runner stop         # stop it; agents it started keep running
```

While the runner isn't running, your agents keep working but don't hear about
mentions or turns.

## How it connects

The runner only ever connects out to the hub, and the hub never reaches into
your machine. When you ask for an agent in the app, the hub hands the request
to the runner the next time the runner checks in, which takes a few seconds at
most. It works the same whether the hub is on your laptop or on a server, and
whether or not your laptop can be reached from outside.

The runner looks on your `PATH` for the agent CLIs it knows, such as Claude
Code, Codex, Gemini CLI, Cursor Agent, OpenCode, Pi, GitHub Copilot CLI and
Amp. It tells the hub what it found and starts agents in [herdr](#herdr)
terminals. It needs herdr 0.9.3 or newer, which the desktop app includes. To look
again, press **Rescan** in the app or run `mycelium runner scan`.

## Starting an agent

In a room, open **Members → Add → Your machine** and fill in these fields:

- **Start from a role.** This picks starting instructions such as
  **reviewer**, **implementer** or **tester**, or a blank page. You can save
  instructions you write as a role of your own, which is kept in your browser.
- **A handle**, which the room uses to mention it, such as `@scout`.
- **Instructions**, which say how the agent should work. They're saved in the
  room's memory as `agents/<handle>/notes`. The agent reads them when it
  starts, and you can edit them later.
- **Where it runs.** This is the agent CLI and the folder it starts in, plus
  the machine if more than one runner is connected.

Press **Add to room**. The agent is added to the room and opens in a herdr
terminal. It reads its notes and looks at the board.

Closing its terminal or pressing **Stop** on the Machines page stops the agent.
It stays in the room with its notes, so you can start it again.

### Agents start in auto mode

Claude Code and Codex agents that the app starts (from Add, a swarm, or a
restart) run in their CLI's own auto mode, so they work without stopping to
ask you before each command:

- **Claude Code** starts with `--permission-mode auto`: it decides on each
  action itself and asks only when it judges something risky.
- **Codex** starts with `--approve-for-me`: its approval requests go to its
  own automatic review, inside its usual sandbox.

This applies to that session only. Your CLI settings aren't changed, and an
agent you start yourself in a terminal runs however you start it. Neither CLI
is ever started with its bypass (`--dangerously-skip-permissions`, or Codex's
`--dangerously-bypass-approvals-and-sandbox`). An older version of either CLI
without auto mode starts as it did before. Add agent says which mode an agent
CLI starts in, next to where you pick it.

## Bringing in an agent that's already running

If you started an agent CLI in herdr yourself and it isn't in a room yet, open
**Members → Add → Running agent**. The dialog lists every agent like that on
your machines, with its CLI, its tab name and its folder. Pick one and edit the
handle, which starts out as the tab name, then press **Add to room**.

Your machine asks you first, because it is about to type into that agent's
terminal. After you say yes, the agent is added to the room. Once it's idle, the
runner types a short introduction into it that names the room and its handle and
tells it to read the skill and the board. The agent keeps its own session.
Pressing **Stop** for it later takes it out of the room's sync but leaves its
terminal open.

## Other kinds of member

The same dialog has three other kinds of member. An **Engine** is a member the
hub runs itself. An **A2A service** is a remote agent. **Open session** gives you text to
paste into a coding agent you already have open, and that agent then joins the
room on its own.

To start agents in [Omnigent](#omnigent) instead of herdr, see that guide.

## A swarm on your machine

The **Start a swarm** dialog has a **Where** choice. If you pick a connected
machine instead of the hub, the team is your own agent CLI in a new herdr
workspace on that machine. It runs in the folder you choose, optionally with a
git worktree per member. It's the same as running [`mycelium swarm`](#swarm) in
that folder.

## Which folders

The app can only start agents inside the folders the runner was given and only
with an agent CLI the scan found. A request from the hub names an agent CLI and
a folder, never a command to run. By default
the allowed folder is the one you ran `mycelium runner` from. Name others with
`--root`:

```bash
mycelium runner --root ~/code --root ~/work/api
```

In the desktop app, it's the working folder you chose at first run. Change it in
Settings. When you add an agent that runs on the same computer as the app,
**Choose…** beside **Folder** opens the system's folder dialog. Anywhere else,
type the folder's path.

## You say yes on the machine

Anyone who can reach a hub can ask it to start an agent on any machine
connected to it, and the hub can't prove who asked. So before it starts or
restarts anything, the runner asks you on the machine. It shows who the hub
says asked, the agent CLI, the folder and the start of the instructions. You
answer in one of two ways:

- In the desktop app, a dialog offers **Start** and **Decline**.
- From a terminal:

```bash
mycelium runner requests          # what is waiting
mycelium runner approve <id>      # start it
mycelium runner decline <id>      # don't
```

If nobody answers within ten minutes, the answer is no.

The runner doesn't ask when the request comes from the desktop app's own hub,
since only this computer can reach that hub. That also means any program on
this computer can start agents through it without a question. For another hub you know nobody else can reach, `mycelium runner --trust-hub`
skips the question.

## Pair a computer to skip approvals

Sometimes no one is at a machine to approve requests, as with a Mac mini or a
home server. Pair the computer you work from with that machine. Requests from
your computer then start without asking, within limits you set on the machine.
On the machine:

```bash
mycelium runner pair --folder ~/code --cli opencode --days 30
```

This prints a code like `K7QM-4XHD-9RWA`. On your computer, open the
**Machines** page and click **Add machine → Pair**. Enter the code and a name
for your computer, and check that both sides show the same key fingerprint.

| Option | What it limits | Default |
|---|---|---|
| `--folder` | Folders agents can start in | all of the runner's folders |
| `--cli` | Agent CLIs it can start | any |
| `--swarms` | Whether swarms are allowed | no |
| `--days` | How long the pairing lasts (`0` means no expiry) | 90 |

Anything outside these limits or from another computer still asks. Your
computer signs each request with a key it can't export. The limits are kept on
the machine, so neither the network nor the hub can change them.
`mycelium runner pairings` lists pairings, and
`mycelium runner unpair "work laptop"` removes one.

## Only your machines are listed

The Machines page and **where it runs** show only your own machines. The
Machines page is the laptop icon beside the notification bell. In the desktop
app, your machine is the computer the app runs on. In a browser, add a machine with the code
`mycelium runner` prints when it starts. With the hub's [sign-in](#auth) on,
the hub itself shows each person only the machines they own.

To see and fix the agents already running on a machine, see
[Your agents on a machine](#agents-on-a-machine).
