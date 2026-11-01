# Your Agents on a Machine

Every herdr agent on a machine is listed in one place, whether the runner,
`mycelium swarm` or you started it. In the app, that's the **Machines** page.
In the desktop app, it's **Your agents…** under its menu bar or system tray
icon. From a terminal on that machine:

```bash
mycelium machine
```

![The Machines page: a machine's agent CLIs, its agents, and what to fix](app-machines.png)

It lists the agents by herdr workspace and says what each one is doing. Then it
lists what's wrong, with the command that fixes each problem. Add `--json` for
the list as data.

An agent is in one of these states:

- **working** or **idle** while it runs;
- **blocked** when it has stopped at a prompt and is waiting for you to answer
  in its terminal;
- **stopped** when its terminal is open with nothing running in it;
- **pane gone** when its terminal was closed.

## When herdr restarts

Restarting herdr's server, for example to update it, stops every agent running
in it. If herdr's integration for an agent's CLI is installed, herdr brings
that agent back in its own conversation. Without it, the terminals come back
empty and the agents show as stopped.

```bash
mycelium machine integrations             # which are installed
mycelium machine integrations --install   # install them for the agent CLIs here
```

Installing one adds a hook to that agent CLI's own settings. For Claude Code,
that's `~/.claude/settings.json`. So Mycelium only does it when you say so, and
the desktop app asks once.

## Pausing your agents

Pausing an agent stops it where it is without closing it. Nothing wakes it
until you resume it, and messages for it still arrive. When it's resumed, it's
told what came in while it was paused and carries on where it stopped. A
working agent is interrupted, and told the pause came from Mycelium and isn't a
correction of its work.

```bash
mycelium agent pause --all        # every agent you own, in every room
mycelium agent resume --all       # in the morning
mycelium agent pause reviewer     # one
mycelium agent stop reviewer      # close it; it stays in the room
```

In the app, an agent's right-click menu in the members list has **Pause**,
**Resume** and **Stop**, and ⌘K has **Pause my agents** and **Resume my
agents**. While your agents are paused, the status bar says how many, and
clicking it resumes them. The desktop app has the same two under **Agents** in
its menu bar or system tray icon. Only an agent's owner can pause, resume or
stop it. An agent with no owner on record can be paused by anyone, but can only
be stopped on its own machine.

## Restarting agents

An agent that stopped and didn't come back can be restarted. It starts again
in its own folder as the same member. Claude Code comes back in its own
conversation. Other agent CLIs start a new one, read their notes and catch up
from the room.

```bash
mycelium machine restart --all         # every stopped agent
mycelium machine restart reviewer      # one
```

On the Machines page, **Restart** shows where each agent will start before it
starts any of them. The runner then asks you on the machine first, as it does
before it starts any agent.

## Other fixes

```bash
mycelium machine rename reviewer "review"  # its name in herdr
mycelium machine unbind reviewer           # forget its terminal; it stays in the room
mycelium machine unbind --gone             # forget every terminal that's gone
```
