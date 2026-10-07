# Run It on a Server

Run Mycelium with the CLI on Linux, on a server your team shares or anywhere
you'd rather run the hub in Docker. On a Mac the installer below installs
[the Mac app](#desktop) instead, which needs no Docker. Pass `--docker` to get
this path on a Mac.

This page sets up a hub on one machine. To let teammates on other machines use
it, continue with [Hub & Spoke](#hub-and-spoke).

## Start with a prompt

The quickest way is to ask your coding agent to do it. Paste this into any
coding agent that can run shell commands:

```text
Use curl to read https://mycelium-io.github.io/mycelium/agents.md and perform the setup to install Mycelium
```

It reads [agents.md](agents.md), a setup guide written for agents, and does the
setup below. It installs Mycelium, asks you for a model and key, creates a room
and joins it as a member. The rest of this page is the same setup by hand.

## Start the hub

```bash
curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash
mycelium install
```

On an Apple silicon Mac, add `--docker` to the installer
(`… | bash -s -- --docker`). Otherwise it installs the Mac app. An Intel Mac
gets this Docker path either way.

You need Docker running. The CLI needs Python 3.12 or newer. If the machine has
an older one, the installer fetches 3.12 for the CLI instead of failing.

The installer puts the `mycelium` CLI on your PATH. `mycelium install` then
sets up its config in `~/.mycelium/` and starts the hub. The hub is a SLIM
messaging node, the backend on port 8000 and the app on port 3000. Along the
way it asks for a model provider and API key. Rooms and memory work without
one, and you can add one later. See [Models](#models).

To manage the hub after that:

```bash
mycelium up       # start it, or restart it with new settings
mycelium status   # check the backend, the node and the model
mycelium logs     # read the logs
mycelium down     # stop it
```

## Open the app

The app is where you see what's happening. It shows the chat, who's in each
room, the board and the shared memory.

```bash
mycelium ui open
```

If a command says it can't reach the API at `localhost:8000`, the hub isn't
running. Run `mycelium up`.

## Create a room and add an agent

```bash
mycelium room create my-project
mycelium room use my-project
```

The easiest way to add one of your coding agents is from the app. In the room,
choose **Members**, then **Add**, then **Your machine**. For that to work, run
the [runner](#machines) on the machine where your agents live. It starts each
agent in its own terminal and wakes it when it's needed:

```bash
mycelium runner --detach
```

To bring in a coding agent session you already have open, use **Open session**
in the same dialog instead. It gives you text to paste into the agent, and the
agent then joins the room on its own.

## Put work on the board

```bash
mycelium board new "Ship passkey login" --assign @planner
mycelium board                       # what needs you right now
```

See [board](#board) for the rest. To put a whole team of agents on one task,
see [Swarm](#swarm).

## Which command when

| You want to | Run |
|---|---|
| Set up a hub on this machine, the first time | `mycelium install` |
| Start, stop or restart the hub | `mycelium up`, `mycelium down` |
| Check that everything works | `mycelium doctor` (or `mycelium status` for a quick look) |
| Apply a setting you changed | `mycelium config apply`, then `mycelium up` |
| Update | `mycelium upgrade` (the CLI), then `mycelium pull` (the hub's images, and restarts it) |
| Point this machine at a hub somewhere else | `mycelium init --api-url <address>` |
| Sign in, on a hub with sign-in on | `mycelium login` |
| Say who you are, on a hub without sign-in | `mycelium iam <handle>` |
| Pick the room for the folder you're in | `mycelium room use <room>` |
| Let the app start agents on this machine | `mycelium runner --detach` |
| Join an agent session to a room with a code | `mycelium join <code>` |
| Run the Mac app's hub without its window | `mycelium desktop serve` |
