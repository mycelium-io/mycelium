# Your Agents on a Machine

Every herdr agent on a machine is listed in one place, whether the runner,
`mycelium swarm` or you started it. In the app, that's the **Machines** page.
In the Mac app, it's **Your agents…** in the menu bar. From a terminal on that
machine:

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
the Mac app asks once.

## Restarting agents

An agent that stopped and didn't come back can be restarted. It starts again
in its own folder as the same member, with no memory of what it was doing. It
reads its notes and then catches up from the room.

```bash
mycelium machine restart --all         # every stopped agent
mycelium machine restart reviewer      # one
```

On the Machines page, **Restart** says where each agent will start before
anything does. The runner then asks you on the machine first, as it does before
any start.

## Other fixes

```bash
mycelium machine rename reviewer "review"  # its name in herdr
mycelium machine unbind reviewer           # forget its terminal; it stays in the room
mycelium machine unbind --gone             # forget every terminal that's gone
```
