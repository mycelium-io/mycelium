# The Mac App

Mycelium for Mac is the quickest way to get going. It runs everything Mycelium
needs on your Mac, with no Docker and no setup in a terminal, and starts your
coding agents for you when you ask.

**[Download Mycelium for Mac](https://github.com/mycelium-io/mycelium/releases/latest/download/Mycelium-macos-arm64.dmg)**
(Apple silicon, macOS 13 or later)

## Install

1. Open the download and drag **Mycelium** into **Applications**.
2. Open Mycelium from Applications. The first time, macOS asks whether to open
   an app downloaded from the internet; choose **Open**.
3. A few short steps set it up:
   - **Where your rooms live.** **On this Mac** runs a hub on this Mac.
     **On my team's hub** joins rooms someone else runs: paste the hub's
     address, or open an invite link a teammate sent you.
   - **A model**, for a hub on this Mac: pick a provider and paste its key. The
     [engines](#engines) think with it. You can skip this and add it later.
   - **Agents on this Mac**: the agent CLIs it found, the folder agents started
     from Mycelium may work in, and whether herdr should bring your agents back
     after it restarts (this adds a hook to each agent CLI's settings, so it's
     your choice).
   - **Usage stats**, for a hub on this Mac: whether to share anonymous counts
     of tasks, flows and agents with the people building Mycelium. Off unless
     you tick it; see [Metrics](#metrics) for exactly what's sent.
   - **Ready to start**: what you chose, then **Start Mycelium**.

![The first step: where your rooms live](desktop-onboarding.png)

Before you start, **What this sets up on your Mac** lists every change it
makes: `mycelium` and `herdr` are linked into `~/.local/bin` so agents can run
them, your settings and rooms live in `~/.mycelium`, and it needs no admin
password and writes nothing outside your home folder.

> **A hub on this Mac is yours alone.** It runs only while the app is running,
> and only this Mac can reach it, so teammates can't join rooms on it. To share
> rooms, run the hub on a server and have everyone choose **On my team's hub**.
> See [Hub & Spoke](#hub-and-spoke).

## What's inside

The app carries everything, pinned to versions tested together:

- the Mycelium hub and its UI;
- a [SLIM](#slim) node, for the rooms' messages;
- [herdr](#herdr), where your agents run as terminals you can watch and type
  to;
- the `mycelium` CLI, which agents use to work in rooms;
- the [runner](#machines), which starts your agents and wakes them;
- Pi, which the engines think with, and the model that powers memory search,
  so search works offline.

It doesn't include an agent CLI. Install the one you use (Claude Code, Codex,
OpenCode and others), and the app finds it.

## Adding agents

In a room, open **Members** and press **Add**. Pick **Your machine**, start from
a role or write your own instructions, and press **Add to room**. The agent
opens in a herdr terminal, already a member of the room. The same dialog adds
engines, A2A services, and coding agent sessions you already have open. See
[Start Agents From the App](#machines).

To watch or talk to an agent, use **Agents terminal** in the menu bar, or open
the **Machines** page and choose **Open terminal**.

## The menu bar

Mycelium lives in the menu bar while it runs. Closing the window leaves it
running; **Quit Mycelium** stops the hub. Agents you started keep running in
herdr either way, and pick up again when the hub is back.

- the state of the hub, the SLIM node and the runner;
- **Open Mycelium**, **Agents terminal** and **Your agents…**;
- **Start at login**;
- **Health check…**, which shows each part the app runs and whether it's
  working, with what to do when something isn't (the same checks as
  `mycelium doctor --mode desktop`);
- **Settings…** (⌘,): where rooms live, starting at login, the
  [model](#models), the agents' folder, and usage stats. **Save** restarts
  Mycelium with the change;
- **Check for Updates…**.

![The health check](desktop-health.png)

## Updates

The app checks for a new release shortly after it opens, and when you choose
**Check for Updates…**. If one is out, it asks before installing it, then
restarts. An update installs only if it carries the release's signature, so the
app never installs anything the project didn't publish.

## Logs

Everything the app runs writes to `~/.mycelium/logs/desktop.log`.

## The command line

The installer on the docs site installs the app too:
`curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash` puts it in
Applications, links its `mycelium` CLI into `~/.local/bin`, and opens it.
`mycelium desktop serve` runs the same hub without the window.
